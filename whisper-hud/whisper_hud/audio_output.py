"""
Streaming PCM16 audio playback via sounddevice.

Plays raw 24 kHz mono PCM16 audio arriving as byte chunks from a realtime
conversation. Designed for low-latency barge-in: ``flush()`` drops queued
audio and interrupts the chunk currently being written so the assistant can
be cut off the instant the user starts speaking.
"""

from __future__ import annotations

import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from .logging_config import get_logger

logger = get_logger("audio_output")

# Cap each stream.write() so flush() can interrupt mid-chunk within a few
# milliseconds at 24 kHz; the flush flag is checked between slices.
_MAX_WRITE_FRAMES = 2400

# Sentinel pushed onto the queue to wake the playback thread for shutdown.
_STOP = object()


class PCM16Player:
    """Plays raw PCM16 byte chunks on a single background stream."""

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self._queue: "queue.Queue[object]" = queue.Queue()
        self._stream: Optional[sd.OutputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._active = False
        self._flush = threading.Event()
        # Monotonic flush generation. enqueue() stamps each item with the
        # generation current at enqueue time; flush() bumps it. The playback
        # thread drops any item stamped before the latest flush, which closes
        # the window where a chunk pulled (or enqueued) just before flush()
        # could still play after barge-in.
        self._generation = 0

    def start(self) -> None:
        """Open the output stream and start the playback thread (idempotent)."""
        with self._lock:
            if self._active:
                return
            try:
                self._stream = sd.OutputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                )
                self._stream.start()
            except Exception:
                logger.warning("Failed to open audio output stream", exc_info=True)
                self._stream = None
                return

            self._active = True
            self._flush.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def enqueue(self, pcm_bytes: bytes) -> None:
        """Queue PCM16 bytes for playback (no-op after stop or for empty input)."""
        if not pcm_bytes:
            return
        with self._lock:
            if not self._active:
                return
            generation = self._generation
        self._queue.put((generation, pcm_bytes))

    def flush(self) -> None:
        """Drop all queued audio and interrupt the current write (barge-in)."""
        # Bump the generation first: every item already enqueued is now stale,
        # so even a chunk the playback thread has already pulled is dropped by
        # its generation check before any of it can be written.
        with self._lock:
            self._generation += 1
        # Signal the writer to abandon the chunk it is slicing through.
        self._flush.set()
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            # Preserve a pending stop sentinel; only discard audio.
            if item is _STOP:
                self._queue.put(_STOP)
                break

    def stop(self) -> None:
        """Flush, stop the thread, and close the stream (idempotent, never raises)."""
        with self._lock:
            if not self._active:
                return
            self._active = False
            thread = self._thread
            self._thread = None

        self.flush()
        self._queue.put(_STOP)

        if thread is not None:
            thread.join(timeout=3.0)

        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                logger.debug("Failed to abort audio output stream", exc_info=True)
            try:
                stream.close()
            except Exception:
                logger.debug("Failed to close audio output stream", exc_info=True)

    def is_active(self) -> bool:
        """Return True while the playback thread is running."""
        return self._active

    def _run(self) -> None:
        """Pull byte chunks from the queue and write them to the stream."""
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if not isinstance(item, tuple):
                continue
            generation, payload = item
            # Drop anything enqueued before the latest flush, then clear the
            # flag so the next (post-flush) chunk is allowed to play.
            if generation != self._current_generation():
                self._flush.clear()
                continue
            self._flush.clear()
            if not isinstance(payload, (bytes, bytearray)):
                continue
            try:
                self._write_chunk(generation, bytes(payload))
            except Exception:
                # One bad chunk must never kill the thread; the rest of the
                # conversation must keep playing.
                logger.debug("Audio output chunk failed; skipping", exc_info=True)

    def _current_generation(self) -> int:
        with self._lock:
            return self._generation

    def _write_chunk(self, generation: int, pcm_bytes: bytes) -> None:
        """Write one chunk in small slices, honoring the flush flag between them."""
        # Tolerate an odd byte count (truncated/mangled frame): drop the dangling
        # trailing byte so np.frombuffer never raises and mutes the rest of the
        # conversation.
        if len(pcm_bytes) & 1:
            pcm_bytes = pcm_bytes[: len(pcm_bytes) & ~1]
        samples = np.frombuffer(pcm_bytes, dtype="<i2")
        stream = self._stream
        if stream is None:
            return
        for start in range(0, len(samples), _MAX_WRITE_FRAMES):
            # Re-check before EVERY slice (including the first): a flush that
            # bumps the generation while this chunk is in-hand must abandon the
            # rest, so no pre-barge-in audio reaches the device after flush().
            if self._flush.is_set() or generation != self._current_generation():
                return
            slice_ = samples[start : start + _MAX_WRITE_FRAMES]
            try:
                stream.write(slice_)
            except Exception:
                logger.debug("Audio output write failed", exc_info=True)
                return

    def _drain(self) -> None:
        """Discard any remaining queued audio without writing it."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
