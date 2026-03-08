"""Focused app-level tests for the Realtime turn state machine."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from whisper_hud.app import ActiveTranscriptionTurn, RecordingTurnPhase, WhisperHUDApp


class FakeLiveSession:
    """Minimal live-session stand-in for turn-state tests."""

    def __init__(self, ready: bool):
        self._ready = ready
        self.closed = False
        self.stop_requested = False

    def is_ready(self) -> bool:
        return self._ready

    def request_stop(self) -> None:
        self.stop_requested = True

    def close(self) -> None:
        self.closed = True


def _build_app_stub():
    """Construct a partial WhisperHUDApp instance for private-method tests."""
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app._recording_lock = threading.Lock()
    app._lock = threading.Lock()
    app._is_recording = True
    app.ICON_PROCESSING = "processing"
    app._set_title = MagicMock()
    app._get_idle_icon = MagicMock(return_value="idle")
    app._schedule_menu_rebuild = MagicMock()
    app._notify = MagicMock()
    app._play_completion_sound = MagicMock()
    app._paste_to_target = MagicMock()
    app.widget = None
    app.hud = SimpleNamespace(show_processing=MagicMock(), hide=MagicMock())
    app.streaming_panel = SimpleNamespace(hide=MagicMock())
    app.config = SimpleNamespace(
        show_hud=False,
        streaming_enabled=False,
        translation_enabled=False,
    )
    app.recorder = SimpleNamespace(stop=MagicMock(return_value=b"x" * 2000))
    return app


def test_request_stop_falls_back_to_batch_once_when_live_not_ready():
    """Stopping before the live session becomes ready should trigger one batch fallback."""
    app = _build_app_stub()
    turn = ActiveTranscriptionTurn(
        turn_id=1,
        provider_id="openai_realtime",
        phase=RecordingTurnPhase.STARTING,
        live_session=FakeLiveSession(ready=False),
    )
    app._active_turn = turn
    app._degrade_turn_to_batch = MagicMock()

    app._request_stop("manual_release")
    app._request_stop("manual_release")

    assert app._is_recording is False
    assert turn.batch_fallback_started is True
    assert turn.audio_bytes == b"x" * 2000
    app._degrade_turn_to_batch.assert_called_once()


def test_finish_turn_cleanup_skips_newer_active_turn(monkeypatch):
    """Delayed cleanup from an older turn must not reset a newer one."""
    app = _build_app_stub()
    newer_turn = ActiveTranscriptionTurn(turn_id=2, provider_id="openai")
    app._active_turn = newer_turn
    app.widget = SimpleNamespace(set_idle=MagicMock())

    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    app._finish_turn_cleanup(1)

    assert app._active_turn is newer_turn
    app._set_title.assert_not_called()
    app.widget.set_idle.assert_not_called()
