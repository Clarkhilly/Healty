"""LLM chat layer — talks to a local Ollama instance with tool calling."""

from __future__ import annotations

import json
import os
from typing import Any

import ollama

from app import insights

# Qwen 2.5 7B Instruct is the best small open model at tool calling — beats
# Llama 3.1 8B on structured-data tasks and is the right default for this app.
# Override via `OLLAMA_MODEL=...` in the environment.
DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
MODEL = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
HOST  = os.environ.get("OLLAMA_HOST",  "http://127.0.0.1:11434")

MAX_TOOL_ROUNDS    = 4
MAX_HISTORY_TURNS  = 6

_LOGICAL = os.cpu_count() or 4
CHAT_OPTIONS = {
    "temperature": 0.3,
    "num_predict": 512,
    "num_ctx":     4096,
    "num_thread":  max(2, _LOGICAL // 2),
    "top_p":       0.9,
}
KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

_client: ollama.Client | None = None


def _get_client() -> ollama.Client:
    global _client
    if _client is None:
        _client = ollama.Client(host=HOST)
    return _client


# ─────────────────────────────────────────────
#  Tool schemas
# ─────────────────────────────────────────────
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "overall_summary",
            "description": "High-level totals across the entire workout log: "
                           "log_first_date / log_last_date (ISO), total sessions, "
                           "sets, volume, unique exercises.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_summary",
            "description": "Workout schedule for the most recent N weeks: sessions, "
                           "sessions-per-week, rest gaps, Mon–Sun breakdown, plus "
                           "window_start_date / window_end_date and log_last_date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weeks": {"type": "integer", "description": "Window in weeks (default 4).", "default": 4}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "muscle_group_volume",
            "description": "Volume and sets by muscle group for the most recent N weeks. "
                           "Includes window_start_date / window_end_date and log span.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weeks": {"type": "integer", "description": "Window in weeks (default 4).", "default": 4}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exercise_progression",
            "description": "Per-day stats for one exercise over the last N weeks (each "
                           "trend[].date is ISO). Includes window bounds and log span.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise": {"type": "string", "description": "Exact exercise name."},
                    "weeks":    {"type": "integer", "description": "Window in weeks (default 12).", "default": 12},
                },
                "required": ["exercise"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_exercises",
            "description": "Most-trained exercises, ranked by sets or volume. Each row "
                           "has last_workout_date (ISO). Includes log span.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                    "by":    {"type": "string", "enum": ["sets", "volume"], "default": "sets"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "personal_records",
            "description": "Heaviest weight per exercise with achieved_on (latest ISO "
                           "date at that max weight). Includes log span.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_sessions",
            "description": "The N most recent sessions: each date is ISO. Includes "
                           "log_first_date / log_last_date.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": "Compare two back-to-back windows of N weeks: each period "
                           "has window_first_date / window_last_date (actual session "
                           "bounds), plus split_on_date and log span.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period_weeks": {"type": "integer", "default": 4}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_exercises",
            "description": "All exercises with set counts; each has last_workout_date. "
                           "Includes log span.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


TOOL_DISPATCH = {
    "overall_summary":      insights.overall_summary,
    "schedule_summary":     insights.schedule_summary,
    "muscle_group_volume":  insights.muscle_group_volume,
    "exercise_progression": insights.exercise_progression,
    "top_exercises":        insights.top_exercises,
    "personal_records":     insights.personal_records,
    "recent_sessions":      insights.recent_sessions,
    "compare_periods":      insights.compare_periods,
    "list_exercises":       insights.list_exercises,
}


SYSTEM_PROMPT = """You are the user's strength coach reviewing their own \
workout log. Talk to them like a friend who happens to know lifting — direct, \
specific, no filler.

Hard rules:
- Reference date = log_last_date from tools = latest workout in their log, not \
today's calendar date. Every tool returns log_first_date / log_last_date \
(ISO YYYY-MM-DD) when data exists. Windowed tools also return explicit \
window_* dates; compare_periods uses split_on_date between recent vs prior. \
Quote those strings exactly when you mention time ranges.
- Never invent numbers, dates, percentages, or exercise names. Call a tool \
first; if it errors, retry with different args or a different tool. Don't \
make things up.
- Stay in your lane. Programming (volume, frequency, balance, progression) is \
yours. Pain, injuries, nutrition, supplements, body comp — defer: "that's a \
physio/RD question, not mine."

How to answer:
- Lead with the verdict in the first sentence. No "Great question," no \
restating what they asked, no closing "let me know if…"
- ~60-140 words for most questions. One short paragraph OR 3-5 tight bullets \
— not both. Only go longer if they explicitly ask for detail.
- Round numbers like a human ("about 6.5 sessions a week," not "6.4892").
- Pick the most reasonable interpretation of vague questions instead of \
asking for clarification.
- Markdown OK: **bold** for the verdict, `- bullets` for lists, `code` for \
exercise names. No headings.

Training knowledge to apply:
- Hypertrophy sweet spot: ~10-20 hard sets per muscle per week. Below 8 \
doesn't stimulate enough; above ~22 mostly burns recovery.
- Hitting a muscle ~2×/week beats 1×.
- A working lift that hasn't moved in 4-6 weeks is a stall — name it.
- Common imbalances to watch for: chest >> back, neglected rear delts / \
calves / core.
- 1-2 full rest days per week is normal; training daily for weeks is a \
yellow flag.
"""


def _coerce_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Best-effort type coercion based on the tool's JSON schema."""
    spec = next((t for t in TOOLS if t["function"]["name"] == name), None)
    if not spec:
        return args
    props = (spec["function"].get("parameters") or {}).get("properties", {}) or {}
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        t = (props.get(k) or {}).get("type")
        try:
            if t == "integer":
                out[k] = int(float(v))
            elif t == "number":
                out[k] = float(v)
            elif t == "string":
                out[k] = str(v)
            else:
                out[k] = v
        except (ValueError, TypeError):
            out[k] = v
    return out


def _call_tool(name: str, args: dict[str, Any]) -> Any:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'. "
                         f"Valid: {', '.join(TOOL_DISPATCH.keys())}"}
    try:
        return fn(**_coerce_args(name, args))
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def health() -> dict:
    try:
        client = _get_client()
        models = client.list().get("models", [])
        names = {m.get("model") or m.get("name") for m in models}
        return {
            "ok":           True,
            "model":        MODEL,
            "model_pulled": MODEL in names,
            "host":         HOST,
            "available":    sorted(n for n in names if n),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "host": HOST, "model": MODEL}


