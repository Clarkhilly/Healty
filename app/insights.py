"""Read-only data helpers exposed to the LLM as tools.

Each public function returns a dict of small, JSON-safe scalars / lists that
the model can quote back at the user. Everything is SELECT-only; the LLM can
never write to the DB.
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


# ─────────────────────────────────────────────
#  Public tools
# ─────────────────────────────────────────────
def overall_summary() -> dict:
    conn = get_connection()
    s = conn.execute(
        """
        SELECT COUNT(*) AS sessions,
               MIN(workout_date) AS first_date,
               MAX(workout_date) AS last_date,
               SUM(total_volume) AS volume,
               SUM(total_sets)   AS sets
        FROM sessions
        """
    ).fetchone()
    exercises = conn.execute("SELECT COUNT(DISTINCT exercise_title) AS n FROM sets").fetchone()
    conn.close()
    return {
        "first_date":      s["first_date"],
        "last_date":       s["last_date"],
        "total_sessions":  int(s["sessions"] or 0),
        "total_sets":      int(s["sets"] or 0),
        "total_volume_lb": _round(s["volume"], 0),
        "unique_exercises": int(exercises["n"] or 0),
    }


def schedule_summary(weeks: int = 4) -> dict:
    conn = get_connection()
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
        return {"weeks": weeks, "sessions": 0, "note": "No sessions in this window."}

    dates = sorted({r["workout_date"] for r in rows})
    day_counts = defaultdict(int)
    for r in rows:
        d = datetime.strptime(r["workout_date"], "%Y-%m-%d").date()
        day_counts[d.strftime("%a")] += 1
    durations = [r["duration_min"] for r in rows if r["duration_min"]]

    gaps = []
    for i in range(1, len(dates)):
        a = datetime.strptime(dates[i - 1], "%Y-%m-%d").date()
        b = datetime.strptime(dates[i], "%Y-%m-%d").date()
        gaps.append((b - a).days)

    return {
        "weeks": weeks,
        "window_start": dates[0],
        "window_end":   dates[-1],
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
    start = _window_start(conn, weeks)
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

    return {"weeks": weeks, "window_start": start, "groups": groups}


def exercise_progression(exercise: str, weeks: int = 12) -> dict:
    conn = get_connection()
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
        return {"exercise": exercise, "weeks": weeks, "sessions": 0, "note": "No data in window."}

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
        "exercise":   exercise,
        "weeks":      weeks,
        "muscle_group": muscle_group(exercise),
        "sessions":   len(sessions),
        "first":      first,
        "last":       last,
        "avg_weight_pct_change": pct_change,
        "trend":      sessions,
    }


def top_exercises(limit: int = 10, by: str = "sets") -> dict:
    conn = get_connection()
    order_col = "volume" if by == "volume" else "sets"
    rows = conn.execute(
        f"""
        SELECT exercise_title,
               COUNT(*)    AS sets,
               SUM(volume) AS volume,
               MAX(weight_lbs) AS max_weight
        FROM sets
        GROUP BY exercise_title
        ORDER BY {order_col} DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return {
        "by": by,
        "exercises": [
            {
                "exercise":     r["exercise_title"],
                "muscle_group": muscle_group(r["exercise_title"]),
                "sets":         int(r["sets"]),
                "volume_lb":    _round(r["volume"], 0),
                "max_weight_lb": _round(r["max_weight"], 1),
            }
            for r in rows
        ],
    }


def personal_records(limit: int = 10) -> dict:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT exercise_title,
               MAX(weight_lbs) AS max_weight,
               MAX(volume)     AS best_set_volume
        FROM sets
        WHERE weight_lbs IS NOT NULL AND reps IS NOT NULL
        GROUP BY exercise_title
        HAVING max_weight > 0
        ORDER BY max_weight DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return {
        "records": [
            {
                "exercise":     r["exercise_title"],
                "muscle_group": muscle_group(r["exercise_title"]),
                "max_weight_lb": _round(r["max_weight"], 1),
                "best_set_volume_lb": _round(r["best_set_volume"], 0),
            }
            for r in rows
        ]
    }


def recent_sessions(limit: int = 10) -> dict:
    conn = get_connection()
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
    end = _latest_workout_date(conn)
    mid = end - timedelta(weeks=period_weeks)
    start = end - timedelta(weeks=period_weeks * 2)

    def _stats(window_start, window_end):
        row = conn.execute(
            """
            SELECT COUNT(*) AS sessions,
                   SUM(total_volume) AS volume,
                   SUM(total_sets)   AS sets,
                   SUM(duration_min) AS minutes
            FROM sessions
            WHERE workout_date > ? AND workout_date <= ?
            """,
            (window_start.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d")),
        ).fetchone()
        return {
            "sessions": int(row["sessions"] or 0),
            "volume_lb": _round(row["volume"], 0),
            "sets":     int(row["sets"] or 0),
            "minutes":  _round(row["minutes"], 0),
        }

    recent = _stats(mid, end)
    prior  = _stats(start, mid)
    conn.close()

    def _delta(a, b):
        if not b: return None
        return _round(100 * (a - b) / b, 1)

    return {
        "period_weeks": period_weeks,
        "recent": {**recent, "window_end": end.strftime("%Y-%m-%d")},
        "prior":  {**prior,  "window_end": mid.strftime("%Y-%m-%d")},
        "deltas_pct": {
            "sessions": _delta(recent["sessions"], prior["sessions"]),
            "volume":   _delta(recent["volume_lb"] or 0, prior["volume_lb"] or 0),
            "sets":     _delta(recent["sets"], prior["sets"]),
            "minutes":  _delta(recent["minutes"] or 0, prior["minutes"] or 0),
        },
    }


def list_exercises() -> dict:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT exercise_title, COUNT(*) AS sets
        FROM sets
        GROUP BY exercise_title
        ORDER BY exercise_title
        """
    ).fetchall()
    conn.close()
    return {
        "exercises": [
            {
                "exercise":     r["exercise_title"],
                "muscle_group": muscle_group(r["exercise_title"]),
                "sets":         int(r["sets"]),
            }
            for r in rows
        ]
    }
