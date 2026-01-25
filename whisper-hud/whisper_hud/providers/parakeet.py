"""
Parakeet MLX provider for Apple Silicon optimized transcription.

Uses NVIDIA's Parakeet model optimized for Apple Silicon via MLX.
Significantly faster than Whisper on M1/M2/M3/M4 chips.

Requirements:
- Apple Silicon Mac (M1/M2/M3/M4)
- parakeet-mlx package

Features:
- 30x faster than Whisper on Apple Silicon
- Word-level timestamps
- Optimized for Neural Engine
- English and 25 European languages
"""

import importlib.util
import os
import time
import platform
from pathlib import Path
from typing import Optional, Callable
from .base import TranscriptionProvider, TranscriptionResult


# Model cache directory
CACHE_DIR = Path.home() / ".cache" / "whisper-hud" / "parakeet"


class ParakeetProvider(TranscriptionProvider):
    """Transcription provider using Parakeet MLX for Apple Silicon."""

    name = "parakeet"
    display_name = "Parakeet (Apple Silicon)"

    # Available models
    MODELS = {
        "parakeet-tdt-0.6b-v3": {
            "name": "Parakeet 0.6B v3",
            "size_mb": 600,
            "description": "25 European languages",
            "languages": "multilingual",
            "recommended": True,
        },
        "parakeet-tdt-0.6b-v2": {
            "name": "Parakeet 0.6B v2",
            "size_mb": 600,
            "description": "English only",
            "languages": ["en"],
        },
    }

    # Supported languages for v3 model
    SUPPORTED_LANGUAGES = {
        "en": "English",
        "de": "German",
        "es": "Spanish",
        "fr": "French",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "pl": "Polish",
        "ru": "Russian",
        "uk": "Ukrainian",
        "cs": "Czech",
        "sk": "Slovak",
        "hu": "Hungarian",
        "ro": "Romanian",
        "bg": "Bulgarian",
        "hr": "Croatian",
        "sl": "Slovenian",
        "sr": "Serbian",
        "da": "Danish",
        "no": "Norwegian",
        "sv": "Swedish",
        "fi": "Finnish",
        "el": "Greek",
        "tr": "Turkish",
        "ca": "Catalan",
    }

    def __init__(self, model: str = "parakeet-tdt-0.6b-v3"):
        """
        Initialize Parakeet provider.

        Args:
            model: Model to use
        """
        if model not in self.MODELS:
            model = "parakeet-tdt-0.6b-v3"
        self.model = model
        self._parakeet_model = None
        self._available = None

    def _is_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon."""
        if platform.system() != "Darwin":
            return False

        try:
            # Check for ARM architecture
            return platform.machine() == "arm64"
        except Exception:
            return False

    def _check_availability(self) -> bool:
        """Check if Parakeet is available on this system."""
        if self._available is not None:
            return self._available

        if not self._is_apple_silicon():
            self._available = False
            return False

        if importlib.util.find_spec("parakeet_mlx") is None:
            self._available = False
            return False

        self._available = True
        return True

    def is_model_downloaded(self) -> bool:
        """Check if the current model is downloaded."""
        try:
            from huggingface_hub import try_to_load_from_cache
            model_name = f"nvidia/{self.model}"
            # Check if any model files are cached
            cached = try_to_load_from_cache(model_name, "config.json")
            return cached is not None
        except Exception:
            return False

    def _load_model(self):
        """Load the Parakeet model."""
        if self._parakeet_model is None:
            try:
                from parakeet_mlx import load_model

                self._parakeet_model = load_model(self.model)

            except ImportError:
                raise RuntimeError(
                    "parakeet-mlx not installed. "
                    "Install with: pip install parakeet-mlx"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to load Parakeet model: {e}")

        return self._parakeet_model

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribe audio using Parakeet MLX.

        Args:
            audio_bytes: WAV file contents

        Returns:
            TranscriptionResult with transcribed text
        """
        start_time = time.time()

        if not self._is_apple_silicon():
            raise RuntimeError(
                "Parakeet requires Apple Silicon (M1/M2/M3/M4). "
                "Please use Whisper Local or a cloud provider instead."
            )

        if not self._check_availability():
            raise RuntimeError(
                "parakeet-mlx is not installed. "
                "Install with: pip install parakeet-mlx"
            )

        try:
            from parakeet_mlx import transcribe

            # Write audio to temp file
            # Prefix enables orphan cleanup if app crashes
            import tempfile
            with tempfile.NamedTemporaryFile(
                prefix="whisper_hud_", suffix=".wav", delete=False
            ) as f:
                f.write(audio_bytes)
                temp_path = f.name

            try:
                # Transcribe
                result = transcribe(
                    temp_path,
                    model=self.model,
                )

                # Extract text from result
                if isinstance(result, dict):
                    text = result.get("text", "")
                elif hasattr(result, "text"):
                    text = result.text
                else:
                    text = str(result)

            finally:
                # Securely delete temp file (overwrite before unlink)
                from ..encryption import secure_delete
                secure_delete(temp_path)

            duration = time.time() - start_time

            return TranscriptionResult(
                text=text.strip(),
                duration_seconds=duration,
                cost_estimate=0.0,  # Free - local processing
                provider=self.name,
                model=self.model,
                language=None  # Parakeet doesn't always return detected language
            )

        except Exception as e:
            raise RuntimeError(f"Parakeet transcription failed: {e}")

    def is_configured(self) -> bool:
        """
        Check if the provider is ready to use.

        Returns True on Apple Silicon with parakeet-mlx installed and model downloaded.
        """
        if not self._is_apple_silicon():
            return False
        if not self._check_availability():
            return False
        return self.is_model_downloaded()

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
                "downloaded": downloaded,
                "languages": config["languages"],
                "recommended": config.get("recommended", False),
            })
        return models

    def _is_specific_model_downloaded(self, model_id: str) -> bool:
        """Check if a specific model is downloaded."""
        try:
            from huggingface_hub import try_to_load_from_cache
            model_name = f"nvidia/{model_id}"
            cached = try_to_load_from_cache(model_name, "config.json")
            return cached is not None
        except Exception:
            return False

    def set_model(self, model_id: str) -> None:
        """Set the active model."""
        if model_id in self.MODELS:
            if model_id != self.model:
                self.model = model_id
                self._parakeet_model = None  # Reset to load new model

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
        if not self._is_apple_silicon():
            if progress_callback:
                progress_callback("Error: Parakeet requires Apple Silicon", 0.0)
            return False

        try:
            from huggingface_hub import snapshot_download

            model_name = f"nvidia/{self.model}"
            model_config = self.MODELS[self.model]

            if progress_callback:
                progress_callback(
                    f"Downloading {model_config['name']} ({model_config['size_mb']}MB)...",
                    0.0
                )

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
                progress_callback("Error: huggingface_hub not installed", 0.0)
            return False
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error: {e}", 0.0)
            return False

    def get_download_size(self) -> float:
        """Get the download size in MB for the current model."""
        return self.MODELS[self.model]["size_mb"]

    def supports_streaming(self) -> bool:
        """Parakeet supports streaming via word-level timestamps."""
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
            on_chunk: Callback called with cumulative text

        Returns:
            TranscriptionResult with final text
        """
        start_time = time.time()

        if not self._is_apple_silicon():
            raise RuntimeError("Parakeet requires Apple Silicon")

        try:
            from parakeet_mlx import transcribe

            # Write audio to temp file
            # Prefix enables orphan cleanup if app crashes
            import tempfile
            with tempfile.NamedTemporaryFile(
                prefix="whisper_hud_", suffix=".wav", delete=False
            ) as f:
                f.write(audio_bytes)
                temp_path = f.name

            try:
                # Transcribe with word timestamps
                result = transcribe(
                    temp_path,
                    model=self.model,
                    word_timestamps=True,
                )

                # Stream words if available
                if isinstance(result, dict):
                    words = result.get("words", [])
                    text = result.get("text", "")

                    if words:
                        cumulative = ""
                        for word_info in words:
                            word = word_info.get("word", "") if isinstance(word_info, dict) else str(word_info)
                            cumulative += word + " "
                            on_chunk(cumulative.strip())
                    else:
                        on_chunk(text)
                else:
                    text = str(result)
                    on_chunk(text)

            finally:
                # Securely delete temp file
                from ..encryption import secure_delete
                secure_delete(temp_path)

            duration = time.time() - start_time

            final_text = text if isinstance(result, dict) else str(result)

            return TranscriptionResult(
                text=final_text.strip(),
                duration_seconds=duration,
                cost_estimate=0.0,
                provider=self.name,
                model=self.model,
                language=None
            )

        except Exception as e:
            raise RuntimeError(f"Parakeet streaming transcription failed: {e}")

    @staticmethod
    def is_apple_silicon() -> bool:
        """Check if running on Apple Silicon."""
        if platform.system() != "Darwin":
            return False
        return platform.machine() == "arm64"

    @staticmethod
    def is_parakeet_installed() -> bool:
        """Check if parakeet-mlx is installed."""
        return importlib.util.find_spec("parakeet_mlx") is not None

    @classmethod
    def get_availability_message(cls) -> str:
        """Get a human-readable availability message."""
        if platform.system() != "Darwin":
            return "Parakeet requires macOS"

        if not cls.is_apple_silicon():
            return "Parakeet requires Apple Silicon (M1/M2/M3/M4)"

        if not cls.is_parakeet_installed():
            return "Install parakeet-mlx: pip install parakeet-mlx"

        return "Parakeet is available"

    @classmethod
    def get_supported_languages(cls) -> dict[str, str]:
        """Return dict of supported language codes to names."""
        return cls.SUPPORTED_LANGUAGES.copy()

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
            has_space = available_mb >= (required_mb * 1.5)
            return has_space, available_mb
        except Exception:
            return False, 0.0
