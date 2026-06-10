"""Deterministic voice-command grammar.

This module recognizes a small set of spoken editing commands inside a
transcribed utterance -- things like "scratch that", "new line", or
"press enter". It is deliberately conservative: **false positives are the
enemy.** Mis-firing a command (e.g. deleting the user's dictation because they
happened to say the words "scratch that" mid-sentence) is far worse than
missing one, so the matcher only fires when it is confident.

Matching modes
--------------
Two kinds of commands exist:

* **Exact commands** fire only when the *entire* normalized utterance is the
  command phrase. "new line" -> insert ``\\n``; "the new line of products" ->
  no match.
* **Scratch (trailing) commands** fire when the normalized utterance *ends with*
  the command phrase on a word boundary. This lets a user append "scratch that"
  to the end of a sentence to throw the whole utterance away. The semantics are
  precise (see :func:`match_command`): the phrase must be the final tokens of
  the utterance, bounded by a word boundary, so "starting from scratch that day"
  does **not** match (it ends with "day").

Normalization
-------------
Before matching, text is:

1. casefolded,
2. stripped of leading/trailing whitespace,
3. stripped of trailing terminal punctuation (``. , ! ?``) on each end,
4. collapsed so runs of inner whitespace become a single space.

Public API
----------
``CommandMatch``
    The result of a successful match (:class:`CommandMatch`).

``match_command(text, custom_commands=None)``
    Return a :class:`CommandMatch` or ``None``.

Actions
-------
* ``"discard"`` -- throw away the whole utterance ("scratch that",
  "delete that", "never mind cancel the dictation", ...).
* ``"insert"`` -- insert literal text; ``payload`` is the text to insert
  ("new line" -> ``"\\n"``, "new paragraph" -> ``"\\n\\n"``).
* ``"keystroke"`` -- emit a key press; ``payload`` is a key name
  ("press enter" -> ``"return"``, "press tab" -> ``"tab"``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["CommandMatch", "match_command"]


@dataclass
class CommandMatch:
    """A recognized voice command.

    Attributes:
        command_id: Stable identifier for the command (e.g. ``"scratch_that"``,
            ``"new_line"``, or the id of a custom command).
        action: One of ``"discard"``, ``"insert"``, or ``"keystroke"``.
        payload: Action-specific data. Empty for ``"discard"``; the literal text
            for ``"insert"``; the key name for ``"keystroke"``.
        matched_text: The normalized phrase that triggered the match.
    """

    command_id: str
    action: str
    payload: str = ""
    matched_text: str = ""


# Terminal punctuation trimmed from each end of the utterance before matching.
_TERMINAL_PUNCT = ".,!?"
_WS_RUN = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Normalize an utterance for command matching.

    Casefolds, trims whitespace and terminal punctuation from both ends, and
    collapses inner whitespace to single spaces. Returns ``""`` for input that
    is empty or only punctuation/whitespace.

    Args:
        text: Raw utterance text.

    Returns:
        The normalized utterance.
    """
    if not text:
        return ""
    lowered = text.casefold()
    collapsed = _WS_RUN.sub(" ", lowered).strip()
    # Trim terminal punctuation from both ends, re-stripping any whitespace it
    # exposes (e.g. "... line ." -> "line").
    collapsed = collapsed.strip(_TERMINAL_PUNCT + " \t\n\r\f\v")
    return collapsed


# --- Built-in command tables -------------------------------------------------
#
# Each tuple is (command_id, action, payload, phrases). ``phrases`` is the set of
# accepted normalized spoken forms. Exact commands require the *whole* utterance
# to equal a phrase; scratch commands (in _SCRATCH_PHRASES) may match as a
# trailing suffix.

# Exact-match commands: utterance must equal one of the phrases.
_EXACT_COMMANDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("new_line", "insert", "\n", ("new line", "newline", "line break")),
    ("new_paragraph", "insert", "\n\n", ("new paragraph", "new para")),
    ("press_enter", "keystroke", "return", ("press enter", "press return", "hit enter")),
    ("press_tab", "keystroke", "tab", ("press tab", "hit tab")),
)

# Scratch / discard commands. These accept a trailing match: an utterance that
# *ends with* one of these phrases discards the whole utterance. They also match
# exactly. Ordered longest-first so multi-word phrases win.
_SCRATCH_COMMANDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "discard",
        "discard",
        "",
        (
            "never mind cancel the dictation",
            "cancel the dictation",
            "scratch that",
            "delete that",
            "never mind",
            "nevermind",
        ),
    ),
)


def _phrase_matches_exact(normalized: str, phrase: str) -> bool:
    """True when the whole normalized utterance equals ``phrase``."""
    return normalized == phrase


def _phrase_matches_trailing(normalized: str, phrase: str) -> bool:
    """True when ``normalized`` ends with ``phrase`` on a word boundary.

    The phrase must be the final tokens of the utterance. We require either that
    the utterance *is* the phrase, or that the character immediately preceding
    the phrase is a space -- guaranteeing whole-token alignment. This makes
    "i changed my mind, scratch that" match while "starting from scratch that
    day" does not (it does not end with the phrase at all).
    """
    if normalized == phrase:
        return True
    if not normalized.endswith(phrase):
        return False
    boundary_index = len(normalized) - len(phrase)
    # Must be preceded by a space so we align on a token boundary (not e.g.
    # matching "scratch that" inside a longer final token).
    return boundary_index > 0 and normalized[boundary_index - 1] == " "


