"""
Translation orchestrator.

Manages translation providers and handles translation requests.
Supports both local (Ollama) and cloud (Gemini, OpenAI) providers.
"""

from typing import Optional, Callable, Dict, Type
from .providers.translation.base import TranslationProvider, TranslationResult
from .providers.translation.ollama import OllamaTranslateProvider
from .providers.translation.apple_translate import AppleTranslateProvider
from .providers.translation.gemini_translate import GeminiTranslateProvider
from .providers.translation.openai_translate import OpenAITranslateProvider
from .providers.translation.anthropic_translate import AnthropicTranslateProvider
from .config import Config


class TranslationManager:
    """Manages translation providers and requests."""

    # Registry of available providers
    PROVIDER_CLASSES: Dict[str, Type[TranslationProvider]] = {
        "ollama": OllamaTranslateProvider,
        "apple": AppleTranslateProvider,
        "gemini": GeminiTranslateProvider,
        "openai": OpenAITranslateProvider,
        "anthropic": AnthropicTranslateProvider,
    }

    # Provider categories for UI organization
    PROVIDER_CATEGORIES = {
        "local": ["ollama", "apple"],
        "cloud": ["gemini", "openai", "anthropic"],
    }

    MODEL_CONFIG_FIELDS = {
        "ollama": "translation_model",
        "gemini": "gemini_translate_model",
        "openai": "openai_translate_model",
        "anthropic": "anthropic_translate_model",
    }

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.load()
        self._shared_config = config is not None
        self._providers: Dict[str, TranslationProvider] = {}
        self._normalize_configured_models()

    def _normalize_model_for_provider(self, provider_id: str, model_id: str) -> str:
        """Normalize model IDs using provider-specific compatibility rules."""
        provider_class = self.PROVIDER_CLASSES.get(provider_id)
        if provider_class is None:
            return model_id

        normalize = getattr(provider_class, "normalize_model_id", None)
        if callable(normalize):
            try:
                return str(normalize(model_id))
            except Exception:
                pass

        models = getattr(provider_class, "MODELS", {})
        if isinstance(models, dict) and model_id in models:
            return model_id
        if isinstance(models, dict) and models:
            default_model = getattr(provider_class, "DEFAULT_MODEL", None)
            if isinstance(default_model, str) and default_model in models:
                return default_model
            return next(iter(models.keys()))
        return model_id

    def _normalize_configured_models(self) -> None:
        """Normalize configured translation models and persist if adjusted."""
        changed = False
        for provider_id, field_name in self.MODEL_CONFIG_FIELDS.items():
            configured_model = getattr(self.config, field_name, "")
            normalized_model = self._normalize_model_for_provider(provider_id, configured_model)
            if configured_model != normalized_model:
                setattr(self.config, field_name, normalized_model)
                changed = True

        if changed:
            self.config.save()

    def get_provider(self, provider_id: str) -> Optional[TranslationProvider]:
        """Get or create a provider instance."""
        if provider_id not in self._providers:
            provider_class = self.PROVIDER_CLASSES.get(provider_id)
            if provider_class:
                model = self._get_provider_model(provider_id)
                self._providers[provider_id] = provider_class(model=model)

        return self._providers.get(provider_id)

    def reset_provider(self, provider_id: str) -> None:
        """Reset a provider instance so it will be re-created on next use."""
        self._providers.pop(provider_id, None)

    def _get_provider_model(self, provider_id: str) -> str:
        """Get the configured model for a provider."""
        if provider_id == "apple":
            return "system"

        field_name = self.MODEL_CONFIG_FIELDS.get(provider_id)
        if field_name is None:
            return ""

        configured_model = getattr(self.config, field_name, "")
        return self._normalize_model_for_provider(provider_id, configured_model)

    @property
    def provider(self) -> TranslationProvider:
        """Get the currently active translation provider."""
        provider_id = getattr(self.config, "translation_provider", "apple")
        provider = self.get_provider(provider_id)
        if provider is None:
            # Fallback to Apple (built-in, no setup required)
            provider = self.get_provider("apple")
        return provider

    def get_available_providers(
        self, check_availability: bool = True, availability_override: Optional[Dict[str, bool]] = None
    ) -> list[dict]:
        """
        Get list of available providers with their status.

        Returns:
            List of dicts with provider info, status, and category
        """
        providers = []

        for provider_id, provider_class in self.PROVIDER_CLASSES.items():
            provider = self.get_provider(provider_id)
            if check_availability:
                is_available = provider.is_available() if provider else False
            elif availability_override and provider_id in availability_override:
                is_available = availability_override[provider_id]
            else:
                is_available = None

            # Determine category
            category = "local" if provider_id in self.PROVIDER_CATEGORIES["local"] else "cloud"

            providers.append(
                {
                    "id": provider_id,
                    "name": provider_class.display_name,
                    "available": is_available,
                    "category": category,
                    "models": provider.get_models() if provider else [],
                    "requires_download": provider_id == "ollama",
                }
            )

        return providers

    def translate(
        self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None
    ) -> TranslationResult:
        """
        Translate text using the configured provider.

        Args:
            text: Text to translate
            source_lang: Source language code (defaults to config value)
            target_lang: Target language code (defaults to config value)

        Returns:
            TranslationResult with translated text

        Raises:
            ConnectionError: If provider is not available
            ValueError: If provider is not configured
        """
        source = source_lang or self.config.source_language
        target = target_lang or self.config.target_language

        provider = self.provider
        if not provider.is_available():
            raise ConnectionError(
                f"Translation provider '{provider.name}' is not available. "
                "Please check configuration or select another provider."
            )

        return provider.translate(text, source, target)

    def is_available(self) -> bool:
        """Check if translation is available with current provider."""
        return self.provider.is_available()

    def get_status(self) -> dict:
        """
        Get translation system status.

        Returns:
            Dict with status information
        """
        provider_id = getattr(self.config, "translation_provider", "apple")
        provider = self.provider
        status = provider.get_model_status()

        status["enabled"] = self.config.translation_enabled
        status["target_language"] = self.config.target_language
        status["source_language"] = self.config.source_language
        status["provider"] = provider_id
        status["provider_name"] = provider.display_name

        # For Ollama, include additional status info
        if provider_id == "ollama" and hasattr(provider, "get_model_status"):
            ollama_status = provider.get_model_status()
            status["ollama_installed"] = ollama_status.get("ollama_installed", False)
            status["ollama_running"] = ollama_status.get("ollama_running", False)
            status["downloaded"] = ollama_status.get("downloaded", False)
        else:
            # Cloud providers are always "installed" and "running"
            status["ollama_installed"] = True
            status["ollama_running"] = True
            status["downloaded"] = True

        return status

    def get_supported_languages(self) -> dict[str, str]:
        """Get dict of supported language codes to names."""
        return self.provider.get_supported_languages()

    def set_provider(self, provider_id: str) -> None:
        """Change the active translation provider."""
        if provider_id in self.PROVIDER_CLASSES:
            self.config.translation_provider = provider_id
            self.config.save()

    def get_current_provider(self) -> str:
        """Get the current provider ID."""
        return getattr(self.config, "translation_provider", "apple")

    def set_model(self, model_id: str) -> None:
        """Change the translation model for the current provider."""
        provider_id = self.get_current_provider()
        self.provider.set_model(model_id)
        normalized_model = self.provider.get_current_model()

        # Save to config
        if provider_id == "ollama":
            self.config.translation_model = normalized_model
        elif provider_id == "gemini":
            self.config.gemini_translate_model = normalized_model
        elif provider_id == "openai":
            self.config.openai_translate_model = normalized_model
        elif provider_id == "anthropic":
            self.config.anthropic_translate_model = normalized_model

        self.config.save()

    def get_models(self) -> list[dict]:
        """Get available translation models for current provider."""
        return self.provider.get_models()

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.provider.get_current_model()

    def download_model(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Download the current model (for providers that need it).

        Args:
            progress_callback: Called with progress updates

        Returns:
            True if download succeeded
        """
        return self.provider.download_model(progress_callback)

    def check_disk_space(self) -> tuple[bool, float, float]:
        """
        Check if there's enough disk space for current model.

        Returns:
            Tuple of (has_space, available_gb, required_gb)
        """
        provider_id = self.get_current_provider()

        if provider_id == "ollama":
            provider = self.get_provider("ollama")
            if hasattr(provider, "model_config"):
                required_gb = provider.model_config["size_gb"]
                has_space, available_gb = OllamaTranslateProvider.check_disk_space(required_gb)
                return has_space, available_gb, required_gb

        # Cloud providers don't need disk space
        return True, 100.0, 0.0

    def reload_config(self) -> None:
        """Reload configuration from disk."""
        new_config = Config.load()
        if self._shared_config:
            self.config.update_from(new_config)
        else:
            self.config = new_config
        self._normalize_configured_models()
        # Update provider models
        for provider_id, provider in self._providers.items():
            model = self._get_provider_model(provider_id)
            provider.set_model(model)

    @staticmethod
    def is_ollama_installed() -> bool:
        """Check if Ollama is installed."""
        return OllamaTranslateProvider.is_ollama_installed()

    def supports_streaming(self) -> bool:
        """Check if current provider supports streaming."""
        return self.provider.supports_streaming()

    def translate_streaming(
        self,
        text: str,
        on_chunk: Callable[[str], None],
        source_lang: Optional[str] = None,
        target_lang: Optional[str] = None,
    ) -> TranslationResult:
        """
        Translate text with streaming output.

        Args:
            text: Text to translate
            on_chunk: Callback called with cumulative text as it streams
            source_lang: Source language code (defaults to config value)
            target_lang: Target language code (defaults to config value)

        Returns:
            TranslationResult with translated text
        """
        source = source_lang or self.config.source_language
        target = target_lang or self.config.target_language

        return self.provider.translate_streaming(text, source, target, on_chunk)

    @staticmethod
    def is_homebrew_installed() -> bool:
        """Check if Homebrew is installed."""
        return OllamaTranslateProvider.is_homebrew_installed()

    @staticmethod
    def install_ollama(progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Install Ollama via Homebrew."""
        return OllamaTranslateProvider.install_ollama(progress_callback)

    @staticmethod
    def start_ollama_server() -> tuple[bool, Optional[int]]:
        """Start the Ollama server in background."""
        return OllamaTranslateProvider.start_ollama_server()

    @staticmethod
    def stop_ollama_server() -> bool:
        """Stop the Ollama server."""
        return OllamaTranslateProvider.stop_ollama_server()
