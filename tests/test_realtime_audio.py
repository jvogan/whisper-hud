"""Guard-rail tests for the shared realtime audio codec.

``encode_pcm16_chunk`` / ``decode_pcm16_chunk`` are the single seam every
OpenAI realtime endpoint (transcription, translation, voice assistant) pushes
microphone audio and pulls playback audio through, so their defensive no-ops
have outsized blast radius: a bad guard here would surface as a crash deep in a
websocket callback on three different features.
"""

import base64

import numpy as np

from whisper_hud.providers.realtime_audio import (
    REALTIME_SAMPLE_RATE,
    decode_pcm16_chunk,
    encode_pcm16_chunk,
)


def test_encode_rejects_none_chunk():
    assert encode_pcm16_chunk(None, REALTIME_SAMPLE_RATE) == ("", 0.0)


def test_encode_rejects_nonpositive_sample_rate():
    chunk = np.zeros(480, dtype=np.float32)
    assert encode_pcm16_chunk(chunk, 0) == ("", 0.0)
    assert encode_pcm16_chunk(chunk, -16000) == ("", 0.0)


def test_encode_rejects_empty_chunk():
    assert encode_pcm16_chunk(np.zeros(0, dtype=np.float32), REALTIME_SAMPLE_RATE) == ("", 0.0)


def test_encode_passthrough_at_native_rate_round_trips():
    # A quarter-scale ramp at the target rate needs no resampling, so it should
    # decode back to the same int16 samples the encoder produced.
    samples = np.linspace(-0.25, 0.25, 240, dtype=np.float32)
    encoded, duration = encode_pcm16_chunk(samples, REALTIME_SAMPLE_RATE)

    assert encoded  # non-empty
    assert duration == len(samples) / REALTIME_SAMPLE_RATE
    decoded = np.frombuffer(decode_pcm16_chunk(encoded), dtype="<i2")
    expected = np.clip(np.round(samples * 32767.0), -32768.0, 32767.0).astype("<i2")
    np.testing.assert_array_equal(decoded, expected)


def test_encode_downmixes_stereo_to_mono():
    # Two channels (L=+0.5, R=-0.5) average to ~0; the encoded mono stream is
    # half the per-channel sample count.
    stereo = np.column_stack([np.full(120, 0.5, dtype=np.float32), np.full(120, -0.5, dtype=np.float32)])
    encoded, _ = encode_pcm16_chunk(stereo, REALTIME_SAMPLE_RATE)
    decoded = np.frombuffer(decode_pcm16_chunk(encoded), dtype="<i2")
    assert len(decoded) == 120
    assert np.all(np.abs(decoded) <= 1)  # averaged to silence


def test_decode_empty_string_is_empty_bytes():
    assert decode_pcm16_chunk("") == b""


def test_decode_invalid_base64_is_empty_bytes():
    # 5 valid-alphabet chars can never be a well-formed base64 payload.
    assert decode_pcm16_chunk("AAAAA") == b""
    assert decode_pcm16_chunk("@@@ not base64 @@@") == b""


def test_decode_valid_base64_round_trips_known_bytes():
    raw = bytes(range(16))
    assert decode_pcm16_chunk(base64.b64encode(raw).decode("ascii")) == raw
