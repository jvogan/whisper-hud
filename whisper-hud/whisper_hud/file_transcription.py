"""
File transcription helpers (picker-free, dependency-injected, testable).

This module holds the *pure* logic behind the "Transcribe Audio File…" menu
action so it can be unit-tested without AppKit, subprocess, or a real
``TranscriptionManager``. The app layer (``app.py``) owns the native file
picker and HUD; everything here takes injected callables.

Security/privacy invariants honored by this module:
  * Audio is decoded with ``afconvert`` via **list-args** subprocess only — no
    ``shell=True``, no string interpolation of untrusted paths into a shell or
    AppleScript.
  * The decoded WAV is written to a private 0600 temp file (the orchestrator is
    handed a ``create_temp_file``/``secure_delete`` pair that mirrors
    ``encryption.py``) and securely deleted in a ``finally`` block.
  * Transcript text is never logged.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional, Sequence

from .logging_config import get_logger

logger = get_logger("file_transcription")

# Extensions afconvert can decode on macOS. Lowercased, no leading dot.
ALLOWED_AUDIO_EXTENSIONS = (
    "wav",
    "mp3",
    "m4a",
    "aac",
    "aiff",
    "aif",
    "caf",
    "flac",
    "mp4",
    "mov",
    "m4v",
)

# Refuse very long media: transcription takes the whole decoded buffer in
# memory, so guard against multi-hour files. ~2 hours.
MAX_FILE_DURATION_SECONDS = 2 * 60 * 60

# afconvert estimated duration is reported by afinfo; this matches the line
# "estimated duration: 12.34 sec".
_AFINFO_DURATION_RE = re.compile(r"estimated duration:\s*([0-9]+(?:\.[0-9]+)?)\s*sec", re.IGNORECASE)


def file_extension(path: str) -> str:
    """Return the lowercased extension (no dot) for ``path``; "" if none."""
    if not path:
        return ""
    _, ext = os.path.splitext(path)
    return ext[1:].lower() if ext.startswith(".") else ext.lower()


def validate_audio_file(path: str, *, exists: Optional[Callable[[str], bool]] = None) -> tuple[bool, str]:
    """Validate that ``path`` is a transcribable media file.

    Checks (in order): non-empty path, file exists, extension in the allowlist.
    ``exists`` is injectable for tests; it defaults to ``os.path.isfile``.

    Returns ``(ok, message)``. ``message`` is a short, user-facing reason when
    ``ok`` is False and "" when ok.
    """
    if not path or not path.strip():
        return False, "No file selected."

    is_file = exists if exists is not None else os.path.isfile
    try:
        present = is_file(path)
    except Exception:
        present = False
    if not present:
        return False, "That file could not be found."

    ext = file_extension(path)
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        allowed = ", ".join(ALLOWED_AUDIO_EXTENSIONS)
        shown = ext or "unknown"
        return False, f"Unsupported file type: .{shown}\nSupported: {allowed}"

    return True, ""


def build_afconvert_command(src: str, dst: str) -> list[str]:
    """Build the ``afconvert`` argv to decode ``src`` to a 16 kHz mono LE16 WAV.

    Always list-args (no shell). The output format matches what the providers
    expect for batch transcription (PCM WAV, 16 kHz, mono).
    """
    return [
        "afconvert",
        "-f",
        "WAVE",
        "-d",
        "LEI16@16000",
        "-c",
        "1",
        src,
        dst,
    ]


def build_afinfo_command(src: str) -> list[str]:
    """Build the ``afinfo`` argv used to probe duration. List-args only."""
    return ["afinfo", src]


def parse_afinfo_duration(output: str) -> Optional[float]:
    """Parse the estimated duration (seconds) from ``afinfo`` output.

    Returns ``None`` when no duration line is present or it cannot be parsed.
    """
    if not output:
        return None
    match = _AFINFO_DURATION_RE.search(output)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def format_duration(seconds: Optional[float]) -> str:
    """Render a duration like "1:05" or "1:02:03"; "" when unknown."""
    if seconds is None or seconds < 0:
        return ""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class FileTranscriptionError(Exception):
    """Raised by :func:`transcribe_file` with a user-facing message."""


def transcribe_file(
    path: str,
    *,
    transcribe: Callable[[bytes], object],
    run_command: Callable[[list[str]], "object"],
    create_temp_file: Callable[[bytes], str],
    secure_delete: Callable[[str], object],
    read_bytes: Callable[[str], bytes],
    apply_replacements: Optional[Callable[[str], str]] = None,
    vocabulary: Optional[Sequence[str]] = None,
    file_exists: Optional[Callable[[str], bool]] = None,
    max_duration_seconds: float = MAX_FILE_DURATION_SECONDS,
) -> dict:
    """Decode, probe, and transcribe an audio/video file.

    All side-effecting operations are injected so this orchestrator is fully
    unit-testable:

      * ``run_command(argv) -> CompletedProcess-like`` with ``.returncode`` and
        ``.stdout`` (str). Used for both ``afinfo`` and ``afconvert``.
      * ``create_temp_file(b"") -> path`` creates a private 0600 scratch file
        (mirrors ``encryption.create_private_temp_file``). We pass empty bytes
        and let ``afconvert`` write the real WAV into it.
      * ``secure_delete(path)`` removes the scratch file (mirrors
        ``encryption.secure_delete``); always called in ``finally``.
      * ``read_bytes(path) -> bytes`` reads the decoded WAV back.
      * ``transcribe(wav_bytes) -> TranscriptionResult-like`` with ``.text`` and
        optional ``.provider`` / ``.model``. Callers bind vocabulary/provider via
        a closure before passing it in.
      * ``apply_replacements(text) -> text`` optional personal-dictionary pass.

    Returns a dict: ``{"text", "char_count", "duration_seconds", "provider",
    "model"}``. Raises :class:`FileTranscriptionError` with a user-facing
    message on any failure. Never logs transcript text.

    ``vocabulary`` is accepted for symmetry/documentation; the actual biasing is
    expected to be bound into the ``transcribe`` closure by the caller.
    """
    ok, message = validate_audio_file(path, exists=file_exists)
    if not ok:
        raise FileTranscriptionError(message)

    # --- Duration probe (best-effort; refuse over the cap) ------------------
    duration: Optional[float] = None
    try:
        info = run_command(build_afinfo_command(path))
        if getattr(info, "returncode", 1) == 0:
            duration = parse_afinfo_duration(getattr(info, "stdout", "") or "")
    except Exception:
        logger.debug("afinfo probe failed; proceeding without duration", exc_info=True)
        duration = None

    if duration is not None and duration > max_duration_seconds:
        limit_min = int(max_duration_seconds // 60)
        raise FileTranscriptionError(
            f"That file is too long ({format_duration(duration)}). " f"Files up to {limit_min} minutes are supported."
        )

    # --- Decode to a private temp WAV, then transcribe ----------------------
    temp_path = create_temp_file(b"")
    try:
        try:
            result = run_command(build_afconvert_command(path, temp_path))
        except Exception as exc:
            logger.error("afconvert invocation failed: %s", type(exc).__name__)
            raise FileTranscriptionError("Could not decode that audio file.") from exc

        if getattr(result, "returncode", 1) != 0:
            logger.error("afconvert returned non-zero exit status")
            raise FileTranscriptionError("Could not decode that audio file. It may be corrupt or unsupported.")

        try:
            wav_bytes = read_bytes(temp_path)
        except Exception as exc:
            logger.error("Failed to read decoded audio: %s", type(exc).__name__)
            raise FileTranscriptionError("Could not read the decoded audio.") from exc

        if not wav_bytes or len(wav_bytes) < 1000:
            raise FileTranscriptionError("The decoded audio was empty or too short to transcribe.")

        try:
            transcription = transcribe(wav_bytes)
        except Exception as exc:
            # Do not echo provider error bodies that might be noisy; keep it short.
            logger.error("File transcription provider error: %s", type(exc).__name__)
            raise FileTranscriptionError(_friendly_transcribe_error(exc)) from exc
    finally:
        try:
            secure_delete(temp_path)
        except Exception:
            logger.debug("secure_delete of file-transcription scratch failed", exc_info=True)

    text = getattr(transcription, "text", "") or ""
    if apply_replacements is not None:
        try:
            text = apply_replacements(text)
        except Exception:
            logger.debug("Text replacement failed for file transcription; using raw text", exc_info=True)

    return {
        "text": text,
        "char_count": len(text),
        "duration_seconds": duration,
        "provider": getattr(transcription, "provider", "") or "",
        "model": getattr(transcription, "model", "") or "",
    }


def _friendly_transcribe_error(error: Exception) -> str:
    """Map a transcription exception to a short, user-facing message."""
    text = str(error).lower()
    if "api key" in text or "not configured" in text or "unauthorized" in text or "401" in text:
        return "Transcription needs an API key. Add or unlock it, or switch to a local provider."
    if "timeout" in text or "timed out" in text:
        return "Transcription timed out. Check your connection and try again."
    if "network" in text or "connection" in text:
        return "Network error during transcription. Check your connection and try again."
    return "Transcription failed for that file."
