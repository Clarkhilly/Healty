"""User's saved workout routine — a reusable session template (no dates).

This is the dashboard's persistent "current program" slot. The LLM writes it
with `save_routine` when the user asks for a split / routine / weekly template
(e.g. "build me a PPL hypertrophy routine"). It's deliberately distinct from
`planned_workouts`:

  * `routine`            → reusable template ("Push A", "Pull A", "Legs A",
                            "Upper A", "Lower A"…) — no dates.
  * `planned_workouts`   → specific upcoming sessions on specific dates.

A natural flow: the model populates `routine` once, then `schedule_workout`
for each day it's applied to. Single-row table (id = 1) keeps things simple.
"""

from __future__ import annotations

import json
from typing import Any

from app.database import get_connection


# ─────────────────────────────────────────────
#  Write
# ─────────────────────────────────────────────
def save_routine(
    name: str,
    sessions: list[Any],
    notes: str = "",
) -> dict[str, Any]:
    """Create or overwrite the saved routine.

    Args:
        name:     Routine name, e.g. "PPL Hypertrophy", "Upper/Lower 4x".
        sessions: List of session dicts: each {title, exercises, notes?}.
                  `exercises` can be a list of strings (names) OR a list of
                  dicts {name, sets, reps, weight_lbs, notes}.
        notes:    Optional routine-level note.
    """
    n = (name or "").strip()
    if not n:
        return {"error": "name is required"}
    if not isinstance(sessions, list) or not sessions:
        return {"error": "sessions must be a non-empty list"}

    norm_sessions: list[dict[str, Any]] = []
    for s in sessions:
        if not isinstance(s, dict) or not s.get("title"):
            return {"error": f"each session needs a 'title' field, got {s!r}"}
        raw_ex = s.get("exercises", [])
        if not isinstance(raw_ex, list) or not raw_ex:
            return {"error": f"session '{s.get('title')}' needs at least one exercise"}

        norm_ex: list[dict[str, Any]] = []
        for ex in raw_ex:
            if isinstance(ex, str):
                name_str = ex.strip()
                if name_str:
                    norm_ex.append({"name": name_str, "sets": None, "reps": None,
                                    "weight_lbs": None, "notes": None})
                continue
            if not isinstance(ex, dict) or not ex.get("name"):
                return {"error": f"exercise needs 'name', got {ex!r}"}
            norm_ex.append({
                "name":       str(ex["name"]).strip(),
                "sets":       _maybe_int(ex.get("sets")),
                "reps":       _stringify(ex.get("reps")),
                "weight_lbs": _maybe_float(ex.get("weight_lbs")),
                "notes":      _stringify(ex.get("notes")),
            })
        if not norm_ex:
            return {"error": f"session '{s.get('title')}' has no valid exercises"}

        norm_sessions.append({
            "title":     str(s["title"]).strip(),
            "exercises": norm_ex,
            "notes":     _stringify(s.get("notes")),
        })

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO routine (id, name, sessions_json, notes, updated_at)
        VALUES (1, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(id) DO UPDATE SET
            name          = excluded.name,
            sessions_json = excluded.sessions_json,
            notes         = excluded.notes,
            updated_at    = excluded.updated_at
        """,
        (n, json.dumps(norm_sessions), (notes or "").strip() or None),
    )
    conn.commit()
    conn.close()
    return {
        "ok":            True,
        "name":          n,
        "session_count": len(norm_sessions),
        "sessions":      norm_sessions,
    }


def clear_routine() -> dict[str, Any]:
    """Delete the saved routine."""
    conn = get_connection()
    cur = conn.execute("DELETE FROM routine WHERE id = 1")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": int(deleted)}


# ─────────────────────────────────────────────
#  Read
# ─────────────────────────────────────────────
def get_routine() -> dict[str, Any]:
    """Return the saved routine (or an `exists: False` payload if empty)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT name, sessions_json, notes, updated_at FROM routine WHERE id = 1"
    ).fetchone()
    conn.close()
    if not row:
        return {
            "exists":     False,
            "name":       None,
            "sessions":   [],
            "notes":      None,
            "updated_at": None,
        }
    try:
        sessions = json.loads(row["sessions_json"]) or []
        if not isinstance(sessions, list):
            sessions = []
    except (json.JSONDecodeError, TypeError):
        sessions = []
    return {
        "exists":     True,
        "name":       row["name"],
        "sessions":   sessions,
        "notes":      row["notes"],
        "updated_at": row["updated_at"],
    }


def routine_for_prompt() -> str:
    """Compact one-liner about the saved routine for the system prompt.
    Empty string if no routine is saved."""
    r = get_routine()
    if not r["exists"] or not r["sessions"]:
        return ""
    titles = ", ".join(s.get("title", "?") for s in r["sessions"])
    return f"Saved routine: \"{r['name']}\" — {len(r['sessions'])} sessions ({titles})"


# ─────────────────────────────────────────────
#  Helpers (mirror app/planning.py — kept inline so the module is self-contained)
# ─────────────────────────────────────────────
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
