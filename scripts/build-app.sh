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
#   - py2app (pip install py2app)
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
    echo -e "${GREEN}✓ Cleaned${NC}"
fi

# Check Python version
echo -e "${CYAN}Checking Python version...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
if [[ "$(echo "$PYTHON_VERSION >= 3.11" | bc)" -ne 1 ]]; then
    echo -e "${RED}Error: Python 3.11+ required, found $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $PYTHON_VERSION${NC}"

# Check py2app
echo -e "${CYAN}Checking py2app...${NC}"
if ! python3 -c "import py2app" 2>/dev/null; then
    echo -e "${YELLOW}Installing py2app...${NC}"
    pip3 install py2app --quiet
fi
echo -e "${GREEN}✓ py2app available${NC}"

# Check for Sparkle.framework
SPARKLE_PATH=""
if [ "$INCLUDE_SPARKLE" = true ]; then
    echo -e "${CYAN}Checking for Sparkle.framework...${NC}"

    # Common Sparkle locations
    SPARKLE_LOCATIONS=(
        "/Library/Frameworks/Sparkle.framework"
        "$HOME/Library/Frameworks/Sparkle.framework"
        "/usr/local/Frameworks/Sparkle.framework"
        "$PROJECT_ROOT/Frameworks/Sparkle.framework"
    )

    for loc in "${SPARKLE_LOCATIONS[@]}"; do
        if [ -d "$loc" ]; then
            SPARKLE_PATH="$loc"
            break
        fi
    done

    if [ -n "$SPARKLE_PATH" ]; then
        echo -e "${GREEN}✓ Found Sparkle at $SPARKLE_PATH${NC}"
    else
        echo -e "${YELLOW}Warning: Sparkle.framework not found. Auto-updates will be disabled.${NC}"
        echo -e "${YELLOW}To install: brew install --cask sparkle${NC}"
    fi
fi

# Ensure assets are generated
echo -e "${CYAN}Ensuring assets are up to date...${NC}"
if [ ! -f "$PROJECT_ROOT/assets/icons/AppIcon.icns" ]; then
    echo -e "${YELLOW}Generating assets...${NC}"
    cd "$PROJECT_ROOT/assets"
    python3 generate_assets.py --icons --svg
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
python3 setup_app.py py2app --dist-dir "$DIST_DIR" --bdist-base "$BUILD_DIR"

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
