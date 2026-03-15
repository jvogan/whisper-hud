"""
py2app setup configuration for WhisperHUD.

Creates a standalone macOS .app bundle with all dependencies bundled.

Usage:
    python setup_app.py py2app

Requirements:
    pip install py2app

The resulting app will be in dist/WhisperHUD.app
"""

import os
import sys
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from setuptools import setup
from py2app.build_app import py2app as _py2app

# Ensure we can import from the project
sys.path.insert(0, str(Path(__file__).parent / "whisper-hud"))

# App metadata
APP_NAME = "WhisperHUD"
APP_VERSION = "1.0.0"
APP_BUNDLE_ID = "com.whisperhud.app"
MAIN_SCRIPT = "whisper-hud/whisper_hud/main.py"

# Get version from package
try:
    from whisper_hud import __version__

    APP_VERSION = __version__
except ImportError:
    pass

# Paths
PROJECT_ROOT = Path(__file__).parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
APP_ICON = ICONS_DIR / "AppIcon.icns"
CURRENT_YEAR = datetime.now().year

# Optional Sparkle updater configuration (set via env)
SPARKLE_FEED_URL = os.environ.get("WHISPERHUD_SPARKLE_FEED_URL")
SPARKLE_PUBLIC_ED_KEY = os.environ.get("WHISPERHUD_SPARKLE_PUBLIC_ED_KEY")

if SPARKLE_FEED_URL:
    parsed = urlparse(SPARKLE_FEED_URL)
    if parsed.scheme != "https":
        raise ValueError("WHISPERHUD_SPARKLE_FEED_URL must use https")
    if not SPARKLE_PUBLIC_ED_KEY:
        raise ValueError("WHISPERHUD_SPARKLE_PUBLIC_ED_KEY is required when Sparkle updates are enabled")


def _relpath(path: Path) -> str:
    """Return setup.py-relative path string for py2app data_files."""
    return str(path.relative_to(PROJECT_ROOT))


# Data files to include in the app bundle
DATA_FILES = [
    # Assets
    (
        "assets/icons",
        [
            _relpath(ICONS_DIR / "AppIcon.icns"),
            _relpath(ICONS_DIR / "icon.svg"),
        ],
    ),
    ("assets/icons/icon.iconset", [_relpath(p) for p in (ICONS_DIR / "icon.iconset").glob("*.png")]),
    (
        "assets/dithered",
        [_relpath(p) for p in (ASSETS_DIR / "dithered").glob("*.png")] if (ASSETS_DIR / "dithered").exists() else [],
    ),
    (
        "assets/ascii",
        [_relpath(p) for p in (ASSETS_DIR / "ascii").glob("*.txt")] if (ASSETS_DIR / "ascii").exists() else [],
    ),
]

# Apple Translation helper (optional)
APPLE_TRANSLATE_HELPER = PROJECT_ROOT / "whisper-hud" / "bin" / "whisperhud-apple-translate"
if APPLE_TRANSLATE_HELPER.exists():
    DATA_FILES.append(("bin", [_relpath(APPLE_TRANSLATE_HELPER)]))

# Filter out empty entries
DATA_FILES = [(dest, files) for dest, files in DATA_FILES if files]

# Base Info.plist
plist = {
    # App identification
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": APP_BUNDLE_ID,
    "CFBundleVersion": APP_VERSION,
    "CFBundleShortVersionString": APP_VERSION,
    "CFBundleExecutable": APP_NAME,
    # App behavior
    "LSUIElement": True,  # Menu bar app - no dock icon
    "LSMinimumSystemVersion": "12.0",  # macOS Monterey+
    "NSHighResolutionCapable": True,
    # Required permissions
    "NSMicrophoneUsageDescription": (
        "WhisperHUD needs microphone access to transcribe your voice. "
        "Audio is processed locally or sent to your configured transcription provider."
    ),
    "NSAppleEventsUsageDescription": (
        "WhisperHUD needs to control other applications to paste transcribed text " "at the cursor position in any app."
    ),
    # Accessibility
    "NSAccessibilityUsageDescription": (
        "WhisperHUD needs accessibility access to insert transcribed text "
        "at your cursor position and detect the active application."
    ),
    # Privacy descriptions
    "NSDesktopFolderUsageDescription": ("WhisperHUD may need access to save audio files or transcriptions."),
    # Copyright
    "NSHumanReadableCopyright": f"Copyright 2024-{CURRENT_YEAR} WhisperHUD. All rights reserved.",
    # Document types (none for menu bar app)
    "CFBundleDocumentTypes": [],
    # URL schemes (optional, for deep linking)
    "CFBundleURLTypes": [
        {
            "CFBundleURLName": APP_BUNDLE_ID,
            "CFBundleURLSchemes": ["whisperhud"],
        }
    ],
}

