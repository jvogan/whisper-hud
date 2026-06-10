"""Tests for whisper_hud.textproc.modes (dictation modes / per-app profiles)."""

import logging

import pytest

from whisper_hud.textproc.modes import BUILTIN_MODES, Mode, modes_from_config, resolve_mode


class TestModeDataclass:
    def test_defaults(self):
        mode = Mode(id="x", name="X", app_patterns=["*x*"])
        assert mode.format_style == "none"
        assert mode.llm_prompt == ""
        assert mode.auto_send is False
        assert mode.vocabulary == []

    def test_vocabulary_default_is_independent(self):
        # default_factory must not share a list between instances.
        a = Mode(id="a", name="A", app_patterns=[])
        b = Mode(id="b", name="B", app_patterns=[])
        a.vocabulary.append("term")
        assert b.vocabulary == []


class TestBuiltinModes:
    def test_expected_builtins_present(self):
        ids = {m.id for m in BUILTIN_MODES}
        assert {"email", "messages", "code", "notes"} <= ids

    @pytest.mark.parametrize("mode", BUILTIN_MODES, ids=[m.id for m in BUILTIN_MODES])
    def test_each_builtin_prompt_ends_with_required_suffix(self, mode):
        assert mode.llm_prompt.endswith("Return only the rewritten text.")

    @pytest.mark.parametrize("mode", BUILTIN_MODES, ids=[m.id for m in BUILTIN_MODES])
    def test_each_builtin_prompt_instructs_preservation(self, mode):
        lowered = mode.llm_prompt.lower()
        # Must explicitly tell the model not to change the words.
        assert "preserve" in lowered
        assert "paraphrase" in lowered

    @pytest.mark.parametrize("mode", BUILTIN_MODES, ids=[m.id for m in BUILTIN_MODES])
    def test_each_builtin_has_patterns_and_valid_style(self, mode):
        assert mode.app_patterns, f"{mode.id} has no app_patterns"
        assert mode.format_style in {"none", "email", "chat", "code", "notes", "prose"}

    def test_email_targets_common_clients(self):
        email = next(m for m in BUILTIN_MODES if m.id == "email")
        assert "*mail*" in email.app_patterns
        assert "com.apple.mail" in email.app_patterns
        assert "*outlook*" in email.app_patterns
        assert "*spark*" in email.app_patterns

    def test_messages_targets_common_apps(self):
        messages = next(m for m in BUILTIN_MODES if m.id == "messages")
        for needle in ("*messages*", "*slack*", "*discord*", "*whatsapp*", "*telegram*"):
            assert needle in messages.app_patterns

    def test_code_targets_common_editors(self):
        code = next(m for m in BUILTIN_MODES if m.id == "code")
        for needle in ("*code*", "*cursor*", "*xcode*", "*terminal*", "*iterm*", "*zed*"):
            assert needle in code.app_patterns

    def test_notes_targets_common_apps(self):
        notes = next(m for m in BUILTIN_MODES if m.id == "notes")
        for needle in ("*notes*", "*obsidian*", "*bear*", "*notion*"):
            assert needle in notes.app_patterns


class TestResolveMode:
    def test_resolves_by_app_name(self):
        mode = resolve_mode("Mail", None, BUILTIN_MODES)
        assert mode is not None
        assert mode.id == "email"

    def test_resolves_by_bundle_id(self):
        mode = resolve_mode(None, "com.apple.mail", BUILTIN_MODES)
        assert mode is not None
        assert mode.id == "email"

    def test_resolves_case_insensitively(self):
        mode = resolve_mode("VISUAL STUDIO CODE", None, BUILTIN_MODES)
        assert mode is not None
        assert mode.id == "code"

    def test_glob_matches_substring_app_name(self):
        # "*slack*" should match "Slack" and "Slack (Beta)".
        assert resolve_mode("Slack", None, BUILTIN_MODES).id == "messages"
        assert resolve_mode("Slack (Beta)", None, BUILTIN_MODES).id == "messages"

    def test_bundle_id_glob_match(self):
        # Cursor editor bundle id contains "cursor".
        mode = resolve_mode(None, "com.todesktop.230313mzl4w4u92.cursor", BUILTIN_MODES)
        assert mode is not None
        assert mode.id == "code"

    def test_no_match_returns_none(self):
        assert resolve_mode("Calculator", "com.apple.calculator", BUILTIN_MODES) is None

    def test_none_app_and_bundle_returns_none(self):
        assert resolve_mode(None, None, BUILTIN_MODES) is None

    def test_empty_strings_treated_as_no_info(self):
        assert resolve_mode("", "", BUILTIN_MODES) is None

    def test_empty_modes_list(self):
        assert resolve_mode("Mail", "com.apple.mail", []) is None

    def test_first_match_wins(self):
        modes = [
            Mode(id="first", name="First", app_patterns=["*mail*"]),
            Mode(id="second", name="Second", app_patterns=["*mail*"]),
        ]
        assert resolve_mode("Mail", None, modes).id == "first"

    def test_user_modes_take_precedence_when_prepended(self):
        user = Mode(id="mycode", name="My Code", app_patterns=["*code*"], format_style="code")
        combined = [user] + BUILTIN_MODES
        assert resolve_mode("Visual Studio Code", None, combined).id == "mycode"

    def test_mode_with_empty_patterns_never_matches(self):
        modes = [Mode(id="empty", name="Empty", app_patterns=[])]
        assert resolve_mode("anything", "any.bundle", modes) is None

    def test_match_when_only_bundle_matches(self):
        # App name does not match but bundle id does.
        modes = [Mode(id="x", name="X", app_patterns=["com.example.app"])]
        assert resolve_mode("Friendly Name", "com.example.app", modes).id == "x"


