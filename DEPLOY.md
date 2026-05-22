# Deploy to Hugging Face Spaces

The easiest free way to host the dashboard online — about 10 minutes
end-to-end. You get a private HTTPS URL like
`https://<your-handle>-healthproject.hf.space` with the full dashboard
(heatmap, year review, Apple Health, profile, routines) and chat backed
by Groq's free hosted Llama 3.3.

## Privacy trade-offs — read this first

- **Make the Space private.** Otherwise anyone on the internet can read
  your data and call write endpoints (`/api/reload`, `/api/planned`,
  routine save/clear, etc). There is no auth in this app.
- **Chat goes to Groq.** Your raw CSV/DB stays on the box, but every
  question + the JSON tool outputs the model sees are sent to Groq's
  servers. The local Ollama path (the README setup) is the only one
  that's truly local.
- **Free Spaces have ephemeral storage.** `data.db` is rebuilt from
  `workout_data.csv` on every container restart. That's fine for the
  dashboard but means anything chat writes (planned workouts, saved
  routine, profile edits) is wiped on restart. Persistent storage costs
  $5/mo on HF.

## Steps

### 1. Get a Groq API key

- Sign up at <https://console.groq.com> — free, no card required.
- Create an API key and copy it. You'll paste it in step 4.

### 2. Create a private Space

- Go to <https://huggingface.co/new-space>.
- Owner = you, name = anything (e.g. `healthproject`).
- **Visibility = Private.**
- SDK = Docker (auto-detected from the `Dockerfile` in this repo).

### 3. Push the repo to the Space

```bash
# From this repo
huggingface-cli login          # paste your HF write token

git remote add space https://huggingface.co/spaces/<USER>/<SPACE>

# workout_data.csv is gitignored on purpose (so you don't accidentally
# leak it to a public GitHub repo). Force-add it for the Space remote.
git add -f workout_data.csv
git commit -m "Add workout data for HF deploy"

git push space main
```

If you also want Apple Health on the deploy, `git add -f apple_health_export/`
before committing. The `export.xml` can be ~500 MB so that push will be slow.

### 4. Set the Groq secret in the Space

In the Space → **Settings → Variables and secrets**:

- Add a **Secret**: name `GROQ_API_KEY`, value from step 1.
- (Optional) Add a **Variable**: `LLM_MODEL=llama-3.3-70b-versatile` if
  you want to override the default.

The Space rebuilds and restarts automatically. Open the URL shown on the
Space page — you're live.

## Switching back to local Ollama

The chat layer is provider-aware: if `GROQ_API_KEY` is unset, it talks to
Ollama at `http://127.0.0.1:11434/v1` (Ollama's OpenAI-compatible API).
So the local `./run.sh` workflow from the README still works unchanged
as long as you don't have `GROQ_API_KEY` exported in your shell.

| Want to run...                | Set this                                      |
| ----------------------------- | --------------------------------------------- |
| Local Ollama (default)        | nothing — just run `ollama serve` + `./run.sh` |
| Groq hosted                   | `GROQ_API_KEY=...`                             |
| OpenAI hosted                 | `OPENAI_API_KEY=...`                           |
| Override the model anywhere   | `LLM_MODEL=...`                                |

## What this deploys

- The full FastAPI app on port 7860 (HF's standard).
- Reads `workout_data.csv` on first boot, writes `data.db`, serves the
  dashboard at `/`.
- Apple Health panel auto-loads if `apple_health_export/export.xml` is
  in the image; otherwise the panel shows empty state gracefully.
- Chat uses Groq if `GROQ_API_KEY` is set, otherwise falls back to local
  Ollama (which won't be reachable from inside an HF container, so leave
  Groq set on hosted deploys).
