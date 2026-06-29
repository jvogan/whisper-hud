"""Tests for the OpenAI Whisper transcription provider."""

from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from whisper_hud.providers.openai_whisper import OpenAITranscribeProvider


class _FakeClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create_transcription))

    def _create_transcription(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def test_provider_reports_unavailable_when_openai_package_not_installed(monkeypatch):
    """Availability should be false when the SDK cannot be imported."""
    provider = OpenAITranscribeProvider()

    def raise_missing_sdk():
        raise RuntimeError("openai package not installed. Install with: pip install openai")

    monkeypatch.setattr(provider, "_get_openai_client_class", raise_missing_sdk)
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")

    assert provider.is_available() is False


def test_provider_reports_unavailable_when_api_key_not_set(monkeypatch):
    """Availability should be false without an OpenAI API key."""
    provider = OpenAITranscribeProvider()
    monkeypatch.setattr(provider, "_get_openai_client_class", lambda: object)
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: None)

    assert provider.is_available() is False
    assert provider.is_configured() is False


def test_provider_reports_available_when_key_present_and_package_installed(monkeypatch):
    """Availability should be true when the SDK loads and a key exists."""
    provider = OpenAITranscribeProvider()
    monkeypatch.setattr(provider, "_get_openai_client_class", lambda: object)
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")

    assert provider.is_available() is True
    assert provider.is_configured() is True


def test_client_pins_openai_base_url_and_disables_env_routing(monkeypatch):
    """The OpenAI client should ignore ambient base-url and proxy environment state."""
    captured_kwargs = {}
    fake_client = _FakeClient(response=SimpleNamespace(text="ok"))

    def fake_openai_client(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_client

    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: fake_openai_client),
    )

    provider = OpenAITranscribeProvider()

    assert provider.client is fake_client
    assert captured_kwargs["base_url"] == "https://api.openai.com/v1"
    assert captured_kwargs["http_client"].trust_env is False
    assert captured_kwargs["http_client"].follow_redirects is False
    captured_kwargs["http_client"].close()


def test_transcribe_returns_empty_result_for_empty_audio():
    """Empty audio should short-circuit without touching the API."""
    result = OpenAITranscribeProvider().transcribe(b"")

    assert result.text == ""
    assert result.duration_seconds == 0
    assert result.cost_estimate == 0
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini-transcribe"


def test_transcribe_returns_text_on_success(monkeypatch, sample_audio_bytes):
    """The default JSON transcription path should strip returned text."""
    fake_client = _FakeClient(response=SimpleNamespace(text="  Hello from OpenAI  "))
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: lambda **_: fake_client),
    )

    provider = OpenAITranscribeProvider(model="gpt-4o-mini-transcribe")
    result = provider.transcribe(sample_audio_bytes)

    assert result.text == "Hello from OpenAI"
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini-transcribe"
    assert result.duration_seconds == pytest.approx(len(sample_audio_bytes) / 32000)
    assert result.cost_estimate == pytest.approx((result.duration_seconds / 60) * 0.003)
    assert result.language is None
    assert fake_client.calls == [
        {
            "model": "gpt-4o-mini-transcribe",
            "file": ANY,
            "response_format": "json",
        }
    ]
    assert fake_client.calls[0]["file"].name == "recording.wav"


def test_whisper_v1_transcribe_uses_verbose_json_fields(monkeypatch, sample_audio_bytes):
    """The legacy whisper-1 path should preserve API duration and language fields."""
    fake_client = _FakeClient(
        response=SimpleNamespace(
            text="  Bonjour  ",
            duration=12.5,
            language="fr",
        )
    )
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: lambda **_: fake_client),
    )

    result = OpenAITranscribeProvider(model="whisper-1").transcribe(sample_audio_bytes)

    assert result.text == "Bonjour"
    assert result.duration_seconds == pytest.approx(12.5)
    assert result.language == "fr"
    assert result.cost_estimate == pytest.approx((12.5 / 60) * 0.006)
    assert fake_client.calls[0]["response_format"] == "verbose_json"


