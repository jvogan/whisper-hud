"""Tests for audio recording functionality."""

import pytest
from unittest.mock import patch
import numpy as np


class TestAudioRecorder:
    """Tests for AudioRecorder class."""

    def test_recorder_initialization(self):
        """Test recorder initializes with correct defaults."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()

            assert recorder.sample_rate == 16000
            assert recorder.channels == 1
            assert recorder.recording is False
            assert recorder.audio_data == []

    def test_recorder_not_recording_initially(self):
        """Test recorder is not recording when created."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            assert recorder.is_recording() is False

    def test_silence_settings(self):
        """Test configuring silence detection."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            recorder.set_silence_settings(
                enabled=True,
                silence_duration=2.0,
                silence_threshold=0.02
            )

            assert recorder._silence_duration == 2.0
            assert recorder._silence_threshold == 0.02

    def test_silence_settings_disabled(self):
        """Test disabling silence detection."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            recorder.set_silence_settings(enabled=False)

            assert recorder._silence_duration == float('inf')

    def test_get_duration_empty(self):
        """Test duration is 0 when no audio recorded."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            assert recorder.get_duration() == 0.0

    def test_get_duration_with_audio(self):
        """Test duration calculation with recorded audio."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder(sample_rate=16000)
            # Simulate 1 second of audio (16000 samples)
            recorder.audio_data = [np.zeros((16000, 1), dtype=np.float32)]

            duration = recorder.get_duration()
            assert abs(duration - 1.0) < 0.01  # ~1 second

    def test_audio_level_initial(self):
        """Test initial audio level is 0."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            assert recorder.get_audio_level() == 0.0
            assert recorder.get_peak_level() == 0.0

    def test_speech_detected_initial(self):
        """Test speech not detected initially."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            assert recorder.speech_detected() is False

    def test_stop_without_start_returns_empty(self):
        """Test stopping without starting returns empty bytes."""
        with patch('sounddevice.InputStream'):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            result = recorder.stop()

            assert result == b''

    def test_start_failure_rolls_back_state(self):
        """Test that start() rolls back if InputStream fails."""
        with patch('sounddevice.InputStream', side_effect=Exception("boom")):
            from whisper_hud.recorder import AudioRecorder

            recorder = AudioRecorder()
            with pytest.raises(Exception):
                recorder.start()

            assert recorder.recording is False
            assert recorder._stream is None

    def test_start_emits_live_audio_chunks(self):
        """Recorder should forward chunks to the optional live callback."""

        class FakeInputStream:
            last_instance = None

            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                FakeInputStream.last_instance = self

            def start(self):
                return None

            def stop(self):
                return None

            def close(self):
                return None

        with patch('sounddevice.InputStream', FakeInputStream):
            with patch('whisper_hud.recorder.is_valid_input_device', return_value=True):
                from whisper_hud.recorder import AudioRecorder

                recorder = AudioRecorder(sample_rate=16000)
                chunks = []
                recorder.start(on_audio_chunk=lambda chunk, rate: chunks.append((chunk.copy(), rate)))

                audio_chunk = np.ones((256, 1), dtype=np.float32) * 0.25
                FakeInputStream.last_instance.callback(audio_chunk, 256, None, None)
                recorder.stop()

                assert len(chunks) == 1
                np.testing.assert_allclose(chunks[0][0], audio_chunk)
                assert chunks[0][1] == 16000


class TestInputDevices:
    """Tests for input device discovery."""

    @patch('sounddevice.query_devices')
    def test_get_input_devices(self, mock_query):
        """Test getting list of input devices."""
        mock_query.return_value = [
            {'name': 'Built-in Microphone', 'max_input_channels': 2, 'default_samplerate': 44100},
            {'name': 'USB Headset', 'max_input_channels': 1, 'default_samplerate': 48000},
            {'name': 'Speakers', 'max_input_channels': 0, 'default_samplerate': 44100},  # Output only
        ]

        from whisper_hud.recorder import get_input_devices

        devices = get_input_devices()

        assert len(devices) == 2  # Only input devices
        assert devices[0]['name'] == 'Built-in Microphone'
        assert devices[1]['name'] == 'USB Headset'

    @patch('sounddevice.query_devices')
    def test_get_input_devices_empty(self, mock_query):
        """Test handling no input devices."""
        mock_query.return_value = []

        from whisper_hud.recorder import get_input_devices

        devices = get_input_devices()
        assert devices == []
