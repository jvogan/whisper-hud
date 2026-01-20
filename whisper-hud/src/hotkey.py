"""
Global hotkey detection using pynput.

Default hotkey: Cmd+Shift+Space (hold to record)

Supports two modes:
- push_to_talk: Hold hotkey to record, release to stop
- toggle: Press hotkey to start recording, press again to stop

Also supports special keys like F-keys, media keys, and USB device keys (e.g., foot pedals).
"""

from pynput import keyboard
from typing import Callable, Optional, Set, List
import threading


# Comprehensive key name mappings for display and serialization
KEY_DISPLAY_NAMES = {
    # Modifiers
    'cmd': '⌘',
    'shift': '⇧',
    'ctrl': '⌃',
    'alt': '⌥',
    'space': 'Space',
    # Function keys
    'f1': 'F1', 'f2': 'F2', 'f3': 'F3', 'f4': 'F4',
    'f5': 'F5', 'f6': 'F6', 'f7': 'F7', 'f8': 'F8',
    'f9': 'F9', 'f10': 'F10', 'f11': 'F11', 'f12': 'F12',
    'f13': 'F13', 'f14': 'F14', 'f15': 'F15', 'f16': 'F16',
    'f17': 'F17', 'f18': 'F18', 'f19': 'F19', 'f20': 'F20',
    # Navigation
    'up': '↑', 'down': '↓', 'left': '←', 'right': '→',
    'page_up': 'PgUp', 'page_down': 'PgDn',
    'home': 'Home', 'end': 'End',
    # Special keys
    'enter': '↵', 'return': '↵',
    'tab': 'Tab',
    'backspace': '⌫',
    'delete': 'Del',
    'escape': 'Esc', 'esc': 'Esc',
    'caps_lock': 'CapsLock',
    'num_lock': 'NumLock',
    'scroll_lock': 'ScrollLock',
    'print_screen': 'PrtSc',
    'pause': 'Pause',
    'insert': 'Ins',
    # Media keys
    'media_play_pause': '⏯',
    'media_volume_mute': '🔇',
    'media_volume_down': '🔉',
    'media_volume_up': '🔊',
    'media_previous': '⏮',
    'media_next': '⏭',
}


def key_to_string(key) -> str:
    """Convert a pynput key to a string name for storage."""
    if hasattr(key, 'name'):
        name = key.name
        # Normalize left/right variants
        if name in ('cmd_l', 'cmd_r'):
            return 'cmd'
        if name in ('shift_l', 'shift_r'):
            return 'shift'
        if name in ('ctrl_l', 'ctrl_r'):
            return 'ctrl'
        if name in ('alt_l', 'alt_r', 'alt_gr'):
            return 'alt'
        return name.lower()
    elif hasattr(key, 'char') and key.char:
        return key.char.lower()
    elif hasattr(key, 'vk'):
        # Virtual key code - useful for USB devices like foot pedals
        return f'vk{key.vk}'
    return str(key)


def string_to_key(name: str):
    """Convert a string name back to a pynput key."""
    name_lower = name.lower()

    # Handle virtual key codes (e.g., vk123)
    if name_lower.startswith('vk') and name_lower[2:].isdigit():
        vk_code = int(name_lower[2:])
        return keyboard.KeyCode.from_vk(vk_code)

    # Handle special keys
    key_mapping = {
        'cmd': keyboard.Key.cmd,
        'shift': keyboard.Key.shift,
        'ctrl': keyboard.Key.ctrl,
        'alt': keyboard.Key.alt,
        'space': keyboard.Key.space,
        'enter': keyboard.Key.enter,
        'return': keyboard.Key.enter,
        'tab': keyboard.Key.tab,
        'backspace': keyboard.Key.backspace,
        'delete': keyboard.Key.delete,
        'escape': keyboard.Key.esc,
        'esc': keyboard.Key.esc,
        'up': keyboard.Key.up,
        'down': keyboard.Key.down,
        'left': keyboard.Key.left,
        'right': keyboard.Key.right,
        'page_up': keyboard.Key.page_up,
        'page_down': keyboard.Key.page_down,
        'home': keyboard.Key.home,
        'end': keyboard.Key.end,
        'caps_lock': keyboard.Key.caps_lock,
        'num_lock': keyboard.Key.num_lock,
        'scroll_lock': keyboard.Key.scroll_lock,
        'print_screen': keyboard.Key.print_screen,
        'pause': keyboard.Key.pause,
        'insert': keyboard.Key.insert,
        'f1': keyboard.Key.f1, 'f2': keyboard.Key.f2, 'f3': keyboard.Key.f3,
        'f4': keyboard.Key.f4, 'f5': keyboard.Key.f5, 'f6': keyboard.Key.f6,
        'f7': keyboard.Key.f7, 'f8': keyboard.Key.f8, 'f9': keyboard.Key.f9,
        'f10': keyboard.Key.f10, 'f11': keyboard.Key.f11, 'f12': keyboard.Key.f12,
        'f13': keyboard.Key.f13, 'f14': keyboard.Key.f14, 'f15': keyboard.Key.f15,
        'f16': keyboard.Key.f16, 'f17': keyboard.Key.f17, 'f18': keyboard.Key.f18,
        'f19': keyboard.Key.f19, 'f20': keyboard.Key.f20,
        'media_play_pause': keyboard.Key.media_play_pause,
        'media_volume_mute': keyboard.Key.media_volume_mute,
        'media_volume_down': keyboard.Key.media_volume_down,
        'media_volume_up': keyboard.Key.media_volume_up,
        'media_previous': keyboard.Key.media_previous,
        'media_next': keyboard.Key.media_next,
    }

    if name_lower in key_mapping:
        return key_mapping[name_lower]

    # Single character key
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name.lower())

    # Unknown - try as character
    return keyboard.KeyCode.from_char(name[0].lower()) if name else None


