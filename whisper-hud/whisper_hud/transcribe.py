"""
Transcription orchestrator.

Manages providers and handles transcription requests.
Supports both cloud (OpenAI, Gemini) and local (Apple Speech, Whisper, Parakeet) providers.
"""

from copy import deepcopy
import inspect
import platform
from typing import Any, Callable, NotRequired, Optional, Sequence, TypedDict, cast

from .providers.base import TranscriptionProvider, TranscriptionResult, LiveTranscriptionSession

# Provider classes are imported into the module namespace so the registry-driven
# builders can resolve them via ``globals()`` by their registry ``class_name``.
# They are also the monkeypatch targets used by the test suite, so they must
# remain importable module attributes even though they are not referenced by name.
from .providers.openai_whisper import OpenAITranscribeProvider  # noqa: F401
from .providers.openai_realtime import OpenAIRealtimeProvider  # noqa: F401
from .providers.gemini import GeminiProvider  # noqa: F401
from .providers.apple_speech import AppleSpeechProvider  # noqa: F401
from .providers.whisper_local import WhisperLocalProvider  # noqa: F401
from .providers.parakeet import ParakeetProvider  # noqa: F401
from .providers.qwen3_asr import Qwen3ASRProvider  # noqa: F401
from .providers.apple_speechanalyzer import AppleSpeechAnalyzerProvider  # noqa: F401
from .providers import registry
from .config import Config
from .keychain import get_configured_providers


def _resolve_transcription_classes() -> dict[str, type[TranscriptionProvider]]:
    """Resolve transcription provider classes from this module's namespace.

    Classes are looked up by their registry ``class_name`` against the module
    globals (rather than via ``registry.resolve_provider_class``) so that tests
    which monkeypatch the module-level imports keep working, and so a spec whose
    class cannot be resolved is skipped gracefully.
    """
    classes: dict[str, type[TranscriptionProvider]] = {}
    for spec in registry.TRANSCRIPTION_SPECS:
        provider_class = globals().get(spec.class_name)
        if provider_class is not None:
            classes[spec.id] = provider_class
    return classes


def _build_provider_categories() -> dict[str, list[str]]:
    """Group registered transcription provider ids by category."""
    categories: dict[str, list[str]] = {"cloud": [], "local": []}
    for spec in registry.TRANSCRIPTION_SPECS:
        categories.setdefault(spec.category, []).append(spec.id)
    return categories


def _build_generic_cache_entry(
    provider_class: type[TranscriptionProvider], spec: registry.ProviderSpec
) -> "ProviderInfo":
    """Build a cache entry for a standard provider from its spec and class.

    Cloud providers report ``configured: False`` here (their real status is
    filled in later from the credential store). Local providers report their own
    ``is_configured()``. ``availability_message`` and ``is_installed`` are
    attached only when the provider exposes the corresponding classmethods, so
    cloud providers (which do not) keep their original metadata shape.
    """
    provider = provider_class()
    info: ProviderInfo = {
        "id": spec.id,
        "name": spec.display_name,
        "display_name": spec.display_name,
        "configured": provider.is_configured() if spec.category == "local" else False,
        "category": spec.category,
        "requires_download": spec.requires_download,
        "models": provider.get_models(),
    }

    installed_check = getattr(provider_class, "is_faster_whisper_installed", None)
    if callable(installed_check):
        info["is_installed"] = installed_check()

    availability = getattr(provider_class, "get_availability_message", None)
    if callable(availability):
        info["availability_message"] = availability()

    return info


def _build_parakeet_cache_entry(
    provider_class: type[TranscriptionProvider], spec: registry.ProviderSpec
) -> "ProviderInfo":
    """Build Parakeet's cache entry, gated on Apple Silicon availability."""
    parakeet_class = cast(type[ParakeetProvider], provider_class)
    provider = parakeet_class()
    is_apple_silicon = parakeet_class.is_apple_silicon()
    return {
        "id": spec.id,
        "name": spec.display_name + (" (Apple Silicon)" if is_apple_silicon else " (requires Apple Silicon)"),
        "display_name": spec.display_name,
        "configured": provider.is_configured() if is_apple_silicon else False,
        "category": spec.category,
        "requires_download": spec.requires_download,
        "models": provider.get_models() if is_apple_silicon else [],
        "is_installed": parakeet_class.is_parakeet_installed() if is_apple_silicon else False,
        "availability_message": parakeet_class.get_availability_message(),
    }


