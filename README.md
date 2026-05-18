# Healty — Personal Workout Dashboard

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

The LLM is given ~9 read-only "tools" against the workout DB (overall summary,
schedule summary, muscle-group volume, exercise progression, PRs, etc.). It
calls whichever tools it needs to answer a question, then writes a
natural-language response grounded in real numbers.

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

Drop your Hevy/Strong export at the project root as `workout_data.csv`.
The schema this app expects is the Hevy default (`Date`, `Workout Name`,
`Exercise Name`, `Set Order`, `Weight`, `Reps`, etc.).

### 4. Run

Three terminals:

```bash
# Terminal 1 — Ollama
ollama serve

# Terminal 2 — the app
./run.sh

# Then open
http://127.0.0.1:8000
```

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
  main.py        FastAPI app, routes
  database.py    SQLite schema, CSV → DB loader
  stats.py       Heatmap + year-in-review queries
  insights.py    Read-only data tools exposed to the LLM
  chat.py        Ollama client, tool schemas, system prompt
web/
  index.html     Dashboard markup
  app.js         Vanilla JS — heatmap rendering + chat client
  styles.css     Styling
workout_data.csv The source of truth — your Hevy/Strong export
run.sh           Convenience launcher
```

## Privacy

Everything runs on your machine. The LLM is local (Ollama), the DB is local
(SQLite), the web server is local (FastAPI on 127.0.0.1). No telemetry, no
external API calls, no data leaves your laptop.

## License

[PolyForm Noncommercial 1.0.0](./LICENSE) — free to use, modify, and share
for any non-commercial purpose (personal use, learning, research, hobby
projects, education). You may **not** sell this software, charge for hosted
copies of it, or build a paid product around it.

If you want to use it commercially, get in touch.
