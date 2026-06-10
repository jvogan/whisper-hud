"""
WhisperHUD Branding Assets

Centralizes access to visual branding assets including:
- ASCII art for terminal display
- Icon paths for menu bar and app
- Color palette definitions

Usage:
    from .branding import ASSETS, Colors, get_ascii_banner
"""

from pathlib import Path
from typing import Optional

# ============================================================================
# ASSET PATHS
# ============================================================================


def _find_assets_dir() -> Optional[Path]:
    """Locate the assets directory relative to this module."""
    # Try relative to this file (src/branding.py -> ../../assets)
    module_dir = Path(__file__).parent
    candidates = [
        module_dir.parent.parent / "assets",  # whisper-hud/whisper_hud -> whisper-hud/../assets
        module_dir.parent / "assets",  # Alternative location
        Path.cwd() / "assets",  # Current working directory
    ]

    for path in candidates:
        if path.is_dir():
            return path.resolve()

    return None


class AssetPaths:
    """Paths to WhisperHUD visual assets."""

    def __init__(self):
        self._base = _find_assets_dir()

    @property
    def base(self) -> Optional[Path]:
        """Base assets directory."""
        return self._base

    @property
    def ascii_dir(self) -> Optional[Path]:
        """ASCII art directory."""
        if self._base:
            return self._base / "ascii"
        return None

    @property
    def icons_dir(self) -> Optional[Path]:
        """Icons directory."""
        if self._base:
            return self._base / "icons"
        return None

    @property
    def dithered_dir(self) -> Optional[Path]:
        """Dithered graphics directory."""
        if self._base:
            return self._base / "dithered"
        return None

    @property
    def app_icon(self) -> Optional[Path]:
        """Path to the macOS .icns app icon."""
        if self._base:
            icns = self._base / "icons" / "AppIcon.icns"
            if icns.exists():
                return icns
        return None

    @property
    def svg_icon(self) -> Optional[Path]:
        """Path to the SVG vector icon."""
        if self._base:
            svg = self._base / "icons" / "icon.svg"
            if svg.exists():
                return svg
        return None

    def get_icon(self, size: int) -> Optional[Path]:
        """Get PNG icon at specified size (16, 32, 64, 128, 256, 512, 1024)."""
        if self._base:
            png = self._base / "icons" / "icon.iconset" / f"icon_{size}x{size}.png"
            if png.exists():
                return png
        return None

    def get_dithered_mic(self, size: int) -> Optional[Path]:
        """Get dithered microphone icon at specified size."""
        if self._base:
            png = self._base / "dithered" / f"mic_{size}.png"
            if png.exists():
                return png
        return None


# Singleton instance
ASSETS = AssetPaths()


# ============================================================================
# COLOR PALETTE
# ============================================================================


class Colors:
    """Official WhisperHUD color palette."""

    # Primary gradient colors (hex)
    CYAN = "#00D4FF"
    PURPLE = "#BD00FF"
    MID_PURPLE = "#7B61FF"

    # Background colors
    DARK_BG = "#0D1117"
    LIGHT_TEXT = "#E6EDF3"
    DIM_TEXT = "#8B949E"

    # Status colors
    SUCCESS = "#3FB950"
    RECORDING = "#F85149"
    PROCESSING = "#F0883E"

    # ANSI escape codes for terminal
    class ANSI:
        CYAN = "\033[0;36m"
        PURPLE = "\033[0;35m"
        GREEN = "\033[0;32m"
        RED = "\033[0;31m"
        YELLOW = "\033[0;33m"
        WHITE = "\033[1;37m"
        DIM = "\033[0;90m"
        RESET = "\033[0m"
        BOLD = "\033[1m"


# ============================================================================
# ASCII ART
# ============================================================================

