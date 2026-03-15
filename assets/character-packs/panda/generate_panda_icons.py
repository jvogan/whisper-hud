#!/usr/bin/env python3
"""
Generate cute panda character icons for WhisperHUD.

Creates SVG-style panda icons for different app states:
- idle: Sleeping panda with Zzz
- recording: Panda writing at desk
- processing: Confused panda with ?
- error: Dizzy panda with stars
- success: Happy panda with sparkles
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
from pathlib import Path


def create_canvas(size: int = 256) -> tuple:
    """Create a transparent canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    return img, draw


def draw_panda_face(draw, cx: int, cy: int, size: int, eye_state: str = "open"):
    """Draw the basic panda face centered at (cx, cy)."""
    # Colors
    white = (255, 255, 255, 255)
    black = (30, 30, 30, 255)
    pink = (255, 180, 180, 255)
    dark_gray = (60, 60, 60, 255)

    # Scale factor
    s = size / 256

    # --- Main face (white circle) ---
    face_r = int(90 * s)
    draw.ellipse(
        [cx - face_r, cy - face_r, cx + face_r, cy + face_r], fill=white, outline=black, width=max(1, int(3 * s))
    )

    # --- Ears (black circles behind face, but we draw them on top edges) ---
    ear_r = int(35 * s)
    ear_offset_x = int(65 * s)
    ear_offset_y = int(55 * s)

    # Left ear
    draw.ellipse(
        [cx - ear_offset_x - ear_r, cy - ear_offset_y - ear_r, cx - ear_offset_x + ear_r, cy - ear_offset_y + ear_r],
        fill=black,
    )
    # Inner ear
    inner_ear_r = int(15 * s)
    draw.ellipse(
        [
            cx - ear_offset_x - inner_ear_r,
            cy - ear_offset_y - inner_ear_r,
            cx - ear_offset_x + inner_ear_r,
            cy - ear_offset_y + inner_ear_r,
        ],
        fill=dark_gray,
    )

    # Right ear
    draw.ellipse(
        [cx + ear_offset_x - ear_r, cy - ear_offset_y - ear_r, cx + ear_offset_x + ear_r, cy - ear_offset_y + ear_r],
        fill=black,
    )
    # Inner ear
    draw.ellipse(
        [
            cx + ear_offset_x - inner_ear_r,
            cy - ear_offset_y - inner_ear_r,
            cx + ear_offset_x + inner_ear_r,
            cy - ear_offset_y + inner_ear_r,
        ],
        fill=dark_gray,
    )

    # --- Eye patches (black ovals) ---
    patch_w = int(35 * s)
    patch_h = int(45 * s)
    patch_offset_x = int(35 * s)
    patch_offset_y = int(10 * s)

    # Left eye patch (tilted slightly)
    draw.ellipse(
        [
            cx - patch_offset_x - patch_w,
            cy - patch_offset_y - patch_h,
            cx - patch_offset_x + patch_w,
            cy - patch_offset_y + patch_h,
        ],
        fill=black,
    )

    # Right eye patch
    draw.ellipse(
        [
            cx + patch_offset_x - patch_w,
            cy - patch_offset_y - patch_h,
            cx + patch_offset_x + patch_w,
            cy - patch_offset_y + patch_h,
        ],
        fill=black,
    )

    # --- Eyes ---
    eye_offset_x = int(35 * s)
    eye_offset_y = int(10 * s)

    if eye_state == "open":
        # White of eyes
        eye_r = int(12 * s)
        draw.ellipse(
            [
                cx - eye_offset_x - eye_r,
                cy - eye_offset_y - eye_r,
                cx - eye_offset_x + eye_r,
                cy - eye_offset_y + eye_r,
            ],
            fill=white,
        )
        draw.ellipse(
            [
                cx + eye_offset_x - eye_r,
                cy - eye_offset_y - eye_r,
                cx + eye_offset_x + eye_r,
                cy - eye_offset_y + eye_r,
            ],
            fill=white,
        )

        # Pupils
        pupil_r = int(6 * s)
        draw.ellipse(
            [
                cx - eye_offset_x - pupil_r,
                cy - eye_offset_y - pupil_r,
                cx - eye_offset_x + pupil_r,
                cy - eye_offset_y + pupil_r,
            ],
            fill=black,
        )
        draw.ellipse(
            [
                cx + eye_offset_x - pupil_r,
                cy - eye_offset_y - pupil_r,
                cx + eye_offset_x + pupil_r,
                cy - eye_offset_y + pupil_r,
            ],
            fill=black,
        )

        # Eye highlights
        highlight_r = int(3 * s)
        highlight_off = int(3 * s)
        draw.ellipse(
            [
                cx - eye_offset_x - highlight_off - highlight_r,
                cy - eye_offset_y - highlight_off - highlight_r,
                cx - eye_offset_x - highlight_off + highlight_r,
                cy - eye_offset_y - highlight_off + highlight_r,
            ],
            fill=white,
        )
        draw.ellipse(
            [
                cx + eye_offset_x - highlight_off - highlight_r,
                cy - eye_offset_y - highlight_off - highlight_r,
                cx + eye_offset_x - highlight_off + highlight_r,
                cy - eye_offset_y - highlight_off + highlight_r,
            ],
            fill=white,
        )

    elif eye_state == "closed" or eye_state == "sleeping":
        # Closed eyes (curved lines)
        line_w = int(3 * s)
        arc_size = int(15 * s)

        # Left eye - arc
        draw.arc(
            [
                cx - eye_offset_x - arc_size,
                cy - eye_offset_y - arc_size,
                cx - eye_offset_x + arc_size,
                cy - eye_offset_y + arc_size,
            ],
            start=0,
            end=180,
            fill=white,
            width=line_w,
        )

        # Right eye - arc
        draw.arc(
            [
                cx + eye_offset_x - arc_size,
                cy - eye_offset_y - arc_size,
                cx + eye_offset_x + arc_size,
                cy - eye_offset_y + arc_size,
            ],
            start=0,
            end=180,
            fill=white,
            width=line_w,
        )

    elif eye_state == "spiral":
        # Dizzy spiral eyes
        spiral_color = white
        eye_r = int(12 * s)
        line_w = int(2 * s)

        # Left spiral
        for i in range(3):
            r = eye_r - i * int(4 * s)
            if r > 0:
                draw.arc(
                    [cx - eye_offset_x - r, cy - eye_offset_y - r, cx - eye_offset_x + r, cy - eye_offset_y + r],
                    start=i * 180,
                    end=i * 180 + 180,
                    fill=spiral_color,
                    width=line_w,
                )

        # Right spiral
        for i in range(3):
            r = eye_r - i * int(4 * s)
            if r > 0:
                draw.arc(
                    [cx + eye_offset_x - r, cy - eye_offset_y - r, cx + eye_offset_x + r, cy - eye_offset_y + r],
                    start=180 + i * 180,
                    end=180 + i * 180 + 180,
                    fill=spiral_color,
                    width=line_w,
                )

    # --- Nose ---
    nose_y = cy + int(25 * s)
    nose_r = int(12 * s)
    draw.ellipse([cx - nose_r, nose_y - nose_r // 2, cx + nose_r, nose_y + nose_r // 2], fill=black)

    # --- Mouth ---
    mouth_y = nose_y + int(15 * s)
    mouth_w = int(20 * s)
    mouth_line = int(2 * s)

    # Simple curved smile
    draw.arc(
        [cx - mouth_w, mouth_y - int(10 * s), cx + mouth_w, mouth_y + int(10 * s)],
        start=0,
        end=180,
        fill=black,
        width=mouth_line,
    )

    # --- Blush (pink cheeks) ---
    blush_r = int(12 * s)
    blush_offset_x = int(55 * s)
    blush_offset_y = int(25 * s)
    blush_color = (255, 200, 200, 150)

    draw.ellipse(
        [
            cx - blush_offset_x - blush_r,
            cy + blush_offset_y - blush_r,
            cx - blush_offset_x + blush_r,
            cy + blush_offset_y + blush_r,
        ],
        fill=blush_color,
    )
    draw.ellipse(
        [
            cx + blush_offset_x - blush_r,
            cy + blush_offset_y - blush_r,
            cx + blush_offset_x + blush_r,
            cy + blush_offset_y + blush_r,
        ],
        fill=blush_color,
    )


def draw_zzz(draw, x: int, y: int, size: int):
    """Draw sleeping Zzz symbols."""
    s = size / 256
    blue = (100, 150, 255, 255)
    line_w = max(2, int(3 * s))

    for i, (dx, dy, scale) in enumerate([(0, 0, 1.0), (25, -20, 0.75), (45, -35, 0.5)]):
        zx = x + int(dx * s)
        zy = y + int(dy * s)
        z_size = int(20 * s * scale)

        # Draw Z shape
        points = [
            (zx - z_size // 2, zy - z_size // 2),
            (zx + z_size // 2, zy - z_size // 2),
            (zx - z_size // 2, zy + z_size // 2),
            (zx + z_size // 2, zy + z_size // 2),
        ]
        draw.line([points[0], points[1]], fill=blue, width=line_w)
        draw.line([points[1], points[2]], fill=blue, width=line_w)
        draw.line([points[2], points[3]], fill=blue, width=line_w)


def draw_question_mark(draw, x: int, y: int, size: int):
    """Draw a confused question mark."""
    s = size / 256
    yellow = (255, 200, 50, 255)
    line_w = max(3, int(5 * s))

    # Question mark curve
    qm_size = int(25 * s)
    draw.arc([x - qm_size, y - qm_size * 2, x + qm_size, y], start=180, end=360, fill=yellow, width=line_w)
    draw.line([(x + qm_size, y - qm_size), (x, y + int(10 * s))], fill=yellow, width=line_w)

    # Dot
    dot_r = int(5 * s)
    dot_y = y + int(25 * s)
    draw.ellipse([x - dot_r, dot_y - dot_r, x + dot_r, dot_y + dot_r], fill=yellow)


def draw_stars(draw, cx: int, cy: int, size: int):
    """Draw dizzy stars around the head."""
    s = size / 256
    yellow = (255, 220, 50, 255)

    def star(x, y, r, points=5):
        """Draw a star at position."""
        angle = -math.pi / 2
        step = math.pi / points
        path = []
        for i in range(points * 2):
            radius = r if i % 2 == 0 else r / 2
            px = x + radius * math.cos(angle)
            py = y + radius * math.sin(angle)
            path.append((px, py))
            angle += step
        draw.polygon(path, fill=yellow)

    # Draw stars around the head
    for angle, dist, star_size in [(30, 90, 15), (90, 100, 12), (150, 90, 10)]:
        rad = math.radians(angle)
        sx = cx + int(dist * s * math.cos(rad - math.pi / 2))
        sy = cy + int(dist * s * math.sin(rad - math.pi / 2)) - int(20 * s)
        star(sx, sy, int(star_size * s))


def draw_sparkles(draw, cx: int, cy: int, size: int):
    """Draw success sparkles."""
    s = size / 256
    gold = (255, 215, 0, 255)

    def sparkle(x, y, r):
        """Draw a 4-point sparkle."""
        points = [
            (x, y - r),
            (x + r // 4, y - r // 4),
            (x + r, y),
            (x + r // 4, y + r // 4),
            (x, y + r),
            (x - r // 4, y + r // 4),
            (x - r, y),
            (x - r // 4, y - r // 4),
        ]
        draw.polygon(points, fill=gold)

    # Draw sparkles around
    for angle, dist, sp_size in [(45, 95, 12), (135, 95, 10), (90, 110, 8)]:
        rad = math.radians(angle)
        sx = cx + int(dist * s * math.cos(rad - math.pi / 2))
        sy = cy + int(dist * s * math.sin(rad - math.pi / 2)) - int(30 * s)
        sparkle(int(sx), int(sy), int(sp_size * s))


def draw_pencil(draw, x: int, y: int, size: int, angle: float = -30):
    """Draw a pencil for the recording state."""
    s = size / 256

    # Pencil colors
    wood = (210, 180, 140, 255)
    yellow = (255, 220, 50, 255)
    gray = (100, 100, 100, 255)
    tip = (30, 30, 30, 255)

    # Pencil dimensions
    length = int(60 * s)
    width = int(12 * s)

    # Create a rotated pencil by using a separate image
    pencil_img = Image.new("RGBA", (int(length * 1.5), int(width * 3)), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(pencil_img)

    px, py = pencil_img.width // 2, pencil_img.height // 2

    # Pencil body (yellow)
    pdraw.rectangle(
        [px - length // 2 + width, py - width // 2, px + length // 2, py + width // 2], fill=yellow, outline=None
    )

    # Pencil tip (wood + graphite)
    tip_points = [
        (px - length // 2 + width, py - width // 2),
        (px - length // 2, py),
        (px - length // 2 + width, py + width // 2),
    ]
    pdraw.polygon(tip_points, fill=wood)

    # Graphite tip
    pdraw.polygon(
        [
            (px - length // 2, py),
            (px - length // 2 + width // 3, py - width // 4),
            (px - length // 2 + width // 3, py + width // 4),
        ],
        fill=tip,
    )

    # Eraser end (gray)
    pdraw.rectangle([px + length // 2 - width // 2, py - width // 2, px + length // 2, py + width // 2], fill=gray)

    # Rotate pencil
    pencil_img = pencil_img.rotate(angle, expand=True, resample=Image.BICUBIC)

    return pencil_img


def create_idle_icon(size: int = 256) -> Image.Image:
    """Create sleeping panda icon."""
    img, draw = create_canvas(size)
    cx, cy = size // 2, size // 2 + size // 10

    draw_panda_face(draw, cx, cy, size, eye_state="sleeping")
    draw_zzz(draw, cx + int(size * 0.3), cy - int(size * 0.25), size)

    return img


def create_recording_icon(size: int = 256) -> Image.Image:
    """Create writing/recording panda icon."""
    img, draw = create_canvas(size)
    cx, cy = size // 2, size // 2 + size // 10

    draw_panda_face(draw, cx, cy, size, eye_state="open")

    # Add pencil
    pencil = draw_pencil(draw, 0, 0, size)
    pencil_x = cx + int(size * 0.15)
    pencil_y = cy + int(size * 0.35)
    img.paste(pencil, (pencil_x - pencil.width // 2, pencil_y - pencil.height // 2), pencil)

    return img


def create_processing_icon(size: int = 256) -> Image.Image:
    """Create confused panda icon."""
    img, draw = create_canvas(size)
    cx, cy = size // 2, size // 2 + size // 10

    draw_panda_face(draw, cx, cy, size, eye_state="open")
    draw_question_mark(draw, cx + int(size * 0.35), cy - int(size * 0.25), size)

    return img


def create_error_icon(size: int = 256) -> Image.Image:
    """Create dizzy panda icon."""
    img, draw = create_canvas(size)
    cx, cy = size // 2, size // 2 + size // 10

    draw_panda_face(draw, cx, cy, size, eye_state="spiral")
    draw_stars(draw, cx, cy, size)

    return img


def create_success_icon(size: int = 256) -> Image.Image:
    """Create happy panda icon with sparkles."""
    img, draw = create_canvas(size)
    cx, cy = size // 2, size // 2 + size // 10

    draw_panda_face(draw, cx, cy, size, eye_state="open")
    draw_sparkles(draw, cx, cy, size)

    return img


def main():
    """Generate all panda icons."""
    output_dir = Path(__file__).parent

    # Generate icons at 256px (will be resized by the widget)
    size = 256

    icons = {
        "idle": create_idle_icon,
        "recording": create_recording_icon,
        "processing": create_processing_icon,
        "error": create_error_icon,
        "success": create_success_icon,
    }

    for name, create_func in icons.items():
        img = create_func(size)

        # Save full size
        output_path = output_dir / f"{name}.png"
        img.save(output_path, "PNG")
        print(f"Created {output_path}")

    print(f"\nGenerated {len(icons)} panda icons in {output_dir}")


if __name__ == "__main__":
    main()
