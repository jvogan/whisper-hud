"""Dictation modes / per-app profiles.

A *mode* tailors how transcribed text is formatted and routed based on which
application is focused. For example, dictating into a code editor should keep
text literal, while dictating an email might get light formatting. Modes are
matched against the focused app's display name *and* its bundle identifier using
case-insensitive :mod:`fnmatch` globs, so a single pattern like ``*mail*`` or
``com.apple.mail`` can target an app.

Built-ins vs. user modes
------------------------
:data:`BUILTIN_MODES` provides sensible defaults for email, messaging, code, and
notes. Users may define their own modes via config (:func:`modes_from_config`).
The caller is expected to combine user modes *before* built-ins and pass the
combined list to :func:`resolve_mode`; the first matching mode wins, so
user-supplied modes take precedence.

LLM prompts
-----------
Each built-in mode carries an ``llm_prompt`` that is fed to a *local* LLM in a
later wave. These prompts are intentionally tight: they instruct the model to
adjust **formatting only** and to **preserve the speaker's words**, and they end
with "Return only the rewritten text." so the model does not add commentary. The
:mod:`.cleanup_guard` module independently guards against paraphrasing.

Public API
----------
``Mode``
    A dictation profile (:class:`Mode`).

``BUILTIN_MODES``
    The default list of modes.

``modes_from_config(raw)``
    Build a validated ``list[Mode]`` from user config (defensive; skips bad
    entries with a logged warning).

``resolve_mode(app_name, bundle_id, modes)``
    Return the first mode whose patterns match the app name or bundle id, or
    ``None``.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = ["Mode", "BUILTIN_MODES", "modes_from_config", "resolve_mode"]

# Accepted formatting styles. ``"none"`` means "leave the text alone"; the others
# are hints the downstream formatter / LLM step can act on.
_VALID_FORMAT_STYLES = {"none", "email", "chat", "code", "notes", "prose"}


@dataclass
class Mode:
    """A dictation profile bound to one or more applications.

    Attributes:
        id: Stable identifier (e.g. ``"email"``).
        name: Human-readable name shown in the UI.
        app_patterns: Case-insensitive :mod:`fnmatch` globs matched against both
            the focused app's display name and its bundle id.
        format_style: A formatting hint; one of ``none``, ``email``, ``chat``,
            ``code``, ``notes``, ``prose``. Defaults to ``"none"``.
        llm_prompt: Optional instruction for a local LLM cleanup pass. Empty
            means "no LLM step".
        auto_send: When ``True``, the integration may press Return after pasting
            (e.g. to send a chat message). Defaults to ``False``.
        vocabulary: Domain words/phrases to bias recognition or cleanup toward.
    """

    id: str
    name: str
    app_patterns: list[str]
    format_style: str = "none"
    llm_prompt: str = ""
    auto_send: bool = False
    vocabulary: list[str] = field(default_factory=list)


# --- Built-in mode prompts ---------------------------------------------------
#
# Each prompt: (1) states the target medium, (2) restricts the model to
# FORMATTING changes, (3) forbids changing the speaker's words/meaning, and
# (4) ends with the exact "Return only the rewritten text." suffix.

_EMAIL_PROMPT = (
    "You are formatting dictated text into a clean email body. "
    "Fix capitalization, punctuation, paragraph breaks, and spacing only. "
    "Do not change, add, remove, reorder, or paraphrase the speaker's words; "
    "preserve their exact wording and meaning. Do not add greetings, sign-offs, "
    "or a subject line that the speaker did not say. "
    "Return only the rewritten text."
)

_MESSAGES_PROMPT = (
    "You are formatting dictated text into a short chat message. "
    "Fix capitalization and punctuation and keep it as a casual, single message. "
    "Do not change, add, remove, reorder, or paraphrase the speaker's words; "
    "preserve their exact wording and meaning. Do not add emojis or greetings "
    "the speaker did not say. "
    "Return only the rewritten text."
)

_CODE_PROMPT = (
    "You are formatting dictated text for a code editor or terminal. "
    "Keep the text literal: do not invent code, do not 'correct' identifiers, "
    "and do not reflow or reformat beyond fixing obvious spoken-to-written "
    "spacing. Do not change, add, remove, reorder, or paraphrase the speaker's "
    "words or symbols; preserve their exact wording and meaning. "
    "Return only the rewritten text."
)

_NOTES_PROMPT = (
    "You are formatting dictated text into tidy notes. "
    "Fix capitalization, punctuation, line breaks, and simple list formatting "
    "only. Do not change, add, remove, reorder, or paraphrase the speaker's "
    "words; preserve their exact wording and meaning. Do not summarize or add "
    "headings the speaker did not say. "
    "Return only the rewritten text."
)


BUILTIN_MODES: list[Mode] = [
    Mode(
        id="email",
        name="Email",
        app_patterns=["*mail*", "com.apple.mail", "*outlook*", "*spark*", "*airmail*", "*sparrow*"],
        format_style="email",
        llm_prompt=_EMAIL_PROMPT,
        auto_send=False,
    ),
    Mode(
        id="messages",
        name="Messages",
        app_patterns=[
            "*messages*",
            "com.apple.messageshelper",
            "*slack*",
            "*discord*",
            "*whatsapp*",
            "*telegram*",
            "*signal*",
        ],
        format_style="chat",
        llm_prompt=_MESSAGES_PROMPT,
        auto_send=False,
    ),
    Mode(
        id="code",
        name="Code",
        app_patterns=[
            "*code*",
            "*cursor*",
            "*xcode*",
            "*terminal*",
            "*iterm*",
            "*zed*",
            "com.apple.terminal",
        ],
        format_style="code",
        llm_prompt=_CODE_PROMPT,
        auto_send=False,
    ),
    Mode(
        id="notes",
        name="Notes",
        app_patterns=["*notes*", "*obsidian*", "*bear*", "*notion*", "com.apple.notes"],
        format_style="notes",
        llm_prompt=_NOTES_PROMPT,
        auto_send=False,
    ),
]


def _coerce_str_list(value: object) -> list[str]:
    """Coerce a config value into a clean ``list[str]``.

    Accepts a list of strings (non-strings inside are dropped). Returns an empty
    list for anything else. Used for ``app_patterns`` and ``vocabulary``.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def modes_from_config(raw: list[dict]) -> list[Mode]:
    """Build a validated list of :class:`Mode` from config dicts.

    Each dict must provide a non-empty string ``id``. Optional keys: ``name``
    (defaults to ``id``), ``app_patterns`` (list of glob strings),
    ``format_style`` (must be one of the known styles, else falls back to
    ``"none"`` with a warning), ``llm_prompt`` (str), ``auto_send`` (bool),
    ``vocabulary`` (list of strings). Entries that are not dicts or lack a usable
    ``id`` are skipped with a logged warning.

    Args:
        raw: The raw config list as loaded from JSON.

    Returns:
        A list of valid modes in their original order.
    """
    modes: list[Mode] = []

    if not isinstance(raw, list):
        logger.warning("Modes config is not a list (got %s); ignoring.", type(raw).__name__)
        return modes

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning("Skipping mode entry #%d: not an object (%s).", index, type(entry).__name__)
            continue

        mode_id = entry.get("id")
        if not isinstance(mode_id, str) or not mode_id:
            logger.warning("Skipping mode entry #%d: missing or empty 'id'.", index)
            continue

        name = entry.get("name")
        if not isinstance(name, str) or not name:
            name = mode_id

        format_style = entry.get("format_style", "none")
        if not isinstance(format_style, str) or format_style not in _VALID_FORMAT_STYLES:
            logger.warning("Mode %r has unknown format_style %r; defaulting to 'none'.", mode_id, format_style)
            format_style = "none"

        llm_prompt = entry.get("llm_prompt", "")
        if not isinstance(llm_prompt, str):
            llm_prompt = ""

        modes.append(
            Mode(
                id=mode_id,
                name=name,
                app_patterns=_coerce_str_list(entry.get("app_patterns")),
                format_style=format_style,
                llm_prompt=llm_prompt,
                auto_send=bool(entry.get("auto_send", False)),
                vocabulary=_coerce_str_list(entry.get("vocabulary")),
            )
        )

    return modes


def _matches(target: str, patterns: list[str]) -> bool:
    """True if any case-insensitive glob in ``patterns`` matches ``target``."""
    folded = target.casefold()
    return any(fnmatch.fnmatch(folded, pattern.casefold()) for pattern in patterns)


def resolve_mode(app_name: str | None, bundle_id: str | None, modes: list[Mode]) -> Mode | None:
    """Return the first mode matching the focused app, or ``None``.

    A mode matches when any of its ``app_patterns`` globs the ``app_name`` or the
    ``bundle_id`` (case-insensitively). Modes are tried in order, so the caller
    controls precedence by ordering the list (user modes before built-ins).
    Modes with empty ``app_patterns`` never match.

    Args:
        app_name: The focused app's display name, or ``None`` if unknown.
        bundle_id: The focused app's bundle identifier, or ``None`` if unknown.
        modes: Ordered list of candidate modes.

    Returns:
        The first matching :class:`Mode`, or ``None`` if nothing matches.
    """
    candidates = [value for value in (app_name, bundle_id) if value]
    if not candidates:
        return None

    for mode in modes:
        if not mode.app_patterns:
            continue
        if any(_matches(candidate, mode.app_patterns) for candidate in candidates):
            return mode

    return None
