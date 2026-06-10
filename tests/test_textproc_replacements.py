"""Tests for whisper_hud.textproc.replacements (personal dictionary)."""

import logging

import pytest

from whisper_hud.textproc.replacements import Rule, apply_replacements, rules_from_config


class TestRuleDataclass:
    def test_defaults(self):
        rule = Rule(pattern="foo", replacement="bar")
        assert rule.pattern == "foo"
        assert rule.replacement == "bar"
        assert rule.is_regex is False
        assert rule.case_sensitive is False
        assert rule.whole_word is True


class TestRulesFromConfig:
    def test_basic_valid_rule(self):
        rules = rules_from_config([{"pattern": "foo", "replacement": "bar"}])
        assert len(rules) == 1
        assert rules[0] == Rule(pattern="foo", replacement="bar")

    def test_all_fields_parsed(self):
        rules = rules_from_config(
            [
                {
                    "pattern": r"\d+",
                    "replacement": "#",
                    "is_regex": True,
                    "case_sensitive": True,
                    "whole_word": False,
                }
            ]
        )
        assert rules[0] == Rule(
            pattern=r"\d+",
            replacement="#",
            is_regex=True,
            case_sensitive=True,
            whole_word=False,
        )

    def test_missing_replacement_defaults_to_empty(self):
        rules = rules_from_config([{"pattern": "foo"}])
        assert rules[0].replacement == ""

    def test_skips_entry_without_pattern(self, caplog):
        with caplog.at_level(logging.WARNING):
            rules = rules_from_config([{"replacement": "bar"}])
        assert rules == []
        assert "missing or empty 'pattern'" in caplog.text

    def test_skips_entry_with_empty_pattern(self):
        assert rules_from_config([{"pattern": "", "replacement": "x"}]) == []

    def test_skips_non_string_pattern(self):
        assert rules_from_config([{"pattern": 123, "replacement": "x"}]) == []

    def test_skips_non_string_replacement(self, caplog):
        with caplog.at_level(logging.WARNING):
            rules = rules_from_config([{"pattern": "foo", "replacement": 5}])
        assert rules == []
        assert "must be a string" in caplog.text

    def test_skips_non_dict_entry(self, caplog):
        with caplog.at_level(logging.WARNING):
            rules = rules_from_config(["not a dict", {"pattern": "ok", "replacement": "y"}])
        assert len(rules) == 1
        assert rules[0].pattern == "ok"
        assert "not an object" in caplog.text

    def test_skips_invalid_regex(self, caplog):
        with caplog.at_level(logging.WARNING):
            rules = rules_from_config([{"pattern": "(", "replacement": "x", "is_regex": True}])
        assert rules == []
        assert "invalid regex" in caplog.text

    def test_non_list_input_returns_empty(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert rules_from_config({"not": "a list"}) == []
        assert "not a list" in caplog.text

    def test_empty_list(self):
        assert rules_from_config([]) == []

    def test_preserves_order(self):
        rules = rules_from_config(
            [
                {"pattern": "a", "replacement": "1"},
                {"pattern": "b", "replacement": "2"},
                {"pattern": "c", "replacement": "3"},
            ]
        )
        assert [r.pattern for r in rules] == ["a", "b", "c"]

    def test_truthy_coercion_of_flags(self):
        rules = rules_from_config(
            [{"pattern": "x", "replacement": "y", "is_regex": 1, "case_sensitive": 0, "whole_word": ""}]
        )
        assert rules[0].is_regex is True
        assert rules[0].case_sensitive is False
        assert rules[0].whole_word is False


class TestApplyReplacementsLiteral:
    def test_simple_literal_replacement(self):
        rules = [Rule(pattern="cat", replacement="dog")]
        assert apply_replacements("the cat", rules) == "the dog"

    def test_whole_word_does_not_match_substring(self):
        rules = [Rule(pattern="cat", replacement="dog", whole_word=True)]
        assert apply_replacements("category cat catalog", rules) == "category dog catalog"

    def test_whole_word_false_matches_substring(self):
        rules = [Rule(pattern="cat", replacement="dog", whole_word=False)]
        assert apply_replacements("category", rules) == "dogegory"

    def test_case_insensitive_by_default(self):
        rules = [Rule(pattern="gpt", replacement="GPT")]
        assert apply_replacements("gpt GpT GPT", rules) == "GPT GPT GPT"

    def test_case_sensitive(self):
        rules = [Rule(pattern="gpt", replacement="GPT", case_sensitive=True)]
        assert apply_replacements("gpt GpT", rules) == "GPT GpT"

    def test_multiple_occurrences_replaced(self):
        rules = [Rule(pattern="ok", replacement="OK")]
        assert apply_replacements("ok ok ok", rules) == "OK OK OK"

    def test_rules_apply_in_order_chained(self):
        # First rule produces text the second rule then transforms.
        rules = [
            Rule(pattern="a", replacement="b", whole_word=False),
            Rule(pattern="b", replacement="c", whole_word=False),
        ]
        assert apply_replacements("a", rules) == "c"

    def test_literal_special_regex_chars_are_escaped(self):
        # A '.' in a literal pattern must match a literal dot, not any char.
        rules = [Rule(pattern="a.b", replacement="X", whole_word=False)]
        assert apply_replacements("a.b axb", rules) == "X axb"

    def test_literal_replacement_with_backslashes_preserved(self):
        rules = [Rule(pattern="path", replacement=r"C:\new", whole_word=False)]
        assert apply_replacements("path", rules) == r"C:\new"

    def test_literal_replacement_with_dollar_and_backref_text_preserved(self):
        # Non-regex replacement text must not be interpreted as a group ref.
        rules = [Rule(pattern="price", replacement=r"\1 cost", whole_word=False)]
        assert apply_replacements("price", rules) == r"\1 cost"

    def test_whole_word_with_punctuation_boundary_pattern(self):
        # Pattern starting with non-word char: leading \b is dropped so it still
        # matches.
        rules = [Rule(pattern="@home", replacement="HOME", whole_word=True)]
        assert apply_replacements("ping @home now", rules) == "ping HOME now"

    def test_whole_word_pattern_with_internal_space(self):
        rules = [Rule(pattern="new york", replacement="NYC", whole_word=True)]
        assert apply_replacements("i live in new york today", rules) == "i live in NYC today"

    def test_unicode_text(self):
        rules = [Rule(pattern="cafe", replacement="café", whole_word=False)]
        assert apply_replacements("cafe", rules) == "café"


class TestApplyReplacementsRegex:
    def test_regex_replacement(self):
        rules = [Rule(pattern=r"\d+", replacement="#", is_regex=True)]
        assert apply_replacements("abc 123 def 4567", rules) == "abc # def #"

    def test_regex_with_backreference(self):
        rules = [Rule(pattern=r"(\w+)@(\w+)", replacement=r"\2.\1", is_regex=True)]
        assert apply_replacements("user@host", rules) == "host.user"

    def test_regex_case_sensitive(self):
        rules = [Rule(pattern=r"[a-z]+", replacement="X", is_regex=True, case_sensitive=True)]
        assert apply_replacements("abc ABC", rules) == "X ABC"

    def test_regex_case_insensitive_default(self):
        rules = [Rule(pattern=r"[a-z]+", replacement="X", is_regex=True)]
        assert apply_replacements("abc ABC", rules) == "X X"

    def test_regex_whole_word_ignored(self):
        # whole_word has no effect on regex rules; author controls anchoring.
        rules = [Rule(pattern="cat", replacement="dog", is_regex=True, whole_word=True)]
        assert apply_replacements("category", rules) == "dogegory"

    def test_regex_bad_backreference_during_apply_is_skipped(self, caplog):
        # Pattern compiles, but the replacement references a non-existent group.
        rules = [Rule(pattern=r"(a)", replacement=r"\2", is_regex=True)]
        with caplog.at_level(logging.WARNING):
            result = apply_replacements("a", rules)
        # Skipped rule -> text unchanged.
        assert result == "a"
        assert "during apply" in caplog.text


class TestApplyReplacementsEdgeCases:
    def test_empty_text_returns_empty(self):
        rules = [Rule(pattern="x", replacement="y")]
        assert apply_replacements("", rules) == ""

    def test_no_rules_returns_text(self):
        assert apply_replacements("hello", []) == "hello"

    def test_no_match_returns_unchanged(self):
        rules = [Rule(pattern="zzz", replacement="!")]
        assert apply_replacements("hello", rules) == "hello"

    @pytest.mark.parametrize(
        "text,pattern,replacement,expected",
        [
            ("hello world", "world", "earth", "hello earth"),
            ("a b c", "b", "B", "a B c"),
            ("repeat repeat", "repeat", "once", "once once"),
        ],
    )
    def test_parametrized_literal(self, text, pattern, replacement, expected):
        rules = [Rule(pattern=pattern, replacement=replacement)]
        assert apply_replacements(text, rules) == expected
