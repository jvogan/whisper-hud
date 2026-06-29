#!/usr/bin/env python3
"""
Generate the "CRT Terminal" built-in character pack for WhisperHUD.

A green-phosphor CRT monitor is the character: a beige/grey rounded case with a
slightly bulged dark screen. All screen content is monochrome green phosphor with
scanlines and a 2-step glow halo around bright glyphs. Every asset is authored on
a 48x48 logical pixel grid and upscaled x4 with Image.NEAREST so the result stays
crisp pixel art with hard edges (no anti-aliasing, no gradients).

States / animation:
  - idle       : blinking block cursor after a prompt char (2 frames, ~2 fps, loop)
  - recording  : "REC *" indicator + scrolling waveform (6 frames, ~8 fps, loop)
  - processing : classic ASCII spinner | / - \\ (4 frames, ~8 fps, loop)
  - success    : "OK" + check, bright flash settling to steady (5 frames, one-shot)
  - error      : horizontal glitch/tear lines + "ERR" (5 frames, one-shot)

Sounds (22050 Hz mono 16-bit PCM, peak ~0.3, fade to zero):
  - recording  : terminal bell beep ~800 Hz, ~0.1s
  - success    : ascending double beep 660 -> 880 Hz, ~0.25s
  - error      : low descending buzz 220 -> 110 Hz, ~0.3s
  (idle / processing stay silent.)

Deterministic: no unseeded randomness. The glitch frames use a fixed RNG seed so
re-running this script reproduces byte-identical output.

Run with the project venv:
    .venv/bin/python assets/character-packs/crt-terminal/generate_crt_terminal.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

# --------------------------------------------------------------------------- #
# Grid + scale
# --------------------------------------------------------------------------- #

OUTPUT_DIR = Path(__file__).parent
GRID = 48  # logical pixel grid (48x48)
SCALE = 4  # nearest-neighbour upscale factor -> 192px PNGs

RGBA = Tuple[int, int, int, int]

# --------------------------------------------------------------------------- #
# Palette  (muted case tones + dark outline; monochrome green phosphor screen)
# --------------------------------------------------------------------------- #

TRANSPARENT: RGBA = (0, 0, 0, 0)

# Case (beige/grey, 3 muted tones + dark outline)
CASE_LIGHT: RGBA = (216, 208, 192, 255)  # #d8d0c0  top/left highlight
CASE_MID: RGBA = (184, 176, 160, 255)  # #b8b0a0  main body
CASE_DARK: RGBA = (168, 160, 144, 255)  # #a8a090  bottom/right shade
CASE_OUTLINE: RGBA = (40, 38, 34, 255)  # near-black outline
CASE_VENT: RGBA = (150, 143, 128, 255)  # vent slits on the chin

# Screen bezel (dark, frames the phosphor)
BEZEL: RGBA = (28, 30, 28, 255)
BEZEL_HI: RGBA = (52, 56, 52, 255)  # subtle inner bezel highlight

# Phosphor greens (4 steps: bg -> dim -> mid -> bright)
SCREEN_BG: RGBA = (10, 15, 10, 255)  # #0a0f0a  screen background
SCREEN_BG_SCAN: RGBA = (6, 11, 6, 255)  # darker alternate scanline row
P_DIM: RGBA = (4, 74, 30, 255)  # #044a1e  dim green (glow halo)
P_MID: RGBA = (24, 165, 88, 255)  # #18a558  mid green
P_BRIGHT: RGBA = (0, 255, 102, 255)  # #00ff66  bright core
# Slightly hotter bright used to emphasise error legibility (still monochrome green)
P_HOT: RGBA = (120, 255, 150, 255)

# Power LED on the case chin
LED_ON: RGBA = (0, 255, 102, 255)
LED_OFF: RGBA = (40, 70, 48, 255)

# --------------------------------------------------------------------------- #
# Geometry of the monitor on the 48x48 grid
# --------------------------------------------------------------------------- #

# Case body rectangle (inclusive pixel coords)
CASE_X0, CASE_Y0 = 4, 5
CASE_X1, CASE_Y1 = 43, 40
CASE_RADIUS = 3

# Screen rectangle (the dark phosphor area), inside a dark bezel
SCREEN_X0, SCREEN_Y0 = 9, 9
SCREEN_X1, SCREEN_Y1 = 38, 31
# Bezel is one pixel ring around the screen
BEZEL_X0, BEZEL_Y0 = SCREEN_X0 - 1, SCREEN_Y0 - 1
BEZEL_X1, BEZEL_Y1 = SCREEN_X1 + 1, SCREEN_Y1 + 1

# Screen text grid: glyphs are 3x5 in a 4x6 cell. Compute usable columns/rows.
GLYPH_W, GLYPH_H = 3, 5
CELL_W, CELL_H = 4, 6
TEXT_X0 = SCREEN_X0 + 1  # left padding inside screen
TEXT_Y0 = SCREEN_Y0 + 1  # top padding inside screen
SCREEN_W = SCREEN_X1 - SCREEN_X0 + 1
SCREEN_H = SCREEN_Y1 - SCREEN_Y0 + 1
COLS = (SCREEN_W - 2) // CELL_W  # how many character cells fit horizontally
ROWS = (SCREEN_H - 2) // CELL_H  # how many character cells fit vertically


# --------------------------------------------------------------------------- #
# Tiny 3x5 pixel font (only the glyphs we need)
# Rows are top->bottom, each string is 3 chars wide ('#'=on, '.'=off).
# --------------------------------------------------------------------------- #

FONT: Dict[str, List[str]] = {
    "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "E": ["###", "#..", "##.", "#..", "###"],
    "C": ["###", "#..", "#..", "#..", "###"],
    "O": ["###", "#.#", "#.#", "#.#", "###"],
    "K": ["#.#", "#.#", "##.", "#.#", "#.#"],
    "P": ["##.", "#.#", "##.", "#..", "#.."],
    ">": ["#..", ".#.", "..#", ".#.", "#.."],
    "*": [".#.", "#.#", ".#.", "#.#", ".#."],  # diamond/asterisk (REC dot uses solid)
    " ": ["...", "...", "...", "...", "..."],
}


# --------------------------------------------------------------------------- #
# Canvas helpers (operate on the logical GRIDxGRID pixel buffer)
# --------------------------------------------------------------------------- #


def new_canvas() -> Image.Image:
    return Image.new("RGBA", (GRID, GRID), TRANSPARENT)


def px(img: Image.Image, x: int, y: int, color: RGBA) -> None:
    if 0 <= x < GRID and 0 <= y < GRID:
        img.putpixel((x, y), color)


def fill_rect(img: Image.Image, x0: int, y0: int, x1: int, y1: int, color: RGBA) -> None:
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px(img, x, y, color)


def in_rounded_case(x: int, y: int) -> bool:
    """True if (x,y) is inside the rounded-rectangle case body."""
    if not (CASE_X0 <= x <= CASE_X1 and CASE_Y0 <= y <= CASE_Y1):
        return False
    r = CASE_RADIUS
    # Corner circles
    corners = [
        (CASE_X0 + r, CASE_Y0 + r),
        (CASE_X1 - r, CASE_Y0 + r),
        (CASE_X0 + r, CASE_Y1 - r),
        (CASE_X1 - r, CASE_Y1 - r),
    ]
    for cx, cy in corners:
        in_corner_zone = (x < CASE_X0 + r or x > CASE_X1 - r) and (y < CASE_Y0 + r or y > CASE_Y1 - r)
        if in_corner_zone:
            # Only test the nearest corner
            if abs(x - cx) <= r and abs(y - cy) <= r:
                if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 0.5) ** 2:
                    return True
            # If it sits in a corner quadrant but matches no corner circle, reject
            continue
        return True
    return False


def case_outline_pixel(x: int, y: int) -> bool:
    """True if (x,y) is on the 1px outline ring of the rounded case."""
    if not in_rounded_case(x, y):
        return False
    # Edge if any 4-neighbour is outside the case
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if not in_rounded_case(x + dx, y + dy):
            return True
    return False


# --------------------------------------------------------------------------- #
# Draw the static CRT case + empty scanlined screen (shared by every frame)
# --------------------------------------------------------------------------- #


def draw_case(img: Image.Image) -> None:
    """Beige/grey rounded monitor case with shading, vents and a power LED."""
    # Body fill with simple directional shading.
    for y in range(CASE_Y0, CASE_Y1 + 1):
        for x in range(CASE_X0, CASE_X1 + 1):
            if not in_rounded_case(x, y):
                continue
            # Default mid tone
            color = CASE_MID
            # Top two rows + left two cols -> light highlight
            if y <= CASE_Y0 + 1 or x <= CASE_X0 + 1:
                color = CASE_LIGHT
            # Bottom two rows + right two cols -> darker shade
            if y >= CASE_Y1 - 1 or x >= CASE_X1 - 1:
                color = CASE_DARK
            px(img, x, y, color)

    # Outline ring (drawn after fill so it sits on top).
    for y in range(CASE_Y0 - 1, CASE_Y1 + 2):
        for x in range(CASE_X0 - 1, CASE_X1 + 2):
            if case_outline_pixel(x, y):
                px(img, x, y, CASE_OUTLINE)

    # Chin area below the screen: vents + power LED + label dash.
    chin_y = SCREEN_Y1 + 3
    # Vent slits (three short horizontal dashes on the left of the chin).
    for vy in (chin_y, chin_y + 2):
        for vx in range(12, 24, 2):
            px(img, vx, vy, CASE_VENT)
    # Power LED bottom-right of the chin (lit green).
    led_x, led_y = 35, chin_y + 1
    px(img, led_x, led_y, LED_ON)
    px(img, led_x + 1, led_y, LED_OFF)


def draw_bezel_and_screen(img: Image.Image) -> None:
    """Dark bezel ring + scanlined phosphor background."""
    # Bezel ring (one pixel around the screen).
    fill_rect(img, BEZEL_X0, BEZEL_Y0, BEZEL_X1, BEZEL_Y1, BEZEL)
    # A faint inner-top bezel highlight to suggest the glass bulge.
    for x in range(BEZEL_X0, BEZEL_X1 + 1):
        px(img, x, BEZEL_Y0, BEZEL_HI)

    # Phosphor background with scanlines (every other row darker).
    for y in range(SCREEN_Y0, SCREEN_Y1 + 1):
        row_color = SCREEN_BG if ((y - SCREEN_Y0) % 2 == 0) else SCREEN_BG_SCAN
        for x in range(SCREEN_X0, SCREEN_X1 + 1):
            px(img, x, y, row_color)

    # CRT glass bulge: darken the four screen corners (a 1px corner vignette).
    # This is the signature cue that the screen is convex tube glass.
    corner_offsets = [(0, 0), (1, 0), (0, 1)]
    corners = [
        (SCREEN_X0, SCREEN_Y0, 1, 1),  # top-left  (dx, dy directions)
        (SCREEN_X1, SCREEN_Y0, -1, 1),  # top-right
        (SCREEN_X0, SCREEN_Y1, 1, -1),  # bottom-left
        (SCREEN_X1, SCREEN_Y1, -1, -1),  # bottom-right
    ]
    for cx, cy, sx, sy in corners:
        for ox, oy in corner_offsets:
            px(img, cx + ox * sx, cy + oy * sy, SCREEN_BG_SCAN)


def base_frame() -> Image.Image:
    """A fresh canvas with case + empty scanlined screen."""
    img = new_canvas()
    draw_case(img)
    draw_bezel_and_screen(img)
    return img


# --------------------------------------------------------------------------- #
# Phosphor drawing helpers (respect scanlines + apply a 2-step glow halo)
# --------------------------------------------------------------------------- #


def on_screen(x: int, y: int) -> bool:
    return SCREEN_X0 <= x <= SCREEN_X1 and SCREEN_Y0 <= y <= SCREEN_Y1


def phosphor_px(img: Image.Image, x: int, y: int, bright: bool = True) -> None:
    """Set a lit phosphor pixel. Bright pixels on a scanline (odd) row are
    knocked down to mid so the scanline texture still reads through glyphs."""
    if not on_screen(x, y):
        return
    scan = (y - SCREEN_Y0) % 2 == 1
    if bright:
        px(img, x, y, P_MID if scan else P_BRIGHT)
    else:
        px(img, x, y, P_DIM)


def glow(img: Image.Image, lit: List[Tuple[int, int]]) -> None:
    """Paint a 1px dim-green halo around the set of bright pixels, without
    overwriting any existing bright pixel. 2-step look: dim ring then core."""
    lit_set = set(lit)
    halo: set = set()
    for x, y in lit:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if (nx, ny) in lit_set:
                    continue
                if not on_screen(nx, ny):
                    continue
                halo.add((nx, ny))
    for x, y in halo:
        # Only halo over background (don't dim-out a different glyph's core).
        cur = img.getpixel((x, y))
        if cur in (SCREEN_BG, SCREEN_BG_SCAN):
            px(img, x, y, P_DIM)


def draw_glyph(img: Image.Image, ch: str, cell_x: int, cell_y: int, collect: List[Tuple[int, int]]) -> None:
    """Stamp a 3x5 font glyph at character-cell (cell_x, cell_y). Lit pixels are
    appended to ``collect`` so a glow halo can be applied afterwards."""
    pattern = FONT.get(ch.upper(), FONT[" "])
    ox = TEXT_X0 + cell_x * CELL_W
    oy = TEXT_Y0 + cell_y * CELL_H
    for ry, row in enumerate(pattern):
        for rx, c in enumerate(row):
            if c == "#":
                x, y = ox + rx, oy + ry
                if on_screen(x, y):
                    collect.append((x, y))


def stamp_lit(img: Image.Image, lit: List[Tuple[int, int]]) -> None:
    """Apply glow halo first, then bright cores on top."""
    glow(img, lit)
    for x, y in lit:
        phosphor_px(img, x, y, bright=True)


def draw_text(img: Image.Image, text: str, cell_x: int, cell_y: int) -> List[Tuple[int, int]]:
    """Draw a short string at a character cell; returns the lit pixels (not yet
    stamped) so callers can combine with other glyphs before glow."""
    lit: List[Tuple[int, int]] = []
    for i, ch in enumerate(text):
        draw_glyph(img, ch, cell_x + i, cell_y, lit)
    return lit


# --------------------------------------------------------------------------- #
# Per-state frame renderers
# --------------------------------------------------------------------------- #


def render_idle(blink_on: bool) -> Image.Image:
    """Prompt char `>` followed by a blinking block cursor."""
    img = base_frame()
    lit = draw_text(img, ">", 0, 0)
    stamp_lit(img, lit)
    if blink_on:
        # Block cursor occupies the next cell (3 wide x 5 tall).
        cx = TEXT_X0 + 1 * CELL_W
        cy = TEXT_Y0
        block: List[Tuple[int, int]] = []
        for yy in range(cy, cy + GLYPH_H):
            for xx in range(cx, cx + GLYPH_W):
                if on_screen(xx, yy):
                    block.append((xx, yy))
        stamp_lit(img, block)
    return img


def _waveform_lit(phase: int) -> List[Tuple[int, int]]:
    """A scrolling waveform polyline across the lower screen area."""
    lit: List[Tuple[int, int]] = []
    wave_y = SCREEN_Y1 - 4  # baseline row for the waveform
    amp = 3
    for x in range(SCREEN_X0 + 1, SCREEN_X1):
        # Deterministic pseudo-wave: sum of two sines scrolling by `phase`.
        t = x + phase * 2
        v = math.sin(t * 0.7) * amp + math.sin(t * 0.33) * (amp * 0.5)
        y = int(round(wave_y - v))
        lit.append((x, y))
    return lit


def render_recording(frame_idx: int, n_frames: int) -> Image.Image:
    """`REC` text + a solid blinking dot + a scrolling waveform line."""
    img = base_frame()
    lit = draw_text(img, "REC", 0, 0)
    # Solid REC dot to the right of the text (blinks on even frames).
    if frame_idx % 2 == 0:
        dot_x = TEXT_X0 + 4 * CELL_W
        dot_y = TEXT_Y0 + 1
        for yy in range(dot_y, dot_y + 3):
            for xx in range(dot_x, dot_x + 3):
                lit.append((xx, yy))
    # Scrolling waveform on its own line lower down.
    lit.extend(_waveform_lit(frame_idx))
    stamp_lit(img, lit)
    return img


_SPINNER = ["|", "/", "-", "\\"]


def _spinner_lit(symbol: str, cx: int, cy: int) -> List[Tuple[int, int]]:
    """Draw one spinner glyph (3x3) centred in a glyph cell."""
    grids = {
        "|": [".#.", ".#.", ".#."],
        "/": ["..#", ".#.", "#.."],
        "-": ["...", "###", "..."],
        "\\": ["#..", ".#.", "..#"],
    }
    pattern = grids[symbol]
    lit: List[Tuple[int, int]] = []
    for ry, row in enumerate(pattern):
        for rx, c in enumerate(row):
            if c == "#":
                lit.append((cx + rx, cy + ry))
    return lit


def render_processing(frame_idx: int) -> Image.Image:
    """Prompt `>` plus a classic ASCII spinner | / - \\ cycling."""
    img = base_frame()
    lit = draw_text(img, ">", 0, 0)
    symbol = _SPINNER[frame_idx % len(_SPINNER)]
    sx = TEXT_X0 + 1 * CELL_W
    sy = TEXT_Y0 + 1
    lit.extend(_spinner_lit(symbol, sx, sy))
    stamp_lit(img, lit)
    return img


def _check_lit(bright_scale: int = 0) -> List[Tuple[int, int]]:
    """A check-mark glyph drawn to the right of 'OK'."""
    # Place check after the 2-char "OK" (cells 0,1) -> start at cell 3.
    ox = TEXT_X0 + 3 * CELL_W
    oy = TEXT_Y0
    pattern = [
        "....#",
        "...#.",
        "#.#..",
        ".#...",
        ".....",
    ]
    lit: List[Tuple[int, int]] = []
    for ry, row in enumerate(pattern):
        for rx, c in enumerate(row):
            if c == "#":
                lit.append((ox + rx, oy + ry))
    return lit


def _flash_overlay(img: Image.Image, intensity: float) -> None:
    """Brighten the whole screen toward bright phosphor to simulate a flash.
    intensity in [0,1]; 0 = none, 1 = full wash. Only touches screen pixels."""
    if intensity <= 0:
        return
    for y in range(SCREEN_Y0, SCREEN_Y1 + 1):
        for x in range(SCREEN_X0, SCREEN_X1 + 1):
            cur = img.getpixel((x, y))
            if cur in (SCREEN_BG, SCREEN_BG_SCAN):
                # Wash background up to dim/mid depending on intensity.
                scan = (y - SCREEN_Y0) % 2 == 1
                if intensity >= 0.66:
                    px(img, x, y, P_DIM if scan else P_MID)
                elif intensity >= 0.33:
                    px(img, x, y, SCREEN_BG_SCAN if scan else P_DIM)


def render_success(frame_idx: int, n_frames: int) -> Image.Image:
    """`OK` + check; opens with a bright flash that settles to a steady read.

    One-shot: the final frame is the clean, steady 'OK v' that is held.
    """
    img = base_frame()
    # Flash intensity ramps down over the first frames, 0 by the last frame.
    # frames: 0 (hot flash) -> ... -> n-1 (steady)
    flash = max(0.0, 1.0 - frame_idx / max(1, (n_frames - 1)))
    # Make the very first frame a strong wash, then ease off.
    _flash_overlay(img, flash)

    lit = draw_text(img, "OK", 0, 0)
    lit.extend(_check_lit())
    stamp_lit(img, lit)

    # On the opening flash frames, push the glyph cores to the hottest green.
    if flash >= 0.66:
        for x, y in lit:
            if on_screen(x, y):
                px(img, x, y, P_HOT)
    return img


def render_error(frame_idx: int, n_frames: int, rng: np.random.Generator) -> Image.Image:
    """`ERR` with horizontal glitch/tear lines. One-shot; final frame is a
    clean, brighter `ERR` for emphasis (still monochrome green)."""
    img = base_frame()

    # Glitch intensity is strongest on the first frames, gone by the last.
    glitch = max(0.0, 1.0 - frame_idx / max(1, (n_frames - 1)))

    # Draw horizontal tear lines at deterministic-random rows.
    n_tears = int(round(glitch * 4))
    if n_tears > 0:
        rows = rng.choice(range(SCREEN_Y0, SCREEN_Y1 + 1), size=min(n_tears, SCREEN_H), replace=False)
        for ry in rows:
            tear: List[Tuple[int, int]] = []
            # A tear line with a random horizontal offset/length.
            start = SCREEN_X0 + int(rng.integers(0, 4))
            end = SCREEN_X1 - int(rng.integers(0, 4))
            for x in range(start, end + 1):
                tear.append((x, int(ry)))
            # Tears render as dim green streaks (not bright) so text stays legible.
            glow(img, tear)
            for x, y in tear:
                phosphor_px(img, x, y, bright=False)

    # ERR text. Shift it horizontally on glitchy frames, centred when steady.
    shift = 0
    if glitch >= 0.5:
        shift = int(rng.integers(-1, 2))  # -1, 0, or 1
    lit = draw_text(img, "ERR", 0, 0)
    if shift:
        lit = [(x + shift, y) for (x, y) in lit]
    stamp_lit(img, lit)

    # Final (steady) frame: brighten ERR cores to hot green for emphasis.
    if glitch <= 0.0:
        for x, y in lit:
            if on_screen(x, y):
                px(img, x, y, P_HOT)
    return img


# --------------------------------------------------------------------------- #
# Save helpers
# --------------------------------------------------------------------------- #


def upscale_save(img: Image.Image, name: str) -> None:
    big = img.resize((GRID * SCALE, GRID * SCALE), Image.NEAREST)
    big.save(OUTPUT_DIR / name, "PNG")


# Frame plan: (state, [filenames], renderer-builds-list)
def build_all_frames() -> Dict[str, List[Image.Image]]:
    frames: Dict[str, List[Image.Image]] = {}

    # idle: 2 frames (cursor off / on). Index 0 = cursor visible so the static
    # `idle_0.png` (preview + single-icon fallback) shows the prompt + cursor.
    frames["idle"] = [render_idle(blink_on=True), render_idle(blink_on=False)]

    # recording: 6 frames scrolling waveform + blinking dot.
    rec_n = 6
    frames["recording"] = [render_recording(i, rec_n) for i in range(rec_n)]

    # processing: 4 frames spinner.
    frames["processing"] = [render_processing(i) for i in range(4)]

    # success: 5 frames, flash -> steady (one-shot).
    suc_n = 5
    frames["success"] = [render_success(i, suc_n) for i in range(suc_n)]

    # error: 5 frames, glitch -> steady (one-shot). Fixed seed for determinism.
    err_n = 5
    rng = np.random.default_rng(0xC27)
    frames["error"] = [render_error(i, err_n, rng) for i in range(err_n)]

    return frames


def write_pngs(frames: Dict[str, List[Image.Image]]) -> Dict[str, List[str]]:
    """Write each frame to <state>_<idx>.png and return the filename lists."""
    names: Dict[str, List[str]] = {}
    for state, imgs in frames.items():
        state_names = []
        for i, im in enumerate(imgs):
            fname = f"{state}_{i}.png"
            upscale_save(im, fname)
            state_names.append(fname)
        names[state] = state_names
    return names


# --------------------------------------------------------------------------- #
# Chiptune sound generation
# --------------------------------------------------------------------------- #

SAMPLE_RATE = 22050
PEAK = 0.30


def _write_wav(path: Path, samples: np.ndarray) -> None:
    """Write a mono 16-bit PCM WAV. Samples are float in [-1, 1]."""
    # Guarantee the tail lands exactly on zero (no click).
    samples = samples.copy()
    if samples.size:
        samples[-1] = 0.0
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


def _decay_env(n: int, attack_frac: float = 0.05) -> np.ndarray:
    """A quick attack + exponential decay envelope that fades to exactly 0."""
    env = np.ones(n)
    attack = max(1, int(n * attack_frac))
    env[:attack] = np.linspace(0.0, 1.0, attack)
    # Exponential decay over the remainder.
    decay = np.linspace(0.0, 1.0, n - attack)
    env[attack:] = np.exp(-4.0 * decay)
    # Force a short linear fade-out on the final samples so it ends on zero.
    tail = max(1, int(n * 0.04))
    env[-tail:] *= np.linspace(1.0, 0.0, tail)
    return env


def _tone(freqs: np.ndarray, duration: float) -> np.ndarray:
    """A tone whose instantaneous frequency follows `freqs` over `duration`."""
    n = int(SAMPLE_RATE * duration)
    f = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(freqs)), freqs)
    phase = 2 * np.pi * np.cumsum(f) / SAMPLE_RATE
    # Square-ish chiptune tone: blend a square with its fundamental for warmth.
    sig = 0.6 * np.sign(np.sin(phase)) + 0.4 * np.sin(phase)
    return sig * _decay_env(n) * PEAK


def make_recording_sound() -> np.ndarray:
    """Terminal bell beep ~800 Hz, ~0.1s."""
    return _tone(np.array([800.0, 800.0]), 0.10)


def make_success_sound() -> np.ndarray:
    """Ascending double beep 660 -> 880 Hz, ~0.25s (two distinct notes)."""
    note1 = _tone(np.array([660.0, 660.0]), 0.11)
    gap = np.zeros(int(SAMPLE_RATE * 0.02))
    note2 = _tone(np.array([880.0, 880.0]), 0.11)
    return np.concatenate([note1, gap, note2])


def make_error_sound() -> np.ndarray:
    """Low descending buzz 220 -> 110 Hz, ~0.3s."""
    return _tone(np.array([220.0, 110.0]), 0.30)


def write_sounds() -> Dict[str, str]:
    sounds = {
        "recording": ("beep.wav", make_recording_sound()),
        "success": ("success.wav", make_success_sound()),
        "error": ("error.wav", make_error_sound()),
    }
    out: Dict[str, str] = {}
    for state, (fname, samples) in sounds.items():
        _write_wav(OUTPUT_DIR / fname, samples)
        out[state] = fname
    return out


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

import json  # noqa: E402  (kept near manifest writer for clarity)

STATE_META = {
    "idle": ("Blinking block cursor at a terminal prompt", 2.0),
    "recording": ("REC indicator with a scrolling green waveform", 8.0),
    "processing": ("Classic ASCII spinner cycling on the screen", 8.0),
    "success": ("OK with a check, opening on a bright phosphor flash", 10.0),
    "error": ("ERR with horizontal glitch/tear lines", 10.0),
}


def write_manifest(frame_names: Dict[str, List[str]], sound_names: Dict[str, str]) -> None:
    states = {}
    for state, names in frame_names.items():
        desc, fps = STATE_META[state]
        entry: Dict[str, object] = {
            "file": names[0],  # single-icon fallback / preview source
            "description": desc,
            "frames": names,
            "fps": fps,
        }
        if state in sound_names:
            entry["sound"] = sound_names[state]
        states[state] = entry

    manifest = {
        "id": "crt-terminal",
        "name": "CRT Terminal",
        "description": (
            "A green-phosphor CRT terminal: scanlined screen, blinking cursor, "
            "scrolling waveform while recording, ASCII spinner, and glitchy errors."
        ),
        "author": "WhisperHUD",
        "version": "1.0.0",
        "preview_image": "idle_0.png",
        "states": states,
        "settings": {
            "shape_mode": "alpha",
            "apply_state_tint": False,
            "recommended_size": "large",
            "interpolation": "nearest",
        },
    }
    with open(OUTPUT_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


# --------------------------------------------------------------------------- #
# Contact sheet (all frames, x4) for visual QA
# --------------------------------------------------------------------------- #


def write_contact_sheet(frames: Dict[str, List[Image.Image]], path: Path) -> None:
    order = ["idle", "recording", "processing", "success", "error"]
    pad = 4
    tile = GRID * SCALE
    max_cols = max(len(frames[s]) for s in order)
    width = pad + len(order) * 1  # placeholder, recomputed below
    cols = max_cols
    rows = len(order)
    sheet_w = pad + cols * (tile + pad)
    sheet_h = pad + rows * (tile + pad)
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (24, 24, 28, 255))
    for r, state in enumerate(order):
        for c, im in enumerate(frames[state]):
            big = im.resize((tile, tile), Image.NEAREST)
            x = pad + c * (tile + pad)
            y = pad + r * (tile + pad)
            sheet.alpha_composite(big, (x, y))
    sheet.save(path, "PNG")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> None:
    frames = build_all_frames()
    frame_names = write_pngs(frames)
    sound_names = write_sounds()
    write_manifest(frame_names, sound_names)
    write_contact_sheet(frames, Path("/tmp/crt_terminal_contact.png"))
    # Brief stdout summary (script is a dev tool, not app code).
    total = sum(len(v) for v in frame_names.values())
    print(f"Wrote {total} PNG frames, {len(sound_names)} WAVs, manifest.json")
    print("Contact sheet: /tmp/crt_terminal_contact.png")


if __name__ == "__main__":
    main()
