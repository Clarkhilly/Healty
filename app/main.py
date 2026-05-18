from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import chat as chat_mod
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
