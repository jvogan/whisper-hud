"""
Global hotkey detection using pynput.

Default hotkey: Cmd+Shift+Space (hold to record)

Supports two modes:
- push_to_talk: Hold hotkey to record, release to stop
- toggle: Press hotkey to start recording, press again to stop

Also supports special keys like F-keys, media keys, and USB device keys (e.g., foot pedals).
"""

import threading
import weakref
from typing import Callable, Iterable, List, Optional, Set

from pynput import keyboard

from .logging_config import get_logger

logger = get_logger("hotkey")

try:
    from AppKit import (
        NSApp,
        NSApplication,
        NSBackingStoreBuffered,
        NSBezelStyleRounded,
        NSButton,
        NSColor,
        NSFont,
        NSScreen,
        NSTextAlignmentCenter,
        NSTextField,
        NSView,
        NSWindow,
        NSWindowStyleMaskTitled,
        NSEvent,
        NSEventTypeFlagsChanged,
        NSEventTypeKeyDown,
        NSEventMaskFlagsChanged,
        NSEventMaskKeyDown,
        NSEventModifierFlagCommand,
        NSEventModifierFlagControl,
        NSEventModifierFlagOption,
        NSEventModifierFlagShift,
        NSMakeRect,
    )
    from Foundation import NSObject
    from objc import super as objc_super

    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


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

MODIFIER_ORDER = ['cmd', 'ctrl', 'alt', 'shift']
MODIFIER_KEYS = set(MODIFIER_ORDER)
SYSTEM_SHORTCUT_WARNINGS = {
    frozenset({'cmd', 'space'}): "Conflicts with Spotlight.",
    frozenset({'cmd', 'tab'}): "Conflicts with macOS app switching.",
    frozenset({'cmd', 'q'}): "Commonly quits the frontmost app.",
    frozenset({'cmd', 'w'}): "Commonly closes the frontmost window.",
    frozenset({'cmd', 'h'}): "Commonly hides the frontmost app.",
    frozenset({'cmd', 'm'}): "Commonly minimizes the frontmost window.",
    frozenset({'cmd', ','}): "Commonly opens app settings.",
}
KEYCODE_NAME_MAP = {
    36: 'return',
    48: 'tab',
    49: 'space',
    51: 'backspace',
    53: 'escape',
    71: 'clear',
    76: 'enter',
    115: 'home',
    116: 'page_up',
    117: 'delete',
    119: 'end',
    121: 'page_down',
    123: 'left',
    124: 'right',
    125: 'down',
    126: 'up',
    122: 'f1',
    120: 'f2',
    99: 'f3',
    118: 'f4',
    96: 'f5',
    97: 'f6',
    98: 'f7',
    100: 'f8',
    101: 'f9',
    109: 'f10',
    103: 'f11',
    111: 'f12',
    105: 'f13',
    107: 'f14',
    113: 'f15',
    106: 'f16',
    64: 'f17',
    79: 'f18',
    80: 'f19',
    90: 'f20',
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


def _build_key_mapping():
    """Build a key name to Key mapping, handling platform differences."""
    mapping = {}

    # Core keys available on all platforms
    core_keys = [
        ('cmd', 'cmd'), ('shift', 'shift'), ('ctrl', 'ctrl'), ('alt', 'alt'),
        ('space', 'space'), ('enter', 'enter'), ('return', 'enter'),
        ('tab', 'tab'), ('backspace', 'backspace'), ('delete', 'delete'),
        ('escape', 'esc'), ('esc', 'esc'),
        ('up', 'up'), ('down', 'down'), ('left', 'left'), ('right', 'right'),
        ('page_up', 'page_up'), ('page_down', 'page_down'),
        ('home', 'home'), ('end', 'end'), ('caps_lock', 'caps_lock'),
    ]

    for name, key_attr in core_keys:
        try:
            mapping[name] = getattr(keyboard.Key, key_attr)
        except AttributeError:
            pass

    # Platform-specific keys (may not exist on macOS)
    optional_keys = [
        'num_lock', 'scroll_lock', 'print_screen', 'pause', 'insert',
    ]
    for key_name in optional_keys:
        try:
            mapping[key_name] = getattr(keyboard.Key, key_name)
        except AttributeError:
            pass

    # F-keys
    for i in range(1, 21):
        try:
            mapping[f'f{i}'] = getattr(keyboard.Key, f'f{i}')
        except AttributeError:
            pass

    # Media keys
    media_keys = [
        'media_play_pause', 'media_volume_mute', 'media_volume_down',
        'media_volume_up', 'media_previous', 'media_next',
    ]
    for key_name in media_keys:
        try:
            mapping[key_name] = getattr(keyboard.Key, key_name)
        except AttributeError:
            pass

    return mapping


# Build the key mapping once at module load time
_KEY_MAPPING = _build_key_mapping()


def string_to_key(name: str):
    """Convert a string name back to a pynput key."""
    name_lower = name.lower()

    # Handle virtual key codes (e.g., vk123)
    if name_lower.startswith('vk') and name_lower[2:].isdigit():
        vk_code = int(name_lower[2:])
        return keyboard.KeyCode.from_vk(vk_code)

    # Handle special keys
    if name_lower in _KEY_MAPPING:
        return _KEY_MAPPING[name_lower]

    # Single character key
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name.lower())

    # Unknown - try as character
    return keyboard.KeyCode.from_char(name[0].lower()) if name else None


