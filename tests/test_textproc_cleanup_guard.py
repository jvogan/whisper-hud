"""Tests for whisper_hud.textproc.cleanup_guard (anti-paraphrase guardrail)."""

import pytest

from whisper_hud.textproc.cleanup_guard import DEFAULT_FILLERS, cleanup_is_safe, words


class TestWords:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Hello, world!", ["hello", "world"]),
            ("Don't stop", ["don't", "stop"]),
            ("UPPER lower MiXeD", ["upper", "lower", "mixed"]),
            ("a  b   c", ["a", "b", "c"]),
            ("punctuation... only?!", ["punctuation", "only"]),
            ("it's a test's case", ["it's", "a", "test's", "case"]),
            ("", []),
            ("   ", []),
            ("123 abc 4.5", ["123", "abc", "4", "5"]),
        ],
    )
    def test_words(self, text, expected):
        assert words(text) == expected

    def test_underscore_is_not_word_char(self):
        # _WORD_RE uses [^\W_], so underscores split tokens.
        assert words("foo_bar") == ["foo", "bar"]


class TestDefaultFillers:
    def test_contains_common_fillers(self):
        for filler in ("um", "uh", "like", "you know", "i mean"):
            assert filler in DEFAULT_FILLERS


class TestPunctuationAndCaseChangesAreFree:
    def test_punctuation_only_fix_passes(self):
        safe, reason = cleanup_is_safe("hello world", "Hello, world.")
        assert safe is True
        assert "formatting only" in reason

    def test_case_only_change_passes(self):
        safe, _ = cleanup_is_safe("the quick brown fox", "The Quick Brown Fox")
        assert safe is True

    def test_whitespace_only_change_passes(self):
        safe, _ = cleanup_is_safe("a  b   c", "a b c")
        assert safe is True

    def test_added_punctuation_passes(self):
        safe, _ = cleanup_is_safe("yes no maybe", "Yes. No. Maybe?")
        assert safe is True

    def test_identical_strings_pass(self):
        safe, reason = cleanup_is_safe("same text here", "same text here")
        assert safe is True
        assert "no word-level changes" in reason


class TestFillerRemovalIsFree:
    def test_single_filler_removed_passes(self):
        safe, reason = cleanup_is_safe("um the report is ready", "the report is ready")
        assert safe is True
        assert "filler" in reason

    def test_multiple_scattered_fillers_removed_passes(self):
        safe, _ = cleanup_is_safe(
            "um so like the thing you know is uh here",
            "so the thing is here",
        )
        assert safe is True

    def test_multiword_filler_removed_passes(self):
        safe, _ = cleanup_is_safe("the plan you know is solid", "the plan is solid")
        assert safe is True

    def test_i_mean_multiword_filler_passes(self):
        safe, _ = cleanup_is_safe("we should i mean go now", "we should go now")
        assert safe is True

    def test_all_words_were_filler_removed_to_empty_passes(self):
        safe, reason = cleanup_is_safe("um uh you know", "")
        assert safe is True
        assert "filler" in reason

    def test_custom_allowed_fillers(self):
        # "basically" is not a default filler, but caller can allow it.
        safe, _ = cleanup_is_safe(
            "basically the answer is yes",
            "the answer is yes",
            allowed_fillers={"basically"},
        )
        assert safe is True

    def test_default_fillers_not_applied_when_custom_set_given(self):
        # With a custom set that excludes "um", removing "um" is now a real
        # deletion and (as the only word besides content) should be counted.
        safe, _ = cleanup_is_safe(
            "um the answer is yes",
            "the answer is yes",
            allowed_fillers={"basically"},
            max_changed_words=0,
        )
        assert safe is False


class TestParaphraseIsRejected:
    def test_aggressive_paraphrase_fails(self):
        safe, reason = cleanup_is_safe(
            "the cat sat on the mat",
            "a feline rested upon the rug",
        )
        assert safe is False
        assert "exceeds" in reason or "too" in reason

    def test_sentence_reorder_fails(self):
        safe, _ = cleanup_is_safe(
            "first we eat then we sleep then we work",
            "then we work then we sleep first we eat",
        )
        assert safe is False

    def test_inserting_new_content_fails(self):
        safe, reason = cleanup_is_safe(
            "send it",
            "please kindly send it over to the team right away immediately now",
        )
        assert safe is False

    def test_replacing_words_fails(self):
        safe, _ = cleanup_is_safe(
            "i went to the store to buy bread and milk",
            "i drove to the shop to grab loaves and cheese",
        )
        assert safe is False

    def test_deleting_real_content_fails(self):
        safe, _ = cleanup_is_safe(
            "the meeting is at three pm in the main conference room",
            "the meeting",
            max_changed_words=3,
        )
        assert safe is False


class TestThresholds:
    def test_small_change_within_tolerance_passes(self):
        # One inserted word out of many -> under both caps.
        original = "the report covers sales numbers for the quarter in detail"
        cleaned = "the report covers all sales numbers for the quarter in detail"
        safe, reason = cleanup_is_safe(original, cleaned)
        assert safe is True
        assert "within tolerance" in reason

    def test_max_changed_words_cap_enforced(self):
        # Big absolute change but small ratio (long original) -> still fails on
        # the absolute cap.
        original = " ".join(["word"] * 200)
        cleaned = " ".join(["word"] * 200 + ["extra"] * 10)
        safe, reason = cleanup_is_safe(original, cleaned, max_changed_words=8, max_changed_ratio=0.9)
        assert safe is False
        assert "max_changed_words" in reason

    def test_max_changed_ratio_cap_enforced(self):
        # Small absolute count but high ratio (short original) -> fails on ratio.
        safe, reason = cleanup_is_safe(
            "yes",
            "yes indeed friend",
            max_changed_words=100,
            max_changed_ratio=0.18,
        )
        assert safe is False
        assert "max_changed_ratio" in reason

    def test_custom_lenient_thresholds_allow_more(self):
        original = "the cat sat on the mat"
        cleaned = "the cat sat quietly on the mat"
        safe, _ = cleanup_is_safe(original, cleaned, max_changed_ratio=0.9, max_changed_words=50)
        assert safe is True


class TestEdgeCases:
    def test_both_empty_passes(self):
        safe, _ = cleanup_is_safe("", "")
        assert safe is True

    def test_empty_original_with_added_words_fails(self):
        safe, reason = cleanup_is_safe("", "fabricated content")
        assert safe is False
        assert "empty input" in reason

    def test_empty_original_stays_empty_passes(self):
        safe, _ = cleanup_is_safe("", "  ...  ")
        assert safe is True

    def test_cleaned_emptied_non_filler_fails(self):
        safe, reason = cleanup_is_safe("important data here", "")
        assert safe is False
        assert "all content" in reason

    def test_reason_is_human_readable_string(self):
        _, reason = cleanup_is_safe("hello there", "hello there friend")
        assert isinstance(reason, str)
        assert reason

    def test_punctuation_only_original_and_cleaned(self):
        safe, _ = cleanup_is_safe("!!!", "???")
        assert safe is True
