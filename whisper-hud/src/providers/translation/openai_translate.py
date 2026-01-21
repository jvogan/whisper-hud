"""
OpenAI translation provider for cloud-based translation.

Uses OpenAI's Chat Completions API (same key as OpenAI transcription) for
high-quality translation with streaming support.

Great for creative and marketing text with natural-sounding output.
"""

from typing import Optional, Callable
from .base import TranslationProvider, TranslationResult


class OpenAITranslateProvider(TranslationProvider):
    """Translation provider using OpenAI Chat Completions API."""

    name = "openai"
    display_name = "OpenAI (Cloud)"

    # Available models (January 2026)
    MODELS = {
        "gpt-5-nano": {
            "name": "GPT-5 Nano",
            "description": "Fastest, most affordable",
            "category": "speed",
        },
        "gpt-5-mini": {
            "name": "GPT-5 Mini",
            "description": "Fast, cost-effective",
            "category": "balanced",
            "recommended": True,
        },
        "gpt-5.2": {
            "name": "GPT-5.2",
            "description": "Best quality, smartest",
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

    def __init__(self, model: str = "gpt-5-mini"):
        if model not in self.MODELS:
            model = "gpt-5-mini"
        self.model = model
        self._client = None

    def _get_client(self):
        """Get or create the OpenAI client."""
        if self._client is None:
            from ...keychain import get_api_key
            from openai import OpenAI

            api_key = get_api_key("openai")
            if not api_key:
                raise ValueError("OpenAI API key not configured")

            self._client = OpenAI(api_key=api_key)

        return self._client

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        """
        Translate text using OpenAI.

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
            messages = self._build_messages(text, source_lang, target_lang)

            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
            )

            result_text = response.choices[0].message.content.strip()
            result_text = self._clean_response(result_text)

            return TranslationResult(
                text=result_text,
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model
            )

        except Exception as e:
            raise RuntimeError(f"OpenAI translation failed: {e}")

    def _build_messages(self, text: str, source_lang: str, target_lang: str) -> list:
        """Build the chat messages for translation."""
        source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        system_prompt = f"""You are a professional translator. Translate text from {source_name} to {target_name}.

Rules:
- Output ONLY the translated text, nothing else
- Preserve the original formatting and punctuation
- Handle idioms and context appropriately
- Keep names and technical terms as appropriate
- Produce natural-sounding translations"""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]

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

    def is_available(self) -> bool:
        """Check if OpenAI API key is configured."""
        from ...keychain import get_api_key
        return bool(get_api_key("openai"))

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
            progress_callback("OpenAI is a cloud service, no download needed")
        return True

    def supports_streaming(self) -> bool:
        """OpenAI supports streaming."""
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
            messages = self._build_messages(text, source_lang, target_lang)

            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
                stream=True
            )

            cumulative_text = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    cumulative_text += chunk.choices[0].delta.content
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
            raise RuntimeError(f"OpenAI streaming translation failed: {e}")

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
