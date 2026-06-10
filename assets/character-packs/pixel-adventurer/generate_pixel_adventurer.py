#!/usr/bin/env python3
"""
Generate the "Pixel Adventurer" character pack for WhisperHUD.

A charming 16-bit JRPG hero sprite, authored on a 40x40 logical pixel grid and
upscaled x4 with nearest-neighbour to crisp 160x160 RGBA PNGs (transparent
background). Every pixel is snapped to the logical grid: 1px dark outline,
2-tone shading (base + shadow), a tight DawnBringer-ish palette, no gradients
and no anti-aliasing.

States (manifest v2):
  idle       - relaxed stance, gentle breathing bob + occasional blink (loops)
  recording  - casting / charging stance, pulsing aura sparkles (loops)
  processing - thinking, hand on chin + a spinning hourglass (loops)
  success    - victory pose, sword raised + star burst (one-shot, holds frame)
  error      - dizzy, stars circling the head (one-shot, holds frame)

Sounds (chiptune, stdlib ``wave`` + numpy, 22050 Hz / mono / 16-bit PCM):
  recording  - bright select blip   (square 880->1320 Hz sweep, ~0.12s)
  success    - two-note coin chime   (E6 then B6, ~0.30s)
  error      - descending buzz       (square 440->110 Hz, ~0.25s)
  (idle / processing stay silent on purpose - they would be annoying.)

The script is fully DETERMINISTIC: no unseeded randomness, no time/date input.
Run it with the project's venv:

    .venv/bin/python assets/character-packs/pixel-adventurer/generate_pixel_adventurer.py

It writes every PNG, WAV and manifest.json into this directory, and a contact
sheet of all frames to /tmp/pixel_adventurer_contact.png for visual review.
"""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #

OUTPUT_DIR = Path(__file__).resolve().parent
GRID = 40           # logical pixel grid (40 x 40)
SCALE = 4           # nearest-neighbour upscale -> 160 x 160 final PNG
FINAL = GRID * SCALE

# --------------------------------------------------------------------------- #
# Palette (DawnBringer-16 vibe, ~14 hues). "." == transparent.
# --------------------------------------------------------------------------- #

RGBA = Tuple[int, int, int, int]
_T: RGBA = (0, 0, 0, 0)

PALETTE: Dict[str, RGBA] = {
    ".": _T,                       # transparent
    "K": (28, 20, 38, 255),        # near-black outline (deep plum)
    "o": (60, 46, 74, 255),        # soft inner shadow / secondary outline
    # skin
    "s": (242, 190, 152, 255),     # skin base
    "S": (198, 140, 112, 255),     # skin shadow
    # hair (warm brown)
    "h": (152, 92, 52, 255),       # hair base
    "H": (104, 58, 34, 255),       # hair shadow
    # tunic (forest green)
    "g": (78, 162, 94, 255),       # tunic base
    "G": (46, 112, 68, 255),       # tunic shadow
    # leather (belt / boots / straps)
    "b": (122, 80, 48, 255),       # leather base
    "B": (84, 52, 30, 255),        # leather shadow
    # trousers (muted blue)
    "p": (76, 98, 152, 255),       # trouser base
    "P": (50, 66, 112, 255),       # trouser shadow
    # sword: steel blade + gold hilt
    "w": (216, 226, 234, 255),     # blade base
    "W": (150, 166, 184, 255),     # blade shadow
    "y": (246, 198, 74, 255),      # gold base (hilt / accents)
    "Y": (198, 150, 44, 255),      # gold shadow
    # shield (red w/ gold rim via y)
    "r": (202, 66, 66, 255),       # shield red base
    "R": (150, 42, 46, 255),       # shield red shadow
    # cape (royal blue, shown on victory)
    "c": (72, 98, 200, 255),       # cape base
    "C": (46, 64, 150, 255),       # cape shadow
    # effects
    "a": (132, 226, 255, 255),     # aura / magic cyan (light)
    "A": (88, 168, 230, 255),      # aura cyan (deep)
    "f": (255, 242, 152, 255),     # spark / star (light)
    "F": (255, 196, 80, 255),      # spark / star (deep)
    "u": (192, 152, 255, 255),     # dizzy star (purple)
    "e": (246, 246, 250, 255),     # eye white / white sparkle
    "z": (150, 202, 236, 255),     # hourglass glass / frame
    "n": (236, 206, 120, 255),     # hourglass sand
}

