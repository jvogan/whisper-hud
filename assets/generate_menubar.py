#!/usr/bin/env python3
"""
WhisperHUD Menu Bar Icon Generator

Renders the macOS status-bar template icon set: a HUD corner-bracket frame
around a per-state glyph (waveform, record dot, spinner, check, ...).

Icons are 40x40 px (displayed at 20x20 pt, i.e. @2x retina) and pure black
with alpha, so macOS template mode can tint them for light/dark menu bars.
Animated states also get numbered frame files (state.frameN.png).

Usage:
    python generate_menubar.py [--out DIR] [--preview FILE]

Requirements:
    pip install Pillow
"""

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Required: pip install Pillow")

# Canvas geometry (all coordinates in 40x40 icon space).
SIZE = 40
SUPER = 8  # supersampling factor for smooth antialiased downscale
S = SIZE * SUPER

# Shared HUD bracket frame.
FRAME_LEFT, FRAME_RIGHT = 5.0, 35.0
FRAME_TOP, FRAME_BOTTOM = 8.0, 32.0
BRACKET_ARM = 7.0
BRACKET_W = 3.0

CX = 20.0
CY = 20.0

BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)


def _pt(xy):
    """Scale a 40-space coordinate pair to the supersampled canvas."""
    return (xy[0] * SUPER, xy[1] * SUPER)


def _line(draw, a, b, width, color, rounded=False):
    draw.line([_pt(a), _pt(b)], fill=color, width=round(width * SUPER))
    if rounded:
        r = (width * SUPER) / 2.0
        for x, y in (_pt(a), _pt(b)):
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _polyline(draw, points, width, color):
    pts = [_pt(p) for p in points]
    draw.line(pts, fill=color, width=round(width * SUPER), joint="curve")
    r = (width * SUPER) / 2.0
    for x, y in pts:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _disc(draw, center, radius, color):
    x, y = _pt(center)
    r = radius * SUPER
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _arc(draw, center, radius, start_deg, end_deg, width, color):
    x, y = _pt(center)
    r = radius * SUPER
    draw.arc([x - r, y - r, x + r, y + r], start=start_deg, end=end_deg, fill=color, width=round(width * SUPER))


def draw_brackets(draw, color):
    """Four HUD viewfinder corners framing the content rect."""
    lf, r, t, b = FRAME_LEFT, FRAME_RIGHT, FRAME_TOP, FRAME_BOTTOM
    a, w = BRACKET_ARM, BRACKET_W
    half = w / 2.0
    # Each corner: a vertical and a horizontal arm meeting flush.
    for vert, horiz in (
        (((lf, t + a), (lf, t)), ((lf - half, t), (lf + a, t))),
        (((r, t + a), (r, t)), ((r + half, t), (r - a, t))),
        (((lf, b - a), (lf, b)), ((lf - half, b), (lf + a, b))),
        (((r, b - a), (r, b)), ((r + half, b), (r - a, b))),
    ):
        _line(draw, vert[0], vert[1], w, color)
        _line(draw, horiz[0], horiz[1], w, color)


def draw_idle(draw, color):
    """Waveform bars — the WhisperHUD voice mark."""
    heights = (6.0, 12.0, 17.0, 12.0, 6.0)
    pitch = 4.8
    bar_w = 2.9
    for i, h in enumerate(heights):
        x = CX + (i - 2) * pitch
        _line(draw, (x, CY - h / 2.0), (x, CY + h / 2.0), bar_w, color, rounded=True)


def draw_recording(draw, color, radius=5.6):
    _disc(draw, (CX, CY), radius, color)


def draw_processing(draw, color, rotation=0.0):
    """Open 270-degree spinner arc."""
    start = -90.0 + rotation
    _arc(draw, (CX, CY), 6.6, start, start + 270.0, 3.2, color)


def draw_success(draw, color):
    _polyline(draw, [(13.5, 20.0), (18.0, 24.4), (26.5, 15.5)], 3.4, color)


def draw_error(draw, color):
    _line(draw, (CX, 12.5), (CX, 22.5), 3.4, color, rounded=True)
    _disc(draw, (CX, 27.3), 2.0, color)


def draw_downloading(draw, color):
    _line(draw, (CX, 11.0), (CX, 22.5), 3.2, color, rounded=True)
    _polyline(draw, [(15.0, 18.2), (CX, 23.4), (25.0, 18.2)], 3.2, color)
    _line(draw, (13.0, 28.2), (27.0, 28.2), 3.0, color, rounded=True)


