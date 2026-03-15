"""Pytest configuration and fixtures for WhisperHUD tests."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Ensure the package directory is importable without an editable install
_PKG_ROOT = Path(__file__).resolve().parent.parent / "whisper-hud"
if _PKG_ROOT.exists() and str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for config files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config(temp_config_dir):
    """Create a mock config with temporary storage."""
    config_file = temp_config_dir / "config.json"

    with patch("whisper_hud.config.CONFIG_FILE", config_file):
        with patch("whisper_hud.config.CONFIG_DIR", temp_config_dir):
            from whisper_hud.config import Config

            yield Config()


@pytest.fixture(autouse=True)
def _block_real_keychain():
    """Auto-mock keyring globally to prevent macOS Keychain access popups."""
    with patch("keyring.get_password", return_value=None):
        with patch("keyring.set_password", return_value=None):
            with patch("keyring.delete_password", return_value=None):
                yield


@pytest.fixture
def mock_keychain():
    """Mock keychain operations with accessible mock objects for assertions."""
    with patch("keyring.get_password") as mock_get:
        with patch("keyring.set_password") as mock_set:
            with patch("keyring.delete_password") as mock_delete:
                mock_get.return_value = None
                mock_set.return_value = None
                mock_delete.return_value = None
                yield {"get": mock_get, "set": mock_set, "delete": mock_delete}


@pytest.fixture
def mock_appkit():
    """Mock AppKit imports for testing without PyObjC."""
    mock_ns = MagicMock()
    with patch.dict(
        "sys.modules",
        {
            "AppKit": mock_ns,
            "Quartz": mock_ns,
            "PyObjCTools": mock_ns,
            "PyObjCTools.AppHelper": mock_ns,
        },
    ):
        yield mock_ns


@pytest.fixture
def sample_audio_bytes():
    """Generate sample WAV audio bytes for testing."""
    import struct
    import io

    # Simple WAV header + silence
    sample_rate = 16000
    duration = 0.5  # seconds
    num_samples = int(sample_rate * duration)

    buffer = io.BytesIO()

    # WAV header
    buffer.write(b"RIFF")
    buffer.write(struct.pack("<I", 36 + num_samples * 2))
    buffer.write(b"WAVE")
    buffer.write(b"fmt ")
    buffer.write(struct.pack("<I", 16))  # Subchunk1Size
    buffer.write(struct.pack("<H", 1))  # AudioFormat (PCM)
    buffer.write(struct.pack("<H", 1))  # NumChannels
    buffer.write(struct.pack("<I", sample_rate))
    buffer.write(struct.pack("<I", sample_rate * 2))  # ByteRate
    buffer.write(struct.pack("<H", 2))  # BlockAlign
    buffer.write(struct.pack("<H", 16))  # BitsPerSample
    buffer.write(b"data")
    buffer.write(struct.pack("<I", num_samples * 2))

    # Silent audio data
    for _ in range(num_samples):
        buffer.write(struct.pack("<h", 0))

    buffer.seek(0)
    return buffer.read()
