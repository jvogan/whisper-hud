#!/bin/bash
#
# Create a DMG installer for WhisperHUD
#
# Usage:
#   ./scripts/build-dmg.sh [--sign]
#
# Options:
#   --sign    Code sign the DMG (requires Developer ID)
#
# This creates a beautiful drag-to-Applications DMG with:
#   - Custom background image
#   - App icon positioned for easy drag
#   - Applications folder alias
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
ASSETS_DIR="$PROJECT_ROOT/assets"
APP_NAME="WhisperHUD"
APP_PATH="$DIST_DIR/$APP_NAME.app"

# DMG settings
DMG_NAME="$APP_NAME"
DMG_PATH="$DIST_DIR/$DMG_NAME.dmg"
DMG_TEMP="$DIST_DIR/$DMG_NAME-temp.dmg"
VOLUME_NAME="$APP_NAME"
DMG_BACKGROUND="$ASSETS_DIR/dmg/background.png"

# Window settings
WINDOW_WIDTH=540
WINDOW_HEIGHT=380
ICON_SIZE=128
APP_X=135
APP_Y=190
APPLICATIONS_X=405
APPLICATIONS_Y=190

# Parse arguments
SIGN_DMG=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --sign)
            SIGN_DMG=true
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
echo "║              WhisperHUD DMG Creator                       ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check app exists
if [ ! -d "$APP_PATH" ]; then
    echo -e "${RED}Error: App not found at $APP_PATH${NC}"
    echo -e "${YELLOW}Run './scripts/build-app.sh' first${NC}"
    exit 1
fi

# Get version from app bundle
VERSION=$(defaults read "$APP_PATH/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo "1.0.0")
DMG_FINAL="$DIST_DIR/$APP_NAME-$VERSION.dmg"

echo -e "Building DMG for ${CYAN}$APP_NAME v$VERSION${NC}"
echo ""

# Generate DMG background if it doesn't exist
if [ ! -f "$DMG_BACKGROUND" ]; then
    echo -e "${YELLOW}DMG background not found. Generating...${NC}"
    mkdir -p "$ASSETS_DIR/dmg"

    # Generate background using Python
    python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, 'assets')
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow not available, creating simple background")
    # Create a simple solid color PNG
    import struct
    import zlib

    width, height = 540, 380

    def create_png(width, height, r, g, b):
        def output_chunk(chunk_type, data):
            return struct.pack('>I', len(data)) + chunk_type + data + struct.pack('>I', zlib.crc32(chunk_type + data) & 0xffffffff)

        raw_data = b''
        for y in range(height):
            raw_data += b'\x00'  # filter byte
            for x in range(width):
                # Gradient from cyan to purple
                t = (x / width + y / height) / 2
                cr = int(0 + (189 - 0) * t)
                cg = int(212 + (0 - 212) * t)
                cb = int(255 + (255 - 255) * t)
                raw_data += bytes([cr, cg, cb])

        header = b'\x89PNG\r\n\x1a\n'
        ihdr = output_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
        idat = output_chunk(b'IDAT', zlib.compress(raw_data, 9))
        iend = output_chunk(b'IEND', b'')

        return header + ihdr + idat + iend

    png_data = create_png(width, height, 0, 212, 255)
    with open('assets/dmg/background.png', 'wb') as f:
        f.write(png_data)
    sys.exit(0)

# Create DMG background with Pillow
width, height = 540, 380

# Create gradient background
img = Image.new('RGB', (width, height))
for y in range(height):
    for x in range(width):
        t = (x / width + y / height) / 2
        r = int(0 + (189 - 0) * t)
        g = int(212 + (0 - 212) * t)
        b = 255
        img.putpixel((x, y), (r, g, b))

draw = ImageDraw.Draw(img)

# Add subtle grid pattern
for i in range(0, height, 40):
    draw.line([(0, i), (width, i)], fill=(255, 255, 255, 20), width=1)

# Add arrow pointing from app to Applications
arrow_y = 190
draw.line([(200, arrow_y), (340, arrow_y)], fill=(255, 255, 255), width=3)
# Arrowhead
draw.polygon([(340, arrow_y), (320, arrow_y - 10), (320, arrow_y + 10)], fill=(255, 255, 255))

# Add "Drag to Install" text area (white rounded rect)
draw.rounded_rectangle([120, 300, 420, 340], radius=10, fill=(255, 255, 255, 180))

