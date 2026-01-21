"""
Whisper Local provider for local transcription.

Uses SYSTRAN's faster-whisper for 4x faster inference than original Whisper.
Models are automatically downloaded from Hugging Face on first use.

Features:
- 99+ language support
- Works completely offline after initial model download
- Multiple model sizes for speed/quality tradeoff
- Automatic model download with progress callback
"""

import os
import time
from pathlib import Path
from typing import Optional, Callable
from .base import TranscriptionProvider, TranscriptionResult


# Model cache directory
CACHE_DIR = Path.home() / ".cache" / "whisper-hud" / "models"


class WhisperLocalProvider(TranscriptionProvider):
    """Transcription provider using faster-whisper for local inference."""

    name = "whisper_local"
    display_name = "Whisper Local"

    # Available models with their characteristics
    MODELS = {
        "tiny": {
            "name": "Tiny (75MB)",
            "size_mb": 75,
            "description": "Basic quality",
            "vram_gb": 1,
            "category": "speed",
        },
        "base": {
            "name": "Base (150MB)",
            "size_mb": 150,
            "description": "Good quality",
            "vram_gb": 1,
            "category": "speed",
        },
        "small": {
            "name": "Small (500MB)",
            "size_mb": 500,
            "description": "Better quality",
            "vram_gb": 2,
            "category": "balanced",
        },
        "large-v3-turbo": {
            "name": "Large v3 Turbo (800MB)",
            "size_mb": 800,
            "description": "Fast + best quality",
            "vram_gb": 4,
            "category": "balanced",
            "recommended": True,
        },
        "medium": {
            "name": "Medium (1.5GB)",
            "size_mb": 1500,
            "description": "Great quality",
            "vram_gb": 5,
            "category": "quality",
        },
        "large-v3": {
            "name": "Large v3 (3GB)",
            "size_mb": 3000,
            "description": "Highest quality",
            "vram_gb": 10,
            "category": "quality",
        },
    }

    # Supported languages (99+)
    SUPPORTED_LANGUAGES = {
        "auto": "Auto-detect",
        "en": "English",
        "zh": "Chinese",
        "de": "German",
        "es": "Spanish",
        "ru": "Russian",
        "ko": "Korean",
        "fr": "French",
        "ja": "Japanese",
        "pt": "Portuguese",
        "tr": "Turkish",
        "pl": "Polish",
        "ca": "Catalan",
        "nl": "Dutch",
        "ar": "Arabic",
        "sv": "Swedish",
        "it": "Italian",
        "id": "Indonesian",
        "hi": "Hindi",
        "fi": "Finnish",
        "vi": "Vietnamese",
        "he": "Hebrew",
        "uk": "Ukrainian",
        "el": "Greek",
        "ms": "Malay",
        "cs": "Czech",
        "ro": "Romanian",
        "da": "Danish",
        "hu": "Hungarian",
        "ta": "Tamil",
        "no": "Norwegian",
        "th": "Thai",
        "ur": "Urdu",
        "hr": "Croatian",
        "bg": "Bulgarian",
        "lt": "Lithuanian",
        "la": "Latin",
        "mi": "Maori",
        "ml": "Malayalam",
        "cy": "Welsh",
        "sk": "Slovak",
        "te": "Telugu",
        "fa": "Persian",
        "lv": "Latvian",
        "bn": "Bengali",
        "sr": "Serbian",
        "az": "Azerbaijani",
        "sl": "Slovenian",
        "kn": "Kannada",
        "et": "Estonian",
        "mk": "Macedonian",
        "br": "Breton",
        "eu": "Basque",
        "is": "Icelandic",
        "hy": "Armenian",
        "ne": "Nepali",
        "mn": "Mongolian",
        "bs": "Bosnian",
        "kk": "Kazakh",
        "sq": "Albanian",
        "sw": "Swahili",
        "gl": "Galician",
        "mr": "Marathi",
        "pa": "Punjabi",
        "si": "Sinhala",
        "km": "Khmer",
        "sn": "Shona",
        "yo": "Yoruba",
        "so": "Somali",
        "af": "Afrikaans",
        "oc": "Occitan",
        "ka": "Georgian",
        "be": "Belarusian",
        "tg": "Tajik",
        "sd": "Sindhi",
        "gu": "Gujarati",
        "am": "Amharic",
        "yi": "Yiddish",
        "lo": "Lao",
        "uz": "Uzbek",
        "fo": "Faroese",
        "ht": "Haitian Creole",
        "ps": "Pashto",
        "tk": "Turkmen",
        "nn": "Norwegian Nynorsk",
        "mt": "Maltese",
        "sa": "Sanskrit",
        "lb": "Luxembourgish",
        "my": "Burmese",
        "bo": "Tibetan",
        "tl": "Tagalog",
        "mg": "Malagasy",
        "as": "Assamese",
        "tt": "Tatar",
        "haw": "Hawaiian",
        "ln": "Lingala",
        "ha": "Hausa",
        "ba": "Bashkir",
        "jw": "Javanese",
        "su": "Sundanese",
    }

    def __init__(self, model: str = "large-v3-turbo"):
        """
        Initialize Whisper Local provider.

        Args:
            model: Model size to use (tiny, base, small, medium, large-v3-turbo, large-v3)
        """
        if model not in self.MODELS:
            model = "large-v3-turbo"
        self.model = model
        self._whisper_model = None
        self._download_progress_callback = None

    def _get_model_path(self) -> Path:
        """Get the path where the model would be cached."""
        return CACHE_DIR / self.model

    def is_model_downloaded(self) -> bool:
        """Check if the current model is already downloaded."""
        # faster-whisper uses huggingface_hub for caching
        # Check if the model directory exists with expected files
        try:
            from huggingface_hub import snapshot_download, try_to_load_from_cache
            model_name = f"Systran/faster-whisper-{self.model}"
            # Check if model is in cache
            cached = try_to_load_from_cache(model_name, "model.bin")
            return cached is not None
        except Exception:
            return False

    def _load_model(self):
        """Load the whisper model."""
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel

                # Use CPU with int8 for broad compatibility
                # Could detect Apple Silicon and use different settings
                compute_type = "int8"
                device = "cpu"

                # Check for Apple Silicon
                import platform
                if platform.processor() == "arm":
                    # Apple Silicon - can use float16
                    compute_type = "float16"

                self._whisper_model = WhisperModel(
                    self.model,
                    device=device,
                    compute_type=compute_type,
                    download_root=str(CACHE_DIR),
                )

            except ImportError:
                raise RuntimeError(
                    "faster-whisper not installed. "
                    "Install with: pip install faster-whisper"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to load Whisper model: {e}")

        return self._whisper_model

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribe audio using local Whisper model.

        Args:
            audio_bytes: WAV file contents

        Returns:
            TranscriptionResult with transcribed text
        """
        start_time = time.time()

        try:
            model = self._load_model()

            # Write audio to temp file (faster-whisper needs a file path)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name

            try:
                # Transcribe
                segments, info = model.transcribe(
                    temp_path,
                    beam_size=5,
                    language=None,  # Auto-detect
                    vad_filter=True,  # Filter out non-speech
                )

                # Collect text from segments
                text_parts = []
                for segment in segments:
                    text_parts.append(segment.text)

                text = " ".join(text_parts).strip()

            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

            duration = time.time() - start_time

            return TranscriptionResult(
                text=text,
                duration_seconds=duration,
                cost_estimate=0.0,  # Free - local processing
                provider=self.name,
                model=self.model,
                language=info.language if hasattr(info, 'language') else None
            )

        except Exception as e:
            raise RuntimeError(f"Whisper transcription failed: {e}")

    def is_configured(self) -> bool:
        """
        Check if the provider is ready to use.

        Returns True if faster-whisper is installed and model is downloaded.
        """
        try:
            import faster_whisper
            return self.is_model_downloaded()
        except ImportError:
            return False

    def get_models(self) -> list[dict]:
        """Return available models with their info."""
        models = []
        for model_id, config in self.MODELS.items():
            downloaded = self._is_specific_model_downloaded(model_id)
            models.append({
                "id": model_id,
                "name": config["name"],
                "description": config["description"],
                "cost_per_minute": 0.0,
                "size_mb": config["size_mb"],
                "vram_gb": config["vram_gb"],
                "downloaded": downloaded,
                "category": config.get("category", "balanced"),
                "recommended": config.get("recommended", False),
            })
        return models

    def _is_specific_model_downloaded(self, model_id: str) -> bool:
        """Check if a specific model is downloaded."""
        try:
            from huggingface_hub import try_to_load_from_cache
            model_name = f"Systran/faster-whisper-{model_id}"
            cached = try_to_load_from_cache(model_name, "model.bin")
            return cached is not None
        except Exception:
            return False

    def set_model(self, model_id: str) -> None:
        """Set the active model."""
        if model_id in self.MODELS:
            if model_id != self.model:
                self.model = model_id
                self._whisper_model = None  # Reset to load new model

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.model

    def download_model(
        self,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> bool:
        """
        Download the current model.

        Args:
            progress_callback: Called with (status_message, progress_percent)

        Returns:
            True if download succeeded
        """
        try:
            from huggingface_hub import snapshot_download
            import sys

            model_name = f"Systran/faster-whisper-{self.model}"
            model_config = self.MODELS[self.model]

            if progress_callback:
                progress_callback(
                    f"Downloading {model_config['name']} ({model_config['size_mb']}MB)...",
                    0.0
                )

            # Download with progress tracking
            def progress_hook(progress):
                if progress_callback and hasattr(progress, 'total'):
                    pct = (progress.completed / progress.total) * 100 if progress.total > 0 else 0
                    progress_callback(f"Downloading... {pct:.0f}%", pct)

            snapshot_download(
                model_name,
                cache_dir=str(CACHE_DIR),
                local_files_only=False,
            )

            if progress_callback:
                progress_callback("Download complete!", 100.0)

            return True

        except ImportError:
            if progress_callback:
                progress_callback("Error: faster-whisper not installed", 0.0)
            return False
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error: {e}", 0.0)
            return False

    def get_download_size(self) -> float:
        """Get the download size in MB for the current model."""
        return self.MODELS[self.model]["size_mb"]

    def supports_streaming(self) -> bool:
        """faster-whisper supports streaming via segments."""
        return True

    def transcribe_streaming(
        self,
        audio_bytes: bytes,
        on_chunk: Callable[[str], None]
    ) -> TranscriptionResult:
        """
        Transcribe audio with streaming output.

        Args:
            audio_bytes: WAV file contents
            on_chunk: Callback called with cumulative text as segments complete

        Returns:
            TranscriptionResult with final text
        """
        start_time = time.time()

        try:
            model = self._load_model()

            # Write audio to temp file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name

            try:
                # Transcribe with streaming
                segments, info = model.transcribe(
                    temp_path,
                    beam_size=5,
                    language=None,
                    vad_filter=True,
                )

                # Stream segments
                cumulative_text = ""
                for segment in segments:
                    cumulative_text += segment.text + " "
                    on_chunk(cumulative_text.strip())

            finally:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

            duration = time.time() - start_time

            return TranscriptionResult(
                text=cumulative_text.strip(),
                duration_seconds=duration,
                cost_estimate=0.0,
                provider=self.name,
                model=self.model,
                language=info.language if hasattr(info, 'language') else None
            )

        except Exception as e:
            raise RuntimeError(f"Whisper streaming transcription failed: {e}")

    @staticmethod
    def check_disk_space(required_mb: float) -> tuple[bool, float]:
        """
        Check if there's enough disk space for download.

        Args:
            required_mb: Required space in MB

        Returns:
            Tuple of (has_space, available_mb)
        """
        try:
            statvfs = os.statvfs(os.path.expanduser("~"))
            available_mb = (statvfs.f_frsize * statvfs.f_bavail) / (1024**2)
            # Require 50% buffer
            has_space = available_mb >= (required_mb * 1.5)
            return has_space, available_mb
        except Exception:
            return False, 0.0

    @staticmethod
    def is_faster_whisper_installed() -> bool:
        """Check if faster-whisper is installed."""
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    @classmethod
    def get_supported_languages(cls) -> dict[str, str]:
        """Return dict of supported language codes to names."""
        return cls.SUPPORTED_LANGUAGES.copy()
