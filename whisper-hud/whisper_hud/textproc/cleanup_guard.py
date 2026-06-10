"""Anti-paraphrase guardrail for LLM cleanup.

When a local LLM "cleans up" a transcription (fixing punctuation, removing filler
words), there is a real risk it quietly rewrites or paraphrases the user's words.
That is unacceptable for a dictation tool: the output must be what the user
*said*, just tidied. This module decides whether a cleaned string stayed faithful
to the original.

The check is word-level. We tokenize both strings into casefolded word tokens
(punctuation/whitespace stripped) and diff them with
:class:`difflib.SequenceMatcher`. Then:

* **Free changes** (do not count against the budget):

  * punctuation, case, and whitespace differences (they vanish during
    tokenization), and
  * deletions whose removed tokens are *only* filler words (e.g. "um", "you
    know"). Multi-word fillers are supported.

* **Counted changes** (count against the budget):

  * insertions of new words,
  * replacements of one word by a different word, and
  * deletions of non-filler words.

A cleanup is rejected if the counted changes exceed *either* an absolute cap
(``max_changed_words``) *or* a proportion of the original length
(``max_changed_ratio``).

Public API
----------
``words(text)``
    Tokenize text into casefolded word tokens.

``DEFAULT_FILLERS``
    The default set of filler words/phrases treated as free to delete.

``cleanup_is_safe(original, cleaned, ...)``
    Return ``(safe, reason)``.
"""

from __future__ import annotations

import difflib
import logging
import re

logger = logging.getLogger(__name__)

__all__ = ["words", "DEFAULT_FILLERS", "cleanup_is_safe"]


# Filler words/phrases that an LLM may freely remove during cleanup. Multi-word
# entries (e.g. "you know") are matched as token sequences.
DEFAULT_FILLERS: set[str] = {
    "um",
    "uh",
    "uhm",
    "erm",
    "hmm",
    "like",
    "you know",
    "i mean",
    "sort of",
    "kind of",
}

# A "word" token: a maximal run of word characters (letters, digits, underscore),
# allowing internal apostrophes so contractions like "don't" stay one token.
_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)


def words(text: str) -> list[str]:
    """Tokenize ``text`` into casefolded word tokens.

    Punctuation and whitespace are stripped; contractions (``don't``) are kept
    as a single token. Returns an empty list for empty/None-ish input.

    Args:
        text: The text to tokenize.

    Returns:
        A list of casefolded word tokens.
    """
    if not text:
        return []
    return [match.group(0).casefold() for match in _WORD_RE.finditer(text)]


def _filler_token_sets(allowed_fillers: set[str]) -> tuple[frozenset[str], tuple[tuple[str, ...], ...]]:
    """Split the filler set into single-token and multi-token forms.

    Returns ``(unigrams, multigrams)`` where ``unigrams`` is a frozenset of
    single-word fillers and ``multigrams`` is a tuple of token tuples (each of
    length >= 2), sorted longest-first so greedy matching prefers the longest
    phrase. Filler phrases are tokenized with :func:`words` so they normalize the
    same way as the text being checked.
    """
    unigrams: set[str] = set()
    multigrams: list[tuple[str, ...]] = []
    for filler in allowed_fillers:
        tokens = tuple(words(filler))
        if len(tokens) == 1:
            unigrams.add(tokens[0])
        elif len(tokens) > 1:
            multigrams.append(tokens)
    multigrams.sort(key=len, reverse=True)
    return frozenset(unigrams), tuple(multigrams)


def _span_is_only_filler(
    span: list[str],
    unigrams: frozenset[str],
    multigrams: tuple[tuple[str, ...], ...],
) -> bool:
    """True if ``span`` of tokens can be fully consumed as filler.

    Greedily consumes the span left-to-right: at each position, tries the longest
    matching multi-word filler, then a single-word filler. If the entire span is
    consumed this way it is "only filler"; if any token cannot be matched, it is
    not.
    """
    if not span:
        return False  # an empty deletion span is not a meaningful "filler removal"

    i = 0
    n = len(span)
    while i < n:
        matched = False
        for phrase in multigrams:
            plen = len(phrase)
            if i + plen <= n and tuple(span[i : i + plen]) == phrase:
                i += plen
                matched = True
                break
        if matched:
            continue
        if span[i] in unigrams:
            i += 1
            continue
        return False
    return True


def cleanup_is_safe(
    original: str,
    cleaned: str,
    *,
    max_changed_ratio: float = 0.18,
    max_changed_words: int = 8,
    allowed_fillers: set[str] | None = None,
) -> tuple[bool, str]:
    """Decide whether ``cleaned`` is a faithful tidy-up of ``original``.

    Punctuation/case/whitespace differences are free. Deleting only filler words
    is free. Inserting words, replacing words, or deleting non-filler words each
    count as changes. The cleanup is rejected if counted changes exceed
    ``max_changed_words`` or ``max_changed_ratio`` of the original word count.

    Args:
        original: The raw transcription.
        cleaned: The candidate cleaned-up text.
        max_changed_ratio: Maximum fraction of original words that may change
            (default ``0.18``). Compared against ``ceil``-free strict ratio.
        max_changed_words: Absolute maximum number of changed words (default
            ``8``).
        allowed_fillers: Filler words/phrases that are free to delete. Defaults
            to :data:`DEFAULT_FILLERS`.

    Returns:
        A ``(safe, reason)`` tuple. ``reason`` is a short human-readable
        explanation suitable for logging or a tooltip.
    """
    fillers = DEFAULT_FILLERS if allowed_fillers is None else allowed_fillers

    original_words = words(original)
    cleaned_words = words(cleaned)

    # Edge case: identical token streams -> only punctuation/case/space differs.
    if original_words == cleaned_words:
        return True, "no word-level changes (formatting only)"

    # Edge case: original had no words. If cleaned added words, that is fabricated
    # content; otherwise it is a no-op.
    if not original_words:
        if cleaned_words:
            return False, f"added {len(cleaned_words)} word(s) to empty input"
        return True, "no word-level changes (formatting only)"

    # Edge case: cleaned removed everything. Only safe if every original word was
    # filler (and there was at least one).
    unigrams, multigrams = _filler_token_sets(fillers)
    if not cleaned_words:
        if _span_is_only_filler(original_words, unigrams, multigrams):
            return True, "removed filler words only"
        return False, "cleanup removed all content"

    matcher = difflib.SequenceMatcher(a=original_words, b=cleaned_words, autojunk=False)

    changed = 0
    inserted = 0
    replaced = 0
    deleted_nonfiller = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            count = j2 - j1
            inserted += count
            changed += count
        elif tag == "delete":
            removed = original_words[i1:i2]
            if _span_is_only_filler(removed, unigrams, multigrams):
                continue  # free: filler removal
            count = i2 - i1
            deleted_nonfiller += count
            changed += count
        elif tag == "replace":
            # A replacement of one word by a different word is always a real
            # change. Count the larger side so growing or shrinking both count.
            count = max(i2 - i1, j2 - j1)
            replaced += count
            changed += count

    if changed == 0:
        return True, "removed filler words only"

    ratio = changed / len(original_words)
    detail = (
        f"{changed} changed word(s) "
        f"(insert={inserted}, replace={replaced}, delete={deleted_nonfiller}; "
        f"ratio={ratio:.2f})"
    )

    if changed > max_changed_words:
        return False, f"too many changes: {detail} exceeds max_changed_words={max_changed_words}"
    if ratio > max_changed_ratio:
        return False, f"too much changed: {detail} exceeds max_changed_ratio={max_changed_ratio:.2f}"

    return True, f"within tolerance: {detail}"
