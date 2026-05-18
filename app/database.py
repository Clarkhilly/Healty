"""SQLite storage: schema, connections, and loading `workout_data.csv` into `data.db`."""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data.db"
CSV_PATH = ROOT / "workout_data.csv"
APPLE_HEALTH_XML_PATH = ROOT / "apple_health_export" / "export.xml"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    description TEXT,
    exercise_title TEXT NOT NULL,
    superset_id TEXT,
    exercise_notes TEXT,
    set_index INTEGER,
    set_type TEXT,
    weight_lbs REAL,
    reps REAL,
    distance_miles REAL,
    duration_seconds REAL,
    rpe REAL,
    volume REAL,
    workout_date TEXT NOT NULL,
    session_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    workout_date TEXT NOT NULL,
    duration_min REAL,
    total_volume REAL,
    total_sets INTEGER,
    exercise_count INTEGER,
    total_miles REAL
);

CREATE INDEX IF NOT EXISTS idx_sets_date ON sets(workout_date);
CREATE INDEX IF NOT EXISTS idx_sets_session ON sets(session_key);
CREATE INDEX IF NOT EXISTS idx_sets_exercise ON sets(exercise_title);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(workout_date);

-- ── Apple Health (separate from Hevy lifting data) ─────────────────────────
-- Workouts: one row per <Workout> in export.xml. Strength workouts that Hevy
-- syncs to Apple Health show up here with source='Hevy' — keep them, but the
-- insights layer filters them out for cardio/non-lifting views.
CREATE TABLE IF NOT EXISTS health_workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_type TEXT NOT NULL,
    start_time    TEXT NOT NULL,
    end_time      TEXT,
    workout_date  TEXT NOT NULL,
    duration_min  REAL,
    energy_kcal   REAL,
    distance_mi   REAL,
    source        TEXT NOT NULL,
    UNIQUE(start_time, activity_type, source)
);

-- Low-volume per-sample metrics (body weight, BMI, RHR, HRV).
CREATE TABLE IF NOT EXISTS health_metric_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_type TEXT NOT NULL,
    sample_date TEXT NOT NULL,
    sample_time TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT,
    source      TEXT NOT NULL,
    UNIQUE(metric_type, sample_time, source)
);

-- High-volume cumulative metrics (steps, energy, distance) folded to daily
-- totals at load time so we don't store millions of individual samples.
CREATE TABLE IF NOT EXISTS health_daily (
    metric_type TEXT NOT NULL,
    day         TEXT NOT NULL,
    total       REAL NOT NULL,
    samples     INTEGER NOT NULL,
    PRIMARY KEY (metric_type, day)
);

CREATE INDEX IF NOT EXISTS idx_hw_date       ON health_workouts(workout_date);
CREATE INDEX IF NOT EXISTS idx_hw_source     ON health_workouts(source);
CREATE INDEX IF NOT EXISTS idx_hms_type_date ON health_metric_samples(metric_type, sample_date);
CREATE INDEX IF NOT EXISTS idx_hd_type_day   ON health_daily(metric_type, day);

-- ── Saved workout routine (a reusable session template) ──────────────────
-- One slot per user (enforced with id=1). A routine is a list of sessions —
-- each session has a title + list of exercises, with no calendar dates. The
-- LLM populates it via `save_routine` when the user asks for a split/template;
-- the model can later APPLY it to the calendar by calling schedule_workout
-- for each session.
CREATE TABLE IF NOT EXISTS routine (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    sessions_json TEXT NOT NULL,
    notes         TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ── Planned workouts (forward-looking sessions written by the LLM) ────────
-- The chat layer's `schedule_workout` tool inserts here. Each row is one
-- upcoming session with a JSON list of exercises. UNIQUE(date,title) lets
-- the LLM idempotently re-plan a session without creating duplicates.
CREATE TABLE IF NOT EXISTS planned_workouts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    planned_date   TEXT NOT NULL,
    title          TEXT NOT NULL,
    exercises_json TEXT NOT NULL,
    notes          TEXT,
    source         TEXT NOT NULL DEFAULT 'llm',
    status         TEXT NOT NULL DEFAULT 'planned',
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(planned_date, title)
);
CREATE INDEX IF NOT EXISTS idx_pw_date ON planned_workouts(planned_date);

