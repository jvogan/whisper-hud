"""Tests for transcription manager provider wiring."""

from dataclasses import replace

import pytest

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


class StubProvider(TranscriptionProvider):
    """Configurable provider stub for dispatch and fallback tests."""

    name = "stub"
    display_name = "Stub"
    configured = True
    transcribed_text = "stub result"
    cost_estimate = 0.0
    instances = 0
    transcribe_calls = 0
    last_audio_bytes = None

    def __init__(self, model: str = ""):
        type(self).instances += 1
        self.model = model

    @classmethod
    def reset_class_state(cls) -> None:
        cls.instances = 0
        cls.transcribe_calls = 0
        cls.last_audio_bytes = None

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        type(self).transcribe_calls += 1
        type(self).last_audio_bytes = audio_bytes
        return TranscriptionResult(
            text=self.transcribed_text,
            duration_seconds=1.25,
            cost_estimate=self.cost_estimate,
            provider=self.name,
            model=self.model,
        )

    def is_configured(self) -> bool:
        return self.configured

    def get_models(self) -> list[dict]:
        return [{"id": "dummy-model", "name": "Dummy"}]

    def set_model(self, model_id: str) -> None:
        self.model = model_id

    def get_current_model(self) -> str:
        return self.model


class CountingMetadataProvider(StubProvider):
    """Provider stub with metadata hooks used by the availability cache."""

    availability_message = "available"
    installed = True
    apple_silicon = True

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


class CountingOpenAIProvider(CountingMetadataProvider):
    name = "openai"
    display_name = "OpenAI"


class CountingRealtimeProvider(CountingMetadataProvider):
    name = "openai_realtime"
    display_name = "OpenAI Realtime"


class CountingGeminiProvider(CountingMetadataProvider):
    name = "gemini"
    display_name = "Gemini"


class CountingAppleProvider(CountingMetadataProvider):
    name = "apple"
    display_name = "Apple"


class CountingWhisperProvider(CountingMetadataProvider):
    name = "whisper_local"
    display_name = "Whisper Local"


class CountingParakeetProvider(CountingMetadataProvider):
    name = "parakeet"
    display_name = "Parakeet"


class PrimaryProvider(StubProvider):
    name = "openai"
    display_name = "Primary"
    configured = False
    transcribed_text = "primary result"


class SecondaryProvider(StubProvider):
    name = "gemini"
    display_name = "Secondary"
    configured = True
    transcribed_text = "fallback result"
    cost_estimate = 0.42


class AppleFallbackProvider(StubProvider):
    name = "apple"
    display_name = "Apple"
    configured = False
    transcribed_text = "apple result"


class WhisperFallbackProvider(StubProvider):
    name = "whisper_local"
    display_name = "Whisper Local"
    configured = False
    transcribed_text = "whisper result"


class ParakeetFallbackProvider(StubProvider):
    name = "parakeet"
    display_name = "Parakeet"
    configured = False
    transcribed_text = "parakeet result"


def reset_provider_classes(*provider_classes: type[StubProvider]) -> None:
    """Reset per-class counters so assertions stay isolated."""
    for provider_class in provider_classes:
        provider_class.reset_class_state()


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


def test_get_available_providers_only_instantiates_once_until_cache_invalidated(mock_config, monkeypatch):
    """Provider metadata should be built once and rebuilt only after cache invalidation."""
    provider_classes = {
        "openai": CountingOpenAIProvider,
        "openai_realtime": CountingRealtimeProvider,
        "gemini": CountingGeminiProvider,
        "apple": CountingAppleProvider,
        "whisper_local": CountingWhisperProvider,
        "parakeet": CountingParakeetProvider,
    }

    reset_provider_classes(*provider_classes.values())
    monkeypatch.setattr(transcribe_module, "OpenAITranscribeProvider", CountingOpenAIProvider)
    monkeypatch.setattr(transcribe_module, "OpenAIRealtimeProvider", CountingRealtimeProvider)
    monkeypatch.setattr(transcribe_module, "GeminiProvider", CountingGeminiProvider)
    monkeypatch.setattr(transcribe_module, "AppleSpeechProvider", CountingAppleProvider)
    monkeypatch.setattr(transcribe_module, "WhisperLocalProvider", CountingWhisperProvider)
    monkeypatch.setattr(transcribe_module, "ParakeetProvider", CountingParakeetProvider)
    monkeypatch.setattr("platform.system", lambda: "Darwin")

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

    manager.set_provider_model("openai", "updated-openai-model")
    manager.get_available_providers(configured_providers=["openai"])

    assert CountingOpenAIProvider.instances == 2
    assert CountingRealtimeProvider.instances == 2
    assert CountingGeminiProvider.instances == 2
    assert CountingAppleProvider.instances == 2
    assert CountingWhisperProvider.instances == 2
    assert CountingParakeetProvider.instances == 2


