"""App-level tests for menu construction and recording dispatch flows."""

import sys
import threading
import types
from unittest.mock import MagicMock

import pytest

from whisper_hud.app import ActiveTranscriptionTurn, RecordingTurnPhase, WhisperHUDApp
from whisper_hud.config import Config
from whisper_hud.providers.base import TranscriptionResult


class FakeMenuItem:
    """Minimal rumps.MenuItem replacement for menu assertions."""

    def __init__(self, title, callback=None):
        self.title = title
        self.callback = callback
        self.items = []

    def add(self, item):
        self.items.append(item)


class FakeMenu:
    """Minimal rumps menu container used by _build_menu tests."""

    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def clear(self):
        self.items.clear()


class AppHarness(WhisperHUDApp):
    """Test subclass that lazily supplies callback attributes."""

    def __getattr__(self, name):
        mock = MagicMock(name=name)
        setattr(self, name, mock)
        return mock


class ImmediateThread:
    """Thread stand-in that executes the target immediately."""

    def __init__(self, *, target, daemon=None):
        self._target = target
        self.daemon = daemon

    def start(self):
        self._target()


def _build_recording_app():
    """Construct a partial app instance for recording-flow tests."""
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app._recording_lock = threading.Lock()
    app._lock = threading.Lock()
    app._is_recording = False
    app._turn_counter = 0
    app._active_turn = None
    app.ICON_RECORDING = "recording"
    app.ICON_ERROR = "error"
    app.ICON_SUCCESS = "success"
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