img.save('assets/dmg/background.png', 'PNG')
print("Background created")
PYTHON_SCRIPT

    if [ -f "$DMG_BACKGROUND" ]; then
        echo -e "${GREEN}✓ Background generated${NC}"
    else
        echo -e "${YELLOW}Using plain background${NC}"
    fi
fi

# Clean up existing DMGs
rm -f "$DMG_PATH" "$DMG_TEMP" "$DMG_FINAL"

# Calculate DMG size (app size + 50MB buffer)
APP_SIZE_MB=$(du -sm "$APP_PATH" | cut -f1)
DMG_SIZE_MB=$((APP_SIZE_MB + 50))

echo -e "${CYAN}Creating DMG (${DMG_SIZE_MB}MB)...${NC}"

# Create temporary DMG
hdiutil create -srcfolder "$APP_PATH" \
    -volname "$VOLUME_NAME" \
    -fs HFS+ \
    -fsargs "-c c=64,a=16,e=16" \
    -format UDRW \
    -size "${DMG_SIZE_MB}m" \
    "$DMG_TEMP"

# Mount the DMG
echo -e "${CYAN}Mounting DMG...${NC}"
MOUNT_DIR=$(hdiutil attach -readwrite -noverify "$DMG_TEMP" | grep "/Volumes" | sed 's/.*\(\/Volumes\/.*\)/\1/')
echo -e "  Mounted at: $MOUNT_DIR"

# Create Applications symlink
echo -e "${CYAN}Adding Applications symlink...${NC}"
ln -sf /Applications "$MOUNT_DIR/Applications"

# Set DMG window properties using AppleScript
echo -e "${CYAN}Configuring DMG appearance...${NC}"

# Copy background if it exists
if [ -f "$DMG_BACKGROUND" ]; then
    mkdir -p "$MOUNT_DIR/.background"
    cp "$DMG_BACKGROUND" "$MOUNT_DIR/.background/background.png"
    HAS_BACKGROUND=true
else
    HAS_BACKGROUND=false
fi

# Apply styling with AppleScript
osascript << EOF
tell application "Finder"
    tell disk "$VOLUME_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {100, 100, $((100 + WINDOW_WIDTH)), $((100 + WINDOW_HEIGHT))}

        set theViewOptions to icon view options of container window
        set arrangement of theViewOptions to not arranged
        set icon size of theViewOptions to $ICON_SIZE

        $(if [ "$HAS_BACKGROUND" = true ]; then
            echo "set background picture of theViewOptions to file \".background:background.png\""
        fi)

        -- Position icons
        set position of item "$APP_NAME.app" to {$APP_X, $APP_Y}
        set position of item "Applications" to {$APPLICATIONS_X, $APPLICATIONS_Y}

        update without registering applications
        close
    end tell
end tell
EOF

# Give Finder time to write .DS_Store
sleep 2

# Sync and unmount
echo -e "${CYAN}Finalizing...${NC}"
sync
hdiutil detach "$MOUNT_DIR"

# Convert to compressed DMG
echo -e "${CYAN}Compressing DMG...${NC}"
hdiutil convert "$DMG_TEMP" \
    -format UDZO \
    -imagekey zlib-level=9 \
    -o "$DMG_FINAL"

# Clean up temp DMG
rm -f "$DMG_TEMP"

# Sign DMG if requested
if [ "$SIGN_DMG" = true ]; then
    echo -e "${CYAN}Signing DMG...${NC}"

    # Find identity
    IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | sed 's/.*"\(.*\)".*/\1/' || echo "-")

    if [ "$IDENTITY" != "-" ]; then
        codesign --force --sign "$IDENTITY" "$DMG_FINAL"
        echo -e "${GREEN}✓ DMG signed${NC}"
    else
        echo -e "${YELLOW}No Developer ID found, DMG unsigned${NC}"
    fi
fi

# Create symlink without version
ln -sf "$(basename "$DMG_FINAL")" "$DMG_PATH"

# Get final size
DMG_SIZE=$(du -h "$DMG_FINAL" | cut -f1)

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ DMG created successfully!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  File:     ${CYAN}$DMG_FINAL${NC}"
echo -e "  Size:     ${CYAN}$DMG_SIZE${NC}"
echo -e "  Version:  ${CYAN}$VERSION${NC}"
echo ""
echo -e "  Test:     ${YELLOW}open \"$DMG_FINAL\"${NC}"
echo ""
echo -e "  The DMG contains:"
echo -e "    - $APP_NAME.app"
echo -e "    - Applications folder shortcut"
if [ "$HAS_BACKGROUND" = true ]; then
    echo -e "    - Custom background image"
fi
echo ""
