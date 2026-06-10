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
import math
import os
import threading
import time
import platform
from collections import deque
from pathlib import Path
from typing import Optional, Callable, Any, Sequence

import numpy as np
from scipy.signal import resample_poly

from .base import LiveTranscriptionSession, TranscriptionProvider, TranscriptionResult
from ..logging_config import get_logger

logger = get_logger("providers.parakeet")

# Model cache directory
CACHE_DIR = Path.home() / ".cache" / "whisper-hud" / "parakeet"

# Hugging Face organization hosting the MLX-converted Parakeet weights.
# parakeet_mlx.from_pretrained loads ``config.json`` + ``model.safetensors`` from
# this repo; the original ``nvidia/`` repos only ship NeMo ``.nemo`` checkpoints
# which parakeet_mlx cannot load directly.
HF_ORG = "mlx-community"

# Parakeet models run at 16 kHz mono (their preprocessor expects this rate).
PARAKEET_SAMPLE_RATE = 16000


class ParakeetProvider(TranscriptionProvider):
    """Transcription provider using Parakeet MLX for Apple Silicon."""

    name = "parakeet"
    display_name = "Parakeet (Apple Silicon)"

    # Default model. v3 is multilingual-safe (25 European languages) so it stays
    # the default; v2 is English-only but slightly more accurate for English.
    DEFAULT_MODEL = "parakeet-tdt-0.6b-v3"

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
            "name": "Parakeet 0.6B v2 (English)",
            "size_mb": 600,
            "description": "Fastest + most accurate for English (English only)",
            "languages": "en",
            "recommended": False,
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

    def __init__(self, model: str = DEFAULT_MODEL):
        """
        Initialize Parakeet provider.

        Args:
            model: Model to use
        """
        if model not in self.MODELS:
            model = self.DEFAULT_MODEL
        self.model = model
        self._parakeet_model = None
        self._available = None

    @staticmethod
    def _hf_repo_id(model_id: str) -> str:
        """Resolve the Hugging Face repo id parakeet_mlx actually loads.

        parakeet_mlx.from_pretrained downloads ``config.json`` and
        ``model.safetensors`` straight from this repo id, so cache checks and
        downloads must use the same id.
        """
        return f"{HF_ORG}/{model_id}"

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

            model_name = self._hf_repo_id(self.model)
            # Check if any model files are cached
            cached = try_to_load_from_cache(model_name, "config.json")
            return cached is not None
        except Exception:
            return False

    def _load_model(self):
        """Load and cache the Parakeet model used for batch transcription.

        parakeet-mlx 0.5.x exposes neither a module-level ``load_model`` nor a
        module-level ``transcribe``; the supported entry point is
        ``from_pretrained(repo_id)``, which returns a model object exposing
        ``.transcribe(audio_path)``. We resolve the same HF repo id the
        streaming path uses. A defensive fallback to the legacy ``load_model``
        symbol is kept (only when it exists) so older installs keep working.
        """
        if self._parakeet_model is None:
            try:
                import parakeet_mlx
            except ImportError:
                raise RuntimeError("parakeet-mlx not installed. " "Install with: pip install parakeet-mlx")

            try:
                from_pretrained = getattr(parakeet_mlx, "from_pretrained", None)
                if from_pretrained is not None:
                    self._parakeet_model = from_pretrained(self._hf_repo_id(self.model))
                else:
                    # Compatibility path for older/mocked APIs exposing load_model().
                    load_model = getattr(parakeet_mlx, "load_model", None)
                    if load_model is None:
                        raise RuntimeError("parakeet_mlx exposes neither from_pretrained nor load_model")
                    self._parakeet_model = load_model(self.model)
            except Exception as e:
                raise RuntimeError(f"Failed to load Parakeet model: {e}")

        return self._parakeet_model

    @staticmethod
    def _extract_text(result: Any) -> str:
        """Pull transcript text out of a parakeet-mlx result object or dict."""
        if isinstance(result, dict):
            return result.get("text", "")
        text = getattr(result, "text", None)
        if text is not None:
            return text
        return str(result)

    def transcribe(self, audio_bytes: bytes, vocabulary: Optional[Sequence[str]] = None) -> TranscriptionResult:
        """
        Transcribe audio using Parakeet MLX.

        Args:
            audio_bytes: WAV file contents
            vocabulary: Accepted for interface compatibility and IGNORED.
                parakeet-mlx provides no vocabulary/biasing mechanism, so user
                vocabulary cannot be applied here.

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
            raise RuntimeError("parakeet-mlx is not installed. " "Install with: pip install parakeet-mlx")

        try:
            from ..encryption import create_private_temp_file, secure_delete

            # parakeet-mlx 0.5.x transcribes from a file path via the loaded
            # model object (model.transcribe(path)); write audio to a private
            # scratch file and securely delete it afterwards.
            model = self._load_model()
            temp_path = create_private_temp_file(audio_bytes)

            try:
                result = model.transcribe(temp_path)
                text = self._extract_text(result)
            finally:
                # Securely delete temp file (overwrite before unlink)
                secure_delete(temp_path)

            duration = time.time() - start_time

            return TranscriptionResult(
                text=text.strip(),
                duration_seconds=duration,
                cost_estimate=0.0,  # Free - local processing
                provider=self.name,
                model=self.model,
                language=None,  # Parakeet doesn't always return detected language
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

    def _is_specific_model_downloaded(self, model_id: str) -> bool:
        """Check if a specific model is downloaded."""
        try:
            from huggingface_hub import try_to_load_from_cache

            model_name = self._hf_repo_id(model_id)
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

    def download_model(self, progress_callback: Optional[Callable[[str, float], None]] = None) -> bool:
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

            model_name = self._hf_repo_id(self.model)
            model_config = self.MODELS[self.model]

            if progress_callback:
                progress_callback(f"Downloading {model_config['name']} ({model_config['size_mb']}MB)...", 0.0)

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

    def supports_live_input(self) -> bool:
        """Live mic dictation is available once the model is fully set up.

        Requires Apple Silicon, an installed parakeet_mlx, and a downloaded
        model. When any prerequisite is missing the manager degrades to batch.
        """
        return self.is_configured()

    def _load_streaming_model(self):
        """Load the model object used for streaming inference.

        Uses ``parakeet_mlx.from_pretrained`` with the resolved HF repo id, which
        returns a model exposing ``transcribe_stream``. Falls back to the
        package-level ``load_model`` helper when present (used by tests).
        """
        import parakeet_mlx

        from_pretrained = getattr(parakeet_mlx, "from_pretrained", None)
        if from_pretrained is not None:
            return from_pretrained(self._hf_repo_id(self.model))

        # Compatibility path for older/mocked APIs exposing load_model().
        load_model = getattr(parakeet_mlx, "load_model", None)
        if load_model is not None:
            return load_model(self.model)

        raise RuntimeError("parakeet_mlx exposes neither from_pretrained nor load_model")

    def create_live_session(
        self,
        *,
        on_partial: Callable[[str], None],
        on_final: Callable[[TranscriptionResult], None],
        on_error: Callable[[Exception], None],
        on_ready: Optional[Callable[[], None]] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> LiveTranscriptionSession:
        """Create a local live transcription session backed by parakeet_mlx."""
        if not self.supports_live_input():
            raise RuntimeError(
                "Parakeet live transcription is unavailable. "
                "Requires Apple Silicon, parakeet-mlx, and a downloaded model."
            )

        return ParakeetLiveSession(
            model_loader=self._load_streaming_model,
            provider_name=self.name,
            model_id=self.model,
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error,
            on_ready=on_ready,
            language=language,
        )

    def transcribe_streaming(
        self,
        audio_bytes: bytes,
        on_chunk: Callable[[str], None],
        vocabulary: Optional[Sequence[str]] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio with streaming output.

        Args:
            audio_bytes: WAV file contents
            on_chunk: Callback called with cumulative text
            vocabulary: Accepted for interface compatibility and IGNORED;
                parakeet-mlx has no vocabulary/biasing mechanism.

        Returns:
            TranscriptionResult with final text
        """
        start_time = time.time()

        if not self._is_apple_silicon():
            raise RuntimeError("Parakeet requires Apple Silicon")

        try:
            from ..encryption import create_private_temp_file, secure_delete

            # parakeet-mlx 0.5.x: transcribe from a file path via the loaded
            # model object. The batch result is produced in one shot, so we emit
            # word-level cumulative chunks when timestamps are available and fall
            # back to a single full-text chunk otherwise.
            model = self._load_model()
            temp_path = create_private_temp_file(audio_bytes)

            try:
                result = model.transcribe(temp_path)
                text = self._extract_text(result)
                words = self._extract_words(result)

                if words:
                    cumulative = ""
                    for word in words:
                        cumulative += word + " "
                        on_chunk(cumulative.strip())
                elif text:
                    on_chunk(text)

            finally:
                # Securely delete temp file
                secure_delete(temp_path)

            duration = time.time() - start_time

            return TranscriptionResult(
                text=text.strip(),
                duration_seconds=duration,
                cost_estimate=0.0,
                provider=self.name,
                model=self.model,
                language=None,
            )

        except Exception as e:
            raise RuntimeError(f"Parakeet streaming transcription failed: {e}")

    @staticmethod
    def _extract_words(result: Any) -> list[str]:
        """Return per-word tokens from a parakeet-mlx result, if present.

        Supports both the legacy dict shape (``{"words": [...]}``) and result
        objects exposing word-level ``tokens`` (each with ``.text``). Returns an
        empty list when no word-level breakdown is available, in which case the
        caller emits the full transcript as a single chunk.
        """
        if isinstance(result, dict):
            raw_words = result.get("words", []) or []
            words: list[str] = []
            for word_info in raw_words:
                if isinstance(word_info, dict):
                    words.append(str(word_info.get("word", "")).strip())
                else:
                    words.append(str(word_info).strip())
            return [w for w in words if w]

        tokens = getattr(result, "tokens", None)
        if tokens:
            words = []
            for token in tokens:
                token_text = getattr(token, "text", None)
                if token_text is None and isinstance(token, dict):
                    token_text = token.get("text")
                if token_text:
                    words.append(str(token_text).strip())
            return [w for w in words if w]

        return []

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