def _build_menu_app(monkeypatch):
    """Construct a partial app instance for _build_menu assertions."""
    fake_rumps = types.SimpleNamespace(MenuItem=FakeMenuItem, separator=object())
    monkeypatch.setattr("whisper_hud.app.rumps", fake_rumps)

    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.recorder",
        types.SimpleNamespace(get_input_devices=lambda: []),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.launch_agent",
        types.SimpleNamespace(is_launch_at_login_enabled=lambda: False),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.encryption",
        types.SimpleNamespace(is_cryptography_installed=lambda: True),
    )

    import whisper_hud

    monkeypatch.setattr(whisper_hud, "__version__", "test-version", raising=False)

    app = AppHarness.__new__(AppHarness)
    app._menu = FakeMenu()
    app._menu_is_open = False
    app._pending_menu_rebuild = False
    app._menu_action_lock = threading.Lock()
    app._is_recording = False
    app._is_downloading = False
    app._translation_availability = {}
    app._translation_availability_inflight = False
    app._translation_availability_last_checked = 0.0
    app._cached_tmux_sessions = []
    app._cached_iterm2_running = False
    app._cached_terminal_running = False
    app._cached_running_apps = []
    app.character_pack_manager = MagicMock()
    app.character_pack_manager.get_pack_for_menu.return_value = []
    app.character_pack_manager.get_current_pack_id.return_value = None
    app.transcriber = MagicMock()
    app.translator = MagicMock()
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app.config.default_provider = "openai"
    app.config.translation_enabled = False
    app.config.show_widget = False
    app.config.show_hud = True
    app.config.auto_stop = False
    app.config.auto_paste = True
    app.config.restore_clipboard = True
    app.config.private_mode = False
    app.config.history_enabled = False
    app.config.play_sound = False
    app.config.show_notifications = True
    app.config.streaming_enabled = False
    app.config.audio_input_device = None
    app.config.paste_target_enabled = False
    app.config.paste_target_type = "focused"
    app.config.paste_target_identifier = ""
    app.config.paste_target_return_focus = True
    app.config.max_recording_duration = 600
    app.config.target_language = "en"
    app.config.source_language = "auto"
    app.config.hotkey = ["cmd", "shift", "space"]
    app.config.hotkey_mode = "push_to_talk"
    app.config.history = []
    app.config.history_encrypted = False
    app.config.widget_appearance["theme"] = "default"

    provider_objects = {
        "openai": MagicMock(
            get_models=MagicMock(return_value=[{"id": "gpt-4o", "name": "GPT-4o", "recommended": True}]),
            get_current_model=MagicMock(return_value="gpt-4o"),
            is_configured=MagicMock(return_value=True),
        ),
        "whisper_local": MagicMock(
            get_models=MagicMock(return_value=[{"id": "tiny", "name": "Tiny", "downloaded": False}]),
            get_current_model=MagicMock(return_value="tiny"),
            is_configured=MagicMock(return_value=False),
        ),
    }
    app.transcriber.get_provider.side_effect = lambda provider_id: provider_objects.get(provider_id)
    app.transcriber.get_available_providers.return_value = [
        {"id": "openai", "name": "OpenAI", "category": "cloud", "configured": True},
        {
            "id": "whisper_local",
            "name": "Whisper Local",
            "category": "local",
            "configured": False,
            "requires_download": True,
        },
    ]
    app.transcriber.get_stats.return_value = {"total_transcriptions": 0, "total_cost": 0.0}

    app.translator.get_current_provider.return_value = "apple"
    app.translator.get_current_model.return_value = "en-US"

    app._log_menu_trace = MagicMock()
    app._clear_menu_callback_registry = MagicMock()
    app._wrap_menu_callbacks = MagicMock()
    app._set_title = MagicMock()
    app._get_idle_icon = MagicMock(return_value="idle")
    app._credential_mode = MagicMock(return_value="passphrase")
    app._is_passphrase_store_locked = MagicMock(return_value=False)
    app._should_query_keychain = MagicMock(return_value=False)
    app._get_configured_cloud_providers = MagicMock(return_value=["openai"])
    app._get_provider_display_name = MagicMock(
        side_effect=lambda provider_id: {
            "openai": "OpenAI",
            "whisper_local": "Whisper Local",
            "apple": "Apple",
        }.get(provider_id, provider_id)
    )
    app._is_transcription_provider_configured = MagicMock(
        side_effect=lambda provider_id, configured: provider_id in configured
    )
    app._get_paste_target_display_name = MagicMock(return_value="Notes")
    app._is_target_available_cached = MagicMock(return_value=True)
    app._get_valid_recent_targets = MagicMock(return_value=[])
    app._format_target_for_menu = MagicMock(side_effect=lambda target_type, target_id, short=False: target_id)
    return app


def _menu_titles(menu):
    """Return the titles of non-separator items in a menu container."""
    return [item.title for item in menu.items if hasattr(item, "title")]


def test_build_menu_reflects_provider_availability(monkeypatch):
    """The menu should expose provider readiness within the merged providers submenu."""
    app = _build_menu_app(monkeypatch)

    app._build_menu()

    top_level_titles = _menu_titles(app.menu)
    assert top_level_titles[0] == "✓ Ready • OpenAI"
    assert top_level_titles[1:] == [
        "Providers & Keys",
        "Paste Target",
        "Translation",
        "Settings",
        "Quit WhisperHUD",
    ]
    assert len(top_level_titles) <= 6

    provider_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Providers & Keys")
    provider_titles = _menu_titles(provider_menu)
    assert "Current: OpenAI" in provider_titles
    assert "● OpenAI ✓" in provider_titles
    assert "   Whisper Local [download] ⬇️" in provider_titles
    assert "OpenAI: Not set" in provider_titles

    settings_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Settings")
    settings_titles = _menu_titles(settings_menu)
    assert "Appearance" in settings_titles
    assert "Hotkey" in settings_titles
    assert "Advanced & Support" in settings_titles

    recording_menu = next(item for item in settings_menu.items if getattr(item, "title", None) == "Recording & Display")
    recording_titles = _menu_titles(recording_menu)
    assert "Reset Position" in recording_titles


