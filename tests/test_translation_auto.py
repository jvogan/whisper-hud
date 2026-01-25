"""Tests for translation auto-detect behavior."""

import pytest

from whisper_hud.translate import TranslationManager
from whisper_hud.providers.translation.base import TranslationProvider, TranslationResult
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
            text="ok",
            source_lang=source_lang,
            target_lang=target_lang,
            provider=self.name,
            model=self.model
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


@pytest.mark.parametrize(
    "provider_cls",
    [OpenAITranslateProvider, GeminiTranslateProvider, OllamaTranslateProvider]
)
def test_provider_prompt_auto_detect(provider_cls):
    """Providers should explicitly request source language detection for 'auto'."""
    provider = provider_cls()
    text = "Hello world"

    if hasattr(provider, "_build_messages"):
        messages = provider._build_messages(text, "auto", "es")
        system_prompt = messages[0]["content"]
        assert "Detect the source language" in system_prompt
        assert "Spanish" in system_prompt
    else:
        prompt = provider._build_prompt(text, "auto", "es")
        assert "Detect the source language" in prompt
        assert "Spanish" in prompt


@pytest.mark.parametrize(
    "provider_cls",
    [OpenAITranslateProvider, GeminiTranslateProvider, OllamaTranslateProvider]
)
def test_provider_prompt_explicit_source(provider_cls):
    """Providers should include explicit source language when provided."""
    provider = provider_cls()
    text = "Hello world"

    if hasattr(provider, "_build_messages"):
        messages = provider._build_messages(text, "en", "es")
        system_prompt = messages[0]["content"]
        assert "Translate text from English to Spanish" in system_prompt
    else:
        prompt = provider._build_prompt(text, "en", "es")
        assert "from English to Spanish" in prompt