def test_reload_config_invalidates_cache_and_updates_provider_models(mock_config, monkeypatch):
    """Reloading config should invalidate cached metadata and update provider instances."""
    provider_classes = {
        "openai": CountingOpenAIProvider,
        "openai_realtime": CountingRealtimeProvider,
        "gemini": CountingGeminiProvider,
        "apple": CountingAppleProvider,
        "whisper_local": CountingWhisperProvider,
        "parakeet": CountingParakeetProvider,
    }

    reset_provider_classes(*provider_classes.values())
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
    provider = manager.get_provider("openai")
    manager.get_available_providers(configured_providers=["openai"])

    assert provider is not None
    assert provider.get_current_model() == mock_config.openai_model
    assert CountingOpenAIProvider.instances == 2

    manager.reload_config()
    manager.get_available_providers(configured_providers=["openai"])

    assert provider.get_current_model() == "updated-openai-model"
    assert CountingOpenAIProvider.instances == 3
    assert CountingRealtimeProvider.instances == 2
    assert CountingGeminiProvider.instances == 2
    assert CountingAppleProvider.instances == 2
    assert CountingWhisperProvider.instances == 2
    assert CountingParakeetProvider.instances == 2


def test_transcribe_falls_back_to_next_configured_provider(mock_config, monkeypatch, sample_audio_bytes):
    """An unavailable primary provider should dispatch transcription to the next configured provider."""
    provider_classes = {
        "openai": PrimaryProvider,
        "gemini": SecondaryProvider,
        "apple": AppleFallbackProvider,
        "whisper_local": WhisperFallbackProvider,
        "parakeet": ParakeetFallbackProvider,
    }

    reset_provider_classes(*provider_classes.values())
    monkeypatch.setattr(TranscriptionManager, "PROVIDER_CLASSES", provider_classes)
    mock_config.default_provider = "openai"

    manager = TranscriptionManager(mock_config)
    result = manager.transcribe(sample_audio_bytes)

    assert result.text == "fallback result"
    assert result.provider == "gemini"
    assert result.model == mock_config.gemini_model
    assert PrimaryProvider.transcribe_calls == 0
    assert SecondaryProvider.transcribe_calls == 1
    assert SecondaryProvider.last_audio_bytes == sample_audio_bytes
    assert mock_config.total_transcriptions == 1
    assert mock_config.total_cost == pytest.approx(0.42)


def test_transcribe_raises_when_no_providers_are_available(mock_config, monkeypatch, sample_audio_bytes):
    """Transcription should fail cleanly when neither the primary provider nor any fallback is configured."""
    provider_classes = {
        "openai": PrimaryProvider,
        "gemini": SecondaryProvider,
        "apple": AppleFallbackProvider,
        "whisper_local": WhisperFallbackProvider,
        "parakeet": ParakeetFallbackProvider,
    }

    reset_provider_classes(*provider_classes.values())
    SecondaryProvider.configured = False
    monkeypatch.setattr(TranscriptionManager, "PROVIDER_CLASSES", provider_classes)
    mock_config.default_provider = "openai"

    manager = TranscriptionManager(mock_config)

    with pytest.raises(ValueError, match="Provider 'openai' is not configured"):
        manager.transcribe(sample_audio_bytes)

    assert PrimaryProvider.transcribe_calls == 0
    assert SecondaryProvider.transcribe_calls == 0
    assert mock_config.total_transcriptions == 0
    assert mock_config.total_cost == 0.0

    SecondaryProvider.configured = True