# Per-provider cache-entry hooks for providers whose availability metadata is
# too bespoke for the generic builder. Anything not listed uses the generic path.
_CACHE_ENTRY_HOOKS = {
    "parakeet": _build_parakeet_cache_entry,
}


class ProviderInfo(TypedDict):
    id: str
    name: str
    display_name: str
    configured: bool
    category: str
    requires_download: bool
    models: list[dict]
    availability_message: NotRequired[str]
    is_installed: NotRequired[bool]


class DownloadInfo(TypedDict, total=False):
    error: str
    provider_id: str
    requires_download: bool
    downloaded: bool
    size_mb: float | int
    has_disk_space: bool
    available_mb: float | int


class TranscriptionManager:
    """Manages transcription providers and requests."""

    # Registry of available providers, derived from the central provider
    # registry. Specs whose class cannot be resolved are skipped, so a future
    # spec pointing at a not-yet-implemented module simply hides that provider.
    PROVIDER_CLASSES: dict[str, type[TranscriptionProvider]] = _resolve_transcription_classes()

    # Provider categories for UI organization
    PROVIDER_CATEGORIES = _build_provider_categories()

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config.load()
        self._shared_config = config is not None
        self._providers: dict[str, TranscriptionProvider] = {}
        self._available_providers_cache: Optional[list[ProviderInfo]] = None

    def get_available_providers(self, configured_providers: Optional[list[str]] = None) -> list[ProviderInfo]:
        """
        Get list of available providers with their configured status.

        Returns:
            List of dicts with provider info, status, and category
        """
        configured = configured_providers if configured_providers is not None else get_configured_providers()
        providers = deepcopy(self._get_cached_available_providers())

        for provider in providers:
            if provider["id"] == "openai_realtime":
                provider["configured"] = "openai" in configured
            elif provider["category"] == "cloud":
                provider["configured"] = provider["id"] in configured

        return providers

    def _get_cached_available_providers(self) -> list[ProviderInfo]:
        """Compute provider metadata once and reuse it until config changes."""
        if self._available_providers_cache is None:
            self._available_providers_cache = self._build_available_providers_cache()
        return self._available_providers_cache

    def _build_available_providers_cache(self) -> list[ProviderInfo]:
        """Build provider metadata that is expensive to recompute on every menu open.

        Driven by the central registry: one entry is produced per spec whose
        provider class resolves from this module's namespace. Most metadata is
        derived generically from the spec and the provider's optional classmethods
        (``is_configured``/``get_availability_message``/``is_faster_whisper_installed``);
        Parakeet keeps a bespoke hook for its Apple-Silicon gating.
        """
        providers: list[ProviderInfo] = []

        for spec in registry.TRANSCRIPTION_SPECS:
            if spec.platform_gate == "darwin" and platform.system() != "Darwin":
                continue

            # Resolve from the module namespace (not PROVIDER_CLASSES) so tests
            # that monkeypatch the module-level provider imports are honored.
            provider_class = globals().get(spec.class_name)
            if provider_class is None:
                continue

            hook = _CACHE_ENTRY_HOOKS.get(spec.id, _build_generic_cache_entry)
            providers.append(hook(provider_class, spec))

        return providers

    def _invalidate_available_providers_cache(self) -> None:
        """Clear cached provider metadata after config changes."""
        self._available_providers_cache = None

    def get_provider(self, provider_id: str) -> Optional[TranscriptionProvider]:
        """Get or create a provider instance."""
        if provider_id not in self._providers:
            provider_class = self.PROVIDER_CLASSES.get(provider_id)
            if provider_class:
                model = self.config.get_provider_model(provider_id)
                provider_factory = cast(Callable[..., TranscriptionProvider], provider_class)
                self._providers[provider_id] = provider_factory(model=model)

        return self._providers.get(provider_id)

    def reset_provider(self, provider_id: str) -> None:
        """Reset a provider instance so it will be re-created on next use."""
        self._providers.pop(provider_id, None)

    def set_provider_model(self, provider_id: str, model_id: str) -> None:
        """Update the model for a provider."""
        provider = self.get_provider(provider_id)
        if provider:
            provider.set_model(model_id)
            self.config.set_provider_model(provider_id, model_id)
            self._invalidate_available_providers_cache()

    def _sync_provider_model_to_config(self, provider_id: str, provider: TranscriptionProvider) -> None:
        """Persist runtime model fallbacks so rejected preview IDs are not retried forever."""
        try:
            current_model = provider.get_current_model()
        except Exception:
            return

        if not isinstance(current_model, str) or not current_model:
            return

        if self.config.get_provider_model(provider_id) != current_model:
            self.config.set_provider_model(provider_id, current_model)
            self._invalidate_available_providers_cache()

    def transcribe(
        self,
        audio_bytes: bytes,
        provider_id: Optional[str] = None,
        vocabulary: Optional[Sequence[str]] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio using specified or default provider.

        Args:
            audio_bytes: WAV audio data
            provider_id: Provider to use (or None for default)
            vocabulary: Optional words/phrases to bias recognition toward; passed
                through to the provider, which applies it via its native biasing
                mechanism (providers without support ignore it).

        Returns:
            TranscriptionResult with text and metadata

        Raises:
            ValueError: If provider is not configured
        """
        provider_id = provider_id or self.config.default_provider
        provider = self.get_provider(provider_id)

        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")

        if not provider.is_configured():
            # Try fallback to available providers
            fallback_provider = self._find_fallback_provider(provider_id)
            if fallback_provider:
                provider = fallback_provider
                provider_id = provider.name
            else:
                raise ValueError(
                    f"Provider '{provider_id}' is not configured. " f"Please configure it in the settings menu."
                )

        result = provider.transcribe(audio_bytes, vocabulary=vocabulary)
        self._sync_provider_model_to_config(provider_id, provider)

        # Update stats
        self.config.add_transcription_stats(result.cost_estimate)

        return result

    def supports_live_input(self, provider_id: Optional[str] = None) -> bool:
        """Check whether a provider supports live microphone input."""
        provider_id = provider_id or self.config.default_provider
        provider = self.get_provider(provider_id)
        return bool(provider and provider.supports_live_input())

    def create_live_session(
        self,
        *,
        on_partial: Callable[[str], None],
        on_final: Callable[[TranscriptionResult], None],
        on_error: Callable[[Exception], None],
        on_ready: Optional[Callable[[], None]] = None,
        provider_id: Optional[str] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        vocabulary: Optional[Sequence[str]] = None,
    ) -> LiveTranscriptionSession:
        """Create a live transcription session for the selected provider.

        ``vocabulary`` is forwarded to the provider's native biasing mechanism
        (e.g. folded into the Realtime session prompt); providers without support
        ignore it.
        """
        provider_id = provider_id or self.config.default_provider
        provider = self.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")
        if not provider.supports_live_input():
            raise ValueError(f"Provider '{provider_id}' does not support live input.")
        if not provider.is_configured():
            raise ValueError(f"Provider '{provider_id}' is not configured.")

        kwargs: dict[str, Any] = dict(
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error,
            on_ready=on_ready,
            language=language,
            prompt=prompt,
        )
        # Forward vocabulary only to providers whose live-session factory accepts
        # it, so providers that predate the kwarg (e.g. local streaming ones) are
        # not broken by an unexpected argument.
        if "vocabulary" in inspect.signature(provider.create_live_session).parameters:
            kwargs["vocabulary"] = vocabulary

        return provider.create_live_session(**kwargs)

    def _find_fallback_provider(self, current_provider: str) -> Optional[TranscriptionProvider]:
        """Find a fallback provider if the current one isn't configured."""
        local_providers = set(self.PROVIDER_CATEGORIES.get("local", []))

        # Respect provider boundaries for privacy. If a user selected a cloud
        # provider, do not silently route microphone audio to a different vendor.
        if current_provider not in local_providers:
            return None

        # Local providers may still fall back to other local options, in the
        # priority order declared by the registry.
        fallback_order = [
            spec.id
            for spec in sorted(
                (s for s in registry.TRANSCRIPTION_SPECS if s.fallback_priority is not None),
                # The generator above filters out None priorities; `or 0` keeps
                # the lambda total for the type checker without changing order.
                key=lambda s: s.fallback_priority or 0,
            )
        ]

        for pid in fallback_order:
            if pid == current_provider:
                continue
            provider = self.get_provider(pid)
            if provider and provider.is_configured():
                return provider

        return None

    def transcribe_streaming(
        self,
        audio_bytes: bytes,
        on_chunk: Callable[[str], None],
        provider_id: Optional[str] = None,
        vocabulary: Optional[Sequence[str]] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio with streaming output.

        Args:
            audio_bytes: WAV audio data
            on_chunk: Callback for streaming text updates
            provider_id: Provider to use (or None for default)
            vocabulary: Optional words/phrases to bias recognition toward; passed
                through to the provider's native biasing mechanism.

        Returns:
            TranscriptionResult with text and metadata
        """
        provider_id = provider_id or self.config.default_provider
        provider = self.get_provider(provider_id)

        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")

        if not provider.is_configured():
            fallback_provider = self._find_fallback_provider(provider_id)
            if fallback_provider:
                provider = fallback_provider
            else:
                raise ValueError(f"Provider '{provider_id}' is not configured.")

        if provider.supports_streaming():
            result = provider.transcribe_streaming(audio_bytes, on_chunk, vocabulary=vocabulary)
        else:
            # Fallback to non-streaming
            result = provider.transcribe(audio_bytes, vocabulary=vocabulary)
            if result.text:
                on_chunk(result.text)

        self._sync_provider_model_to_config(provider_id, provider)

        # Update stats
        self.config.add_transcription_stats(result.cost_estimate)

        return result

    def download_model(
        self, provider_id: str, progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> bool:
        """
        Download model for a provider that requires it.

        Args:
            provider_id: Provider ID
            progress_callback: Called with (message, progress_percent)

        Returns:
            True if download succeeded
        """
        provider = self.get_provider(provider_id)
        if not provider:
            if progress_callback:
                progress_callback(f"Unknown provider: {provider_id}", 0.0)
            return False

        if hasattr(provider, "download_model"):
            success = provider.download_model(progress_callback)
            if success:
                self._invalidate_available_providers_cache()
            return success

        if progress_callback:
            progress_callback("This provider doesn't require download", 100.0)
        return True

    def get_download_info(self, provider_id: str) -> DownloadInfo:
        """
        Get download information for a provider.

        Args:
            provider_id: Provider ID

        Returns:
            Dict with download size, status, etc.
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return {"error": f"Unknown provider: {provider_id}"}

        download_specs = {spec.id for spec in registry.TRANSCRIPTION_SPECS if spec.requires_download}
        info: DownloadInfo = {
            "provider_id": provider_id,
            "requires_download": provider_id in download_specs,
        }

        if hasattr(provider, "is_model_downloaded"):
            info["downloaded"] = provider.is_model_downloaded()
        else:
            info["downloaded"] = True

        if hasattr(provider, "get_download_size"):
            info["size_mb"] = provider.get_download_size()
        else:
            info["size_mb"] = 0

        if hasattr(provider, "check_disk_space"):
            size_mb = info.get("size_mb", 0)
            has_space, available = provider.check_disk_space(size_mb)
            info["has_disk_space"] = has_space
            info["available_mb"] = available
        else:
            info["has_disk_space"] = True
            info["available_mb"] = float("inf")

        return info

    def get_stats(self) -> dict[str, int | float]:
        """Get transcription statistics."""
        return {"total_transcriptions": self.config.total_transcriptions, "total_cost": self.config.total_cost}

    def reload_config(self) -> None:
        """Reload configuration from disk."""
        new_config = Config.load()
        if self._shared_config:
            self.config.update_from(new_config)
        else:
            self.config = new_config
        self._invalidate_available_providers_cache()
        # Update provider models
        for provider_id, provider in self._providers.items():
            model = self.config.get_provider_model(provider_id)
            provider.set_model(model)

    def is_local_provider(self, provider_id: str) -> bool:
        """Check if a provider is a local (non-cloud) provider."""
        return provider_id in self.PROVIDER_CATEGORIES.get("local", [])

    def is_cloud_provider(self, provider_id: str) -> bool:
        """Check if a provider is a cloud provider."""
        return provider_id in self.PROVIDER_CATEGORIES.get("cloud", [])
