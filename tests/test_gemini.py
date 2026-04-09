"""Tests for the Gemini transcription provider."""

from types import ModuleType, SimpleNamespace

import pytest

from whisper_hud.providers.gemini import GeminiProvider


@pytest.fixture
def fake_gemini_sdk(monkeypatch):
    """Install a minimal google.genai SDK surface for provider tests."""

    calls = {"parts": [], "client_api_keys": [], "client_http_timeouts": []}

    class FakePart:
        @staticmethod
        def from_bytes(*, data, mime_type):
            calls["parts"].append({"data": data, "mime_type": mime_type})
            return {"data": data, "mime_type": mime_type}

    class FakeClient:
        def __init__(self, *, api_key, http_options=None):
            calls["client_api_keys"].append(api_key)
            calls["client_http_timeouts"].append(getattr(http_options, "timeout", None))
            self.models = SimpleNamespace()

    class FakeHttpOptions:
        def __init__(self, *, timeout=None, **_kwargs):
            self.timeout = timeout

    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    types_module = ModuleType("google.genai.types")

    genai_module.Client = FakeClient
    genai_module.types = types_module
    types_module.Part = FakePart
    types_module.HttpOptions = FakeHttpOptions
    google_module.genai = genai_module

    monkeypatch.setitem(__import__("sys").modules, "google", google_module)
    monkeypatch.setitem(__import__("sys").modules, "google.genai", genai_module)
    monkeypatch.setitem(__import__("sys").modules, "google.genai.types", types_module)

    return calls


def test_provider_initialization_and_model_helpers():
    """GeminiProvider should expose the expected default interface."""
    provider = GeminiProvider()

    assert provider.get_current_model() == "gemini-2.5-flash"
    assert provider.supports_streaming() is True
    assert provider.get_models() == provider.MODELS

    provider.set_model("gemini-2.5-flash")
    assert provider.get_current_model() == "gemini-2.5-flash"

    provider.set_model("not-a-real-model")
    assert provider.get_current_model() == "gemini-2.5-flash"
    assert GeminiProvider.normalize_model_id("gemini-3-pro-preview") == "gemini-2.5-pro"


def test_provider_reports_unavailable_when_api_key_is_not_set(monkeypatch):
    """Providers without an API key should report unconfigured."""
    monkeypatch.setattr("whisper_hud.providers.gemini.get_api_key", lambda _: None)

    assert GeminiProvider().is_configured() is False


def test_provider_reports_available_when_api_key_is_present(monkeypatch):
    """Providers with an API key should report configured."""
    monkeypatch.setattr("whisper_hud.providers.gemini.get_api_key", lambda _: "gemini-key")

    assert GeminiProvider().is_configured() is True


def test_get_client_builds_and_caches_sdk_client(monkeypatch, fake_gemini_sdk):
    """Client creation should use the configured API key and cache the instance."""
    monkeypatch.setattr("whisper_hud.providers.gemini.get_api_key", lambda _: "gemini-key")
    provider = GeminiProvider()

    first = provider._get_client()
    second = provider._get_client()

    assert first is second
    assert fake_gemini_sdk["client_api_keys"] == ["gemini-key"]
    assert fake_gemini_sdk["client_http_timeouts"] == [30000]


def test_get_client_raises_value_error_when_api_key_is_missing(monkeypatch, fake_gemini_sdk):
    """Client creation should fail fast when the API key is not configured."""
    monkeypatch.setattr("whisper_hud.providers.gemini.get_api_key", lambda _: None)

    with pytest.raises(ValueError, match="Gemini API key not configured"):
        GeminiProvider()._get_client()


def test_transcribe_returns_result_on_success(monkeypatch, sample_audio_bytes, fake_gemini_sdk):
    """Successful transcriptions should return normalized text and metadata."""
    provider = GeminiProvider(model="gemini-2.5-flash")

    class FakeModels:
        def generate_content(self, *, model, contents):
            assert model == "gemini-2.5-flash"
            assert contents[0].startswith("Transcribe this audio exactly as spoken.")
            assert contents[1]["data"] == sample_audio_bytes
            assert contents[1]["mime_type"] == "audio/wav"
            return {"text": "  Hello from Gemini  "}

    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=FakeModels()))

    result = provider.transcribe(sample_audio_bytes)

    assert result.text == "Hello from Gemini"
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"
    assert result.duration_seconds == pytest.approx(len(sample_audio_bytes) / 32000)
    assert result.cost_estimate == pytest.approx((result.duration_seconds / 60) * 0.001)
    assert result.language is None
    assert fake_gemini_sdk["parts"] == [{"data": sample_audio_bytes, "mime_type": "audio/wav"}]


