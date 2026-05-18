# Healthy — Personal Workout Dashboard

A local-first workout analytics dashboard with a chat interface powered by a
local LLM. Browse your training history as a GitHub-style heatmap, get
per-year stats, and ask plain-English questions about your data — all on your
own machine, with no data ever leaving it.

## What you get

- **Year-in-review** — totals, longest streak, top exercise, monthly bars, PR list.
- **Activity heatmap** — GitHub-style contribution grid, color-coded by daily volume.
- **Ask your data** — chat with a local LLM that has tool access to your workout DB.
  Questions like "Am I overtraining any muscle group?" or "Which lifts have stalled?"
  get answered with real numbers pulled directly from your logs.
- **"For nerds" toggle** — surfaces the math behind every metric.
- **Apple Health (optional)** — drop your iPhone Health export at
  `apple_health_export/export.xml` and the dashboard adds a panel for recent
  cardio (watch-recorded), body weight trend, resting HR, HRV, and daily
  steps/calories. The chat layer gets three new tools: `cardio_summary`,
  `body_metric_trend`, `daily_activity`.

## How it works

```
┌──────────────┐   POST /api/chat    ┌───────────────────┐
│   Browser    │ ──────────────────► │   FastAPI server  │
│  (vanilla    │                     │   (uvicorn)       │
│   HTML/JS)   │ ◄────────────────── │                   │
└──────────────┘    JSON response    └────────┬──────────┘
                                              │
                                              │ tool calls
                                              ▼
                                     ┌───────────────────┐
                                     │  Ollama (local)   │
                                     │  qwen2.5:7b-      │
                                     │  instruct-q4_K_M  │
                                     └────────┬──────────┘
                                              │
                                              ▼
                                     ┌───────────────────┐
                                     │  SQLite (data.db) │
                                     │  built from CSV   │
                                     └───────────────────┘
```

The LLM has 12 read-only tools: 9 against the Hevy lifting DB (overall summary,
schedule summary, muscle-group volume, exercise progression, top exercises, PRs,
recent sessions, compare periods, list exercises) and 3 against the optional
Apple Health DB (cardio summary, body metric trend, daily activity). It calls
whichever tools it needs, then writes a natural-language answer grounded in
real numbers.

## Setup

### 1. Install Ollama and pull the model (one-time)

```bash
# Linux/macOS
curl -fsSL https://ollama.com/install.sh | sh

ollama pull qwen2.5:7b-instruct-q4_K_M    # ~4.4 GB
```

### 2. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Provide your workout data

Place a CSV at the project root named `workout_data.csv`. The loader expects
**one row** per set and these columns (names and types must match):

`title`, `start_time`, `end_time`, `description`, `exercise_title`,
`superset_id`, `exercise_notes`, `set_index`, `set_type`, `weight_lbs`, `reps`,
`distance_miles`, `duration_seconds`, `rpe`

`start_time` / `end_time` are parsed as `"%d %b %Y, %H:%M"` (e.g. `15 Jan 2024,
09:30`). If your export uses different headers, rename or reshape the CSV to
match before loading.

### 3b. (Optional) Add Apple Health data

On your iPhone: Health app → profile picture → **Export All Health Data**. You
get a zip; unzip it and copy the `apple_health_export/` folder (containing
`export.xml`) to the project root. The dashboard auto-loads it on next start
and exposes:

- A new **Apple Health** panel with recent cardio, weight trend, RHR, HRV,
  avg daily steps / active kcal.
- New chat tools (`cardio_summary`, `body_metric_trend`, `daily_activity`).

Strength sessions Hevy mirrors into Apple Health are imported but filtered
from the cardio view (matched by `source IN ('Hevy', …)`) so they don't get
double-counted against your lifting tables. To rebuild after a fresh export,
click **Reload XML** in the Apple Health panel or POST to
`/api/apple-health/reload`.

### 4. Run

Three terminals:

```bash
# Terminal 1 — Ollama
ollama serve

# Terminal 2 — the app
./run.sh

# Then open (same machine)
http://127.0.0.1:8000
```

`run.sh` binds uvicorn to `0.0.0.0:8000`, so other devices on your LAN can open
`http://<this-host>:8000` if your firewall allows it.

## HTTP API (JSON)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | API process up |
| `GET` | `/api/years` | Distinct years in the DB |
| `GET` | `/api/summary` | All-time session count, first/last date, total volume |
| `GET` | `/api/heatmap?year=` | Per-day volume and heat levels for a year |
| `GET` | `/api/year-review/{year}` | Year-in-review payload for the dashboard |
| `POST` | `/api/reload` | Rebuild SQLite from `workout_data.csv` |
| `GET` | `/api/apple-health/summary` | Snapshot for the Apple Health panel (latest weight, RHR, HRV, 28d averages, weight trend) |
| `GET` | `/api/apple-health/cardio?weeks=` | Non-strength workouts in the window (filters out Hevy/etc.) |
| `POST` | `/api/apple-health/reload` | Stream-parse `apple_health_export/export.xml` and rebuild the three `health_*` tables |
| `GET` | `/api/chat/health` | Ollama reachability and model pull status |
| `POST` | `/api/chat` | `{ "question": "…", "history": optional turns }` → answer + tools used |

Static assets live under `/static/`; `/` serves `web/index.html`.

## Configuration

All optional — sensible defaults are baked in.

| Env var | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct-q4_K_M` | Switch to a different Ollama model |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Point at a non-default Ollama install |
| `OLLAMA_KEEP_ALIVE` | `30m` | How long Ollama keeps the model in RAM |

For a snappier (but less accurate at tool calling) experience on weaker
hardware:

```bash
OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M ./run.sh
```

## Project layout

```
app/
  main.py            FastAPI app, HTTP routes
  database.py        SQLite schema, Hevy CSV → DB loader
  apple_health.py    Streaming XML loader (Apple Health → 3 SQLite tables)
  stats.py           Heatmap + year-in-review queries
  insights.py        Read-only data tools used by the chat layer (Hevy + Apple Health)
  chat.py            Ollama client, tool schemas, system prompt
web/
  index.html         Dashboard markup
  app.js             Vanilla JS — heatmap, chat UI, Apple Health panel
  styles.css         Styling
workout_data.csv     Per-set CSV (see setup; gitignored by default)
apple_health_export/ Optional iPhone export (gitignored; export.xml ~500MB)
data.db              Generated SQLite file (gitignored)
run.sh               Venv + uvicorn launcher
```

## Privacy

Everything runs on your machine. The LLM is local (Ollama), the DB is local
(SQLite), and the dashboard is served by FastAPI on your network (see
`run.sh`: `0.0.0.0` means LAN access is possible; tighten the bind if you
only want loopback). No telemetry, no external API calls, and the chat layer
never sends your log to a hosted model.

## License

[PolyForm Noncommercial 1.0.0](./LICENSE) — free to use, modify, and share
for any non-commercial purpose (personal use, learning, research, hobby
projects, education). You may **not** sell this software, charge for hosted
copies of it, or build a paid product around it.

If you want to use it commercially, get in touch.