def draw_assistant(draw, color):
    """Tiny robot head: antenna, outlined head, two eyes."""
    w = 2.8
    # Head outline.
    x0, y0 = _pt((13.0, 16.0))
    x1, y1 = _pt((27.0, 27.5))
    draw.rounded_rectangle([x0, y0, x1, y1], radius=2.8 * SUPER, outline=color, width=round(w * SUPER))
    # Eyes.
    _disc(draw, (17.0, 21.7), 1.8, color)
    _disc(draw, (23.0, 21.7), 1.8, color)
    # Antenna.
    _line(draw, (CX, 16.0), (CX, 13.2), 2.4, color)
    _disc(draw, (CX, 12.2), 1.5, color)


def draw_private(draw, color):
    """Padlock: shackle arc over a filled body."""
    _arc(draw, (CX, 19.0), 4.6, 180.0, 360.0, 3.0, color)
    _line(draw, (15.4, 16.8), (15.4, 19.0), 3.0, color)
    _line(draw, (24.6, 16.8), (24.6, 19.0), 3.0, color)
    x0, y0 = _pt((13.2, 19.0))
    x1, y1 = _pt((26.8, 29.0))
    draw.rounded_rectangle([x0, y0, x1, y1], radius=2.2 * SUPER, fill=color)


# state -> (glyph fn, draw bracket frame?)
STATES = {
    "idle": (draw_idle, True),
    "recording": (draw_recording, True),
    "processing": (draw_processing, True),
    "success": (draw_success, True),
    "error": (draw_error, True),
    "downloading": (draw_downloading, True),
    "assistant": (draw_assistant, True),
    "private": (draw_private, True),
}

# Animated states: list of kwargs per frame.
RECORDING_FRAMES = [{"radius": r} for r in (4.6, 5.4, 6.2, 5.4)]
PROCESSING_FRAMES = [{"rotation": i * 45.0} for i in range(8)]


def render(glyph_fn, with_frame, color=BLACK, **kwargs) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if with_frame:
        draw_brackets(draw, color)
    glyph_fn(draw, color, **kwargs)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def build_preview(icons: dict) -> Image.Image:
    """Side-by-side light/dark strips at 1x and 3x for visual review."""
    names = list(icons)
    pad = 14
    cell = SIZE + pad
    zoom = 3
    cell_z = SIZE * zoom + pad
    width = pad + cell_z * len(names)
    height = (pad + cell) * 2 + (pad + cell_z) * 2 + pad
    sheet = Image.new("RGBA", (width, height), (120, 120, 120, 255))

    rows = [
        ((246, 246, 246, 255), BLACK, 1),
        ((29, 29, 31, 255), WHITE, 1),
        ((246, 246, 246, 255), BLACK, zoom),
        ((29, 29, 31, 255), WHITE, zoom),
    ]
    y = pad
    for bg, tint, scale in rows:
        row_h = SIZE * scale + pad
        strip = Image.new("RGBA", (width, row_h), bg)
        for i, name in enumerate(names):
            glyph_fn, with_frame, kwargs = icons[name]
            icon = render(glyph_fn, with_frame, color=tint, **kwargs)
            if scale != 1:
                icon = icon.resize((SIZE * scale, SIZE * scale), Image.NEAREST)
            strip.alpha_composite(icon, (pad + i * (SIZE * zoom + pad), pad // 2))
        sheet.alpha_composite(strip, (0, y))
        y += row_h + pad // 2
    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate WhisperHUD menu bar icons")
    parser.add_argument("--out", default=str(Path(__file__).parent / "menubar"))
    parser.add_argument("--preview", default=None, help="Also write a review sheet PNG here")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    preview_entries = {}
    for name, (glyph_fn, with_frame) in STATES.items():
        render(glyph_fn, with_frame).save(out_dir / f"{name}.png")
        preview_entries[name] = (glyph_fn, with_frame, {})

    for i, kwargs in enumerate(RECORDING_FRAMES):
        render(draw_recording, True, **kwargs).save(out_dir / f"recording.frame{i}.png")
    for i, kwargs in enumerate(PROCESSING_FRAMES):
        render(draw_processing, True, **kwargs).save(out_dir / f"processing.frame{i}.png")

    print(f"Wrote {len(STATES)} states (+{len(RECORDING_FRAMES) + len(PROCESSING_FRAMES)} frames) to {out_dir}")

    if args.preview:
        build_preview(preview_entries).save(args.preview)
        print(f"Preview sheet: {args.preview}")


if __name__ == "__main__":
    main()
