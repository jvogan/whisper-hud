"""
Gemini translation provider for cloud-based translation.

Uses Google's Gemini API (same key as Gemini transcription) for
high-quality, context-aware translation with streaming support.

Supports 100+ languages with excellent handling of idioms and context.
"""

from typing import Optional, Callable
from .base import TranslationProvider, TranslationResult


class GeminiTranslateProvider(TranslationProvider):
    """Translation provider using Google Gemini API."""

    name = "gemini"
    display_name = "Gemini (Cloud)"

    # Available models (January 2026)
    MODELS = {
        "gemini-3.0-flash": {
            "name": "Gemini 3 Flash",
            "description": "Cutting-edge, fastest",
            "category": "speed",
        },
        "gemini-2.5-flash": {
            "name": "Gemini 2.5 Flash",
            "description": "Fast, efficient",
            "category": "balanced",
            "recommended": True,
        },
        "gemini-2.5-pro": {
            "name": "Gemini 2.5 Pro",
            "description": "Best quality",
            "category": "quality",
        },
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

    def __init__(self, model: str = "gemini-2.5-flash"):
        if model not in self.MODELS:
            model = "gemini-2.5-flash"
        self.model = model
        self._client = None

    def _get_client(self):
        """Get or create the Gemini client."""
        if self._client is None:
            from ...keychain import get_api_key
            import google.generativeai as genai

            api_key = get_api_key("gemini")
            if not api_key:
                raise ValueError("Gemini API key not configured")

            genai.configure(api_key=api_key)
            self._client = genai.GenerativeModel(self.model)

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
                text="",
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model
            )

        try:
            client = self._get_client()
            prompt = self._build_prompt(text, source_lang, target_lang)

            response = client.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 4096,
                }
            )

            result_text = response.text.strip()
            result_text = self._clean_response(result_text)

            return TranslationResult(
                text=result_text,
                source_lang=source_lang,
                target_lang=target_lang,
                provider=self.name,
                model=self.model
            )

        except Exception as e:
            raise RuntimeError(f"Gemini translation failed: {e}")

    def _build_prompt(self, text: str, source_lang: str, target_lang: str) -> str:
        """Build the translation prompt."""
        source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        return f"""Translate the following text from {source_name} to {target_name}.

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
            "requires_download": False
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
            prompt = self._build_prompt(text, source_lang, target_lang)

            response = client.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 4096,
                },
                stream=True
            )

            cumulative_text = ""
            for chunk in response:
                if chunk.text:
                    cumulative_text += chunk.text
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
            raise RuntimeError(f"Gemini streaming translation failed: {e}")

    def set_model(self, model_id: str) -> None:
        """Change the active model."""
        if model_id in self.MODELS:
            self.model = model_id
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
