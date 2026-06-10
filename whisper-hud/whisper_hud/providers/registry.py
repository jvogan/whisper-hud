"""
Central provider registry.

This is a LEAF module: it imports only from the standard library and never
imports concrete provider modules (or any other ``whisper_hud`` module) at
import time. Provider classes are resolved lazily via :func:`resolve_provider_class`
so that this module is safe to import from anywhere — including ``keychain.py``,
which providers themselves depend on — without creating import cycles.

Adding a new provider should require a single :class:`ProviderSpec` entry here
plus the provider implementation (and, for cloud providers, one credential
validator/display-name entry in ``keychain.py``). The transcription and
translation managers, the credential keychain, the config model maps, and the
app-level provider-set helpers all derive their behavior from these specs.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Optional

from ..logging_config import get_logger

logger = get_logger("providers.registry")


@dataclass(frozen=True)
class ProviderSpec:
    """Declarative description of a transcription or translation provider.

    Attributes:
        id: Stable provider identifier used as the key in manager registries,
            config, and the UI (e.g. ``"openai"``, ``"openai_realtime"``).
        display_name: Human-readable provider name shown in menus.
        kind: ``"transcription"`` or ``"translation"``.
        category: ``"local"`` or ``"cloud"``.
        module: Dotted import path to the module defining the provider class
            (e.g. ``"whisper_hud.providers.parakeet"``).
        class_name: Name of the provider class within ``module``.
        credential_vendor: The API-key vendor this provider authenticates with
            (``"openai"``, ``"gemini"``, ``"anthropic"``), or ``None`` for
            providers that need no API key. ``openai_realtime`` uses ``"openai"``.
        config_model_field: Name of the :class:`whisper_hud.config.Config` field
            that stores this provider's selected model, or ``None`` if the
            provider has no persisted model field (e.g. Apple translation, which
            always uses the ``"system"`` model).
        requires_download: Whether the provider downloads a model before use.
        fallback_priority: Order among local transcription fallback candidates
            (lower runs first). ``None`` means the provider is never used as an
            automatic fallback target.
        platform_gate: Optional platform restriction. ``"darwin"`` means the
            provider is only surfaced in availability listings on macOS.
    """

    id: str
    display_name: str
    kind: str
    category: str
    module: str
    class_name: str
    credential_vendor: Optional[str]
    config_model_field: Optional[str]
    requires_download: bool
    fallback_priority: Optional[int]
    platform_gate: Optional[str] = None


# Transcription providers, in the exact order TranscriptionManager exposes them.
TRANSCRIPTION_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="openai",
        display_name="OpenAI",
        kind="transcription",
        category="cloud",
        module="whisper_hud.providers.openai_whisper",
        class_name="OpenAITranscribeProvider",
        credential_vendor="openai",
        config_model_field="openai_model",
        requires_download=False,
        fallback_priority=None,
    ),
    ProviderSpec(
        id="openai_realtime",
        display_name="OpenAI Realtime",
        kind="transcription",
        category="cloud",
        module="whisper_hud.providers.openai_realtime",
        class_name="OpenAIRealtimeProvider",
        credential_vendor="openai",
        config_model_field="openai_realtime_model",
        requires_download=False,
        fallback_priority=None,
    ),
    ProviderSpec(
        id="gemini",
        display_name="Google Gemini",
        kind="transcription",
        category="cloud",
        module="whisper_hud.providers.gemini",
        class_name="GeminiProvider",
        credential_vendor="gemini",
        config_model_field="gemini_model",
        requires_download=False,
        fallback_priority=None,
    ),
    ProviderSpec(
        id="apple",
        display_name="Apple (Built-in)",
        kind="transcription",
        category="local",
        module="whisper_hud.providers.apple_speech",
        class_name="AppleSpeechProvider",
        credential_vendor=None,
        config_model_field="apple_model",
        requires_download=False,
        fallback_priority=0,
    ),
    ProviderSpec(
        id="whisper_local",
        display_name="Whisper Local",
        kind="transcription",
        category="local",
        module="whisper_hud.providers.whisper_local",
        class_name="WhisperLocalProvider",
        credential_vendor=None,
        config_model_field="whisper_local_model",
        requires_download=True,
        fallback_priority=1,
    ),
    ProviderSpec(
        id="parakeet",
        display_name="Parakeet",
        kind="transcription",
        category="local",
        module="whisper_hud.providers.parakeet",
        class_name="ParakeetProvider",
        credential_vendor=None,
        config_model_field="parakeet_model",
        requires_download=True,
        fallback_priority=2,
        platform_gate="darwin",
    ),
    ProviderSpec(
        id="qwen3_asr",
        display_name="Qwen3 ASR",
        kind="transcription",
        category="local",
        module="whisper_hud.providers.qwen3_asr",
        class_name="Qwen3ASRProvider",
        credential_vendor=None,
        config_model_field="qwen3_asr_model",
        requires_download=True,
        fallback_priority=3,
        platform_gate="darwin",
    ),
    ProviderSpec(
        id="apple_analyzer",
        display_name="Apple Speech (Advanced)",
        kind="transcription",
        category="local",
        module="whisper_hud.providers.apple_speechanalyzer",
        class_name="AppleSpeechAnalyzerProvider",
        credential_vendor=None,
        config_model_field="apple_analyzer_model",
        requires_download=False,
        fallback_priority=None,
        platform_gate="darwin",
    ),
)


# Translation providers, in the exact order TranslationManager exposes them.
TRANSLATION_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="ollama",
        display_name="Ollama (Local)",
        kind="translation",
        category="local",
        module="whisper_hud.providers.translation.ollama",
        class_name="OllamaTranslateProvider",
        credential_vendor=None,
        config_model_field="translation_model",
        requires_download=True,
        fallback_priority=None,
    ),
    ProviderSpec(
        id="apple",
        display_name="Apple (Local)",
        kind="translation",
        category="local",
        module="whisper_hud.providers.translation.apple_translate",
        class_name="AppleTranslateProvider",
        credential_vendor=None,
        config_model_field=None,
        requires_download=False,
        fallback_priority=None,
    ),
    ProviderSpec(
        id="gemini",
        display_name="Gemini (Cloud)",
        kind="translation",
        category="cloud",
        module="whisper_hud.providers.translation.gemini_translate",
        class_name="GeminiTranslateProvider",
        credential_vendor="gemini",
        config_model_field="gemini_translate_model",
        requires_download=False,
        fallback_priority=None,
    ),
    ProviderSpec(
        id="openai",
        display_name="OpenAI (Cloud)",
        kind="translation",
        category="cloud",
        module="whisper_hud.providers.translation.openai_translate",
        class_name="OpenAITranslateProvider",
        credential_vendor="openai",
        config_model_field="openai_translate_model",
        requires_download=False,
        fallback_priority=None,
    ),
    ProviderSpec(
        id="anthropic",
        display_name="Anthropic Claude",
        kind="translation",
        category="cloud",
        module="whisper_hud.providers.translation.anthropic_translate",
        class_name="AnthropicTranslateProvider",
        credential_vendor="anthropic",
        config_model_field="anthropic_translate_model",
        requires_download=False,
        fallback_priority=None,
    ),
)


def resolve_provider_class(spec: ProviderSpec) -> Optional[type]:
    """Lazily import and return the provider class described by ``spec``.

    Returns ``None`` (logging at debug level) if the module or class cannot be
    resolved. This tolerance lets a spec point at a not-yet-implemented module:
    such a provider is simply hidden until its module exists.
    """
    try:
        module = importlib.import_module(spec.module)
        return getattr(module, spec.class_name)
    except (ImportError, AttributeError) as exc:
        logger.debug("Provider %s unavailable: %s", spec.id, exc)
        return None


def specs_by_id(kind: str) -> dict[str, ProviderSpec]:
    """Return a mapping of provider id -> spec for the given ``kind``.

    ``kind`` is ``"transcription"`` or ``"translation"``. Ids are unique within
    a kind (transcription and translation may legitimately reuse ids such as
    ``"apple"``/``"gemini"``/``"openai"``, which is why this is keyed per kind).
    """
    specs = TRANSCRIPTION_SPECS if kind == "transcription" else TRANSLATION_SPECS
    return {spec.id: spec for spec in specs}


def credential_vendors() -> tuple[str, ...]:
    """Return the unique API-key vendors across all providers.

    Order is preserved by first appearance, scanning transcription specs then
    translation specs. With the current spec set this yields
    ``("openai", "gemini", "anthropic")``.
    """
    vendors: list[str] = []
    for spec in (*TRANSCRIPTION_SPECS, *TRANSLATION_SPECS):
        vendor = spec.credential_vendor
        if vendor is not None and vendor not in vendors:
            vendors.append(vendor)
    return tuple(vendors)
