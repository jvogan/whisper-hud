"""
Image processing for custom widget icons.

Handles loading, cropping, resizing, and tinting images for the widget.
Uses PyObjC for native macOS image handling.

Supports multiple shape modes:
- circle: Crop to circle (default)
- alpha: Preserve image's alpha channel (for transparent PNGs)
- subject: AI-powered background removal using rembg
- vision: Native macOS 14+ Vision framework background removal
- auto: Auto-detect best mode (alpha > vision > subject > circle)
"""

import io
import hashlib
import platform
from pathlib import Path
from typing import Optional, Tuple, Dict

from .logging_config import get_logger

logger = get_logger("image_processor")

try:
    from AppKit import (
        NSImage, NSBezierPath, NSColor, NSCompositingOperationSourceOver,
        NSGraphicsContext, NSMakeRect, NSZeroRect,
        NSImageInterpolationHigh, NSBitmapImageRep, NSPNGFileType
    )
    from Foundation import NSData, NSURL
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False

# macOS Vision framework for native background removal (macOS 14+)
HAS_VISION = False
_VISION_AVAILABLE = False
try:
    from Vision import (
        VNGenerateForegroundInstanceMaskRequest,
        VNImageRequestHandler
    )
    from Quartz import (
        CIImage, CIContext, CIFilter,
    )
    HAS_VISION = True
    # Check macOS version
    macos_version = platform.mac_ver()[0]
    major_version = int(macos_version.split('.')[0]) if macos_version else 0
    _VISION_AVAILABLE = major_version >= 14
    if not _VISION_AVAILABLE:
        logger.debug(f"Vision framework requires macOS 14+, found {macos_version}")
except ImportError as e:
    logger.debug(f"Vision framework not available: {e}")

# Optional AI background removal
try:
    from rembg import remove as rembg_remove
    HAS_REMBG = True
except ImportError:
    HAS_REMBG = False

# PIL for image manipulation (required by rembg, also useful standalone)
try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# Supported image formats
SUPPORTED_FORMATS = {'.png', '.jpg', '.jpeg', '.gif', '.heic', '.webp', '.tiff', '.bmp'}

# Maximum file size (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

# Cache for processed images (with size limit to prevent memory leaks)
MAX_CACHE_SIZE = 100
_image_cache: Dict[str, 'NSImage'] = {}
_cache_order: list = []  # Track insertion order for LRU eviction


def _cache_set(key: str, image: 'NSImage') -> None:
    """Set a cache entry with LRU eviction when limit is reached."""
    # If key already exists, move it to end (most recently used)
    if key in _image_cache:
        _cache_order.remove(key)
        _cache_order.append(key)
        _image_cache[key] = image
        return

    # Evict oldest entry if at capacity
    while len(_image_cache) >= MAX_CACHE_SIZE and _cache_order:
        oldest_key = _cache_order.pop(0)
        _image_cache.pop(oldest_key, None)

    # Add new entry
    _image_cache[key] = image
    _cache_order.append(key)


def _cache_get(key: str) -> Optional['NSImage']:
    """Get a cache entry, updating access order for LRU."""
    if key in _image_cache:
        # Move to end (most recently used)
        if key in _cache_order:
            _cache_order.remove(key)
            _cache_order.append(key)
        return _image_cache[key]
    return None


