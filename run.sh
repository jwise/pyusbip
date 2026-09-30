#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=.venv
INSTALLED_STAMP="$VENV_DIR/.requirements-installed"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi

if [ ! -f "$INSTALLED_STAMP" ] || [ requirements.txt -nt "$INSTALLED_STAMP" ]; then
  "$VENV_DIR/bin/pip" install --quiet -r requirements.txt
  touch "$INSTALLED_STAMP"
fi

exec "$VENV_DIR/bin/python" pyusbip.py "$@"