Grid = List[List[str]]


# --------------------------------------------------------------------------- #
# Tiny pixel drawing API (all coordinates are logical grid pixels)
# --------------------------------------------------------------------------- #

def new_grid() -> Grid:
    return [["." for _ in range(GRID)] for _ in range(GRID)]


def px(g: Grid, x: int, y: int, c: str) -> None:
    """Plot one pixel (transparent code is a no-op so layers compose)."""
    if c == "." or not c:
        return
    xi = int(round(x))
    yi = int(round(y))
    if 0 <= xi < GRID and 0 <= yi < GRID:
        g[yi][xi] = c


def rect(g: Grid, x0: int, y0: int, x1: int, y1: int, c: str) -> None:
    """Filled rectangle, inclusive of both corners."""
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px(g, x, y, c)


def hline(g: Grid, x0: int, x1: int, y: int, c: str) -> None:
    rect(g, x0, y, x1, y, c)


def vline(g: Grid, x: int, y0: int, y1: int, c: str) -> None:
    rect(g, x, y0, x, y1, c)


def disc(g: Grid, cx: float, cy: float, r: float, c: str) -> None:
    """Filled circle (grid-snapped)."""
    r2 = r * r
    for y in range(int(math.floor(cy - r)), int(math.ceil(cy + r)) + 1):
        for x in range(int(math.floor(cx - r)), int(math.ceil(cx + r)) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                px(g, x, y, c)


def ring(g: Grid, cx: float, cy: float, r: float, c: str) -> None:
    """A 1px-ish ring outline at radius r (used for shield rim, sparkles)."""
    steps = max(8, int(2 * math.pi * r * 1.6))
    for i in range(steps):
        a = 2 * math.pi * i / steps
        px(g, cx + r * math.cos(a), cy + r * math.sin(a), c)


def stamp(g: Grid, rows: Sequence[str], ox: int, oy: int) -> None:
    """Stamp an ASCII block at offset (ox, oy); spaces & '.' are transparent."""
    for dy, row in enumerate(rows):
        for dx, ch in enumerate(row):
            if ch not in (".", " "):
                px(g, ox + dx, oy + dy, ch)


def outline_silhouette(g: Grid, color: str = "K") -> None:
    """Add a 1px dark outline around every opaque pixel that lacks one.

    Any transparent cell that is 4-neighbour-adjacent to a non-outline opaque
    pixel becomes an outline pixel. This guarantees a clean, consistent border
    even where hand-placed outlines have small gaps.
    """
    additions: List[Tuple[int, int]] = []
    for y in range(GRID):
        for x in range(GRID):
            if g[y][x] != ".":
                continue
            adjacent_solid = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < GRID and 0 <= ny < GRID:
                    nb = g[ny][nx]
                    if nb not in (".", color, "o"):
                        adjacent_solid = True
                        break
            if adjacent_solid:
                additions.append((x, y))
    for x, y in additions:
        g[y][x] = color


# --------------------------------------------------------------------------- #
# Hero construction
# --------------------------------------------------------------------------- #
# The hero is built procedurally and centered on x ~= 20. The head sits high
# enough that a raised sword and circling stars have head-room. ``bob`` shifts
# the whole figure vertically for the idle breathing loop.

HEAD_CX = 20          # head/torso centre column
HEAD_TOP = 8          # top of hair (before bob)


def draw_head(g: Grid, top: int, eyes: str = "open") -> None:
    """Draw the hero head: hair, face, eyes, mouth. ``top`` = hair top row."""
    cx = HEAD_CX
    # --- hair cap ---
    rect(g, cx - 4, top + 0, cx + 4, top + 0, "h")
    rect(g, cx - 5, top + 1, cx + 5, top + 3, "h")
    # hair shading along the right + a few strands
    vline(g, cx + 4, top + 1, top + 3, "H")
    px(g, cx - 4, top + 2, "H")
    px(g, cx + 2, top + 1, "H")
    # a little spiky fringe poking onto the forehead
    px(g, cx - 3, top + 4, "h")
    px(g, cx - 1, top + 4, "h")
    px(g, cx + 1, top + 4, "h")
    px(g, cx + 3, top + 4, "h")

    # --- face (skin) ---
    rect(g, cx - 4, top + 4, cx + 4, top + 9, "s")
    # jaw taper
    px(g, cx - 4, top + 9, ".")
    px(g, cx + 4, top + 9, ".")
    rect(g, cx - 3, top + 10, cx + 3, top + 10, "s")
    # cheek / jaw shadow
    vline(g, cx + 4, top + 5, top + 8, "S")
    px(g, cx + 3, top + 9, "S")
    px(g, cx - 3, top + 9, "S")
    px(g, cx - 2, top + 10, "S")
    px(g, cx + 2, top + 10, "S")
    # ear hints
    px(g, cx - 4, top + 7, "S")
    px(g, cx + 4, top + 7, "S")

    # --- eyes ---
    eye_y = top + 6
    if eyes == "blink":
        # closed eyes: short shaded lash lines
        hline(g, cx - 3, cx - 2, eye_y, "S")
        hline(g, cx + 2, cx + 3, eye_y, "S")
    elif eyes == "dazed":
        # dizzy eyes: a 2x2 white field with a dark diagonal "x" stroke so two
        # opposite corners stay white (reads clearly as crossed-out eyes).
        for j, ex in enumerate((cx - 3, cx + 2)):
            px(g, ex, eye_y - 1, "e")
            px(g, ex + 1, eye_y - 1, "e")
            px(g, ex, eye_y, "e")
            px(g, ex + 1, eye_y, "e")
            if j == 0:  # left eye: "\" stroke
                px(g, ex, eye_y - 1, "K")
                px(g, ex + 1, eye_y, "K")
            else:       # right eye: "/" stroke (mirrored)
                px(g, ex + 1, eye_y - 1, "K")
                px(g, ex, eye_y, "K")
            # faint dazed brow above each eye
            px(g, ex, eye_y - 2, "H")
    else:
        # open eyes: white + dark pupil
        px(g, cx - 3, eye_y, "e")
        px(g, cx - 2, eye_y, "K")
        px(g, cx + 2, eye_y, "K")
        px(g, cx + 3, eye_y, "e")
        # tiny brow accent
        px(g, cx - 3, eye_y - 1, "H")
        px(g, cx + 3, eye_y - 1, "H")

    # --- nose + mouth ---
    px(g, cx, top + 7, "S")
    if eyes == "dazed":
        # woozy little open "o" mouth -> reads as "oops"
        px(g, cx, top + 9, "K")
        px(g, cx - 1, top + 9, "S")
        px(g, cx + 1, top + 9, "S")
        px(g, cx, top + 10, "S")
    else:
        hline(g, cx - 1, cx + 1, top + 9, "S")  # gentle smile


def draw_torso(g: Grid, top: int) -> None:
    """Draw neck, tunic torso, belt, trousers, boots. ``top`` = hair top row."""
    cx = HEAD_CX
    neck_y = top + 11
    # neck
    rect(g, cx - 1, neck_y, cx + 1, neck_y, "s")
    px(g, cx + 1, neck_y, "S")

    sh = neck_y + 1                       # shoulder row
    # --- tunic torso (trapezoid) ---
    rect(g, cx - 5, sh + 0, cx + 5, sh + 0, "g")       # shoulders
    rect(g, cx - 6, sh + 1, cx + 6, sh + 5, "g")       # chest/belly
    # tunic shading (right side + collar V)
    vline(g, cx + 6, sh + 1, sh + 5, "G")
    vline(g, cx + 5, sh + 4, sh + 5, "G")
    px(g, cx - 1, sh + 1, "G")
    px(g, cx + 1, sh + 1, "G")
    px(g, cx, sh + 2, "G")
    # a lighter tunic collar trim
    px(g, cx - 2, sh + 1, "g")
    px(g, cx + 2, sh + 1, "g")

    # --- belt ---
    belt_y = sh + 6
    rect(g, cx - 6, belt_y, cx + 6, belt_y, "b")
    rect(g, cx - 6, belt_y, cx + 6, belt_y, "b")
    vline(g, cx + 6, belt_y, belt_y, "B")
    # gold buckle
    px(g, cx, belt_y, "y")
    px(g, cx - 1, belt_y, "Y")

    # --- trousers ---
    tr = belt_y + 1
    rect(g, cx - 5, tr + 0, cx + 5, tr + 1, "p")
    # leg split
    vline(g, cx, tr + 1, tr + 4, ".")
    rect(g, cx - 5, tr + 2, cx - 1, tr + 4, "p")
    rect(g, cx + 1, tr + 2, cx + 5, tr + 4, "p")
    # trouser shading
    vline(g, cx - 1, tr + 2, tr + 4, "P")
    vline(g, cx + 5, tr + 0, tr + 4, "P")
    px(g, cx + 1, tr + 2, "P")

    # --- boots ---
    bt = tr + 5
    rect(g, cx - 5, bt, cx - 1, bt + 1, "b")
    rect(g, cx + 1, bt, cx + 5, bt + 1, "b")
    # boot shading + soles
    hline(g, cx - 5, cx - 1, bt + 1, "B")
    hline(g, cx + 1, cx + 5, bt + 1, "B")
    px(g, cx - 1, bt, "B")
    px(g, cx + 5, bt, "B")


def draw_shield_arm(g: Grid, top: int, raised: bool = False) -> None:
    """Hero's right arm (viewer-left) holding a round shield."""
    cx = HEAD_CX
    sh = top + 12
    if raised:
        # arm bent upward holding shield high
        rect(g, cx - 8, sh + 1, cx - 7, sh + 4, "g")   # upper arm sleeve
        rect(g, cx - 8, sh - 2, cx - 7, sh + 0, "s")   # forearm raised
        cy = sh - 4
        _round_shield(g, cx - 8, cy)
    else:
        # arm down by side, shield facing front lower-left
        rect(g, cx - 7, sh + 1, cx - 6, sh + 3, "g")   # sleeve
        px(g, cx - 7, sh + 4, "s")                     # hand
        _round_shield(g, cx - 9, sh + 5)


def _round_shield(g: Grid, cx: float, cy: float) -> None:
    """A small heraldic round shield centred at (cx, cy)."""
    disc(g, cx, cy, 3.2, "r")
    # shadow lower-right
    disc(g, cx + 0.7, cy + 0.7, 2.4, "R")
    disc(g, cx - 0.4, cy - 0.4, 2.1, "r")
    # gold rim
    ring(g, cx, cy, 3.2, "y")
    # gold boss + cross emblem
    px(g, cx, cy, "y")
    px(g, cx, cy - 1, "Y")
    px(g, cx, cy + 1, "Y")


def draw_sword_arm(
    g: Grid,
    top: int,
    pose: str = "rest",
    cast_offset: int = 0,
) -> None:
    """Hero's left arm (viewer-right) holding the sword.

    pose: 'rest'   - sword pointed down at the side
          'cast'   - sword/hand raised forward, blade glowing (recording)
          'raised' - sword thrust straight up (success)
    """
    cx = HEAD_CX
    sh = top + 12
    if pose == "raised":
        # arm straight up
        rect(g, cx + 6, sh - 1, cx + 7, sh + 3, "g")    # sleeve
        rect(g, cx + 6, sh - 4, cx + 7, sh - 2, "s")    # forearm
        # sword pointing up from the fist
        _sword(g, cx + 6, sh - 5, direction="up", length=10)
    elif pose == "cast":
        # forearm raised forward & slightly up, sword angled up-right
        yy = sh - cast_offset
        rect(g, cx + 6, sh + 0, cx + 7, sh + 3, "g")    # sleeve
        rect(g, cx + 7, yy - 1, cx + 8, yy + 1, "s")    # hand forward
        _sword(g, cx + 9, yy - 1, direction="up", length=8)
    else:  # rest
        rect(g, cx + 6, sh + 1, cx + 7, sh + 4, "g")    # sleeve
        px(g, cx + 7, sh + 5, "s")                      # hand
        _sword(g, cx + 8, sh + 4, direction="down", length=9)


def _sword(g: Grid, hx: int, hy: int, direction: str = "up", length: int = 9) -> None:
    """Draw a sword with gold cross-guard + hilt; blade extends from (hx,hy)."""
    # cross-guard (gold) at the hand
    hline(g, hx - 1, hx + 1, hy, "y")
    px(g, hx - 1, hy, "Y")
    if direction == "up":
        # pommel/grip just below guard
        px(g, hx, hy + 1, "y")
        # blade upward
        for i in range(1, length + 1):
            yy = hy - i
            px(g, hx, yy, "w")
            px(g, hx + 1, yy, "W")   # one-pixel bevel shadow
        # pointed tip
        px(g, hx, hy - length - 1, "w")
    else:  # down
        px(g, hx, hy - 1, "y")       # grip above guard
        for i in range(1, length + 1):
            yy = hy + i
            px(g, hx, yy, "w")
            px(g, hx + 1, yy, "W")
        px(g, hx, hy + length + 1, "w")


def draw_cape(g: Grid, top: int) -> None:
    """A small royal-blue cape flaring behind the shoulders (victory only)."""
    cx = HEAD_CX
    sh = top + 12
    rect(g, cx - 7, sh + 1, cx - 6, sh + 6, "c")
    px(g, cx - 8, sh + 4, "c")
    px(g, cx - 8, sh + 6, "C")
    vline(g, cx - 6, sh + 1, sh + 6, "C")
    px(g, cx - 7, sh + 6, "C")


# --------------------------------------------------------------------------- #
# Hero presets used by multiple states
# --------------------------------------------------------------------------- #

def hero_base(
    g: Grid,
    bob: int = 0,
    eyes: str = "open",
    sword: str = "rest",
    shield_raised: bool = False,
    cast_offset: int = 0,
    cape: bool = False,
) -> None:
    """Compose a full hero into grid ``g`` with the given pose options."""
    top = HEAD_TOP + bob
    if cape:
        draw_cape(g, top)
    # Back arm first so the body overlaps it cleanly.
    draw_shield_arm(g, top, raised=shield_raised)
    draw_torso(g, top)
    draw_head(g, top, eyes=eyes)
    draw_sword_arm(g, top, pose=sword, cast_offset=cast_offset)


# --------------------------------------------------------------------------- #
# Effect helpers
# --------------------------------------------------------------------------- #

def spark(g: Grid, cx: int, cy: int, size: int, c_light: str, c_deep: str) -> None:
    """A 4-point sparkle/star."""
    px(g, cx, cy, c_light)
    for i in range(1, size + 1):
        c = c_light if i <= 1 else c_deep
        px(g, cx + i, cy, c)
        px(g, cx - i, cy, c)
        px(g, cx, cy + i, c)
        px(g, cx, cy - i, c)


def small_star(g: Grid, cx: int, cy: int, c: str) -> None:
    """A tiny + shaped dizzy star."""
    px(g, cx, cy, "e")
    px(g, cx + 1, cy, c)
    px(g, cx - 1, cy, c)
    px(g, cx, cy + 1, c)
    px(g, cx, cy - 1, c)


def hourglass(g: Grid, cx: int, cy: int, phase: float) -> None:
    """A small hourglass; ``phase`` in [0,1) animates the falling sand."""
    # frame (z), top & bottom bulbs
    rows = [
        "zzzzz",
        ".zzz.",
        "..z..",
        ".zzz.",
        "zzzzz",
    ]
    stamp(g, rows, cx - 2, cy - 2)
    # sand: amount in top vs bottom depends on phase
    top_amt = 1.0 - phase
    if top_amt > 0.5:
        hline(g, cx - 1, cx + 1, cy - 1, "n")
    if top_amt > 0.15:
        px(g, cx, cy - 1, "n")
    # a falling grain in the neck
    px(g, cx, cy, "n")
    # bottom pile grows with phase
    bot = phase
    if bot > 0.3:
        px(g, cx, cy + 1, "n")
    if bot > 0.6:
        hline(g, cx - 1, cx + 1, cy + 1, "n")


# --------------------------------------------------------------------------- #
# Frame builders (one function per state -> list of grids)
# --------------------------------------------------------------------------- #

def build_idle() -> List[Grid]:
    """4 frames: gentle breathing bob; the 4th frame blinks."""
    frames: List[Grid] = []
    specs = [
        (0, "open"),   # neutral
        (-1, "open"),  # inhale (rise)
        (0, "open"),   # neutral
        (0, "blink"),  # blink at rest
    ]
    for bob, eyes in specs:
        g = new_grid()
        hero_base(g, bob=bob, eyes=eyes, sword="rest")
        outline_silhouette(g)
        frames.append(g)
    return frames


def build_recording() -> List[Grid]:
    """5 frames: casting stance with a pulsing aura of cyan sparkles."""
    frames: List[Grid] = []
    # aura sparkle positions (around the raised hand / blade), with per-frame
    # radius pulse so it visibly breathes.
    centre = (29, 13)
    for i in range(5):
        g = new_grid()
        pulse = i % 4
        cast = [0, 1, 2, 1][pulse]
        hero_base(g, bob=0, eyes="open", sword="cast", cast_offset=cast)
        outline_silhouette(g)
        # aura ring of sparkles AFTER outline so they sit on top, unbordered
        n = 6
        base_r = 4.0 + [0.0, 1.0, 2.0, 1.0][pulse]
        for k in range(n):
            ang = 2 * math.pi * k / n + i * 0.5
            r = base_r + (0.6 if (k + i) % 2 == 0 else 0.0)
            sx = centre[0] + r * math.cos(ang)
            sy = centre[1] + r * math.sin(ang)
            c = "a" if (k + i) % 2 == 0 else "A"
            px(g, sx, sy, c)
        # a brighter core glow on the blade tip on alternating frames
        if i % 2 == 0:
            spark(g, centre[0] + 1, centre[1] - 2, 1, "a", "A")
        frames.append(g)
    return frames


def build_processing() -> List[Grid]:
    """5 frames: thinking (hand-to-chin) with a spinning hourglass + thought dots."""
    frames: List[Grid] = []
    for i in range(5):
        g = new_grid()
        # slight head tilt feel via a 1px bob every other frame
        bob = -1 if i % 2 == 1 else 0
        # custom 'thinking' pose: shield arm down, sword arm bent so the hand
        # reaches the chin. We reuse hero_base for body, then overdraw a chin
        # hand and hide the resting sword by drawing 'rest' low.
        hero_base(g, bob=bob, eyes="open", sword="rest")
        top = HEAD_TOP + bob
        cx = HEAD_CX
        # hand to chin (overdraw skin near jaw)
        px(g, cx + 4, top + 10, "s")
        px(g, cx + 5, top + 9, "s")
        px(g, cx + 5, top + 8, "S")
        outline_silhouette(g)
        # spinning hourglass beside the head
        hourglass(g, 33, top + 4, phase=(i / 5.0))
        # three thought dots that pop in sequence above the head
        dots = (i % 5)
        if dots >= 1:
            px(g, cx + 6, top + 1, "e")
        if dots >= 2:
            px(g, cx + 7, top - 1, "e")
        if dots >= 3:
            spark(g, cx + 8, top - 3, 1, "f", "F")
        frames.append(g)
    return frames


def build_success() -> List[Grid]:
    """7 frames, one-shot: rise into a victory pose, sword raised + star burst.

    The LAST frame is a clean triumphant hold (sword up, biggest stars settled
    symmetrically) since the engine holds it after one play.
    """
    frames: List[Grid] = []
    # frames 0-1: wind up (sword still resting, slight crouch)
    # frames 2-3: sword swings up
    # frames 4-6: full victory, expanding star burst, settle to clean hold
    for i in range(7):
        g = new_grid()
        if i == 0:
            hero_base(g, bob=1, eyes="open", sword="rest")
            outline_silhouette(g)
        elif i == 1:
            hero_base(g, bob=0, eyes="open", sword="rest", cape=True)
            outline_silhouette(g)
        else:
            shield_raised = i >= 3
            hero_base(
                g,
                bob=-1 if i >= 4 else 0,
                eyes="open",
                sword="raised",
                shield_raised=shield_raised,
                cape=True,
            )
            outline_silhouette(g)
            # star burst around the raised sword tip, growing then settling
            tip = (26, HEAD_TOP - 6)
            burst = {2: 2, 3: 3, 4: 5, 5: 4, 6: 3}.get(i, 3)
            positions = [
                (tip[0], tip[1] - 1),
                (tip[0] - 4, tip[1] + 2),
                (tip[0] + 4, tip[1] + 2),
                (tip[0] - 6, tip[1] + 6),
                (tip[0] + 6, tip[1] + 6),
                (tip[0] - 2, tip[1] + 8),
                (tip[0] + 2, tip[1] + 8),
            ]
            # On the final hold frame use a clean, symmetric trio of stars.
            if i == 6:
                for (sx, sy) in [(tip[0], tip[1] - 1),
                                 (tip[0] - 5, tip[1] + 4),
                                 (tip[0] + 5, tip[1] + 4)]:
                    spark(g, sx, sy, 1, "f", "F")
            else:
                for (sx, sy) in positions[:burst]:
                    sz = 2 if (sx == tip[0]) else 1
                    spark(g, sx, sy, sz, "f", "F")
        frames.append(g)
    return frames


def _composite_shifted(dst: Grid, src: Grid, dx: int, dy: int = 0) -> None:
    """Copy every opaque pixel of ``src`` into ``dst`` offset by (dx, dy)."""
    for y in range(GRID):
        for x in range(GRID):
            ch = src[y][x]
            if ch != ".":
                px(dst, x + dx, y + dy, ch)


def build_error() -> List[Grid]:
    """5 frames, one-shot: dizzy hero, stars circling the head; last frame 'oops'."""
    frames: List[Grid] = []
    n_stars = 3
    # Whole-figure side-to-side wobble sells the dizziness; the entire sprite
    # (outline + every limb) shifts together so it never tears.
    wobble = [0, 1, 1, -1, -1]
    for i in range(5):
        # Build the full dazed hero on a temp grid, then shift it by the wobble
        # so the outline + every limb move together (no gaps).
        tmp = new_grid()
        top = HEAD_TOP
        draw_shield_arm(tmp, top, raised=False)
        draw_torso(tmp, top)
        draw_head(tmp, top, eyes="dazed")
        draw_sword_arm(tmp, top, pose="rest")
        outline_silhouette(tmp)

        g = new_grid()
        _composite_shifted(g, tmp, dx=wobble[i])

        # three purple stars circling the head, rotating each frame
        for k in range(n_stars):
            ang = 2 * math.pi * (k / n_stars) + i * (2 * math.pi / 5)
            r = 6.5
            sx = HEAD_CX + wobble[i] + r * math.cos(ang)
            sy = (top + 2) + (r * 0.5) * math.sin(ang)
            small_star(g, int(round(sx)), int(round(sy)), "u")
        frames.append(g)
    return frames


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def grid_to_image(g: Grid) -> Image.Image:
    """Convert a logical grid to a crisp x4 RGBA PNG via nearest-neighbour."""
    small = Image.new("RGBA", (GRID, GRID), _T)
    px_access = small.load()
    for y in range(GRID):
        for x in range(GRID):
            px_access[x, y] = PALETTE[g[y][x]]
    return small.resize((FINAL, FINAL), Image.NEAREST)


STATE_BUILDERS = {
    "idle": build_idle,
    "recording": build_recording,
    "processing": build_processing,
    "success": build_success,
    "error": build_error,
}


def write_pngs() -> Dict[str, List[str]]:
    """Render every state's frames to PNGs. Returns {state: [filenames]}."""
    written: Dict[str, List[str]] = {}
    for state, builder in STATE_BUILDERS.items():
        frames = builder()
        names: List[str] = []
        for idx, g in enumerate(frames):
            name = f"{state}_{idx}.png"
            grid_to_image(g).save(OUTPUT_DIR / name)
            names.append(name)
        written[state] = names
    return written


def write_contact_sheet(written: Dict[str, List[str]], path: Path) -> None:
    """Tile all frames (one row per state) into a single review image."""
    states = list(written.keys())
    max_cols = max(len(v) for v in written.values())
    pad = 8
    cell = FINAL
    label_h = 0
    w = pad + max_cols * (cell + pad)
    h = pad + len(states) * (cell + pad + label_h)
    sheet = Image.new("RGBA", (w, h), (40, 40, 52, 255))
    for r, state in enumerate(states):
        for c, name in enumerate(written[state]):
            img = Image.open(OUTPUT_DIR / name).convert("RGBA")
            x = pad + c * (cell + pad)
            y = pad + r * (cell + pad + label_h)
            sheet.alpha_composite(img, (x, y))
    sheet.save(path)


# --------------------------------------------------------------------------- #
# Chiptune sound generation (stdlib wave + numpy)
# --------------------------------------------------------------------------- #

SAMPLE_RATE = 22050
PEAK = 0.30  # peak amplitude (fraction of full scale)


def _square(freq: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Square wave from an instantaneous-frequency array (phase-accumulated)."""
    phase = 2 * math.pi * np.cumsum(freq) / SAMPLE_RATE
    return np.sign(np.sin(phase))


def _envelope(n: int, attack: float = 0.005, decay: float = 1.0) -> np.ndarray:
    """Fast attack + exponential decay; last samples forced to exactly 0."""
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    atk_n = max(1, int(attack * SAMPLE_RATE))
    env = np.exp(-decay * 3.5 * t)
    # linear attack ramp
    ramp = np.minimum(1.0, np.arange(n) / atk_n)
    env = env * ramp
    # force a clean fade to zero over the final ~80 samples (no click)
    tail = min(80, n)
    env[-tail:] *= np.linspace(1.0, 0.0, tail)
    return env


def _to_pcm16(signal: np.ndarray) -> bytes:
    """Normalize to PEAK, clip, and pack as little-endian 16-bit PCM."""
    sig = np.asarray(signal, dtype=np.float64)
    peak = np.max(np.abs(sig)) or 1.0
    sig = (sig / peak) * PEAK
    sig = np.clip(sig, -1.0, 1.0)
    # ensure the very last sample is exactly zero
    sig[-1] = 0.0
    return (sig * 32767.0).astype("<i2").tobytes()


def _write_wav(path: Path, signal: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(_to_pcm16(signal))


def make_recording_sound() -> np.ndarray:
    """Bright select blip: square 880 -> 1320 Hz sweep, ~0.12s."""
    dur = 0.12
    n = int(dur * SAMPLE_RATE)
    t = np.linspace(0.0, dur, n, endpoint=False)
    freq = np.linspace(880.0, 1320.0, n)
    wave_ = _square(freq, t)
    return wave_ * _envelope(n, attack=0.003, decay=1.1)


def make_success_sound() -> np.ndarray:
    """Two-note coin chime: E6 (~1318.5) then B6 (~1975.5), ~0.30s total."""
    note_dur = 0.15
    n = int(note_dur * SAMPLE_RATE)
    t = np.linspace(0.0, note_dur, n, endpoint=False)

    def note(freq: float, decay: float) -> np.ndarray:
        f = np.full(n, freq)
        return _square(f, t) * _envelope(n, attack=0.003, decay=decay)

    e6 = note(1318.51, 1.4)
    b6 = note(1975.53, 1.0)
    sig = np.concatenate([e6, b6])
    return sig


def make_error_sound() -> np.ndarray:
    """Descending buzz: square 440 -> 110 Hz, ~0.25s."""
    dur = 0.25
    n = int(dur * SAMPLE_RATE)
    t = np.linspace(0.0, dur, n, endpoint=False)
    freq = np.linspace(440.0, 110.0, n)
    wave_ = _square(freq, t)
    return wave_ * _envelope(n, attack=0.004, decay=0.9)


def write_sounds() -> Dict[str, str]:
    """Write the three state sounds. Returns {state: filename}."""
    sounds = {
        "recording": ("blip.wav", make_recording_sound()),
        "success": ("chime.wav", make_success_sound()),
        "error": ("buzz.wav", make_error_sound()),
    }
    out: Dict[str, str] = {}
    for state, (name, sig) in sounds.items():
        _write_wav(OUTPUT_DIR / name, sig)
        out[state] = name
    return out


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

STATE_FPS = {
    "idle": 3,
    "recording": 8,
    "processing": 8,
    "success": 10,
    "error": 8,
}

STATE_DESCRIPTIONS = {
    "idle": "Hero at ease, gently breathing with the occasional blink",
    "recording": "Hero in a casting stance, sword charging with a pulsing aura",
    "processing": "Hero thinking, hand to chin beside a spinning hourglass",
    "success": "Hero's victory pose: sword raised high in a burst of stars",
    "error": "Hero dazed and dizzy with stars circling overhead",
}


def write_manifest(frames: Dict[str, List[str]], sounds: Dict[str, str]) -> None:
    states: Dict[str, Dict] = {}
    for state, names in frames.items():
        entry: Dict = {
            "file": names[0],
            "description": STATE_DESCRIPTIONS[state],
            "frames": names,
            "fps": STATE_FPS[state],
        }
        if state in sounds:
            entry["sound"] = sounds[state]
        states[state] = entry

    manifest = {
        "id": "pixel-adventurer",
        "name": "Pixel Adventurer",
        "description": (
            "A charming 16-bit JRPG hero who breathes, casts, thinks, "
            "celebrates and gets dizzy right in your menu bar."
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
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    frames = write_pngs()
    sounds = write_sounds()
    write_manifest(frames, sounds)
    contact = Path("/tmp/pixel_adventurer_contact.png")
    write_contact_sheet(frames, contact)

    total_frames = sum(len(v) for v in frames.values())
    print(f"Wrote {total_frames} frames across {len(frames)} states to {OUTPUT_DIR}")
    for state, names in frames.items():
        snd = sounds.get(state, "-")
        print(f"  {state:10s} {len(names)} frames @ {STATE_FPS[state]}fps  sound={snd}")
    print(f"Contact sheet: {contact}")


if __name__ == "__main__":
    main()
