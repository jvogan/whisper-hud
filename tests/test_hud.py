"""HUD behavior tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import whisper_hud.hud as hud_module
from whisper_hud.hud import HUD, HUDState


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


def _build_fake_hud(monkeypatch):
    """Create a HUD instance with AppKit interactions stubbed out."""
    monkeypatch.setattr(hud_module, "HAS_APPKIT", True)
    monkeypatch.setattr(hud_module, "AppHelper", SimpleNamespace(callAfter=lambda fn: fn()))

    hud = HUD()
    hud._window = MagicMock()
    hud._label = MagicMock()
    hud._indicator_view = MagicMock()
    hud._indicator_view.layer.return_value = MagicMock()
    hud._level_bars = []
    hud._ensure_window = MagicMock()
    hud._update_window_frame = MagicMock()
    monkeypatch.setattr(hud, "_get_indicator_color", lambda state: f"color-{state.value}")
    return hud


def test_error_state_enables_click_dismiss(monkeypatch):
    """Error banners should accept clicks across the HUD window."""
    hud = _build_fake_hud(monkeypatch)

    hud.show_error("Transcription failed")

    assert hud.get_state() == HUDState.ERROR
    hud._window.setIgnoresMouseEvents_.assert_called_with(False)


def test_click_dismisses_error_immediately(monkeypatch):
    """Clicking the HUD in error state should hide it immediately."""
    hud = _build_fake_hud(monkeypatch)
    hud.hide = MagicMock()
    hud._state = HUDState.ERROR

    hud._handle_click()

    hud.hide.assert_called_once_with()


def test_click_is_ignored_outside_error_state(monkeypatch):
    """Normal recording and success states should not become click-dismiss targets."""
    hud = _build_fake_hud(monkeypatch)
    hud.hide = MagicMock()
    hud._state = HUDState.SUCCESS

    hud._handle_click()

    hud.hide.assert_not_called()


def test_selects_screen_for_frontmost_app_window(monkeypatch):
    primary = _FakeScreen(_rect(0, 0, 1440, 900))
    secondary = _FakeScreen(_rect(1440, 0, 1728, 1117))
    fake_screens = _FakeNSScreen([primary, secondary])

    monkeypatch.setattr("whisper_hud.hud.HAS_APPKIT", True)
    monkeypatch.setattr("whisper_hud.hud.NSScreen", fake_screens)
    monkeypatch.setattr("whisper_hud.hud.NSWorkspace", _FakeWorkspaceClass(pid=4242))
    monkeypatch.setattr(
        "whisper_hud.hud.CGWindowListCopyWindowInfo",
        lambda _opts, _window_id: [
            {
                "kCGWindowOwnerPID": 4242,
                "kCGWindowBounds": {"X": 1500, "Y": 100, "Width": 1200, "Height": 800},
            }
        ],
    )
    monkeypatch.setattr("whisper_hud.hud.kCGWindowListOptionOnScreenOnly", 1)
    monkeypatch.setattr("whisper_hud.hud.kCGNullWindowID", 0)

    hud = HUD()

    assert hud._screen_for_frontmost_window() is secondary


def test_single_monitor_uses_main_screen(monkeypatch):
    primary = _FakeScreen(_rect(0, 0, 1440, 900))
    fake_screens = _FakeNSScreen([primary])

    monkeypatch.setattr("whisper_hud.hud.HAS_APPKIT", True)
    monkeypatch.setattr("whisper_hud.hud.NSScreen", fake_screens)

    hud = HUD()

    assert hud._screen_for_frontmost_window() is primary


def test_window_frame_is_clamped_to_visible_screen(monkeypatch):
    tiny_screen = _FakeScreen(_rect(10, 20, 120, 30))

    monkeypatch.setattr("whisper_hud.hud.NSMakeRect", _rect)

    hud = HUD()
    frame = hud._window_frame_for_screen(tiny_screen)

    assert frame.origin.x == 10
    assert frame.origin.y == 20
    assert frame.size.width == 120
    assert frame.size.height == 30


def test_show_error_truncates_to_120_characters(monkeypatch):
    hud = HUD()
    shown = {}
    scheduled = {}

    monkeypatch.setattr(hud, "_show", lambda text, state: shown.update({"text": text, "state": state}))
    monkeypatch.setattr(hud, "_schedule_dismiss", lambda delay: scheduled.update({"delay": delay}))

    long_message = "x" * 140
    hud.show_error(long_message)

    assert len(shown["text"]) == 120
    assert shown["text"].endswith("\u2026")
    assert scheduled["delay"] == 6.5
