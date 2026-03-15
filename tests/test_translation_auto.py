"""Tests for translation auto-detect behavior."""

from types import SimpleNamespace

import pytest

from whisper_hud.translate import TranslationManager
from whisper_hud.providers.translation.base import TranslationProvider, TranslationResult
from whisper_hud.providers.translation.anthropic_translate import AnthropicTranslateProvider
from whisper_hud.providers.translation.openai_translate import OpenAITranslateProvider
from whisper_hud.providers.translation.gemini_translate import GeminiTranslateProvider
from whisper_hud.providers.translation.ollama import OllamaTranslateProvider


class DummyProvider(TranslationProvider):
    """Minimal provider to capture translate args."""

    name = "dummy"
    display_name = "Dummy"

    def __init__(self, model: str = ""):
        self.model = model
        self.args = None

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        self.args = (source_lang, target_lang)
        return TranslationResult(
            text="ok", source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
        )

    def is_available(self) -> bool:
        return True

    def get_model_status(self) -> dict:
        return {}

    def download_model(self, progress_callback=None) -> bool:
        return True


def test_translate_manager_passes_auto_source(mock_config, monkeypatch):
    """Ensure TranslationManager doesn't coerce 'auto' to English."""
    monkeypatch.setattr(TranslationManager, "PROVIDER_CLASSES", {"dummy": DummyProvider})
    mock_config.translation_provider = "dummy"

    manager = TranslationManager(mock_config)
    manager.translate("hello", source_lang="auto", target_lang="es")

    provider = manager.get_provider("dummy")
    assert provider.args[0] == "auto"
    assert provider.args[1] == "es"


@pytest.mark.parametrize("provider_cls", [OpenAITranslateProvider, GeminiTranslateProvider, OllamaTranslateProvider])
def test_provider_prompt_auto_detect(provider_cls):
    """Providers should explicitly request source language detection for 'auto'."""
    provider = provider_cls()
    text = "Hello world"

    if hasattr(provider, "_build_messages"):
        system_prompt, _ = provider._build_messages(text, "auto", "es")
        assert isinstance(system_prompt, str)
        assert "Detect the source language" in system_prompt
        assert "Spanish" in system_prompt
    elif hasattr(provider, "_build_instructions"):
        instructions = provider._build_instructions("auto", "es")
        assert "Detect the source language" in instructions
        assert "Spanish" in instructions
    else:
        prompt = provider._build_prompt(text, "auto", "es")
        assert "Detect the source language" in prompt
        assert "Spanish" in prompt


@pytest.mark.parametrize("provider_cls", [OpenAITranslateProvider, GeminiTranslateProvider, OllamaTranslateProvider])
def test_provider_prompt_explicit_source(provider_cls):
    """Providers should include explicit source language when provided."""
    provider = provider_cls()
    text = "Hello world"

    if hasattr(provider, "_build_messages"):
        system_prompt, _ = provider._build_messages(text, "en", "es")
        assert "Translate text from English to Spanish" in system_prompt
    elif hasattr(provider, "_build_instructions"):
        instructions = provider._build_instructions("en", "es")
        assert "Translate text from English to Spanish" in instructions
    else:
        prompt = provider._build_prompt(text, "en", "es")
        assert "from English to Spanish" in prompt


def test_openai_responses_request_builder():
    """OpenAI provider should build Responses-compatible request params."""
    provider = OpenAITranslateProvider(model="gpt-5.2")
    kwargs = provider._build_request_kwargs("Hello", "auto", "es", stream=True)

    assert kwargs["model"] == "gpt-5.2"
    assert kwargs["input"] == "Hello"
    assert kwargs["stream"] is True
    assert kwargs["max_output_tokens"] == 4096
    assert "Detect the source language" in kwargs["instructions"]
    assert kwargs["temperature"] == 0.1
    assert kwargs["reasoning"] == {"effort": "none"}


