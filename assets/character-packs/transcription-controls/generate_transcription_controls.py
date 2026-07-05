#!/usr/bin/env python3
"""
Generate the Transcription Controls built-in icon pack.

The final assets are deterministic transparent PNGs. Image generation is best
used for concept/style exploration here; these committed buttons keep the
state glyphs exact and legible at menu-widget sizes.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUTPUT_DIR = Path(__file__).parent
CANVAS_SIZE = 512
SUPERSAMPLE = 4
SIZE = CANVAS_SIZE * SUPERSAMPLE
S = SUPERSAMPLE

PALETTES = {
    "idle": {
        "base": "#242832",
        "rim": "#566173",
        "glyph": "#9EB6D9",
        "accent": "#5C91E6",
        "shadow": "#05070A",
    },
    "recording": {
        "base": "#D92626",
        "rim": "#FF7474",
        "glyph": "#FFFFFF",
        "accent": "#FFB8B8",
        "shadow": "#170303",
    },
    "processing": {
        "base": "#BF8C19",
        "rim": "#FFD073",
        "glyph": "#FFFFFF",
        "accent": "#FFE2A8",
        "shadow": "#140C01",
    },
    "success": {
        "base": "#2E9F55",
        "rim": "#8BE6A8",
        "glyph": "#FFFFFF",
        "accent": "#CFF7DB",
        "shadow": "#031206",
    },
    "error": {
        "base": "#C9344A",
        "rim": "#FF8B9B",
        "glyph": "#FFFFFF",
        "accent": "#FFD1D8",
        "shadow": "#190207",
    },
}


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
        alpha,
    )


def _xy(values: tuple[float, ...]) -> tuple[int, ...]:
    return tuple(round(v * S) for v in values)


def _line(draw: ImageDraw.ImageDraw, xy: list[tuple[float, float]], fill: str, width: float) -> None:
    draw.line([_xy(point) for point in xy], fill=_hex_to_rgba(fill), width=round(width * S), joint="curve")


def _rounded_rectangle(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float, float, float],
    radius: float,
    fill: str,
    outline: str | None = None,
    width: float = 1,
) -> None:
    draw.rounded_rectangle(
        _xy(xy),
        radius=round(radius * S),
        fill=_hex_to_rgba(fill),
        outline=_hex_to_rgba(outline) if outline else None,
        width=round(width * S),
    )


def _draw_button_base(draw: ImageDraw.ImageDraw, state: str) -> None:
    palette = PALETTES[state]

    # Soft alpha shadow is part of the icon, so the button remains readable on any desktop.
    shadow_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.ellipse(_xy((74, 82, 438, 446)), fill=_hex_to_rgba(palette["shadow"], 120))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(18 * S))
    draw.bitmap((0, 0), shadow_layer, fill=None)

    draw.ellipse(
        _xy((78, 66, 434, 422)), fill=_hex_to_rgba(palette["base"]), outline=_hex_to_rgba(palette["rim"]), width=7 * S
    )
    draw.ellipse(_xy((103, 91, 409, 397)), outline=_hex_to_rgba("#FFFFFF", 46), width=3 * S)

    # Top highlight.
    highlight = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    highlight_draw.ellipse(_xy((116, 92, 396, 226)), fill=(255, 255, 255, 34))
    highlight = highlight.filter(ImageFilter.GaussianBlur(10 * S))
    draw.bitmap((0, 0), highlight, fill=None)


def _draw_power(draw: ImageDraw.ImageDraw, palette: dict[str, str]) -> None:
    draw.arc(_xy((165, 155, 347, 337)), start=32, end=328, fill=_hex_to_rgba(palette["glyph"]), width=24 * S)
    _line(draw, [(256, 130), (256, 240)], palette["glyph"], 24)
    draw.ellipse(_xy((238, 300, 274, 336)), fill=_hex_to_rgba(palette["accent"], 210))


def _draw_mic(draw: ImageDraw.ImageDraw, palette: dict[str, str]) -> None:
    _rounded_rectangle(draw, (211, 142, 301, 272), 45, palette["glyph"])
    _rounded_rectangle(draw, (231, 158, 281, 254), 24, "#D92626")
    draw.arc(_xy((176, 200, 336, 330)), start=18, end=162, fill=_hex_to_rgba(palette["glyph"]), width=18 * S)
    _line(draw, [(256, 320), (256, 364)], palette["glyph"], 18)
    _line(draw, [(216, 370), (296, 370)], palette["glyph"], 18)
    for offset in (58, 82):
        draw.arc(
            _xy((256 - offset, 176 - offset / 3, 256 + offset, 312 + offset / 3)),
            start=312,
            end=48,
            fill=_hex_to_rgba(palette["accent"], 190),
            width=8 * S,
        )
        draw.arc(
            _xy((256 - offset, 176 - offset / 3, 256 + offset, 312 + offset / 3)),
            start=132,
            end=228,
            fill=_hex_to_rgba(palette["accent"], 190),
            width=8 * S,
        )


def _draw_spinner(draw: ImageDraw.ImageDraw, palette: dict[str, str]) -> None:
    center = (256, 256)
    radius = 96
    for index in range(12):
        angle = math.radians(index * 30 - 90)
        alpha = 76 + index * 14
        dot_radius = 9 + index * 0.45
        x = center[0] + math.cos(angle) * radius
        y = center[1] + math.sin(angle) * radius
        draw.ellipse(
            _xy((x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius)),
            fill=_hex_to_rgba(palette["glyph"], min(255, round(alpha))),
        )
    _rounded_rectangle(draw, (220, 214, 292, 296), 30, palette["glyph"])
    draw.ellipse(_xy((239, 233, 273, 267)), fill=_hex_to_rgba(PALETTES["processing"]["base"]))


def _draw_check(draw: ImageDraw.ImageDraw, palette: dict[str, str]) -> None:
    _line(draw, [(163, 260), (226, 322), (358, 190)], palette["glyph"], 34)
    _line(draw, [(170, 260), (226, 314), (350, 190)], palette["accent"], 10)


def _draw_error(draw: ImageDraw.ImageDraw, palette: dict[str, str]) -> None:
    draw.polygon([_xy((256, 146)), _xy((365, 340)), _xy((147, 340))], fill=_hex_to_rgba(palette["glyph"]))
    draw.polygon([_xy((256, 184)), _xy((327, 316)), _xy((185, 316))], fill=_hex_to_rgba(PALETTES["error"]["base"]))
    _line(draw, [(256, 218), (256, 276)], palette["glyph"], 20)
    draw.ellipse(_xy((244, 294, 268, 318)), fill=_hex_to_rgba(palette["glyph"]))


DRAWERS = {
    "idle": _draw_power,
    "recording": _draw_mic,
    "processing": _draw_spinner,
    "success": _draw_check,
    "error": _draw_error,
}


def render_icon(state: str) -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _draw_button_base(draw, state)
    DRAWERS[state](draw, PALETTES[state])
    return image.resize((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)


def main() -> None:
    for state in DRAWERS:
        render_icon(state).save(OUTPUT_DIR / f"{state}.png", "PNG")


if __name__ == "__main__":
    main()