# Inline fallback banners (in case files aren't found)
BANNER_WIDE = """
    ╭──────────────────────────────────────────────────╮
    │                                                  │
    │   ░▒▓█  W H I S P E R H U D  █▓▒░               │
    │                                                  │
    │      ┌───────────────────────┐                   │
    │      │   ◉ ── ╱╲ ── ◉       │   voice → text   │
    │      │   ░░▒▒▓▓██▓▓▒▒░░     │    invisibly     │
    │      └───────────────────────┘                   │
    │                                                  │
    ╰──────────────────────────────────────────────────╯
""".strip()

BANNER_COMPACT = """
┌─────────────────────┐
│  ◉ ╱╲  WHISPERHUD  │
│   ▓▓▓▓  voice→text │
└─────────────────────┘
""".strip()

STATE_RECORDING = """
   ◉ RECORDING ◉
  ═══════════════
  ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁
""".strip()

STATE_PROCESSING = """
   ⟳ Processing...
  ─────────────────
  ░░▒▒▓▓██▓▓▒▒░░
""".strip()

BANNER_INSTALLER = """
               ╭─────────────────────────────────────╮
               │                                     │
               │   ░▒▓  W H I S P E R H U D  ▓▒░    │
               │                                     │
               │      ┌─────────────────────┐        │
               │      │  ◉ ─ ─ ─ ╱╲ ─ ─ ─   │        │
               │      │    ░░▒▒▓▓██▓▓▒▒░░   │        │
               │      └─────────────────────┘        │
               │                                     │
               │   voice → text, invisibly           │
               │                                     │
               ╰─────────────────────────────────────╯
""".strip()


def get_ascii_banner(style: str = "wide") -> str:
    """
    Get ASCII banner art.

    Args:
        style: "wide", "compact", or "installer"

    Returns:
        ASCII art string
    """
    # Try to load from file
    if ASSETS.ascii_dir:
        filenames = {
            "wide": "banner_wide.txt",
            "compact": "banner_compact.txt",
            "installer": "banner_installer.txt",
        }

        filename = filenames.get(style, "banner_wide.txt")
        filepath = ASSETS.ascii_dir / filename

        if filepath.exists():
            try:
                return filepath.read_text().rstrip()
            except Exception:
                pass

    # Fallback to inline
    fallbacks = {
        "compact": BANNER_COMPACT,
        "installer": BANNER_INSTALLER,
        "wide": BANNER_WIDE,
    }
    return fallbacks.get(style, BANNER_WIDE)


def get_state_ascii(state: str) -> str:
    """
    Get ASCII art for a specific state.

    Args:
        state: "idle", "recording", "processing", "success", "error"

    Returns:
        ASCII art string
    """
    if ASSETS.ascii_dir:
        filepath = ASSETS.ascii_dir / "states" / f"{state}.txt"
        if filepath.exists():
            try:
                return filepath.read_text().rstrip()
            except Exception:
                pass

    # Fallbacks
    fallbacks = {
        "recording": STATE_RECORDING,
        "processing": STATE_PROCESSING,
    }
    return fallbacks.get(state, "")


# ============================================================================
# MENU BAR ICONS (Emoji)
# ============================================================================


class MenuBarIcons:
    """Menu bar emoji icons for different states."""

    IDLE = "🎙️"
    RECORDING = "🔴"
    PROCESSING = "⏳"
    SUCCESS = "✅"
    ERROR = "❌"
    DOWNLOADING = "⬇️"
    PRIVATE = "🔒"  # Private mode indicator
    ASSISTANT = "🤖"  # Voice assistant active indicator


# ============================================================================
# APPEARANCE THEMES
# ============================================================================

