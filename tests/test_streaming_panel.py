"""Streaming panel behavior tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import whisper_hud.streaming_panel as streaming_panel_module
from whisper_hud.streaming_panel import StreamingPanel, StreamingPanelState


def _rect(x, y, width, height):
    return SimpleNamespace(
        origin=SimpleNamespace(x=x, y=y),
        size=SimpleNamespace(width=width, height=height),
    )


class _FakeScreen:
    def __init__(self, rect):
        self._rect = rect

    def visibleFrame(self):
        return self._rect


class _FakeApplication:
    def __init__(self, pid):
        self._pid = pid

    def processIdentifier(self):
        return self._pid


class _FakeWorkspace:
    def __init__(self, pid):
        self._pid = pid

    def frontmostApplication(self):
        return _FakeApplication(self._pid)


class _FakeWorkspaceClass:
    def __init__(self, pid):
        self._workspace = _FakeWorkspace(pid)

    def sharedWorkspace(self):
        return self._workspace


class _FakeNSScreen:
    def __init__(self, screens, main_index=0):
        self._screens = screens
        self._main_index = main_index

    def screens(self):
        return self._screens

    def mainScreen(self):
        return self._screens[self._main_index]


def test_auto_dismiss_delay_scales_with_word_count():
    panel = StreamingPanel()
    panel._latest_transcription = "word " * 24

    assert panel._auto_dismiss_delay_for_text(2.0) == 4.0


def test_zero_length_transcription_keeps_existing_dismiss_delay():
    panel = StreamingPanel()

    assert panel._auto_dismiss_delay_for_text(2.0) == 2.0


def test_show_complete_uses_scaled_dismiss_delay(monkeypatch):
    monkeypatch.setattr(streaming_panel_module, "HAS_APPKIT", True)
    monkeypatch.setattr(
        streaming_panel_module,
        "AppHelper",
        SimpleNamespace(callAfter=lambda fn: fn()),
        raising=False,
    )

    panel = StreamingPanel()
    panel._latest_transcription = "word " * 10

    scheduled = {}
    monkeypatch.setattr(panel, "_flush_pending_updates", lambda: None)
    monkeypatch.setattr(panel, "_schedule_dismiss", lambda delay: scheduled.setdefault("delay", delay))

    panel.show_complete()

    assert panel.get_state() == StreamingPanelState.COMPLETE
    assert scheduled["delay"] == 3.5


def test_close_button_action_dismisses_panel():
    panel = StreamingPanel()
    panel.hide = MagicMock()
    panel._state = StreamingPanelState.COMPLETE

    panel.closePanel_(None)

    panel.hide.assert_called_once_with()


def test_manual_dismiss_is_ignored_when_panel_already_hidden():
    panel = StreamingPanel()
    panel.hide = MagicMock()

    panel._handle_manual_dismiss()

    panel.hide.assert_not_called()


def test_selects_screen_for_frontmost_app_window(monkeypatch):
    primary = _FakeScreen(_rect(0, 0, 1440, 900))
    secondary = _FakeScreen(_rect(1440, 0, 1728, 1117))
    fake_screens = _FakeNSScreen([primary, secondary])

    monkeypatch.setattr(streaming_panel_module, "HAS_APPKIT", True)
    monkeypatch.setattr(streaming_panel_module, "NSScreen", fake_screens, raising=False)
    monkeypatch.setattr(
        streaming_panel_module,
        "NSWorkspace",
        _FakeWorkspaceClass(pid=4242),
        raising=False,
    )
    monkeypatch.setattr(
        streaming_panel_module,
        "CGWindowListCopyWindowInfo",
        lambda _opts, _window_id: [
            {
                "kCGWindowOwnerPID": 4242,
                "kCGWindowBounds": {"X": 1500, "Y": 100, "Width": 1200, "Height": 800},
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(streaming_panel_module, "kCGWindowListOptionOnScreenOnly", 1, raising=False)
    monkeypatch.setattr(streaming_panel_module, "kCGNullWindowID", 0, raising=False)

    panel = StreamingPanel()

    assert panel._screen_for_frontmost_window() is secondary


def test_window_frame_is_clamped_to_visible_screen(monkeypatch):
    tiny_screen = _FakeScreen(_rect(10, 20, 120, 30))

    monkeypatch.setattr(streaming_panel_module, "NSMakeRect", _rect, raising=False)

    panel = StreamingPanel()
    frame = panel._window_frame_for_screen(tiny_screen)

    assert frame.origin.x == 10
    assert frame.origin.y == 20
    assert frame.size.width == 120
    assert frame.size.height == 30
