#!/bin/bash
# run.sh - Launch WhisperHUD
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/whisper-hud"
if [ -f "$SCRIPT_DIR/scripts/build-apple-translate.sh" ]; then
    if [ ! -x "$SCRIPT_DIR/whisper-hud/bin/whisperhud-apple-translate" ]; then
        "$SCRIPT_DIR/scripts/build-apple-translate.sh" || true
    fi
fi
source venv/bin/activate
python -m whisper_hud.main
