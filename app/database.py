import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data.db"
CSV_PATH = ROOT / "workout_data.csv"

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
    count = conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    conn.close()

    if count == 0:
        load_csv()


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