def test_openai_streaming_delta_parser():
    """OpenAI streaming parser should extract text deltas and final output text."""
    provider = OpenAITranslateProvider()

    assert provider._extract_delta_text({"type": "response.output_text.delta", "delta": "Hola"}) == "Hola"
    assert provider._extract_delta_text({"type": "response.completed"}) == ""

    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hola mundo"}],
            }
        ]
    }
    assert provider._extract_text_from_response(response) == "Hola mundo"


def test_anthropic_model_normalization_handles_stale_ids():
    """Anthropic provider should map historical model IDs to current aliases."""
    assert AnthropicTranslateProvider.normalize_model_id("claude-opus-4-5") == "claude-opus-4-6"
    assert AnthropicTranslateProvider.normalize_model_id("claude-opus-4-1") == "claude-opus-4-6"
    assert AnthropicTranslateProvider.normalize_model_id("unknown-id") == AnthropicTranslateProvider.DEFAULT_MODEL


def test_anthropic_translate_returns_result_on_success(monkeypatch):
    """Anthropic translate should return TranslationResult on the success path."""
    provider = AnthropicTranslateProvider(model="claude-sonnet-4-5")

    monkeypatch.setattr(provider, "_build_messages", lambda text, source, target: ("system", text))
    monkeypatch.setattr(provider, "_translate_once", lambda model, system, user: "Hola mundo")

    result = provider.translate("Hello world", "en", "es")

    assert result.text == "Hola mundo"
    assert result.provider == "anthropic"
    assert result.model == "claude-sonnet-4-5"


def test_anthropic_streaming_returns_result_on_success(monkeypatch):
    """Anthropic streaming translate should return TranslationResult on success."""
    provider = AnthropicTranslateProvider(model="claude-sonnet-4-5")

    monkeypatch.setattr(provider, "_build_messages", lambda text, source, target: ("system", text))

    def fake_stream(model, system, user, on_chunk):
        on_chunk("Ho")
        on_chunk("Hola")
        return "Hola mundo"

    monkeypatch.setattr(provider, "_translate_stream_once", fake_stream)

    chunks = []
    result = provider.translate_streaming("Hello world", "en", "es", chunks.append)

    assert result.text == "Hola mundo"
    assert result.provider == "anthropic"
    assert result.model == "claude-sonnet-4-5"
    assert chunks == ["Ho", "Hola"]


def test_gemini_model_not_found_falls_back_to_stable(monkeypatch):
    """Gemini provider should fall back to stable model when preview ID is rejected."""

    class FakeGeminiModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, *, model, contents, config):
            self.calls.append(model)
            if model == "gemini-3-flash-preview":
                raise RuntimeError("Model not found: gemini-3-flash-preview")
            return SimpleNamespace(text="Hola mundo")

    class FakeGeminiClient:
        def __init__(self):
            self.models = FakeGeminiModels()

    provider = GeminiTranslateProvider(model="gemini-3-flash-preview")
    fake_client = FakeGeminiClient()
    monkeypatch.setattr(provider, "_get_client", lambda: fake_client)

    result = provider.translate("Hello world", "en", "es")

    assert fake_client.models.calls == ["gemini-3-flash-preview", "gemini-2.5-flash"]
    assert result.text == "Hola mundo"
    assert result.model == "gemini-2.5-flash"
    assert provider.get_current_model() == "gemini-2.5-flash"


def test_translation_manager_normalizes_provider_models(mock_config):
    """TranslationManager should normalize invalid/stale configured model IDs."""
    mock_config.openai_translate_model = "invalid-openai-model"
    mock_config.gemini_translate_model = "invalid-gemini-model"
    mock_config.anthropic_translate_model = "claude-opus-4-5"

    TranslationManager(mock_config)

    assert mock_config.openai_translate_model == OpenAITranslateProvider.DEFAULT_MODEL
    assert mock_config.gemini_translate_model == GeminiTranslateProvider.DEFAULT_MODEL
    assert mock_config.anthropic_translate_model == "claude-opus-4-6"
