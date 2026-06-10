"""
Qwen3-ASR local transcription provider (Apple Silicon, via qwen3-asr-mlx).

Qwen3-ASR is Alibaba's Apache-2.0 speech-recognition family (52 languages and
dialects, strong on accented and noisy speech). This provider runs it fully
on-device through the pure-MLX ``qwen3-asr-mlx`` package, closing WhisperHUD's
biggest local gap: non-European languages that otherwise force users to cloud.

The ``qwen3-asr-mlx`` 0.1.x package exposes ``Qwen3ASR.from_pretrained(repo_id)``
which returns a model object with ``.transcribe(audio, language=None) ->
TranscriptionResult(text, language, duration)``. ``from_pretrained`` resolves a
HuggingFace repo id through ``huggingface_hub.snapshot_download`` into the
standard HF cache, so download/cache checks here mirror that exactly.
"""

import importlib.util
import os
import platform
import time
from typing import Any, Callable, Optional, Sequence

from .base import TranscriptionProvider, TranscriptionResult
from ..logging_config import get_logger

logger = get_logger("providers.qwen3_asr")

# HuggingFace organisation hosting the MLX-converted Qwen3-ASR weights.
# ``Qwen3ASR.from_pretrained`` downloads ``config.json`` + ``model.safetensors``
# (plus tokenizer files) from these repos; cache checks must use the same ids.
# The original ``Qwen/`` repos ship PyTorch checkpoints that qwen3-asr-mlx does
# not load directly, so we point at the mlx-community bf16 conversions that the
# package's own README documents.
HF_ORG = "mlx-community"