def test_hotkey_press_starts_recording():
    """Starting a hotkey turn should mark recording active and start the recorder."""
    app = _build_recording_app()
    app.transcriber.supports_live_input.return_value = False

    app._start_recording()

    assert app._is_recording is True
    assert app._active_turn.provider_id == "openai"
    app.recorder.start.assert_called_once_with(on_audio_chunk=None)
    app.hud.show_recording.assert_called_once_with()
    app._start_level_monitor.assert_called_once_with(1)
    app._start_max_duration_timer.assert_called_once_with(1)


def test_hotkey_release_stops_recording_and_dispatches_transcription():
    """Stopping a recording turn without a ready live session should fall back to batch dispatch."""
    app = _build_recording_app()
    app._is_recording = True
    app._active_turn = ActiveTranscriptionTurn(turn_id=7, provider_id="openai")
    app.recorder.stop.return_value = b"x" * 2000
    app._degrade_turn_to_batch = MagicMock()

    app._stop_recording()

    assert app._is_recording is False
    assert app._active_turn.stop_reason == "manual_release"
    assert app._active_turn.batch_fallback_started is True
    app.recorder.stop.assert_called_once_with()
    app._degrade_turn_to_batch.assert_called_once_with(7, "Stop requested before live session ready (manual_release)")


def test_transcription_result_is_dispatched_to_paste_pipeline(monkeypatch):
    """Successful final text should be sent through the paste target pipeline."""
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(turn_id=3, provider_id="openai")
    app._paste_to_target = MagicMock(return_value=True)
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    result = TranscriptionResult(
        text="hello world",
        duration_seconds=1.0,
        cost_estimate=0.01,
        provider="openai",
        model="gpt-4o",
    )

    app._process_turn_result(3, result, use_streaming=False, stats_already_recorded=True)

    app._paste_to_target.assert_called_once_with("hello world")
    app.hud.show_success.assert_called_once_with("Done! (2 words)")
    app._finish_turn_cleanup.assert_called_once_with(3)


def test_empty_transcription_suppresses_success_hud(monkeypatch):
    """Whitespace-only transcriptions should not surface a success banner."""
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(turn_id=5, provider_id="openai")
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)

    result = TranscriptionResult(
        text="   ",
        duration_seconds=1.0,
        cost_estimate=0.01,
        provider="openai",
        model="gpt-4o",
    )

    app._process_turn_result(5, result, use_streaming=False, stats_already_recorded=True)

    app.hud.show_success.assert_not_called()
    app.hud.show_error.assert_called_once_with("No speech detected")
    app._play_completion_sound.assert_not_called()
    app._finish_turn_cleanup.assert_called_once_with(5)


def test_hud_success_message_formats_word_count():
    assert WhisperHUDApp._hud_success_message("hello") == "Done! (1 word)"
    assert WhisperHUDApp._hud_success_message("hello world") == "Done! (2 words)"
    assert WhisperHUDApp._hud_success_message("   ") == "Nothing detected"


def test_hud_success_message_preserves_suffix():
    assert WhisperHUDApp._hud_success_message("hello", " -> French") == "Done! (1 word) -> French"


def test_transcription_failure_shows_hud_error():
    """Transcription errors should surface a terminal HUD error state."""
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(turn_id=4, provider_id="openai")

    app._handle_transcription_error(4, RuntimeError("boom"), use_streaming=False)

    app.hud.show_error.assert_called_once_with("Transcription failed")
    app._notify.assert_called_once_with("WhisperHUD", "Transcription failed", "boom")
    app._finish_turn_cleanup.assert_called_once_with(4)


def test_select_provider_updates_config_and_rebuilds_menu():
    """Selecting a provider should persist the new default provider and rebuild the menu."""
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app._schedule_menu_rebuild = MagicMock()

    app._select_provider("gemini")

    assert app.config.default_provider == "gemini"
    app.config.save.assert_called_once_with()
    app._schedule_menu_rebuild.assert_called_once_with()
