"""
Shared microphone-audio encoding for realtime websocket sessions.

All OpenAI realtime endpoints (transcription, translation, conversation)
consume base64-encoded 24 kHz mono PCM16 audio.
"""

from __future__ import annotations

import base64
import math
from typing import Any

import numpy as np
from scipy.signal import resample_poly

REALTIME_SAMPLE_RATE = 24000


def encode_pcm16_chunk(
    audio_chunk: Any,
    sample_rate: int,
    target_sample_rate: int = REALTIME_SAMPLE_RATE,
) -> tuple[str, float]:
    """Resample float32 microphone audio to mono PCM16 and base64-encode it.

    Returns ``(encoded_audio, duration_seconds)`` where ``encoded_audio`` is an
    empty string when the chunk is unusable (None, empty, or bad sample rate).
    """
    if audio_chunk is None or sample_rate <= 0:
        return "", 0.0

    chunk = np.asarray(audio_chunk, dtype=np.float32)
    if chunk.size == 0:
        return "", 0.0

    if chunk.ndim == 2:
        mono = chunk.mean(axis=1)
    else:
        mono = chunk.reshape(-1)

    mono = np.clip(mono, -1.0, 1.0)

    if sample_rate != target_sample_rate:
        gcd = math.gcd(sample_rate, target_sample_rate)
        up = target_sample_rate // gcd
        down = sample_rate // gcd
        mono = resample_poly(mono, up, down).astype(np.float32)

    # Clip AFTER resampling: resample_poly is a polyphase FIR that overshoots
    # (Gibbs ringing) on full-scale audio, pushing samples past +/-1.0. Casting
    # those directly to int16 wraps modularly (a loud peak flips to a large
    # negative value -> audible click), so saturate to the int16 range first.
    pcm16 = np.clip(np.round(mono * 32767.0), -32768.0, 32767.0).astype("<i2")
    encoded = base64.b64encode(pcm16.tobytes()).decode("ascii")
    duration_seconds = len(mono) / float(target_sample_rate)
    return encoded, duration_seconds


def decode_pcm16_chunk(encoded_audio: str) -> bytes:
    """Decode a base64 PCM16 payload from a realtime audio delta event."""
    if not encoded_audio:
        return b""
    try:
        return base64.b64decode(encoded_audio)
    except (ValueError, TypeError):
        return b""
