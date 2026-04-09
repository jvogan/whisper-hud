"""Tests for the OpenAI Realtime transcription provider."""

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from whisper_hud.providers.openai_realtime import OpenAIRealtimeProvider, OpenAIRealtimeSession


def _build_session(
    *,
    model: str = "gpt-4o-mini-transcribe",
    language: str | None = None,
    prompt: str | None = None,
):
    partials: list[str] = []
    finals = []
    errors = []
    ready = []

    with patch("whisper_hud.providers.openai_realtime.OpenAI"):
        session = OpenAIRealtimeSession(
            api_key="sk-test",
            model=model,
            provider_name="openai_realtime",
            cost_per_minute=0.003,
            on_partial=partials.append,
            on_final=finals.append,
            on_error=errors.append,
            on_ready=lambda: ready.append(True),
            language=language,
            prompt=prompt,
        )

    return session, partials, finals, errors, ready


def test_session_builds_expected_transcription_payload():
    """Realtime sessions should use the transcription session schema from the API docs."""
    session, _, _, _, _ = _build_session(language="en", prompt="Use punctuation.")

    assert session._build_session_update() == {
        "type": "transcription",
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "noise_reduction": {"type": "near_field"},
                "transcription": {
                    "model": "gpt-4o-mini-transcribe",
                    "language": "en",
                    "prompt": "Use punctuation.",
                },
                "turn_detection": None,
            }
        },
    }


def test_session_flushes_buffer_and_commits_after_ready_when_stop_was_requested():
    """Buffered audio should flush on session readiness and commit exactly once."""
    session, _, _, _, ready = _build_session()
    session._connection = MagicMock()

    audio_chunk = np.array([0.25, -0.25, 0.5, -0.5], dtype=np.float32)
    session.push_audio(audio_chunk, sample_rate=24000)
    session.request_stop()

    assert len(session._pending_audio) == 1
    assert session._commit_sent is False

    session._handle_event(SimpleNamespace(type="session.updated"))

    assert ready == [True]
    assert session.is_ready() is True
    session._connection.input_audio_buffer.append.assert_called_once()
    session._connection.input_audio_buffer.commit.assert_called_once()
    assert session._commit_sent is True


def test_session_emits_partials_and_final_for_the_committed_item():
    """Incremental delta events should accumulate into a final result."""
    session, partials, finals, _, _ = _build_session(language="en")
    session._sent_audio_seconds = 5.0

    session._handle_event(SimpleNamespace(type="input_audio_buffer.committed", item_id="item-1"))
    session._handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.delta",
            item_id="item-1",
            delta="hel",
        )
    )
    session._handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.delta",
            item_id="item-1",
            delta="lo",
        )
    )
    session._handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item-1",
            transcript=" hello ",
            usage={"seconds": 2.5},
        )
    )

    assert partials == ["hel", "hello"]
    assert len(finals) == 1
    assert finals[0].text == "hello"
    assert finals[0].duration_seconds == pytest.approx(2.5)
    assert finals[0].cost_estimate == pytest.approx(2.5 / 60.0 * 0.003)
    assert finals[0].language == "en"


def test_session_ignores_completed_events_for_other_items_and_falls_back_to_partial_text():
    """A one-turn session should only finalize the item created by its commit event."""
    session, partials, finals, _, _ = _build_session()

    session._handle_event(SimpleNamespace(type="input_audio_buffer.committed", item_id="item-1"))
    session._handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.delta",
            item_id="item-1",
            delta="hello",
        )
    )
    session._handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item-2",
            transcript="wrong item",
            usage={"seconds": 9.0},
        )
    )
    session._handle_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item-1",
            transcript="",
            usage=None,
        )
    )

    assert partials == ["hello"]
    assert len(finals) == 1
    assert finals[0].text == "hello"


def test_encode_audio_chunk_resamples_stereo_audio_to_24khz_pcm16():
    """Live audio chunks should be resampled and encoded as mono PCM16."""
    stereo = np.ones((480, 2), dtype=np.float32)

    encoded, duration_seconds = OpenAIRealtimeSession._encode_audio_chunk(stereo, sample_rate=48000)

    assert len(encoded) > 0
    assert duration_seconds == pytest.approx(0.01, rel=1e-3)
    pcm_bytes = np.frombuffer(base64.b64decode(encoded), dtype="<i2")
    assert pcm_bytes.shape == (240,)


def test_provider_normalizes_models_and_uses_batch_fallback_for_supported_model():
    """The realtime provider should expose the current documented model slugs and map latest-only aliases for batch fallback."""
    default_provider = OpenAIRealtimeProvider(model="unsupported")
    assert default_provider.get_current_model() == "gpt-4o-mini-transcribe"
    assert OpenAIRealtimeProvider(model="gpt-4o-transcribe-latest").get_current_model() == "gpt-4o-transcribe-latest"

    model_ids = [model["id"] for model in default_provider.get_models()]
    assert model_ids == ["gpt-4o-mini-transcribe", "gpt-4o-transcribe-latest", "gpt-4o-transcribe"]

    with patch("whisper_hud.providers.openai_realtime.OpenAITranscribeProvider") as batch_cls:
        batch_cls.return_value.transcribe.return_value = SimpleNamespace(
            text="hello",
            duration_seconds=1.25,
            cost_estimate=0.006,
            model="gpt-4o-transcribe",
            language="en",
        )
        provider = OpenAIRealtimeProvider(model="gpt-4o-transcribe-latest")
        result = provider.transcribe(b"wav")

    batch_cls.assert_called_once_with(model="gpt-4o-transcribe")
    assert result.provider == "openai_realtime"
    assert result.model == "gpt-4o-transcribe"
    assert result.text == "hello"


def test_provider_create_live_session_uses_openai_key_and_selected_model():
    """Provider session creation should pass through the configured OpenAI key and session options."""
    with patch("whisper_hud.providers.openai_realtime.get_api_key", return_value="sk-test"):
        with patch("whisper_hud.providers.openai_realtime.OpenAIRealtimeSession") as session_cls:
            expected_session = object()
            session_cls.return_value = expected_session

            provider = OpenAIRealtimeProvider(model="gpt-4o-transcribe")
            session = provider.create_live_session(
                on_partial=lambda _: None,
                on_final=lambda _: None,
                on_error=lambda _: None,
                on_ready=lambda: None,
                language="en",
                prompt="Use punctuation.",
            )

    assert session is expected_session
    session_cls.assert_called_once()
    kwargs = session_cls.call_args.kwargs
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["model"] == "gpt-4o-transcribe"
    assert kwargs["cost_per_minute"] == pytest.approx(0.006)
    assert kwargs["language"] == "en"
    assert kwargs["prompt"] == "Use punctuation."


def test_realtime_session_pins_openai_endpoints_and_disables_env_routing():
    """Realtime sessions should pin the official HTTP and websocket endpoints."""
    with patch("whisper_hud.providers.openai_realtime.OpenAI") as openai_cls:
        openai_cls.return_value = MagicMock()

        OpenAIRealtimeSession(
            api_key="sk-test",
            model="gpt-4o-mini-transcribe",
            provider_name="openai_realtime",
            cost_per_minute=0.003,
            on_partial=lambda _text: None,
            on_final=lambda _result: None,
            on_error=lambda _exc: None,
        )

    kwargs = openai_cls.call_args.kwargs
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["websocket_base_url"] == "wss://api.openai.com/v1"
    assert kwargs["http_client"].trust_env is False
    assert kwargs["http_client"].follow_redirects is False
    kwargs["http_client"].close()
