"""LLM chat layer — OpenAI-compatible client with tool calling.

Provider is auto-selected from env vars:

* `GROQ_API_KEY`   set → Groq hosted (default model: llama-3.3-70b-versatile)
* `OPENAI_API_KEY` set → OpenAI hosted (default model: gpt-4o-mini)
* otherwise            → local Ollama at OLLAMA_HOST (default model:
                         qwen2.5:7b-instruct-q4_K_M). Ollama exposes an
                         OpenAI-compatible API at /v1, so the same client
                         works for both hosted and local.

Override the model with `LLM_MODEL=...` (or legacy `OLLAMA_MODEL=...`).
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from app import insights, planning, profile, routines

_GROQ_KEY   = os.environ.get("GROQ_API_KEY")
_OPENAI_KEY = os.environ.get("OPENAI_API_KEY")

if _GROQ_KEY:
    PROVIDER       = "groq"
    BASE_URL       = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    API_KEY        = _GROQ_KEY
    DEFAULT_MODEL  = "llama-3.3-70b-versatile"
elif _OPENAI_KEY:
    PROVIDER       = "openai"
    BASE_URL       = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    API_KEY        = _OPENAI_KEY
    DEFAULT_MODEL  = "gpt-4o-mini"
else:
    PROVIDER       = "ollama"
    BASE_URL       = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/") + "/v1"
    API_KEY        = "ollama"  # not validated by Ollama; library requires non-empty
    DEFAULT_MODEL  = "qwen2.5:7b-instruct-q4_K_M"

MODEL = (
    os.environ.get("LLM_MODEL")
    or os.environ.get("OLLAMA_MODEL")
    or DEFAULT_MODEL
)

MAX_TOOL_ROUNDS    = 12
MAX_HISTORY_TURNS  = 6

CHAT_OPTIONS = {
    "temperature": 0.3,
    "max_tokens":  512,
    "top_p":       0.9,
}

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
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
    # ── Apple Health tools ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "cardio_summary",
            "description": "Apple Health workouts in the last N weeks, EXCLUDING strength "
                           "sessions that Hevy duplicated into Apple Health. Use for cardio, "
                           "conditioning, watch-logged activity, or 'am I doing anything "
                           "besides lifting' questions. Returns sessions, totals, and a list.",
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
            "name": "body_metric_trend",
            "description": "Trend of one body / cardio-health metric from Apple Health over "
                           "the last N weeks: BodyMass, BodyMassIndex, RestingHeartRate, or "
                           "HeartRateVariabilitySDNN. Returns first/last/min/max/avg, pct "
                           "change, and a chronological sample list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["BodyMass", "BodyMassIndex", "RestingHeartRate", "HeartRateVariabilitySDNN"],
                        "default": "BodyMass",
                    },
                    "weeks": {"type": "integer", "default": 12},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daily_activity",
            "description": "Daily steps, active calories, basal calories, walking miles, and "
                           "flights climbed from Apple Health, averaged over the last N weeks. "
                           "Use for activity-level / NEAT / general-movement questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weeks": {"type": "integer", "default": 4}
                },
            },
        },
    },
    # ── Stall detector ────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "stall_report",
            "description": "Classify working lifts as stalled or progressing over the "
                           "last N weeks. Returns the stalled list (no new heavy-set PR + "
                           "flat avg-weight slope) and a progressing list. Use this for "
                           "'what's plateaued / what should I push' questions instead of "
                           "calling exercise_progression for every lift.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weeks":        {"type": "integer", "default": 8},
                    "min_sessions": {"type": "integer", "default": 4},
                },
            },
        },
    },
    # ── Saved routine (a reusable template — distinct from planned dates) ─
    {
        "type": "function",
        "function": {
            "name": "save_routine",
            "description": "Save (or overwrite) the user's current reusable workout "
                           "routine — the template they want to repeat. Call this when the "
                           "user asks for a 'routine', 'split', 'weekly template', 'program "
                           "structure', or 'what should my week look like'. The routine has "
                           "session titles + exercises but NO dates. To put it on the "
                           "calendar, use `schedule_workout` for each day separately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Routine name, e.g. 'PPL Hypertrophy', "
                                       "'Upper/Lower 4x', 'Full Body 3x'.",
                    },
                    "sessions": {
                        "type": "array",
                        "description": "Ordered list of sessions. Each item is an object "
                                       "{title, exercises, notes?}. `exercises` may be a "
                                       "list of strings OR a list of objects "
                                       "{name, sets, reps, weight_lbs, notes}.",
                        "items": {"type": "object"},
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional routine-level note (goal, RPE cap, etc).",
                    },
                },
                "required": ["name", "sessions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_routine",
            "description": "Read the user's saved routine (name + list of session "
                           "templates). Use BEFORE generating planned workouts so you "
                           "can apply the routine to the calendar consistently, or to "
                           "answer 'what's my routine'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_routine",
            "description": "Delete the saved routine. Use only when the user explicitly "
                           "says 'wipe my routine' / 'I want to start over'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # ── Planning / program generator (WRITE + READ) ───────────────────────
    {
        "type": "function",
        "function": {
            "name": "schedule_workout",
            "description": "Add a planned workout for a specific future date. Use this when "
                           "the user asks for a program / split / schedule. Call once per "
                           "session you want to schedule. UPSERTs on (date, title) so calling "
                           "twice for the same day+title overwrites — safe to re-plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date":  {"type": "string", "description": "ISO YYYY-MM-DD."},
                    "title": {"type": "string", "description": "Session name, e.g. 'Push A'."},
                    "exercises": {
                        "type": "array",
                        "description": "List of exercises. Each item may be a string "
                                       "(name only) OR an object {name, sets, reps, "
                                       "weight_lbs, notes}.",
                        "items": {"type": "object"},
                    },
                    "notes": {"type": "string", "description": "Optional session note."},
                },
                "required": ["date", "title", "exercises"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_planned_workouts",
            "description": "Return planned workouts in the next N days. Use to check what's "
                           "already scheduled before adding more, or to answer 'what's on tap "
                           "this week'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead":   {"type": "integer", "default": 14},
                    "include_past": {"type": "boolean", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_planned_workouts",
            "description": "Delete planned workouts. Pass `from_date` (YYYY-MM-DD) to keep "
                           "earlier ones; omit it to wipe all. Use before generating a brand-"
                           "new program if the user wants to replace what's there.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "description": "YYYY-MM-DD, optional."},
                },
            },
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
    "cardio_summary":       insights.cardio_summary,
    "body_metric_trend":    insights.body_metric_trend,
    "daily_activity":       insights.daily_activity,
    "stall_report":         insights.stall_report,
    # write tools — planning (dated upcoming sessions)
    "schedule_workout":      planning.schedule_workout,
    "list_planned_workouts": planning.list_planned_workouts,
    "clear_planned_workouts": planning.clear_planned_workouts,
    # write tools — routine (reusable template, no dates)
    "save_routine":          routines.save_routine,
    "get_routine":           routines.get_routine,
    "clear_routine":         routines.clear_routine,
}


SYSTEM_PROMPT_BASE = """You are the user's strength coach reviewing their own \
workout log. Talk to them like a friend who happens to know lifting — direct, \
specific, no filler.

