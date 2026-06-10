"""Tests for streaming PCM16 audio playback."""

import threading
import time

import numpy as np
from unittest.mock import patch


class FakeOutputStream:
    """Records every write so tests can inspect what reached the device."""

    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.writes: list[np.ndarray] = []
        self.closed = False
        self.aborted = False
        self._lock = threading.Lock()
        self.close_raises = False
        FakeOutputStream.last_instance = self

    def start(self):
        return None

    def write(self, data):
        with self._lock:
            self.writes.append(np.asarray(data).copy())

    def abort(self):
        self.aborted = True

    def close(self):
        if self.close_raises:
            raise RuntimeError("close boom")
        self.closed = True

    def total_samples(self):
        with self._lock:
            return int(sum(arr.size for arr in self.writes))


def _pcm(values):
    """Build little-endian PCM16 bytes from int sample values."""
    return np.array(values, dtype="<i2").tobytes()


def _wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_start_is_idempotent():
    """A second start() must not open a second stream or thread."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        thread = player._thread
        stream = player._stream
        player.start()

        assert player._thread is thread
        assert player._stream is stream
        player.stop()


def test_enqueue_writes_int16_arrays_to_stream():
    """Queued bytes should arrive at the stream as int16 numpy arrays."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        player.enqueue(_pcm([1, 2, 3, 4]))

        stream = FakeOutputStream.last_instance
        assert _wait_until(lambda: stream.total_samples() == 4)
        written = np.concatenate(stream.writes)
        assert written.dtype == np.dtype("int16")
        np.testing.assert_array_equal(written, np.array([1, 2, 3, 4], dtype="<i2"))
        player.stop()


def test_flush_drops_queued_audio():
    """After flush(), audio queued before the flush must never be written."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance

        # Block the writer on a sentinel value so the queue backs up.
        gate = threading.Event()
        original_write = stream.write

        def gated_write(data):
            gate.wait(2.0)
            original_write(data)

        stream.write = gated_write

        player.enqueue(_pcm([100]))  # first chunk, writer parks on the gate
        # Give the writer a moment to pull the first chunk and park on the gate.
        time.sleep(0.05)
        # Queue several more chunks that flush should discard.
        player.enqueue(_pcm([200]))
        player.enqueue(_pcm([201]))
        player.enqueue(_pcm([202]))

        player.flush()
        stream.write = original_write
        gate.set()

        # Let the thread settle; only the very first chunk may have been written.
        assert _wait_until(lambda: stream.total_samples() >= 1)
        time.sleep(0.1)
        written = np.concatenate(stream.writes) if stream.writes else np.array([], dtype="<i2")
        assert 200 not in written.tolist()
        assert 201 not in written.tolist()
        assert 202 not in written.tolist()
        player.stop()


def test_write_slice_size_is_capped():
    """No single stream.write() may exceed the 2400-frame slice cap."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance

        # 6000 frames must be split into multiple writes of <= 2400.
        player.enqueue(_pcm(list(range(6000))))
        assert _wait_until(lambda: stream.total_samples() == 6000)
        assert len(stream.writes) >= 3
        assert all(arr.size <= 2400 for arr in stream.writes)
        player.stop()


def test_stop_is_idempotent_and_never_raises_even_if_close_raises():
    """stop() joins the thread, survives a failing close(), and is repeatable."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance
        stream.close_raises = True
        thread = player._thread

        player.stop()  # must not raise despite close() raising
        assert player.is_active() is False
        assert thread is not None and not thread.is_alive()

        player.stop()  # second stop is a safe no-op
        assert player.is_active() is False


def test_enqueue_after_stop_is_a_no_op():
    """Audio enqueued after stop() must not be written anywhere."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance
        player.stop()

        player.enqueue(_pcm([7, 7, 7]))
        time.sleep(0.05)
        assert stream.total_samples() == 0


def test_empty_enqueue_is_ignored():
    """Empty byte input is dropped silently."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance
        player.enqueue(b"")
        time.sleep(0.05)
        assert stream.total_samples() == 0
        player.stop()


def test_flush_interrupts_chunk_mid_write():
    """flush() during a long chunk abandons its remaining slices (barge-in)."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance

        # The write of the FIRST slice triggers a barge-in flush(); the
        # remaining slices of the same chunk must never be written.
        first_write_done = threading.Event()
        original_write = stream.write

        def flushing_write(data):
            original_write(data)
            if not first_write_done.is_set():
                first_write_done.set()
                player.flush()

        stream.write = flushing_write

        # 20 slices worth (2400-frame cap) in a SINGLE chunk (in-range int16).
        player.enqueue(_pcm([1000] * 48000))

        assert _wait_until(lambda: first_write_done.is_set())
        # Let any (erroneously) un-interrupted writes land.
        time.sleep(0.1)
        # Only the first slice should have been written; the chunk was cut off.
        assert stream.total_samples() <= 2400
        assert len(stream.writes) == 1
        player.stop()


def test_odd_length_chunk_does_not_kill_playback_thread():
    """An odd-length PCM chunk must not poison the thread or mute later audio."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance
        thread = player._thread

        # A 3-byte (odd) chunk: a truncated/mangled frame from the network.
        # Without the length-normalization fix, np.frombuffer raises and the
        # broad except in _run terminates the playback thread for good.
        player.enqueue(b"\x01\x02\x03")
        # A subsequent valid chunk must still reach the stream.
        player.enqueue(_pcm([7, 8, 9, 10]))

        # The valid 4-sample chunk must arrive (the odd chunk may contribute its
        # one whole sample after the dangling byte is dropped).
        assert _wait_until(lambda: stream.total_samples() >= 4)
        time.sleep(0.05)
        assert thread is not None and thread.is_alive()
        assert player.is_active() is True
        written = np.concatenate(stream.writes).tolist()
        # The valid chunk's samples reached the device intact (as a contiguous run).
        assert [7, 8, 9, 10] == written[-4:]
        player.stop()


def test_chunk_pulled_before_flush_in_clear_gap_is_dropped():
    """A flush landing after the writer pulls a chunk (the pull/clear gap) must
    still drop that chunk -- a single-slice pre-barge-in delta must not play."""
    with patch("sounddevice.OutputStream", FakeOutputStream):
        from whisper_hud.audio_output import PCM16Player

        player = PCM16Player()
        player.start()
        stream = FakeOutputStream.last_instance

        # Seam: park the writer in the pull/clear gap (after it has pulled the
        # chunk, before it decides whether to write it) until a barge-in flush()
        # has fired. This is the exact window the old clear-after-get code lost.
        pulled = threading.Event()
        flushed = threading.Event()
        original = player._current_generation
        first = {"done": False}

        def gated_generation():
            if not first["done"]:
                first["done"] = True
                pulled.set()
                flushed.wait(2.0)
            return original()

        player._current_generation = gated_generation

        # A single-slice chunk: the common ~100ms delta. Under the old code its
        # one slice plays in full because the cleared flag is never re-seen.
        player.enqueue(_pcm([123] * 100))
        assert pulled.wait(2.0), "writer never pulled the chunk"

        # Barge-in arrives while the chunk is in-hand, in the gap.
        player.flush()
        flushed.set()

        time.sleep(0.1)
        assert stream.total_samples() == 0
        assert 123 not in (np.concatenate(stream.writes).tolist() if stream.writes else [])

        # A fresh chunk enqueued AFTER the flush still plays normally.
        player.enqueue(_pcm([11, 12]))
        assert _wait_until(lambda: stream.total_samples() == 2)
        player.stop()
