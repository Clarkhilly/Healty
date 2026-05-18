"""Planned future workouts — the LLM's only *write* tools.

`schedule_workout` is what turns this app from "analytics over past data" into
an actual coaching loop: the model proposes a program and writes it to the
`planned_workouts` table, where the dashboard surfaces upcoming sessions.

All other LLM tools remain read-only against Hevy + Apple Health data.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from app.database import get_connection


# ─────────────────────────────────────────────
#  Write tools
# ─────────────────────────────────────────────
def schedule_workout(
    date: str,
    title: str,
    exercises: list[Any],
    notes: str = "",
) -> dict[str, Any]:
    """Insert or replace a planned workout for one date.

    Args:
        date:      ISO YYYY-MM-DD.
        title:     Session title (e.g. "Push A", "Lower Heavy").
        exercises: Either a list of strings (exercise names) OR a list of dicts
                   with keys: name (required), sets, reps, weight_lbs, notes.
        notes:     Optional session-level note (e.g. "deload", "RPE 7 cap").

    UPSERTs on (planned_date, title) so the model can re-plan idempotently.
    """
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return {"error": f"date must be YYYY-MM-DD, got {date!r}"}

    t = (title or "").strip()
    if not t:
        return {"error": "title is required"}

    if not isinstance(exercises, list) or not exercises:
        return {"error": "exercises must be a non-empty list"}

    norm: list[dict[str, Any]] = []
    for ex in exercises:
        if isinstance(ex, str):
            name = ex.strip()
            if not name:
                continue
            norm.append({"name": name, "sets": None, "reps": None,
                         "weight_lbs": None, "notes": None})
            continue
        if not isinstance(ex, dict) or not ex.get("name"):
            return {"error": f"each exercise needs a 'name' field, got {ex!r}"}
        norm.append({
            "name":       str(ex["name"]).strip(),
            "sets":       _maybe_int(ex.get("sets")),
            "reps":       _stringify(ex.get("reps")),
            "weight_lbs": _maybe_float(ex.get("weight_lbs")),
            "notes":      _stringify(ex.get("notes")),
        })

    if not norm:
        return {"error": "no valid exercises in the list"}

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO planned_workouts (planned_date, title, exercises_json, notes, source)
        VALUES (?, ?, ?, ?, 'llm')
        ON CONFLICT(planned_date, title) DO UPDATE SET
            exercises_json = excluded.exercises_json,
            notes          = excluded.notes,
            created_at     = datetime('now', 'localtime')
        """,
        (d.strftime("%Y-%m-%d"), t, json.dumps(norm), (notes or "").strip() or None),
    )
    conn.commit()
    conn.close()
    return {
        "ok":           True,
        "planned_date": d.strftime("%Y-%m-%d"),
        "title":        t,
        "exercises":    norm,
    }


def clear_planned_workouts(from_date: str | None = None) -> dict[str, Any]:
    """Delete planned workouts. If `from_date` is supplied (YYYY-MM-DD),
    only sessions on or after that date are removed.
    """
    conn = get_connection()
    if from_date:
        try:
            d = datetime.strptime(from_date, "%Y-%m-%d").date()
        except ValueError:
            conn.close()
            return {"error": f"from_date must be YYYY-MM-DD, got {from_date!r}"}
        cur = conn.execute(
            "DELETE FROM planned_workouts WHERE planned_date >= ?",
            (d.strftime("%Y-%m-%d"),),
        )
    else:
        cur = conn.execute("DELETE FROM planned_workouts")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": int(deleted), "from_date": from_date}


# ─────────────────────────────────────────────
#  Read tool / dashboard query
# ─────────────────────────────────────────────
def list_planned_workouts(days_ahead: int = 14, include_past: bool = False) -> dict[str, Any]:
    """Planned sessions from today to today + N days. Set include_past=True
    to also return any past planned sessions (useful for review).
    """
    today = date.today()
    end   = today + timedelta(days=int(days_ahead or 14))
    today_s = today.strftime("%Y-%m-%d")
    end_s   = end.strftime("%Y-%m-%d")

    conn = get_connection()
    if include_past:
        rows = conn.execute(
            """
            SELECT planned_date, title, exercises_json, notes, status, created_at
            FROM planned_workouts
            WHERE planned_date <= ?
            ORDER BY planned_date
            """,
            (end_s,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT planned_date, title, exercises_json, notes, status, created_at
            FROM planned_workouts
            WHERE planned_date >= ? AND planned_date <= ?
            ORDER BY planned_date
            """,
            (today_s, end_s),
        ).fetchall()
    conn.close()

    return {
        "today":           today_s,
        "window_end_date": end_s,
        "days_ahead":      int(days_ahead or 14),
        "count":           len(rows),
        "planned": [
            {
                "date":       r["planned_date"],
                "title":      r["title"],
                "exercises":  _parse_json_list(r["exercises_json"]),
                "notes":      r["notes"],
                "status":     r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def _parse_json_list(s: str | None) -> list[dict[str, Any]]:
    try:
        v = json.loads(s) if s else []
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _maybe_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _maybe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _stringify(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
