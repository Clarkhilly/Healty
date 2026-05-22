#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# Arch / Artix: ensure Python and pip packages are installed (system packages).
if command -v pacman >/dev/null 2>&1; then
  missing=()
  pacman -Qi python &>/dev/null || missing+=("python")
  pacman -Qi python-pip &>/dev/null || missing+=("python-pip")
  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "Install missing packages with:"
    echo "  sudo pacman -S --needed ${missing[*]}"
    exit 1
  fi
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

# Hugging Face CLI: use HF_TOKEN / HUGGINGFACE_HUB_TOKEN if set (CI/non-interactive).
if [[ -z "${HF_TOKEN:-}" && -z "${HUGGINGFACE_HUB_TOKEN:-}" ]]; then
  if hf auth whoami >/dev/null 2>&1; then
    :
  else
    hf auth login
  fi
fi

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
