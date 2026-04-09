"""
Audio recording module using sounddevice.

Records from the default microphone and outputs WAV bytes
suitable for API upload to OpenAI or Gemini.

Includes silence detection for auto-stop functionality.
"""

import io
import logging
import threading
import time
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from .logging_config import get_logger

logger = get_logger("recorder")


class AudioRecorder:
    """
    Records audio from the microphone with optional silence detection.

    Usage:
        recorder = AudioRecorder()
        recorder.start(on_silence=lambda: logger.debug("Silence detected!"))
        # ... user speaks ...
        audio_bytes = recorder.stop()  # Returns WAV bytes

    Silence detection:
        - Waits for speech to start (audio above threshold)
        - After speech detected, monitors for silence
        - Triggers callback after silence_duration seconds of quiet
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1, device: Optional[int] = None):
        """
        Initialize recorder.

        Args:
            sample_rate: 16000 Hz is optimal for speech (Whisper expects this)
            channels: 1 for mono (required by most speech APIs)
            device: Audio input device ID (None = system default)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.recording = False
        self.audio_data: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

        # Silence detection settings (tuned for typical MacBook microphones)
        # Real mic RMS during speech is typically 0.005-0.03, ambient noise 0.002-0.004
        self._silence_threshold = 0.002  # RMS threshold for "silence" (below ambient noise)
        self._speech_threshold = 0.004  # RMS threshold to confirm speech started
        self._silence_duration = 1.5  # Seconds of silence before auto-stop
        self._min_recording_duration = 0.3  # Minimum recording before silence detection

        # Silence detection state
        self._speech_detected = False
        self._silence_start: Optional[float] = None
        self._on_silence: Optional[Callable[[], None]] = None
        self._on_audio_chunk: Optional[Callable[[np.ndarray, int], None]] = None
        self._silence_triggered = False

        # Audio level monitoring
        self._current_level: float = 0.0  # Current RMS level (0.0 - 1.0)
        self._peak_level: float = 0.0  # Peak level during recording
        self._level_lock = threading.Lock()

    def set_silence_settings(
        self, enabled: bool = True, silence_duration: float = 1.5, silence_threshold: float = 0.01
    ):
        """
        Configure silence detection.

        Args:
            enabled: Whether to use silence detection
            silence_duration: Seconds of silence before triggering callback
            silence_threshold: Audio level below this is considered silence
        """
        self._silence_duration = silence_duration if enabled else float("inf")
        self._silence_threshold = silence_threshold
        # Set speech threshold slightly above silence threshold for reliable detection
        self._speech_threshold = silence_threshold * 1.5

    def start(
        self,
        on_silence: Optional[Callable[[], None]] = None,
        on_audio_chunk: Optional[Callable[[np.ndarray, int], None]] = None,
    ) -> None:
        """
        Start recording.

        Args:
            on_silence: Optional callback when silence is detected after speech.
                        If provided, enables auto-stop on silence.
            on_audio_chunk: Optional callback for live audio chunk delivery.
        """
        with self._lock:
            if self.recording:
                return

            # Validate device is actually an input device
            if not is_valid_input_device(self.device):
                device_name = get_device_name(self.device)
                logger.warning(
                    f"Device {self.device} ({device_name}) is not a valid input device. "
                    "Falling back to system default."
                )
                self.device = None

            # Log the device being used
            device_name = get_device_name(self.device)
            logger.info(f"Starting recording with device: {device_name} (ID: {self.device})")

            self.audio_data = []
            self._speech_detected = False
            self._silence_start = None
            self._on_silence = on_silence
            self._on_audio_chunk = on_audio_chunk
            self._silence_triggered = False
            self._recording_start = time.time()
            self._current_level = 0.0
            self._peak_level = 0.0
            self._low_audio_warned = False  # Reset low audio warning
            self._speech_peak_rms = 0.0  # Track peak speech level for relative silence detection

            def callback(indata, frames, time_info, status):
                if status:
                    logger.debug(f"Audio status: {status}")
                if not self.recording:
                    return

                self.audio_data.append(indata.copy())

                if self._on_audio_chunk:
                    try:
                        self._on_audio_chunk(indata.copy(), self.sample_rate)
                    except Exception:
                        logger.debug("Live audio chunk callback failed", exc_info=True)

                # Calculate RMS level for monitoring
                rms = float(np.sqrt(np.mean(indata**2)))
                # Normalize to 0-1 range - use higher multiplier for better visibility
                # Typical quiet speech is 0.01-0.05 RMS, normal speech 0.05-0.15
                normalized_level = min(1.0, rms * 25)

                with self._level_lock:
                    self._current_level = normalized_level
                    self._peak_level = max(self._peak_level, normalized_level)

                # Silence detection logic
                if self._on_silence and not self._silence_triggered:
                    self._check_silence(indata)

            # Try to start the stream, with retry on device errors
            max_retries = 2
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    # On retry, always use system default (handles device changes)
                    device_to_use = None if attempt > 0 else self.device

                    if attempt > 0:
                        logger.info(f"Retry {attempt}: Using system default device after error")
                        # Small delay to let audio system settle after device change
                        import time as time_module

                        time_module.sleep(0.2)

                    self._stream = sd.InputStream(
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        dtype=np.float32,
                        callback=callback,
                        blocksize=1024,
                        device=device_to_use,
                    )
                    self._stream.start()
                    self.recording = True

                    # Success - update device if we fell back
                    if attempt > 0:
                        self.device = None
                        logger.info("Successfully started with system default device")
                    break

                except Exception as e:
                    last_error = e
                    if self._stream:
                        try:
                            self._stream.stop()
                            self._stream.close()
                        except Exception:
                            pass
                        self._stream = None

                    if attempt < max_retries:
                        logger.warning(f"Audio device error (attempt {attempt + 1}): {e}")
                        continue

                    # All retries failed
                    self.recording = False
                    self._on_silence = None
                    self._silence_triggered = False
                    self.audio_data = []
                    logger.exception("Failed to start audio recording after retries")
                    raise last_error

    def _check_silence(self, audio_chunk: np.ndarray):
        """Check audio chunk for silence and trigger callback if needed."""
        # Calculate RMS (root mean square) as volume level
        rms = np.sqrt(np.mean(audio_chunk**2))
        debug_enabled = logger.isEnabledFor(logging.DEBUG)

        current_time = time.time()
        recording_duration = current_time - self._recording_start

        # Track peak speech RMS for relative silence detection
        if not hasattr(self, "_speech_peak_rms"):
            self._speech_peak_rms = 0.0

        # Debug logging every ~0.5 seconds
        if int(recording_duration * 2) != getattr(self, "_last_debug_time", -1):
            self._last_debug_time = int(recording_duration * 2)
            if debug_enabled:
                relative_thresh = self._speech_peak_rms * 0.3 if self._speech_detected else 0
                logger.debug(
                    f"Audio RMS: {rms:.4f}, peak: {self._speech_peak_rms:.4f}, "
                    f"rel_thresh: {relative_thresh:.4f}, speech_detected: {self._speech_detected}"
                )

            # Warn if audio levels are suspiciously low after some recording time
            if recording_duration > 2.0 and not self._speech_detected:
                with self._level_lock:
                    peak = self._peak_level
                if peak < 0.02 and not getattr(self, "_low_audio_warned", False):
                    self._low_audio_warned = True
                    logger.warning(
                        f"Audio levels very low (peak: {peak:.4f}). "
                        "Check microphone selection and system permissions."
                    )

        # Don't check for silence too early
        if recording_duration < self._min_recording_duration:
            return

        # First, detect if speech has started (use absolute threshold)
        if not self._speech_detected:
            if rms > self._speech_threshold:
                self._speech_detected = True
                self._speech_peak_rms = rms
                self._silence_start = None
                if debug_enabled:
                    logger.debug(f"Speech detected! RMS: {rms:.4f}")
            return

        # Track peak speech level (with decay to adapt to volume changes)
        if rms > self._speech_peak_rms:
            self._speech_peak_rms = rms
        else:
            # Slow decay to adapt to lower speech volumes
            self._speech_peak_rms = self._speech_peak_rms * 0.995

        # Use RELATIVE silence detection: silence = RMS below 30% of peak speech
        # This adapts to microphone characteristics and ambient noise
        relative_silence_threshold = max(self._silence_threshold, self._speech_peak_rms * 0.3)

        if rms < relative_silence_threshold:
            # Audio is quiet
            if self._silence_start is None:
                self._silence_start = current_time
            elif current_time - self._silence_start >= self._silence_duration:
                # Silence duration exceeded - trigger callback
                self._silence_triggered = True
                if self._on_silence:
                    # Call in separate thread to avoid blocking audio
                    threading.Thread(target=self._on_silence, daemon=True).start()
        else:
            # Audio is loud again, reset silence timer
            self._silence_start = None

    def stop(self) -> bytes:
        """
        Stop recording and return WAV bytes.

        Returns:
            bytes: WAV file contents ready for API upload
        """
        with self._lock:
            self.recording = False
            self._on_silence = None
            self._on_audio_chunk = None

            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    logger.debug("Failed to stop audio stream cleanly", exc_info=True)
                finally:
                    self._stream = None

            audio_chunks = self.audio_data
            self.audio_data = []

            if not audio_chunks:
                return b""

            # Concatenate all recorded chunks
            audio = np.concatenate(audio_chunks, axis=0)

            # Trim silence from end if we auto-stopped
            if self._silence_triggered:
                # Remove the trailing silence (keep a tiny bit for natural sound)
                samples_to_trim = int(self._silence_duration * 0.8 * self.sample_rate)
                if len(audio) > samples_to_trim:
                    audio = audio[:-samples_to_trim]

            # Convert to 16-bit PCM
            audio_int16 = (audio * 32767).astype(np.int16)

            # Write to WAV bytes
            buffer = io.BytesIO()
            wavfile.write(buffer, self.sample_rate, audio_int16)
            buffer.seek(0)
            return buffer.read()

    def get_duration(self) -> float:
        """Return current recording duration in seconds."""
        if not self.audio_data:
            return 0.0
        total_samples = sum(chunk.shape[0] for chunk in self.audio_data)
        return total_samples / self.sample_rate

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self.recording

    def set_device(self, device: Optional[int]) -> None:
        """Set the audio input device."""
        self.device = device

    def speech_detected(self) -> bool:
        """Check if speech has been detected in current recording."""
        return self._speech_detected

    def get_audio_level(self) -> float:
        """
        Get current audio input level.

        Returns:
            Normalized level from 0.0 (silence) to 1.0 (loud)
        """
        with self._level_lock:
            return self._current_level

    def get_peak_level(self) -> float:
        """
        Get peak audio level during current recording.

        Returns:
            Normalized peak level from 0.0 to 1.0
        """
        with self._level_lock:
            return self._peak_level


