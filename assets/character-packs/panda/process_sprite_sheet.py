#!/usr/bin/env python3
"""
Process the panda sprite sheet: split into panels and remove green screen.
"""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def remove_green_screen(img: Image.Image) -> Image.Image:
    """
    Remove green screen background from an image using HSV color space.

    Args:
        img: PIL Image (will be converted to RGBA)

    Returns:
        Image with green replaced by transparency
    """
    # Convert to RGBA
    img = img.convert("RGBA")
    data = np.array(img, dtype=np.float32)

    # Extract RGB channels (0-255)
    r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]

    # Convert to HSV-like detection
    # Green has high G relative to R and B
    # We want to catch all shades of green including the border lines

    # Calculate "greenness" - how much more green than other channels
    max_rb = np.maximum(r, b)
    greenness = g - max_rb

    # Also check for the specific bright green (#00FF00 style)
    is_bright_green = (g > 100) & (r < 150) & (b < 150) & (greenness > 20)

    # Check for darker green tones (the lines/borders)
    is_dark_green = (g > 80) & (g > r) & (g > b) & (greenness > 10)

    # Combine masks
    green_mask = is_bright_green | is_dark_green

    # Convert back to uint8
    result = data.astype(np.uint8)

    # Make green pixels transparent
    result[green_mask] = [0, 0, 0, 0]

    # Also remove near-white pixels that might be artifacts at edges
    # (anti-aliasing with green can create light pixels)
    white_mask = (r > 240) & (g > 240) & (b > 240)
    # Don't remove white pixels that are part of the panda

    return Image.fromarray(result)


def remove_green_better(img: Image.Image) -> Image.Image:
    """
    Better green screen removal using color distance.
    """
    img = img.convert("RGBA")
    data = np.array(img, dtype=np.float32)

    r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]

    # Detect bright green background
    is_bright_green = (g > 100) & (g > r + 30) & (g > b + 30)

    # Detect darker green/teal lines (the borders)
    # These have g > r and g > b but are darker overall
    is_dark_green = (g > 50) & (g > r) & (g > b) & (r < 100) & (b < 100)

    # Detect grayish-green (anti-aliasing artifacts)
    is_gray_green = (g > r) & (g > b) & (g - r > 5) & (g - b > 5) & (r < 180) & (b < 180)

    # Combine all green masks
    is_green = is_bright_green | is_dark_green | is_gray_green

    # Convert back to uint8
    result = data.astype(np.uint8)
    result[is_green] = [0, 0, 0, 0]

    return Image.fromarray(result)


def clean_edges(img: Image.Image, iterations: int = 2) -> Image.Image:
    """
    Clean up edges by removing semi-transparent pixels near fully transparent ones.
    This helps remove green fringing.
    """
    data = np.array(img)

    for _ in range(iterations):
        # Find pixels that are adjacent to transparent pixels
        alpha = data[:, :, 3]

        # Shift in all 4 directions to find neighbors
        has_transparent_neighbor = np.zeros_like(alpha, dtype=bool)

        # Check all 8 neighbors
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                shifted = np.roll(np.roll(alpha, dy, axis=0), dx, axis=1)
                has_transparent_neighbor |= shifted == 0

        # Remove pixels that have transparent neighbors AND have some green tint
        r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]
        has_green_tint = (g > r) & (g > b)

        # Make these edge pixels with green tint transparent
        edge_green_mask = has_transparent_neighbor & has_green_tint & (alpha > 0)
        data[edge_green_mask, 3] = 0

    return Image.fromarray(data)


def split_sprite_sheet(sprite_path: str, output_dir: str):
    """
    Split a vertical sprite sheet into individual images.
    """
    # Load sprite sheet
    img = Image.open(sprite_path)
    width, height = img.size

    print(f"Sprite sheet size: {width}x{height}")

    # The sprite sheet has 4 panels stacked vertically
    # Each panel is separated by a thin line, so we need to account for that
    num_panels = 4
    panel_height = height // num_panels

    # State mapping for panels (top to bottom)
    states = [
        ("idle", "Sleeping panda"),
        ("recording", "Writing panda"),
        ("processing", "Confused panda"),
        ("error", "Dizzy panda"),
    ]

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for i, (state_name, description) in enumerate(states):
        # Calculate crop box with margins to avoid border lines
        margin_y = 5  # Pixels to skip at top/bottom
        margin_x = 5  # Pixels to skip at left/right
        top = i * panel_height + margin_y
        bottom = (i + 1) * panel_height - margin_y

        # Crop the panel (also trim edges horizontally)
        panel = img.crop((margin_x, top, width - margin_x, bottom))

        # Remove green screen
        panel_transparent = remove_green_better(panel)

        # Clean up edges (remove green fringing)
        panel_clean = clean_edges(panel_transparent, iterations=3)

        # Trim transparent edges to get just the panda
        bbox = panel_clean.getbbox()
        if bbox:
            panel_trimmed = panel_clean.crop(bbox)
        else:
            panel_trimmed = panel_clean

        # Create a square canvas - NO padding, panda fills the entire space
        max_dim = max(panel_trimmed.size)
        canvas = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))

        # Center the panda on the square canvas
        x_offset = (max_dim - panel_trimmed.width) // 2
        y_offset = (max_dim - panel_trimmed.height) // 2
        canvas.paste(panel_trimmed, (x_offset, y_offset), panel_trimmed)

        # Resize to 512x512 - the panda will fill this completely
        final = canvas.resize((512, 512), Image.LANCZOS)

        # Save
        output_file = output_path / f"{state_name}.png"
        final.save(output_file, "PNG")
        print(f"Created {output_file} - {description}")

    # For success state, reuse the writing panda
    recording_img = Image.open(output_path / "recording.png")
    recording_img.save(output_path / "success.png", "PNG")
    print(f"Created {output_path / 'success.png'} - Reused writing panda for success")

    print(f"\nDone! Created {len(states) + 1} panda icons in {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split a panda sprite sheet into icons.")
    parser.add_argument(
        "sprite_sheet",
        help="Path to the sprite sheet image.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent),
        help="Output directory (default: script directory).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sprite_path = Path(args.sprite_sheet)
    if not sprite_path.exists():
        raise SystemExit(f"Sprite sheet not found: {sprite_path}")

    split_sprite_sheet(str(sprite_path), args.output_dir)
