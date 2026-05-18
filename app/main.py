"""FastAPI application: REST + static dashboard, SQLite init on startup."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import apple_health as apple_mod
from app import chat as chat_mod
from app import insights
from app import planning
from app import routines
from app import stats
from app.database import init_db


class ChatRequest(BaseModel):
    question: str
    history: list[dict] | None = None

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Workout Stats API", version="1.0.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/years")
def years() -> dict:
    return {"years": stats.available_years()}


@app.get("/api/summary")
def summary() -> dict:
    return stats.summary()


@app.get("/api/heatmap")
def heatmap(year: int | None = Query(default=None)) -> dict:
    return stats.heatmap(year)


@app.get("/api/year-review/{year}")
def year_review(year: int) -> dict:
    return stats.year_in_review(year)


@app.post("/api/reload")
def reload_db() -> dict:
    init_db(force_reload=True)
    return {"status": "reloaded"}


@app.get("/api/apple-health/summary")
def apple_health_summary() -> dict:
    return apple_mod.summary_payload()


@app.get("/api/apple-health/cardio")
def apple_health_cardio(weeks: int = Query(default=4, ge=1, le=104)) -> dict:
    return insights.cardio_summary(weeks)


@app.post("/api/apple-health/reload")
def apple_health_reload() -> dict:
    return apple_mod.load_apple_health(force_reload=True)


@app.get("/api/routine")
def get_routine() -> dict:
    return routines.get_routine()


@app.delete("/api/routine")
def clear_routine() -> dict:
    return routines.clear_routine()


@app.get("/api/planned")
def get_planned(
    days_ahead: int = Query(default=14, ge=1, le=365),
    include_past: bool = Query(default=False),
) -> dict:
    return planning.list_planned_workouts(days_ahead, include_past)


@app.delete("/api/planned")
def delete_planned(from_date: str | None = Query(default=None)) -> dict:
    return planning.clear_planned_workouts(from_date)


@app.get("/api/stalls")
def get_stalls(
    weeks: int = Query(default=8, ge=1, le=52),
    min_sessions: int = Query(default=4, ge=2, le=20),
) -> dict:
    return insights.stall_report(weeks, min_sessions)


@app.get("/api/chat/health")
def chat_health() -> dict:
    return chat_mod.health()


@app.post("/api/chat")
def chat_endpoint(body: ChatRequest) -> dict:
    return chat_mod.chat(body.question, body.history)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
