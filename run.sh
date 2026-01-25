#!/bin/bash
# run.sh - Launch WhisperHUD
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/whisper-hud"
source venv/bin/activate
python -m whisper_hud.main