def _iter_custom(custom_commands: list[dict] | None):
    """Yield validated ``(command_id, action, payload, phrases, trailing)``.

    ``custom_commands`` is user-editable JSON. Each entry must be a dict with:

    * ``id`` (str, required, non-empty),
    * ``action`` (str, required, one of ``insert`` / ``keystroke`` / ``discard``),
    * ``phrases`` (list[str], required, at least one non-empty phrase) *or* a
      single ``phrase`` string,
    * ``payload`` (str, optional; defaults to ``""``),
    * ``trailing`` (bool, optional; defaults to ``True`` for ``discard`` actions
      and ``False`` otherwise) -- whether the command may match as a trailing
      suffix.

    Malformed entries are skipped with a logged warning.
    """
    if custom_commands is None:
        return
    if not isinstance(custom_commands, list):
        logger.warning("Custom commands is not a list (got %s); ignoring.", type(custom_commands).__name__)
        return

    valid_actions = {"insert", "keystroke", "discard"}

    for index, entry in enumerate(custom_commands):
        if not isinstance(entry, dict):
            logger.warning("Skipping custom command #%d: not an object (%s).", index, type(entry).__name__)
            continue

        command_id = entry.get("id")
        if not isinstance(command_id, str) or not command_id:
            logger.warning("Skipping custom command #%d: missing or empty 'id'.", index)
            continue

        action = entry.get("action")
        if action not in valid_actions:
            logger.warning(
                "Skipping custom command %r: invalid action %r (expected one of %s).",
                command_id,
                action,
                sorted(valid_actions),
            )
            continue

        payload = entry.get("payload", "")
        if not isinstance(payload, str):
            logger.warning("Skipping custom command %r: 'payload' must be a string.", command_id)
            continue

        raw_phrases = entry.get("phrases")
        if raw_phrases is None and isinstance(entry.get("phrase"), str):
            raw_phrases = [entry["phrase"]]
        if not isinstance(raw_phrases, list):
            logger.warning("Skipping custom command %r: missing 'phrases' list.", command_id)
            continue

        phrases: list[str] = []
        for raw_phrase in raw_phrases:
            if not isinstance(raw_phrase, str):
                continue
            norm = normalize(raw_phrase)
            if norm:
                phrases.append(norm)
        if not phrases:
            logger.warning("Skipping custom command %r: no usable phrases.", command_id)
            continue

        trailing_raw = entry.get("trailing")
        if trailing_raw is None:
            trailing = action == "discard"
        else:
            trailing = bool(trailing_raw)

        yield command_id, action, payload, tuple(phrases), trailing


def match_command(text: str, custom_commands: list[dict] | None = None) -> CommandMatch | None:
    """Match ``text`` against the command grammar.

    Custom commands are checked first (so users can override or extend the
    built-ins), then built-in scratch/discard commands, then built-in exact
    commands. For each, exact matches are preferred and trailing matches are only
    attempted for commands that allow trailing.

    Args:
        text: The raw utterance to inspect.
        custom_commands: Optional user-defined command definitions (see
            :func:`_iter_custom` for the accepted schema). Malformed entries are
            skipped, never raised.

    Returns:
        A :class:`CommandMatch` if a command fires, otherwise ``None``.
    """
    normalized = normalize(text)
    if not normalized:
        return None

    # 1) Custom commands first (user precedence). Exact pass, then trailing pass,
    #    so an exact command never loses to a trailing one.
    custom_specs = list(_iter_custom(custom_commands))

    for command_id, action, payload, phrases, _trailing in custom_specs:
        for phrase in phrases:
            if _phrase_matches_exact(normalized, phrase):
                return CommandMatch(command_id=command_id, action=action, payload=payload, matched_text=phrase)

    # 2) Built-in exact commands (whole-utterance only).
    for command_id, action, payload, phrases in _EXACT_COMMANDS:
        for phrase in phrases:
            if _phrase_matches_exact(normalized, phrase):
                return CommandMatch(command_id=command_id, action=action, payload=payload, matched_text=phrase)

    # 3) Built-in scratch/discard exact matches.
    for command_id, action, payload, phrases in _SCRATCH_COMMANDS:
        for phrase in phrases:
            if _phrase_matches_exact(normalized, phrase):
                return CommandMatch(command_id=command_id, action=action, payload=payload, matched_text=phrase)

    # 4) Trailing matches (custom first, then built-in scratch). Longest phrase
    #    wins to avoid a short phrase pre-empting a longer one.
    trailing_candidates: list[tuple[str, str, str, str]] = []

    for command_id, action, payload, phrases, trailing in custom_specs:
        if not trailing:
            continue
        for phrase in phrases:
            if _phrase_matches_trailing(normalized, phrase):
                trailing_candidates.append((command_id, action, payload, phrase))

    for command_id, action, payload, phrases in _SCRATCH_COMMANDS:
        for phrase in phrases:
            if _phrase_matches_trailing(normalized, phrase):
                trailing_candidates.append((command_id, action, payload, phrase))

    if trailing_candidates:
        command_id, action, payload, phrase = max(trailing_candidates, key=lambda item: len(item[3]))
        return CommandMatch(command_id=command_id, action=action, payload=payload, matched_text=phrase)

    return None
