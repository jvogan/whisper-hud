"""
Sparkle auto-update integration for WhisperHUD.

This module provides a Python wrapper around the Sparkle framework for
automatic updates on macOS. Sparkle must be embedded in the app bundle
for this to work.

Usage:
    from sparkle_updater import SparkleUpdater

    # Initialize (typically at app startup)
    updater = SparkleUpdater.shared()

    # Check for updates on startup
    updater.check_for_updates_in_background()

    # Check for updates (user initiated, shows UI)
    updater.check_for_updates()

Requirements:
    - Sparkle.framework embedded in app bundle
    - SUFeedURL set in Info.plist
    - PyObjC
"""

import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Sparkle availability flag
_sparkle_available = False
_SUUpdater = None


def _load_sparkle():
    """Attempt to load Sparkle framework."""
    global _sparkle_available, _SUUpdater

    if _sparkle_available:
        return True

    try:
        from Foundation import NSBundle

        # Try to load Sparkle from the app bundle's Frameworks directory
        bundle = NSBundle.mainBundle()
        frameworks_path = bundle.privateFrameworksPath()

        if frameworks_path:
            sparkle_path = f"{frameworks_path}/Sparkle.framework"

            try:
                sparkle_bundle = NSBundle.bundleWithPath_(sparkle_path)
                if sparkle_bundle and sparkle_bundle.load():
                    # Import SUUpdater class
                    from objc import lookUpClass

                    _SUUpdater = lookUpClass("SUUpdater")
                    if _SUUpdater:
                        _sparkle_available = True
                        logger.info("Sparkle framework loaded successfully")
                        return True
            except Exception as e:
                logger.debug(f"Could not load Sparkle from {sparkle_path}: {e}")

        # Try system-wide Sparkle (for development)
        try:
            from objc import lookUpClass

            _SUUpdater = lookUpClass("SUUpdater")
            if _SUUpdater:
                _sparkle_available = True
                logger.info("Sparkle framework loaded from system")
                return True
        except Exception:
            pass

        logger.debug("Sparkle framework not available")
        return False

    except ImportError as e:
        logger.debug(f"PyObjC not available: {e}")
        return False
    except Exception as e:
        logger.debug(f"Failed to load Sparkle: {e}")
        return False


class SparkleUpdater:
    """
    Wrapper for Sparkle SUUpdater.

    Provides a Python-friendly interface to Sparkle's auto-update functionality.
    Falls back gracefully if Sparkle is not available.
    """

    _instance: Optional["SparkleUpdater"] = None

    def __init__(self):
        """Initialize the updater. Use SparkleUpdater.shared() instead."""
        self._updater = None
        self._delegate = None
        self._on_update_available: Optional[Callable] = None
        self._on_update_error: Optional[Callable] = None
        self._initialized = False

    @classmethod
    def shared(cls) -> "SparkleUpdater":
        """Get the shared updater instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_available(self) -> bool:
        """Check if Sparkle is available and properly configured."""
        return self._initialize()

    def _initialize(self) -> bool:
        """Initialize Sparkle if available."""
        if self._initialized:
            return self._updater is not None

        self._initialized = True

        if not _load_sparkle():
            logger.debug("Sparkle not available")
            return False

        try:
            # Get the shared updater instance
            self._updater = _SUUpdater.sharedUpdater()

            # Configure updater
            # These can be overridden in Info.plist
            # self._updater.setAutomaticallyChecksForUpdates_(True)
            # self._updater.setUpdateCheckInterval_(86400)  # Daily

            logger.info("Sparkle updater initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Sparkle: {e}")
            self._updater = None
            return False

    def check_for_updates(self):
        """
        Check for updates and show UI if update is available.

        This should be called in response to a user action (e.g., menu item).
        Shows a progress window and prompts user if an update is found.
        """
        if not self._initialize():
            logger.info("Updates not available (Sparkle not loaded)")
            self._show_update_unavailable_dialog()
            return

        try:
            # This shows UI during the check
            self._updater.checkForUpdates_(None)
            logger.info("Checking for updates (user initiated)")
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")

    def check_for_updates_in_background(self):
        """
        Check for updates silently in the background.

        This should be called at app startup. Only shows UI if an update
        is found and ready to install.
        """
        if not self._initialize():
            return

        try:
            self._updater.checkForUpdatesInBackground()
            logger.debug("Background update check initiated")
        except Exception as e:
            logger.debug(f"Background update check failed: {e}")

    def reset_update_cycle(self):
        """Reset the update check cycle (useful after errors)."""
        if not self._initialize():
            return

        try:
            self._updater.resetUpdateCycle()
        except Exception as e:
            logger.debug(f"Reset update cycle failed: {e}")

    @property
    def last_update_check_date(self):
        """Get the date of the last update check."""
        if not self._initialize():
            return None

        try:
            return self._updater.lastUpdateCheckDate()
        except Exception:
            return None

    @property
    def automatically_checks_for_updates(self) -> bool:
        """Get whether automatic update checks are enabled."""
        if not self._initialize():
            return False

        try:
            return self._updater.automaticallyChecksForUpdates()
        except Exception:
            return False

    @automatically_checks_for_updates.setter
    def automatically_checks_for_updates(self, value: bool):
        """Set whether automatic update checks are enabled."""
        if not self._initialize():
            return

        try:
            self._updater.setAutomaticallyChecksForUpdates_(value)
        except Exception as e:
            logger.error(f"Failed to set auto-check: {e}")

    @property
    def update_check_interval(self) -> int:
        """Get the update check interval in seconds."""
        if not self._initialize():
            return 0

        try:
            return int(self._updater.updateCheckInterval())
        except Exception:
            return 0

    @update_check_interval.setter
    def update_check_interval(self, seconds: int):
        """Set the update check interval in seconds."""
        if not self._initialize():
            return

        try:
            self._updater.setUpdateCheckInterval_(seconds)
        except Exception as e:
            logger.error(f"Failed to set check interval: {e}")

    def _show_update_unavailable_dialog(self):
        """Show a dialog when updates aren't available."""
        try:
            import rumps

            rumps.alert(
                title="Updates Not Available",
                message=(
                    "Automatic updates are not available in this version.\n\n"
                    "Please check the GitHub releases page for the latest version:\n"
                    "https://github.com/jvogan/whisper-hud/releases"
                ),
                ok="OK",
            )
        except Exception:
            logger.info("Updates not available - please check GitHub releases")


# Convenience function for simple usage
def check_for_updates():
    """Check for updates (shows UI)."""
    SparkleUpdater.shared().check_for_updates()


def check_for_updates_in_background():
    """Check for updates silently."""
    SparkleUpdater.shared().check_for_updates_in_background()


def is_sparkle_available() -> bool:
    """Check if Sparkle auto-updates are available."""
    return SparkleUpdater.shared().is_available