-- ── Self-reported user profile (for chat personalization) ────────────────
-- One row (id = 1). Filled from the dashboard; injected into the LLM system
-- prompt. Not derived from Hevy or Apple Health exports.
CREATE TABLE IF NOT EXISTS user_profile (
    id              INTEGER PRIMARY KEY,
    age             INTEGER,
    sex             TEXT,
    years_trained   REAL,
    notes           TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force_reload: bool = False) -> None:
    if force_reload and DB_PATH.exists():
        DB_PATH.unlink()

    conn = get_connection()
    conn.executescript(SCHEMA)
    sets_count = conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    health_count = conn.execute("SELECT COUNT(*) FROM health_workouts").fetchone()[0]
    conn.close()

    if sets_count == 0:
        load_csv()

    # Lazy Apple Health import: only on first run (table empty) AND if the XML
    # exists. Subsequent imports go through /api/apple-health/reload so we
    # don't pay the iterparse cost on every server start.
    if health_count == 0 and APPLE_HEALTH_XML_PATH.exists():
        from app.apple_health import load_apple_health  # lazy to avoid circular import
        load_apple_health()


SETS_COLS = [
    "title", "start_time", "end_time", "description", "exercise_title",
    "superset_id", "exercise_notes", "set_index", "set_type",
    "weight_lbs", "reps", "distance_miles", "duration_seconds", "rpe",
    "volume", "workout_date", "session_key",
]

SESSIONS_COLS = [
    "session_key", "title", "start_time", "end_time", "workout_date",
    "duration_min", "total_volume", "total_sets", "exercise_count", "total_miles",
]


def load_csv() -> None:
    df = pd.read_csv(CSV_PATH)
    df["start_time"] = pd.to_datetime(df["start_time"], format="%d %b %Y, %H:%M", errors="coerce")
    df["end_time"]   = pd.to_datetime(df["end_time"],   format="%d %b %Y, %H:%M", errors="coerce")
    df = df.dropna(subset=["start_time"])

    for col in ("weight_lbs", "reps", "distance_miles", "duration_seconds", "rpe", "set_index"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["volume"] = df["weight_lbs"].fillna(0) * df["reps"].fillna(0)
    df["workout_date"] = df["start_time"].dt.strftime("%Y-%m-%d")
    df["session_key"]  = df["title"] + "|" + df["start_time"].astype(str)

    sessions = df.groupby("session_key").agg(
        title=("title", "first"),
        start_time=("start_time", "min"),
        end_time=("end_time", "max"),
        workout_date=("workout_date", "first"),
        total_volume=("volume", "sum"),
        total_sets=("set_index", "count"),
        exercise_count=("exercise_title", "nunique"),
        total_miles=("distance_miles", "sum"),
    ).reset_index()
    sessions["duration_min"] = (sessions["end_time"] - sessions["start_time"]).dt.total_seconds() / 60
    sessions["total_miles"]  = sessions["total_miles"].fillna(0)

    # Stringify datetime columns once, in both frames, before writing.
    for frame in (df, sessions):
        frame["start_time"] = frame["start_time"].dt.strftime("%Y-%m-%d %H:%M")
        frame["end_time"]   = frame["end_time"].dt.strftime("%Y-%m-%d %H:%M")

    conn = get_connection()
    df[SETS_COLS].to_sql("sets", conn, if_exists="append", index=False)
    sessions[SESSIONS_COLS].to_sql("sessions", conn, if_exists="append", index=False)
    conn.commit()
    conn.close()
