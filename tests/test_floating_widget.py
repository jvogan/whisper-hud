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
