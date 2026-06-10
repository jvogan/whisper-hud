"""Tests for the local-only LLM cleanup engine."""

from unittest.mock import MagicMock, patch

import requests

from whisper_hud.cleanup import LocalCleanupEngine, merge_vocabulary


def _response(status=200, json_payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_payload if json_payload is not None else {}
    return resp


class TestMergeVocabulary:
    def test_merges_and_dedupes_order_stably(self):
        merged = merge_vocabulary(["alpha", "beta"], ["beta", "gamma"])
        assert merged == ["alpha", "beta", "gamma"]

    def test_drops_blank_and_non_strings(self):
        merged = merge_vocabulary(["alpha", "", "  ", 5, None], ["beta"])
        assert merged == ["alpha", "beta"]

    def test_caps_total_entries(self):
        big = [f"w{i}" for i in range(500)]
        merged = merge_vocabulary(big, ["extra"], cap=200)
        assert len(merged) == 200
        assert "extra" not in merged  # cap reached before second source

    def test_handles_none_sources(self):
        assert merge_vocabulary(None, ["a"], None) == ["a"]
        assert merge_vocabulary() == []


class TestIsAvailable:
    def test_available_when_tags_ok(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.get.return_value = _response(200, {"models": []})
        engine._http_session = session

        assert engine.is_available() is True
        # Quick probe budget passed through.
        _, kwargs = session.get.call_args
        assert kwargs["timeout"] == 0.5
        assert kwargs["allow_redirects"] is False

    def test_unavailable_on_connection_error(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError()
        engine._http_session = session

        assert engine.is_available() is False

    def test_unavailable_on_non_200(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.get.return_value = _response(503, {})
        engine._http_session = session

        assert engine.is_available() is False

    def test_session_disables_proxies(self):
        engine = LocalCleanupEngine()
        session = engine._get_http_session()
        assert session.trust_env is False


class TestPickModel:
    def test_uses_configured_when_valid(self):
        engine = LocalCleanupEngine()
        # No network call should be needed when configured is set.
        assert engine.pick_model("qwen3:8b") == "qwen3:8b"

    def test_rejects_invalid_configured_then_probes(self):
        engine = LocalCleanupEngine()
        engine.installed_models = MagicMock(return_value=["llama3.2:3b"])
        # "bad name" is invalid -> falls through to installed detection.
        assert engine.pick_model("bad name!") == "llama3.2:3b"

    def test_prefers_smallest_decent_present(self):
        engine = LocalCleanupEngine()
        engine.installed_models = MagicMock(return_value=["gemma3:4b", "qwen3:1.7b", "llama3.2:3b"])
        # qwen3:1.7b is first in the preference list.
        assert engine.pick_model(None) == "qwen3:1.7b"

    def test_prefix_match_for_base_name(self):
        engine = LocalCleanupEngine()
        engine.installed_models = MagicMock(return_value=["llama3.2:latest"])
        # Preference "llama3.2:3b" misses exact, but base "llama3.2" prefix hits.
        assert engine.pick_model(None) == "llama3.2:latest"

    def test_falls_back_to_first_installed(self):
        engine = LocalCleanupEngine()
        engine.installed_models = MagicMock(return_value=["exotic-model:7b"])
        assert engine.pick_model(None) == "exotic-model:7b"

    def test_none_when_nothing_installed(self):
        engine = LocalCleanupEngine()
        engine.installed_models = MagicMock(return_value=[])
        assert engine.pick_model(None) is None


class TestCleanup:
    def test_success_returns_cleaned_text(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.return_value = _response(200, {"response": "Hello, world."})
        engine._http_session = session

        out = engine.cleanup("hello world", prompt="fix it", model="qwen3:1.7b", timeout=5.0)
        assert out == "Hello, world."
        # stream disabled, no redirects, timeout forwarded.
        _, kwargs = session.post.call_args
        assert kwargs["stream"] is False
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 5.0
        assert kwargs["json"]["model"] == "qwen3:1.7b"
        assert kwargs["json"]["system"] == "fix it"
        assert kwargs["json"]["prompt"] == "hello world"

    def test_server_down_returns_none(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.side_effect = requests.exceptions.ConnectionError()
        engine._http_session = session

        assert engine.cleanup("hello", prompt="p", model="qwen3:1.7b", timeout=5.0) is None

    def test_timeout_returns_none(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.side_effect = requests.exceptions.Timeout()
        engine._http_session = session

        assert engine.cleanup("hello", prompt="p", model="qwen3:1.7b", timeout=5.0) is None

    def test_http_error_returns_none(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.return_value = _response(500, {})
        engine._http_session = session

        assert engine.cleanup("hello", prompt="p", model="qwen3:1.7b", timeout=5.0) is None

    def test_empty_input_returns_none(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        engine._http_session = session
        assert engine.cleanup("   ", prompt="p", model="qwen3:1.7b", timeout=5.0) is None
        session.post.assert_not_called()

    def test_invalid_model_returns_none_without_request(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        engine._http_session = session
        assert engine.cleanup("hello", prompt="p", model="bad name!", timeout=5.0) is None
        session.post.assert_not_called()

    def test_guardrail_unsafe_returns_original(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        # Model paraphrases heavily -> guardrail should reject and we keep original.
        session.post.return_value = _response(
            200, {"response": "Completely different sentence with new fabricated words everywhere."}
        )
        engine._http_session = session

        original = "turn left at the next street"
        out = engine.cleanup(original, prompt="p", model="qwen3:1.7b", timeout=5.0)
        assert out == original

    def test_default_prompt_used_when_blank(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.return_value = _response(200, {"response": "Hello world"})
        engine._http_session = session

        engine.cleanup("hello world", prompt="", model="qwen3:1.7b", timeout=5.0)
        _, kwargs = session.post.call_args
        # Falls back to the default formatting-only prompt.
        assert "Return only the rewritten text." in kwargs["json"]["system"]

    def test_strips_wrapping_quotes(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.return_value = _response(200, {"response": '"hello world"'})
        engine._http_session = session

        out = engine.cleanup("hello world", prompt="p", model="qwen3:1.7b", timeout=5.0)
        assert out == "hello world"

    def test_blank_response_returns_none(self):
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.return_value = _response(200, {"response": "   "})
        engine._http_session = session

        assert engine.cleanup("hello world", prompt="p", model="qwen3:1.7b", timeout=5.0) is None

    def test_never_logs_transcript_at_info(self):
        """Cleanup must not leak transcript contents at INFO level."""
        engine = LocalCleanupEngine()
        session = MagicMock()
        session.post.return_value = _response(200, {"response": "Hello world."})
        engine._http_session = session

        with patch("whisper_hud.cleanup.logger") as mock_logger:
            engine.cleanup("super secret words", prompt="p", model="qwen3:1.7b", timeout=5.0)
            for call in mock_logger.info.call_args_list:
                rendered = " ".join(str(a) for a in call.args)
                assert "super secret words" not in rendered
