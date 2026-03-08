"""Tests for transcription manager provider wiring."""

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
