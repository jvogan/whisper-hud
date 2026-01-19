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


def insert_text(text: str, restore_clipboard: bool = True) -> bool:
    """
    Insert text at current cursor position.

    Args:
        text: Text to insert
        restore_clipboard: Whether to restore the original clipboard after paste

    Returns:
        True if successful, False otherwise
    """
    if not text:
        return False

    original_clipboard: Optional[str] = None

    try:
        # Save original clipboard if requested
        if restore_clipboard:
            try:
                original_clipboard = pyperclip.paste()
            except Exception:
                original_clipboard = None

        # Copy to clipboard
        pyperclip.copy(text)

        # Small delay to ensure clipboard is ready
        time.sleep(0.05)

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
            print(f"AppleScript error: {result.stderr.decode()}")
            return False

        # Small delay before restoring clipboard
        if restore_clipboard and original_clipboard is not None:
            time.sleep(0.1)
            try:
                pyperclip.copy(original_clipboard)
            except Exception:
                pass  # If restore fails, that's okay

        return True

    except subprocess.TimeoutExpired:
        print("Paste operation timed out")
        return False
    except Exception as e:
        print(f"Paste error: {e}")
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
        print(f"Direct insert error: {e}")
        return False


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
