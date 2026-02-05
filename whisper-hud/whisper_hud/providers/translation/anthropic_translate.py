"""
Anthropic translation provider for cloud-based translation.

Uses Anthropic's Messages API for high-quality translation with streaming support.
Claude 4.5 models provide fast, accurate translations.
"""

from typing import Optional, Callable
from .base import TranslationProvider, TranslationResult


class AnthropicTranslateProvider(TranslationProvider):
    """Translation provider using Anthropic Claude API."""

    name = "anthropic"
    display_name = "Anthropic Claude"

    # Available models (February 2026)
    MODELS = {
        "claude-sonnet-4-5": {
            "name": "Claude Sonnet 4.5",
            "description": "Best all-around balance of quality and speed",
            "category": "balanced",
            "recommended": True,
        },
        "claude-haiku-4-5": {
            "name": "Claude Haiku 4.5",
            "description": "Fastest, most cost-efficient",
            "category": "speed",
        },
        "claude-opus-4-5": {
            "name": "Claude Opus 4.5",
            "description": "Highest quality, deeper reasoning",
            "category": "quality",
        },
    }

    # Supported languages (50+)
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

    def __init__(self, model: str = "claude-sonnet-4-5"):
        if model not in self.MODELS:
            model = "claude-sonnet-4-5"
        self.model = model
        self._client = None

    def _get_client(self):
        """Get or create the Anthropic client."""
        if self._client is None:
            try:
                from anthropic import Anthropic
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. Install with: pip install anthropic"
                )

            from ...keychain import get_api_key

            api_key = get_api_key("anthropic")
            if not api_key:
                raise ValueError("Anthropic API key not configured")

            self._client = Anthropic(api_key=api_key)

        return self._client

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        """
        Translate text using Anthropic Claude.

        Args:
            text: Text to translate
            source_lang: Source language code (e.g., 'en')
            target_lang: Target language code (e.g., 'es')

        Returns:
            TranslationResult with translated text
        """
        if not text.strip():
            return TranslationResult(
                text="",
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model
            )

        try:
            client = self._get_client()
            system_prompt, user_message = self._build_messages(text, source_lang, target_lang)

            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            result_text = response.content[0].text.strip()
            result_text = self._clean_response(result_text)

            return TranslationResult(
                text=result_text,
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model
            )

        except Exception as e:
            raise RuntimeError(f"Anthropic translation failed: {e}")

    def _build_messages(self, text: str, source_lang: str, target_lang: str) -> tuple[str, str]:
        """Build the system prompt and user message for translation."""
        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        if not source_lang or source_lang == "auto":
            intro = f"You are a professional translator. Detect the source language and translate to {target_name}."
        else:
            source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
            intro = f"You are a professional translator. Translate text from {source_name} to {target_name}."

        system_prompt = f"""{intro}

Rules:
- Output ONLY the translated text, nothing else
- Preserve the original formatting and punctuation
- Handle idioms and context appropriately
- Keep names and technical terms as appropriate
- Produce natural-sounding translations"""

        return system_prompt, text

    def _clean_response(self, text: str) -> str:
        """Clean up model response."""
        # Remove any markdown formatting
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()

        # Remove quotes if wrapped
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]

        return text.strip()

    @classmethod
    def is_package_available(cls) -> bool:
        """Check if anthropic package is installed."""
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        """Check if Anthropic is usable (package installed and API key configured)."""
        if not self.is_package_available():
            return False
        from ...keychain import get_api_key
        return bool(get_api_key("anthropic"))

    def get_model_status(self) -> dict:
        """Return model status information."""
        return {
            "model": self.model,
            "downloaded": True,  # Cloud-based, always available
            "size_gb": 0,
            "ram_required": "N/A (cloud)",
            "requires_download": False
        }

    def download_model(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """No download needed for cloud provider."""
        if progress_callback:
            progress_callback("Anthropic is a cloud service, no download needed")
        return True

    def supports_streaming(self) -> bool:
        """Anthropic supports streaming."""
        return True

    def translate_streaming(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_chunk: Callable[[str], None]
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
                text="",
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model
            )

        try:
            client = self._get_client()
            system_prompt, user_message = self._build_messages(text, source_lang, target_lang)

            cumulative_text = ""
            with client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                for text_chunk in stream.text_stream:
                    cumulative_text += text_chunk
                    clean_text = self._clean_response(cumulative_text)
                    on_chunk(clean_text)

            final_text = self._clean_response(cumulative_text)

            return TranslationResult(
                text=final_text,
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model
            )

        except Exception as e:
            raise RuntimeError(f"Anthropic streaming translation failed: {e}")

    def set_model(self, model_id: str) -> None:
        """Change the active model."""
        if model_id in self.MODELS:
            self.model = model_id

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
