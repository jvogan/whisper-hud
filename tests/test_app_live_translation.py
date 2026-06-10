"""App-level tests for live speech translation wiring (Subsystem A).

Self-contained recording-flow harness (mirrors the WhisperHUDApp.__new__ +
MagicMock pattern in test_app.py); menu assertions reuse test_app's full
_build_menu_app harness, imported via an explicit tests-dir path insert so the
import is independent of pytest collection order.
"""

import os
import sys
import threading
from unittest.mock import MagicMock

# Make sibling test module importable regardless of collection order.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from test_app import ImmediateThread, _build_menu_app, _menu_titles  # noqa: E402

from whisper_hud.app import ActiveTranscriptionTurn, WhisperHUDApp  # noqa: E402
from whisper_hud.config import Config  # noqa: E402
from whisper_hud.providers.base import TranscriptionResult  # noqa: E402


def _build_recording_app():
    """Construct a partial app instance for recording-flow tests."""
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app._recording_lock = threading.Lock()
    app._lock = threading.Lock()
    app._is_recording = False
    app._turn_counter = 0
    app._active_turn = None
    app._voice_assistant = None
    app._assistant_error_notified = False
    app.ICON_RECORDING = "recording"
    app.ICON_ERROR = "error"
    app.ICON_SUCCESS = "success"
    app.ICON_PROCESSING = "processing"
    app._set_title = MagicMock()
    app._get_idle_icon = MagicMock(return_value="idle")
    app._notify = MagicMock()
    app._schedule_menu_rebuild = MagicMock()
    app._play_completion_sound = MagicMock()
    app._ensure_cloud_credentials_ready = MagicMock(return_value=True)
    app._ensure_history_encryption_session = MagicMock()
    app._selected_live_language = MagicMock(return_value=None)
    app._start_level_monitor = MagicMock()
    app._start_max_duration_timer = MagicMock()
    app._start_live_connect_timer = MagicMock(return_value=None)
    app._cancel_turn_timers = MagicMock()
    app._close_live_session = MagicMock()
    app._finish_turn_cleanup = MagicMock()
    app._is_passphrase_store_locked = MagicMock(return_value=False)
    app.widget = None
    app.hud = MagicMock()
    app.streaming_panel = MagicMock()
    app.recorder = MagicMock()
    app.transcriber = MagicMock()
    app.translator = MagicMock()
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app.config.show_hud = True
    app.config.auto_stop = False
    app.config.auto_paste = True
    app.config.translation_enabled = False
    app.config.streaming_enabled = False
    app.config.history_enabled = True
    app.config.history = []
    app.config.private_mode = False
    app.config.history_encrypted = False
    app.config.default_provider = "openai"
    return app


def _live_result(**overrides):
    """Build a TranscriptionResult that looks like a live-translation final."""
    base = dict(
        text="hola mundo",
        duration_seconds=1.0,
        cost_estimate=0.034,
        provider="openai_translate_live",
        model="gpt-realtime-translate",
        language="es",
        source_text="hello world",
    )
    base.update(overrides)
    return TranscriptionResult(**base)


def _configure_for_live_translation(app):
    """Set config so every live-translation precondition is satisfied."""
    app.config.translation_enabled = True
    app.config.live_translation_enabled = True
    app.config.target_language = "es"


# --- (a) _live_translation_active truth table -------------------------------


def test_live_translation_active_all_conditions(monkeypatch):
    app = _build_recording_app()
    _configure_for_live_translation(app)
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")

    assert app._live_translation_active() is True


def test_live_translation_inactive_when_toggle_off(monkeypatch):
    app = _build_recording_app()
    _configure_for_live_translation(app)
    app.config.live_translation_enabled = False
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")

    assert app._live_translation_active() is False


def test_live_translation_inactive_when_translation_off(monkeypatch):
    app = _build_recording_app()
    _configure_for_live_translation(app)
    app.config.translation_enabled = False
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")

    assert app._live_translation_active() is False


def test_live_translation_inactive_when_target_unsupported(monkeypatch):
    app = _build_recording_app()
    _configure_for_live_translation(app)
    app.config.target_language = "tlh"  # Klingon: not a supported target
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")

    assert app._live_translation_active() is False


def test_live_translation_inactive_when_no_key(monkeypatch):
    app = _build_recording_app()
    _configure_for_live_translation(app)
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: None)

    assert app._live_translation_active() is False


# --- (b) _start_recording routes to the live-translation factory ------------


def test_start_recording_routes_to_live_translation_session(monkeypatch):
    app = _build_recording_app()
    _configure_for_live_translation(app)
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")

    fake_session = MagicMock(name="translate_session")
    factory = MagicMock(return_value=fake_session)
    monkeypatch.setattr("whisper_hud.app.create_live_translation_session", factory)

    app._start_recording()

    assert app._active_turn.live_session is fake_session
    assert app._active_turn.live_translation is True
    # The per-provider live transcription path must NOT be used for this turn.
    app.transcriber.create_live_session.assert_not_called()
    # Factory was called with the OpenAI key and the configured target language.
    assert factory.call_args.kwargs["api_key"] == "sk-test"
    assert factory.call_args.kwargs["target_language"] == "es"
    fake_session.start.assert_called_once_with()


