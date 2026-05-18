"""Self-reported user facts for chat personalization (not present in Hevy/Health)."""

from __future__ import annotations

from typing import Any

from app.database import get_connection

_PROFILE_ID = 1


def get_profile() -> dict[str, Any]:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT age, sex, years_trained, notes, updated_at
        FROM user_profile WHERE id = ?
        """,
        (_PROFILE_ID,),
    ).fetchone()
    conn.close()
    if not row:
        return _empty_payload()
    return {
        "age":            row["age"],
        "sex":            row["sex"],
        "years_trained":  row["years_trained"],
        "notes":          row["notes"],
        "updated_at":     row["updated_at"],
        "has_any":        _row_has_any(row),
    }


def save_profile(
    age: int | None = None,
    sex: str | None = None,
    years_trained: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Upsert profile. Pass None to clear a field."""
    err = _validate(age, sex, years_trained, notes)
    if err:
        return {"ok": False, "error": err}

    norm_age = int(age) if age is not None else None
    norm_sex = (sex or "").strip() or None
    norm_years = float(years_trained) if years_trained is not None else None
    norm_notes = (notes or "").strip() or None

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO user_profile (id, age, sex, years_trained, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(id) DO UPDATE SET
            age            = excluded.age,
            sex            = excluded.sex,
            years_trained  = excluded.years_trained,
            notes          = excluded.notes,
            updated_at     = excluded.updated_at
        """,
        (_PROFILE_ID, norm_age, norm_sex, norm_years, norm_notes),
    )
    conn.commit()
    conn.close()
    return {"ok": True, **get_profile()}


def profile_for_prompt() -> str:
    """Text block for the system prompt; empty if nothing saved."""
    p = get_profile()
    if not p.get("has_any"):
        return ""
    parts: list[str] = []
    if p.get("age") is not None:
        parts.append(f"age {int(p['age'])}")
    if p.get("sex"):
        parts.append(f"sex {p['sex']}")
    if p.get("years_trained") is not None:
        yt = p["years_trained"]
        parts.append(f"~{yt:g} years training experience")
    if p.get("notes"):
        parts.append(f"notes: {p['notes']}")
    line = "; ".join(parts)
    return (
        "Self-reported profile (use for personalization — volume expectations, "
        f"recovery framing, how technical to be; do NOT treat as medical fact): {line}"
    )


def _empty_payload() -> dict[str, Any]:
    return {
        "age":            None,
        "sex":            None,
        "years_trained":  None,
        "notes":          None,
        "updated_at":     None,
        "has_any":        False,
    }


def _row_has_any(row: Any) -> bool:
    return any(
        row[k] is not None and str(row[k]).strip() != ""
        for k in ("age", "sex", "years_trained", "notes")
    )


def _validate(
    age: int | None,
    sex: str | None,
    years_trained: float | None,
    notes: str | None,
) -> str | None:
    if age is not None:
        try:
            a = int(age)
        except (TypeError, ValueError):
            return "age must be a whole number"
        if a < 13 or a > 120:
            return "age should be between 13 and 120 (or leave blank)"
    if sex is not None and len(str(sex).strip()) > 48:
        return "sex label is too long"
    if years_trained is not None:
        try:
            y = float(years_trained)
        except (TypeError, ValueError):
            return "years trained must be a number"
        if y < 0 or y > 80:
            return "years trained should be between 0 and 80"
    if notes is not None and len(str(notes)) > 2000:
        return "notes must be 2000 characters or less"
    return None