def format_hotkey_display(key_names: List[str]) -> str:
    """Format a list of key names for display with symbols."""
    parts = []
    # Sort modifiers first
    modifier_order = ['cmd', 'ctrl', 'alt', 'shift']
    sorted_keys = sorted(key_names, key=lambda k: (
        modifier_order.index(k.lower()) if k.lower() in modifier_order else 100,
        k.lower()
    ))

    for name in sorted_keys:
        display = KEY_DISPLAY_NAMES.get(name.lower(), name.upper())
        parts.append(display)

    return ''.join(parts) if all(len(p) <= 2 for p in parts) else ' + '.join(parts)


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
        hotkey: Optional[Set] = None,
        mode: str = "push_to_talk"
    ):
        """
        Initialize hotkey listener.

        Args:
            on_start: Called when hotkey is pressed (start recording)
            on_stop: Called when hotkey is released (stop recording) or toggled off
            hotkey: Set of keys to listen for (default: Cmd+Shift+Space)
            mode: "push_to_talk" (hold to record) or "toggle" (press to start/stop)
        """
        self.on_start = on_start
        self.on_stop = on_stop
        self.hotkey = hotkey or self.DEFAULT_HOTKEY
        self.mode = mode

        self._pressed_keys: Set = set()
        self._is_active = False  # True while recording
        self._hotkey_was_pressed = False  # For toggle mode debouncing
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
            if key.name in ('alt', 'alt_l', 'alt_r', 'alt_gr'):
                return keyboard.Key.alt
        return key

    def _on_press(self, key):
        """Handle key press event."""
        with self._lock:
            normalized = self._normalize_key(key)
            self._pressed_keys.add(normalized)

            # Check if hotkey combination is pressed
            if self.hotkey.issubset(self._pressed_keys):
                if self.mode == "toggle":
                    # Toggle mode: only trigger on first press (debounce)
                    if not self._hotkey_was_pressed:
                        self._hotkey_was_pressed = True
                        if self._is_active:
                            # Currently recording, stop
                            self._is_active = False
                            threading.Thread(target=self.on_stop, daemon=True).start()
                        else:
                            # Not recording, start
                            self._is_active = True
                            threading.Thread(target=self.on_start, daemon=True).start()
                else:
                    # Push-to-talk mode: start on press
                    if not self._is_active:
                        self._is_active = True
                        threading.Thread(target=self.on_start, daemon=True).start()

    def _on_release(self, key):
        """Handle key release event."""
        with self._lock:
            normalized = self._normalize_key(key)

            if self.mode == "push_to_talk":
                # Push-to-talk mode: stop when any hotkey component is released
                if normalized in self.hotkey and self._is_active:
                    self._is_active = False
                    threading.Thread(target=self.on_stop, daemon=True).start()
            else:
                # Toggle mode: reset debounce flag when hotkey is released
                if normalized in self.hotkey:
                    self._hotkey_was_pressed = False

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
            self._hotkey_was_pressed = False

    def is_listening(self) -> bool:
        """Check if listener is active."""
        return self._listener is not None and self._listener.is_alive()

    def update_hotkey(self, hotkey: Set) -> None:
        """Update the hotkey combination."""
        with self._lock:
            self.hotkey = hotkey
            self._pressed_keys.clear()
            self._is_active = False
            self._hotkey_was_pressed = False

    def update_mode(self, mode: str) -> None:
        """Update the hotkey mode."""
        with self._lock:
            self.mode = mode
            self._pressed_keys.clear()
            self._is_active = False
            self._hotkey_was_pressed = False

    def force_stop_recording(self) -> None:
        """Force stop recording (useful for toggle mode)."""
        with self._lock:
            if self._is_active:
                self._is_active = False
                threading.Thread(target=self.on_stop, daemon=True).start()


