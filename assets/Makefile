# WhisperHUD Asset Build System
#
# Usage:
#   make all       - Generate all assets
#   make icons     - Generate app icons only
#   make icns      - Compile .icns from iconset
#   make dithered  - Generate dithered graphics
#   make social    - Generate social media graphics
#   make clean     - Remove generated assets
#
# Requirements:
#   - Python 3.8+
#   - Pillow (pip install Pillow)
#   - numpy (pip install numpy)
#   - iconutil (macOS only, for .icns compilation)

PYTHON ?= python3
ICONUTIL ?= iconutil
ASSET_SCRIPT = generate_assets.py

# Directories
ICONS_DIR = icons
ICONSET_DIR = $(ICONS_DIR)/icon.iconset
DITHERED_DIR = dithered
SOCIAL_DIR = social

# Output files
ICNS_FILE = $(ICONS_DIR)/AppIcon.icns
SVG_FILE = $(ICONS_DIR)/icon.svg

# Icon sizes (standard + @2x)
ICON_SIZES = 16 32 64 128 256 512 1024
ICON_FILES = $(foreach size,$(ICON_SIZES),$(ICONSET_DIR)/icon_$(size)x$(size).png)

.PHONY: all icons dithered social icns clean help install-deps check-deps

# Default target
all: check-deps icons dithered social
	@echo ""
	@echo "All assets generated successfully!"
	@echo "See: icons/, dithered/, social/"

# Generate app icons
icons: check-deps
	@echo "Generating app icons..."
	$(PYTHON) $(ASSET_SCRIPT) --icons --svg
	@echo "Done!"

# Compile iconset to .icns (macOS only)
icns: $(ICNS_FILE)

$(ICNS_FILE): $(ICON_FILES)
	@echo "Compiling .icns file..."
	@if command -v $(ICONUTIL) > /dev/null 2>&1; then \
		$(ICONUTIL) -c icns $(ICONSET_DIR) -o $(ICNS_FILE); \
		echo "Generated: $(ICNS_FILE)"; \
	else \
		echo "Warning: iconutil not found (macOS only)"; \
	fi

# Generate dithered graphics
dithered: check-deps
	@echo "Generating dithered graphics..."
	$(PYTHON) $(ASSET_SCRIPT) --dithered
	@echo "Done!"

# Generate social media graphics
social: check-deps
	@echo "Generating social media graphics..."
	$(PYTHON) $(ASSET_SCRIPT) --social
	@echo "Done!"

# Check dependencies
check-deps:
	@$(PYTHON) -c "import PIL, numpy" 2>/dev/null || { \
		echo "Missing dependencies. Run: make install-deps"; \
		exit 1; \
	}

# Install Python dependencies
install-deps:
	@echo "Installing Python dependencies..."
	pip install Pillow numpy
	@echo "Done!"

# Clean generated assets
clean:
	@echo "Cleaning generated assets..."
	rm -f $(ICONSET_DIR)/*.png
	rm -f $(ICNS_FILE)
	rm -f $(SVG_FILE)
	rm -f $(DITHERED_DIR)/*.png
	rm -f $(SOCIAL_DIR)/*.png
	@echo "Done!"

# Deep clean (remove directories too)
distclean: clean
	rm -rf $(ICONSET_DIR)
	rm -rf $(DITHERED_DIR)
	rm -rf $(SOCIAL_DIR)

# Help
help:
	@echo "WhisperHUD Asset Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all         Generate all assets (default)"
	@echo "  icons       Generate app icons (PNG + SVG)"
	@echo "  icns        Compile .icns from iconset (macOS only)"
	@echo "  dithered    Generate dithered graphics"
	@echo "  social      Generate social media graphics"
	@echo "  clean       Remove generated assets"
	@echo "  distclean   Remove assets and directories"
	@echo "  install-deps Install Python dependencies"
	@echo ""
	@echo "Requirements:"
	@echo "  Python 3.8+ with Pillow and numpy"
	@echo "  iconutil (macOS) for .icns compilation"