# Sparkle auto-update configuration (optional)
if SPARKLE_FEED_URL:
    plist["SUFeedURL"] = SPARKLE_FEED_URL
    plist["SUEnableAutomaticChecks"] = True
    plist["SUScheduledCheckInterval"] = 86400  # Check daily (seconds)
if SPARKLE_PUBLIC_ED_KEY:
    plist["SUPublicEDKey"] = SPARKLE_PUBLIC_ED_KEY

# py2app options
OPTIONS = {
    "argv_emulation": False,  # Menu bar apps don't need this
    "iconfile": str(APP_ICON) if APP_ICON.exists() else None,
    "plist": plist,
    # Include these Python packages
    "packages": [
        "rumps",
        "pynput",
        "sounddevice",
        "numpy",
        "scipy",
        "openai",
        "anthropic",
        "keyring",
        "pyperclip",
        "objc",
        "Foundation",
        "AppKit",
        "Cocoa",
        "Quartz",
    ],
    # Exclude these to reduce bundle size
    "excludes": [
        "tkinter",
        "matplotlib",
        "pandas",
        "PIL",  # Only needed for asset generation
        "setuptools",
        "pkg_resources",
        "pip",
        "wheel",
        "pytest",
        "_pytest",
        "test",
        "tests",
        "unittest",
    ],
    # Include these specific modules
    "includes": [
        "whisper_hud",
        "whisper_hud.app",
        "whisper_hud.config",
        "whisper_hud.recorder",
        "whisper_hud.transcribe",
        "whisper_hud.translate",
        "whisper_hud.hotkey",
        "whisper_hud.hud",
        "whisper_hud.paste",
        "whisper_hud.paste_targets",
        "whisper_hud.floating_widget",
        "whisper_hud.streaming_panel",
        "whisper_hud.setup_wizard",
        "whisper_hud.keychain",
        "whisper_hud.branding",
        "whisper_hud.image_processor",
        "whisper_hud.character_packs",
        "whisper_hud.appearance_editor",
        "whisper_hud.pack_creator",
        "whisper_hud.launch_agent",
        "whisper_hud.logging_config",
        "whisper_hud.encryption",
        "whisper_hud.providers",
        "whisper_hud.providers.base",
        "whisper_hud.providers.openai_whisper",
        "whisper_hud.providers.apple_speech",
        "whisper_hud.providers.gemini",
        "whisper_hud.providers.parakeet",
        "whisper_hud.providers.whisper_local",
        "whisper_hud.providers.translation",
        "whisper_hud.providers.translation.base",
        "whisper_hud.providers.translation.gemini_translate",
        "whisper_hud.providers.translation.ollama",
        "whisper_hud.providers.translation.openai_translate",
        "whisper_hud.providers.translation.anthropic_translate",
    ],
    # Framework paths (will be populated by build script if Sparkle is available)
    "frameworks": [],
    # Resources to copy into bundle
    "resources": [],
    # Optimization
    "optimize": 2,  # -OO optimization
    "compressed": True,
    # Build options
    "strip": True,  # Strip debug symbols
    "semi_standalone": False,  # Full standalone (include Python framework)
}


class WhisperHUDPy2App(_py2app):
    """py2app command that ignores project metadata install_requires."""

    def finalize_options(self):
        if getattr(self.distribution, "install_requires", None):
            self.distribution.install_requires = []
        super().finalize_options()


setup(
    name=APP_NAME,
    version=APP_VERSION,
    app=[MAIN_SCRIPT],
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    cmdclass={"py2app": WhisperHUDPy2App},
    setup_requires=["py2app"],
)
