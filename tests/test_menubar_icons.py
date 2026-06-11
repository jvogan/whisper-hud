"""Tests for the menu bar template icon set and its state resolution."""

from unittest.mock import MagicMock, patch

import pytest

from whisper_hud.branding import (
    MENUBAR_STATE_BY_EMOJI,
    MenuBarIcons,
    get_menubar_icon,
    get_menubar_icon_frames,
    split_menubar_title,
)
from whisper_hud.app import WhisperHUDApp


# ---------------------------------------------------------------------------
# branding: state resolution and assets
# ---------------------------------------------------------------------------


def test_every_state_emoji_maps_to_a_committed_icon_asset():
    """Each emoji state token resolves to a state with a real PNG asset."""
    for emoji, state in MENUBAR_STATE_BY_EMOJI.items():
        assert split_menubar_title(emoji) == (state, "")
        icon = get_menubar_icon(state)
        assert icon is not None, f"missing menubar asset for state {state!r}"
        assert icon.name == f"{state}.png"
        assert icon.exists()


def test_split_preserves_text_suffix():
    state, suffix = split_menubar_title(MenuBarIcons.IDLE + "📍")
    assert state == "idle"
    assert suffix == "📍"


def test_split_unknown_title_passes_through():
    assert split_menubar_title("hello") == (None, "hello")


def test_animated_states_have_ordered_frames():
    processing = get_menubar_icon_frames("processing")
    assert [p.name for p in processing] == [f"processing.frame{i}.png" for i in range(8)]
    recording = get_menubar_icon_frames("recording")
    assert [p.name for p in recording] == [f"recording.frame{i}.png" for i in range(4)]
    assert all(p.exists() for p in processing + recording)


def test_static_states_have_no_frames():
    assert get_menubar_icon_frames("idle") == []
    assert get_menubar_icon_frames("assistant") == []


# ---------------------------------------------------------------------------
# app: title -> status item resolution
# ---------------------------------------------------------------------------


def _status_app():
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app._set_menubar_visuals = MagicMock()
    return app


def test_idle_state_renders_icon_with_suffix_text():
    app = _status_app()
    app._animate_menubar_state = MagicMock()
    app._stop_menubar_animation = MagicMock()

    app._apply_menubar_status(MenuBarIcons.IDLE + "📍")

    icon_path, text = app._set_menubar_visuals.call_args[0]
    assert icon_path.endswith("idle.png")
    assert text == "📍"
    app._animate_menubar_state.assert_called_once_with("idle")
    app._stop_menubar_animation.assert_not_called()


def test_unknown_title_falls_back_to_plain_text():
    app = _status_app()
    app._stop_menubar_animation = MagicMock()

    app._apply_menubar_status("Downloading model 42%")

    app._set_menubar_visuals.assert_called_once_with(None, "Downloading model 42%")
    app._stop_menubar_animation.assert_called_once()


def test_missing_assets_fall_back_to_emoji_title():
    app = _status_app()
    app._stop_menubar_animation = MagicMock()

    with patch("whisper_hud.app.get_menubar_icon", return_value=None):
        app._apply_menubar_status(MenuBarIcons.RECORDING)

    app._set_menubar_visuals.assert_called_once_with(None, MenuBarIcons.RECORDING)
    app._stop_menubar_animation.assert_called_once()


# ---------------------------------------------------------------------------
# app: animated menu bar states
# ---------------------------------------------------------------------------


def test_processing_animation_runs_frame_timer():
    app = _status_app()

    with patch("whisper_hud.app.rumps.Timer") as timer_cls:
        app._animate_menubar_state("processing")

        timer_cls.assert_called_once()
        _callback, interval = timer_cls.call_args[0]
        assert interval == pytest.approx(WhisperHUDApp.MENUBAR_FRAME_INTERVALS["processing"])
        timer_cls.return_value.start.assert_called_once()

        # Re-entering the same state must not restart the timer.
        app._animate_menubar_state("processing")
        assert timer_cls.call_count == 1

        # A tick advances to the next frame and pushes it to the status item.
        app._menubar_anim_tick(None)
        icon_path, text = app._set_menubar_visuals.call_args[0]
        assert "processing.frame1" in icon_path
        assert text is None

        # A static state stops the animation and clears its bookkeeping.
        app._animate_menubar_state("idle")
        timer_cls.return_value.stop.assert_called_once()
        assert app._menubar_anim_state is None
        assert app._menubar_anim_frames == ()


def test_tick_without_frames_is_a_noop():
    app = _status_app()
    app._menubar_anim_tick(None)
    app._set_menubar_visuals.assert_not_called()