class TestModesFromConfig:
    def test_minimal_valid_mode(self):
        modes = modes_from_config([{"id": "custom"}])
        assert len(modes) == 1
        mode = modes[0]
        assert mode.id == "custom"
        assert mode.name == "custom"  # defaults to id
        assert mode.app_patterns == []
        assert mode.format_style == "none"

    def test_all_fields(self):
        modes = modes_from_config(
            [
                {
                    "id": "work",
                    "name": "Work Mode",
                    "app_patterns": ["*slack*", "com.acme.app"],
                    "format_style": "chat",
                    "llm_prompt": "Tidy it up. Return only the rewritten text.",
                    "auto_send": True,
                    "vocabulary": ["Kubernetes", "OAuth"],
                }
            ]
        )
        mode = modes[0]
        assert mode.id == "work"
        assert mode.name == "Work Mode"
        assert mode.app_patterns == ["*slack*", "com.acme.app"]
        assert mode.format_style == "chat"
        assert mode.auto_send is True
        assert mode.vocabulary == ["Kubernetes", "OAuth"]

    def test_name_defaults_to_id_when_blank(self):
        modes = modes_from_config([{"id": "x", "name": ""}])
        assert modes[0].name == "x"

    def test_invalid_format_style_falls_back_to_none(self, caplog):
        with caplog.at_level(logging.WARNING):
            modes = modes_from_config([{"id": "x", "format_style": "fancy"}])
        assert modes[0].format_style == "none"
        assert "unknown format_style" in caplog.text

    def test_non_string_llm_prompt_becomes_empty(self):
        modes = modes_from_config([{"id": "x", "llm_prompt": 123}])
        assert modes[0].llm_prompt == ""

    def test_app_patterns_filters_non_strings(self):
        modes = modes_from_config([{"id": "x", "app_patterns": ["*good*", 5, None, "", "*ok*"]}])
        assert modes[0].app_patterns == ["*good*", "*ok*"]

    def test_app_patterns_non_list_becomes_empty(self):
        modes = modes_from_config([{"id": "x", "app_patterns": "*notalist*"}])
        assert modes[0].app_patterns == []

    def test_vocabulary_filters_non_strings(self):
        modes = modes_from_config([{"id": "x", "vocabulary": ["a", 1, "b"]}])
        assert modes[0].vocabulary == ["a", "b"]

    def test_skips_entry_without_id(self, caplog):
        with caplog.at_level(logging.WARNING):
            modes = modes_from_config([{"name": "no id"}])
        assert modes == []
        assert "missing or empty 'id'" in caplog.text

    def test_skips_non_dict_entry(self, caplog):
        with caplog.at_level(logging.WARNING):
            modes = modes_from_config(["bad", {"id": "ok"}])
        assert len(modes) == 1
        assert modes[0].id == "ok"
        assert "not an object" in caplog.text

    def test_non_list_input_returns_empty(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert modes_from_config({"not": "a list"}) == []
        assert "not a list" in caplog.text

    def test_empty_list(self):
        assert modes_from_config([]) == []

    def test_preserves_order(self):
        modes = modes_from_config([{"id": "a"}, {"id": "b"}, {"id": "c"}])
        assert [m.id for m in modes] == ["a", "b", "c"]

    def test_config_modes_resolve(self):
        modes = modes_from_config([{"id": "term", "app_patterns": ["*terminal*"], "format_style": "code"}])
        assert resolve_mode("Terminal", None, modes).id == "term"
