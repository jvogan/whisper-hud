#!/bin/bash
#
# Build WhisperHUD.app using py2app
#
# Usage:
#   ./scripts/build-app.sh [--clean] [--sparkle]
#
# Options:
#   --clean    Remove existing build artifacts before building
#   --sparkle  Include Sparkle.framework for auto-updates
#
# Requirements:
#   - Python 3.11+
#   - py2app already installed in the selected interpreter
#   - app dependencies already installed in the selected interpreter
#   - Sparkle.framework (optional, for auto-updates)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Project paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_ROOT/dist"
BUILD_DIR="$PROJECT_ROOT/build"
APP_NAME="WhisperHUD"
PROJECT_VENV_PYTHON="$PROJECT_ROOT/whisper-hud/venv/bin/python"

is_python_311_plus() {
    local candidate="$1"
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

read_plist_value() {
    local plist_path="$1"
    local key="$2"
    /usr/libexec/PlistBuddy -c "Print :$key" "$plist_path" 2>/dev/null || true
}

verify_sparkle_framework() {
    local candidate="$1"
    local info_plist="$candidate/Resources/Info.plist"
    local bundle_id=""

    if [ ! -f "$info_plist" ]; then
        echo -e "${YELLOW}Warning: Sparkle Info.plist missing at $info_plist${NC}"
        return 1
    fi

    bundle_id="$(read_plist_value "$info_plist" "CFBundleIdentifier")"
    if [ "$bundle_id" != "org.sparkle-project.Sparkle" ]; then
        echo -e "${YELLOW}Warning: Refusing Sparkle.framework with unexpected bundle ID '$bundle_id'${NC}"
        return 1
    fi

    if ! codesign --verify --deep --strict "$candidate" >/dev/null 2>&1; then
        echo -e "${YELLOW}Warning: Refusing unsigned or invalid Sparkle.framework at $candidate${NC}"
        return 1
    fi

    return 0
}

# Parse arguments
CLEAN=false
INCLUDE_SPARKLE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN=true
            shift
            ;;
        --sparkle)
            INCLUDE_SPARKLE=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                WhisperHUD App Builder                     ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Clean if requested