APPEARANCE_THEMES = {
    "default": {
        "name": "Default (Blue)",
        "colors": {
            "idle": {"background": "#232329", "icon": "#66A5FF", "background_hover": "#383840"},
            "recording": {"background": "#D92626", "icon": "#FFFFFF"},
            "processing": {"background": "#BF8C19", "icon": "#FFFFFF"},
            "success": {"background": "#3FB950", "icon": "#FFFFFF"},
            "error": {"background": "#F85149", "icon": "#FFFFFF"},
        },
    },
    "dark_red": {
        "name": "Dark Red",
        "colors": {
            "idle": {"background": "#2D1B1B", "icon": "#FF6B6B", "background_hover": "#3D2B2B"},
            "recording": {"background": "#8B0000", "icon": "#FFFFFF"},
            "processing": {"background": "#B8860B", "icon": "#FFFFFF"},
            "success": {"background": "#3FB950", "icon": "#FFFFFF"},
            "error": {"background": "#FF4444", "icon": "#FFFFFF"},
        },
    },
    "ocean_blue": {
        "name": "Ocean Blue",
        "colors": {
            "idle": {"background": "#1A2634", "icon": "#4DA8DA", "background_hover": "#2A3644"},
            "recording": {"background": "#C0392B", "icon": "#FFFFFF"},
            "processing": {"background": "#F39C12", "icon": "#FFFFFF"},
            "success": {"background": "#27AE60", "icon": "#FFFFFF"},
            "error": {"background": "#E74C3C", "icon": "#FFFFFF"},
        },
    },
    "forest_green": {
        "name": "Forest Green",
        "colors": {
            "idle": {"background": "#1E2D24", "icon": "#7CB342", "background_hover": "#2E3D34"},
            "recording": {"background": "#D32F2F", "icon": "#FFFFFF"},
            "processing": {"background": "#FFA000", "icon": "#FFFFFF"},
            "success": {"background": "#4CAF50", "icon": "#FFFFFF"},
            "error": {"background": "#E53935", "icon": "#FFFFFF"},
        },
    },
    "sunset_orange": {
        "name": "Sunset Orange",
        "colors": {
            "idle": {"background": "#2D1F1A", "icon": "#FF8A65", "background_hover": "#3D2F2A"},
            "recording": {"background": "#C62828", "icon": "#FFFFFF"},
            "processing": {"background": "#FFB300", "icon": "#FFFFFF"},
            "success": {"background": "#66BB6A", "icon": "#FFFFFF"},
            "error": {"background": "#EF5350", "icon": "#FFFFFF"},
        },
    },
    "purple_night": {
        "name": "Purple Night",
        "colors": {
            "idle": {"background": "#1F1A2E", "icon": "#9575CD", "background_hover": "#2F2A3E"},
            "recording": {"background": "#AD1457", "icon": "#FFFFFF"},
            "processing": {"background": "#FF6F00", "icon": "#FFFFFF"},
            "success": {"background": "#4DB6AC", "icon": "#FFFFFF"},
            "error": {"background": "#D81B60", "icon": "#FFFFFF"},
        },
    },
    "monochrome": {
        "name": "Monochrome",
        "colors": {
            "idle": {"background": "#1A1A1A", "icon": "#CCCCCC", "background_hover": "#2A2A2A"},
            "recording": {"background": "#666666", "icon": "#FFFFFF"},
            "processing": {"background": "#999999", "icon": "#FFFFFF"},
            "success": {"background": "#808080", "icon": "#FFFFFF"},
            "error": {"background": "#555555", "icon": "#FFFFFF"},
        },
    },
}


def get_theme(theme_id: str) -> Optional[dict]:
    """Get a theme by ID."""
    return APPEARANCE_THEMES.get(theme_id)


def get_theme_colors(theme_id: str) -> dict:
    """Get colors for a theme, with fallback to default."""
    theme = APPEARANCE_THEMES.get(theme_id, APPEARANCE_THEMES["default"])
    return theme.get("colors", APPEARANCE_THEMES["default"]["colors"])


def get_available_themes() -> list:
    """Get list of available theme IDs and names."""
    return [(tid, theme["name"]) for tid, theme in APPEARANCE_THEMES.items()]


# ============================================================================
# TAGLINE
# ============================================================================

TAGLINE = "voice -> text, invisibly"
APP_NAME = "WhisperHUD"
