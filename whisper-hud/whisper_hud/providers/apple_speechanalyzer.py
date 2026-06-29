"""
Apple Speech (Advanced) — on-device transcription via the macOS 26+
SpeechAnalyzer / SpeechTranscriber API.

SpeechAnalyzer is Apple's modern replacement for SFSpeechRecognizer: fully
on-device, Neural Engine accelerated, and substantially faster than Whisper
for comparable quality. The API is Swift-only, so this provider drives a small
bundled Swift helper binary (mirroring the Apple Translation helper pattern).

The helper (``whisperhud-speechanalyzer``) reads a JSON request on stdin and
writes line-delimited JSON events on stdout: ``{"type":"partial",...}`` for
volatile in-progress hypotheses and a single ``{"type":"final",...}`` event
with the completed transcript. Errors are reported as
``{"type":"error","message":...}`` followed by a nonzero exit.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from .base import TranscriptionProvider, TranscriptionResult
from .vocabulary_utils import normalize_vocabulary_phrases
from ..logging_config import get_logger

logger = get_logger("providers.apple_speechanalyzer")

# Name of the bundled Swift helper binary built by scripts/build-speechanalyzer.sh.
HELPER_NAME = "whisperhud-speechanalyzer"

# Generous-but-bounded wall clock for a single batch transcription. The helper
# may briefly download a locale model on first use; if it exceeds this the
# process is killed and a clear error is raised. The helper enforces its own
# (shorter) asset-download timeout internally.
HELPER_TIMEOUT_SECONDS = 120

# SpeechAnalyzer biases toward a small set of hint phrases (contextualStrings);
# cap the vocabulary we forward to keep accuracy/latency sane.
MAX_CONTEXTUAL_STRINGS = 100

# Minimum macOS major version exposing SpeechAnalyzer.
MIN_MACOS_MAJOR = 26


def _parse_macos_major(version_string: str) -> Optional[int]:
    """Parse the major version number from a ``platform.mac_ver()[0]`` string.

    ``mac_ver()`` returns strings like ``"26.5.1"`` (or occasionally ``"26"``).
    Returns the leading integer component, or ``None`` when the string is empty
    or unparseable (e.g. on non-macOS hosts where ``mac_ver()`` returns ``""``).
    """
    if not version_string:
        return None
    head = version_string.split(".", 1)[0].strip()
    if not head:
        return None
    try:
        return int(head)
    except ValueError:
        return None


class AppleSpeechAnalyzerProvider(TranscriptionProvider):
    """On-device transcription via the bundled SpeechAnalyzer Swift helper."""

    name = "apple_analyzer"
    display_name = "Apple Speech (Advanced)"

    MODELS = {
        "system": {
            "name": "System (SpeechAnalyzer)",
            "size_mb": 0,
            "description": "macOS 26+ on-device speech model — fast, free, ~40 languages",
            "languages": "system locales",
            "recommended": True,
        },
    }
    DEFAULT_MODEL = "system"

    # The "system" model uses the host's current locale, falling back to this
    # when the system locale is unavailable or unsupported. The helper performs
    # the actual locale resolution (mapping e.g. "en" -> "en-US").
    DEFAULT_LOCALE = "en-US"

    def __init__(self, model: Optional[str] = None):
        self.model = model if model in self.MODELS else self.DEFAULT_MODEL

    # -- helper discovery (mirrors AppleTranslateProvider) -----------------

    @staticmethod
    def _source_helper_path() -> Path:
        """Return the expected helper location when running from source."""
        pkg_root = Path(__file__).resolve().parents[2]
        return pkg_root / "bin" / HELPER_NAME

    @classmethod
    def _development_override_path(cls) -> Optional[Path]:
        """Allow helper overrides only inside the repo-controlled bin directory."""
        override = os.environ.get("WHISPERHUD_SPEECHANALYZER_HELPER")
        if not override:
            return None

        candidate = Path(override).expanduser().resolve()

        allowed_dir = cls._source_helper_path().parent.resolve()
        try:
            candidate.relative_to(allowed_dir)
            return candidate
        except ValueError:
            logger.warning("Ignoring untrusted SpeechAnalyzer helper override outside %s", allowed_dir)
            return None

    @classmethod
    def _helper_path(cls) -> Path:
        if getattr(sys, "frozen", False):
            try:
                from Foundation import NSBundle

                bundle = NSBundle.mainBundle()
                resources_path = bundle.resourcePath()
                if resources_path:
                    return Path(resources_path) / "bin" / HELPER_NAME
            except Exception:
                pass
        else:
            override_path = cls._development_override_path()
            if override_path is not None:
                return override_path

        return cls._source_helper_path()

    # -- availability ------------------------------------------------------

    @staticmethod
    def _is_supported_macos() -> bool:
        if platform.system() != "Darwin":
            return False
        major = _parse_macos_major(platform.mac_ver()[0])
        return major is not None and major >= MIN_MACOS_MAJOR

    def _helper_available(self) -> bool:
        helper = self._helper_path()
        return helper.exists() and os.access(helper, os.X_OK)

    def is_configured(self) -> bool:
        """Ready when on macOS 26+ and the helper binary exists and is runnable."""
        if not self._is_supported_macos():
            return False
        return self._helper_available()

    # -- locale ------------------------------------------------------------

    def _resolve_locale(self) -> str:
        """Pick the locale to request from the helper.

        For the v1 ``system`` model there is a single locale: the host's current
        locale when it can be determined, otherwise ``DEFAULT_LOCALE`` (en-US).
        The helper maps a bare language like ``"en"`` to a concrete supported
        locale (``"en-US"``) and reports a clear error for unsupported ones.
        """
        try:
            locale_id, _encoding = __import__("locale").getlocale()
            if locale_id:
                # Python locales look like "en_US"; normalize to BCP-47 "en-US".
                return locale_id.replace("_", "-")
        except Exception:
            pass
        return self.DEFAULT_LOCALE

    # -- transcription -----------------------------------------------------

    def transcribe(self, audio_bytes: bytes, vocabulary: Optional[Sequence[str]] = None) -> TranscriptionResult:
        """Transcribe audio via the bundled SpeechAnalyzer helper.

        Args:
            audio_bytes: WAV file contents.
            vocabulary: Optional words/phrases forwarded to the helper as
                SpeechAnalyzer ``contextualStrings`` biasing hints (capped at
                ``MAX_CONTEXTUAL_STRINGS``). The helper applies them when the
                API supports biasing for the active locale.

        Returns:
            TranscriptionResult with the final transcript text.
        """
        start_time = time.time()

        if not self._is_supported_macos():
            raise RuntimeError("Apple Speech (Advanced) requires macOS 26 or later (SpeechAnalyzer).")
        if not self._helper_available():
            raise RuntimeError(
                "Apple Speech (Advanced) helper not available. " "Build it with scripts/build-speechanalyzer.sh"
            )

        from ..encryption import create_private_temp_file, secure_delete

        locale = self._resolve_locale()
        phrases = normalize_vocabulary_phrases(vocabulary, max_phrases=MAX_CONTEXTUAL_STRINGS)

        payload: dict = {"audio_path": "", "locale": locale}
        if phrases:
            payload["vocabulary"] = phrases

        # SpeechAnalyzer reads from a file URL, so stage audio in a private
        # scratch file and securely delete it afterwards.
        temp_path = create_private_temp_file(audio_bytes)
        payload["audio_path"] = temp_path

        helper = self._helper_path()
        proc: Optional[subprocess.Popen] = None
        try:
            proc = subprocess.Popen(
                [str(helper)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                stdout, stderr = proc.communicate(input=json.dumps(payload), timeout=HELPER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # Kill the stuck helper and reap it so no process is orphaned.
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except Exception:
                    pass
                raise TimeoutError("Apple Speech (Advanced) transcription timed out")

            text = self._parse_helper_output(stdout, stderr, proc.returncode)
        finally:
            secure_delete(temp_path)

        duration = time.time() - start_time
        return TranscriptionResult(
            text=text.strip(),
            duration_seconds=duration,
            cost_estimate=0.0,  # Free — on-device.
            provider=self.name,
            model=self.model,
            language=locale.split("-")[0] if "-" in locale else locale,
        )

    @staticmethod
    def _parse_helper_output(stdout: str, stderr: str, returncode: int) -> str:
        """Extract the final transcript from the helper's line-delimited events.

        The helper emits one compact JSON object per line: ``partial`` events
        for in-progress hypotheses, a single ``final`` event with the completed
        transcript, or an ``error`` event. We take the ``final`` event's text;
        an ``error`` event (or a nonzero exit) becomes a RuntimeError.
        """
        final_text: Optional[str] = None
        error_message: Optional[str] = None

        for raw_line in (stdout or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Ignore non-JSON noise; the final/error events are well-formed.
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "final":
                final_text = str(event.get("text", ""))
            elif event_type == "error":
                error_message = str(event.get("message", "")) or error_message

        if error_message:
            raise RuntimeError(f"Apple Speech (Advanced) failed: {error_message}")

        if returncode != 0 and final_text is None:
            detail = (stderr or "").strip() or "Unknown error"
            raise RuntimeError(f"Apple Speech (Advanced) failed: {detail}")

        if final_text is None:
            raise RuntimeError("Apple Speech (Advanced) failed: no transcript returned")

        return final_text

    # -- model metadata ----------------------------------------------------

    def get_models(self) -> list[dict]:
        return [
            {
                "id": model_id,
                "name": info["name"],
                "description": info["description"],
                "cost_per_minute": 0.0,
                "size_mb": info["size_mb"],
                "languages": info["languages"],
                "recommended": info.get("recommended", False),
            }
            for model_id, info in self.MODELS.items()
        ]

    def set_model(self, model_id: str) -> None:
        if model_id in self.MODELS:
            self.model = model_id

    def get_current_model(self) -> str:
        return self.model

    # -- availability messaging --------------------------------------------

    @classmethod
    def get_availability_message(cls) -> str:
        """Human-readable readiness / setup guidance for menus and dialogs."""
        if platform.system() != "Darwin":
            return "Apple Speech (Advanced) requires macOS"

        if not cls._is_supported_macos():
            current = platform.mac_ver()[0] or "an older version"
            return (
                f"Apple Speech (Advanced) requires macOS {MIN_MACOS_MAJOR}+ "
                f"(SpeechAnalyzer). You have macOS {current}."
            )

        helper = cls._helper_path()
        if not (helper.exists() and os.access(helper, os.X_OK)):
            return "Build the SpeechAnalyzer helper: scripts/build-speechanalyzer.sh"

        return "Apple Speech (Advanced) is available"
