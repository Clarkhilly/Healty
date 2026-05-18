"""Apple Health: streaming XML loader and idempotent SQLite import.

Apple's export is one big XML file (often 500MB+, 700k+ records). We use
`xml.etree.ElementTree.iterparse` so memory stays flat even on huge exports,
and `INSERT OR IGNORE` + `UNIQUE` constraints so re-running the loader is
safe — the user can drop a fresh `export.xml` and reload at any time.

Three tables get populated:
- `health_workouts`           — one row per <Workout>
- `health_metric_samples`     — per-sample weight / BMI / resting HR / HRV
- `health_daily`              — pre-aggregated daily sums of high-volume
                                metrics (steps, energy, distance, flights)

Records outside the tracked sets are skipped at load time so the DB never
grows unboundedly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from app.database import APPLE_HEALTH_XML_PATH, get_connection

# Apple prefixes every type/identifier with these.
_WORKOUT_PREFIX = "HKWorkoutActivityType"
_METRIC_PREFIX  = "HKQuantityTypeIdentifier"

# Cumulative metrics — sum to daily totals during load.
SUM_METRICS = {
    "StepCount",
    "DistanceWalkingRunning",
    "ActiveEnergyBurned",
    "BasalEnergyBurned",
    "FlightsClimbed",
}

# Instantaneous body / cardio-health metrics — keep per sample (low volume).
SAMPLE_METRICS = {
    "BodyMass",
    "BodyMassIndex",
    "RestingHeartRate",
    "HeartRateVariabilitySDNN",
}

# Apps that double-write strength workouts into Apple Health. Used by the
# insights layer to filter cardio / non-strength views; we still import
# their rows so the model can see them if asked.
STRENGTH_DUPLICATE_SOURCES = ("Hevy", "Strong", "Heavyset", "FitNotes")

_MI_PER_KM = 0.6213711922
_BATCH = 2000


def _strip(prefix: str, s: str) -> str:
    return s[len(prefix):] if s and s.startswith(prefix) else (s or "")


def _drop_tz(apple_dt: str | None) -> str | None:
    """`2025-03-02 20:42:57 -0700` -> `2025-03-02 20:42:57` (Apple writes local time)."""
    if not apple_dt:
        return None
    parts = apple_dt.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].startswith(("+", "-")) and parts[1][1:].isdigit():
        return parts[0]
    return apple_dt


def _date_of(apple_dt: str | None) -> str | None:
    if not apple_dt or len(apple_dt) < 10:
        return None
    return apple_dt[:10]


def _float_or_none(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _convert_distance(value: float, unit: str | None) -> float:
    if unit and unit.lower() == "km":
        return value * _MI_PER_KM
    return value  # default to miles


def load_apple_health(force_reload: bool = False) -> dict:
    """Stream-parse the export.xml and write to SQLite. Idempotent.

    If `force_reload=True`, wipes the three Apple Health tables first.
    Otherwise relies on UNIQUE constraints + INSERT OR IGNORE to skip
    rows we've already imported.
    """
    if not APPLE_HEALTH_XML_PATH.exists():
        return {"ok": False, "reason": f"missing {APPLE_HEALTH_XML_PATH}"}

    conn = get_connection()
    if force_reload:
        conn.execute("DELETE FROM health_workouts")
        conn.execute("DELETE FROM health_metric_samples")
        conn.execute("DELETE FROM health_daily")
        conn.commit()

    workout_buf: list[tuple] = []
    sample_buf: list[tuple]  = []
    # (metric, day) -> {"total": float, "samples": int}
    daily_acc: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"total": 0.0, "samples": 0}
    )

    records_seen = 0

    def flush() -> None:
        if workout_buf:
            conn.executemany(
                "INSERT OR IGNORE INTO health_workouts "
                "(activity_type, start_time, end_time, workout_date, "
                " duration_min, energy_kcal, distance_mi, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                workout_buf,
            )
            workout_buf.clear()
        if sample_buf:
            conn.executemany(
                "INSERT OR IGNORE INTO health_metric_samples "
                "(metric_type, sample_date, sample_time, value, unit, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                sample_buf,
            )
            sample_buf.clear()

    context = ET.iterparse(APPLE_HEALTH_XML_PATH, events=("start", "end"))
    _, root = next(context)  # grab the <HealthData> root so we can prune below

    for event, elem in context:
        if event != "end":
            continue

        tag = elem.tag

        if tag == "Workout":
            a = elem.attrib
            activity = _strip(_WORKOUT_PREFIX, a.get("workoutActivityType", ""))
            start    = _drop_tz(a.get("startDate"))
            end      = _drop_tz(a.get("endDate"))
            wdate    = _date_of(a.get("startDate"))
            if start and wdate:
                duration = _float_or_none(a.get("duration"))
                energy   = _float_or_none(a.get("totalEnergyBurned"))
                distance = _float_or_none(a.get("totalDistance"))
                if distance is not None:
                    distance = _convert_distance(distance, a.get("totalDistanceUnit"))
                source = a.get("sourceName") or "Unknown"
                workout_buf.append(
                    (activity, start, end, wdate, duration, energy, distance, source)
                )

        elif tag == "Record":
            records_seen += 1
            a = elem.attrib
            t = _strip(_METRIC_PREFIX, a.get("type", ""))
            if t in SUM_METRICS:
                day = _date_of(a.get("startDate"))
                v = _float_or_none(a.get("value"))
                if day and v is not None:
                    daily_acc[(t, day)]["total"]   += v
                    daily_acc[(t, day)]["samples"] += 1
            elif t in SAMPLE_METRICS:
                sample_time = _drop_tz(a.get("startDate"))
                day         = _date_of(a.get("startDate"))
                v           = _float_or_none(a.get("value"))
                if sample_time and day and v is not None:
                    sample_buf.append((
                        t, day, sample_time, v,
                        a.get("unit"), a.get("sourceName") or "Unknown",
                    ))
            # Records we don't care about are dropped here.

        # Memory hygiene: clear the just-finished element and detach all
        # accumulated children from the root, so the parser doesn't keep
        # growing a tree of empty <Record/> placeholders.
        elem.clear()
        del root[:]

        if len(workout_buf) >= _BATCH or len(sample_buf) >= _BATCH:
            flush()

    flush()

    # Daily aggregates: one upsert per (metric, day). UPSERT lets us re-run
    # safely while overwriting any prior daily row for the same key.
    if daily_acc:
        conn.executemany(
            "INSERT INTO health_daily (metric_type, day, total, samples) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(metric_type, day) DO UPDATE SET "
            "  total = excluded.total, samples = excluded.samples",
            [
                (m, d, v["total"], int(v["samples"]))
                for (m, d), v in daily_acc.items()
            ],
        )

    conn.commit()

    # Post-load counts (real values, not the per-batch approximation).
    workouts_total = conn.execute("SELECT COUNT(*) FROM health_workouts").fetchone()[0]
    samples_total  = conn.execute("SELECT COUNT(*) FROM health_metric_samples").fetchone()[0]
    daily_total    = conn.execute("SELECT COUNT(*) FROM health_daily").fetchone()[0]
    conn.close()

    return {
        "ok": True,
        "xml_path": str(APPLE_HEALTH_XML_PATH),
        "records_seen": records_seen,
        "workouts_rows": int(workouts_total),
        "metric_sample_rows": int(samples_total),
        "daily_rows": int(daily_total),
    }


def summary_payload() -> dict:
    """Quick read-only snapshot for the dashboard panel."""
    conn = get_connection()

    span = conn.execute(
        "SELECT MIN(workout_date) AS a, MAX(workout_date) AS b FROM health_workouts"
    ).fetchone()

    workouts_total = conn.execute("SELECT COUNT(*) FROM health_workouts").fetchone()[0]

    placeholders = ",".join("?" * len(STRENGTH_DUPLICATE_SOURCES))
    non_strength = conn.execute(
        f"SELECT COUNT(*) FROM health_workouts WHERE source NOT IN ({placeholders})",
        STRENGTH_DUPLICATE_SOURCES,
    ).fetchone()[0]

    latest_weight = conn.execute(
        "SELECT sample_date, value, unit FROM health_metric_samples "
        "WHERE metric_type = 'BodyMass' "
        "ORDER BY sample_time DESC LIMIT 1"
    ).fetchone()

    latest_rhr = conn.execute(
        "SELECT sample_date, value FROM health_metric_samples "
        "WHERE metric_type = 'RestingHeartRate' "
        "ORDER BY sample_time DESC LIMIT 1"
    ).fetchone()

    latest_hrv = conn.execute(
        "SELECT sample_date, value FROM health_metric_samples "
        "WHERE metric_type = 'HeartRateVariabilitySDNN' "
        "ORDER BY sample_time DESC LIMIT 1"
    ).fetchone()

    # Average daily steps / active kcal across the most recent 28 days that
    # actually have data — avoids dragging the average down with empty days.
    daily_steps = conn.execute(
        "SELECT total FROM health_daily WHERE metric_type = 'StepCount' "
        "ORDER BY day DESC LIMIT 28"
    ).fetchall()
    daily_active = conn.execute(
        "SELECT total FROM health_daily WHERE metric_type = 'ActiveEnergyBurned' "
        "ORDER BY day DESC LIMIT 28"
    ).fetchall()

    weight_trend = conn.execute(
        "SELECT sample_date, value FROM health_metric_samples "
        "WHERE metric_type = 'BodyMass' "
        "ORDER BY sample_time DESC LIMIT 60"
    ).fetchall()

    conn.close()

    def _avg(rows):
        if not rows:
            return None
        return round(sum(r["total"] for r in rows) / len(rows), 1)

    return {
        "loaded":            workouts_total > 0 or bool(latest_weight or latest_rhr),
        "xml_present":       APPLE_HEALTH_XML_PATH.exists(),
        "xml_path":          str(APPLE_HEALTH_XML_PATH),
        "first_workout_date": span["a"] if span else None,
        "last_workout_date":  span["b"] if span else None,
        "workouts_total":    int(workouts_total),
        "non_strength_workouts": int(non_strength),
        "latest_weight": (
            {
                "value": round(latest_weight["value"], 1),
                "unit":  latest_weight["unit"],
                "date":  latest_weight["sample_date"],
            }
            if latest_weight else None
        ),
        "latest_resting_hr": (
            {"value": round(latest_rhr["value"], 0), "date": latest_rhr["sample_date"]}
            if latest_rhr else None
        ),
        "latest_hrv_sdnn_ms": (
            {"value": round(latest_hrv["value"], 1), "date": latest_hrv["sample_date"]}
            if latest_hrv else None
        ),
        "avg_steps_last_28d":       _avg(daily_steps),
        "avg_active_kcal_last_28d": _avg(daily_active),
        "weight_trend": [
            {"date": r["sample_date"], "value": round(r["value"], 1)}
            for r in reversed(weight_trend)  # chronological for charting
        ],
    }
