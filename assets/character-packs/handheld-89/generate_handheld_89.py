#!/usr/bin/env python3
"""
Deterministic generator for the **handheld-89** WhisperHUD character pack.

A chunky 1989-era monochrome handheld console rendered in the classic 4-shade
green LCD palette. The console body *is* the character: a rounded-corner shell
with a screen "face" that shows the current state, a d-pad, and two action
buttons below.

Art is authored on a 32x32 logical pixel grid (RGBA, transparent background),
then upscaled x4 with ``Image.NEAREST`` to a crisp 128px pixel-art PNG. Every
pixel uses the strict 4-shade green DMG palette plus a minimal neutral shell
colour. No gradients, no anti-aliasing, 1px dark outlines.

Sounds are pure square-wave chiptune (22050 Hz, mono, 16-bit PCM) authored with
the stdlib ``wave`` module + numpy. Original melodies only.

Run with the repo venv::

    .venv/bin/python assets/character-packs/handheld-89/generate_handheld_89.py

Everything here is deterministic: no unseeded randomness. The faux-static in the
error state uses a fixed checkerboard/bit pattern, not ``random``.
"""

import math
import struct
import wave
from pathlib import Path

import numpy as np
from PIL import Image

# --------------------------------------------------------------------------- #
# Palette  (strict 4-shade green DMG + minimal neutral shell)
# --------------------------------------------------------------------------- #
# RGBA tuples. Index names match the brief.
DARKEST = (0x0F, 0x38, 0x0F, 255)  # #0f380f  near-black green (outlines, ink)
DARK = (0x30, 0x62, 0x30, 255)  # #306230  mid-dark green
LIGHT = (0x8B, 0xAC, 0x0F, 255)  # #8bac0f  light green
LIGHTEST = (0x9B, 0xBC, 0x0F, 255)  # #9bbc0f  screen background (lit LCD)

# Console body shell: a muted neutral cream/grey, kept minimal. A slightly
# darker tone is used for shading the body edge so the shell reads as plastic.
SHELL = (0xC4, 0xCF, 0xA1, 255)  # #c4cfa1  body plastic
SHELL_DARK = (0x9A, 0xA6, 0x7C, 255)  # darker plastic for bezel/shadow
SHELL_HI = (0xD9, 0xE2, 0xBE, 255)  # subtle plastic highlight

TRANSPARENT = (0, 0, 0, 0)

# Logical authoring grid and upscale factor.
GRID = 32
SCALE = 4  # -> 128px final PNGs (crisp x4 nearest-neighbour)