class HotkeyCapture:
    """
    Captures a hotkey combination from user input.

    Usage:
        capture = HotkeyCapture(on_captured=lambda keys: print(keys))
        capture.start()
        # User presses keys...
        # on_captured is called with the key set
        capture.stop()
    """

    def __init__(
        self,
        on_captured: Callable[[Set, List[str]], None],
        on_key_change: Optional[Callable[[List[str]], None]] = None
    ):
        """
        Initialize hotkey capture.

        Args:
            on_captured: Called when capture is complete with (key_set, key_names)
            on_key_change: Called when pressed keys change (for live preview)
        """
        self.on_captured = on_captured
        self.on_key_change = on_key_change

        self._pressed_keys: Set = set()
        self._key_names: List[str] = []
        self._max_keys: Set = set()  # Track the maximum key combination
        self._max_key_names: List[str] = []
        self._listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()
        self._capture_complete = False

    def _on_press(self, key):
        """Handle key press during capture."""
        with self._lock:
            if self._capture_complete:
                return

            # Normalize and add key
            if hasattr(key, 'name'):
                name = key.name
                if name in ('cmd_l', 'cmd_r'):
                    name = 'cmd'
                elif name in ('shift_l', 'shift_r'):
                    name = 'shift'
                elif name in ('ctrl_l', 'ctrl_r'):
                    name = 'ctrl'
                elif name in ('alt_l', 'alt_r', 'alt_gr'):
                    name = 'alt'
                normalized_key = string_to_key(name)
            elif hasattr(key, 'char') and key.char:
                name = key.char.lower()
                normalized_key = key
            elif hasattr(key, 'vk'):
                name = f'vk{key.vk}'
                normalized_key = key
            else:
                return

            self._pressed_keys.add(normalized_key)
            if name not in self._key_names:
                self._key_names.append(name)

            # Track maximum combination
            if len(self._pressed_keys) > len(self._max_keys):
                self._max_keys = self._pressed_keys.copy()
                self._max_key_names = self._key_names.copy()

            # Notify of key change
            if self.on_key_change:
                self.on_key_change(self._key_names.copy())

    def _on_release(self, key):
        """Handle key release during capture."""
        with self._lock:
            if self._capture_complete:
                return

            # When all keys are released, capture is complete
            if hasattr(key, 'name'):
                name = key.name
                if name in ('cmd_l', 'cmd_r'):
                    name = 'cmd'
                elif name in ('shift_l', 'shift_r'):
                    name = 'shift'
                elif name in ('ctrl_l', 'ctrl_r'):
                    name = 'ctrl'
                elif name in ('alt_l', 'alt_r', 'alt_gr'):
                    name = 'alt'
                normalized_key = string_to_key(name)
            elif hasattr(key, 'char') and key.char:
                name = key.char.lower()
                normalized_key = key
            elif hasattr(key, 'vk'):
                name = f'vk{key.vk}'
                normalized_key = key
            else:
                return

            self._pressed_keys.discard(normalized_key)
            if name in self._key_names:
                self._key_names.remove(name)

            # Update preview
            if self.on_key_change:
                self.on_key_change(self._key_names.copy())

            # If all keys released and we have a captured combination, complete
            if len(self._pressed_keys) == 0 and len(self._max_keys) > 0:
                self._capture_complete = True
                # Convert max_keys to proper key set
                final_keys = set()
                for name in self._max_key_names:
                    k = string_to_key(name)
                    if k:
                        final_keys.add(k)

                threading.Thread(
                    target=self.on_captured,
                    args=(final_keys, self._max_key_names.copy()),
                    daemon=True
                ).start()

    def start(self):
        """Start capturing hotkey."""
        if self._listener is not None:
            return

        self._pressed_keys.clear()
        self._key_names.clear()
        self._max_keys.clear()
        self._max_key_names.clear()
        self._capture_complete = False

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.start()

    def stop(self):
        """Stop capturing."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    def is_capturing(self) -> bool:
        """Check if capture is active."""
        return self._listener is not None and self._listener.is_alive()
