"""Local-only LLM cleanup for dictated text.

This module performs an optional "tidy up" pass over a finished transcript using
a **local** Ollama daemon (``127.0.0.1:11434``). It fixes formatting --
capitalization, punctuation, obvious spoken-to-written spacing, filler removal --
according to a mode's prompt, while a separate guardrail
(:func:`whisper_hud.textproc.cleanup_guard.cleanup_is_safe`) independently
rejects any rewrite that paraphrases the speaker.

Privacy invariant
-----------------
Cleanup is **LOCAL-ONLY**. Transcripts are sent to a loopback Ollama server and
never to any cloud service. There is intentionally no cloud cleanup path. The
HTTP session disables proxies (``trust_env = False``) and redirects so the
request cannot be diverted off-box.

Failure policy
--------------
This module never raises into the paste path. Every public method swallows
errors and returns a safe fallback (``None`` / ``False`` / unchanged text) so the
caller can fall back to the raw transcript. Transcript contents are only ever
logged at DEBUG level, matching the app's logging discipline.

Design note
-----------
We deliberately reuse the *conventions* of
``providers/translation/ollama.py`` (loopback endpoint, ``/api/tags`` probe,
proxy-free non-redirecting session, ``stream=False`` generate) without importing
it, keeping this module small and independent.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

import requests

from .logging_config import get_logger
from .textproc.cleanup_guard import cleanup_is_safe

logger = get_logger("cleanup")

__all__ = ["LocalCleanupEngine"]

# Loopback Ollama daemon. Mirrors the translation provider's endpoint.
OLLAMA_API = "http://127.0.0.1:11434"

# Quick reachability probe budget (seconds). Kept tight so menu/status checks
# never block the UI noticeably.
HEALTH_TIMEOUT_SECONDS = 0.5

# A short default instruction used when LLM cleanup is enabled but the active
# mode (if any) does not supply its own ``llm_prompt``. Formatting-only, and it
# ends with the same "Return only the rewritten text." suffix as the builtin
# mode prompts so the guardrail and parsing behave consistently.
DEFAULT_CLEANUP_PROMPT = (
    "You are tidying up a dictated transcript. "
    "Fix capitalization, punctuation, and obvious spacing only, and remove "
    "filler words such as um and uh. Do not change, add, remove, reorder, or "
    "paraphrase the speaker's words; preserve their exact wording and meaning. "
    "Return only the rewritten text."
)

# Preferred local models, smallest-decent-first. The first one present in
# ``/api/tags`` is auto-selected when the user has not pinned a model. These are
# small instruct models well-suited to a fast formatting-only pass.
_PREFERRED_MODELS = (
    "qwen3:1.7b",
    "qwen3:4b",
    "llama3.2:3b",
    "gemma3:4b",
    "qwen2.5:3b",
    "llama3.2:1b",
)

# Same conservative whitelist the translation provider uses for model names.
_VALID_MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9._:-]+$")


def _is_valid_model_name(model_name: str) -> bool:
    """Return True if ``model_name`` is safe to send to the Ollama API."""
    if not model_name or len(model_name) > 100:
        return False
    return bool(_VALID_MODEL_PATTERN.match(model_name))


class LocalCleanupEngine:
    """Tidy up transcripts via a local Ollama model, guard-checked.

    The engine is cheap to construct and holds a single proxy-free HTTP session.
    It is safe to call from a background thread (the app invokes it from the
    finalize daemon thread).
    """

    def __init__(self) -> None:
        self._http_session: Optional[requests.Session] = None

    def _get_http_session(self) -> requests.Session:
        """Return a loopback-only session that ignores proxy env vars."""
        if self._http_session is None:
            session = requests.Session()
            session.trust_env = False
            self._http_session = session
        return self._http_session

    def _get_tags(self, timeout: float) -> Optional[list[dict]]:
        """Fetch installed models from ``/api/tags``; ``None`` on any failure."""
        try:
            response = self._get_http_session().get(
                f"{OLLAMA_API}/api/tags",
                timeout=timeout,
                allow_redirects=False,
            )
            if response.status_code != 200:
                return None
            models = response.json().get("models", [])
            return models if isinstance(models, list) else []
        except Exception:
            return None

    def is_available(self) -> bool:
        """Return True if a local Ollama server answers a quick probe.

        Uses a short timeout so callers (e.g. menu status lines) never block.
        """
        return self._get_tags(HEALTH_TIMEOUT_SECONDS) is not None

    def installed_models(self) -> list[str]:
        """Return the list of installed Ollama model names (empty on failure)."""
        models = self._get_tags(HEALTH_TIMEOUT_SECONDS)
        if not models:
            return []
        names: list[str] = []
        for entry in models:
            name = entry.get("name") if isinstance(entry, dict) else None
            if isinstance(name, str) and name:
                names.append(name)
        return names

    def pick_model(self, configured: Optional[str] = None) -> Optional[str]:
        """Choose which local model to use.

        If ``configured`` is a non-empty, syntactically valid name, it is used
        verbatim (the user pinned it). Otherwise the smallest decent instruct
        model from :data:`_PREFERRED_MODELS` that is actually installed is
        chosen. Falls back to the first installed model if none of the preferred
        ones are present, or ``None`` if nothing is installed / server is down.
        """
        if configured and _is_valid_model_name(configured):
            return configured

        installed = self.installed_models()
        if not installed:
            return None

        installed_set = set(installed)
        # Exact match first, then prefix match (e.g. preferred "qwen3:4b" should
        # match an installed "qwen3:4b" exactly; a bare "qwen3" tag is matched by
        # base-name prefix below).
        for preferred in _PREFERRED_MODELS:
            if preferred in installed_set:
                return preferred
            base = preferred.split(":")[0]
            for name in installed:
                if name == base or name.startswith(f"{base}:"):
                    return name

        # No preferred model present; use the first installed one as a last
        # resort so cleanup can still work with whatever the user has.
        first = installed[0]
        return first if _is_valid_model_name(first) else None

    def _generate(self, *, model: str, system_prompt: str, transcript: str, timeout: float) -> Optional[str]:
        """POST to ``/api/generate`` (stream=False) and return the raw response.

        Returns ``None`` on any failure (server down, timeout, HTTP error, bad
        JSON). Never raises.
        """
        try:
            response = self._get_http_session().post(
                f"{OLLAMA_API}/api/generate",
                json={
                    "model": model,
                    "system": system_prompt,
                    "prompt": transcript,
                    "stream": False,
                    "options": {
                        # Deterministic, faithful formatting pass.
                        "temperature": 0.0,
                    },
                },
                stream=False,
                timeout=timeout,
                allow_redirects=False,
            )
            if response.status_code != 200:
                logger.debug("Cleanup HTTP %s from Ollama", response.status_code)
                return None
            text = response.json().get("response", "")
            return text if isinstance(text, str) else None
        except requests.exceptions.Timeout:
            logger.debug("Cleanup request timed out after %ss", timeout)
            return None
        except requests.exceptions.ConnectionError:
            logger.debug("Cleanup could not connect to local Ollama server")
            return None
        except Exception as exc:  # noqa: BLE001 - defensive: never raise into paste path
            logger.debug("Cleanup request failed: %s", type(exc).__name__)
            return None

    @staticmethod
    def _strip(text: str) -> str:
        """Trim whitespace and a single layer of wrapping quotes, if present."""
        cleaned = text.strip()
        if len(cleaned) >= 2:
            if cleaned[0] == '"' and cleaned[-1] == '"':
                cleaned = cleaned[1:-1].strip()
            elif cleaned[0] == "'" and cleaned[-1] == "'":
                cleaned = cleaned[1:-1].strip()
        return cleaned

    def cleanup(
        self,
        text: str,
        prompt: str,
        model: str,
        timeout: float,
        *,
        allowed_fillers: Optional[set[str]] = None,
    ) -> Optional[str]:
        """Return a tidied version of ``text``, or ``None`` to fall back to raw.

        Args:
            text: The raw transcript to tidy.
            prompt: System instruction (typically the active mode's
                ``llm_prompt``; falls back to :data:`DEFAULT_CLEANUP_PROMPT` when
                blank).
            model: Ollama model id to use. Must be syntactically valid.
            timeout: Per-request timeout in seconds.
            allowed_fillers: Optional override forwarded to the guardrail.

        Behavior:
            * Empty/blank input -> ``None`` (nothing to do).
            * On any request failure -> ``None`` (caller uses raw text).
            * After a successful response, the guardrail is ALWAYS run. If the
              cleaned text is judged unfaithful, the reason is logged and the
              ORIGINAL text is returned (never the paraphrase).

        This method never raises.
        """
        if not text or not text.strip():
            return None

        if not _is_valid_model_name(model):
            logger.debug("Cleanup skipped: invalid model name")
            return None

        system_prompt = prompt.strip() if prompt and prompt.strip() else DEFAULT_CLEANUP_PROMPT

        raw_response = self._generate(
            model=model,
            system_prompt=system_prompt,
            transcript=text,
            timeout=timeout,
        )
        if raw_response is None:
            return None

        cleaned = self._strip(raw_response)
        if not cleaned:
            # Model returned nothing usable; fall back to raw text.
            return None

        # Guardrail is NOT optional: an unfaithful rewrite must never reach the
        # paste path. On rejection we return the original transcript.
        safe, reason = cleanup_is_safe(text, cleaned, allowed_fillers=allowed_fillers)
        if not safe:
            logger.info("Cleanup rejected by guardrail (%s); using original text.", reason)
            return text

        logger.debug("Cleanup accepted (%s)", reason)
        return cleaned


def merge_vocabulary(*sources: Optional[Sequence[str]], cap: int = 200) -> list[str]:
    """Merge vocabulary lists, de-duplicating order-stably and capping length.

    Non-string and blank entries are dropped. Case-sensitive de-duplication
    preserves the first occurrence. The combined list is capped at ``cap``
    entries (default 200) to keep provider biasing payloads bounded.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not source:
            continue
        for item in source:
            if not isinstance(item, str):
                continue
            word = item.strip()
            if not word or word in seen:
                continue
            seen.add(word)
            merged.append(word)
            if len(merged) >= cap:
                return merged
    return merged
