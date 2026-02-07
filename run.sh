#!/bin/bash
# run.sh - Launch WhisperHUD
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/whisper-hud"
VENV_ACTIVATE="$APP_DIR/venv/bin/activate"

if [[ ! -d "$APP_DIR" ]]; then
    echo "Error: Could not find app directory at $APP_DIR"
    echo "Run this script from the WhisperHUD repository root."
    exit 1
fi

cd "$APP_DIR"

if [[ -f "$SCRIPT_DIR/scripts/build-apple-translate.sh" && ! -x "$APP_DIR/bin/whisperhud-apple-translate" ]]; then
    "$SCRIPT_DIR/scripts/build-apple-translate.sh" || true
fi

if [[ ! -f "$VENV_ACTIVATE" ]]; then
    echo "WhisperHUD virtual environment not found."
    echo "Run ./install.sh first, then try ./run.sh again."
    exit 1
fi

source "$VENV_ACTIVATE"
exec python -m whisper_hud.main