class Qwen3ASRProvider(TranscriptionProvider):
    """Local Qwen3-ASR transcription via the qwen3-asr-mlx package."""

    name = "qwen3_asr"
    display_name = "Qwen3 ASR"

    DEFAULT_MODEL = "qwen3-asr-0.6b"

    MODELS = {
        "qwen3-asr-0.6b": {
            "name": "Qwen3 ASR 0.6B",
            "size_mb": 700,
            "description": "52 languages — fast, strong on accents and noisy audio",
            "languages": "multilingual (52)",
            "recommended": True,
        },
        "qwen3-asr-1.7b": {
            "name": "Qwen3 ASR 1.7B",
            "size_mb": 1800,
            "description": "52 languages — higher accuracy, larger download",
            "languages": "multilingual (52)",
            "recommended": False,
        },
    }

    # Map our public model ids to the mlx-community bf16 repos that
    # qwen3-asr-mlx's ``from_pretrained`` actually loads.
    _HF_REPOS = {
        "qwen3-asr-0.6b": f"{HF_ORG}/Qwen3-ASR-0.6B-bf16",
        "qwen3-asr-1.7b": f"{HF_ORG}/Qwen3-ASR-1.7B-bf16",
    }

    def __init__(self, model: Optional[str] = None):
        """Initialize the Qwen3-ASR provider.

        Args:
            model: Model id to use. Falls back to :attr:`DEFAULT_MODEL` when
                missing or unknown.
        """
        self.model = model if model in self.MODELS else self.DEFAULT_MODEL
        self._qwen_model = None
        self._available = None

    # -- repo id resolution ----------------------------------------------

    @classmethod
    def _hf_repo_id(cls, model_id: str) -> str:
        """Resolve the HuggingFace repo id qwen3-asr-mlx loads for *model_id*.

        ``Qwen3ASR.from_pretrained`` downloads from this repo id, so cache
        checks and downloads must use the same id.
        """
        return cls._HF_REPOS.get(model_id, f"{HF_ORG}/{model_id}")

    # -- platform / availability gating ----------------------------------

    def _is_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon (arm64 macOS)."""
        if platform.system() != "Darwin":
            return False
        try:
            return platform.machine() == "arm64"
        except Exception:
            return False

    def _check_availability(self) -> bool:
        """Check whether Qwen3-ASR can run on this system (cached)."""
        if self._available is not None:
            return self._available

        if not self._is_apple_silicon():
            self._available = False
            return False

        if importlib.util.find_spec("qwen3_asr_mlx") is None:
            self._available = False
            return False

        self._available = True
        return True

    # -- model download state --------------------------------------------

    def is_model_downloaded(self) -> bool:
        """Check if the current model is present in the HuggingFace cache."""
        return self._is_specific_model_downloaded(self.model)

    def _is_specific_model_downloaded(self, model_id: str) -> bool:
        """Check if a specific model's weights are present in the HF cache.

        ``from_pretrained`` always reads ``config.json`` first, so probing the
        cache for it mirrors exactly what the loader will look for.
        """
        try:
            from huggingface_hub import try_to_load_from_cache

            repo_id = self._hf_repo_id(model_id)
            cached = try_to_load_from_cache(repo_id, "config.json")
            return cached is not None
        except Exception:
            return False

    # -- model loading ----------------------------------------------------

    def _load_model(self):
        """Load and cache the Qwen3-ASR model handle.

        qwen3-asr-mlx exposes ``Qwen3ASR.from_pretrained(repo_id)``; we resolve
        the same mlx-community repo id used for cache checks and downloads. The
        loaded handle is cached on the instance and reused across calls.
        """
        if self._qwen_model is None:
            try:
                import qwen3_asr_mlx
            except ImportError:
                raise RuntimeError(
                    "qwen3-asr-mlx not installed. "
                    "Install with: pip install 'whisper-hud[qwen3-asr]'"
                )

            try:
                self._qwen_model = qwen3_asr_mlx.Qwen3ASR.from_pretrained(self._hf_repo_id(self.model))
            except Exception as e:
                raise RuntimeError(f"Failed to load Qwen3-ASR model: {e}")

        return self._qwen_model

    @staticmethod
    def _extract_text(result: Any) -> str:
        """Pull transcript text out of a qwen3-asr-mlx result object or dict."""
        if isinstance(result, dict):
            return result.get("text", "") or ""
        text = getattr(result, "text", None)
        if text is not None:
            return text
        return str(result)

    @staticmethod
    def _extract_language(result: Any) -> Optional[str]:
        """Pull the detected language (full name) from a result, if present.

        The package reports ``"Unknown"`` when it cannot determine a language;
        we normalise that to ``None`` so callers do not surface a non-language.
        """
        if isinstance(result, dict):
            language = result.get("language")
        else:
            language = getattr(result, "language", None)
        if not language or str(language).strip().lower() in ("unknown", "none", ""):
            return None
        return str(language)

    # -- transcription ----------------------------------------------------

    def transcribe(self, audio_bytes: bytes, vocabulary: Optional[Sequence[str]] = None) -> TranscriptionResult:
        """
        Transcribe audio using Qwen3-ASR via MLX.

        Args:
            audio_bytes: WAV file contents.
            vocabulary: Accepted for interface compatibility and IGNORED.
                The qwen3-asr-mlx 0.1.x ``transcribe`` API exposes no
                vocabulary/context-biasing parameter (its prompt builder takes
                only audio tokens and an optional language name), so user
                vocabulary cannot be applied here. The argument is accepted so
                the provider conforms to the transcribe() contract.

        Returns:
            TranscriptionResult with the transcribed text and detected language.
        """
        start_time = time.time()

        if not self._is_apple_silicon():
            raise RuntimeError(
                "Qwen3 ASR requires Apple Silicon (M1/M2/M3/M4). "
                "Please use Whisper Local or a cloud provider instead."
            )

        if not self._check_availability():
            raise RuntimeError(
                "qwen3-asr-mlx is not installed. "
                "Install with: pip install 'whisper-hud[qwen3-asr]'"
            )

        try:
            from ..encryption import create_private_temp_file, secure_delete

            # qwen3-asr-mlx transcribes from a file path (or numpy array) via
            # the loaded model object (model.transcribe(path)); write audio to a
            # private scratch file and securely delete it afterwards.
            model = self._load_model()
            temp_path = create_private_temp_file(audio_bytes)

            try:
                result = model.transcribe(temp_path)
                text = self._extract_text(result)
                language = self._extract_language(result)
            finally:
                # Securely delete temp file (overwrite before unlink).
                secure_delete(temp_path)

            duration = time.time() - start_time

            return TranscriptionResult(
                text=text.strip(),
                duration_seconds=duration,
                cost_estimate=0.0,  # Free - local processing.
                provider=self.name,
                model=self.model,
                language=language,
            )

        except Exception as e:
            raise RuntimeError(f"Qwen3 ASR transcription failed: {e}")

    # -- configuration / models ------------------------------------------

    def is_configured(self) -> bool:
        """
        Check if the provider is ready to use.

        Returns True on Apple Silicon with qwen3-asr-mlx installed and the
        current model downloaded.
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
            models.append(
                {
                    "id": model_id,
                    "name": config["name"],
                    "description": config["description"],
                    "cost_per_minute": 0.0,
                    "size_mb": config["size_mb"],
                    "downloaded": downloaded,
                    "languages": config["languages"],
                    "recommended": config.get("recommended", False),
                }
            )
        return models

    def set_model(self, model_id: str) -> None:
        """Set the active model, resetting the cached handle when it changes."""
        if model_id in self.MODELS:
            if model_id != self.model:
                self.model = model_id
                self._qwen_model = None  # Reset to load new model.

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.model

    # -- download surface -------------------------------------------------

    def download_model(self, progress_callback: Optional[Callable[[str, float], None]] = None) -> bool:
        """
        Download the current model's weights from HuggingFace.

        Uses the same ``snapshot_download`` mechanism (and default HF cache)
        that ``Qwen3ASR.from_pretrained`` reads from, so a successful download
        here makes :meth:`is_model_downloaded` return True.

        Args:
            progress_callback: Called with (status_message, progress_percent).

        Returns:
            True if the download succeeded.
        """
        if not self._is_apple_silicon():
            if progress_callback:
                progress_callback("Error: Qwen3 ASR requires Apple Silicon", 0.0)
            return False

        try:
            from huggingface_hub import snapshot_download

            repo_id = self._hf_repo_id(self.model)
            model_config = self.MODELS[self.model]

            if progress_callback:
                progress_callback(f"Downloading {model_config['name']} ({model_config['size_mb']}MB)...", 0.0)

            snapshot_download(repo_id)

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
        return float(self.MODELS[self.model]["size_mb"])

    # -- static / class helpers ------------------------------------------

    @staticmethod
    def is_apple_silicon() -> bool:
        """Check if running on Apple Silicon."""
        if platform.system() != "Darwin":
            return False
        return platform.machine() == "arm64"

    @staticmethod
    def is_qwen3_asr_installed() -> bool:
        """Check if qwen3-asr-mlx is installed."""
        return importlib.util.find_spec("qwen3_asr_mlx") is not None

    @classmethod
    def get_availability_message(cls) -> str:
        """Get a human-readable availability message."""
        if platform.system() != "Darwin":
            return "Qwen3 ASR requires macOS"

        if not cls.is_apple_silicon():
            return "Qwen3 ASR requires Apple Silicon (M1/M2/M3/M4)"

        if not cls.is_qwen3_asr_installed():
            return "Install qwen3-asr-mlx: pip install 'whisper-hud[qwen3-asr]'"

        return "Qwen3 ASR is available"

    @staticmethod
    def check_disk_space(required_mb: float) -> tuple[bool, float]:
        """
        Check if there's enough disk space for a download.

        Args:
            required_mb: Required space in MB.

        Returns:
            Tuple of (has_space, available_mb). Uses a 1.5x safety margin.
        """
        try:
            statvfs = os.statvfs(os.path.expanduser("~"))
            available_mb = (statvfs.f_frsize * statvfs.f_bavail) / (1024**2)
            has_space = available_mb >= (required_mb * 1.5)
            return has_space, available_mb
        except Exception:
            return False, 0.0
