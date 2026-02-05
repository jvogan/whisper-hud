# Translation providers
from .base import TranslationProvider, TranslationResult
from .ollama import OllamaTranslateProvider
from .apple_translate import AppleTranslateProvider
from .gemini_translate import GeminiTranslateProvider
from .openai_translate import OpenAITranslateProvider
from .anthropic_translate import AnthropicTranslateProvider

__all__ = [
    "TranslationProvider",
    "TranslationResult",
    "OllamaTranslateProvider",
    "AppleTranslateProvider",
    "GeminiTranslateProvider",
    "OpenAITranslateProvider",
    "AnthropicTranslateProvider",
]
