"""Aggregations for the dashboard: heatmap levels and year-in-review metrics."""

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from app.database import get_connection


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def heatmap(year: int | None = None) -> dict:
    conn = get_connection()
    if year:
        rows = _rows(
            conn,
            """
            SELECT workout_date, COUNT(DISTINCT session_key) AS sessions,
                   SUM(total_volume) AS volume
            FROM sessions
            WHERE workout_date LIKE ?
            GROUP BY workout_date
            ORDER BY workout_date
            """,
            (f"{year}-%",),
        )
    else:
        rows = _rows(
            conn,
            """
            SELECT workout_date, COUNT(DISTINCT session_key) AS sessions,
                   SUM(total_volume) AS volume
            FROM sessions
            GROUP BY workout_date
            ORDER BY workout_date
            """,
        )
    conn.close()

    if not rows:
        return {"year": year, "days": [], "max_volume": 0}

    max_vol = max(r["volume"] or 0 for r in rows)
    days = [
        {
            "date": r["workout_date"],
            "sessions": r["sessions"],
            "volume": round(r["volume"] or 0),
            "level": _heat_level(r["volume"] or 0, max_vol),
        }
        for r in rows
    ]
    return {"year": year, "days": days, "max_volume": round(max_vol)}


def _heat_level(volume: float, max_volume: float) -> int:
    if volume <= 0 or max_volume <= 0:
        return 1
    ratio = volume / max_volume
    if ratio < 0.25:
        return 1
    if ratio < 0.5:
        return 2
    if ratio < 0.75:
        return 3
    return 4


def year_in_review(year: int) -> dict:
    conn = get_connection()
    prefix = f"{year}-%"

    sessions = _rows(
        conn,
        """
        SELECT workout_date, title, duration_min,
               total_volume, total_sets, total_miles
        FROM sessions
        WHERE workout_date LIKE ?
        ORDER BY workout_date
        """,
        (prefix,),
    )
    if not sessions:
        conn.close()
        return {"year": year, "has_data": False}

    total_sets = 0
    total_volume = 0.0
    total_miles = 0.0
    total_minutes = 0.0
    by_month: dict[str, dict[str, float]] = defaultdict(lambda: {"sessions": 0, "volume": 0})
    title_counts: dict[str, int] = defaultdict(int)
    dates: list[str] = []
    for s in sessions:
        total_sets += s["total_sets"] or 0
        vol = s["total_volume"] or 0
        total_volume += vol
        total_miles += s["total_miles"] or 0
        total_minutes += s["duration_min"] or 0
        month = s["workout_date"][:7]
        by_month[month]["sessions"] += 1
        by_month[month]["volume"] += vol
        title_counts[s["title"]] += 1
        dates.append(s["workout_date"])

    total_sessions = len(sessions)
    busiest_month = max(by_month.items(), key=lambda x: x[1]["sessions"])

    exercise_sets = _rows(
        conn,
        """
        SELECT exercise_title, COUNT(*) AS set_count, SUM(volume) AS volume
        FROM sets
        WHERE workout_date LIKE ?
        GROUP BY exercise_title
        ORDER BY set_count DESC
        """,
        (prefix,),
    )

    top_exercise = exercise_sets[0] if exercise_sets else None

    prs = _rows(
        conn,
        """
        SELECT exercise_title,
               MAX(weight_lbs) AS max_weight,
               MAX(volume) AS max_set_volume
        FROM sets
        WHERE workout_date LIKE ? AND weight_lbs IS NOT NULL AND reps IS NOT NULL
        GROUP BY exercise_title
        HAVING max_weight > 0
        ORDER BY max_weight DESC
        LIMIT 8
        """,
        (prefix,),
    )

    favorite_time = max(title_counts.items(), key=lambda x: x[1])[0] if title_counts else None

    streak = _longest_streak(dates)

    conn.close()

    return {
        "year": year,
        "has_data": True,
        "total_sessions": total_sessions,
        "total_sets": total_sets,
        "total_volume_lbs": round(total_volume),
        "total_volume_tons": round(total_volume / 2000, 1),
        "total_miles": round(total_miles, 1),
        "total_hours": round(total_minutes / 60, 1),
        "busiest_month": {
            "month": busiest_month[0],
            "sessions": busiest_month[1]["sessions"],
        },
        "top_exercise": {
            "name": top_exercise["exercise_title"],
            "sets": top_exercise["set_count"],
        } if top_exercise else None,
        "favorite_workout_title": favorite_time,
        "longest_streak_days": streak,
        "personal_records": [
            {
                "exercise": p["exercise_title"],
                "max_weight_lbs": p["max_weight"],
                "best_set_volume": round(p["max_set_volume"] or 0),
            }
            for p in prs
        ],
        "months": [
            {"month": m, **by_month[m]}
            for m in sorted(by_month.keys())
        ],
    }


def _longest_streak(dates: list[str]) -> int:
    if not dates:
        return 0
    parsed = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in dates})
    best = cur = 1
    for prev, curr in zip(parsed, parsed[1:]):
        if (curr - prev) == timedelta(days=1):
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def available_years() -> list[int]:
    conn = get_connection()
    rows = _rows(
        conn,
        "SELECT DISTINCT substr(workout_date, 1, 4) AS y FROM sessions ORDER BY y",
    )
    conn.close()
    return [int(r["y"]) for r in rows]


def summary() -> dict:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT COUNT(*) AS sessions,
               MIN(workout_date) AS first_date,
               MAX(workout_date) AS last_date,
               SUM(total_volume) AS total_volume
        FROM sessions
        """
    ).fetchone()
    conn.close()
    return dict(row)