def test_start_recording_uses_normal_live_path_when_inactive(monkeypatch):
    app = _build_recording_app()
    # Live translation disabled: should fall through to the normal live path.
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")
    factory = MagicMock()
    monkeypatch.setattr("whisper_hud.app.create_live_translation_session", factory)
    app.transcriber.supports_live_input.return_value = False

    app._start_recording()

    factory.assert_not_called()
    assert app._active_turn.live_translation is False
    assert app._active_turn.live_session is None


# --- (c) finalize: live-translated result skips command handler + translator ---


def test_finalize_live_translated_skips_commands_and_text_translation(monkeypatch):
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(
        turn_id=5,
        provider_id="openai",
        live_translation=True,
    )
    app._paste_to_target = MagicMock(return_value=True)
    app._handle_voice_command = MagicMock()
    app.config.add_to_history = MagicMock(return_value=True)
    app.translator.get_supported_languages.return_value = {"es": "Spanish"}
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    app._process_turn_result(5, _live_result(), use_streaming=False, stats_already_recorded=True)

    # Foreign-language sentence: voice-command handler must never run.
    app._handle_voice_command.assert_not_called()
    # Text already translated: the TEXT translator must never run.
    app.translator.translate.assert_not_called()
    app.translator.translate_streaming.assert_not_called()
    # The translated text is pasted, and history records it as translated with
    # the source transcript as original_text.
    app._paste_to_target.assert_called_once_with("hola mundo")
    history_call = app.config.add_to_history.call_args
    assert history_call.kwargs["text"] == "hola mundo"
    assert history_call.kwargs["translated"] is True
    assert history_call.kwargs["original_text"] == "hello world"
    assert history_call.kwargs["provider"] == "openai_translate_live"


def test_finalize_live_translated_applies_replacements(monkeypatch):
    app = _build_recording_app()
    app.config.text_replacements = [{"pattern": "hola", "replacement": "HOLA"}]
    app._active_turn = ActiveTranscriptionTurn(turn_id=6, provider_id="openai", live_translation=True)
    app._paste_to_target = MagicMock(return_value=True)
    app.config.add_to_history = MagicMock(return_value=True)
    app.translator.get_supported_languages.return_value = {"es": "Spanish"}
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    app._process_turn_result(6, _live_result(), use_streaming=False, stats_already_recorded=True)

    # Replacement applied to the translated text before paste.
    app._paste_to_target.assert_called_once_with("HOLA mundo")


# --- (d) batch-degraded turn (provider != live) takes the normal path -------


def test_finalize_batch_result_on_live_turn_uses_text_translation(monkeypatch):
    app = _build_recording_app()
    app.config.translation_enabled = True
    # Turn started live-translated but degraded to batch; the result carries a
    # batch provider, so the normal transcribe-then-translate path must run.
    app._active_turn = ActiveTranscriptionTurn(turn_id=8, provider_id="openai", live_translation=True)
    app._paste_to_target = MagicMock(return_value=True)
    app._handle_voice_command = MagicMock(return_value=None)
    app.config.add_to_history = MagicMock(return_value=True)
    app.translator.supports_streaming.return_value = False
    app.translator.translate.return_value = TranscriptionResult(
        text="translated text",
        duration_seconds=0.0,
        cost_estimate=0.0,
        provider="apple",
        model="",
    )
    app.translator.get_supported_languages.return_value = {"en": "English"}
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    batch_result = TranscriptionResult(
        text="some english words",
        duration_seconds=1.0,
        cost_estimate=0.0,
        provider="apple",
        model="",
    )
    app._process_turn_result(8, batch_result, use_streaming=False, stats_already_recorded=True)

    # Normal path: voice command handler ran and the TEXT translator was used.
    app._handle_voice_command.assert_called_once()
    app.translator.translate.assert_called_once()
    app._paste_to_target.assert_called_once_with("translated text")


# --- (e) menu shows the toggle; hint lines per missing key / unsupported target ---


def _enable_translation_menu(app):
    """Switch the shared menu harness into a fully-enabled translation state."""
    app.config.translation_enabled = True
    app.config.live_translation_enabled = True
    app.config.target_language = "es"
    # Suppress the background availability probe the enabled menu would spawn.
    app._translation_availability_inflight = True
    app._translation_availability_last_checked = 1e18
    app.translator.get_available_providers.return_value = []
    app.translator.get_supported_languages.return_value = {"es": "Spanish", "en": "English"}


def _translation_submenu(app):
    return next(item for item in app.menu.items if getattr(item, "title", None) == "Translation")


def test_translation_menu_shows_live_toggle(monkeypatch):
    app = _build_menu_app(monkeypatch)  # translation off by default
    app.config.live_translation_enabled = False

    app._build_menu()

    titles = _menu_titles(_translation_submenu(app))
    assert any("Live Speech Translation (OpenAI)" in t for t in titles)


def test_translation_menu_hint_when_no_key(monkeypatch):
    app = _build_menu_app(monkeypatch)
    _enable_translation_menu(app)
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: None)

    app._build_menu()

    titles = _menu_titles(_translation_submenu(app))
    assert any("Add an OpenAI key to use live speech translation" in t for t in titles)


def test_translation_menu_hint_when_target_unsupported(monkeypatch):
    app = _build_menu_app(monkeypatch)
    _enable_translation_menu(app)
    app.config.target_language = "tlh"  # unsupported for live translation
    app.translator.get_supported_languages.return_value = {"tlh": "Klingon"}
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")

    app._build_menu()

    titles = _menu_titles(_translation_submenu(app))
    assert any("Target language not supported for live translation" in t for t in titles)
