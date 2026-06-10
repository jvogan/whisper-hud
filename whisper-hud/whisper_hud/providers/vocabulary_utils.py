"""Helpers for turning user vocabulary into provider biasing artifacts.

A "vocabulary" is a list of words/phrases (names, jargon, acronyms) the user
expects to say. Different providers consume biasing hints in different shapes:

- Prompt-style providers (OpenAI batch ``prompt``, faster-whisper
  ``initial_prompt``, OpenAI Realtime ``prompt``) take a single natural-language
  string. :func:`format_vocabulary_glossary` builds that string.
- Phrase-list providers (Apple ``contextualStrings``) take the list directly.
  :func:`normalize_vocabulary_phrases` cleans and caps that list.
"""

from __future__ import annotations

from typing import Optional, Sequence

# Apple's SFSpeechRecognitionRequest contextualStrings is intended for a small
# set of hint phrases; an unbounded list hurts accuracy and latency. Cap it.
DEFAULT_MAX_PHRASES = 100


def normalize_vocabulary_phrases(
    vocabulary: Optional[Sequence[str]], max_phrases: int = DEFAULT_MAX_PHRASES
) -> list[str]:
    """Return a cleaned, de-duplicated, capped list of vocabulary phrases.

    Strips surrounding whitespace, drops empties, removes duplicates while
    preserving first-seen order, and truncates to ``max_phrases``. Returns an
    empty list when ``vocabulary`` is falsy.
    """
    if not vocabulary:
        return []

    phrases: list[str] = []
    seen: set[str] = set()
    for raw in vocabulary:
        if not isinstance(raw, str):
            continue
        phrase = raw.strip()
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        phrases.append(phrase)
        if len(phrases) >= max_phrases:
            break

    return phrases


def format_vocabulary_glossary(
    vocabulary: Optional[Sequence[str]], max_phrases: int = DEFAULT_MAX_PHRASES
) -> Optional[str]:
    """Format vocabulary as a natural-language glossary string for prompt biasing.

    Produces e.g. ``"Vocabulary: Kubernetes, Anthropic, gRPC."`` which prompt
    based ASR models (OpenAI, faster-whisper) use to bias recognition toward
    those terms. Returns ``None`` when there is no usable vocabulary so callers
    can omit the prompt entirely.
    """
    phrases = normalize_vocabulary_phrases(vocabulary, max_phrases=max_phrases)
    if not phrases:
        return None
    return "Vocabulary: " + ", ".join(phrases) + "."
