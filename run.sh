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

PYTHON_PATH="$(python -c 'import sys; print(sys.executable)')"
APP_VERSION="$(python -c 'from whisper_hud import __version__; print(__version__)')"
printf 'WhisperHUD v%s | Python: %s\n' "$APP_VERSION" "$PYTHON_PATH" >&2

if [[ "$(uname -s)" == "Darwin" ]]; then
    MACOS_VERSION="$(sw_vers -productVersion 2>/dev/null || true)"
    MACOS_MAJOR="${MACOS_VERSION%%.*}"
    if [[ -n "$MACOS_MAJOR" ]] && [[ "$MACOS_MAJOR" =~ ^[0-9]+$ ]] && (( MACOS_MAJOR < 14 )); then
        printf 'Apple Translation requires macOS 14+, this provider will be unavailable\n' >&2
    fi
fi

exec python -m whisper_hud.main
