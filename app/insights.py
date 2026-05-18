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
