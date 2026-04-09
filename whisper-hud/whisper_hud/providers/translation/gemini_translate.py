"""
Gemini translation provider for cloud-based translation.

Uses Google's Gemini API (same key as Gemini transcription) for
high-quality, context-aware translation with streaming support.

Supports 100+ languages with excellent handling of idioms and context.
"""

from __future__ import annotations

from typing import Callable, Optional

from .base import TranslationProvider, TranslationResult
from ..error_utils import build_provider_error_message


class GeminiTranslateProvider(TranslationProvider):
    """Translation provider using Google Gemini API."""

    name = "gemini"
    display_name = "Gemini (Cloud)"

    DEFAULT_MODEL = "gemini-2.5-flash"
    STABLE_FALLBACK_MODEL = "gemini-2.5-flash"
    CLIENT_TIMEOUT_MS = 30000

    # Available models (April 2026)
    MODELS = {
        "gemini-3.1-pro-preview": {
            "name": "Gemini 3.1 Pro (Preview)",
            "description": "Latest preview quality model with improved reasoning and reliability",
            "category": "quality",
        },
        "gemini-2.5-pro": {
            "name": "Gemini 2.5 Pro",
            "description": "Highest stable quality for nuanced translation",
            "category": "quality",
        },
        "gemini-2.5-flash": {
            "name": "Gemini 2.5 Flash",
            "description": "Current stable default for fast, high-volume translation",
            "category": "balanced",
            "recommended": True,
        },
        "gemini-2.5-flash-lite": {
            "name": "Gemini 2.5 Flash Lite",
            "description": "Lowest latency/cost",
            "category": "speed",
        },
        "gemini-3-flash-preview": {
            "name": "Gemini 3 Flash (Preview)",
            "description": "Frontier preview model for the latest Gemini 3 quality",
            "category": "balanced",
        },
        "gemini-3.1-flash-lite-preview": {
            "name": "Gemini 3.1 Flash-Lite (Preview)",
            "description": "Latest preview speed/cost option, explicitly recommended for translation at scale",
            "category": "speed",
        },
    }

    MODEL_ALIASES = {
        "gemini-3-pro-preview": "gemini-3.1-pro-preview",
        "gemini-3-pro": "gemini-3.1-pro-preview",
        "gemini-3.1-pro": "gemini-3.1-pro-preview",
        "gemini-3-flash": "gemini-3-flash-preview",
        "gemini-3.1-flash-lite": "gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash-preview": "gemini-2.5-flash",
        "gemini-2.5-flash-lite-preview-09-2025": "gemini-2.5-flash-lite",
    }

    # Supported languages (100+)
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
        "af": "Afrikaans",
        "sq": "Albanian",
        "am": "Amharic",
        "hy": "Armenian",
        "az": "Azerbaijani",
        "eu": "Basque",
        "be": "Belarusian",
        "bs": "Bosnian",
        "my": "Burmese",
        "ceb": "Cebuano",
        "ny": "Chichewa",
        "co": "Corsican",
        "eo": "Esperanto",
        "tl": "Filipino",
        "fy": "Frisian",
        "gl": "Galician",
        "ka": "Georgian",
        "ht": "Haitian Creole",
        "ha": "Hausa",
        "haw": "Hawaiian",
        "iw": "Hebrew",
        "hmn": "Hmong",
        "ig": "Igbo",
        "jw": "Javanese",
        "kk": "Kazakh",
        "km": "Khmer",
        "rw": "Kinyarwanda",
        "ku": "Kurdish",
        "ky": "Kyrgyz",
        "lo": "Lao",
        "la": "Latin",
        "lb": "Luxembourgish",
        "mg": "Malagasy",
        "mt": "Maltese",
        "mi": "Maori",
        "mn": "Mongolian",
        "ne": "Nepali",
        "or": "Odia",
        "ps": "Pashto",
        "sm": "Samoan",
        "gd": "Scots Gaelic",
        "st": "Sesotho",
        "sn": "Shona",
        "sd": "Sindhi",
        "si": "Sinhala",
        "so": "Somali",
        "su": "Sundanese",
        "tg": "Tajik",
        "tt": "Tatar",
        "tk": "Turkmen",
        "ug": "Uyghur",
        "uz": "Uzbek",
        "xh": "Xhosa",
        "yi": "Yiddish",
        "yo": "Yoruba",
    }

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = self.normalize_model_id(model)
        self._client = None

    @classmethod
    def normalize_model_id(cls, model_id: str) -> str:
        """Normalize configured IDs to supported Gemini translation models."""
        if model_id in cls.MODELS:
            return model_id
        mapped = cls.MODEL_ALIASES.get(model_id)
        if mapped in cls.MODELS:
            return mapped
        return cls.DEFAULT_MODEL

    @staticmethod
    def _is_model_not_found_error(error: Exception) -> bool:
        """Return True when Gemini rejects the selected model ID."""
        message = str(error).lower()
        if "model" not in message:
            return False
        return any(token in message for token in ("not found", "invalid", "unsupported", "unknown"))

    def _get_client(self):
        """Get or create the Gemini client."""
        if self._client is None:
            from ...keychain import get_api_key

            try:
                from google import genai
                from google.genai import types
            except ImportError:
                raise RuntimeError("google-genai package not installed. Install with: pip install google-genai")

            api_key = get_api_key("gemini")
            if not api_key:
                raise ValueError("Gemini API key not configured")

            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=self.CLIENT_TIMEOUT_MS),
            )

        return self._client

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        """
        Translate text using Gemini.

        Args:
            text: Text to translate
            source_lang: Source language code (e.g., 'en')
            target_lang: Target language code (e.g., 'es')

        Returns:
            TranslationResult with translated text
        """
        if not text.strip():
            return TranslationResult(
                text="", source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
            )

        attempt_models = [self.model]
        if self.STABLE_FALLBACK_MODEL not in attempt_models:
            attempt_models.append(self.STABLE_FALLBACK_MODEL)

        try:
            client = self._get_client()
            prompt = self._build_prompt(text, source_lang, target_lang)
            from google.genai import types

            result_text = ""
            used_model = self.model
            last_error: Optional[Exception] = None
            for index, model_id in enumerate(attempt_models):
                try:
                    response = client.models.generate_content(
                        model=model_id,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            max_output_tokens=4096,
                        ),
                    )
                    result_text = self._clean_response((response.text or "").strip())
                    used_model = model_id
                    break
                except Exception as e:
                    last_error = e
                    should_retry = index < len(attempt_models) - 1 and self._is_model_not_found_error(e)
                    if not should_retry:
                        raise

            if result_text == "" and last_error is not None:
                raise last_error

            if used_model != self.model:
                self.model = used_model

            return TranslationResult(
                text=result_text, source_lang=source_lang, target_lang=target_lang, provider=self.name, model=used_model
            )

        except Exception as e:
            raise RuntimeError(build_provider_error_message("Gemini", "translation", e)) from e

    def _build_prompt(self, text: str, source_lang: str, target_lang: str) -> str:
        """Build the translation prompt."""
        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        if not source_lang or source_lang == "auto":
            header = f"Detect the source language and translate to {target_name}."
        else:
            source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
            header = f"Translate the following text from {source_name} to {target_name}."

        return f"""{header}

Rules:
- Output ONLY the translated text, nothing else
- Preserve the original formatting and punctuation
- Handle idioms and context appropriately
- Keep names and technical terms as appropriate

Text to translate:
{text}"""

    def _clean_response(self, text: str) -> str:
        """Clean up model response."""
        # Remove any markdown formatting the model might add
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()

        # Remove quotes if wrapped
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]

        return text.strip()

    def is_available(self) -> bool:
        """Check if Gemini API key is configured."""
        from ...keychain import get_api_key

        return bool(get_api_key("gemini"))

    def get_model_status(self) -> dict:
        """Return model status information."""
        return {
            "model": self.model,
            "downloaded": True,  # Cloud-based, always available
            "size_gb": 0,
            "ram_required": "N/A (cloud)",
            "requires_download": False,
        }

    def download_model(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """No download needed for cloud provider."""
        if progress_callback:
            progress_callback("Gemini is a cloud service, no download needed")
        return True

    def supports_streaming(self) -> bool:
        """Gemini supports streaming."""
        return True

    def translate_streaming(
        self, text: str, source_lang: str, target_lang: str, on_chunk: Callable[[str], None]
    ) -> TranslationResult:
        """
        Translate text with streaming output.

        Args:
            text: Text to translate
            source_lang: Source language code
            target_lang: Target language code
            on_chunk: Callback called with cumulative text as it streams

        Returns:
            TranslationResult with translated text
        """
        if not text.strip():
            return TranslationResult(
                text="", source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
            )

        attempt_models = [self.model]
        if self.STABLE_FALLBACK_MODEL not in attempt_models:
            attempt_models.append(self.STABLE_FALLBACK_MODEL)

        try:
            client = self._get_client()
            prompt = self._build_prompt(text, source_lang, target_lang)
            from google.genai import types

            final_text = ""
            used_model = self.model
            last_error: Optional[Exception] = None
            for index, model_id in enumerate(attempt_models):
                try:
                    response = client.models.generate_content_stream(
                        model=model_id,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            max_output_tokens=4096,
                        ),
                    )

                    cumulative_text = ""
                    for chunk in response:
                        chunk_text = getattr(chunk, "text", None)
                        if chunk_text:
                            cumulative_text += chunk_text
                            on_chunk(self._clean_response(cumulative_text))

                    final_text = self._clean_response(cumulative_text)
                    used_model = model_id
                    break
                except Exception as e:
                    last_error = e
                    should_retry = index < len(attempt_models) - 1 and self._is_model_not_found_error(e)
                    if not should_retry:
                        raise

            if final_text == "" and last_error is not None:
                raise last_error

            if used_model != self.model:
                self.model = used_model

            return TranslationResult(
                text=final_text, source_lang=source_lang, target_lang=target_lang, provider=self.name, model=used_model
            )

        except Exception as e:
            raise RuntimeError(build_provider_error_message("Gemini", "translation", e)) from e

    def set_model(self, model_id: str) -> None:
        """Change the active model."""
        if model_id in self.MODELS:
            normalized_model = model_id
        else:
            normalized_model = self.MODEL_ALIASES.get(model_id)
            if normalized_model not in self.MODELS:
                return

        if normalized_model != self.model:
            self.model = normalized_model
            self._client = None  # Reset client to use new model

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
