"""Personal dictionary / text replacements.

This module implements a small, deterministic find-and-replace engine used to
fix up transcribed text: expanding shorthand, correcting names the recognizer
keeps mangling, normalizing capitalization of brand names, etc.

Public API
----------
``Rule``
    A single replacement rule (:class:`Rule`).

``rules_from_config(raw)``
    Build a validated ``list[Rule]`` from user-editable config dicts. Malformed
    entries (missing/blank pattern, wrong types, invalid regex) are skipped with
    a logged warning -- this never raises on bad input.

``apply_replacements(text, rules)``
    Apply rules to ``text`` in order and return the result.

Matching semantics
------------------
* **Literal rules** (``is_regex=False``) match the pattern as plain text. When
  ``whole_word=True`` (the default), the match must be bounded by word
  boundaries so ``"cat"`` does not match inside ``"category"``. Whole-word
  bounding is only applied where it makes sense: if the pattern starts (or ends)
  with a non-word character, the corresponding boundary is dropped, because a
  ``\b`` there would never match.
* **Regex rules** (``is_regex=True``) treat the pattern as a regular expression.
  ``whole_word`` is ignored for regex rules -- the author controls anchoring.
* ``case_sensitive`` toggles case sensitivity for both kinds (default: case
  insensitive).
* Rules are applied **in order**; each rule sees the output of the previous one.

Preserve-case niceties (matching the casing of the replaced span) are
intentionally *not* implemented.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["Rule", "rules_from_config", "apply_replacements"]


@dataclass
class Rule:
    """A single text-replacement rule.

    Attributes:
        pattern: The text (or regex source, when ``is_regex``) to look for.
        replacement: The text to substitute in. For regex rules this may use
            backreferences such as ``\\1``.
        is_regex: When ``True``, ``pattern`` is compiled as a regular
            expression. When ``False`` it is matched literally.
        case_sensitive: When ``True``, matching is case sensitive. Defaults to
            ``False`` (case-insensitive).
        whole_word: When ``True`` (default), literal matches must be bounded by
            word boundaries. Ignored for regex rules.
    """

    pattern: str
    replacement: str
    is_regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = True


# Characters considered part of a "word" for whole-word boundary decisions.
_WORD_CHAR = re.compile(r"\w")


def _compiled(rule: Rule) -> re.Pattern[str] | None:
    """Compile a rule into a regex pattern, or return ``None`` if it cannot.

    For literal rules the pattern text is escaped and optionally wrapped in
    word-boundary assertions. For regex rules the pattern is compiled as-is.
    Any :class:`re.error` is caught and logged, and ``None`` is returned so the
    caller can skip the rule rather than crash.
    """
    flags = 0 if rule.case_sensitive else re.IGNORECASE

    if rule.is_regex:
        source = rule.pattern
    else:
        source = re.escape(rule.pattern)
        if rule.whole_word and rule.pattern:
            # Only add a boundary on a side that begins/ends with a word char;
            # a \b next to punctuation/space would never match.
            prefix = r"\b" if _WORD_CHAR.match(rule.pattern[0]) else ""
            suffix = r"\b" if _WORD_CHAR.match(rule.pattern[-1]) else ""
            source = f"{prefix}{source}{suffix}"

    try:
        return re.compile(source, flags)
    except re.error as exc:
        logger.warning("Skipping replacement rule with invalid regex %r: %s", rule.pattern, exc)
        return None


def rules_from_config(raw: list[dict]) -> list[Rule]:
    """Build a validated list of :class:`Rule` from config dicts.

    Each dict may contain the keys ``pattern`` (required, non-empty string),
    ``replacement`` (string, defaults to ``""``), ``is_regex``, ``case_sensitive``
    and ``whole_word`` (all optional booleans). Entries that are not dicts, that
    lack a usable ``pattern``, that have a non-string ``replacement``, or whose
    regex fails to compile are skipped with a logged warning.

    Args:
        raw: The raw config list as loaded from JSON.

    Returns:
        A list of valid, compilable rules in their original order.
    """
    rules: list[Rule] = []

    if not isinstance(raw, list):
        logger.warning("Replacement config is not a list (got %s); ignoring.", type(raw).__name__)
        return rules

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning("Skipping replacement entry #%d: not an object (%s).", index, type(entry).__name__)
            continue

        pattern = entry.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            logger.warning("Skipping replacement entry #%d: missing or empty 'pattern'.", index)
            continue

        replacement = entry.get("replacement", "")
        if not isinstance(replacement, str):
            logger.warning("Skipping replacement entry #%d (%r): 'replacement' must be a string.", index, pattern)
            continue

        rule = Rule(
            pattern=pattern,
            replacement=replacement,
            is_regex=bool(entry.get("is_regex", False)),
            case_sensitive=bool(entry.get("case_sensitive", False)),
            whole_word=bool(entry.get("whole_word", True)),
        )

        # Validate compilability now so apply_replacements never sees a bad rule.
        if _compiled(rule) is None:
            continue

        rules.append(rule)

    return rules


def apply_replacements(text: str, rules: list[Rule]) -> str:
    """Apply replacement ``rules`` to ``text`` in order.

    Each rule is applied to the full current text (all non-overlapping matches),
    and the result is fed into the next rule. Rules whose pattern fails to
    compile are skipped (defensively; ``rules_from_config`` already filters these
    out). The original ``text`` is returned unchanged if it is empty or there are
    no rules.

    Args:
        text: The input text to transform.
        rules: Ordered replacement rules.

    Returns:
        The transformed text.
    """
    if not text or not rules:
        return text

    result = text
    for rule in rules:
        compiled = _compiled(rule)
        if compiled is None:
            continue

        if rule.is_regex:
            replacement = rule.replacement
        else:
            # Escape backslashes so a literal replacement like "C:\path" is not
            # mis-parsed as a backreference by re.sub.
            replacement = rule.replacement.replace("\\", "\\\\")

        try:
            result = compiled.sub(replacement, result)
        except re.error as exc:
            # Bad backreference in a user-authored regex replacement, etc.
            logger.warning("Skipping replacement rule %r during apply: %s", rule.pattern, exc)
            continue

    return result
