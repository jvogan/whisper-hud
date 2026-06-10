"""Tests for the picker-free file-transcription logic."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from whisper_hud.file_transcription import (
    ALLOWED_AUDIO_EXTENSIONS,
    FileTranscriptionError,
    build_afconvert_command,
    build_afinfo_command,
    file_extension,
    format_duration,
    parse_afinfo_duration,
    transcribe_file,
    validate_audio_file,
)

# --- Validation ----------------------------------------------------------------


def test_file_extension_lowercases_and_strips_dot():
    assert file_extension("/tmp/Clip.MP3") == "mp3"
    assert file_extension("/tmp/no_ext") == ""
    assert file_extension("") == ""


@pytest.mark.parametrize("ext", ALLOWED_AUDIO_EXTENSIONS)
def test_validate_accepts_all_allowed_extensions(ext):
    ok, message = validate_audio_file(f"/tmp/sample.{ext}", exists=lambda p: True)
    assert ok is True
    assert message == ""


def test_validate_rejects_missing_path():
    ok, message = validate_audio_file("", exists=lambda p: True)
    assert ok is False
    assert "No file" in message


def test_validate_rejects_nonexistent_file():
    ok, message = validate_audio_file("/tmp/missing.wav", exists=lambda p: False)
    assert ok is False
    assert "could not be found" in message


def test_validate_rejects_unsupported_extension():
    ok, message = validate_audio_file("/tmp/doc.txt", exists=lambda p: True)
    assert ok is False
    assert "Unsupported file type" in message
    assert ".txt" in message


# --- Command construction ------------------------------------------------------


def test_build_afconvert_command_shape():
    cmd = build_afconvert_command("/in put.mp3", "/out.wav")
    # List args only (paths are separate elements; no shell string).
    assert cmd[0] == "afconvert"
    assert "-f" in cmd and "WAVE" in cmd
    assert "LEI16@16000" in cmd
    assert cmd[-2] == "/in put.mp3"
    assert cmd[-1] == "/out.wav"
    # 16 kHz mono enforced
    assert "-c" in cmd and "1" in cmd


def test_build_afinfo_command_shape():
    assert build_afinfo_command("/a b.m4a") == ["afinfo", "/a b.m4a"]


# --- afinfo parsing ------------------------------------------------------------


def test_parse_afinfo_duration_extracts_seconds():
    output = "File: sample.mp3\n" "File type ID: MPG3\n" "estimated duration: 73.45 sec\n" "audio bytes: 123456\n"
    assert parse_afinfo_duration(output) == pytest.approx(73.45)


def test_parse_afinfo_duration_integer_seconds():
    assert parse_afinfo_duration("estimated duration: 5 sec") == pytest.approx(5.0)


def test_parse_afinfo_duration_returns_none_when_absent():
    assert parse_afinfo_duration("no duration here") is None
    assert parse_afinfo_duration("") is None


def test_format_duration():
    assert format_duration(None) == ""
    assert format_duration(-3) == ""
    assert format_duration(5) == "0:05"
    assert format_duration(65) == "1:05"
    assert format_duration(3723) == "1:02:03"


# --- Orchestrator: happy + error paths ----------------------------------------


def _ok_command(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


def _build_injected(*, afinfo_stdout="estimated duration: 12.0 sec", transcribe_text="hello world"):
    """Return a kwargs dict of injected fakes for transcribe_file."""
    deleted = []

    def run_command(argv):
        if argv and argv[0] == "afinfo":
            return _ok_command(stdout=afinfo_stdout)
        return _ok_command()  # afconvert success

    transcription = SimpleNamespace(text=transcribe_text, provider="apple", model="en-US")

    return {
        "transcribe": MagicMock(return_value=transcription),
        "run_command": MagicMock(side_effect=run_command),
        "create_temp_file": MagicMock(return_value="/scratch/decoded.wav"),
        "secure_delete": MagicMock(side_effect=lambda p: deleted.append(p)),
        "read_bytes": MagicMock(return_value=b"R" * 4000),
        "file_exists": lambda p: True,
    }, deleted


def test_transcribe_file_happy_path_returns_text_and_metadata():
    injected, deleted = _build_injected()
    outcome = transcribe_file("/tmp/clip.mp3", **injected)

    assert outcome["text"] == "hello world"
    assert outcome["char_count"] == len("hello world")
    assert outcome["duration_seconds"] == pytest.approx(12.0)
    assert outcome["provider"] == "apple"
    assert outcome["model"] == "en-US"
    # Scratch file is securely deleted.
    assert deleted == ["/scratch/decoded.wav"]
    injected["transcribe"].assert_called_once()


def test_transcribe_file_applies_replacements():
    injected, _ = _build_injected(transcribe_text="teh cat")
    outcome = transcribe_file(
        "/tmp/clip.wav",
        apply_replacements=lambda t: t.replace("teh", "the"),
        **injected,
    )
    assert outcome["text"] == "the cat"


def test_transcribe_file_rejects_overlong_media():
    injected, deleted = _build_injected(afinfo_stdout="estimated duration: 9000.0 sec")
    with pytest.raises(FileTranscriptionError) as exc:
        transcribe_file("/tmp/long.mp3", max_duration_seconds=3600, **injected)
    assert "too long" in str(exc.value)
    # No decode/transcribe should have happened, so no temp file deletion needed.
    injected["transcribe"].assert_not_called()


def test_transcribe_file_invalid_path_raises():
    injected, _ = _build_injected()
    injected["file_exists"] = lambda p: False
    with pytest.raises(FileTranscriptionError) as exc:
        transcribe_file("/tmp/missing.mp3", **injected)
    assert "could not be found" in str(exc.value)


def test_transcribe_file_afconvert_failure_raises_and_cleans_up():
    deleted = []

    def run_command(argv):
        if argv and argv[0] == "afinfo":
            return _ok_command(stdout="estimated duration: 3.0 sec")
        return _ok_command(returncode=1)  # afconvert fails

    with pytest.raises(FileTranscriptionError) as exc:
        transcribe_file(
            "/tmp/clip.mp3",
            transcribe=MagicMock(),
            run_command=MagicMock(side_effect=run_command),
            create_temp_file=MagicMock(return_value="/scratch/x.wav"),
            secure_delete=MagicMock(side_effect=lambda p: deleted.append(p)),
            read_bytes=MagicMock(return_value=b""),
            file_exists=lambda p: True,
        )
    assert "decode" in str(exc.value).lower()
    # Scratch file still securely deleted in finally.
    assert deleted == ["/scratch/x.wav"]


def test_transcribe_file_empty_decode_raises():
    injected, deleted = _build_injected()
    injected["read_bytes"] = MagicMock(return_value=b"\x00" * 10)  # too short
    with pytest.raises(FileTranscriptionError) as exc:
        transcribe_file("/tmp/clip.mp3", **injected)
    assert "empty" in str(exc.value).lower() or "short" in str(exc.value).lower()
    assert deleted == ["/scratch/decoded.wav"]


def test_transcribe_file_provider_error_is_friendly_and_cleans_up():
    deleted = []

    def run_command(argv):
        if argv and argv[0] == "afinfo":
            return _ok_command(stdout="estimated duration: 3.0 sec")
        return _ok_command()

    def boom(_bytes):
        raise RuntimeError("401 unauthorized: invalid api key")

    with pytest.raises(FileTranscriptionError) as exc:
        transcribe_file(
            "/tmp/clip.mp3",
            transcribe=boom,
            run_command=MagicMock(side_effect=run_command),
            create_temp_file=MagicMock(return_value="/scratch/x.wav"),
            secure_delete=MagicMock(side_effect=lambda p: deleted.append(p)),
            read_bytes=MagicMock(return_value=b"R" * 4000),
            file_exists=lambda p: True,
        )
    assert "API key" in str(exc.value)
    assert deleted == ["/scratch/x.wav"]


def test_transcribe_file_tolerates_afinfo_failure():
    """A failed afinfo probe should not block transcription (duration just None)."""

    def run_command(argv):
        if argv and argv[0] == "afinfo":
            raise OSError("afinfo missing")
        return _ok_command()

    transcription = SimpleNamespace(text="ok", provider="apple", model="en-US")
    outcome = transcribe_file(
        "/tmp/clip.wav",
        transcribe=MagicMock(return_value=transcription),
        run_command=MagicMock(side_effect=run_command),
        create_temp_file=MagicMock(return_value="/scratch/x.wav"),
        secure_delete=MagicMock(),
        read_bytes=MagicMock(return_value=b"R" * 4000),
        file_exists=lambda p: True,
    )
    assert outcome["text"] == "ok"
    assert outcome["duration_seconds"] is None