OUT_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Tiny pixel canvas helpers
# --------------------------------------------------------------------------- #
class Canvas:
    """A GRIDxGRID RGBA pixel buffer with convenience drawing ops.

    All coordinates are integer logical pixels. Out-of-bounds writes are
    silently ignored so drawing helpers can be sloppy at the edges.
    """

    def __init__(self, size=GRID):
        self.size = size
        self.img = Image.new("RGBA", (size, size), TRANSPARENT)
        self.px = self.img.load()

    def set(self, x, y, color):
        x = int(x)
        y = int(y)
        if 0 <= x < self.size and 0 <= y < self.size:
            self.px[x, y] = color

    def get(self, x, y):
        if 0 <= x < self.size and 0 <= y < self.size:
            return self.px[x, y]
        return TRANSPARENT

    def hline(self, x0, x1, y, color):
        if x1 < x0:
            x0, x1 = x1, x0
        for x in range(x0, x1 + 1):
            self.set(x, y, color)

    def vline(self, x, y0, y1, color):
        if y1 < y0:
            y0, y1 = y1, y0
        for y in range(y0, y1 + 1):
            self.set(x, y, color)

    def rect(self, x0, y0, x1, y1, color):
        """Filled rectangle, inclusive bounds."""
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, color)

    def rect_outline(self, x0, y0, x1, y1, color):
        self.hline(x0, x1, y0, color)
        self.hline(x0, x1, y1, color)
        self.vline(x0, y0, y1, color)
        self.vline(x1, y0, y1, color)

    def disc(self, cx, cy, r, color):
        """Filled circle (pixel disc) centred at (cx, cy)."""
        for y in range(int(cy - r), int(cy + r) + 1):
            for x in range(int(cx - r), int(cx + r) + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r + 0.5:
                    self.set(x, y, color)

    def upscaled(self, factor=SCALE):
        return self.img.resize((self.size * factor, self.size * factor), Image.NEAREST)


# --------------------------------------------------------------------------- #
# Console body  (shared across every frame — this is the "character")
# --------------------------------------------------------------------------- #
# Screen (LCD) window — the "face". Inside this rect we draw only the 4 greens.
SCREEN_X0, SCREEN_Y0 = 6, 5
SCREEN_X1, SCREEN_Y1 = 25, 17  # inclusive; 20px wide x 13px tall lit area
SCREEN_W = SCREEN_X1 - SCREEN_X0 + 1
SCREEN_H = SCREEN_Y1 - SCREEN_Y0 + 1


def draw_body(c: Canvas):
    """Draw the chunky handheld shell, screen bezel, d-pad and two buttons.

    Leaves the lit LCD area (SCREEN_*) filled with LIGHTEST so per-state content
    can be painted on top.
    """
    # ---- Body shell: rounded-corner rectangle spanning most of the grid ----
    bx0, by0, bx1, by1 = 2, 1, 29, 30
    # Fill body
    c.rect(bx0, by0, bx1, by1, SHELL)
    # Knock out the four corners to fake rounding (2px notch).
    for cx, cy in [(bx0, by0), (bx1, by0), (bx0, by1), (bx1, by1)]:
        c.set(cx, cy, TRANSPARENT)
    for cx, cy in [(bx0, by0), (bx1, by0), (bx0, by1), (bx1, by1)]:
        # also soften one pixel inward diagonally? keep simple single-notch.
        pass

    # 1px dark outline around the shell (skip the notched corners).
    c.hline(bx0 + 1, bx1 - 1, by0, DARKEST)
    c.hline(bx0 + 1, bx1 - 1, by1, DARKEST)
    c.vline(bx0, by0 + 1, by1 - 1, DARKEST)
    c.vline(bx1, by0 + 1, by1 - 1, DARKEST)
    # corner outline pixels (one step in from each notch)
    c.set(bx0 + 1, by0, DARKEST)
    c.set(bx0, by0 + 1, DARKEST)
    c.set(bx1 - 1, by0, DARKEST)
    c.set(bx1, by0 + 1, DARKEST)
    c.set(bx0 + 1, by1, DARKEST)
    c.set(bx0, by1 - 1, DARKEST)
    c.set(bx1 - 1, by1, DARKEST)
    c.set(bx1, by1 - 1, DARKEST)

    # Subtle plastic highlight along the top inner edge, shadow along bottom.
    c.hline(bx0 + 2, bx1 - 2, by0 + 1, SHELL_HI)
    c.hline(bx0 + 1, bx1 - 1, by1 - 1, SHELL_DARK)
    c.vline(bx1 - 1, by0 + 2, by1 - 2, SHELL_DARK)

    # ---- Screen bezel: dark recessed frame around the LCD --------------------
    bezel_x0, bezel_y0 = SCREEN_X0 - 2, SCREEN_Y0 - 2
    bezel_x1, bezel_y1 = SCREEN_X1 + 2, SCREEN_Y1 + 2
    c.rect(bezel_x0, bezel_y0, bezel_x1, bezel_y1, SHELL_DARK)
    c.rect_outline(bezel_x0, bezel_y0, bezel_x1, bezel_y1, DARKEST)
    # Inner dark frame hugging the lit area.
    c.rect_outline(SCREEN_X0 - 1, SCREEN_Y0 - 1, SCREEN_X1 + 1, SCREEN_Y1 + 1, DARKEST)

    # ---- The lit LCD area: fill with the lightest green (screen "on") --------
    c.rect(SCREEN_X0, SCREEN_Y0, SCREEN_X1, SCREEN_Y1, LIGHTEST)

    # ---- D-pad (lower-left): a dark plus -------------------------------------
    dcx, dcy = 8, 24
    c.rect(dcx - 1, dcy - 3, dcx + 1, dcy + 3, DARKEST)  # vertical bar
    c.rect(dcx - 3, dcy - 1, dcx + 3, dcy + 1, DARKEST)  # horizontal bar
    c.set(dcx, dcy, DARK)  # tiny centre pivot highlight

    # ---- Two round action buttons (lower-right), set on a diagonal -----------
    # Button A (lower), Button B (upper) — classic offset.
    for bxc, byc in [(23, 26), (26, 23)]:
        c.disc(bxc, byc, 1.6, DARKEST)
        c.set(bxc, byc, DARK)  # lit centre

    # ---- Speaker grille hint: 3 short diagonal dark lines, lower-right edge ---
    for i in range(3):
        gx = 18 + i
        gy = 28 - i
        c.set(gx, gy, SHELL_DARK)

    # ---- Brand dash under the screen (decorative, neutral) -------------------
    c.hline(11, 20, 20, SHELL_DARK)


def new_console() -> Canvas:
    c = Canvas()
    draw_body(c)
    return c


# --------------------------------------------------------------------------- #
# On-screen content helpers (draw ONLY in the 4 greens inside the LCD)
# --------------------------------------------------------------------------- #
def screen_clear(c: Canvas, color=LIGHTEST):
    c.rect(SCREEN_X0, SCREEN_Y0, SCREEN_X1, SCREEN_Y1, color)


def sx(col):
    """Screen-local column (0-based) -> absolute x."""
    return SCREEN_X0 + col


def sy(row):
    """Screen-local row (0-based) -> absolute y."""
    return SCREEN_Y0 + row


# --------------------------------------------------------------------------- #
# STATE: idle  — sleepy screen with a slow-blinking cursor + tiny "z"
# --------------------------------------------------------------------------- #
def _draw_chevron(c, col, row, color):
    """A clean 3px-tall '>' chevron with its point at (col+1, row+1)."""
    #  X .
    #  . X
    #  X .
    c.set(sx(col), sy(row), color)
    c.set(sx(col + 1), sy(row + 1), color)
    c.set(sx(col), sy(row + 2), color)


def draw_cursor_block(c, on):
    """A terminal prompt: a fixed '>' chevron and a blinking cursor block."""
    # Prompt chevron stays lit; it anchors the screen as a little terminal.
    _draw_chevron(c, 2, 5, DARK)
    # Blinking cursor block to the right of the prompt.
    col, row = 5, 5
    color = DARK if on else LIGHTEST
    c.rect(sx(col), sy(row), sx(col + 1), sy(row + 2), color)


def _draw_z(c, col, row, color):
    """A compact 3x3 'z' glyph: top bar, diagonal, bottom bar."""
    #  X X X
    #  . X .
    #  X X X
    c.hline(sx(col), sx(col + 2), sy(row), color)
    c.set(sx(col + 1), sy(row + 1), color)
    c.hline(sx(col), sx(col + 2), sy(row + 2), color)


def draw_sleepy_z(c, big):
    """Stylised 'Zzz' sleep hint drifting up-right from the screen corner."""
    if big:
        # Two z's: a small one low, a bigger drift cue higher (rising).
        _draw_z(c, 12, 6, DARK)
        _draw_z(c, 15, 2, DARK)
    else:
        # Single small z resting near the upper-right.
        _draw_z(c, 14, 4, DARK)


def make_idle_frames():
    """3 frames: cursor on + small z, cursor on + big z, cursor off (blink)."""
    frames = []

    # frame 0: cursor on, small z
    c = new_console()
    draw_cursor_block(c, on=True)
    draw_sleepy_z(c, big=False)
    frames.append(c)

    # frame 1: cursor on, big z (the z "rises")
    c = new_console()
    draw_cursor_block(c, on=True)
    draw_sleepy_z(c, big=True)
    frames.append(c)

    # frame 2: cursor off (blink), no z -> the slow blink the brief asks for
    c = new_console()
    draw_cursor_block(c, on=False)
    frames.append(c)

    return frames


# --------------------------------------------------------------------------- #
# STATE: recording — bouncing equalizer bars on the LCD
# --------------------------------------------------------------------------- #
def draw_eq_bars(c, heights):
    """Draw vertical equalizer bars rising from the screen baseline.

    ``heights`` is a list of bar heights (in pixels). Bars are 2px wide with a
    1px gap, seated on the bottom row of the screen, drawn in DARK with a
    LIGHT cap so they have a little depth.
    """
    baseline = SCREEN_Y1 - 1
    bar_w = 2
    gap = 1
    n = len(heights)
    total = n * bar_w + (n - 1) * gap
    start = SCREEN_X0 + ((SCREEN_W - total) // 2)
    for i, h in enumerate(heights):
        x0 = start + i * (bar_w + gap)
        x1 = x0 + bar_w - 1
        h = max(1, min(h, SCREEN_H - 3))
        top = baseline - h + 1
        c.rect(x0, top, x1, baseline, DARK)
        # bright cap pixel row
        c.hline(x0, x1, top, LIGHT)
    # ground line under the bars
    c.hline(start, start + total - 1, baseline + 1, DARK)


# Deterministic bouncing pattern: 5 bars across 6 frames. Values picked by hand
# so the motion reads as a lively, looping bounce (no randomness).
_EQ_PATTERN = [
    [2, 5, 8, 4, 2],
    [4, 7, 5, 6, 3],
    [6, 9, 3, 8, 5],
    [8, 4, 6, 5, 7],
    [5, 6, 9, 3, 8],
    [3, 8, 4, 7, 4],
]


def make_recording_frames():
    frames = []
    for heights in _EQ_PATTERN:
        c = new_console()
        # small red-dot stand-in: a filled DARK dot top-left = "REC" indicator
        c.disc(sx(2), sy(1), 1.0, DARK)
        draw_eq_bars(c, heights)
        frames.append(c)
    return frames


# --------------------------------------------------------------------------- #
# STATE: processing — marching dots ("...") across the screen
# --------------------------------------------------------------------------- #
def make_processing_frames():
    """4 frames: a row of 3 dots where the 'active' dot marches + a small
    spinner tick in the corner so motion is obvious even at a glance."""
    frames = []
    dot_rows = 6  # vertical centre-ish
    base_cols = [4, 8, 12]
    spinner = ["|", "/", "-", "\\"]
    for f in range(4):
        c = new_console()
        # three baseline dots, the active one is a filled 2x2, others 1px
        for i, col in enumerate(base_cols):
            if i == f % 3:
                c.rect(sx(col), sy(dot_rows), sx(col + 1), sy(dot_rows + 1), DARK)
            else:
                c.set(sx(col), sy(dot_rows + 1), DARK)
        # tiny spinner glyph upper-right, drawn as line segments
        _draw_spinner(c, spinner[f], sx(15), sy(2))
        frames.append(c)
    return frames


def _draw_spinner(c, ch, ox, oy):
    """Draw a 3x3 spinner glyph (one of | / - \\) centred near (ox, oy)."""
    if ch == "|":
        c.vline(ox, oy - 1, oy + 1, DARK)
    elif ch == "-":
        c.hline(ox - 1, ox + 1, oy, DARK)
    elif ch == "/":
        c.set(ox + 1, oy - 1, DARK)
        c.set(ox, oy, DARK)
        c.set(ox - 1, oy + 1, DARK)
    elif ch == "\\":
        c.set(ox - 1, oy - 1, DARK)
        c.set(ox, oy, DARK)
        c.set(ox + 1, oy + 1, DARK)


# --------------------------------------------------------------------------- #
# STATE: success — checkmark draws on, sparkle flourish, holds clean check
# --------------------------------------------------------------------------- #
def _check_points():
    """Return the full ordered list of (col,row) screen-local pixels forming a
    bold checkmark, from the short tail to the long upstroke."""
    pts = []
    # short descending stroke (down-right)
    for i in range(3):
        pts.append((4 + i, 6 + i))  # (4,6)(5,7)(6,8)
    # long ascending stroke (up-right)
    for i in range(1, 6):
        pts.append((6 + i, 8 - i))  # (7,7)(8,6)(9,5)(10,4)(11,3)
    return pts


def _draw_check(c, n_points, bold=True):
    """Draw the first ``n_points`` of the checkmark. ``bold`` thickens it."""
    pts = _check_points()
    for col, row in pts[:n_points]:
        c.set(sx(col), sy(row), DARK)
        if bold:
            c.set(sx(col), sy(row + 1), DARK)  # 1px thicker downward
            c.set(sx(col + 1), sy(row), DARK)  # 1px thicker rightward (subtle)


def _draw_sparkle(c, col, row, size):
    """A 4-point sparkle/star centred at screen-local (col,row)."""
    cx, cy = sx(col), sy(row)
    c.set(cx, cy, LIGHT)
    for d in range(1, size + 1):
        col_ = LIGHT if d == 1 else DARK
        c.set(cx, cy - d, col_)
        c.set(cx, cy + d, col_)
        c.set(cx - d, cy, col_)
        c.set(cx + d, cy, col_)


def make_success_frames():
    """7 frames, ONE-SHOT. Check draws progressively, sparkles pop, final frame
    is a clean bold check (held by the engine)."""
    frames = []
    total_pts = len(_check_points())

    # frames 0-3: progressively draw the check
    steps = [2, 4, 6, total_pts]
    for n in steps:
        c = new_console()
        _draw_check(c, n, bold=True)
        frames.append(c)

    # frame 4: full check + small sparkle upper-right
    c = new_console()
    _draw_check(c, total_pts, bold=True)
    _draw_sparkle(c, 14, 2, 1)
    frames.append(c)

    # frame 5: full check + bigger sparkle (flourish peak)
    c = new_console()
    _draw_check(c, total_pts, bold=True)
    _draw_sparkle(c, 14, 2, 2)
    _draw_sparkle(c, 3, 9, 1)
    frames.append(c)

    # frame 6 (FINAL, held): clean bold check, no sparkle clutter
    c = new_console()
    _draw_check(c, total_pts, bold=True)
    frames.append(c)

    return frames


# --------------------------------------------------------------------------- #
# STATE: error — X with brief faux-static / screen flicker, holds clean X
# --------------------------------------------------------------------------- #
def _draw_x(c, partial=1.0, bold=True):
    """Draw a bold X across the screen. ``partial`` (0..1) reveals it."""
    # Diagonal endpoints in screen-local coords.
    span = list(range(2, 14))  # cols/rows 2..13
    n = max(1, int(len(span) * partial))
    for i in range(n):
        col = span[i]
        row1 = 3 + i  # top-left -> bottom-right
        row2 = 14 - i  # bottom-left -> top-right
        c.set(sx(col), sy(row1), DARK)
        c.set(sx(col), sy(row2), DARK)
        if bold:
            c.set(sx(col), sy(row1 + 1), DARK)
            c.set(sx(col), sy(row2 - 1), DARK)


def _draw_static(c, phase):
    """Deterministic LCD 'static': a fixed dither pattern toggled by phase.

    Uses (x*7 + y*13 + phase*5) parity so it looks noisy but is fully
    reproducible — no RNG.
    """
    for y in range(SCREEN_Y0, SCREEN_Y1 + 1):
        for x in range(SCREEN_X0, SCREEN_X1 + 1):
            if ((x * 7 + y * 13 + phase * 5) % 3) == 0:
                c.set(x, y, DARK)
            elif ((x * 5 + y * 11 + phase * 3) % 4) == 0:
                c.set(x, y, LIGHT)


def make_error_frames():
    """5 frames, ONE-SHOT. Static burst -> X slams in with a shake -> clean X
    held on the final frame."""
    frames = []

    # frame 0: heavy static flash
    c = new_console()
    _draw_static(c, phase=0)
    frames.append(c)

    # frame 1: static + half X (shifted 1px right = shake)
    c = new_console()
    _draw_static(c, phase=1)
    _draw_x(c, partial=0.5, bold=True)
    frames.append(c)

    # frame 2: light static + nearly-full X (shifted back = shake)
    c = new_console()
    _draw_static(c, phase=2)
    _draw_x(c, partial=0.85, bold=True)
    frames.append(c)

    # frame 3: full bold X, faint residual flicker dots
    c = new_console()
    _draw_x(c, partial=1.0, bold=True)
    # a couple of residual flicker pixels in the corners
    c.set(sx(1), sy(1), LIGHT)
    c.set(sx(16), sy(11), LIGHT)
    frames.append(c)

    # frame 4 (FINAL, held): clean bold X
    c = new_console()
    _draw_x(c, partial=1.0, bold=True)
    frames.append(c)

    return frames


# --------------------------------------------------------------------------- #
# Chiptune sound synthesis (square waves)
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 22050
PEAK = 0.30  # peak amplitude per the brief (polite)


def _square_tone(freq, dur, sr=SAMPLE_RATE, duty=0.5):
    """A pure square wave of ``freq`` Hz for ``dur`` seconds (float -1..1)."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    phase = (t * freq) % 1.0
    wave_arr = np.where(phase < duty, 1.0, -1.0)
    return wave_arr


def _decay_env(n, attack_frac=0.02, sr=SAMPLE_RATE):
    """Quick-attack, exponential-decay envelope ending at exactly 0."""
    env = np.ones(n)
    a = max(1, int(n * attack_frac))
    env[:a] = np.linspace(0.0, 1.0, a)
    # exponential decay over the remainder
    decay = np.exp(-np.linspace(0.0, 4.0, n - a))
    env[a:] = decay
    # force a clean tail to exactly zero over the final few samples (no click)
    tail = min(40, n)
    env[-tail:] *= np.linspace(1.0, 0.0, tail)
    return env


def _write_wav(path, samples_float, sr=SAMPLE_RATE):
    """Write a mono 16-bit PCM WAV, clipped, peak-normalised to PEAK."""
    s = np.asarray(samples_float, dtype=np.float64)
    # Normalise to PEAK then clip for safety.
    peak = np.max(np.abs(s)) if s.size else 0.0
    if peak > 0:
        s = s / peak * PEAK
    s = np.clip(s, -1.0, 1.0)
    # Guarantee the very last sample is exactly 0 to avoid a click.
    if s.size:
        s[-1] = 0.0
    pcm = (s * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def make_recording_sound(path):
    """Single square blip ~1047 Hz, ~0.1s (entry chirp for recording)."""
    tone = _square_tone(1047.0, 0.10)
    env = _decay_env(len(tone), attack_frac=0.05)
    _write_wav(path, tone * env)


def make_success_sound(path):
    """Ascending two-note 523 -> 1047 Hz, ~0.3s total (cheerful, original)."""
    n1 = _square_tone(523.25, 0.13)
    n2 = _square_tone(1046.50, 0.17)
    e1 = _decay_env(len(n1), attack_frac=0.04)
    e2 = _decay_env(len(n2), attack_frac=0.04)
    seq = np.concatenate([n1 * e1, n2 * e2])
    _write_wav(path, seq)


def make_error_sound(path):
    """Harsh low buzz ~130 Hz, ~0.25s (a curt 'nope' with a square edge)."""
    tone = _square_tone(130.81, 0.25, duty=0.5)
    # A second slightly detuned square adds gritty beating without RNG.
    tone2 = _square_tone(123.47, 0.25, duty=0.5)
    mixed = tone + 0.5 * tone2
    env = _decay_env(len(mixed), attack_frac=0.01)
    _write_wav(path, mixed * env)


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def build_manifest():
    return {
        "id": "handheld-89",
        "name": "Handheld '89",
        "description": (
            "A chunky 1989-era monochrome handheld console rendered in the "
            "classic 4-shade green LCD palette. Its screen is the face: a "
            "blinking cursor at rest, bouncing equalizer bars while recording, "
            "marching dots while thinking, a sparkle-checked screen on success "
            "and a static-buzz X on error."
        ),
        "author": "WhisperHUD",
        "version": "1.0.0",
        "preview_image": "idle_0.png",
        "states": {
            "idle": {
                "file": "idle_0.png",
                "description": "Sleepy LCD with a slow-blinking terminal cursor",
                "frames": ["idle_0.png", "idle_1.png", "idle_2.png"],
                "fps": 2,
            },
            "recording": {
                "file": "recording_0.png",
                "description": "Bouncing equalizer bars on the LCD with a REC dot",
                "frames": [
                    "recording_0.png",
                    "recording_1.png",
                    "recording_2.png",
                    "recording_3.png",
                    "recording_4.png",
                    "recording_5.png",
                ],
                "fps": 8,
                "sound": "recording.wav",
            },
            "processing": {
                "file": "processing_0.png",
                "description": "Marching dots and a tiny spinner while thinking",
                "frames": [
                    "processing_0.png",
                    "processing_1.png",
                    "processing_2.png",
                    "processing_3.png",
                ],
                "fps": 6,
            },
            "success": {
                "file": "success_0.png",
                "description": "Checkmark draws on with a sparkle flourish (holds a clean check)",
                "frames": [
                    "success_0.png",
                    "success_1.png",
                    "success_2.png",
                    "success_3.png",
                    "success_4.png",
                    "success_5.png",
                    "success_6.png",
                ],
                "fps": 10,
                "sound": "success.wav",
            },
            "error": {
                "file": "error_0.png",
                "description": "Static burst and screen-shake resolving to a clear X",
                "frames": [
                    "error_0.png",
                    "error_1.png",
                    "error_2.png",
                    "error_3.png",
                    "error_4.png",
                ],
                "fps": 10,
                "sound": "error.wav",
            },
        },
        "settings": {
            "shape_mode": "alpha",
            "apply_state_tint": False,
            "recommended_size": "large",
            "interpolation": "nearest",
        },
    }


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def save_frames(name, frames):
    paths = []
    for i, c in enumerate(frames):
        p = OUT_DIR / f"{name}_{i}.png"
        c.upscaled().save(p)
        paths.append(p)
    return paths


def main():
    import json

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # PNG frames
    save_frames("idle", make_idle_frames())
    save_frames("recording", make_recording_frames())
    save_frames("processing", make_processing_frames())
    save_frames("success", make_success_frames())
    save_frames("error", make_error_frames())

    # Sounds (only recording / success / error)
    make_recording_sound(OUT_DIR / "recording.wav")
    make_success_sound(OUT_DIR / "success.wav")
    make_error_sound(OUT_DIR / "error.wav")

    # Manifest
    with open(OUT_DIR / "manifest.json", "w") as f:
        json.dump(build_manifest(), f, indent=2)
        f.write("\n")

    print(f"handheld-89 pack written to {OUT_DIR}")


if __name__ == "__main__":
    main()