def validate_image(path: str) -> Tuple[bool, str]:
    """
    Validate an image file for use as a custom icon.

    Args:
        path: Path to the image file

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not path:
        return False, "No path provided"

    file_path = Path(path)

    # Check if file exists
    if not file_path.exists():
        return False, "File does not exist"

    # Check file extension
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        return False, f"Unsupported format. Supported: {', '.join(SUPPORTED_FORMATS)}"

    # Check file size
    file_size = file_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        return False, f"File too large ({file_size / 1024 / 1024:.1f} MB). Maximum: 10 MB"

    if not HAS_APPKIT:
        return False, "AppKit not available"

    # Try to load the image
    try:
        image = NSImage.alloc().initWithContentsOfFile_(str(file_path))
        if image is None:
            return False, "Failed to load image"

        # Check if image has valid size
        size = image.size()
        if size.width < 16 or size.height < 16:
            return False, "Image too small (minimum 16x16)"

        return True, ""
    except Exception as e:
        return False, f"Error loading image: {str(e)}"


def load_image(path: str) -> Optional['NSImage']:
    """
    Load an image from disk.

    Args:
        path: Path to the image file

    Returns:
        NSImage or None if loading fails
    """
    if not HAS_APPKIT or not path:
        return None

    try:
        file_path = Path(path)
        if not file_path.exists():
            return None

        image = NSImage.alloc().initWithContentsOfFile_(str(file_path))
        return image
    except Exception as e:
        logger.error(f"Error loading image {path}: {e}")
        return None


def crop_to_circle(image: 'NSImage', size: int) -> Optional['NSImage']:
    """
    Crop an image to a circle and resize.

    Args:
        image: Source NSImage
        size: Target size in pixels (width and height)

    Returns:
        Circle-cropped NSImage or None
    """
    if not HAS_APPKIT or image is None:
        return None

    result = None
    try:
        # Create a new image with the target size
        result = NSImage.alloc().initWithSize_((size, size))
        result.lockFocus()
        try:
            # Set up high-quality interpolation
            context = NSGraphicsContext.currentContext()
            context.setImageInterpolation_(NSImageInterpolationHigh)

            # Create a circular clipping path
            circle_path = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(0, 0, size, size))
            circle_path.addClip()

            # Calculate source rect to crop center square
            src_size = image.size()
            src_min = min(src_size.width, src_size.height)
            src_x = (src_size.width - src_min) / 2
            src_y = (src_size.height - src_min) / 2
            src_rect = NSMakeRect(src_x, src_y, src_min, src_min)

            # Draw the image scaled to fit
            dest_rect = NSMakeRect(0, 0, size, size)
            image.drawInRect_fromRect_operation_fraction_(
                dest_rect,
                src_rect,
                NSCompositingOperationSourceOver,
                1.0
            )
        finally:
            result.unlockFocus()
        return result
    except Exception as e:
        logger.error(f"Error cropping image to circle: {e}")
        return None


def has_alpha_channel(image: 'NSImage') -> bool:
    """
    Check if an image has meaningful transparency (not all opaque).

    Args:
        image: Source NSImage

    Returns:
        True if image has actual transparent pixels
    """
    if not HAS_APPKIT or image is None:
        return False

    try:
        # Get the best representation
        reps = image.representations()
        if not reps:
            return False

        for rep in reps:
            if hasattr(rep, 'hasAlpha') and rep.hasAlpha():
                # Check if there are actually any transparent pixels
                if hasattr(rep, 'bitmapData'):
                    # Get bitmap data and sample for transparency
                    bitmap = rep
                    if bitmap.samplesPerPixel() >= 4:  # Has alpha channel
                        # Sample a few pixels to check for actual transparency
                        width = int(bitmap.pixelsWide())
                        height = int(bitmap.pixelsHigh())

                        # Sample corners and center
                        samples = [
                            (0, 0), (width - 1, 0),
                            (0, height - 1), (width - 1, height - 1),
                            (width // 2, height // 2)
                        ]

                        for x, y in samples:
                            try:
                                color = bitmap.colorAtX_y_(x, y)
                                if color and color.alphaComponent() < 0.99:
                                    return True
                            except Exception:
                                pass

                return True  # Has alpha flag but couldn't verify pixels, assume yes

        return False
    except Exception as e:
        logger.debug(f"Error checking alpha channel: {e}")
        return False


def crop_preserving_alpha(image: 'NSImage', size: int) -> Optional['NSImage']:
    """
    Resize image while preserving alpha channel (no circle crop).

    Creates a square image with the original centered and scaled to fit.

    Args:
        image: Source NSImage
        size: Target size in pixels (width and height)

    Returns:
        Resized NSImage with preserved alpha or None
    """
    if not HAS_APPKIT or image is None:
        return None

    result = None
    try:
        # Create a new transparent image
        result = NSImage.alloc().initWithSize_((size, size))
        result.lockFocus()
        try:
            # Set up high-quality interpolation
            context = NSGraphicsContext.currentContext()
            context.setImageInterpolation_(NSImageInterpolationHigh)

            # Clear to transparent
            NSColor.clearColor().set()
            NSBezierPath.fillRect_(NSMakeRect(0, 0, size, size))

            # Calculate scaling to fit while maintaining aspect ratio
            src_size = image.size()
            scale = min(size / src_size.width, size / src_size.height)
            new_width = src_size.width * scale
            new_height = src_size.height * scale

            # Center the image
            x_offset = (size - new_width) / 2
            y_offset = (size - new_height) / 2

            dest_rect = NSMakeRect(x_offset, y_offset, new_width, new_height)

            # Draw the image preserving transparency
            image.drawInRect_fromRect_operation_fraction_(
                dest_rect,
                NSZeroRect,
                NSCompositingOperationSourceOver,
                1.0
            )
        finally:
            result.unlockFocus()
        return result
    except Exception as e:
        logger.error(f"Error resizing with alpha: {e}")
        return None


def vision_remove_background(image_path: str, size: int) -> Optional['NSImage']:
    """
    Remove background using macOS 14+ Vision framework.

    Uses VNGenerateForegroundInstanceMaskRequest to isolate the subject
    and create a transparent background.

    Args:
        image_path: Path to source image file
        size: Target size in pixels

    Returns:
        NSImage with transparent background or None if not available/failed
    """
    if not HAS_VISION or not _VISION_AVAILABLE or not HAS_APPKIT:
        return None

    try:
        # Load image as CIImage
        url = NSURL.fileURLWithPath_(image_path)
        ci_image = CIImage.imageWithContentsOfURL_(url)
        if ci_image is None:
            logger.warning(f"Could not load image as CIImage: {image_path}")
            return None

        # Create the foreground mask request
        request = VNGenerateForegroundInstanceMaskRequest.alloc().init()

        # Create handler and perform request
        handler = VNImageRequestHandler.alloc().initWithCIImage_options_(ci_image, None)

        # PyObjC: performRequests:error: returns bool, error is output param
        success = handler.performRequests_error_([request], None)
        if not success:
            logger.warning("Vision request failed")
            return None

        # Get results
        results = request.results()
        if not results or len(results) == 0:
            logger.warning("No foreground mask results from Vision")
            return None

        observation = results[0]

        # Generate the mask as a CIImage
        mask_ci = observation.generateScaledMaskForImage_(ci_image)
        if mask_ci is None:
            logger.warning("Could not generate scaled mask")
            return None

        # Create CIContext for rendering
        context = CIContext.context()

        # Apply the mask to the original image
        # Use CIBlendWithMask filter to composite with transparent background
        blend_filter = CIFilter.filterWithName_("CIBlendWithMask")
        if blend_filter is None:
            logger.warning("CIBlendWithMask filter not available")
            return None

        # Create a transparent background
        extent = ci_image.extent()
        clear_color = CIImage.imageWithColor_(
            NSColor.clearColor().colorUsingColorSpaceName_("NSCalibratedRGBColorSpace")
        )
        if clear_color:
            clear_color = clear_color.imageByCroppingToRect_(extent)

        blend_filter.setValue_forKey_(ci_image, "inputImage")
        blend_filter.setValue_forKey_(clear_color, "inputBackgroundImage")
        blend_filter.setValue_forKey_(mask_ci, "inputMaskImage")

        output_ci = blend_filter.outputImage()
        if output_ci is None:
            logger.warning("Blend filter produced no output")
            return None

        # Render to CGImage
        cg_image = context.createCGImage_fromRect_(output_ci, extent)
        if cg_image is None:
            logger.warning("Could not create CGImage from result")
            return None

        # Convert to NSImage
        ns_image = NSImage.alloc().initWithCGImage_size_(cg_image, (0, 0))
        if ns_image is None:
            return None

        # Resize and center in target size
        result = crop_preserving_alpha(ns_image, size)
        logger.debug(f"Vision background removal successful for {image_path}")
        return result

    except Exception as e:
        logger.error(f"Error in Vision background removal: {e}")
        return None


def extract_subject(image_path: str, size: int) -> Optional['NSImage']:
    """
    Extract subject from image using AI background removal (rembg).

    Args:
        image_path: Path to source image file
        size: Target size in pixels

    Returns:
        NSImage with subject extracted (transparent background) or None
    """
    if not HAS_REMBG or not HAS_PIL or not HAS_APPKIT:
        return None

    try:
        # Load image with PIL
        pil_image = PILImage.open(image_path)

        # Convert to RGBA if needed
        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')

        # Remove background using rembg
        output = rembg_remove(pil_image)

        # Resize to fit in target size while maintaining aspect ratio
        output.thumbnail((size, size), PILImage.Resampling.LANCZOS)

        # Create a new image with the subject centered
        final = PILImage.new('RGBA', (size, size), (0, 0, 0, 0))
        x_offset = (size - output.width) // 2
        y_offset = (size - output.height) // 2
        final.paste(output, (x_offset, y_offset))

        # Convert PIL image to NSImage
        return pil_to_nsimage(final)
    except Exception as e:
        logger.error(f"Error extracting subject: {e}")
        return None


def pil_to_nsimage(pil_image: 'PILImage.Image') -> Optional['NSImage']:
    """
    Convert a PIL Image to NSImage.

    Args:
        pil_image: PIL Image object (should be RGBA)

    Returns:
        NSImage or None
    """
    if not HAS_APPKIT or not HAS_PIL:
        return None

    try:
        # Ensure RGBA mode
        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')

        # Save to bytes as PNG
        buffer = io.BytesIO()
        pil_image.save(buffer, format='PNG')
        png_data = buffer.getvalue()

        # Create NSImage from PNG data
        ns_data = NSData.dataWithBytes_length_(png_data, len(png_data))
        ns_image = NSImage.alloc().initWithData_(ns_data)

        return ns_image
    except Exception as e:
        logger.error(f"Error converting PIL to NSImage: {e}")
        return None


def process_shape(
    image: 'NSImage',
    image_path: str,
    size: int,
    shape_mode: str = "auto"
) -> Optional['NSImage']:
    """
    Process image according to shape mode with fallback chain.

    Args:
        image: Source NSImage (already loaded)
        image_path: Original file path (needed for subject extraction)
        size: Target size in pixels
        shape_mode: "auto", "circle", "alpha", "vision", or "subject"

    Returns:
        Processed NSImage or None
    """
    if not HAS_APPKIT or image is None:
        return None

    if shape_mode == "circle":
        return crop_to_circle(image, size)

    elif shape_mode == "alpha":
        # Use alpha if image has transparency, otherwise fall back to circle
        if has_alpha_channel(image):
            return crop_preserving_alpha(image, size)
        return crop_to_circle(image, size)

    elif shape_mode == "vision":
        # Try Vision framework (macOS 14+), fall back to rembg, then circle
        if _VISION_AVAILABLE and image_path:
            result = vision_remove_background(image_path, size)
            if result:
                return result
        # Fall back to rembg
        if HAS_REMBG and image_path:
            result = extract_subject(image_path, size)
            if result:
                return result
        return crop_to_circle(image, size)

    elif shape_mode == "subject":
        # Try AI extraction (rembg), fall back to circle
        if HAS_REMBG and image_path:
            result = extract_subject(image_path, size)
            if result:
                return result
        return crop_to_circle(image, size)

    elif shape_mode == "auto":
        # Priority: alpha > vision > subject > circle
        if has_alpha_channel(image):
            return crop_preserving_alpha(image, size)

        # Try Vision framework first (native, fast)
        if _VISION_AVAILABLE and image_path:
            result = vision_remove_background(image_path, size)
            if result:
                return result

        # Fall back to rembg
        if HAS_REMBG and image_path:
            result = extract_subject(image_path, size)
            if result:
                return result

        return crop_to_circle(image, size)

    else:
        # Unknown mode, default to circle
        return crop_to_circle(image, size)


def apply_tint(image: 'NSImage', hex_color: str, opacity: float = 0.3) -> Optional['NSImage']:
    """
    Apply a color tint overlay to an image.

    Args:
        image: Source NSImage
        hex_color: Hex color code (e.g., "#FF0000")
        opacity: Tint opacity (0.0 to 1.0)

    Returns:
        Tinted NSImage or None
    """
    if not HAS_APPKIT or image is None:
        return None

    try:
        # Parse hex color
        color = hex_to_nscolor(hex_color)
        if color is None:
            return image

        size = image.size()

        # Create result image
        result = NSImage.alloc().initWithSize_(size)
        result.lockFocus()

        # Draw original image
        image.drawAtPoint_fromRect_operation_fraction_(
            (0, 0),
            NSZeroRect,
            NSCompositingOperationSourceOver,
            1.0
        )

        # Draw tint overlay
        tint_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            color.redComponent(),
            color.greenComponent(),
            color.blueComponent(),
            opacity
        )
        tint_color.set()

        rect = NSMakeRect(0, 0, size.width, size.height)
        NSBezierPath.fillRect_(rect)

        result.unlockFocus()
        return result
    except Exception as e:
        logger.error(f"Error applying tint: {e}")
        return image


def hex_to_nscolor(hex_color: str) -> Optional['NSColor']:
    """
    Convert a hex color string to NSColor.

    Args:
        hex_color: Hex color (e.g., "#FF0000" or "FF0000")

    Returns:
        NSColor or None if invalid
    """
    if not HAS_APPKIT:
        return None

    try:
        # Remove # prefix if present
        hex_color = hex_color.lstrip('#')

        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)
        elif len(hex_color) == 8:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            a = int(hex_color[6:8], 16) / 255.0
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
    except Exception as e:
        logger.debug(f"Error parsing hex color {hex_color}: {e}")

    return None


def _get_cache_key(
    path: str,
    size: int,
    state: str,
    tint_color: str = "",
    tint_opacity: float = 0.0,
    shape_mode: str = "circle"
) -> str:
    """Generate a cache key for a processed image."""
    key_str = f"{path}_{size}_{state}_{tint_color}_{tint_opacity}_{shape_mode}"
    return hashlib.md5(key_str.encode()).hexdigest()


def get_icon_for_state(
    config: dict,
    state: str,
    size: int,
    force_reload: bool = False
) -> Optional['NSImage']:
    """
    Get a processed icon for a specific widget state.

    Args:
        config: Widget appearance config dict
        state: Widget state (idle, recording, processing, success, error)
        size: Target icon size in pixels
        force_reload: Force reload from disk, bypassing cache

    Returns:
        Processed NSImage or None
    """
    if not HAS_APPKIT:
        return None

    custom_icon = config.get("custom_icon", {})
    if not custom_icon.get("enabled", False):
        return None

    # Get icon path - either per-state or single icon
    if custom_icon.get("per_state", False):
        icons = custom_icon.get("icons", {})
        path = icons.get(state, "")
        if not path:
            path = custom_icon.get("path", "")
    else:
        path = custom_icon.get("path", "")

    if not path:
        return None

    # Get shape mode
    shape_mode = custom_icon.get("shape_mode", "auto")

    # Get tint settings
    apply_tint_flag = custom_icon.get("apply_state_tint", True)
    tint_opacity = custom_icon.get("tint_opacity", 0.3)

    # Get tint color from state colors
    colors = config.get("colors", {})
    state_colors = colors.get(state, {})
    tint_color = state_colors.get("icon", "#FFFFFF") if apply_tint_flag else ""

    # Check cache
    cache_key = _get_cache_key(
        path, size, state, tint_color,
        tint_opacity if apply_tint_flag else 0,
        shape_mode
    )
    if not force_reload:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    # Load and process image
    image = load_image(path)
    if image is None:
        return None

    # Process according to shape mode
    image = process_shape(image, path, size, shape_mode)
    if image is None:
        return None

    # Apply tint if enabled and not idle state
    if apply_tint_flag and state != "idle" and tint_color:
        image = apply_tint(image, tint_color, tint_opacity)

    # Cache result with LRU eviction
    _cache_set(cache_key, image)

    return image


def import_image(source_path: str, dest_dir: str, filename: str = None) -> Tuple[bool, str, str]:
    """
    Import an image to the custom icons directory.

    Args:
        source_path: Path to the source image
        dest_dir: Destination directory
        filename: Optional filename (generated from source if not provided)

    Returns:
        Tuple of (success, dest_path, error_message)
    """
    # Validate source
    is_valid, error = validate_image(source_path)
    if not is_valid:
        return False, "", error

    try:
        source = Path(source_path)
        dest_path = Path(dest_dir).resolve()

        # Security: Validate destination is within allowed config directory
        config_dir = (Path.home() / ".config" / "whisper-hud").resolve()
        try:
            dest_path.relative_to(config_dir)
        except ValueError:
            return False, "", "Invalid destination directory"

        dest_path.mkdir(parents=True, exist_ok=True)

        # Generate filename if not provided
        if not filename:
            # Use hash of file content for unique naming
            with open(source, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()[:8]
            filename = f"icon_{file_hash}{source.suffix.lower()}"

        # Security: Validate filename doesn't contain path traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            return False, "", "Invalid filename"

        # Validate the final path stays within dest_dir
        dest_file = (dest_path / filename).resolve()
        try:
            dest_file.relative_to(dest_path)
        except ValueError:
            return False, "", "Invalid filename path"

        # Copy file
        import shutil
        shutil.copy2(source, dest_file)

        return True, str(dest_file), ""
    except Exception as e:
        return False, "", f"Failed to import image: {str(e)}"


def clear_cache():
    """Clear the image cache."""
    global _image_cache, _cache_order
    _image_cache = {}
    _cache_order = []


def get_preview_image(
    path: str,
    size: int,
    tint_color: str = "",
    tint_opacity: float = 0.3,
    shape_mode: str = "circle"
) -> Optional['NSImage']:
    """
    Get a preview of a processed image without caching.

    Args:
        path: Path to the image
        size: Target size
        tint_color: Optional tint color
        tint_opacity: Tint opacity
        shape_mode: Shape mode ("auto", "circle", "alpha", "subject")

    Returns:
        Processed NSImage or None
    """
    if not HAS_APPKIT:
        return None

    image = load_image(path)
    if image is None:
        return None

    # Process according to shape mode
    image = process_shape(image, path, size, shape_mode)
    if image is None:
        return None

    if tint_color:
        image = apply_tint(image, tint_color, tint_opacity)

    return image


def is_rembg_available() -> bool:
    """Check if rembg (AI background removal) is available."""
    return HAS_REMBG


def is_vision_available() -> bool:
    """Check if Vision framework background removal is available (macOS 14+)."""
    return _VISION_AVAILABLE


def get_shape_mode_description(mode: str) -> str:
    """Get a human-readable description of a shape mode."""
    descriptions = {
        "auto": "Auto-detect (tries alpha, then Vision/AI, then circle)",
        "circle": "Circle crop (default)",
        "alpha": "Use transparency from PNG",
        "vision": "macOS Vision framework (requires macOS 14+)",
        "subject": "AI subject extraction (requires rembg)"
    }
    return descriptions.get(mode, mode)


def remove_background(image_path: str, size: int) -> Optional['NSImage']:
    """
    Remove background from an image using the best available method.

    Priority: Vision (macOS 14+) > rembg > preserve alpha > None

    Args:
        image_path: Path to the image file
        size: Target size in pixels

    Returns:
        NSImage with transparent background or None if all methods fail
    """
    if not HAS_APPKIT:
        return None

    # Try Vision framework first (fastest, native)
    if _VISION_AVAILABLE:
        result = vision_remove_background(image_path, size)
        if result:
            logger.debug(f"Background removed via Vision: {image_path}")
            return result

    # Fall back to rembg
    if HAS_REMBG:
        result = extract_subject(image_path, size)
        if result:
            logger.debug(f"Background removed via rembg: {image_path}")
            return result

    # Try to preserve existing alpha
    image = load_image(image_path)
    if image and has_alpha_channel(image):
        result = crop_preserving_alpha(image, size)
        if result:
            logger.debug(f"Preserved alpha channel: {image_path}")
            return result

    logger.warning(f"No background removal method available for: {image_path}")
    return None


def save_nsimage_as_png(image: 'NSImage', dest_path: str) -> bool:
    """
    Save an NSImage to a PNG file.

    Args:
        image: NSImage to save
        dest_path: Destination file path

    Returns:
        True if successful, False otherwise
    """
    if not HAS_APPKIT or image is None:
        return False

    try:
        # Get the bitmap representation
        size = image.size()
        image.lockFocus()
        try:
            bitmap = NSBitmapImageRep.alloc().initWithFocusedViewRect_(
                NSMakeRect(0, 0, size.width, size.height)
            )
        finally:
            image.unlockFocus()

        if bitmap is None:
            logger.error("Could not create bitmap representation")
            return False

        # Get PNG data
        png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
        if png_data is None:
            logger.error("Could not create PNG data")
            return False

        # Write to file
        success = png_data.writeToFile_atomically_(dest_path, True)
        if success:
            logger.debug(f"Saved PNG to: {dest_path}")
        return success

    except Exception as e:
        logger.error(f"Error saving NSImage as PNG: {e}")
        return False


def get_background_removal_method() -> str:
    """
    Get a description of the available background removal method.

    Returns:
        Human-readable string describing available method
    """
    if _VISION_AVAILABLE:
        return "Vision (macOS 14+)"
    elif HAS_REMBG:
        return "rembg (AI)"
    else:
        return "None (alpha only)"


class ImageProcessor:
    """
    High-level interface for image processing operations.

    Wraps the module-level functions with config awareness.
    """

    def __init__(self, config):
        """
        Initialize the image processor.

        Args:
            config: Config object with widget_appearance settings
        """
        self._config = config

    def get_icon_for_state(self, state: str, size: int) -> Optional['NSImage']:
        """Get the processed icon for a widget state."""
        appearance = self._config.widget_appearance
        return get_icon_for_state(appearance, state, size)

    def validate_image(self, path: str) -> Tuple[bool, str]:
        """Validate an image file."""
        return validate_image(path)

    def import_image(self, source_path: str, filename: str = None) -> Tuple[bool, str, str]:
        """Import an image to the custom icons directory."""
        dest_dir = str(self._config.get_custom_icons_dir())
        return import_image(source_path, dest_dir, filename)

    def get_preview(
        self,
        path: str,
        size: int,
        tint_color: str = "",
        tint_opacity: float = 0.3,
        shape_mode: str = None
    ) -> Optional['NSImage']:
        """
        Get a preview of a processed image.

        Args:
            path: Path to the image
            size: Target size
            tint_color: Optional tint color
            tint_opacity: Tint opacity
            shape_mode: Shape mode (uses config default if None)
        """
        # Use config's shape_mode if not specified
        if shape_mode is None:
            custom_icon = self._config.widget_appearance.get("custom_icon", {})
            shape_mode = custom_icon.get("shape_mode", "circle")

        return get_preview_image(path, size, tint_color, tint_opacity, shape_mode)

    def get_current_shape_mode(self) -> str:
        """Get the current shape mode from config."""
        custom_icon = self._config.widget_appearance.get("custom_icon", {})
        return custom_icon.get("shape_mode", "auto")

    def is_rembg_available(self) -> bool:
        """Check if AI subject extraction is available."""
        return is_rembg_available()

    def is_vision_available(self) -> bool:
        """Check if Vision framework background removal is available."""
        return is_vision_available()

    def get_background_removal_method(self) -> str:
        """Get description of available background removal method."""
        return get_background_removal_method()

    def remove_background(self, image_path: str, size: int) -> Optional['NSImage']:
        """Remove background from image using best available method."""
        return remove_background(image_path, size)

    def save_image(self, image: 'NSImage', dest_path: str) -> bool:
        """Save an NSImage to a PNG file."""
        return save_nsimage_as_png(image, dest_path)

    def clear_cache(self):
        """Clear the image cache."""
        clear_cache()

    def reload(self):
        """Reload icons by clearing cache."""
        self.clear_cache()
