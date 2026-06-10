"""
Translation orchestrator.

Manages translation providers and handles translation requests.
Supports both local (Ollama) and cloud (Gemini, OpenAI) providers.
"""

from typing import Optional, Callable, Dict, Type
from .providers.translation.base import TranslationProvider, TranslationResult
from .providers.translation.ollama import OllamaTranslateProvider

# Translation provider classes are imported into the module namespace so the
# registry-driven structures below can resolve them via ``globals()`` by their
# registry ``class_name``. They are also test monkeypatch targets, so they must
# remain importable module attributes even when not referenced by name.
from .providers.translation.apple_translate import AppleTranslateProvider  # noqa: F401
from .providers.translation.gemini_translate import GeminiTranslateProvider  # noqa: F401
from .providers.translation.openai_translate import OpenAITranslateProvider  # noqa: F401
from .providers.translation.anthropic_translate import AnthropicTranslateProvider  # noqa: F401
from .providers import registry
from .config import Config


def _resolve_translation_classes() -> Dict[str, Type[TranslationProvider]]:
    """Resolve translation provider classes from this module's namespace.

    Classes are looked up by their registry ``class_name`` against the module
    globals, so a spec whose class cannot be resolved is skipped gracefully and
    tests that monkeypatch the module-level imports keep working.
    """
    classes: Dict[str, Type[TranslationProvider]] = {}
    for spec in registry.TRANSLATION_SPECS:
        provider_class = globals().get(spec.class_name)
        if provider_class is not None:
            classes[spec.id] = provider_class
    return classes


def _build_translation_categories() -> Dict[str, list]:
    """Group registered translation provider ids by category."""
    categories: Dict[str, list] = {"local": [], "cloud": []}
    for spec in registry.TRANSLATION_SPECS:
        categories.setdefault(spec.category, []).append(spec.id)
    return categories


def _build_translation_model_fields() -> Dict[str, str]:
    """Map translation provider ids to their config model field.

    Providers without a persisted model field (e.g. Apple, which always uses the
    ``"system"`` model) are omitted, matching the historical field map.
    """
    return {
        spec.id: spec.config_model_field for spec in registry.TRANSLATION_SPECS if spec.config_model_field is not None
    }


class TranslationManager:
    """Manages translation providers and requests."""

    # Registry of available providers, derived from the central provider
    # registry. Specs whose class cannot be resolved are skipped.
    PROVIDER_CLASSES: Dict[str, Type[TranslationProvider]] = _resolve_translation_classes()

    # Provider categories for UI organization
    PROVIDER_CATEGORIES = _build_translation_categories()

    MODEL_CONFIG_FIELDS = _build_translation_model_fields()

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

    def _sync_provider_model_to_config(self, provider_id: str, provider: TranslationProvider) -> None:
        """Persist runtime model fallbacks so stale preview IDs do not get retried on the next launch."""
        field_name = self.MODEL_CONFIG_FIELDS.get(provider_id)
        if field_name is None:
            return

        try:
            current_model = provider.get_current_model()
        except Exception:
            return

        if not isinstance(current_model, str) or not current_model:
            return

        if getattr(self.config, field_name, "") != current_model:
            setattr(self.config, field_name, current_model)
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
        download_specs = {spec.id for spec in registry.TRANSLATION_SPECS if spec.requires_download}

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
                    "requires_download": provider_id in download_specs,
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

        provider_id = getattr(self.config, "translation_provider", "apple")
        provider = self.provider
        if not provider.is_available():
            raise ConnectionError(
                f"Translation provider '{provider.name}' is not available. "
                "Please check configuration or select another provider."
            )

        result = provider.translate(text, source, target)
        self._sync_provider_model_to_config(provider_id, provider)
        return result

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

        # Save to config. Providers without a model field (e.g. Apple, which
        # always uses the "system" model) are simply not persisted.
        field_name = self.MODEL_CONFIG_FIELDS.get(provider_id)
        if field_name is not None:
            setattr(self.config, field_name, normalized_model)

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

        provider_id = getattr(self.config, "translation_provider", "apple")
        provider = self.provider
        result = provider.translate_streaming(text, source, target, on_chunk)
        self._sync_provider_model_to_config(provider_id, provider)
        return result

    @staticmethod
    def is_homebrew_installed() -> bool:
        """Check if Homebrew is installed."""
        return OllamaTranslateProvider.is_homebrew_installed()

    @staticmethod
    def install_ollama(progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Install Ollama via Homebrew."""
        return OllamaTranslateProvider.install_ollama(progress_callback)

    def start_ollama_server(self) -> tuple[bool, Optional[int]]:
        """Start the Ollama server in background."""
        provider = self.get_provider("ollama")
        if provider is None:
            return False, None
        return provider.start_ollama_server()

    def stop_ollama_server(self) -> bool:
        """Stop the Ollama server."""
        provider = self.get_provider("ollama")
        if provider is None:
            return False
        return provider.stop_ollama_server()
