"""Tests for whisper_hud.textproc.voice_commands (command grammar).

The overriding goal of these tests is to prove that **false positives do not
happen**: a command must only fire when the utterance is exactly a command
phrase, or (for scratch-style commands) when it ends with the phrase on a token
boundary.
"""

import logging

import pytest

from whisper_hud.textproc.voice_commands import CommandMatch, match_command, normalize


class TestNormalize:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("New Line", "new line"),
            ("  scratch that  ", "scratch that"),
            ("scratch that.", "scratch that"),
            ("scratch that!?", "scratch that"),
            ("new   line", "new line"),
            ("New\tParagraph\n", "new paragraph"),
            ("", ""),
            ("...", ""),
            ("   ", ""),
            (".,!?", ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize(raw) == expected


class TestExactCommands:
    @pytest.mark.parametrize(
        "text,command_id,action,payload",
        [
            ("new line", "new_line", "insert", "\n"),
            ("newline", "new_line", "insert", "\n"),
            ("line break", "new_line", "insert", "\n"),
            ("new paragraph", "new_paragraph", "insert", "\n\n"),
            ("new para", "new_paragraph", "insert", "\n\n"),
            ("press enter", "press_enter", "keystroke", "return"),
            ("press return", "press_enter", "keystroke", "return"),
            ("hit enter", "press_enter", "keystroke", "return"),
            ("press tab", "press_tab", "keystroke", "tab"),
            ("hit tab", "press_tab", "keystroke", "tab"),
        ],
    )
    def test_exact_match(self, text, command_id, action, payload):
        match = match_command(text)
        assert match is not None
        assert match.command_id == command_id
        assert match.action == action
        assert match.payload == payload

    @pytest.mark.parametrize(
        "text",
        [
            "New Line",
            "  new line  ",
            "New Line.",
            "PRESS ENTER!",
            "new paragraph?",
        ],
    )
    def test_exact_match_with_normalization(self, text):
        assert match_command(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "the new line of products is great",
            "please add a new line here",
            "i need to press enter the room",
            "press enter the building",
            "a new paragraph of the book",
            "start a new paragraph please",
            "hit the tab key",
            "new lines everywhere",
            "press entered",
        ],
    )
    def test_exact_commands_do_not_fire_mid_sentence(self, text):
        # These contain command words but are not the whole utterance -> no fire.
        assert match_command(text) is None


class TestScratchCommands:
    @pytest.mark.parametrize(
        "text",
        [
            "scratch that",
            "Scratch that.",
            "  scratch that  ",
            "delete that",
            "never mind",
            "nevermind",
            "cancel the dictation",
            "never mind cancel the dictation",
        ],
    )
    def test_scratch_exact(self, text):
        match = match_command(text)
        assert match is not None
        assert match.action == "discard"
        assert match.command_id == "discard"

    @pytest.mark.parametrize(
        "text",
        [
            "i changed my mind, scratch that",
            "send the email to bob scratch that",
            "let's go with plan a scratch that",
            "the meeting is at noon. scratch that",
            "buy milk and eggs delete that",
        ],
    )
    def test_scratch_trailing_match_discards_whole_utterance(self, text):
        # Utterance ENDS with the scratch phrase -> discard the entire thing.
        match = match_command(text)
        assert match is not None
        assert match.action == "discard"
        assert match.matched_text in {"scratch that", "delete that"}

    @pytest.mark.parametrize(
        "text",
        [
            "starting from scratch that day was hard",
            "we built it from scratch that time",
            "scratch that itch on my back",
            "from scratch that recipe is great",
        ],
    )
    def test_scratch_mid_sentence_does_not_fire(self, text):
        # "scratch that" appears but the utterance does NOT end with it -> no fire.
        assert match_command(text) is None

    def test_scratch_phrase_inside_longer_final_token_does_not_fire(self):
        # Defensive: ensure the trailing matcher requires a token boundary.
        # "unscratch that" should not fire (final tokens are not "scratch that"
        # preceded by a space at the right place).
        assert match_command("please unscratch that") is None

    def test_longest_trailing_phrase_wins(self):
        # "never mind cancel the dictation" should win over "never mind".
        match = match_command("ok so never mind cancel the dictation")
        assert match is not None
        assert match.matched_text == "never mind cancel the dictation"


class TestNoMatch:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "...",
            "hello world how are you",
            "this is just normal dictation text",
            "i am writing a long sentence with no commands",
        ],
    )
    def test_no_match(self, text):
        assert match_command(text) is None


