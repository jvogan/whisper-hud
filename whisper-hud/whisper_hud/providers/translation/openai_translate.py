"""
OpenAI translation provider for cloud-based translation.

Uses OpenAI's Responses API (same key as OpenAI transcription) for
high-quality translation with streaming support.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .base import TranslationProvider, TranslationResult
from ..error_utils import build_provider_error_message
from ..http_client_utils import OPENAI_API_BASE_URL, build_hardened_http_client


class OpenAITranslateProvider(TranslationProvider):
    """Translation provider using the OpenAI Responses API."""

    name = "openai"
    display_name = "OpenAI (Cloud)"

    DEFAULT_MODEL = "gpt-5-mini"
    CLIENT_TIMEOUT_SECONDS = 30.0
    CLIENT_MAX_RETRIES = 0

    # Available models (February 2026)
    MODELS = {
        "gpt-5.2": {
            "name": "GPT-5.2",
            "description": "Best quality, smartest",
            "category": "quality",
            "recommended": True,
        },
        "gpt-5-mini": {
            "name": "GPT-5 Mini",
            "description": "Fast, cost-effective",
            "category": "balanced",
        },
        "gpt-5-nano": {
            "name": "GPT-5 Nano",
            "description": "Fastest, most affordable",
            "category": "speed",
        },
    }

    MODEL_ALIASES = {
        # Historical/general aliases -> tuned translation defaults
        "gpt-5": "gpt-5.2",
        "gpt-5.1": "gpt-5.2",
        "gpt-5.2-chat-latest": "gpt-5.2",
        "gpt-5.2-pro": "gpt-5.2",
    }

    SUPPORTED_LANGUAGES = {
        "ar": "Arabic",
        "bn": "Bengali",
        "bg": "Bulgarian",
        "ca": "Catalan",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "hr": "Croatian",
        "cs": "Czech",
        "da": "Danish",
        "nl": "Dutch",
        "en": "English",
        "et": "Estonian",
        "fi": "Finnish",
        "fr": "French",
        "de": "German",
        "el": "Greek",
        "gu": "Gujarati",
        "he": "Hebrew",
        "hi": "Hindi",
        "hu": "Hungarian",
        "is": "Icelandic",
        "id": "Indonesian",
        "ga": "Irish",
        "it": "Italian",
        "ja": "Japanese",
        "kn": "Kannada",
        "ko": "Korean",
        "lv": "Latvian",
        "lt": "Lithuanian",
        "mk": "Macedonian",
        "ms": "Malay",
        "ml": "Malayalam",
        "mr": "Marathi",
        "no": "Norwegian",
        "fa": "Persian",
        "pl": "Polish",
        "pt": "Portuguese",
        "pt-BR": "Portuguese (Brazilian)",
        "pa": "Punjabi",
        "ro": "Romanian",
        "ru": "Russian",
        "sr": "Serbian",
        "sk": "Slovak",
        "sl": "Slovenian",
        "es": "Spanish",
        "sw": "Swahili",
        "sv": "Swedish",
        "ta": "Tamil",
        "te": "Telugu",
        "th": "Thai",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "ur": "Urdu",
        "vi": "Vietnamese",
        "cy": "Welsh",
        "zu": "Zulu",
    }

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = self.normalize_model_id(model)
        self._client = None

    @classmethod
    def normalize_model_id(cls, model_id: str) -> str:
        """Normalize configured model IDs to a supported OpenAI translation model."""
        if model_id in cls.MODELS:
            return model_id
        mapped = cls.MODEL_ALIASES.get(model_id)
        if mapped in cls.MODELS:
            return mapped
        return cls.DEFAULT_MODEL

    def _get_client(self):
        """Get or create the OpenAI client."""
        if self._client is None:
            from ...keychain import get_api_key
            from openai import OpenAI

            api_key = get_api_key("openai")
            if not api_key:
                raise ValueError("OpenAI API key not configured")

            self._client = OpenAI(
                api_key=api_key,
                base_url=OPENAI_API_BASE_URL,
                timeout=self.CLIENT_TIMEOUT_SECONDS,
                max_retries=self.CLIENT_MAX_RETRIES,
                http_client=build_hardened_http_client(self.CLIENT_TIMEOUT_SECONDS),
            )

        return self._client

    def _build_instructions(self, source_lang: str, target_lang: str) -> str:
        """Build translation instructions for the Responses API."""
        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        if not source_lang or source_lang == "auto":
            intro = "You are a professional translator. Detect the source language " f"and translate to {target_name}."
        else:
            source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
            intro = "You are a professional translator. " f"Translate text from {source_name} to {target_name}."

        return (
            f"{intro}\n\n"
            "Rules:\n"
            "- Output ONLY the translated text, nothing else\n"
            "- Preserve the original formatting and punctuation\n"
            "- Handle idioms and context appropriately\n"
            "- Keep names and technical terms as appropriate\n"
            "- Produce natural-sounding translations"
        )

    def _build_request_kwargs(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        stream: bool,
    ) -> dict:
        """Build Responses API request params with GPT-5 compatibility."""
        kwargs = {
            "model": self.model,
            "instructions": self._build_instructions(source_lang, target_lang),
            "input": text,
            "max_output_tokens": 4096,
        }
        if stream:
            kwargs["stream"] = True

        # GPT-5.2 supports temperature only with reasoning effort set to none.
        if self._supports_temperature():
            kwargs["temperature"] = 0.1
            kwargs["reasoning"] = {"effort": "none"}

        return kwargs

    def _supports_temperature(self) -> bool:
        """Temperature support is restricted to GPT-5.2 compatibility mode."""
        return self.model.startswith("gpt-5.2")

    def _safe_get(self, obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _extract_text_from_response(self, response: Any) -> str:
        """Extract model text from a Responses API response object or dict."""
        output_text = self._safe_get(response, "output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        parts = []
        output_items = self._safe_get(response, "output", []) or []
        for item in output_items:
            if self._safe_get(item, "type") != "message":
                continue
            content_items = self._safe_get(item, "content", []) or []
            for content in content_items:
                if self._safe_get(content, "type") not in {"output_text", "text"}:
                    continue
                text_part = self._safe_get(content, "text")
                if isinstance(text_part, str) and text_part:
                    parts.append(text_part)

        return "".join(parts).strip()

    def _extract_delta_text(self, event: Any) -> str:
        """Extract text delta from a streaming event."""
        if self._safe_get(event, "type") != "response.output_text.delta":
            return ""
        delta = self._safe_get(event, "delta", "")
        return delta if isinstance(delta, str) else ""

    def _clean_response(self, text: str) -> str:
        """Clean up model response."""
        if not text:
            return ""
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]
        return text.strip()

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        """Translate text using OpenAI Responses API."""
        if not text or not text.strip():
            return TranslationResult(
                text="",
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model,
            )

        try:
            client = self._get_client()
            response = client.responses.create(
                **self._build_request_kwargs(text, source_lang, target_lang, stream=False)
            )
            result_text = self._clean_response(self._extract_text_from_response(response))
            return TranslationResult(
                text=result_text,
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model,
            )
        except Exception as e:
            raise RuntimeError(build_provider_error_message("OpenAI", "translation", e)) from e

    def is_available(self) -> bool:
        """Check if OpenAI API key is configured."""
        from ...keychain import get_api_key

        return bool(get_api_key("openai"))

    def get_model_status(self) -> dict:
        """Return model status information."""
        return {
            "model": self.model,
            "downloaded": True,
            "size_gb": 0,
            "ram_required": "N/A (cloud)",
            "requires_download": False,
        }

    def download_model(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """No download needed for cloud provider."""
        if progress_callback:
            progress_callback("OpenAI is a cloud service, no download needed")
        return True

    def supports_streaming(self) -> bool:
        """OpenAI supports streaming via the Responses API."""
        return True

    def translate_streaming(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_chunk: Callable[[str], None],
    ) -> TranslationResult:
        """Translate text with streaming output."""
        if not text or not text.strip():
            return TranslationResult(
                text="",
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model,
            )

        try:
            client = self._get_client()
            responses_api = client.responses
            cumulative_text = ""

            # Preferred streaming path for modern SDKs.
            if hasattr(responses_api, "stream"):
                stream_request = self._build_request_kwargs(text, source_lang, target_lang, stream=False)
                with responses_api.stream(**stream_request) as stream:
                    for event in stream:
                        delta = self._extract_delta_text(event)
                        if not delta:
                            continue
                        cumulative_text += delta
                        on_chunk(self._clean_response(cumulative_text))

                    final_response = stream.get_final_response() if hasattr(stream, "get_final_response") else None
                    final_text = self._extract_text_from_response(final_response) if final_response else ""
                    if not final_text:
                        final_text = cumulative_text
            else:
                # Backward-compatible fallback path.
                events = responses_api.create(**self._build_request_kwargs(text, source_lang, target_lang, stream=True))
                for event in events:
                    delta = self._extract_delta_text(event)
                    if not delta:
                        continue
                    cumulative_text += delta
                    on_chunk(self._clean_response(cumulative_text))
                final_text = cumulative_text

                # If no streaming text was emitted, fall back to one-shot call.
                if not final_text:
                    response = responses_api.create(
                        **self._build_request_kwargs(text, source_lang, target_lang, stream=False)
                    )
                    final_text = self._extract_text_from_response(response)

            final_text = self._clean_response(final_text)
            if final_text:
                on_chunk(final_text)

            return TranslationResult(
                text=final_text,
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model,
            )
        except Exception as e:
            raise RuntimeError(build_provider_error_message("OpenAI", "translation", e)) from e

    def set_model(self, model_id: str) -> None:
        """Change the active model."""
        self.model = self.normalize_model_id(model_id)
        self._client = None

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.model

    def get_models(self) -> list[dict]:
        """Return available models."""
        return [
            {
                "id": model_id,
                "name": config["name"],
                "description": config["description"],
                "size_gb": 0,
                "ram_required": "N/A",
                "category": config.get("category", "balanced"),
                "recommended": config.get("recommended", False),
            }
            for model_id, config in self.MODELS.items()
        ]

    @classmethod
    def get_supported_languages(cls) -> dict[str, str]:
        """Return dict of supported language codes to names."""
        return cls.SUPPORTED_LANGUAGES.copy()
