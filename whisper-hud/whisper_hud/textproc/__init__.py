"""Pure text-processing utilities for WhisperHUD.

This subpackage contains deterministic, dependency-free helpers that transform
transcribed text *after* speech recognition and *before* it is pasted at the
cursor. Everything here is pure Python (stdlib only): there are NO imports of
AppKit, rumps, providers, config, or any other app-level module. That makes
these helpers trivially unit-testable and safe to call from any thread.

The public surface is intentionally small and stable -- app wiring happens in a
later wave and depends on these exact signatures:

``replacements``
    Personal dictionary / text-replacement rules. See
    :func:`.replacements.rules_from_config` and
    :func:`.replacements.apply_replacements`.

``voice_commands``
    Deterministic command grammar ("scratch that", "new line", "press enter",
    ...). False positives are the enemy: only exact (or trailing, for
    scratch-style) phrase matches fire. See
    :func:`.voice_commands.match_command`.

``modes``
    Dictation modes / per-app profiles with fnmatch-based app matching and
    built-in formatting prompts. See :data:`.modes.BUILTIN_MODES`,
    :func:`.modes.modes_from_config`, and :func:`.modes.resolve_mode`.

``cleanup_guard``
    Anti-paraphrase guardrail that decides whether an LLM "cleanup" rewrite
    stayed faithful to the original words. See
    :func:`.cleanup_guard.cleanup_is_safe`.

Design rules every module here follows:

* **Pure stdlib only** -- ``re``, ``difflib``, ``dataclasses``, ``fnmatch``,
  ``logging``, etc.
* **Defensive parsing** -- the ``*_from_config`` functions consume
  user-editable JSON. Malformed entries are skipped with a logged warning
  (via ``logging.getLogger(__name__)``); they never raise.
* **Full type hints** on every public function and dataclass.
"""

from .cleanup_guard import DEFAULT_FILLERS, cleanup_is_safe, words
from .modes import BUILTIN_MODES, Mode, modes_from_config, resolve_mode
from .replacements import Rule, apply_replacements, rules_from_config
from .voice_commands import CommandMatch, match_command

__all__ = [
    # replacements
    "Rule",
    "rules_from_config",
    "apply_replacements",
    # voice_commands
    "CommandMatch",
    "match_command",
    # modes
    "Mode",
    "BUILTIN_MODES",
    "modes_from_config",
    "resolve_mode",
    # cleanup_guard
    "words",
    "DEFAULT_FILLERS",
    "cleanup_is_safe",
]
