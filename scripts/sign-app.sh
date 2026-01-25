#!/bin/bash
#
# Code sign WhisperHUD.app for macOS distribution
#
# Usage:
#   ./scripts/sign-app.sh [--identity "Developer ID"] [--notarize]
#
# Options:
#   --identity    Code signing identity (default: auto-detect or ad-hoc)
#   --notarize    Submit to Apple for notarization
#
# Environment variables:
#   DEVELOPER_ID       - Apple Developer ID certificate name
#   APPLE_ID           - Apple ID email for notarization
#   APPLE_PASSWORD     - App-specific password for notarization
#   APPLE_TEAM_ID      - Apple Developer Team ID
#
# For local testing without a certificate:
#   The script will use ad-hoc signing if no certificate is available.
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Project paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_ROOT/dist"
APP_NAME="WhisperHUD"
APP_PATH="$DIST_DIR/$APP_NAME.app"
ENTITLEMENTS="$PROJECT_ROOT/entitlements.plist"

# Default options
IDENTITY=""
NOTARIZE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --identity)
            IDENTITY="$2"
            shift 2
            ;;
        --notarize)
            NOTARIZE=true
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
echo "║              WhisperHUD Code Signing                      ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check app exists
if [ ! -d "$APP_PATH" ]; then
    echo -e "${RED}Error: App not found at $APP_PATH${NC}"
    echo -e "${YELLOW}Run './scripts/build-app.sh' first${NC}"
    exit 1
fi

# Auto-detect identity if not provided
if [ -z "$IDENTITY" ]; then
    # Check environment variable
    if [ -n "$DEVELOPER_ID" ]; then
        IDENTITY="$DEVELOPER_ID"
        echo -e "${GREEN}Using DEVELOPER_ID from environment${NC}"
    else
        # Try to find a Developer ID certificate
        FOUND_ID=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | sed 's/.*"\(.*\)".*/\1/' || true)
        if [ -n "$FOUND_ID" ]; then
            IDENTITY="$FOUND_ID"
            echo -e "${GREEN}Found Developer ID: $IDENTITY${NC}"
        else
            echo -e "${YELLOW}No Developer ID certificate found${NC}"
            echo -e "${YELLOW}Using ad-hoc signing (suitable for local testing only)${NC}"
            IDENTITY="-"
        fi
    fi
fi

# Sign the app
echo -e "${CYAN}Signing $APP_NAME.app...${NC}"

# Remove any existing signatures
echo -e "  Removing existing signatures..."
codesign --remove-signature "$APP_PATH" 2>/dev/null || true

# Sign embedded frameworks and libraries first
echo -e "  Signing embedded frameworks..."
find "$APP_PATH/Contents/Frameworks" -type f -name "*.dylib" 2>/dev/null | while read -r lib; do
    codesign --force --sign "$IDENTITY" \
        --options runtime \
        --entitlements "$ENTITLEMENTS" \
        "$lib" 2>/dev/null || true
done

find "$APP_PATH/Contents/Frameworks" -type d -name "*.framework" 2>/dev/null | while read -r framework; do
    codesign --force --sign "$IDENTITY" \
        --options runtime \
        --entitlements "$ENTITLEMENTS" \
        "$framework" 2>/dev/null || true
done

# Sign Python.framework if present
if [ -d "$APP_PATH/Contents/Frameworks/Python.framework" ]; then
    echo -e "  Signing Python.framework..."
    codesign --force --deep --sign "$IDENTITY" \
        --options runtime \
        --entitlements "$ENTITLEMENTS" \
        "$APP_PATH/Contents/Frameworks/Python.framework"
fi

# Sign Sparkle.framework if present
if [ -d "$APP_PATH/Contents/Frameworks/Sparkle.framework" ]; then
    echo -e "  Signing Sparkle.framework..."
    codesign --force --deep --sign "$IDENTITY" \
        --options runtime \
        "$APP_PATH/Contents/Frameworks/Sparkle.framework"
fi

# Sign the main app bundle
echo -e "  Signing main app bundle..."
codesign --force --deep --sign "$IDENTITY" \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    "$APP_PATH"

# Verify signature
echo -e "${CYAN}Verifying signature...${NC}"
if codesign --verify --verbose=2 "$APP_PATH" 2>&1; then
    echo -e "${GREEN}✓ Signature verified${NC}"
else
    echo -e "${RED}Signature verification failed${NC}"
    exit 1
fi

# Check Gatekeeper assessment
echo -e "${CYAN}Checking Gatekeeper assessment...${NC}"
if spctl --assess --verbose=2 "$APP_PATH" 2>&1; then
    echo -e "${GREEN}✓ Gatekeeper assessment passed${NC}"
else
    if [ "$IDENTITY" = "-" ]; then
        echo -e "${YELLOW}○ Gatekeeper rejects ad-hoc signed apps (expected)${NC}"
    else
        echo -e "${YELLOW}○ Gatekeeper assessment failed (notarization may be needed)${NC}"
    fi
fi

# Notarization
if [ "$NOTARIZE" = true ]; then
    echo -e "${CYAN}Submitting for notarization...${NC}"

    # Check required environment variables
    if [ -z "$APPLE_ID" ] || [ -z "$APPLE_PASSWORD" ] || [ -z "$APPLE_TEAM_ID" ]; then
        echo -e "${RED}Error: Notarization requires APPLE_ID, APPLE_PASSWORD, and APPLE_TEAM_ID${NC}"
        exit 1
    fi

    # Create a zip for notarization
    NOTARIZE_ZIP="$DIST_DIR/$APP_NAME-notarize.zip"
    echo -e "  Creating zip for notarization..."
    ditto -c -k --keepParent "$APP_PATH" "$NOTARIZE_ZIP"

    # Submit for notarization
    echo -e "  Submitting to Apple..."
    xcrun notarytool submit "$NOTARIZE_ZIP" \
        --apple-id "$APPLE_ID" \
        --password "$APPLE_PASSWORD" \
        --team-id "$APPLE_TEAM_ID" \
        --wait

    # Staple the ticket
    echo -e "  Stapling notarization ticket..."
    xcrun stapler staple "$APP_PATH"

    # Clean up
    rm -f "$NOTARIZE_ZIP"

    echo -e "${GREEN}✓ Notarization complete${NC}"
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Code signing complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$IDENTITY" = "-" ]; then
    echo -e "  ${YELLOW}Note: Ad-hoc signed (local testing only)${NC}"
    echo -e "  ${YELLOW}For distribution, sign with a Developer ID certificate${NC}"
else
    echo -e "  Signed with: ${CYAN}$IDENTITY${NC}"
fi

if [ "$NOTARIZE" = true ]; then
    echo -e "  ${GREEN}✓ Notarized by Apple${NC}"
fi

echo ""
echo -e "  Next: ${CYAN}./scripts/build-dmg.sh${NC}"
echo ""