def get_input_devices() -> list[dict]:
    """Get list of available input devices."""
    devices = sd.query_devices()
    input_devices = []
    for i, device in enumerate(devices):
        if device["max_input_channels"] > 0:
            input_devices.append(
                {
                    "id": i,
                    "name": device["name"],
                    "channels": device["max_input_channels"],
                    "sample_rate": device["default_samplerate"],
                }
            )
    return input_devices


def is_valid_input_device(device_id: Optional[int]) -> bool:
    """
    Check if the given device ID is a valid audio input device.

    Args:
        device_id: Device ID to validate. None means system default.

    Returns:
        True if device is a valid input device or None (system default)
    """
    if device_id is None:
        return True  # System default is always valid

    try:
        devices = sd.query_devices()
        if device_id < 0 or device_id >= len(devices):
            return False
        device = devices[device_id]
        return device["max_input_channels"] > 0
    except Exception:
        return False


def get_device_name(device_id: Optional[int]) -> str:
    """
    Get the name of an audio device by ID.

    Args:
        device_id: Device ID. None returns "System Default".

    Returns:
        Device name string
    """
    if device_id is None:
        return "System Default"

    try:
        devices = sd.query_devices()
        if 0 <= device_id < len(devices):
            return devices[device_id]["name"]
    except Exception:
        pass
    return f"Unknown Device ({device_id})"
