"""
Audio recording module using sounddevice.

Records from the default microphone and outputs WAV bytes
suitable for API upload to OpenAI or Gemini.

Includes silence detection for auto-stop functionality.
"""

import sounddevice as sd
import numpy as np
from scipy.io import wavfile
import io
import threading
import time
from typing import Optional, Callable


class AudioRecorder:
    """
    Records audio from the microphone with optional silence detection.

    Usage:
        recorder = AudioRecorder()
        recorder.start(on_silence=lambda: print("Silence detected!"))
        # ... user speaks ...
        audio_bytes = recorder.stop()  # Returns WAV bytes

    Silence detection:
        - Waits for speech to start (audio above threshold)
        - After speech detected, monitors for silence
        - Triggers callback after silence_duration seconds of quiet
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        """
        Initialize recorder.

        Args:
            sample_rate: 16000 Hz is optimal for speech (Whisper expects this)
            channels: 1 for mono (required by most speech APIs)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.recording = False
        self.audio_data: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

        # Silence detection settings
        self._silence_threshold = 0.01  # RMS threshold for "silence"
        self._speech_threshold = 0.02   # RMS threshold to confirm speech started
        self._silence_duration = 1.5    # Seconds of silence before auto-stop
        self._min_recording_duration = 0.5  # Minimum recording before silence detection

        # Silence detection state
        self._speech_detected = False
        self._silence_start: Optional[float] = None
        self._on_silence: Optional[Callable[[], None]] = None
        self._silence_triggered = False

    def set_silence_settings(
        self,
        enabled: bool = True,
        silence_duration: float = 1.5,
        silence_threshold: float = 0.01
    ):
        """
        Configure silence detection.

        Args:
            enabled: Whether to use silence detection
            silence_duration: Seconds of silence before triggering callback
            silence_threshold: Audio level below this is considered silence
        """
        self._silence_duration = silence_duration if enabled else float('inf')
        self._silence_threshold = silence_threshold

    def start(self, on_silence: Optional[Callable[[], None]] = None) -> None:
        """
        Start recording.

        Args:
            on_silence: Optional callback when silence is detected after speech.
                        If provided, enables auto-stop on silence.
        """
        with self._lock:
            if self.recording:
                return

            self.audio_data = []
            self.recording = True
            self._speech_detected = False
            self._silence_start = None
            self._on_silence = on_silence
            self._silence_triggered = False
            self._recording_start = time.time()

            def callback(indata, frames, time_info, status):
                if status:
                    print(f"Audio status: {status}")
                if not self.recording:
                    return

                self.audio_data.append(indata.copy())

                # Silence detection logic
                if self._on_silence and not self._silence_triggered:
                    self._check_silence(indata)

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                callback=callback,
                blocksize=1024
            )
            self._stream.start()

    def _check_silence(self, audio_chunk: np.ndarray):
        """Check audio chunk for silence and trigger callback if needed."""
        # Calculate RMS (root mean square) as volume level
        rms = np.sqrt(np.mean(audio_chunk ** 2))

        current_time = time.time()
        recording_duration = current_time - self._recording_start

        # Don't check for silence too early
        if recording_duration < self._min_recording_duration:
            return

        # First, detect if speech has started
        if not self._speech_detected:
            if rms > self._speech_threshold:
                self._speech_detected = True
                self._silence_start = None
            return

        # Speech was detected, now monitor for silence
        if rms < self._silence_threshold:
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

            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

            if not self.audio_data:
                return b''

            # Concatenate all recorded chunks
            audio = np.concatenate(self.audio_data, axis=0)

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

    def speech_detected(self) -> bool:
        """Check if speech has been detected in current recording."""
        return self._speech_detected


def get_input_devices() -> list[dict]:
    """Get list of available input devices."""
    devices = sd.query_devices()
    input_devices = []
    for i, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            input_devices.append({
                'id': i,
                'name': device['name'],
                'channels': device['max_input_channels'],
                'sample_rate': device['default_samplerate']
            })
    return input_devices
