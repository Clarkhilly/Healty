"""Read-only data helpers exposed to the LLM as tools.

Each public function returns a dict of small, JSON-safe scalars / lists that
the model can quote back at the user. Everything is SELECT-only; the LLM can
never write to the DB.

Every payload includes log_first_date / log_last_date (ISO YYYY-MM-DD from
sessions, or null if empty) so answers anchor on exact log dates, not the
real-world calendar.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from app.database import get_connection

# ─────────────────────────────────────────────
#  Muscle-group mapping
# ─────────────────────────────────────────────
EXERCISE_GROUP = {
    "Behind the Back Bicep Wrist Curl (Barbell)": "biceps",
    "Bicep Curl (Barbell)":                       "biceps",
    "Bicep Curl (Cable)":                         "biceps",
    "Concentration Curl":                         "biceps",
    "Hammer Curl (Dumbbell)":                     "biceps",
    "Preacher Curl (Barbell)":                    "biceps",
    "Preacher Curl (Dumbbell)":                   "biceps",
    "Seated Incline Curl (Dumbbell)":             "biceps",
    "Seated Palms Up Wrist Curl":                 "biceps",

    "Cable Fly Crossovers":                       "chest",
    "Chest Dip":                                  "chest",
    "Chest Dip (Assisted)":                       "chest",
    "Chest Fly (Machine)":                        "chest",
    "Chest Press (Machine)":                      "chest",
    "Incline Bench Press (Dumbbell)":             "chest",
    "Push Up":                                    "chest",

    "Dumbbell Row":                               "back",
    "Landmine Row":                               "back",
    "Lat Pulldown (Cable)":                       "back",
    "Rope Straight Arm Pulldown":                 "back",
    "Shrug (Dumbbell)":                           "back",

    "Lateral Raise (Dumbbell)":                   "shoulders",
    "Plate Front Raise":                          "shoulders",
    "Rear Delt Reverse Fly (Dumbbell)":           "shoulders",
    "Rear Delt Reverse Fly (Machine)":            "shoulders",
    "Seated Shoulder Press (Machine)":            "shoulders",
    "Shoulder Press (Dumbbell)":                  "shoulders",
    "Single Arm Lateral Raise (Cable)":           "shoulders",

    "Overhead Triceps Extension (Cable)":         "triceps",
    "Skullcrusher (Dumbbell)":                    "triceps",
    "Triceps Extension (Dumbbell)":               "triceps",
    "Triceps Pushdown":                           "triceps",
    "Triceps Rope Pushdown":                      "triceps",

    "Bulgarian Split Squat":                      "legs",
    "Leg Extension (Machine)":                    "legs",
    "Leg Press Horizontal (Machine)":             "legs",
    "Lunge (Dumbbell)":                           "legs",
    "Seated Leg Curl (Machine)":                  "legs",
    "Squat (Barbell)":                            "legs",
    "Wall Sit":                                   "legs",

    "Standing Calf Raise (Dumbbell)":             "calves",

    "Crunch (Machine)":                           "core",
    "Crunch (Weighted)":                          "core",

    "Cycling":                                    "cardio",
    "Stair Machine (Steps)":                      "cardio",
    "Treadmill":                                  "cardio",
}


def muscle_group(exercise: str) -> str:
    return EXERCISE_GROUP.get(exercise, "other")


def _latest_workout_date(conn) -> date:
    row = conn.execute("SELECT MAX(workout_date) AS d FROM sessions").fetchone()
    return datetime.strptime(row["d"], "%Y-%m-%d").date() if row and row["d"] else date.today()


def _window_start(conn, weeks: int) -> str:
    end = _latest_workout_date(conn)
    return (end - timedelta(weeks=weeks)).strftime("%Y-%m-%d")


def _round(x, n=1):
    return None if x is None else round(float(x), n)


def _log_span(conn) -> dict[str, str | None]:
    row = conn.execute(
        "SELECT MIN(workout_date) AS a, MAX(workout_date) AS b FROM sessions",
    ).fetchone()
    if not row or row["a"] is None:
        return {"log_first_date": None, "log_last_date": None}
    return {"log_first_date": row["a"], "log_last_date": row["b"]}


# ─────────────────────────────────────────────
#  Public tools
# ─────────────────────────────────────────────
def overall_summary() -> dict:
    conn = get_connection()
    span = _log_span(conn)
    s = conn.execute(
        """
        SELECT COUNT(*) AS sessions,
               SUM(total_volume) AS volume,
               SUM(total_sets)   AS sets
        FROM sessions
        """
    ).fetchone()
    exercises = conn.execute("SELECT COUNT(DISTINCT exercise_title) AS n FROM sets").fetchone()
    conn.close()
    return {
        **span,
        "total_sessions":  int(s["sessions"] or 0),
        "total_sets":      int(s["sets"] or 0),
        "total_volume_lb": _round(s["volume"], 0),
        "unique_exercises": int(exercises["n"] or 0),
    }


def schedule_summary(weeks: int = 4) -> dict:
    conn = get_connection()
    span = _log_span(conn)
    start = _window_start(conn, weeks)
    rows = conn.execute(
        """
        SELECT workout_date, duration_min
        FROM sessions
        WHERE workout_date >= ?
        ORDER BY workout_date
        """,
        (start,),
    ).fetchall()
    conn.close()

    if not rows:
        return {
            **span,
            "weeks": weeks,
            "window_filter_from_date": start,
            "sessions": 0,
            "note": "No sessions in this window.",
        }

    parsed = [datetime.strptime(r["workout_date"], "%Y-%m-%d").date() for r in rows]
    unique_dates = sorted(set(parsed))

    day_counts: dict[str, int] = defaultdict(int)
    for d in parsed:
        day_counts[d.strftime("%a")] += 1

    durations = [r["duration_min"] for r in rows if r["duration_min"]]

    gaps = [(b - a).days for a, b in zip(unique_dates, unique_dates[1:])]

    return {
        **span,
        "weeks": weeks,
        "window_filter_from_date": start,
        "window_start_date": unique_dates[0].strftime("%Y-%m-%d"),
        "window_end_date": unique_dates[-1].strftime("%Y-%m-%d"),
        "sessions":     len(rows),
        "sessions_per_week": _round(len(rows) / max(weeks, 1), 2),
        "avg_rest_days_between": _round(sum(gaps) / len(gaps), 1) if gaps else None,
        "longest_rest_days":     max(gaps) if gaps else 0,
        "avg_duration_min":      _round(sum(durations) / len(durations), 1) if durations else None,
        "by_day_of_week": {
            d: day_counts.get(d, 0)
            for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        },
    }


def muscle_group_volume(weeks: int = 4) -> dict:
    conn = get_connection()
    span = _log_span(conn)
    start = _window_start(conn, weeks)
    window_end_row = conn.execute(
        "SELECT MAX(workout_date) AS d FROM sets WHERE workout_date >= ?",
        (start,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT exercise_title, COUNT(*) AS sets, SUM(volume) AS volume
        FROM sets
        WHERE workout_date >= ?
        GROUP BY exercise_title
        """,
        (start,),
    ).fetchall()
    conn.close()

    grouped = defaultdict(lambda: {"sets": 0, "volume_lb": 0.0, "exercises": set()})
    for r in rows:
        g = muscle_group(r["exercise_title"])
        grouped[g]["sets"]      += int(r["sets"])
        grouped[g]["volume_lb"] += float(r["volume"] or 0)
        grouped[g]["exercises"].add(r["exercise_title"])

    total_sets   = sum(v["sets"] for v in grouped.values()) or 1
    total_volume = sum(v["volume_lb"] for v in grouped.values()) or 1.0

    groups = []
    for name, v in grouped.items():
        groups.append({
            "group":            name,
            "sets":             v["sets"],
            "volume_lb":        _round(v["volume_lb"], 0),
            "share_of_sets_pct":   _round(100 * v["sets"] / total_sets, 1),
            "share_of_volume_pct": _round(100 * v["volume_lb"] / total_volume, 1),
            "exercises_used":   sorted(v["exercises"]),
        })
    groups.sort(key=lambda g: g["volume_lb"] or 0, reverse=True)

    return {
        **span,
        "weeks": weeks,
        "window_start_date": start,
        "window_end_date": window_end_row["d"],
        "groups": groups,
    }


