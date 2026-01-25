#!/usr/bin/env python3
"""
WhisperHUD Asset Generator

Generates dithered graphics, app icons, and social media assets
using a retro lo-fi aesthetic with Floyd-Steinberg dithering.

Color Palette:
- #0D1117 (Dark background)
- #00D4FF (Cyan - primary)
- #BD00FF (Purple/Magenta - accent)
- #FFFFFF (White)

Usage:
    python generate_assets.py [--all | --icons | --dithered | --social]

Requirements:
    pip install Pillow numpy
"""

import argparse
import math
import subprocess
import sys
from pathlib import Path
from typing import Tuple, List

try:
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np
except ImportError:
    print("Required: pip install Pillow numpy")
    sys.exit(1)


# ============================================================================
# COLOR PALETTE
# ============================================================================

class Colors:
    """Official WhisperHUD color palette."""

    # Primary colors (hex and RGB tuples)
    DARK_BG = "#0D1117"
    DARK_BG_RGB = (13, 17, 23)

    CYAN = "#00D4FF"
    CYAN_RGB = (0, 212, 255)

    PURPLE = "#BD00FF"
    PURPLE_RGB = (189, 0, 255)

    WHITE = "#FFFFFF"
    WHITE_RGB = (255, 255, 255)

    # Additional accent colors
    MID_PURPLE = "#7B61FF"
    MID_PURPLE_RGB = (123, 97, 255)

    SUCCESS_GREEN = "#3FB950"
    SUCCESS_GREEN_RGB = (63, 185, 80)

    RECORDING_RED = "#F85149"
    RECORDING_RED_RGB = (248, 81, 73)

    DIM_GRAY = "#8B949E"
    DIM_GRAY_RGB = (139, 148, 158)

    # 4-color dithering palette
    DITHER_PALETTE = [
        DARK_BG_RGB,
        CYAN_RGB,
        PURPLE_RGB,
        WHITE_RGB,
    ]


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def ensure_dirs():
    """Create output directories if they don't exist."""
    base = Path(__file__).parent
    dirs = [
        base / "dithered",
        base / "icons" / "icon.iconset",
        base / "social",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return base


def lerp_color(c1: Tuple[int, int, int], c2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    """Linear interpolation between two colors.

    Args:
        c1: Start color as (R, G, B) tuple
        c2: End color as (R, G, B) tuple
        t: Interpolation factor (0.0 = c1, 1.0 = c2)

    Returns:
        Interpolated color as (R, G, B) tuple
    """
    t = max(0.0, min(1.0, t))  # Clamp t to [0, 1]
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def create_gradient(width: int, height: int,
                   c1: Tuple[int, int, int],
                   c2: Tuple[int, int, int],
                   direction: str = "diagonal") -> Image.Image:
    """Create a gradient image."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()

    for y in range(height):
        for x in range(width):
            if direction == "horizontal":
                t = x / (width - 1) if width > 1 else 0
            elif direction == "vertical":
                t = y / (height - 1) if height > 1 else 0
            elif direction == "diagonal":
                t = (x / (width - 1) + y / (height - 1)) / 2 if width > 1 and height > 1 else 0
            else:
                t = 0

            pixels[x, y] = lerp_color(c1, c2, t)

    return img


def floyd_steinberg_dither(img: Image.Image, palette: List[Tuple[int, int, int]]) -> Image.Image:
    """Apply Floyd-Steinberg dithering with a custom palette."""
    img = img.convert("RGB")
    pixels = np.array(img, dtype=np.float32)
    height, width = pixels.shape[:2]

    palette_array = np.array(palette, dtype=np.float32)

    for y in range(height):
        for x in range(width):
            old_pixel = pixels[y, x].copy()

            # Find closest color in palette
            distances = np.sum((palette_array - old_pixel) ** 2, axis=1)
            closest_idx = np.argmin(distances)
            new_pixel = palette_array[closest_idx]

            pixels[y, x] = new_pixel

            # Calculate error
            error = old_pixel - new_pixel

            # Distribute error to neighbors (Floyd-Steinberg pattern)
            if x + 1 < width:
                pixels[y, x + 1] += error * 7 / 16
            if y + 1 < height:
                if x > 0:
                    pixels[y + 1, x - 1] += error * 3 / 16
                pixels[y + 1, x] += error * 5 / 16
                if x + 1 < width:
                    pixels[y + 1, x + 1] += error * 1 / 16

    # Clip and convert back
    pixels = np.clip(pixels, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels)


def draw_microphone(draw: ImageDraw.Draw,
                   center_x: int, center_y: int,
                   size: int,
                   color: Tuple[int, int, int],
                   outline_color: Tuple[int, int, int] = None):
    """Draw a stylized microphone icon."""
    # Scale factors
    head_radius = int(size * 0.35)
    body_height = int(size * 0.3)
    body_width = int(size * 0.15)
    stand_height = int(size * 0.15)
    base_width = int(size * 0.25)

    # Microphone head (oval)
    head_top = center_y - int(size * 0.45)
    head_bottom = head_top + head_radius * 2
    draw.ellipse([
        center_x - head_radius, head_top,
        center_x + head_radius, head_bottom
    ], fill=color, outline=outline_color)

    # Microphone body
    body_top = head_bottom - int(head_radius * 0.3)
    body_bottom = body_top + body_height
    draw.rectangle([
        center_x - body_width, body_top,
        center_x + body_width, body_bottom
    ], fill=color, outline=outline_color)

    # Stand (vertical line)
    stand_top = body_bottom
    stand_bottom = stand_top + stand_height
    stand_width = max(2, int(size * 0.04))
    draw.rectangle([
        center_x - stand_width // 2, stand_top,
        center_x + stand_width // 2, stand_bottom
    ], fill=color)

    # Base (horizontal line)
    base_y = stand_bottom
    base_height = max(2, int(size * 0.04))
    draw.rectangle([
        center_x - base_width, base_y,
        center_x + base_width, base_y + base_height
    ], fill=color)


def draw_sound_waves(draw: ImageDraw.Draw,
                    center_x: int, center_y: int,
                    size: int,
                    color: Tuple[int, int, int],
                    num_waves: int = 3):
    """Draw sound wave arcs emanating from center."""
    for i in range(num_waves):
        radius = int(size * (0.4 + i * 0.15))
        line_width = max(1, int(size * 0.03))

        # Draw arc on right side
        bbox = [
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius
        ]
        draw.arc(bbox, start=-45, end=45, fill=color, width=line_width)


# ============================================================================
# HUD ELEMENTS (New for HUD Visor design)
# ============================================================================

def draw_hud_corner_brackets(draw: ImageDraw.Draw,
                             size: int,
                             color: Tuple[int, int, int],
                             opacity: float = 0.7):
    """Draw HUD-style corner brackets."""
    margin = int(size * 0.08)
    bracket_len = int(size * 0.1)
    line_width = max(1, int(size * 0.008))

    # Adjust color for opacity (blend with transparent)
    bracket_color = tuple(int(c * opacity) for c in color)

    # Top-left bracket
    draw.line([(margin, margin + bracket_len), (margin, margin), (margin + bracket_len, margin)],
              fill=bracket_color, width=line_width)

    # Top-right bracket
    draw.line([(size - margin - bracket_len, margin), (size - margin, margin), (size - margin, margin + bracket_len)],
              fill=bracket_color, width=line_width)

    # Bottom-left bracket
    draw.line([(margin, size - margin - bracket_len), (margin, size - margin), (margin + bracket_len, size - margin)],
              fill=bracket_color, width=line_width)

    # Bottom-right bracket
    draw.line([(size - margin - bracket_len, size - margin), (size - margin, size - margin), (size - margin, size - margin - bracket_len)],
              fill=bracket_color, width=line_width)


def draw_hud_scan_lines(draw: ImageDraw.Draw,
                        size: int,
                        color: Tuple[int, int, int],
                        opacity: float = 0.15,
                        num_lines: int = 3):
    """Draw subtle horizontal scan lines."""
    line_width = max(1, int(size * 0.002))
    scan_color = tuple(int(c * opacity) for c in color)

    for i in range(1, num_lines + 1):
        y = int(size * i / (num_lines + 1))
        draw.line([(0, y), (size, y)], fill=scan_color, width=line_width)


def draw_hud_targeting_reticle(draw: ImageDraw.Draw,
                               center_x: int, center_y: int,
                               radius: int,
                               color: Tuple[int, int, int],
                               size: int):
    """Draw targeting reticle circle with crosshair marks."""
    line_width = max(1, int(size * 0.006))
    mark_len = int(size * 0.04)

    # Dashed circle (main reticle)
    # PIL doesn't support dashed lines natively, so we draw segments
    num_segments = 36
    for i in range(0, num_segments, 2):  # Skip every other to create dash effect
        start_angle = i * 360 / num_segments
        end_angle = (i + 1) * 360 / num_segments
        bbox = [center_x - radius, center_y - radius, center_x + radius, center_y + radius]
        reticle_color = tuple(int(c * 0.5) for c in color)
        draw.arc(bbox, start=start_angle, end=end_angle, fill=reticle_color, width=line_width)

    # Outer ring (fainter)
    outer_radius = int(radius * 1.18)
    outer_color = tuple(int(c * 0.3) for c in color)
    outer_width = max(1, int(size * 0.003))
    draw.ellipse([center_x - outer_radius, center_y - outer_radius,
                  center_x + outer_radius, center_y + outer_radius],
                 outline=outer_color, width=outer_width)

    # Crosshair marks (outside the circle)
    mark_color = tuple(int(c * 0.6) for c in color)
    mark_width = max(1, int(size * 0.004))
    gap = int(radius * 0.15)

    # Top mark
    draw.line([(center_x, center_y - outer_radius - gap - mark_len),
               (center_x, center_y - outer_radius - gap)],
              fill=mark_color, width=mark_width)
    # Bottom mark
    draw.line([(center_x, center_y + outer_radius + gap),
               (center_x, center_y + outer_radius + gap + mark_len)],
              fill=mark_color, width=mark_width)
    # Left mark
    draw.line([(center_x - outer_radius - gap - mark_len, center_y),
               (center_x - outer_radius - gap, center_y)],
              fill=mark_color, width=mark_width)
    # Right mark
    draw.line([(center_x + outer_radius + gap, center_y),
               (center_x + outer_radius + gap + mark_len, center_y)],
              fill=mark_color, width=mark_width)


def draw_hud_status_indicators(draw: ImageDraw.Draw,
                               size: int,
                               color: Tuple[int, int, int],
                               opacity: float = 0.4):
    """Draw small HUD data readout decorations."""
    indicator_color = tuple(int(c * opacity) for c in color)
    bar_height = max(1, int(size * 0.006))
    margin = int(size * 0.1)

    # Top-left indicators
    draw.rectangle([margin, margin + int(size * 0.04),
                   margin + int(size * 0.06), margin + int(size * 0.04) + bar_height],
                  fill=indicator_color)
    draw.rectangle([margin, margin + int(size * 0.055),
                   margin + int(size * 0.04), margin + int(size * 0.055) + bar_height],
                  fill=indicator_color)

    # Bottom-right indicators
    draw.rectangle([size - margin - int(size * 0.06), size - margin - int(size * 0.04),
                   size - margin, size - margin - int(size * 0.04) + bar_height],
                  fill=indicator_color)
    draw.rectangle([size - margin - int(size * 0.04), size - margin - int(size * 0.025),
                   size - margin, size - margin - int(size * 0.025) + bar_height],
                  fill=indicator_color)


# ============================================================================
# ICON GENERATION
# ============================================================================

def draw_geometric_microphone(draw: ImageDraw.Draw,
                              center_x: int, center_y: int,
                              size: int,
                              color: Tuple[int, int, int]):
    """Draw a more geometric/angular microphone for HUD aesthetic."""
    # Scale factors (more angular proportions)
    head_width = int(size * 0.30)
    head_height = int(size * 0.32)
    head_radius = int(size * 0.10)  # Corner radius for rounded rect
    body_height = int(size * 0.12)
    body_width = int(size * 0.20)
    stand_height = int(size * 0.10)
    stand_width = max(2, int(size * 0.04))
    base_width = int(size * 0.26)
    base_height = max(2, int(size * 0.03))

    # Microphone head (rounded rectangle - more angular than oval)
    head_top = center_y - int(size * 0.30)
    head_left = center_x - head_width // 2
    draw.rounded_rectangle([
        head_left, head_top,
        head_left + head_width, head_top + head_height
    ], radius=head_radius, fill=color)

    # Microphone body (rectangle connecting head to stand)
    body_top = head_top + head_height - int(head_radius * 0.3)
    body_left = center_x - body_width // 2
    draw.rectangle([
        body_left, body_top,
        body_left + body_width, body_top + body_height
    ], fill=color)

    # Stand (vertical line)
    stand_top = body_top + body_height
    stand_left = center_x - stand_width // 2
    draw.rectangle([
        stand_left, stand_top,
        stand_left + stand_width, stand_top + stand_height
    ], fill=color)

    # Base (horizontal bar with slight taper)
    base_y = stand_top + stand_height
    base_left = center_x - base_width // 2
    # Draw as polygon for angular look
    draw.polygon([
        (base_left, base_y),
        (base_left + base_width, base_y),
        (base_left + base_width - int(size * 0.02), base_y + base_height),
        (base_left + int(size * 0.02), base_y + base_height)
    ], fill=color)


def generate_app_icon(size: int, output_path: Path):
    """Generate a macOS app icon at the specified size with HUD visor design."""
    # Create base with gradient
    img = create_gradient(size, size, Colors.CYAN_RGB, Colors.PURPLE_RGB, "diagonal")

    # Apply slight blur for smoother gradient
    if size >= 64:
        img = img.filter(ImageFilter.GaussianBlur(radius=size * 0.02))

    draw = ImageDraw.Draw(img)

    # === HUD Elements (background layer) ===
    # Only draw HUD elements on larger sizes for clarity
    if size >= 32:
        # Scan lines (very subtle)
        draw_hud_scan_lines(draw, size, Colors.WHITE_RGB, opacity=0.15, num_lines=3)

    if size >= 64:
        # Corner brackets
        draw_hud_corner_brackets(draw, size, Colors.WHITE_RGB, opacity=0.7)

    # === Microphone (main element) ===
    mic_size = int(size * 0.6)
    center = size // 2
    mic_center_y = center - int(size * 0.05)  # Shift up slightly for balance

    # Shadow (offset and semi-transparent)
    if size >= 32:
        shadow_offset = max(1, size // 64)
        shadow_color = (40, 20, 60)  # Dark purple-ish shadow
        draw_geometric_microphone(draw, center + shadow_offset, mic_center_y + shadow_offset,
                                  mic_size, shadow_color)

    # Main microphone (geometric style)
    draw_geometric_microphone(draw, center, mic_center_y, mic_size, Colors.WHITE_RGB)

    # === Targeting Reticle (around mic head) ===
    if size >= 64:
        reticle_radius = int(size * 0.22)
        reticle_center_y = mic_center_y - int(size * 0.08)  # Around mic head
        draw_hud_targeting_reticle(draw, center, reticle_center_y, reticle_radius,
                                   Colors.WHITE_RGB, size)

    # === Sound waves ===
    wave_offset = int(size * 0.15)
    wave_center_y = mic_center_y - int(size * 0.08)
    draw_sound_waves(draw, center + wave_offset, wave_center_y,
                    mic_size, Colors.WHITE_RGB, num_waves=3)

    # === HUD Status Indicators ===
    if size >= 128:
        draw_hud_status_indicators(draw, size, Colors.WHITE_RGB, opacity=0.4)

    # Apply REDUCED dithering for cleaner appearance
    # Only apply on very large sizes and with reduced intensity
    if size >= 512:
        img = floyd_steinberg_dither(img, Colors.DITHER_PALETTE)
    # For medium sizes, no dithering for cleaner look at small display sizes

    # Save
    img.save(output_path, "PNG")
    print(f"  Generated: {output_path.name} ({size}x{size})")


def generate_all_icons(base_path: Path):
    """Generate all macOS icon sizes."""
    print("\nGenerating macOS app icons...")

    iconset_path = base_path / "icons" / "icon.iconset"

    # Standard macOS icon sizes
    sizes = [16, 32, 64, 128, 256, 512, 1024]

    for size in sizes:
        # Standard resolution
        filename = f"icon_{size}x{size}.png"
        generate_app_icon(size, iconset_path / filename)

        # @2x retina (for sizes that need it)
        if size <= 512:
            filename_2x = f"icon_{size}x{size}@2x.png"
            generate_app_icon(size * 2, iconset_path / filename_2x)

    print("  Done!")


def compile_icns(base_path: Path):
    """Compile iconset to .icns file using iconutil."""
    print("\nCompiling .icns file...")

    iconset_path = base_path / "icons" / "icon.iconset"
    icns_path = base_path / "icons" / "AppIcon.icns"

    try:
        subprocess.run([
            "iconutil", "-c", "icns",
            str(iconset_path),
            "-o", str(icns_path)
        ], check=True)
        print(f"  Generated: AppIcon.icns")
    except subprocess.CalledProcessError as e:
        print(f"  Error: iconutil failed - {e}")
    except FileNotFoundError:
        print("  Warning: iconutil not found (only available on macOS)")


# ============================================================================
# DITHERED GRAPHICS
# ============================================================================

def generate_dithered_mic(size: int, output_path: Path):
    """Generate a dithered microphone icon."""
    # Create gradient background
    img = create_gradient(size, size, Colors.DARK_BG_RGB, Colors.DARK_BG_RGB)
    draw = ImageDraw.Draw(img)

    # Draw microphone with cyan-to-purple gradient effect
    # We'll draw it in layers
    mic_size = int(size * 0.7)
    center = size // 2

    # Create a mask for the microphone
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    draw_microphone(mask_draw, center, center, mic_size, 255)

    # Create gradient for the microphone
    mic_gradient = create_gradient(size, size, Colors.CYAN_RGB, Colors.PURPLE_RGB, "vertical")

    # Composite
    img.paste(mic_gradient, mask=mask)

    # Add sound waves
    draw = ImageDraw.Draw(img)
    wave_color = lerp_color(Colors.CYAN_RGB, Colors.PURPLE_RGB, 0.5)
    draw_sound_waves(draw, center + int(size * 0.15), center - int(size * 0.05),
                    mic_size, wave_color, num_waves=2)

    # Apply dithering
    img = floyd_steinberg_dither(img, Colors.DITHER_PALETTE)

    img.save(output_path, "PNG")
    print(f"  Generated: {output_path.name} ({size}x{size})")


def generate_waveform(width: int, height: int, output_path: Path):
    """Generate a dithered waveform visualization."""
    img = Image.new("RGB", (width, height), Colors.DARK_BG_RGB)
    draw = ImageDraw.Draw(img)

    # Draw waveform bars
    num_bars = 32
    bar_width = width // (num_bars * 2)
    bar_spacing = width // num_bars

    for i in range(num_bars):
        # Create varying heights for waveform effect
        t = i / max(1, num_bars - 1)  # Avoid division by zero
        phase = math.sin(t * math.pi * 2 + 0.5) * 0.5 + 0.5
        bar_height = int(height * 0.2 + height * 0.6 * phase)

        x = i * bar_spacing + bar_spacing // 2
        y_top = (height - bar_height) // 2
        y_bottom = y_top + bar_height

        # Gradient color per bar
        color = lerp_color(Colors.CYAN_RGB, Colors.PURPLE_RGB, t)

        draw.rectangle([x, y_top, x + bar_width, y_bottom], fill=color)

    # Apply dithering
    img = floyd_steinberg_dither(img, Colors.DITHER_PALETTE)

    img.save(output_path, "PNG")
    print(f"  Generated: {output_path.name} ({width}x{height})")


def generate_logo_banner(width: int, height: int, output_path: Path):
    """Generate a dithered logo banner for README."""
    img = Image.new("RGB", (width, height), Colors.DARK_BG_RGB)
    draw = ImageDraw.Draw(img)

    # Add subtle gradient background
    for y in range(height):
        t = y / height
        alpha = int(30 * (1 - t))  # Subtle top highlight
        if alpha > 0:
            draw.line([(0, y), (width, y)],
                     fill=lerp_color(Colors.DARK_BG_RGB, Colors.CYAN_RGB, alpha / 255))

    # Draw microphone on left side
    mic_size = int(height * 0.6)
    mic_x = int(width * 0.12)
    mic_y = height // 2

    # Microphone with gradient
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    draw_microphone(mask_draw, mic_x, mic_y, mic_size, 255)

    mic_gradient = create_gradient(width, height, Colors.CYAN_RGB, Colors.PURPLE_RGB, "diagonal")
    img.paste(mic_gradient, mask=mask)

    # Draw sound waves
    draw = ImageDraw.Draw(img)
    draw_sound_waves(draw, mic_x + int(mic_size * 0.3), mic_y - int(mic_size * 0.1),
                    mic_size, Colors.CYAN_RGB, num_waves=3)

    # Add text placeholder area (will be overlaid with actual text in final use)
    text_x = int(width * 0.25)
    text_y = int(height * 0.35)

    # Draw "WHISPERHUD" text using rectangles as a stylized font
    # This creates a blocky, retro look
    letter_width = int(width * 0.045)
    letter_height = int(height * 0.25)
    letter_spacing = int(letter_width * 1.3)

    text = "WHISPERHUD"
    text_len = len(text)
    for i, char in enumerate(text):
        x = text_x + i * letter_spacing
        t = i / max(1, text_len - 1)  # Avoid division by zero, spread gradient across text
        color = lerp_color(Colors.CYAN_RGB, Colors.PURPLE_RGB, t)

        # Simple blocky letter representation
        draw.rectangle([x, text_y, x + letter_width, text_y + letter_height], fill=color)

    # Add tagline area
    tagline_y = text_y + letter_height + int(height * 0.1)
    tagline_text = "voice -> text, invisibly"

    # Draw small blocks for tagline
    small_block = int(width * 0.008)
    for i in range(len(tagline_text)):
        if tagline_text[i] != ' ':
            x = text_x + i * int(small_block * 1.5)
            draw.rectangle([x, tagline_y, x + small_block, tagline_y + small_block],
                          fill=Colors.DIM_GRAY_RGB)

    # Apply dithering
    img = floyd_steinberg_dither(img, Colors.DITHER_PALETTE)

    img.save(output_path, "PNG")
    print(f"  Generated: {output_path.name} ({width}x{height})")


def generate_all_dithered(base_path: Path):
    """Generate all dithered graphics."""
    print("\nGenerating dithered graphics...")

    dithered_path = base_path / "dithered"

    # Microphone icons at various sizes
    for size in [16, 32, 64, 128]:
        generate_dithered_mic(size, dithered_path / f"mic_{size}.png")

    # Waveform
    generate_waveform(200, 50, dithered_path / "waveform.png")
    generate_waveform(400, 100, dithered_path / "waveform_large.png")

    # Logo banner
    generate_logo_banner(400, 200, dithered_path / "logo_banner.png")

    print("  Done!")


# ============================================================================
# SOCIAL MEDIA GRAPHICS
# ============================================================================

def generate_readme_banner(width: int, height: int, output_path: Path):
    """Generate a README header banner."""
    img = Image.new("RGB", (width, height), Colors.DARK_BG_RGB)
    draw = ImageDraw.Draw(img)

    # Create gradient sweep across bottom
    gradient_height = height // 3
    for y in range(gradient_height):
        t = y / gradient_height
        x_offset = int(width * t * 0.3)
        color = lerp_color(Colors.CYAN_RGB, Colors.PURPLE_RGB, 0.3 + t * 0.4)
        # Fade the color based on height
        alpha = int((1 - t) * 80)
        faded_color = lerp_color(Colors.DARK_BG_RGB, color, alpha / 255)
        draw.line([(x_offset, height - y - 1), (width, height - y - 1)], fill=faded_color)

    # Draw large microphone
    mic_size = int(height * 0.7)
    mic_x = int(width * 0.15)
    mic_y = int(height * 0.5)

    # Create microphone with gradient
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    draw_microphone(mask_draw, mic_x, mic_y, mic_size, 255)

    mic_gradient = create_gradient(width, height, Colors.CYAN_RGB, Colors.PURPLE_RGB, "diagonal")
    img.paste(mic_gradient, mask=mask)

    # Redraw for additional elements
    draw = ImageDraw.Draw(img)

    # Sound waves
    draw_sound_waves(draw, mic_x + int(mic_size * 0.25), mic_y - int(mic_size * 0.05),
                    int(mic_size * 0.8), Colors.WHITE_RGB, num_waves=3)

    # Draw waveform across middle
    waveform_y = int(height * 0.65)
    num_bars = 60
    bar_width = max(2, width // (num_bars * 3))

    for i in range(num_bars):
        t = i / max(1, num_bars - 1)  # Avoid division by zero
        x = int(width * 0.3) + int(width * 0.65 * t)

        # Waveform pattern
        phase = math.sin(t * math.pi * 4) * 0.5 + 0.5
        bar_height = int(height * 0.05 + height * 0.15 * phase)

        y_top = waveform_y - bar_height // 2
        y_bottom = waveform_y + bar_height // 2

        color = lerp_color(Colors.CYAN_RGB, Colors.PURPLE_RGB, t)
        draw.rectangle([x, y_top, x + bar_width, y_bottom], fill=color)

    # Add title text area (blocky style)
    title_x = int(width * 0.32)
    title_y = int(height * 0.25)
    block_size = int(height * 0.08)

    # "WHISPERHUD" in blocks (10 characters)
    title_text = "WHISPERHUD"
    title_len = len(title_text)
    for i in range(title_len):
        x = title_x + i * int(block_size * 1.4)
        t = i / max(1, title_len - 1)  # Spread gradient across text
        color = lerp_color(Colors.CYAN_RGB, Colors.PURPLE_RGB, t)
        draw.rectangle([x, title_y, x + block_size, title_y + block_size], fill=color)

    # Tagline
    tagline_y = title_y + int(block_size * 1.5)
    small_block = int(height * 0.02)
    for i in range(20):
        x = title_x + i * int(small_block * 2)
        draw.rectangle([x, tagline_y, x + small_block, tagline_y + small_block],
                      fill=Colors.DIM_GRAY_RGB)

    # Apply dithering
    img = floyd_steinberg_dither(img, Colors.DITHER_PALETTE)

    img.save(output_path, "PNG")
    print(f"  Generated: {output_path.name} ({width}x{height})")


def generate_og_image(output_path: Path):
    """Generate Open Graph image for social sharing (1200x630)."""
    generate_readme_banner(1200, 630, output_path)


def generate_twitter_card(output_path: Path):
    """Generate Twitter card image (1200x600)."""
    generate_readme_banner(1200, 600, output_path)


def generate_all_social(base_path: Path):
    """Generate all social media graphics."""
    print("\nGenerating social media graphics...")

    social_path = base_path / "social"

    # README banner (wider for GitHub)
    generate_readme_banner(800, 200, social_path / "readme_banner.png")
    generate_readme_banner(1200, 300, social_path / "readme_banner_large.png")

    # Open Graph image
    generate_og_image(social_path / "og_image.png")

    # Twitter card
    generate_twitter_card(social_path / "twitter_card.png")

    print("  Done!")


# ============================================================================
# SVG ICON (Vector source)
# ============================================================================

def generate_svg_icon(output_path: Path):
    """Generate an SVG version of the icon with HUD visor design."""
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- Main gradient -->
    <linearGradient id="mainGradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#00D4FF;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#BD00FF;stop-opacity:1" />
    </linearGradient>

    <!-- Subtle glow effect -->
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="8" result="coloredBlur"/>
      <feMerge>
        <feMergeNode in="coloredBlur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <!-- Background -->
  <rect width="1024" height="1024" fill="url(#mainGradient)"/>

  <!-- HUD Scan Lines (subtle horizontal lines) -->
  <g opacity="0.15">
    <line x1="0" y1="256" x2="1024" y2="256" stroke="white" stroke-width="2"/>
    <line x1="0" y1="512" x2="1024" y2="512" stroke="white" stroke-width="2"/>
    <line x1="0" y1="768" x2="1024" y2="768" stroke="white" stroke-width="2"/>
  </g>

  <!-- HUD Corner Brackets -->
  <g stroke="white" stroke-width="8" fill="none" opacity="0.7">
    <!-- Top-left bracket -->
    <path d="M 80 180 L 80 80 L 180 80"/>
    <!-- Top-right bracket -->
    <path d="M 844 80 L 944 80 L 944 180"/>
    <!-- Bottom-left bracket -->
    <path d="M 80 844 L 80 944 L 180 944"/>
    <!-- Bottom-right bracket -->
    <path d="M 844 944 L 944 944 L 944 844"/>
  </g>

  <!-- Targeting Reticle (circle around mic head) -->
  <circle cx="512" cy="380" r="220" stroke="white" stroke-width="6" fill="none" opacity="0.5" stroke-dasharray="20 10"/>

  <!-- Inner reticle ring -->
  <circle cx="512" cy="380" r="260" stroke="white" stroke-width="3" fill="none" opacity="0.3"/>

  <!-- Reticle crosshair marks -->
  <g stroke="white" stroke-width="4" opacity="0.6">
    <!-- Top mark -->
    <line x1="512" y1="100" x2="512" y2="140"/>
    <!-- Bottom mark (above mic body) -->
    <line x1="512" y1="620" x2="512" y2="660"/>
    <!-- Left mark -->
    <line x1="232" y1="380" x2="272" y2="380"/>
    <!-- Right mark -->
    <line x1="752" y1="380" x2="792" y2="380"/>
  </g>

  <!-- Geometric Microphone (more angular/modern) -->
  <g filter="url(#glow)">
    <!-- Mic head (rounded rectangle instead of oval for more angular look) -->
    <rect x="362" y="200" width="300" height="320" rx="100" ry="100" fill="white"/>

    <!-- Microphone body (tapered) -->
    <path d="M 412 480 L 412 600 L 612 600 L 612 480 Z" fill="white"/>

    <!-- Stand (geometric) -->
    <rect x="492" y="600" width="40" height="100" fill="white"/>

    <!-- Base (angular) -->
    <polygon points="380,700 644,700 620,730 404,730" fill="white"/>
  </g>

  <!-- Sound waves (right side, geometric style) -->
  <g stroke="white" stroke-width="10" fill="none" stroke-linecap="round" opacity="0.9">
    <!-- Inner wave -->
    <path d="M 680 300 Q 720 380 680 460"/>
    <!-- Middle wave -->
    <path d="M 730 250 Q 790 380 730 510"/>
    <!-- Outer wave -->
    <path d="M 780 200 Q 860 380 780 560"/>
  </g>

  <!-- HUD data readout decoration (small text-like elements) -->
  <g opacity="0.4" fill="white">
    <!-- Top status indicator -->
    <rect x="100" y="120" width="60" height="6"/>
    <rect x="100" y="134" width="40" height="6"/>

    <!-- Bottom status indicator -->
    <rect x="864" y="884" width="60" height="6"/>
    <rect x="884" y="898" width="40" height="6"/>
  </g>
</svg>
'''

    with open(output_path, 'w') as f:
        f.write(svg_content)

    print(f"  Generated: {output_path.name}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate WhisperHUD visual assets")
    parser.add_argument("--all", action="store_true", help="Generate all assets")
    parser.add_argument("--icons", action="store_true", help="Generate app icons")
    parser.add_argument("--dithered", action="store_true", help="Generate dithered graphics")
    parser.add_argument("--social", action="store_true", help="Generate social media graphics")
    parser.add_argument("--svg", action="store_true", help="Generate SVG icon")

    args = parser.parse_args()

    # If no args, generate all
    if not (args.all or args.icons or args.dithered or args.social or args.svg):
        args.all = True

    print("=" * 60)
    print("  WhisperHUD Asset Generator")
    print("  Retro/Lo-fi aesthetic with cyan→purple gradient")
    print("=" * 60)

    base_path = ensure_dirs()

    if args.all or args.icons:
        generate_all_icons(base_path)
        compile_icns(base_path)

    if args.all or args.svg:
        print("\nGenerating SVG icon...")
        generate_svg_icon(base_path / "icons" / "icon.svg")
        print("  Done!")

    if args.all or args.dithered:
        generate_all_dithered(base_path)

    if args.all or args.social:
        generate_all_social(base_path)

    print("\n" + "=" * 60)
    print("  Asset generation complete!")
    print("=" * 60)
    print("\nGenerated assets in:")
    print(f"  {base_path / 'icons'}")
    print(f"  {base_path / 'dithered'}")
    print(f"  {base_path / 'social'}")


if __name__ == "__main__":
    main()
