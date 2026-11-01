#!/usr/bin/env bash
# Start fn-dictate. Extra arguments are passed through (see ./run.sh --help).
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Not installed yet. Run ./install.sh first." >&2
  exit 1
fi
exec .venv/bin/python fn_dictate.py "$@"