def exercise_progression(exercise: str, weeks: int = 12) -> dict:
    conn = get_connection()
    span = _log_span(conn)
    start = _window_start(conn, weeks)
    rows = conn.execute(
        """
        SELECT workout_date,
               AVG(weight_lbs) AS avg_weight,
               AVG(reps)       AS avg_reps,
               MAX(weight_lbs) AS max_weight,
               COUNT(*)        AS sets,
               SUM(volume)     AS volume
        FROM sets
        WHERE exercise_title = ? AND workout_date >= ?
        GROUP BY workout_date
        ORDER BY workout_date
        """,
        (exercise, start),
    ).fetchall()
    conn.close()

    if not rows:
        return {
            **span,
            "exercise": exercise,
            "weeks": weeks,
            "window_start_date": start,
            "window_end_date": None,
            "sessions": 0,
            "note": "No data in window.",
        }

    sessions = [
        {
            "date":       r["workout_date"],
            "avg_weight": _round(r["avg_weight"], 1),
            "avg_reps":   _round(r["avg_reps"], 1),
            "max_weight": _round(r["max_weight"], 1),
            "sets":       int(r["sets"]),
            "volume_lb":  _round(r["volume"], 0),
        }
        for r in rows
    ]

    first, last = sessions[0], sessions[-1]
    pct_change = (
        None if not first["avg_weight"]
        else _round(100 * (last["avg_weight"] - first["avg_weight"]) / first["avg_weight"], 1)
    )

    return {
        **span,
        "exercise":   exercise,
        "weeks":      weeks,
        "muscle_group": muscle_group(exercise),
        "window_start_date": start,
        "window_end_date": last["date"],
        "sessions":   len(sessions),
        "first":      first,
        "last":       last,
        "avg_weight_pct_change": pct_change,
        "trend":      sessions,
    }