Hard rules:
- A **self-reported user profile** (age, training history, short notes) may be \
appended below the main rules. It is **not** from their CSV or Apple Health — \
use it to personalize tone and expectations, not as a medical history.
- Reference date = log_last_date from tools = latest workout in their log, not \
today's calendar date. Every tool returns log_first_date / log_last_date \
(ISO YYYY-MM-DD) when data exists. Windowed tools also return explicit \
window_* dates; compare_periods uses split_on_date between recent vs prior. \
Quote those strings exactly when you mention time ranges.
- Never invent numbers, dates, percentages, or exercise names. Call a tool \
first; if it errors, retry with different args or a different tool. Don't \
make things up.
- Stay in your lane. Programming (volume, frequency, balance, progression) \
is yours. Body composition / cardio fitness trends pulled FROM TOOLS \
(`body_metric_trend`, `daily_activity`, `cardio_summary` — Apple Health \
data) are also fair game; describe what the numbers show. Pain, injuries, \
nutrition, supplements, medical advice — defer: "that's a physio/RD \
question, not mine."
- Apple Health vs Hevy: lifting belongs to Hevy tools (sets/PRs/sessions); \
watch-recorded cardio and body metrics belong to the Apple Health tools. \
`cardio_summary` already filters out Hevy-duplicated strength workouts, so \
don't worry about double-counting.

