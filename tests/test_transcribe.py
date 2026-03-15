"""Tests for transcription manager provider wiring."""

from dataclasses import replace

import whisper_hud.transcribe as transcribe_module
from whisper_hud.providers.base import LiveTranscriptionSession, TranscriptionProvider, TranscriptionResult
from whisper_hud.transcribe import TranscriptionManager


class DummyLiveSession(LiveTranscriptionSession):
    """Minimal live session test double."""

    def __init__(self):
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def push_audio(self, audio_chunk, sample_rate: int) -> None:
        return None

    def request_stop(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def is_ready(self) -> bool:
        return True


class DummyLiveProvider(TranscriptionProvider):
    """Minimal provider implementing the live session contract."""

    name = "dummy_live"
    display_name = "Dummy Live"

    def __init__(self, model: str = ""):
        self.model = model
        self.session = DummyLiveSession()

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        return TranscriptionResult(
            text="",
            duration_seconds=0.0,
            cost_estimate=0.0,
            provider=self.name,
            model=self.model,
        )

    def is_configured(self) -> bool:
        return True

    def get_models(self) -> list[dict]:
        return [{"id": "dummy-model", "name": "Dummy"}]

    def set_model(self, model_id: str) -> None:
        self.model = model_id

    def get_current_model(self) -> str:
        return self.model

    def supports_live_input(self) -> bool:
        return True

    def create_live_session(self, **kwargs) -> LiveTranscriptionSession:
        return self.session


def test_manager_lists_openai_realtime_with_openai_credentials(mock_config):
    """OpenAI Realtime should appear as a distinct cloud provider using the OpenAI key."""
    manager = TranscriptionManager(mock_config)

    providers = manager.get_available_providers(configured_providers=["openai"])
    provider_map = {provider["id"]: provider for provider in providers}

    assert "openai_realtime" in provider_map
    assert provider_map["openai_realtime"]["configured"] is True
    assert provider_map["openai_realtime"]["category"] == "cloud"
    assert manager.is_cloud_provider("openai_realtime") is True
    assert [model["id"] for model in provider_map["openai_realtime"]["models"]] == [
        "gpt-4o-mini-transcribe",
        "gpt-4o-transcribe",
    ]


def test_manager_can_create_live_session(mock_config, monkeypatch):
    """TranscriptionManager should delegate live session creation to the provider."""
    monkeypatch.setattr(TranscriptionManager, "PROVIDER_CLASSES", {"dummy_live": DummyLiveProvider})
    mock_config.default_provider = "dummy_live"

    manager = TranscriptionManager(mock_config)
    session = manager.create_live_session(
        on_partial=lambda text: None,
        on_final=lambda result: None,
        on_error=lambda exc: None,
    )

    assert isinstance(session, DummyLiveSession)
    assert manager.supports_live_input("dummy_live") is True


def test_get_available_providers_caches_provider_metadata(mock_config, monkeypatch):
    """Provider metadata should be cached between calls and rebuilt after config reload."""

    class CountingProvider(TranscriptionProvider):
        instances = 0
        configured = True
        models = [{"id": "dummy-model", "name": "Dummy"}]
        availability_message = "available"
        installed = True
        apple_silicon = True

        def __init__(self, model: str = ""):
            type(self).instances += 1
            self.model = model

        def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
            return TranscriptionResult(
                text="",
                duration_seconds=0.0,
                cost_estimate=0.0,
                provider=self.name,
                model=self.model,
            )

        def is_configured(self) -> bool:
            return self.configured

        def get_models(self) -> list[dict]:
            return self.models

        def set_model(self, model_id: str) -> None:
            self.model = model_id

        def get_current_model(self) -> str:
            return self.model

        @classmethod
        def get_availability_message(cls) -> str:
            return cls.availability_message

        @classmethod
        def is_faster_whisper_installed(cls) -> bool:
            return cls.installed

        @classmethod
        def is_parakeet_installed(cls) -> bool:
            return cls.installed

        @classmethod
        def is_apple_silicon(cls) -> bool:
            return cls.apple_silicon

    class CountingOpenAIProvider(CountingProvider):
        name = "openai"

    class CountingRealtimeProvider(CountingProvider):
        name = "openai_realtime"

    class CountingGeminiProvider(CountingProvider):
        name = "gemini"

    class CountingAppleProvider(CountingProvider):
        name = "apple"

    class CountingWhisperProvider(CountingProvider):
        name = "whisper_local"

    class CountingParakeetProvider(CountingProvider):
        name = "parakeet"

    provider_classes = {
        "openai": CountingOpenAIProvider,
        "openai_realtime": CountingRealtimeProvider,
        "gemini": CountingGeminiProvider,
        "apple": CountingAppleProvider,
        "whisper_local": CountingWhisperProvider,
        "parakeet": CountingParakeetProvider,
    }

    monkeypatch.setattr(transcribe_module, "OpenAITranscribeProvider", CountingOpenAIProvider)
    monkeypatch.setattr(transcribe_module, "OpenAIRealtimeProvider", CountingRealtimeProvider)
    monkeypatch.setattr(transcribe_module, "GeminiProvider", CountingGeminiProvider)
    monkeypatch.setattr(transcribe_module, "AppleSpeechProvider", CountingAppleProvider)
    monkeypatch.setattr(transcribe_module, "WhisperLocalProvider", CountingWhisperProvider)
    monkeypatch.setattr(transcribe_module, "ParakeetProvider", CountingParakeetProvider)
    monkeypatch.setattr(TranscriptionManager, "PROVIDER_CLASSES", provider_classes)
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    reloaded_config = replace(mock_config, openai_model="updated-openai-model")
    monkeypatch.setattr(transcribe_module.Config, "load", classmethod(lambda cls: reloaded_config))

    manager = TranscriptionManager(mock_config)

    first = manager.get_available_providers(configured_providers=["openai"])
    second = manager.get_available_providers(configured_providers=["gemini"])

    assert CountingOpenAIProvider.instances == 1
    assert CountingRealtimeProvider.instances == 1
    assert CountingGeminiProvider.instances == 1
    assert CountingAppleProvider.instances == 1
    assert CountingWhisperProvider.instances == 1
    assert CountingParakeetProvider.instances == 1
    assert next(provider for provider in first if provider["id"] == "openai")["configured"] is True
    assert next(provider for provider in second if provider["id"] == "openai")["configured"] is False
    assert next(provider for provider in second if provider["id"] == "gemini")["configured"] is True

    manager.reload_config()
    manager.get_available_providers(configured_providers=["openai"])

    assert CountingOpenAIProvider.instances == 2
    assert CountingRealtimeProvider.instances == 2
    assert CountingGeminiProvider.instances == 2
    assert CountingAppleProvider.instances == 2
    assert CountingWhisperProvider.instances == 2
    assert CountingParakeetProvider.instances == 2
