#!/usr/bin/env bash
#
# Build Apple Translation helper (macOS 26+)
#
# Usage:
#   ./scripts/build-apple-translate.sh
#
# Notes:
# - Requires Xcode Command Line Tools (swiftc)
# - Translation framework is only available on macOS 26+
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HELPER_SRC="$PROJECT_ROOT/whisper-hud/apple-translate-helper/main.swift"
OUT_DIR="$PROJECT_ROOT/whisper-hud/bin"
OUT_BIN="$OUT_DIR/whisperhud-apple-translate"

if ! command -v swiftc >/dev/null 2>&1; then
    echo "swiftc not found; skipping Apple Translation helper build."
    exit 0
fi

if ! command -v sw_vers >/dev/null 2>&1; then
    echo "sw_vers not available; skipping Apple Translation helper build."
    exit 0
fi

MACOS_VERSION="$(sw_vers -productVersion)"
MACOS_MAJOR="$(echo "$MACOS_VERSION" | cut -d. -f1)"

if [ "$MACOS_MAJOR" -lt 26 ]; then
    echo "Apple Translation requires macOS 26+. Found $MACOS_VERSION; skipping."
    exit 0
fi

mkdir -p "$OUT_DIR"

swiftc -parse-as-library \
    -module-cache-path /tmp/whisperhud-swift-module-cache \
    "$HELPER_SRC" \
    -o "$OUT_BIN"

echo "✓ Built Apple Translation helper: $OUT_BIN"