def chat(question: str, history: list[dict] | None = None) -> dict:
    client = _get_client()

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-MAX_HISTORY_TURNS:]:
        role = h.get("role")
        if role in ("user", "assistant") and h.get("content"):
            messages.append({"role": role, "content": h["content"]})
    messages.append({"role": "user", "content": question})

    tools_used: list[str] = []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.chat(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                options=CHAT_OPTIONS,
                keep_alive=KEEP_ALIVE,
            )
            msg = response["message"]
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                return {
                    "answer":     msg.get("content", "").strip() or "(empty response)",
                    "tools_used": tools_used,
                    "rounds":     len(tools_used),
                    "model":      MODEL,
                }

            messages.append({
                "role":       "assistant",
                "content":    msg.get("content", "") or "",
                "tool_calls": tool_calls,
            })

            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments", {}) or {}
                args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                result = _call_tool(name, args)
                tools_used.append(name)
                messages.append({
                    "role":    "tool",
                    "name":    name,
                    "content": json.dumps(result, default=str),
                })
    except ConnectionError as e:
        return _error_response(
            f"Could not reach Ollama at `{HOST}`. Start it with `ollama serve` "
            f"and pull the model with `ollama pull {MODEL}`. ({e})",
            tools_used,
        )
    except ollama.ResponseError as e:
        msg = str(e)
        hint = f" Try `ollama pull {MODEL}`." if "not found" in msg.lower() else ""
        return _error_response(f"Ollama error: {msg}.{hint}", tools_used)
    except Exception as e:  # noqa: BLE001
        return _error_response(f"Unexpected error: {type(e).__name__}: {e}", tools_used)

    return _error_response(
        "Hit the tool-call budget without composing an answer. Try rephrasing.",
        tools_used,
    )


def _error_response(message: str, tools_used: list[str]) -> dict:
    return {
        "answer":     message,
        "tools_used": tools_used,
        "rounds":     len(tools_used),
        "model":      MODEL,
        "error":      True,
    }
