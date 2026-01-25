"""
Paste target management for directing text to specific apps.

Enables transcription output to be directed to a locked target app/window,
even when that app isn't focused. Supports:
- Generic macOS apps (activate + paste + return focus)
- tmux sessions (direct send-keys, no focus change)
- iTerm2 (direct AppleScript write, no focus change)
- Terminal.app
"""

import subprocess
import time
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum

from .logging_config import get_logger

logger = get_logger("paste_targets")


class TargetType(Enum):
    """Types of paste targets."""
    FOCUSED = "focused"  # Current behavior - paste to focused window
    APP = "app"  # Generic app (activate + paste)
    TMUX = "tmux"  # tmux session (no focus change)
    ITERM2 = "iterm2"  # iTerm2 (no focus change)
    TERMINAL = "terminal"  # Terminal.app


@dataclass
class PasteTarget:
    """Represents a paste target."""
    type: TargetType
    name: str  # Display name
    identifier: str  # Bundle ID, session name, etc.


class PasteTargetManager:
    """Manage paste targets and routing."""

    # Apps to exclude from the target list (only true system processes)
    EXCLUDED_APPS = {
        "WhisperHUD",  # This app itself
        "loginwindow",  # Login screen
        "SystemUIServer",  # Menu bar system
        "WindowServer",  # Window management
        "Dock",  # Dock process
        "CoreServicesUIAgent",  # System dialogs
        "Notification Center",  # Notifications
        "Control Center",  # Control center
        "Spotlight",  # Spotlight search (has its own input)
        "universalAccessAuthWarn",  # Accessibility warning
        "AirPlayUIAgent",  # AirPlay
        "WiFiAgent",  # WiFi menu
        "UserNotificationCenter",  # Notifications
    }
    # Note: Finder, System Settings, etc. are NOT excluded - they can receive paste

    @staticmethod
    def _escape_applescript_string(value: str) -> str:
        """Escape a string for safe use inside AppleScript quotes."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def get_running_apps(self) -> List[str]:
        """Get list of running apps via AppleScript."""
        applescript = '''
        tell application "System Events"
            set appNames to name of every application process whose background only is false
            set output to ""
            repeat with appName in appNames
                set output to output & appName & linefeed
            end repeat
            return output
        end tell
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                apps = [
                    app.strip() for app in result.stdout.strip().split('\n')
                    if app.strip() and app.strip() not in self.EXCLUDED_APPS
                ]
                return sorted(apps)
        except Exception as e:
            logger.error(f"Error getting running apps: {e}")
        return []

    def get_tmux_sessions(self) -> List[str]:
        """Get active tmux sessions."""
        try:
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F', '#{session_name}'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                sessions = [
                    s.strip() for s in result.stdout.strip().split('\n')
                    if s.strip()
                ]
                return sessions
        except FileNotFoundError:
            # tmux not installed
            pass
        except Exception as e:
            logger.error(f"Error getting tmux sessions: {e}")
        return []

    def is_iterm2_running(self) -> bool:
        """Check if iTerm2 is running."""
        applescript = '''
        tell application "System Events"
            return exists (processes where name is "iTerm2")
        end tell
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and 'true' in result.stdout.lower()
        except Exception:
            return False

    def is_terminal_running(self) -> bool:
        """Check if Terminal.app is running."""
        applescript = '''
        tell application "System Events"
            return exists (processes where name is "Terminal")
        end tell
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and 'true' in result.stdout.lower()
        except Exception:
            return False

    def get_available_targets(self) -> List[PasteTarget]:
        """Discover all available paste targets."""
        targets = []

        # Always include focused window option
        targets.append(PasteTarget(
            type=TargetType.FOCUSED,
            name="Focused Window",
            identifier=""
        ))

        # tmux sessions (highest priority for terminals - no focus change)
        for session in self.get_tmux_sessions():
            targets.append(PasteTarget(
                type=TargetType.TMUX,
                name=f"tmux: {session}",
                identifier=session
            ))

        # iTerm2 (no focus change via AppleScript)
        if self.is_iterm2_running():
            targets.append(PasteTarget(
                type=TargetType.ITERM2,
                name="iTerm2",
                identifier="iTerm2"
            ))

        # Terminal.app
        if self.is_terminal_running():
            targets.append(PasteTarget(
                type=TargetType.TERMINAL,
                name="Terminal",
                identifier="Terminal"
            ))

        # Running apps
        for app in self.get_running_apps():
            # Skip terminal apps that we already have special handling for
            if app in ("iTerm2", "Terminal"):
                continue
            targets.append(PasteTarget(
                type=TargetType.APP,
                name=app,
                identifier=app
            ))

        return targets

    def get_frontmost_app(self) -> Optional[str]:
        """Get the name of the currently frontmost application."""
        applescript = '''
        tell application "System Events"
            return name of first application process whose frontmost is true
        end tell
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"Error getting frontmost app: {e}")
        return None

    def activate_app(self, app_name: str) -> bool:
        """Activate (bring to front) an application."""
        safe_app = self._escape_applescript_string(app_name)
        applescript = f'''
        tell application "{safe_app}"
            activate
        end tell
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error activating app '{app_name}': {e}")
            return False

    def paste_to_target(self, text: str, target: PasteTarget,
                        return_focus: bool = True,
                        restore_clipboard: bool = True) -> bool:
        """Route paste to appropriate method based on target type."""
        if target.type == TargetType.FOCUSED:
            # Use default paste behavior
            from .paste import insert_text
            return insert_text(text, restore_clipboard=restore_clipboard)

        elif target.type == TargetType.TMUX:
            return self.paste_to_tmux(text, target.identifier)

        elif target.type == TargetType.ITERM2:
            return self.paste_to_iterm2(text)

        elif target.type == TargetType.TERMINAL:
            return self.paste_to_terminal(text)

        elif target.type == TargetType.APP:
            return self.paste_to_app(
                text, target.identifier,
                return_focus=return_focus,
                restore_clipboard=restore_clipboard
            )

        return False

    def paste_to_app(self, text: str, app_name: str,
                     return_focus: bool = True,
                     restore_clipboard: bool = True) -> bool:
        """
        Activate app, paste, optionally return to original app.

        Args:
            text: Text to paste
            app_name: Name of the application to paste to
            return_focus: Whether to return focus to the original app
            restore_clipboard: Whether to restore the original clipboard content

        Returns:
            True if successful, False otherwise
        """
        import pyperclip

        original_app = None
        original_clipboard = None

        try:
            # Save original state
            if return_focus:
                original_app = self.get_frontmost_app()

            if restore_clipboard:
                try:
                    original_clipboard = pyperclip.paste()
                except Exception:
                    original_clipboard = None

            # Copy text to clipboard
            pyperclip.copy(text)
            time.sleep(0.05)

            # Activate target app
            if not self.activate_app(app_name):
                logger.warning(f"Failed to activate app: {app_name}")
                return False

            # Wait for app to come to front
            time.sleep(0.15)

            # Paste via Cmd+V
            applescript = '''
            tell application "System Events"
                keystroke "v" using command down
            end tell
            '''
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"Paste failed: {result.stderr.decode()}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error pasting to app '{app_name}': {e}")
            return False
        finally:
            # Return focus to original app
            if return_focus and original_app and original_app != app_name:
                time.sleep(0.1)
                self.activate_app(original_app)

            # Restore clipboard
            if restore_clipboard and original_clipboard is not None:
                time.sleep(0.1)
                try:
                    pyperclip.copy(original_clipboard)
                except Exception:
                    pass

    def paste_to_tmux(self, text: str, session: str) -> bool:
        """
        Send text directly to tmux session (no focus change).

        Args:
            text: Text to send
            session: tmux session name

        Returns:
            True if successful, False otherwise
        """
        try:
            # Use send-keys with -l flag for literal text
            # This prevents interpretation of special characters
            result = subprocess.run(
                ['tmux', 'send-keys', '-t', session, '-l', text],
                capture_output=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"tmux send-keys failed: {result.stderr.decode()}")
                return False

            return True

        except FileNotFoundError:
            logger.warning("tmux not found")
            return False
        except Exception as e:
            logger.error(f"Error sending to tmux session '{session}': {e}")
            return False

    def _escape_for_applescript(self, text: str) -> str:
        """Escape text for use in AppleScript strings."""
        # Order matters: escape backslashes first
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        text = text.replace('\n', '\\n')
        text = text.replace('\r', '\\r')
        text = text.replace('\t', '\\t')
        return text

    def paste_to_iterm2(self, text: str) -> bool:
        """
        Send text directly to iTerm2 (no focus change).

        Uses AppleScript to write directly to iTerm2's current session
        without changing window focus.

        Args:
            text: Text to send

        Returns:
            True if successful, False otherwise
        """
        escaped_text = self._escape_for_applescript(text)

        # Use 'write text' without newline to insert text at cursor
        applescript = f'''
        tell application "iTerm"
            tell current session of current window
                write text "{escaped_text}" without newline
            end tell
        end tell
        '''

        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"iTerm2 write failed: {result.stderr.decode()}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error writing to iTerm2: {e}")
            return False

    def paste_to_terminal(self, text: str) -> bool:
        """
        Paste text to Terminal.app using clipboard method.

        Terminal.app's 'do script' EXECUTES commands, so we use
        clipboard paste instead for safety.

        Args:
            text: Text to paste

        Returns:
            True if successful, False otherwise
        """
        import pyperclip

        original_clipboard = None

        try:
            # Save clipboard
            try:
                original_clipboard = pyperclip.paste()
            except Exception:
                pass

            # Copy text to clipboard
            pyperclip.copy(text)
            time.sleep(0.05)

            # Use AppleScript to paste into Terminal (Cmd+V)
            # This pastes text without executing it
            applescript = '''
            tell application "Terminal"
                activate
            end tell
            delay 0.1
            tell application "System Events"
                keystroke "v" using command down
            end tell
            '''

            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error(f"Terminal paste failed: {result.stderr.decode()}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error pasting to Terminal: {e}")
            return False
        finally:
            # Restore clipboard
            if original_clipboard is not None:
                time.sleep(0.1)
                try:
                    pyperclip.copy(original_clipboard)
                except Exception:
                    pass

    def is_target_available(self, target_type: str, identifier: str) -> bool:
        """
        Check if a specific target is currently available.

        Args:
            target_type: The type of target (focused, app, tmux, iterm2, terminal)
            identifier: The target identifier (app name, session name, etc.)

        Returns:
            True if the target is available, False otherwise
        """
        if target_type == "focused":
            return True

        elif target_type == "tmux":
            return identifier in self.get_tmux_sessions()

        elif target_type == "iterm2":
            return self.is_iterm2_running()

        elif target_type == "terminal":
            return self.is_terminal_running()

        elif target_type == "app":
            return identifier in self.get_running_apps()

        return False