def normalize_hotkey_names(key_names: Iterable[str]) -> List[str]:
    """Normalize hotkey names for storage and display."""
    normalized = []
    seen = set()

    for raw_name in key_names:
        if not raw_name:
            continue
        name = raw_name.lower()
        if name in ('cmd_l', 'cmd_r'):
            name = 'cmd'
        elif name in ('shift_l', 'shift_r'):
            name = 'shift'
        elif name in ('ctrl_l', 'ctrl_r'):
            name = 'ctrl'
        elif name in ('alt_l', 'alt_r', 'alt_gr'):
            name = 'alt'
        elif name == 'esc':
            name = 'escape'
        elif name == 'enter':
            name = 'return'

        if name not in seen:
            normalized.append(name)
            seen.add(name)

    return sorted(
        normalized,
        key=lambda key: (MODIFIER_ORDER.index(key) if key in MODIFIER_ORDER else 100, key),
    )


def get_hotkey_conflict_warning(key_names: Iterable[str]) -> Optional[str]:
    """Return a warning for common system shortcuts that are risky to override."""
    normalized = frozenset(normalize_hotkey_names(key_names))
    return SYSTEM_SHORTCUT_WARNINGS.get(normalized)


def format_hotkey_display(key_names: List[str]) -> str:
    """Format a list of key names for display with symbols."""
    parts = []
    sorted_keys = normalize_hotkey_names(key_names)

    for name in sorted_keys:
        display = KEY_DISPLAY_NAMES.get(name.lower(), name.upper())
        parts.append(display)

    return ''.join(parts)


def modifier_flags_to_names(flags: int) -> List[str]:
    """Convert NSEvent modifier flags into serialized key names."""
    if not HAS_APPKIT:
        return []

    modifiers = []
    if flags & NSEventModifierFlagCommand:
        modifiers.append('cmd')
    if flags & NSEventModifierFlagControl:
        modifiers.append('ctrl')
    if flags & NSEventModifierFlagOption:
        modifiers.append('alt')
    if flags & NSEventModifierFlagShift:
        modifiers.append('shift')
    return normalize_hotkey_names(modifiers)


def event_to_key_name(event) -> Optional[str]:
    """Convert an NSEvent keyDown event into a serialized key name."""
    key_code = int(event.keyCode())
    if key_code in KEYCODE_NAME_MAP:
        return KEYCODE_NAME_MAP[key_code]

    characters = event.charactersIgnoringModifiers()
    if not characters:
        return None

    char = characters[0].lower()
    if char == ' ':
        return 'space'
    if char.isprintable():
        return char
    return None


