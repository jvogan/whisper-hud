#!/usr/bin/env python3
"""
WhisperHUD Character Pack Extras Generator

Derives two optional extras for the built-in retro packs from their existing
idle art, keeping everything on the original pixel grid (NEAREST only):

- ``menubar.png``: a 40x40 color glyph the app shows in the menu bar while
  idle when the pack is active (``menubar_icon`` manifest key).
- ``idle_rare.frame*.png``: a short one-shot "hop" the widget plays rarely
  after long idle stretches (``idle_rare`` manifest state).

Run after changing pack idle art:
    python generate_pack_extras.py
"""

import json
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Required: pip install Pillow")

PACKS_DIR = Path(__file__).parent / "character-packs"
PACKS = ("pixel-adventurer", "handheld-89", "crt-terminal")

MENUBAR_CANVAS = 40
HOP_FPS = 10
# Hop arc as fractions of the source height: lift-off, two apex frames for
# hang time, landing. Frame 0 doubles as the state's static file.
HOP_SHIFTS = (0.0, 0.06, 0.12, 0.12, 0.06, 0.0)


def make_menubar_glyph(src: Image.Image) -> Image.Image:
    """Downscale pack art to a 40x40 menu bar glyph on the pixel grid."""
    size = src.width
    # Prefer an exact integer downscale (40 when possible, else 32 padded).
    inner = MENUBAR_CANVAS if size % MENUBAR_CANVAS == 0 else 32
    scaled = src.resize((inner, inner), Image.NEAREST)
    canvas = Image.new("RGBA", (MENUBAR_CANVAS, MENUBAR_CANVAS), (0, 0, 0, 0))
    offset = (MENUBAR_CANVAS - inner) // 2
    canvas.alpha_composite(scaled, (offset, offset))
    return canvas


def make_hop_frames(src: Image.Image) -> list:
    """Vertical integer-pixel shifts so the sprite stays grid-crisp."""
    frames = []
    for fraction in HOP_SHIFTS:
        shift = round(src.height * fraction)
        canvas = Image.new("RGBA", src.size, (0, 0, 0, 0))
        canvas.alpha_composite(src, (0, -shift))
        frames.append(canvas)
    return frames


def update_manifest(pack_dir: Path, frame_names: list) -> None:
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    manifest["menubar_icon"] = "menubar.png"
    manifest["states"]["idle_rare"] = {
        "file": frame_names[0],
        "description": "A surprised little hop after a long quiet stretch",
        "frames": frame_names,
        "fps": HOP_FPS,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    for pack_name in PACKS:
        pack_dir = PACKS_DIR / pack_name
        manifest = json.loads((pack_dir / "manifest.json").read_text())
        idle_file = manifest["states"]["idle"]["file"]
        src = Image.open(pack_dir / idle_file).convert("RGBA")

        make_menubar_glyph(src).save(pack_dir / "menubar.png")

        frame_names = []
        for i, frame in enumerate(make_hop_frames(src)):
            name = f"idle_rare.frame{i}.png"
            frame.save(pack_dir / name)
            frame_names.append(name)

        update_manifest(pack_dir, frame_names)
        print(f"{pack_name}: menubar.png + {len(frame_names)} hop frames")


if __name__ == "__main__":
    main()
