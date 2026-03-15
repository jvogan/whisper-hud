"""Tests for GeminiProvider transcription behavior."""

from types import ModuleType, SimpleNamespace

import pytest

from whisper_hud.providers.gemini import GeminiProvider


@pytest.fixture
def fake_gemini_types(monkeypatch):
    """Provide a minimal google.genai.types module for provider imports."""

    class FakePart:
        @staticmethod
        def from_bytes(*, data, mime_type):
            return {"data": data, "mime_type": mime_type}

    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    types_module = ModuleType("google.genai.types")
    types_module.Part = FakePart
    genai_module.types = types_module
    google_module.genai = genai_module

    monkeypatch.setitem(__import__("sys").modules, "google", google_module)
    monkeypatch.setitem(__import__("sys").modules, "google.genai", genai_module)
    monkeypatch.setitem(__import__("sys").modules, "google.genai.types", types_module)


def test_gemini_transcribe_returns_result_on_success(monkeypatch, sample_audio_bytes, fake_gemini_types):
    """Gemini provider should preserve the success path behavior."""
    provider = GeminiProvider(model="gemini-3-flash-preview")

    class FakeModels:
        def generate_content(self, *, model, contents):
            assert model == "gemini-3-flash-preview"
            assert contents[0].startswith("Transcribe this audio exactly as spoken.")
            assert contents[1]["data"] == sample_audio_bytes
            assert contents[1]["mime_type"] == "audio/wav"
            return SimpleNamespace(text="  Hello from Gemini  ")

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_get_client", lambda: fake_client)

    result = provider.transcribe(sample_audio_bytes)

    assert result.text == "Hello from Gemini"
    assert result.provider == "gemini"
    assert result.model == "gemini-3-flash-preview"
    assert result.duration_seconds == pytest.approx(len(sample_audio_bytes) / 32000)
    assert result.cost_estimate == pytest.approx((result.duration_seconds / 60) * 0.001)
    assert result.language is None


def test_gemini_transcribe_raises_runtime_error_on_network_error(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_types,
):
    """Transport failures should surface as user-readable RuntimeError messages."""
    provider = GeminiProvider()

    class ConnectionError(Exception):
        pass

    class FakeModels:
        def generate_content(self, *, model, contents):
            raise ConnectionError("Connection timed out")

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="network error: Connection timed out"):
        provider.transcribe(sample_audio_bytes)


def test_gemini_transcribe_raises_runtime_error_on_api_error(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_types,
):
    """Gemini API failures should surface as user-readable RuntimeError messages."""
    provider = GeminiProvider()

    class FakeAPIError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.status_code = 429

    class FakeModels:
        def generate_content(self, *, model, contents):
            raise FakeAPIError("Quota exceeded")

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="API error: Quota exceeded"):
        provider.transcribe(sample_audio_bytes)


def test_gemini_transcribe_raises_runtime_error_on_malformed_response(
    monkeypatch,
    sample_audio_bytes,
    fake_gemini_types,
):
    """Responses without text should raise a descriptive RuntimeError."""
    provider = GeminiProvider()

    class FakeModels:
        def generate_content(self, *, model, contents):
            return SimpleNamespace()

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="unexpected response format"):
        provider.transcribe(sample_audio_bytes)