def test_diarized_transcription_extracts_text_from_segments(monkeypatch, sample_audio_bytes):
    """Diarized responses should fall back to concatenated segment text."""
    fake_client = _FakeClient(
        response={
            "segments": [
                {"speaker": "speaker_0", "text": " Hello "},
                {"speaker": "speaker_1", "text": " world "},
            ]
        }
    )
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: lambda **_: fake_client),
    )

    result = OpenAITranscribeProvider(model="gpt-4o-transcribe-diarize").transcribe(sample_audio_bytes)

    assert result.text == "Hello world"
    assert result.duration_seconds == pytest.approx(len(sample_audio_bytes) / 32000)
    assert result.language is None
    assert fake_client.calls[0]["response_format"] == "diarized_json"
    assert fake_client.calls[0]["chunking_strategy"] == "auto"


def test_transcribe_raises_runtime_error_on_api_error(monkeypatch, sample_audio_bytes):
    """SDK failures should surface as sanitized RuntimeError messages."""
    fake_client = _FakeClient(error=Exception("Quota exceeded"))
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: lambda **_: fake_client),
    )

    with pytest.raises(RuntimeError, match="OpenAI transcription failed: rate limited"):
        OpenAITranscribeProvider().transcribe(sample_audio_bytes)


def test_transcribe_handles_audio_file_not_found(monkeypatch, sample_audio_bytes):
    """Unexpected local failures should be wrapped without leaking path details."""
    fake_client = _FakeClient(error=FileNotFoundError("missing.wav"))
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: lambda **_: fake_client),
    )

    with pytest.raises(RuntimeError, match="OpenAI transcription failed: unexpected error"):
        OpenAITranscribeProvider().transcribe(sample_audio_bytes)


def test_set_model_updates_known_models_and_resets_cached_client():
    """Model changes should invalidate the cached client only for supported IDs."""
    provider = OpenAITranscribeProvider()
    provider._client = object()

    provider.set_model("whisper-1")

    assert provider.get_current_model() == "whisper-1"
    assert provider._client is None

    sentinel = object()
    provider._client = sentinel
    provider.set_model("not-a-real-model")

    assert provider.get_current_model() == "whisper-1"
    assert provider._client is sentinel


def test_normalize_model_id_maps_realtime_latest_alias():
    """Batch transcription should coerce realtime-only alias slugs to supported batch models."""
    assert OpenAITranscribeProvider.normalize_model_id("gpt-4o-transcribe-latest") == "gpt-4o-transcribe"


def test_vocabulary_is_mapped_to_prompt_glossary(monkeypatch, sample_audio_bytes):
    """Vocabulary should reach the API as a natural-language ``prompt`` glossary string."""
    fake_client = _FakeClient(response=SimpleNamespace(text="ok"))
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: lambda **_: fake_client),
    )

    provider = OpenAITranscribeProvider(model="gpt-4o-mini-transcribe")
    provider.transcribe(sample_audio_bytes, vocabulary=["Kubernetes", "Anthropic", "gRPC"])

    assert fake_client.calls[0]["prompt"] == "Vocabulary: Kubernetes, Anthropic, gRPC."


def test_no_prompt_sent_when_vocabulary_absent_or_empty(monkeypatch, sample_audio_bytes):
    """No ``prompt`` artifact should be sent for None or empty vocabulary."""
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")

    for vocabulary in (None, [], ["", "  "]):
        fake_client = _FakeClient(response=SimpleNamespace(text="ok"))
        monkeypatch.setattr(
            OpenAITranscribeProvider,
            "_get_openai_client_class",
            staticmethod(lambda fc=fake_client: lambda **_: fc),
        )
        OpenAITranscribeProvider(model="gpt-4o-mini-transcribe").transcribe(sample_audio_bytes, vocabulary=vocabulary)
        assert "prompt" not in fake_client.calls[0]


def test_diarize_model_never_sends_prompt(monkeypatch, sample_audio_bytes):
    """The diarize model rejects ``prompt``, so vocabulary must be skipped for it."""
    fake_client = _FakeClient(response={"text": "Hello world"})
    monkeypatch.setattr("whisper_hud.providers.openai_whisper.get_api_key", lambda _: "sk-test")
    monkeypatch.setattr(
        OpenAITranscribeProvider,
        "_get_openai_client_class",
        staticmethod(lambda: lambda **_: fake_client),
    )

    OpenAITranscribeProvider(model="gpt-4o-transcribe-diarize").transcribe(
        sample_audio_bytes, vocabulary=["Kubernetes", "Anthropic"]
    )

    assert "prompt" not in fake_client.calls[0]
    assert fake_client.calls[0]["response_format"] == "diarized_json"