class ParakeetLiveSession(LiveTranscriptionSession):
    """Local live dictation session backed by parakeet_mlx streaming inference.

    Wraps ``model.transcribe_stream(...)`` (a ``StreamingParakeet`` context
    manager). A single background thread owns the streaming context: it loads
    the model, enters the context, then drains microphone chunks fed via
    ``push_audio`` and emits incremental partial transcripts. Inference never
    runs on the caller's thread, so ``push_audio`` never blocks.
    """

    # Local streaming attention context window (left, right) feature frames.
    CONTEXT_SIZE = (256, 256)
    DEPTH = 1
    # How long the worker waits for new audio before re-checking stop/close.
    QUEUE_POLL_SECONDS = 0.1

    def __init__(
        self,
        *,
        model_loader: Callable[[], Any],
        provider_name: str,
        model_id: str,
        on_partial: Callable[[str], None],
        on_final: Callable[[TranscriptionResult], None],
        on_error: Callable[[Exception], None],
        on_ready: Optional[Callable[[], None]] = None,
        language: Optional[str] = None,
    ) -> None:
        self._model_loader = model_loader
        self._provider_name = provider_name
        self._model_id = model_id
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._on_ready = on_ready
        self._language = language

        self._thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self._audio_available = threading.Event()
        self._pending_audio: deque[np.ndarray] = deque()

        self._ready = threading.Event()
        self._finalize_requested = threading.Event()
        self._closed = threading.Event()

        self._final_sent = False
        self._error_sent = False
        self._audio_seconds = 0.0

    def start(self) -> None:
        """Start the background streaming worker."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def is_ready(self) -> bool:
        """Return True once the model is loaded and streaming has begun."""
        return self._ready.is_set()

    def push_audio(self, audio_chunk: Any, sample_rate: int) -> None:
        """Queue a chunk of microphone audio (non-blocking)."""
        if self._closed.is_set() or self._finalize_requested.is_set():
            return

        samples = self._prepare_audio_chunk(audio_chunk, sample_rate)
        if samples is None or samples.size == 0:
            return

        with self._state_lock:
            self._pending_audio.append(samples)
            self._audio_seconds += len(samples) / float(PARAKEET_SAMPLE_RATE)
        self._audio_available.set()

    def request_stop(self) -> None:
        """Stop accepting audio and finalize the current turn."""
        self._finalize_requested.set()
        # Wake the worker so it can drain remaining audio and finalize.
        self._audio_available.set()

    def close(self) -> None:
        """Close the session and release the streaming context.

        A bare ``close()`` (without a prior ``request_stop()``) aborts the turn:
        the worker exits without emitting a final transcript.
        """
        if self._closed.is_set():
            return
        self._closed.set()
        self._audio_available.set()

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    # -- worker -----------------------------------------------------------

    def _run(self) -> None:
        """Own the streaming context for the lifetime of the turn."""
        try:
            model = self._model_loader()
            stream_cm = model.transcribe_stream(
                context_size=self.CONTEXT_SIZE,
                depth=self.DEPTH,
            )
            with stream_cm as stream:
                self._ready.set()
                logger.debug("Parakeet live session ready (model=%s)", self._model_id)
                if self._on_ready:
                    self._on_ready()

                self._stream_loop(stream)
                self._finalize(stream)
        except Exception as e:
            logger.debug("Parakeet live session failed", exc_info=True)
            self._notify_error(RuntimeError(f"Parakeet live transcription failed: {e}"))

    def _stream_loop(self, stream: Any) -> None:
        """Consume queued audio until finalize is requested or the session closes."""
        while not self._closed.is_set():
            chunk = self._next_chunk()
            if chunk is None:
                # Queue is empty: finalize once stop was requested, otherwise
                # wait briefly for more audio (or for stop/close).
                if self._finalize_requested.is_set():
                    return
                self._audio_available.wait(timeout=self.QUEUE_POLL_SECONDS)
                self._audio_available.clear()
                continue

            self._feed_chunk(stream, chunk)
            if not self._closed.is_set():
                self._emit_partial(stream)

    def _finalize(self, stream: Any) -> None:
        """Emit the final transcript exactly once after a graceful stop.

        A bare close (abort) leaves ``_finalize_requested`` unset, so no final
        transcript is delivered for discarded turns.
        """
        if not self._finalize_requested.is_set():
            return

        with self._state_lock:
            if self._final_sent or self._error_sent:
                return
            self._final_sent = True

        text = self._read_text(stream)
        with self._state_lock:
            duration = self._audio_seconds
        self._on_final(
            TranscriptionResult(
                text=text,
                duration_seconds=duration,
                cost_estimate=0.0,  # Free — local processing.
                provider=self._provider_name,
                model=self._model_id,
                language=self._language,
            )
        )

    def _next_chunk(self) -> Optional[np.ndarray]:
        """Pop the next queued audio chunk, if any."""
        with self._state_lock:
            if self._pending_audio:
                return self._pending_audio.popleft()
        return None

    def _feed_chunk(self, stream: Any, chunk: np.ndarray) -> None:
        """Convert a numpy chunk to an mlx array and feed it to the stream."""
        import mlx.core as mx

        stream.add_audio(mx.array(chunk))

    def _emit_partial(self, stream: Any) -> None:
        """Read the current transcript and emit it as a partial update."""
        text = self._read_text(stream)
        if text:
            self._on_partial(text)

    @staticmethod
    def _read_text(stream: Any) -> str:
        """Read the (stripped) transcript text from a StreamingParakeet."""
        result = stream.result
        text = getattr(result, "text", None)
        if text is None:
            text = str(result)
        return text.strip()

    def _notify_error(self, error: Exception) -> None:
        """Emit the first terminal error to the app."""
        with self._state_lock:
            if self._error_sent or self._final_sent:
                return
            self._error_sent = True
        self._on_error(error)

    @staticmethod
    def _prepare_audio_chunk(audio_chunk: Any, sample_rate: int) -> Optional[np.ndarray]:
        """Convert recorder audio to 1D float32 mono at Parakeet's sample rate."""
        if audio_chunk is None or sample_rate <= 0:
            return None

        chunk = np.asarray(audio_chunk, dtype=np.float32)
        if chunk.size == 0:
            return None

        if chunk.ndim == 2:
            mono = chunk.mean(axis=1)
        else:
            mono = chunk.reshape(-1)

        mono = np.clip(mono, -1.0, 1.0)

        if sample_rate != PARAKEET_SAMPLE_RATE:
            gcd = math.gcd(int(sample_rate), PARAKEET_SAMPLE_RATE)
            up = PARAKEET_SAMPLE_RATE // gcd
            down = int(sample_rate) // gcd
            mono = resample_poly(mono, up, down).astype(np.float32)

        return np.ascontiguousarray(mono, dtype=np.float32)