if [ "$CLEAN" = true ]; then
    echo -e "${YELLOW}Cleaning previous build artifacts...${NC}"
    rm -rf "$BUILD_DIR" "$DIST_DIR"
    rm -rf "$PROJECT_ROOT"/*.egg-info
    rm -rf "$PROJECT_ROOT/whisper-hud/whisper_hud.egg-info"
    echo -e "${GREEN}✓ Cleaned${NC}"
fi

# Resolve Python binary (allow override with PYTHON_BIN)
if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "$PROJECT_VENV_PYTHON" ] && is_python_311_plus "$PROJECT_VENV_PYTHON"; then
        PYTHON_BIN="$PROJECT_VENV_PYTHON"
    elif command -v python3.11 >/dev/null 2>&1 && is_python_311_plus "$(command -v python3.11)"; then
        PYTHON_BIN="$(command -v python3.11)"
    elif command -v python3 >/dev/null 2>&1 && is_python_311_plus "$(command -v python3)"; then
        PYTHON_BIN="$(command -v python3)"
    else
        echo -e "${RED}Error: Python not found${NC}"
        exit 1
    fi
fi

# Check Python version
echo -e "${CYAN}Checking Python version...${NC}"
PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo -e "${RED}Error: Python 3.11+ required, found $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $PYTHON_VERSION (${PYTHON_BIN})${NC}"

# Check py2app
echo -e "${CYAN}Checking py2app...${NC}"
if ! "$PYTHON_BIN" -c "import py2app" 2>/dev/null; then
    echo -e "${RED}Error: py2app is not installed for ${PYTHON_BIN}${NC}"
    echo -e "${YELLOW}Refusing to auto-install release dependencies during the build.${NC}"
    echo -e "${YELLOW}Tip:${NC} Use the project virtualenv Python or set PYTHON_BIN explicitly."
    echo -e "  ${CYAN}cd \"$PROJECT_ROOT/whisper-hud\" && python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt${NC}"
    echo -e "  ${CYAN}PYTHON_BIN=\"$PROJECT_ROOT/whisper-hud/venv/bin/python\" ./scripts/build-app.sh --clean${NC}"
    exit 1
fi
echo -e "${GREEN}✓ py2app available${NC}"

# Check runtime dependencies used by the app bundle
echo -e "${CYAN}Checking app dependencies...${NC}"
if ! MISSING_MODULES="$("$PYTHON_BIN" - <<'PY'
import importlib

required = [
    "rumps",
    "pynput",
    "sounddevice",
    "numpy",
    "scipy",
    "openai",
    "anthropic",
    "google.genai",
    "keyring",
    "pyperclip",
]
missing = []
for mod in required:
    try:
        importlib.import_module(mod)
    except Exception:
        missing.append(mod)

if missing:
    print(",".join(missing))
    raise SystemExit(1)
PY
)"; then
    echo -e "${RED}Error: Missing app dependencies for ${PYTHON_BIN}${NC}"
    if [ -n "$MISSING_MODULES" ]; then
        echo -e "  Missing modules: ${YELLOW}$MISSING_MODULES${NC}"
    fi
    echo -e "${YELLOW}Refusing to auto-install release dependencies during the build.${NC}"
    echo -e "${YELLOW}Tip:${NC} Install the pinned project requirements first."
    echo -e "  ${CYAN}cd \"$PROJECT_ROOT/whisper-hud\" && source venv/bin/activate && pip install -r requirements.txt${NC}"
    exit 1
fi
echo -e "${GREEN}✓ App dependencies available${NC}"

# Check for Sparkle.framework
SPARKLE_PATH=""
if [ "$INCLUDE_SPARKLE" = true ]; then
    echo -e "${CYAN}Checking for Sparkle.framework...${NC}"

    SPARKLE_OVERRIDE="${WHISPERHUD_SPARKLE_PATH:-}"
    SPARKLE_LOCATIONS=()
    if [ -n "$SPARKLE_OVERRIDE" ]; then
        SPARKLE_LOCATIONS+=("$SPARKLE_OVERRIDE")
    fi
    SPARKLE_LOCATIONS+=("$PROJECT_ROOT/Frameworks/Sparkle.framework")

    for loc in "${SPARKLE_LOCATIONS[@]}"; do
        if [ -d "$loc" ] && verify_sparkle_framework "$loc"; then
            SPARKLE_PATH="$loc"
            break
        fi
    done

    if [ -n "$SPARKLE_PATH" ]; then
        echo -e "${GREEN}✓ Found Sparkle at $SPARKLE_PATH${NC}"
    else
        echo -e "${YELLOW}Warning: Sparkle.framework not found. Auto-updates will be disabled.${NC}"
        echo -e "${YELLOW}To include Sparkle, place it at $PROJECT_ROOT/Frameworks/Sparkle.framework or set WHISPERHUD_SPARKLE_PATH.${NC}"
    fi
fi

# Ensure assets are generated
echo -e "${CYAN}Ensuring assets are up to date...${NC}"
if [ ! -f "$PROJECT_ROOT/assets/icons/AppIcon.icns" ]; then
    echo -e "${YELLOW}Generating assets...${NC}"
    cd "$PROJECT_ROOT/assets"
    "$PYTHON_BIN" generate_assets.py --icons --svg
fi
echo -e "${GREEN}✓ Assets ready${NC}"

# Build Apple Translation helper if supported
if [ -f "$PROJECT_ROOT/scripts/build-apple-translate.sh" ]; then
    echo -e "${CYAN}Building Apple Translation helper (if supported)...${NC}"
    "$PROJECT_ROOT/scripts/build-apple-translate.sh" || true
fi

# Build the app
echo -e "${CYAN}Building $APP_NAME.app...${NC}"
cd "$PROJECT_ROOT"

# Set environment for build
export PYTHONPATH="$PROJECT_ROOT/whisper-hud:$PYTHONPATH"

# Run py2app
"$PYTHON_BIN" setup_app.py py2app --dist-dir "$DIST_DIR" --bdist-base "$BUILD_DIR"

# Verify app was created
APP_PATH="$DIST_DIR/$APP_NAME.app"
if [ ! -d "$APP_PATH" ]; then
    echo -e "${RED}Error: App bundle was not created${NC}"
    exit 1
fi
echo -e "${GREEN}✓ App bundle created${NC}"

# Copy Sparkle.framework if available
if [ -n "$SPARKLE_PATH" ] && [ -d "$SPARKLE_PATH" ]; then
    echo -e "${CYAN}Embedding Sparkle.framework...${NC}"
    FRAMEWORKS_DIR="$APP_PATH/Contents/Frameworks"
    mkdir -p "$FRAMEWORKS_DIR"
    cp -R "$SPARKLE_PATH" "$FRAMEWORKS_DIR/"
    echo -e "${GREEN}✓ Sparkle embedded${NC}"
fi

# Copy assets into bundle (ensure they're in the right place)
echo -e "${CYAN}Copying assets...${NC}"
RESOURCES_DIR="$APP_PATH/Contents/Resources"
mkdir -p "$RESOURCES_DIR/assets"
cp -R "$PROJECT_ROOT/assets/icons" "$RESOURCES_DIR/assets/"
cp -R "$PROJECT_ROOT/assets/dithered" "$RESOURCES_DIR/assets/" 2>/dev/null || true
cp -R "$PROJECT_ROOT/assets/ascii" "$RESOURCES_DIR/assets/" 2>/dev/null || true
cp -R "$PROJECT_ROOT/assets/character-packs" "$RESOURCES_DIR/assets/" 2>/dev/null || true
echo -e "${GREEN}✓ Assets copied${NC}"

# Get app size
APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Build complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  App:      ${CYAN}$APP_PATH${NC}"
echo -e "  Size:     ${CYAN}$APP_SIZE${NC}"
echo ""
echo -e "  Test:     ${YELLOW}open \"$APP_PATH\"${NC}"
echo ""

if [ -n "$SPARKLE_PATH" ]; then
    echo -e "  ${GREEN}✓ Sparkle auto-updates enabled${NC}"
else
    echo -e "  ${YELLOW}○ Sparkle not included (no auto-updates)${NC}"
fi

echo ""
echo -e "  Next steps:"
echo -e "    1. Test the app: ${CYAN}open \"$APP_PATH\"${NC}"
echo -e "    2. Code sign:    ${CYAN}./scripts/sign-app.sh${NC}"
echo -e "    3. Create DMG:   ${CYAN}./scripts/build-dmg.sh${NC}"
echo ""
