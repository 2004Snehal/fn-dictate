#!/usr/bin/env bash
# One-time setup for fn-dictate: Python venv, dependencies, and the Granite Speech model.
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${FN_DICTATE_MODEL:-hf.co/ibm-granite/granite-speech-4.1-2b-GGUF:Q8_0}"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "fn-dictate only works on macOS." >&2
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it with:  brew install ollama" >&2
  echo "or download it from https://ollama.com/download, then run this script again." >&2
  exit 1
fi

if ! ollama list >/dev/null 2>&1; then
  echo "Ollama is installed but not running. Start it with:  open -a Ollama   (or: brew services start ollama)" >&2
  exit 1
fi

PY="$(command -v python3 || true)"
if [[ -z "$PY" ]] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  echo "Python 3.9 or newer is required. Install it with:  brew install python" >&2
  exit 1
fi

echo "==> Creating virtual environment (.venv)"
"$PY" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
echo "==> Installing Python packages"
.venv/bin/pip install --quiet -r requirements.txt

echo "==> Downloading the speech model (about 3.1 GB, once)"
# Large downloads sometimes drop; ollama resumes where it stopped, so retry a few times.
for attempt in 1 2 3 4 5; do
  if ollama pull "$MODEL"; then
    break
  fi
  if [[ $attempt == 5 ]]; then
    echo "Model download failed 5 times. Run this script again to resume." >&2
    exit 1
  fi
  echo "Download interrupted, retrying ($attempt/5)..."
  sleep 3
done

chmod +x run.sh
echo
echo "Done. Test your microphone with:   ./run.sh --test"
echo "Then start dictating with:         ./run.sh"