class TestCustomCommands:
    def test_custom_exact_command(self):
        custom = [{"id": "sig", "action": "insert", "payload": "-- Jacob", "phrases": ["my signature"]}]
        match = match_command("my signature", custom)
        assert match is not None
        assert match.command_id == "sig"
        assert match.action == "insert"
        assert match.payload == "-- Jacob"

    def test_custom_single_phrase_key(self):
        custom = [{"id": "smiley", "action": "insert", "payload": ":)", "phrase": "insert smiley"}]
        match = match_command("insert smiley", custom)
        assert match is not None
        assert match.payload == ":)"

    def test_custom_keystroke_command(self):
        custom = [{"id": "esc", "action": "keystroke", "payload": "escape", "phrases": ["press escape"]}]
        match = match_command("press escape", custom)
        assert match is not None
        assert match.action == "keystroke"
        assert match.payload == "escape"

    def test_custom_does_not_fire_mid_sentence_by_default(self):
        custom = [{"id": "sig", "action": "insert", "payload": "X", "phrases": ["my signature"]}]
        # Non-discard custom commands default to exact-only (trailing=False).
        assert match_command("please add my signature here", custom) is None

    def test_custom_trailing_when_enabled(self):
        custom = [{"id": "wipe", "action": "discard", "payload": "", "phrases": ["forget it"], "trailing": True}]
        match = match_command("send to bob forget it", custom)
        assert match is not None
        assert match.command_id == "wipe"
        assert match.action == "discard"

    def test_custom_discard_defaults_to_trailing(self):
        # discard action defaults trailing=True even without explicit flag.
        custom = [{"id": "wipe", "action": "discard", "payload": "", "phrases": ["forget it"]}]
        match = match_command("buy milk forget it", custom)
        assert match is not None
        assert match.command_id == "wipe"

    def test_custom_takes_precedence_over_builtin(self):
        # Override the built-in "new line" exact phrase with a custom command.
        custom = [{"id": "custom_nl", "action": "keystroke", "payload": "down", "phrases": ["new line"]}]
        match = match_command("new line", custom)
        assert match is not None
        assert match.command_id == "custom_nl"
        assert match.action == "keystroke"

    def test_custom_phrases_are_normalized(self):
        custom = [{"id": "x", "action": "insert", "payload": "Y", "phrases": ["  My  Phrase!  "]}]
        match = match_command("my phrase", custom)
        assert match is not None
        assert match.command_id == "x"


class TestCustomCommandValidation:
    def test_none_custom_commands(self):
        # Should behave exactly like no custom commands.
        assert match_command("new line", None) is not None

    def test_non_list_custom_commands_ignored(self, caplog):
        with caplog.at_level(logging.WARNING):
            match = match_command("new line", {"not": "a list"})
        # Built-in still works; custom ignored.
        assert match is not None
        assert "not a list" in caplog.text

    def test_skips_non_dict_entry(self, caplog):
        with caplog.at_level(logging.WARNING):
            match_command("hello", ["bad"])
        assert "not an object" in caplog.text

    def test_skips_missing_id(self, caplog):
        with caplog.at_level(logging.WARNING):
            match_command("hello", [{"action": "insert", "phrases": ["x"]}])
        assert "missing or empty 'id'" in caplog.text

    def test_skips_invalid_action(self, caplog):
        with caplog.at_level(logging.WARNING):
            match_command("hello", [{"id": "x", "action": "explode", "phrases": ["x"]}])
        assert "invalid action" in caplog.text

    def test_skips_non_string_payload(self, caplog):
        with caplog.at_level(logging.WARNING):
            match_command("hello", [{"id": "x", "action": "insert", "payload": 5, "phrases": ["x"]}])
        assert "'payload' must be a string" in caplog.text

    def test_skips_missing_phrases(self, caplog):
        with caplog.at_level(logging.WARNING):
            match_command("hello", [{"id": "x", "action": "insert"}])
        assert "missing 'phrases' list" in caplog.text

    def test_skips_when_no_usable_phrases(self, caplog):
        with caplog.at_level(logging.WARNING):
            match_command("hello", [{"id": "x", "action": "insert", "phrases": [123, "", "   "]}])
        assert "no usable phrases" in caplog.text

    def test_malformed_entry_does_not_break_valid_one(self):
        custom = [
            "bad",
            {"id": "good", "action": "insert", "payload": "Z", "phrases": ["do it"]},
        ]
        match = match_command("do it", custom)
        assert match is not None
        assert match.command_id == "good"


class TestCommandMatchDataclass:
    def test_defaults(self):
        match = CommandMatch(command_id="x", action="insert")
        assert match.payload == ""
        assert match.matched_text == ""
