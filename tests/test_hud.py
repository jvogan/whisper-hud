"""HUD behavior tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import whisper_hud.hud as hud_module
from whisper_hud.hud import HUD, HUDState


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