Routine vs Planned — pick the right write tool:
- A **routine** is a REUSABLE WEEKLY TEMPLATE with no dates ("Push A", \
"Pull A", "Legs A", "Upper A"…). Save it with `save_routine(name, sessions)` \
when the user asks for "a routine", "a split", "a weekly template", \
"my program structure", "what my week should look like".
- A **planned workout** is a SPECIFIC DATED SESSION ("Mon Oct 13 — Push A"). \
Use `schedule_workout(date, title, exercises)` once per day when the user \
asks to "schedule next week", "build me a 4-week program starting Monday", \
"put it on the calendar", or similar.
- Natural combo: if the user asks for both, save the routine first, then \
schedule_workout for each day applying the routine sessions in order.
- Before scheduling many sessions, call `get_routine()` if a saved routine \
exists — apply it instead of inventing new sessions.
- Sensible defaults: sets 3-4, reps "8-12" for hypertrophy / "3-6" for \
strength. Use exercise names from `list_exercises` when possible — don't \
invent new ones unless the user specifically asks. If replacing an existing \
program on the calendar, call `clear_planned_workouts(from_date)` first.
- After writing, summarize in your reply — don't dump the JSON.

Weekly digest format — if the user asks for a "digest", "weekly review", \
"how did this week go", or similar: call schedule_summary(1), \
muscle_group_volume(1), compare_periods(1), and stall_report(6). Then write:
  **Verdict** in one sentence.
  - **What went up**: 1-2 bullets (PRs hit, sessions vs prior week).
  - **What stalled / dropped**: 1-2 bullets (named lifts from stall_report).
  - **One change for next week**: a single concrete action.

Stall questions: prefer `stall_report` (one call) over running \
`exercise_progression` for each lift.

How to answer:
- Lead with the verdict in the first sentence. No "Great question," no \
restating what they asked, no closing "let me know if…"
- ~60-140 words for most questions. One short paragraph OR 3-5 tight bullets \
— not both. Only go longer if they explicitly ask for detail or for a \
digest/program.
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


def _build_system_prompt() -> str:
    """Inject saved routine + self-reported profile into the base prompt.
    Built per-turn so a freshly-saved routine or profile is visible on the very
    next message."""
    chunks: list[str] = [SYSTEM_PROMPT_BASE]
    prof = profile.profile_for_prompt()
    if prof:
        chunks.append("\n\n" + prof)
    summary = routines.routine_for_prompt()
    if summary:
        chunks.append(
            "\n\nUser has a saved routine on record — use `get_routine()` to "
            "fetch the full details before applying it to the calendar:\n"
            + summary
        )
    return "".join(chunks)


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
        listing = client.models.list()
        names = sorted(m.id for m in listing.data)
        return {
            "ok":           True,
            "provider":     PROVIDER,
            "model":        MODEL,
            "model_pulled": MODEL in names,
            "host":         BASE_URL,
            "available":    names,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok":       False,
            "provider": PROVIDER,
            "error":    f"{type(e).__name__}: {e}",
            "host":     BASE_URL,
            "model":    MODEL,
        }


def chat(question: str, history: list[dict] | None = None) -> dict:
    client = _get_client()

    messages: list[dict] = [{"role": "system", "content": _build_system_prompt()}]
    for h in (history or [])[-MAX_HISTORY_TURNS:]:
        role = h.get("role")
        if role in ("user", "assistant") and h.get("content"):
            messages.append({"role": role, "content": h["content"]})
    messages.append({"role": "user", "content": question})

    tools_used: list[str] = []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                **CHAT_OPTIONS,
            )
            msg = response.choices[0].message
            tool_calls = msg.tool_calls or []

            if not tool_calls:
                return {
                    "answer":     (msg.content or "").strip() or "(empty response)",
                    "tools_used": tools_used,
                    "rounds":     len(tools_used),
                    "model":      MODEL,
                    "provider":   PROVIDER,
                }

            messages.append({
                "role":    "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id":       c.id,
                        "type":     "function",
                        "function": {
                            "name":      c.function.name,
                            "arguments": c.function.arguments,
                        },
                    }
                    for c in tool_calls
                ],
            })

            for call in tool_calls:
                name = call.function.name
                raw_args = call.function.arguments or "{}"
                try:
                    args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
                result = _call_tool(name, args)
                tools_used.append(name)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": call.id,
                    "content":      json.dumps(result, default=str),
                })
    except Exception as e:  # noqa: BLE001
        hint = ""
        if PROVIDER == "groq":
            hint = (f" Check that GROQ_API_KEY is valid and that '{MODEL}' is "
                    "still listed at https://console.groq.com/docs/models.")
        elif PROVIDER == "openai":
            hint = " Check OPENAI_API_KEY and your account quota."
        elif PROVIDER == "ollama":
            hint = (f" Make sure `ollama serve` is running at {BASE_URL} "
                    f"and the model is pulled: `ollama pull {MODEL}`.")
        return _error_response(f"{type(e).__name__}: {e}.{hint}", tools_used)

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
        "provider":   PROVIDER,
        "error":      True,
    }
