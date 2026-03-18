"""
Transcription orchestrator.

Manages providers and handles transcription requests.
Supports both cloud (OpenAI, Gemini) and local (Apple Speech, Whisper, Parakeet) providers.
"""

from copy import deepcopy
import platform
from typing import Callable, NotRequired, Optional, TypedDict, cast

from .providers.base import TranscriptionProvider, TranscriptionResult, LiveTranscriptionSession
from .providers.openai_whisper import OpenAITranscribeProvider
from .providers.openai_realtime import OpenAIRealtimeProvider
from .providers.gemini import GeminiProvider
from .providers.apple_speech import AppleSpeechProvider
from .providers.whisper_local import WhisperLocalProvider
from .providers.parakeet import ParakeetProvider
from .config import Config
from .keychain import get_configured_providers


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

    # Registry of available providers
    PROVIDER_CLASSES: dict[str, type[TranscriptionProvider]] = {
        "openai": OpenAITranscribeProvider,
        "openai_realtime": OpenAIRealtimeProvider,
        "gemini": GeminiProvider,
        "apple": AppleSpeechProvider,
        "whisper_local": WhisperLocalProvider,
        "parakeet": ParakeetProvider,
    }

    # Provider categories for UI organization
    PROVIDER_CATEGORIES = {
        "cloud": ["openai", "openai_realtime", "gemini"],
        "local": ["apple", "whisper_local", "parakeet"],
    }

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
        """Build provider metadata that is expensive to recompute on every menu open."""
        providers: list[ProviderInfo] = []

        openai_provider = OpenAITranscribeProvider()
        providers.append(
            {
                "id": "openai",
                "name": "OpenAI",
                "display_name": "OpenAI",
                "configured": False,
                "category": "cloud",
                "requires_download": False,
                "models": openai_provider.get_models(),
            }
        )

        openai_realtime_provider = OpenAIRealtimeProvider()
        providers.append(
            {
                "id": "openai_realtime",
                "name": "OpenAI Realtime",
                "display_name": "OpenAI Realtime",
                "configured": False,
                "category": "cloud",
                "requires_download": False,
                "models": openai_realtime_provider.get_models(),
            }
        )

        gemini_provider = GeminiProvider()
        providers.append(
            {
                "id": "gemini",
                "name": "Google Gemini",
                "display_name": "Google Gemini",
                "configured": False,
                "category": "cloud",
                "requires_download": False,
                "models": gemini_provider.get_models(),
            }
        )

        apple_provider = AppleSpeechProvider()
        providers.append(
            {
                "id": "apple",
                "name": "Apple (Built-in)",
                "display_name": "Apple (Built-in)",
                "configured": apple_provider.is_configured(),
                "category": "local",
                "requires_download": False,
                "models": apple_provider.get_models(),
                "availability_message": AppleSpeechProvider.get_availability_message(),
            }
        )

        whisper_provider = WhisperLocalProvider()
        providers.append(
            {
                "id": "whisper_local",
                "name": "Whisper Local",
                "display_name": "Whisper Local",
                "configured": whisper_provider.is_configured(),
                "category": "local",
                "requires_download": True,
                "models": whisper_provider.get_models(),
                "is_installed": WhisperLocalProvider.is_faster_whisper_installed(),
                "availability_message": WhisperLocalProvider.get_availability_message(),
            }
        )

        if platform.system() == "Darwin":
            parakeet_provider = ParakeetProvider()
            is_apple_silicon = ParakeetProvider.is_apple_silicon()
            providers.append(
                {
                    "id": "parakeet",
                    "name": "Parakeet" + (" (Apple Silicon)" if is_apple_silicon else " (requires Apple Silicon)"),
                    "display_name": "Parakeet",
                    "configured": parakeet_provider.is_configured() if is_apple_silicon else False,
                    "category": "local",
                    "requires_download": True,
                    "models": parakeet_provider.get_models() if is_apple_silicon else [],
                    "is_installed": ParakeetProvider.is_parakeet_installed() if is_apple_silicon else False,
                    "availability_message": ParakeetProvider.get_availability_message(),
                }
            )

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

    def transcribe(self, audio_bytes: bytes, provider_id: Optional[str] = None) -> TranscriptionResult:
        """
        Transcribe audio using specified or default provider.

        Args:
            audio_bytes: WAV audio data
            provider_id: Provider to use (or None for default)

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

        result = provider.transcribe(audio_bytes)

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
    ) -> LiveTranscriptionSession:
        """Create a live transcription session for the selected provider."""
        provider_id = provider_id or self.config.default_provider
        provider = self.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")
        if not provider.supports_live_input():
            raise ValueError(f"Provider '{provider_id}' does not support live input.")
        if not provider.is_configured():
            raise ValueError(f"Provider '{provider_id}' is not configured.")

        return provider.create_live_session(
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error,
            on_ready=on_ready,
            language=language,
            prompt=prompt,
        )

    def _find_fallback_provider(self, current_provider: str) -> Optional[TranscriptionProvider]:
        """Find a fallback provider if the current one isn't configured."""
        local_providers = {"apple", "whisper_local", "parakeet"}

        # If user selected a local provider, only fall back to other local providers
        # to respect their privacy choice — never silently route to a cloud vendor.
        if current_provider in local_providers:
            fallback_order = ["apple", "whisper_local", "parakeet"]
        else:
            # Cloud provider can fall back to any; prefer local first
            fallback_order = ["apple", "whisper_local", "parakeet", "gemini", "openai"]

        for pid in fallback_order:
            if pid == current_provider:
                continue
            provider = self.get_provider(pid)
            if provider and provider.is_configured():
                return provider

        return None

    def transcribe_streaming(
        self, audio_bytes: bytes, on_chunk: Callable[[str], None], provider_id: Optional[str] = None
    ) -> TranscriptionResult:
        """
        Transcribe audio with streaming output.

        Args:
            audio_bytes: WAV audio data
            on_chunk: Callback for streaming text updates
            provider_id: Provider to use (or None for default)

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
            result = provider.transcribe_streaming(audio_bytes, on_chunk)
        else:
            # Fallback to non-streaming
            result = provider.transcribe(audio_bytes)
            if result.text:
                on_chunk(result.text)

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

        info: DownloadInfo = {
            "provider_id": provider_id,
            "requires_download": provider_id in ["whisper_local", "parakeet"],
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
