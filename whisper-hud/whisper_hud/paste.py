"""
Text insertion module.

Strategy:
1. Copy text to clipboard
2. Simulate Cmd+V keystroke via AppleScript

This works in ANY application that supports paste.
"""

import subprocess
import pyperclip
import time
from typing import Optional

from .logging_config import get_logger

logger = get_logger("paste")


def _escape_applescript_string(value: str) -> str:
    """Escape a string for safe use inside AppleScript quotes."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def insert_text(
    text: str,
    restore_clipboard: bool = True,
    target_app: Optional[str] = None,
    return_focus: bool = True
) -> bool:
    """
    Insert text at current cursor position.

    Args:
        text: Text to insert
        restore_clipboard: Whether to restore the original clipboard after paste
        target_app: Optional app name to paste to (activates the app first)
        return_focus: Whether to return focus to original app after pasting to target_app

    Returns:
        True if successful, False otherwise
    """
    if not text:
        return False

    original_clipboard: Optional[str] = None
    original_app: Optional[str] = None

    try:
        # Save original clipboard if requested
        if restore_clipboard:
            try:
                original_clipboard = pyperclip.paste()
            except Exception:
                original_clipboard = None

        # If targeting a specific app, save current frontmost app
        if target_app and return_focus:
            original_app = get_frontmost_app()

        # Copy to clipboard
        pyperclip.copy(text)

        # Small delay to ensure clipboard is ready
        time.sleep(0.05)

        # If targeting a specific app, activate it first
        if target_app:
            safe_app = _escape_applescript_string(target_app)
            activate_result = subprocess.run(
                ['osascript', '-e', f'tell application "{safe_app}" to activate'],
                capture_output=True,
                timeout=5
            )
            if activate_result.returncode != 0:
                logger.warning(f"Failed to activate app: {target_app}")
                return False
            # Wait for app to come to front
            time.sleep(0.15)

        # Simulate Cmd+V using AppleScript
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
            logger.error(f"AppleScript error: {result.stderr.decode()}")
            return False

        # Return focus to original app if needed
        if target_app and return_focus and original_app and original_app != target_app:
            time.sleep(0.1)
            safe_app = _escape_applescript_string(original_app)
            subprocess.run(
                ['osascript', '-e', f'tell application "{safe_app}" to activate'],
                capture_output=True,
                timeout=5
            )

        # Small delay before restoring clipboard
        if restore_clipboard and original_clipboard is not None:
            time.sleep(0.1)
            try:
                # Only restore if clipboard still contains our text
                # This prevents overwriting user's content if they copied
                # something during the paste delay
                current_clipboard = pyperclip.paste()
                if current_clipboard == text:
                    pyperclip.copy(original_clipboard)
            except Exception:
                pass  # If restore fails, that's okay

        return True

    except subprocess.TimeoutExpired:
        logger.error("Paste operation timed out")
        return False
    except Exception as e:
        logger.error(f"Paste error: {e}")
        return False


def insert_text_direct(text: str) -> bool:
    """
    Alternative: Insert text by simulating keystrokes.

    Slower but doesn't modify clipboard.
    Only use for short text (< 50 chars).
    """
    if not text:
        return False

    # For longer text, fall back to clipboard method
    if len(text) > 50:
        return insert_text(text, restore_clipboard=True)

    try:
        # Escape special characters for AppleScript
        escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')

        applescript = f'''
        tell application "System Events"
            keystroke "{escaped}"
        end tell
        '''

        result = subprocess.run(
            ['osascript', '-e', applescript],
            capture_output=True,
            timeout=10
        )

        return result.returncode == 0

    except Exception as e:
        logger.error(f"Direct insert error: {e}")
        return False


def get_frontmost_app() -> Optional[str]:
    """
    Get the name of the currently frontmost application.

    Returns:
        App name if successful, None otherwise
    """
    try:
        applescript = '''
        tell application "System Events"
            return name of first process whose frontmost is true
        end tell
        '''
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


def check_accessibility_permission() -> bool:
    """
    Check if the app has Accessibility permission.

    Returns:
        True if permission granted, False otherwise
    """
    try:
        # Try a simple AppleScript that requires Accessibility
        applescript = '''
        tell application "System Events"
            return name of first process whose frontmost is true
        end tell
        '''
        result = subprocess.run(
            ['osascript', '-e', applescript],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def get_accessibility_error_message() -> str:
    """
    Get a user-friendly error message for accessibility permission issues.

    Returns:
        Detailed error message with instructions
    """
    return (
        "WhisperHUD needs Accessibility permission to:\n"
        "• Detect global hotkeys\n"
        "• Paste transcribed text into applications\n\n"
        "To grant access:\n"
        "1. Open System Settings\n"
        "2. Go to Privacy & Security → Accessibility\n"
        "3. Enable WhisperHUD (or the Terminal/Python app)\n\n"
        "Then restart WhisperHUD."
    )


def open_accessibility_settings() -> bool:
    """
    Open System Settings to the Accessibility pane.

    Returns:
        True if successful, False otherwise
    """
    try:
        # macOS 13+ uses System Settings with this URL
        applescript = '''
        tell application "System Settings"
            activate
            delay 0.5
        end tell
        do shell script "open x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        '''
        result = subprocess.run(
            ['osascript', '-e', applescript],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Failed to open accessibility settings: {e}")
        # Fallback: try older System Preferences approach
        try:
            subprocess.run(
                ['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'],
                capture_output=True,
                timeout=5
            )
            return True
        except Exception:
            return False