def is_modifier_only_hotkey(key_names: Iterable[str]) -> bool:
    """Return True when the hotkey contains only modifier keys."""
    normalized = normalize_hotkey_names(key_names)
    return bool(normalized) and all(name in MODIFIER_KEYS for name in normalized)


if HAS_APPKIT:
    class _HotkeyCaptureActionHandler(NSObject):
        """Bridge Cocoa button actions back into the pure-python panel controller."""

        def initWithPanel_(self, panel):
            self = objc_super(_HotkeyCaptureActionHandler, self).init()
            if self is None:
                return None
            self._panel_ref = weakref.ref(panel)
            return self

        def confirm_(self, _sender):
            panel = self._panel_ref()
            if panel:
                panel.confirm_capture()

        def cancel_(self, _sender):
            panel = self._panel_ref()
            if panel:
                panel.cancel()


class HotkeyCapturePanel:
    """Native key-capture panel for configuring the app hotkey."""

    def __init__(
        self,
        current_hotkey: Iterable[str],
        on_confirm: Callable[[Set, List[str]], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ):
        self.current_hotkey = normalize_hotkey_names(current_hotkey)
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel

        self.captured_key_names = self.current_hotkey.copy()
        self.conflict_warning = get_hotkey_conflict_warning(self.current_hotkey)

        self._window = None
        self._event_monitor = None
        self._action_handler = None
        self._current_value_label = None
        self._preview_value_label = None
        self._warning_label = None
        self._save_button = None

    def show(self) -> bool:
        """Open the key-capture panel."""
        if not HAS_APPKIT:
            logger.warning("Hotkey capture panel requested without AppKit support")
            return False

        if self._window is None:
            self._build_window()

        self.present_candidate(self.current_hotkey)
        self._event_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown | NSEventMaskFlagsChanged,
            self._handle_event,
        )
        self._window.center()
        self._window.makeKeyAndOrderFront_(None)
        app = NSApplication.sharedApplication() if NSApplication else NSApp()
        if app:
            app.activateIgnoringOtherApps_(True)
        return True

    def close(self):
        """Dismiss the panel and remove any active event monitor."""
        if HAS_APPKIT and self._event_monitor is not None:
            NSEvent.removeMonitor_(self._event_monitor)
            self._event_monitor = None

        if self._window is not None:
            self._window.orderOut_(None)
            self._window.close()
            self._window = None

        self._current_value_label = None
        self._preview_value_label = None
        self._warning_label = None
        self._save_button = None
        self._action_handler = None

    def cancel(self):
        """Cancel without changing the configured hotkey."""
        self.close()
        if self.on_cancel:
            self.on_cancel()

    def present_candidate(self, key_names: Iterable[str]):
        """Update the preview with a candidate key combination."""
        self.captured_key_names = normalize_hotkey_names(key_names)
        self.conflict_warning = get_hotkey_conflict_warning(self.captured_key_names)
        self._refresh_ui_state()

    def confirm_capture(self):
        """Confirm the currently displayed hotkey candidate."""
        if not self.captured_key_names:
            return

        if is_modifier_only_hotkey(self.captured_key_names):
            self.conflict_warning = "Choose a hotkey that includes a non-modifier key."
            self._refresh_ui_state()
            return

        final_keys = set()
        for name in self.captured_key_names:
            key = string_to_key(name)
            if key:
                final_keys.add(key)

        self.close()
        self.on_confirm(final_keys, self.captured_key_names.copy())

    def _handle_event(self, event):
        """Consume key events while the capture panel is focused."""
        event_type = int(event.type())
        if event_type == int(NSEventTypeFlagsChanged):
            self.present_candidate(modifier_flags_to_names(int(event.modifierFlags())))
            return None
        if event_type != int(NSEventTypeKeyDown):
            return event

        key_code = int(event.keyCode())
        if key_code == 53:
            self.cancel()
            return None

        modifiers = modifier_flags_to_names(int(event.modifierFlags()))
        key_name = event_to_key_name(event)
        if key_name == 'escape':
            self.cancel()
            return None

        candidate = modifiers + ([key_name] if key_name else [])
        if candidate:
            self.present_candidate(candidate)
        return None

    def _refresh_ui_state(self):
        """Sync current capture state into the panel labels."""
        current_display = format_hotkey_display(self.current_hotkey) or "Not set"
        preview_display = format_hotkey_display(self.captured_key_names) or "Press your desired hotkey combination"
        warning_text = self.conflict_warning or ""
        can_save = bool(self.captured_key_names) and not is_modifier_only_hotkey(self.captured_key_names)

        if self._current_value_label is not None:
            self._current_value_label.setStringValue_(current_display)
        if self._preview_value_label is not None:
            self._preview_value_label.setStringValue_(preview_display)
        if self._warning_label is not None:
            self._warning_label.setStringValue_(warning_text)
            if HAS_APPKIT:
                color = NSColor.systemRedColor() if warning_text else NSColor.secondaryLabelColor()
                self._warning_label.setTextColor_(color)
        if self._save_button is not None:
            self._save_button.setEnabled_(can_save)

    def _build_window(self):
        """Create the native capture panel."""
        screen = NSScreen.mainScreen()
        frame = screen.frame() if screen else None
        width = 440
        height = 220
        x_pos = 200 if frame is None else int((frame.size.width - width) / 2)
        y_pos = 300 if frame is None else int((frame.size.height - height) / 2)

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x_pos, y_pos, width, height),
            NSWindowStyleMaskTitled,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("Configure Hotkey")
        self._window.setReleasedWhenClosed_(False)

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        self._window.setContentView_(content)

        title = self._make_label(NSMakeRect(20, 170, width - 40, 24), 15, True)
        title.setStringValue_("Press your desired hotkey combination")
        content.addSubview_(title)

        current_label = self._make_label(NSMakeRect(20, 138, width - 40, 18), 11, False)
        current_label.setStringValue_("Current hotkey")
        current_label.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(current_label)

        self._current_value_label = self._make_label(NSMakeRect(20, 114, width - 40, 22), 13, True)
        content.addSubview_(self._current_value_label)

        preview_label = self._make_label(NSMakeRect(20, 84, width - 40, 18), 11, False)
        preview_label.setStringValue_("Captured combination")
        preview_label.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(preview_label)

        self._preview_value_label = self._make_label(NSMakeRect(20, 56, width - 40, 22), 16, True)
        content.addSubview_(self._preview_value_label)

        self._warning_label = self._make_label(NSMakeRect(20, 32, width - 40, 16), 11, False)
        self._warning_label.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(self._warning_label)

        self._action_handler = _HotkeyCaptureActionHandler.alloc().initWithPanel_(self)

        self._save_button = NSButton.alloc().initWithFrame_(NSMakeRect(width - 110, 8, 90, 28))
        self._save_button.setTitle_("Save")
        self._save_button.setBezelStyle_(NSBezelStyleRounded)
        self._save_button.setTarget_(self._action_handler)
        self._save_button.setAction_("confirm:")
        content.addSubview_(self._save_button)

        cancel_button = NSButton.alloc().initWithFrame_(NSMakeRect(width - 210, 8, 90, 28))
        cancel_button.setTitle_("Cancel")
        cancel_button.setBezelStyle_(NSBezelStyleRounded)
        cancel_button.setTarget_(self._action_handler)
        cancel_button.setAction_("cancel:")
        content.addSubview_(cancel_button)

    @staticmethod
    def _make_label(frame, font_size: int, bold: bool):
        label = NSTextField.alloc().initWithFrame_(frame)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(NSTextAlignmentCenter)
        font = NSFont.boldSystemFontOfSize_(font_size) if bold else NSFont.systemFontOfSize_(font_size)
        label.setFont_(font)
        return label


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
        capture = HotkeyCapture(on_captured=lambda keys: logger.info(f"Captured keys: {keys}"))
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
