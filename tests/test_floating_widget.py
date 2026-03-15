"""Tests for floating widget state visuals and tooltip metadata."""

from importlib import import_module, reload
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock


def _load_floating_widget_module(monkeypatch):
    appkit = ModuleType("AppKit")
    appkit.NSWindow = type("NSWindow", (), {})
    appkit.NSView = type("NSView", (), {})
    appkit.NSColor = MagicMock()
    appkit.NSBezierPath = MagicMock()
    appkit.NSWindowStyleMaskBorderless = 0
    appkit.NSBackingStoreBuffered = 0
    appkit.NSFloatingWindowLevel = 0
    appkit.NSScreen = MagicMock()
    appkit.NSMakeRect = lambda x, y, w, h: SimpleNamespace(
        origin=SimpleNamespace(x=x, y=y),
        size=SimpleNamespace(width=w, height=h),
    )
    appkit.NSTrackingArea = MagicMock()
    appkit.NSWindowCollectionBehaviorCanJoinAllSpaces = 0
    appkit.NSWindowCollectionBehaviorStationary = 0
    appkit.NSTrackingMouseEnteredAndExited = 0
    appkit.NSTrackingActiveAlways = 0
    appkit.NSTrackingInVisibleRect = 0
    appkit.NSCursor = MagicMock()
    appkit.NSCompositingOperationSourceOver = 0
    appkit.NSZeroRect = SimpleNamespace()
    appkit.NSMenu = MagicMock()
    appkit.NSMenuItem = MagicMock()
    appkit.NSAccessibilityButtonRole = "AXButton"
    appkit.NSAccessibilityImageRole = "AXImage"
    appkit.NSAccessibilityCreatedNotification = "AXCreated"
    appkit.NSAccessibilityFocusedUIElementChangedNotification = "AXFocusedUIElementChanged"
    appkit.NSAccessibilityValueChangedNotification = "AXValueChanged"
    appkit.NSAccessibilityPostNotification = MagicMock()

    pyobjc_tools = ModuleType("PyObjCTools")
    pyobjc_tools.AppHelper = SimpleNamespace(callAfter=lambda fn: fn())

    objc = ModuleType("objc")
    objc.super = super

    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "PyObjCTools", pyobjc_tools)
    monkeypatch.setitem(sys.modules, "objc", objc)

    module = import_module("whisper_hud.floating_widget")
    return reload(module)


class FakeTimer:
    """Threading.Timer test double that does not run asynchronously."""

    created = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False
        self.cancelled = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def test_widget_tooltip_shows_provider_and_hotkey(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._view = MagicMock()

    widget.set_tooltip_context("OpenAI", "⌘⇧Space", "push_to_talk")

    widget._view.setToolTip_.assert_called_once_with("Provider: OpenAI\nHotkey: Hold ⌘⇧Space")


def test_widget_animation_timer_tracks_state_transitions(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()

    widget.set_recording()

    assert widget._state == floating_widget.WidgetState.RECORDING
    assert len(FakeTimer.created) == 1
    recording_timer = FakeTimer.created[-1]
    assert recording_timer.started is True

    widget.set_processing()

    assert widget._state == floating_widget.WidgetState.PROCESSING
    assert recording_timer.cancelled is True
    assert len(FakeTimer.created) == 2
    processing_timer = FakeTimer.created[-1]
    assert processing_timer.started is True

    widget.set_idle()

    assert widget._state == floating_widget.WidgetState.IDLE
    assert processing_timer.cancelled is True
    widget._view.setAnimationPhase_.assert_called_with(0.0)


def test_widget_hide_cancels_animation_timer(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._window = MagicMock()
    widget._view = MagicMock()

    widget.set_recording()
    active_timer = FakeTimer.created[-1]

    widget.hide()

    assert widget._visible is False
    assert active_timer.cancelled is True
    widget._window.orderOut_.assert_called_once_with(None)


def test_widget_reset_position_moves_to_primary_monitor_default(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    screen_frame = SimpleNamespace(
        origin=SimpleNamespace(x=50, y=25),
        size=SimpleNamespace(width=1400, height=900),
    )
    floating_widget.NSScreen.mainScreen.return_value = SimpleNamespace(
        visibleFrame=lambda: screen_frame
    )

    on_position_changed = MagicMock()
    widget = floating_widget.FloatingWidget(
        lambda: None,
        lambda: None,
        size="medium",
        initial_position={"x": 100, "y": 200},
        on_position_changed=on_position_changed,
    )
    widget._window = MagicMock()

    widget.reset_position()

    expected_position = (
        screen_frame.origin.x
        + screen_frame.size.width
        - floating_widget.FloatingWidget.SIZES["medium"][0]
        - floating_widget.DEFAULT_WIDGET_RIGHT_MARGIN,
        screen_frame.origin.y + floating_widget.DEFAULT_WIDGET_BOTTOM_MARGIN,
    )
    assert widget._position == expected_position
    widget._window.setFrameOrigin_.assert_called_once_with(expected_position)
    on_position_changed.assert_called_once_with(*expected_position)


def test_widget_accessibility_label_tracks_state_changes(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._view = MagicMock()
    widget._window = MagicMock()

    widget.set_recording()
    assert widget._accessibility_label == "WhisperHUD - Recording"
    widget._view.setAccessibilityLabelText_.assert_called_with("WhisperHUD - Recording")

    widget.set_processing()
    assert widget._accessibility_label == "WhisperHUD - Processing"
    widget._view.setAccessibilityLabelText_.assert_called_with("WhisperHUD - Processing")

    widget.set_idle()
    assert widget._accessibility_label == "WhisperHUD - Idle"
    widget._view.setAccessibilityLabelText_.assert_called_with("WhisperHUD - Idle")


def test_widget_posts_accessibility_notifications_on_state_change(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._view = MagicMock()
    widget._window = MagicMock()

    floating_widget.NSAccessibilityPostNotification.reset_mock()

    widget.set_recording()

    assert floating_widget.NSAccessibilityPostNotification.call_count == 2
    floating_widget.NSAccessibilityPostNotification.assert_any_call(
        widget._view,
        floating_widget.NSAccessibilityValueChangedNotification,
    )
    floating_widget.NSAccessibilityPostNotification.assert_any_call(
        widget._view,
        floating_widget.NSAccessibilityFocusedUIElementChangedNotification,
    )


def test_widget_view_exposes_button_accessibility(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    clicked = MagicMock()
    view = object.__new__(floating_widget.WidgetView)
    view._on_click = clicked
    view._accessibility_role = floating_widget.NSAccessibilityButtonRole
    view._accessibility_label = "WhisperHUD - Idle"

    assert view.isAccessibilityElement() is True
    assert view.accessibilityRole() == floating_widget.NSAccessibilityButtonRole
    assert view.accessibilityLabel() == "WhisperHUD - Idle"
    assert view.accessibilityPerformPress() is True
    clicked.assert_called_once_with()