def top_exercises(limit: int = 10, by: str = "sets") -> dict:
    conn = get_connection()
    span = _log_span(conn)
    order_col = "volume" if by == "volume" else "sets"
    rows = conn.execute(
        f"""
        SELECT exercise_title,
               COUNT(*)    AS sets,
               SUM(volume) AS volume,
               MAX(weight_lbs) AS max_weight,
               MAX(workout_date) AS last_workout_date
        FROM sets
        GROUP BY exercise_title
        ORDER BY {order_col} DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return {
        **span,
        "by": by,
        "exercises": [
            {
                "exercise":     r["exercise_title"],
                "muscle_group": muscle_group(r["exercise_title"]),
                "sets":         int(r["sets"]),
                "volume_lb":    _round(r["volume"], 0),
                "max_weight_lb": _round(r["max_weight"], 1),
                "last_workout_date": r["last_workout_date"],
            }
            for r in rows
        ],
    }


def personal_records(limit: int = 10) -> dict:
    conn = get_connection()
    span = _log_span(conn)
    rows = conn.execute(
        """
        SELECT x.exercise_title AS exercise_title,
               x.max_weight AS max_weight,
               x.best_set_volume AS best_set_volume,
               (
                 SELECT workout_date FROM sets y
                 WHERE y.exercise_title = x.exercise_title
                   AND y.weight_lbs = x.max_weight
                   AND y.reps IS NOT NULL
                   AND y.weight_lbs IS NOT NULL
                 ORDER BY workout_date DESC
                 LIMIT 1
               ) AS achieved_on
        FROM (
          SELECT exercise_title,
                 MAX(weight_lbs) AS max_weight,
                 MAX(volume) AS best_set_volume
          FROM sets
          WHERE weight_lbs IS NOT NULL AND reps IS NOT NULL
          GROUP BY exercise_title
          HAVING max_weight > 0
        ) AS x
        ORDER BY x.max_weight DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return {
        **span,
        "records": [
            {
                "exercise":     r["exercise_title"],
                "muscle_group": muscle_group(r["exercise_title"]),
                "max_weight_lb": _round(r["max_weight"], 1),
                "best_set_volume_lb": _round(r["best_set_volume"], 0),
                "achieved_on": r["achieved_on"],
            }
            for r in rows
        ],
    }


def recent_sessions(limit: int = 10) -> dict:
    conn = get_connection()
    span = _log_span(conn)
    rows = conn.execute(
        """
        SELECT workout_date, title, duration_min, total_volume, total_sets, exercise_count
        FROM sessions
        ORDER BY workout_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return {
        **span,
        "sessions": [
            {
                "date":     r["workout_date"],
                "title":    r["title"],
                "duration_min":   _round(r["duration_min"], 1),
                "total_volume_lb": _round(r["total_volume"], 0),
                "total_sets":     int(r["total_sets"]),
                "exercise_count": int(r["exercise_count"]),
            }
            for r in rows
        ]
    }


def compare_periods(period_weeks: int = 4) -> dict:
    conn = get_connection()
    span = _log_span(conn)
    end = _latest_workout_date(conn)
    mid = end - timedelta(weeks=period_weeks)
    start = end - timedelta(weeks=period_weeks * 2)

    start_s = start.strftime("%Y-%m-%d")
    mid_s   = mid.strftime("%Y-%m-%d")
    end_s   = end.strftime("%Y-%m-%d")

    # One pass over the union of both windows; CASE buckets each row into
    # `recent` (mid, end] or `prior` (start, mid]. Saves three round-trips
    # vs. the previous "two _stats() calls × (aggregate + bounds)" shape.
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN workout_date >  :mid   AND workout_date <= :end THEN 1            ELSE 0 END) AS r_sessions,
          SUM(CASE WHEN workout_date >  :mid   AND workout_date <= :end THEN total_volume ELSE 0 END) AS r_volume,
          SUM(CASE WHEN workout_date >  :mid   AND workout_date <= :end THEN total_sets   ELSE 0 END) AS r_sets,
          SUM(CASE WHEN workout_date >  :mid   AND workout_date <= :end THEN duration_min ELSE 0 END) AS r_minutes,
          MIN(CASE WHEN workout_date >  :mid   AND workout_date <= :end THEN workout_date END)        AS r_first,
          MAX(CASE WHEN workout_date >  :mid   AND workout_date <= :end THEN workout_date END)        AS r_last,
          SUM(CASE WHEN workout_date >  :start AND workout_date <= :mid THEN 1            ELSE 0 END) AS p_sessions,
          SUM(CASE WHEN workout_date >  :start AND workout_date <= :mid THEN total_volume ELSE 0 END) AS p_volume,
          SUM(CASE WHEN workout_date >  :start AND workout_date <= :mid THEN total_sets   ELSE 0 END) AS p_sets,
          SUM(CASE WHEN workout_date >  :start AND workout_date <= :mid THEN duration_min ELSE 0 END) AS p_minutes,
          MIN(CASE WHEN workout_date >  :start AND workout_date <= :mid THEN workout_date END)        AS p_first,
          MAX(CASE WHEN workout_date >  :start AND workout_date <= :mid THEN workout_date END)        AS p_last
        FROM sessions
        WHERE workout_date > :start AND workout_date <= :end
        """,
        {"start": start_s, "mid": mid_s, "end": end_s},
    ).fetchone()
    conn.close()

    def _bucket(prefix: str) -> dict:
        return {
            "sessions":  int(row[f"{prefix}_sessions"] or 0),
            "volume_lb": _round(row[f"{prefix}_volume"], 0),
            "sets":      int(row[f"{prefix}_sets"] or 0),
            "minutes":   _round(row[f"{prefix}_minutes"], 0),
            "window_first_date": row[f"{prefix}_first"],
            "window_last_date":  row[f"{prefix}_last"],
        }

    recent = _bucket("r")
    prior  = _bucket("p")

    def _delta(a, b):
        if not b: return None
        return _round(100 * (a - b) / b, 1)

    return {
        **span,
        "period_weeks": period_weeks,
        "split_on_date": mid_s,
        "recent": recent,
        "prior": prior,
        "deltas_pct": {
            "sessions": _delta(recent["sessions"], prior["sessions"]),
            "volume":   _delta(recent["volume_lb"] or 0, prior["volume_lb"] or 0),
            "sets":     _delta(recent["sets"], prior["sets"]),
            "minutes":  _delta(recent["minutes"] or 0, prior["minutes"] or 0),
        },
    }


def stall_report(weeks: int = 8, min_sessions: int = 4) -> dict:
    """Classify working lifts in the last N weeks as stalled or progressing.

    A lift counts as *stalled* if:
      - it has ≥ min_sessions sessions in the window,
      - its peak max weight in the second half of the window does NOT exceed
        the peak in the first half (no new heavy-set PR), AND
      - the per-session slope of average working weight is ≤ 0 (no upward
        drift in working weights either).

    A lift counts as *progressing* if last_max > first_max and the avg-weight
    slope is positive. Anything else is omitted (too few data points / mixed
    signal).
    """
    conn = get_connection()
    span = _log_span(conn)
    start = _window_start(conn, weeks)
    rows = conn.execute(
        """
        SELECT exercise_title,
               workout_date,
               AVG(weight_lbs) AS avg_weight,
               MAX(weight_lbs) AS max_weight,
               COUNT(*)        AS sets
        FROM sets
        WHERE workout_date >= ?
          AND weight_lbs IS NOT NULL
          AND reps IS NOT NULL
          AND weight_lbs > 0
        GROUP BY exercise_title, workout_date
        ORDER BY exercise_title, workout_date
        """,
        (start,),
    ).fetchall()
    conn.close()

    by_lift: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_lift[r["exercise_title"]].append({
            "date":       r["workout_date"],
            "avg_weight": float(r["avg_weight"] or 0),
            "max_weight": float(r["max_weight"] or 0),
            "sets":       int(r["sets"]),
        })

    stalled: list[dict] = []
    progressing: list[dict] = []

    for name, sessions in by_lift.items():
        if len(sessions) < min_sessions:
            continue
        maxes = [s["max_weight"] for s in sessions]
        avgs  = [s["avg_weight"] for s in sessions]
        first_max, last_max = maxes[0], maxes[-1]
        peak_max = max(maxes)

        half = len(maxes) // 2 or 1
        first_half_peak = max(maxes[:half])
        second_half_peak = max(maxes[half:])

        slope = (avgs[-1] - avgs[0]) / max(len(avgs) - 1, 1)
        slope_threshold = 0.05 * (first_max or 1)
        peak_change_pct = (
            _round(100 * (last_max - first_max) / first_max, 1) if first_max else None
        )

        is_stalled     = second_half_peak <= first_half_peak and slope <= slope_threshold
        is_progressing = last_max > first_max and slope > 0

        entry = {
            "exercise":         name,
            "muscle_group":     muscle_group(name),
            "sessions":         len(sessions),
            "first_date":       sessions[0]["date"],
            "last_date":        sessions[-1]["date"],
            "first_max_weight": _round(first_max, 1),
            "last_max_weight":  _round(last_max, 1),
            "peak_max_weight":  _round(peak_max, 1),
            "avg_weight_slope_per_session": _round(slope, 3),
            "peak_change_pct":  peak_change_pct,
        }
        if is_stalled:
            stalled.append(entry)
        elif is_progressing:
            progressing.append(entry)

    stalled.sort(key=lambda x: x["sessions"], reverse=True)
    progressing.sort(key=lambda x: (x["peak_change_pct"] or 0), reverse=True)

    return {
        **span,
        "weeks":              weeks,
        "window_start_date":  start,
        "min_sessions":       min_sessions,
        "stalled_count":      len(stalled),
        "stalled":            stalled,
        "progressing_count":  len(progressing),
        "progressing":        progressing[:10],
    }


def list_exercises() -> dict:
    conn = get_connection()
    span = _log_span(conn)
    rows = conn.execute(
        """
        SELECT exercise_title, COUNT(*) AS sets, MAX(workout_date) AS last_workout_date
        FROM sets
        GROUP BY exercise_title
        ORDER BY exercise_title
        """
    ).fetchall()
    conn.close()
    return {
        **span,
        "exercises": [
            {
                "exercise":     r["exercise_title"],
                "muscle_group": muscle_group(r["exercise_title"]),
                "sets":         int(r["sets"]),
                "last_workout_date": r["last_workout_date"],
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────────
#  Apple Health tools (separate source: device-recorded data)
# ─────────────────────────────────────────────
# Sources known to double-write strength sessions into Apple Health.
# We import their rows so the model can still see them if asked, but the
# default cardio / non-lifting views filter them out to avoid duplicate
# counting against the Hevy `sessions` table.
_STRENGTH_DUPLICATE_SOURCES = ("Hevy", "Strong", "Heavyset", "FitNotes")

_BODY_METRICS = ("BodyMass", "BodyMassIndex", "RestingHeartRate", "HeartRateVariabilitySDNN")


def _health_span(conn) -> dict[str, str | None]:
    row = conn.execute(
        "SELECT MIN(workout_date) AS a, MAX(workout_date) AS b FROM health_workouts",
    ).fetchone()
    if row and row["a"]:
        return {"health_first_date": row["a"], "health_last_date": row["b"]}
    return {"health_first_date": None, "health_last_date": None}


def _latest_health_workout_date(conn) -> date | None:
    row = conn.execute("SELECT MAX(workout_date) AS d FROM health_workouts").fetchone()
    if row and row["d"]:
        return datetime.strptime(row["d"], "%Y-%m-%d").date()
    return None


def cardio_summary(weeks: int = 4) -> dict:
    """Apple Health workouts (cardio + 'Other') in the last N weeks, EXCLUDING
    strength workouts that Hevy / Strong / etc. duplicated into Apple Health.
    """
    conn = get_connection()
    log    = _log_span(conn)
    health = _health_span(conn)
    end = _latest_health_workout_date(conn)
    if end is None:
        conn.close()
        return {
            **log, **health, "weeks": weeks, "sessions": 0,
            "note": "No Apple Health workouts loaded yet.",
        }

    start = end - timedelta(weeks=weeks)
    placeholders = ",".join("?" * len(_STRENGTH_DUPLICATE_SOURCES))
    rows = conn.execute(
        f"""
        SELECT workout_date, activity_type, duration_min, energy_kcal, distance_mi, source
        FROM health_workouts
        WHERE workout_date >= ? AND source NOT IN ({placeholders})
        ORDER BY workout_date DESC, start_time DESC
        """,
        (start.strftime("%Y-%m-%d"), *_STRENGTH_DUPLICATE_SOURCES),
    ).fetchall()
    conn.close()

    total_min  = sum((r["duration_min"] or 0) for r in rows)
    total_kcal = sum((r["energy_kcal"]  or 0) for r in rows)
    total_mi   = sum((r["distance_mi"]  or 0) for r in rows)
    return {
        **log,
        **health,
        "weeks": weeks,
        "window_start_date": start.strftime("%Y-%m-%d"),
        "window_end_date":   end.strftime("%Y-%m-%d"),
        "excluded_sources": list(_STRENGTH_DUPLICATE_SOURCES),
        "sessions": len(rows),
        "total_duration_min":  _round(total_min, 0),
        "total_energy_kcal":   _round(total_kcal, 0),
        "total_distance_mi":   _round(total_mi, 1),
        "sessions_list": [
            {
                "date":         r["workout_date"],
                "activity":     r["activity_type"],
                "duration_min": _round(r["duration_min"], 1),
                "energy_kcal":  _round(r["energy_kcal"], 0),
                "distance_mi":  _round(r["distance_mi"], 1),
                "source":       r["source"],
            }
            for r in rows[:25]
        ],
    }


def body_metric_trend(metric: str = "BodyMass", weeks: int = 12) -> dict:
    """Trend of one body / cardio-health metric over the last N weeks.
    Allowed metrics: BodyMass, BodyMassIndex, RestingHeartRate, HeartRateVariabilitySDNN.
    """
    if metric not in _BODY_METRICS:
        return {
            "error": f"unknown metric '{metric}'",
            "allowed": list(_BODY_METRICS),
        }
    conn = get_connection()
    log = _log_span(conn)
    span_row = conn.execute(
        "SELECT MIN(sample_date) AS a, MAX(sample_date) AS b "
        "FROM health_metric_samples WHERE metric_type = ?",
        (metric,),
    ).fetchone()
    if not span_row or not span_row["a"]:
        conn.close()
        return {**log, "metric": metric, "samples": 0,
                "note": f"No {metric} samples in Apple Health data."}

    end   = datetime.strptime(span_row["b"], "%Y-%m-%d").date()
    start = end - timedelta(weeks=weeks)
    rows = conn.execute(
        """
        SELECT sample_date, sample_time, value, unit
        FROM health_metric_samples
        WHERE metric_type = ? AND sample_date >= ?
        ORDER BY sample_time
        """,
        (metric, start.strftime("%Y-%m-%d")),
    ).fetchall()
    conn.close()

    if not rows:
        return {**log, "metric": metric, "samples": 0,
                "window_start_date": start.strftime("%Y-%m-%d"),
                "window_end_date":   end.strftime("%Y-%m-%d"),
                "note": "No samples in window."}

    values = [r["value"] for r in rows]
    first_v, last_v = values[0], values[-1]
    pct_change = None if not first_v else _round(100 * (last_v - first_v) / first_v, 1)

    return {
        **log,
        "metric": metric,
        "unit":   rows[0]["unit"],
        "weeks":  weeks,
        "window_start_date": start.strftime("%Y-%m-%d"),
        "window_end_date":   end.strftime("%Y-%m-%d"),
        "samples":     len(rows),
        "first_value": _round(first_v, 2),
        "last_value":  _round(last_v, 2),
        "min_value":   _round(min(values), 2),
        "max_value":   _round(max(values), 2),
        "avg_value":   _round(sum(values) / len(values), 2),
        "pct_change":  pct_change,
        "trend": [
            {"date": r["sample_date"], "value": _round(r["value"], 2)}
            for r in rows[-60:]
        ],
    }


def daily_activity(weeks: int = 4) -> dict:
    """Daily steps, active/basal kcal, walking miles, flights climbed from
    Apple Health, averaged over the last N weeks."""
    conn = get_connection()
    log = _log_span(conn)
    end_row = conn.execute(
        "SELECT MAX(day) AS d FROM health_daily "
        "WHERE metric_type IN ('StepCount','ActiveEnergyBurned','DistanceWalkingRunning')"
    ).fetchone()
    if not end_row or not end_row["d"]:
        conn.close()
        return {**log, "weeks": weeks, "days": 0,
                "note": "No daily Apple Health activity rows loaded yet."}

    end   = datetime.strptime(end_row["d"], "%Y-%m-%d").date()
    start = end - timedelta(weeks=weeks)
    rows = conn.execute(
        """
        SELECT day, metric_type, total
        FROM health_daily
        WHERE day >= ?
          AND metric_type IN ('StepCount','ActiveEnergyBurned',
                              'DistanceWalkingRunning','BasalEnergyBurned',
                              'FlightsClimbed')
        ORDER BY day
        """,
        (start.strftime("%Y-%m-%d"),),
    ).fetchall()
    conn.close()

    by_day: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_day[r["day"]][r["metric_type"]] = r["total"]
    days = sorted(by_day.keys())

    def _avg(metric: str) -> float | None:
        values = [by_day[d].get(metric) for d in days if by_day[d].get(metric) is not None]
        return _round(sum(values) / len(values), 1) if values else None

    return {
        **log,
        "weeks": weeks,
        "window_start_date": start.strftime("%Y-%m-%d"),
        "window_end_date":   end.strftime("%Y-%m-%d"),
        "days": len(days),
        "avg_steps_per_day":         _avg("StepCount"),
        "avg_active_kcal_per_day":   _avg("ActiveEnergyBurned"),
        "avg_basal_kcal_per_day":    _avg("BasalEnergyBurned"),
        "avg_distance_mi_per_day":   _avg("DistanceWalkingRunning"),
        "avg_flights_per_day":       _avg("FlightsClimbed"),
        "trend": [
            {
                "date":        d,
                "steps":       int(by_day[d].get("StepCount") or 0),
                "active_kcal": _round(by_day[d].get("ActiveEnergyBurned"), 0),
                "distance_mi": _round(by_day[d].get("DistanceWalkingRunning"), 1),
                "basal_kcal":  _round(by_day[d].get("BasalEnergyBurned"), 0),
                "flights":     int(by_day[d].get("FlightsClimbed") or 0),
            }
            for d in days
        ],
    }
