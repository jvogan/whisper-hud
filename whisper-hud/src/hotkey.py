"""
Global hotkey detection using pynput.

Default hotkey: Cmd+Shift+Space (hold to record)

Detects key press and release to enable hold-to-record behavior.
"""

from pynput import keyboard
from typing import Callable, Optional, Set
import threading


class HotkeyListener:
    """
    Listens for global hotkey to trigger recording.

    Usage:
        listener = HotkeyListener(on_start=start_recording, on_stop=stop_recording)
        listener.start()  # Non-blocking
        # ... app runs ...
        listener.stop()
    """

    # Default hotkey: Cmd+Shift+Space
    DEFAULT_HOTKEY = {keyboard.Key.cmd, keyboard.Key.shift, keyboard.Key.space}

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        hotkey: Optional[Set] = None
    ):
        """
        Initialize hotkey listener.

        Args:
            on_start: Called when hotkey is pressed (start recording)
            on_stop: Called when hotkey is released (stop recording)
            hotkey: Set of keys to listen for (default: Cmd+Shift+Space)
        """
        self.on_start = on_start
        self.on_stop = on_stop
        self.hotkey = hotkey or self.DEFAULT_HOTKEY

        self._pressed_keys: Set = set()
        self._is_active = False  # True while hotkey is held
        self._listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()

    def _normalize_key(self, key):
        """Normalize key for comparison."""
        # Handle left/right modifier variants
        if hasattr(key, 'name'):
            if key.name in ('cmd', 'cmd_l', 'cmd_r'):
                return keyboard.Key.cmd
            if key.name in ('shift', 'shift_l', 'shift_r'):
                return keyboard.Key.shift
            if key.name in ('ctrl', 'ctrl_l', 'ctrl_r'):
                return keyboard.Key.ctrl
            if key.name in ('alt', 'alt_l', 'alt_r'):
                return keyboard.Key.alt
        return key

    def _on_press(self, key):
        """Handle key press event."""
        with self._lock:
            normalized = self._normalize_key(key)
            self._pressed_keys.add(normalized)

            # Check if hotkey combination is pressed
            if self.hotkey.issubset(self._pressed_keys) and not self._is_active:
                self._is_active = True
                # Call on_start in a separate thread to avoid blocking
                threading.Thread(target=self.on_start, daemon=True).start()

    def _on_release(self, key):
        """Handle key release event."""
        with self._lock:
            normalized = self._normalize_key(key)

            # If any hotkey component is released while active, stop recording
            if normalized in self.hotkey and self._is_active:
                self._is_active = False
                # Call on_stop in a separate thread
                threading.Thread(target=self.on_stop, daemon=True).start()

            # Remove key from pressed set
            self._pressed_keys.discard(normalized)

    def start(self):
        """Start listening for hotkey (non-blocking)."""
        if self._listener is not None:
            return

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.start()

    def stop(self):
        """Stop listening for hotkey."""
        if self._listener:
            self._listener.stop()
            self._listener = None
            self._pressed_keys.clear()
            self._is_active = False

    def is_listening(self) -> bool:
        """Check if listener is active."""
        return self._listener is not None and self._listener.is_alive()

    def update_hotkey(self, hotkey: Set) -> None:
        """Update the hotkey combination."""
        with self._lock:
            self.hotkey = hotkey
            self._pressed_keys.clear()
            self._is_active = False