def test_transcribe_raises_runtime_error_on_network_error(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_sdk,
):
    """Transport failures should surface as descriptive RuntimeError messages."""
    provider = GeminiProvider()

    class ConnectionError(Exception):
        pass

    class FakeModels:
        def generate_content(self, *, model, contents):
            raise ConnectionError("Connection timed out")

    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=FakeModels()))

    with pytest.raises(RuntimeError, match="Gemini transcription failed: request timed out"):
        provider.transcribe(sample_audio_bytes)


def test_transcribe_raises_runtime_error_on_api_error(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_sdk,
):
    """API failures should surface as descriptive RuntimeError messages."""
    provider = GeminiProvider()

    class FakeAPIError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.status_code = 429

    class FakeModels:
        def generate_content(self, *, model, contents):
            raise FakeAPIError("Quota exceeded")

    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=FakeModels()))

    with pytest.raises(RuntimeError, match="Gemini transcription failed: rate limited"):
        provider.transcribe(sample_audio_bytes)


def test_transcribe_raises_runtime_error_on_unclassified_error(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_sdk,
):
    """Unexpected SDK errors should keep the generic provider prefix."""
    provider = GeminiProvider()

    class FakeModels:
        def generate_content(self, *, model, contents):
            raise Exception("Something odd happened")

    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=FakeModels()))

    with pytest.raises(RuntimeError, match="Gemini transcription failed: unexpected error"):
        provider.transcribe(sample_audio_bytes)


def test_transcribe_raises_runtime_error_on_malformed_response(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_sdk,
):
    """Responses without transcription text should raise a descriptive error."""
    provider = GeminiProvider()

    class FakeModels:
        def generate_content(self, *, model, contents):
            return SimpleNamespace()

    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=FakeModels()))

    with pytest.raises(RuntimeError, match="unexpected response format"):
        provider.transcribe(sample_audio_bytes)


def test_transcribe_handles_empty_audio_gracefully():
    """Empty audio should short-circuit without calling the provider."""
    result = GeminiProvider().transcribe(b"")

    assert result.text == ""
    assert result.duration_seconds == 0
    assert result.cost_estimate == 0
    assert result.provider == "gemini"


def test_transcribe_streaming_emits_cumulative_chunks_and_returns_final_result(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_sdk,
):
    """Streaming transcription should accumulate chunk text and return final metadata."""
    provider = GeminiProvider(model="gemini-2.5-flash")
    seen_chunks = []

    class FakeModels:
        def generate_content_stream(self, *, model, contents):
            assert model == "gemini-2.5-flash"
            assert contents[1]["data"] == sample_audio_bytes
            return [
                SimpleNamespace(text=" Hello"),
                SimpleNamespace(text=" world "),
                SimpleNamespace(text=""),
            ]

    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=FakeModels()))

    result = provider.transcribe_streaming(sample_audio_bytes, seen_chunks.append)

    assert seen_chunks == ["Hello", "Hello world"]
    assert result.text == "Hello world"
    assert result.duration_seconds == pytest.approx(len(sample_audio_bytes) / 32000)
    assert result.cost_estimate == pytest.approx((result.duration_seconds / 60) * 0.001)
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"


def test_transcribe_streaming_handles_empty_audio_gracefully():
    """Streaming transcription should short-circuit empty audio the same way as batch."""
    seen_chunks = []

    result = GeminiProvider().transcribe_streaming(b"", seen_chunks.append)

    assert seen_chunks == []
    assert result.text == ""
    assert result.duration_seconds == 0
    assert result.cost_estimate == 0


def test_transcribe_streaming_raises_runtime_error_on_api_error(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_sdk,
):
    """Streaming transcription should sanitize backend failures the same way as batch."""
    provider = GeminiProvider()

    class FakeAPIError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.status_code = 429

    class FakeModels:
        def generate_content_stream(self, *, model, contents):
            raise FakeAPIError("Quota exceeded")

    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=FakeModels()))

    with pytest.raises(RuntimeError, match="Gemini transcription failed: rate limited"):
        provider.transcribe_streaming(sample_audio_bytes, lambda _chunk: None)
