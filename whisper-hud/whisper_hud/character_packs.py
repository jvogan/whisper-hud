"""
Character pack management for WhisperHUD.

Character packs provide themed icon sets for different widget states,
allowing users to customize the floating widget's appearance with
fun character icons like pandas, cats, robots, etc.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from .logging_config import get_logger

logger = get_logger("character_packs")
_VALID_PACK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Animation / sound schema (manifest v2) constraints.
# Frame-sequence playback speed is clamped to a sane range so a malformed
# manifest cannot pin the animation timer at an absurd interval.
MIN_FRAME_FPS = 0.5
MAX_FRAME_FPS = 30.0
DEFAULT_FRAME_FPS = 12.0

# Per-state sounds are restricted to small, uncompressed clips that NSSound /
# afplay can play without extra codecs.
ALLOWED_SOUND_EXTENSIONS = {".wav", ".aiff", ".aif"}
MAX_SOUND_SIZE = 2 * 1024 * 1024  # 2 MB

# Valid interpolation hints for the rendering pipeline.
VALID_INTERPOLATION_MODES = {"smooth", "nearest"}
DEFAULT_INTERPOLATION = "smooth"


def _clamp_fps(value: Any) -> float:
    """Coerce a manifest fps value into the supported range."""
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return DEFAULT_FRAME_FPS
    if fps != fps:  # NaN guard
        return DEFAULT_FRAME_FPS
    return max(MIN_FRAME_FPS, min(MAX_FRAME_FPS, fps))


# Default location for built-in character packs
def _get_builtin_packs_dir() -> Path:
    """Get the directory containing built-in character packs."""
    # Navigate from whisper-hud/whisper_hud to assets/character-packs
    src_dir = Path(__file__).parent
    project_root = src_dir.parent.parent
    return project_root / "assets" / "character-packs"


def _get_user_packs_dir() -> Path:
    """Get the directory for user-installed character packs."""
    return Path.home() / ".config" / "whisper-hud" / "character-packs"


def _is_valid_pack_id(pack_id: str) -> bool:
    """Allow only simple slugs for user-controlled pack identifiers."""
    return bool(pack_id and _VALID_PACK_ID_RE.fullmatch(pack_id))


def _resolve_pack_member(pack_dir: Path, relative_path: str) -> Optional[Path]:
    """Resolve a manifest path safely inside the pack directory."""
    if not relative_path:
        return None

    pack_root = pack_dir.resolve()
    candidate = (pack_root / relative_path).resolve()
    if not candidate.is_relative_to(pack_root):
        return None
    return candidate


def _resolve_pack_sound(pack_dir: Path, relative_path: str) -> Optional[Path]:
    """Resolve a sound path, enforcing extension and size limits.

    Returns the resolved path only when it stays inside the pack, has an
    allowed extension and is within ``MAX_SOUND_SIZE``; otherwise None.
    """
    candidate = _resolve_pack_member(pack_dir, relative_path)
    if candidate is None or not candidate.is_file():
        return None
    if candidate.suffix.lower() not in ALLOWED_SOUND_EXTENSIONS:
        logger.warning(f"Sound has unsupported extension and was skipped: {relative_path}")
        return None
    try:
        if candidate.stat().st_size > MAX_SOUND_SIZE:
            logger.warning(f"Sound exceeds size cap and was skipped: {relative_path}")
            return None
    except OSError:
        return None
    return candidate


def _get_safe_user_pack_dir(pack_id: str) -> Optional[Path]:
    """Return the target user-pack directory only for safe pack identifiers."""
    if not _is_valid_pack_id(pack_id):
        return None

    user_dir = _get_user_packs_dir()
    user_root = user_dir.resolve()
    candidate = (user_root / pack_id).resolve()
    if not candidate.is_relative_to(user_root):
        return None
    return candidate


@dataclass
class CharacterPackState:
    """Represents a single state's icon in a character pack.

    Manifest v2 (all optional) adds multi-frame sprite animation and a
    per-state sound:

    - ``frames``: ordered list of image filenames resolved to ``frame_paths``.
      When present, the widget plays them as an animation loop (or one-shot for
      transient states) instead of the single ``file`` icon.
    - ``fps``: playback speed for ``frames`` (clamped to ``MIN_FRAME_FPS``..
      ``MAX_FRAME_FPS``).
    - ``sound``: filename played once when the widget enters this state.
    """

    file: str
    description: str = ""
    full_path: str = ""
    frames: List[str] = field(default_factory=list)
    frame_paths: List[str] = field(default_factory=list)
    fps: float = DEFAULT_FRAME_FPS
    sound: str = ""
    sound_path: str = ""


@dataclass
class CharacterPack:
    """Represents a character pack with icons for different states."""

    id: str
    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    preview_image: str = ""
    preview_path: str = ""  # Full path to preview image
    pack_dir: str = ""  # Directory containing the pack
    builtin: bool = True  # True if this is a built-in pack

    # Optional menu bar glyph shown (in color) while the app is idle and this
    # pack is active. Replaces only the idle status icon; recording/processing
    # and the other states keep the standard template icons for legibility.
    menubar_icon: str = ""
    menubar_icon_path: str = ""

    # State icons
    states: Dict[str, CharacterPackState] = field(default_factory=dict)

    # Recommended settings
    settings: Dict[str, Any] = field(
        default_factory=lambda: {"shape_mode": "alpha", "apply_state_tint": False, "recommended_size": "large"}
    )

    def get_icon_path(self, state: str) -> Optional[str]:
        """Get the full path to an icon for a specific state."""
        if state in self.states:
            return self.states[state].full_path
        return None

    def get_all_icon_paths(self) -> Dict[str, str]:
        """Get a dict of state -> full path for all icons."""
        return {state: info.full_path for state, info in self.states.items() if info.full_path}

    def get_animation_states(self) -> Dict[str, Dict[str, Any]]:
        """Per-state animation metadata for the widget/image layers.

        Maps each state with resolved frames to ``{frames, fps}`` where
        ``frames`` is a list of absolute image paths.
        """
        animations: Dict[str, Dict[str, Any]] = {}
        for state, info in self.states.items():
            if info.frame_paths:
                animations[state] = {"frames": list(info.frame_paths), "fps": info.fps}
        return animations

    def get_state_sounds(self) -> Dict[str, str]:
        """Map of state -> absolute sound path for states that define one."""
        return {state: info.sound_path for state, info in self.states.items() if info.sound_path}

    def get_interpolation(self) -> str:
        """Interpolation hint requested by the pack (smooth|nearest)."""
        mode = self.settings.get("interpolation", DEFAULT_INTERPOLATION)
        return mode if mode in VALID_INTERPOLATION_MODES else DEFAULT_INTERPOLATION

    def to_appearance_config(self) -> Dict[str, Any]:
        """Convert pack to widget appearance custom_icon config format.

        ``icons`` stays a flat state -> path map for backward compatibility with
        the single-icon image pipeline. Manifest v2 adds ``animations`` (frame
        sequences), ``sounds`` (per-state audio) and ``interpolation`` so the
        widget and image layers can opt into animation / crisp pixel-art
        rendering without breaking older packs.
        """
        return {
            "enabled": True,
            "path": "",  # Not used when per_state is True
            "per_state": True,
            "icons": self.get_all_icon_paths(),
            "animations": self.get_animation_states(),
            "sounds": self.get_state_sounds(),
            "interpolation": self.get_interpolation(),
            "apply_state_tint": self.settings.get("apply_state_tint", False),
            "tint_opacity": self.settings.get("tint_opacity", 0.3),
            "shape_mode": self.settings.get("shape_mode", "alpha"),
            "character_pack": self.id,
            "menubar_icon": self.menubar_icon_path,
        }


def load_pack_manifest(pack_dir: Path) -> Optional[CharacterPack]:
    """
    Load a character pack from a directory containing manifest.json.

    Args:
        pack_dir: Path to the character pack directory

    Returns:
        CharacterPack or None if loading fails
    """
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        logger.debug(f"No manifest.json in {pack_dir}")
        return None

    try:
        with open(manifest_path, "r") as f:
            data = json.load(f)

        pack_id = data.get("id", pack_dir.name)
        if not _is_valid_pack_id(pack_id):
            logger.warning(f"Invalid character pack id '{pack_id}' in {pack_dir}")
            return None

        pack = CharacterPack(
            id=pack_id,
            name=data.get("name", pack_id.title()),
            description=data.get("description", ""),
            author=data.get("author", ""),
            version=data.get("version", "1.0.0"),
            preview_image=data.get("preview_image", ""),
            pack_dir=str(pack_dir),
            settings=data.get("settings", {}),
        )

        # Load state icons
        states_data = data.get("states", {})
        for state_name, state_info in states_data.items():
            if isinstance(state_info, str):
                # Simple format: just filename
                file_name = state_info
                description = ""
                frames_raw: List[Any] = []
                fps_raw: Any = DEFAULT_FRAME_FPS
                sound_raw = ""
            else:
                # Full format: dict with file and (optional) v2 keys.
                file_name = state_info.get("file", "")
                description = state_info.get("description", "")
                frames_raw = state_info.get("frames", []) or []
                fps_raw = state_info.get("fps", DEFAULT_FRAME_FPS)
                sound_raw = state_info.get("sound", "") or ""

            if file_name:
                full_path = _resolve_pack_member(pack_dir, file_name)
                if full_path and full_path.is_file():
                    state = CharacterPackState(file=file_name, description=description, full_path=str(full_path))

                    # Resolve frame sequence (manifest v2). Every frame must
                    # stay inside the pack and exist; unsafe/missing frames are
                    # dropped so the state simply falls back to the static icon.
                    if isinstance(frames_raw, list):
                        for frame_name in frames_raw:
                            if not isinstance(frame_name, str) or not frame_name:
                                continue
                            frame_path = _resolve_pack_member(pack_dir, frame_name)
                            if frame_path and frame_path.is_file():
                                state.frames.append(frame_name)
                                state.frame_paths.append(str(frame_path))
                            else:
                                logger.warning(f"Frame is missing or escapes the pack directory: {frame_name}")

                    state.fps = _clamp_fps(fps_raw)

                    # Resolve per-state sound (manifest v2).
                    if sound_raw:
                        sound_path = _resolve_pack_sound(pack_dir, sound_raw)
                        if sound_path:
                            state.sound = sound_raw
                            state.sound_path = str(sound_path)

                    pack.states[state_name] = state
                else:
                    logger.warning(f"Icon path is missing or escapes the pack directory: {file_name}")

        # Set preview path
        if pack.preview_image:
            preview_path = _resolve_pack_member(pack_dir, pack.preview_image)
            if preview_path and preview_path.is_file():
                pack.preview_path = str(preview_path)
            else:
                logger.warning(f"Preview image path is missing or escapes the pack directory: {pack.preview_image}")

        # Optional menu bar glyph (same containment rules as other members).
        menubar_icon = data.get("menubar_icon", "")
        if isinstance(menubar_icon, str) and menubar_icon:
            menubar_path = _resolve_pack_member(pack_dir, menubar_icon)
            if menubar_path and menubar_path.is_file():
                pack.menubar_icon = menubar_icon
                pack.menubar_icon_path = str(menubar_path)
            else:
                logger.warning(f"Menubar icon is missing or escapes the pack directory: {menubar_icon}")

        # Validate that pack has at least idle state
        if "idle" not in pack.states:
            logger.warning(f"Pack {pack_id} missing required 'idle' state")
            return None

        return pack

    except json.JSONDecodeError as e:
        logger.error(f"Invalid manifest.json in {pack_dir}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading pack from {pack_dir}: {e}")
        return None


def discover_packs() -> List[CharacterPack]:
    """
    Discover all available character packs.

    Returns:
        List of CharacterPack objects
    """
    packs = []

    # Check built-in packs
    builtin_dir = _get_builtin_packs_dir()
    if builtin_dir.exists():
        for item in builtin_dir.iterdir():
            if item.is_dir():
                pack = load_pack_manifest(item)
                if pack:
                    pack.builtin = True
                    packs.append(pack)
                    logger.debug(f"Found built-in pack: {pack.name}")

    # Check user packs
    user_dir = _get_user_packs_dir()
    if user_dir.exists():
        for item in user_dir.iterdir():
            if item.is_dir():
                pack = load_pack_manifest(item)
                if pack:
                    pack.builtin = False
                    # Check for ID collision with built-in packs
                    if any(p.id == pack.id for p in packs):
                        pack.id = f"user_{pack.id}"
                    packs.append(pack)
                    logger.debug(f"Found user pack: {pack.name}")

    return packs


def get_pack_by_id(pack_id: str) -> Optional[CharacterPack]:
    """
    Get a specific character pack by its ID.

    Args:
        pack_id: The pack's unique identifier

    Returns:
        CharacterPack or None if not found
    """
    for pack in discover_packs():
        if pack.id == pack_id:
            return pack
    return None


def get_available_packs() -> List[Dict[str, Any]]:
    """
    Get a list of available packs in a format suitable for menus.

    Returns:
        List of dicts with id, name, description, builtin
    """
    packs = discover_packs()
    return [
        {
            "id": pack.id,
            "name": pack.name,
            "description": pack.description,
            "builtin": pack.builtin,
            "preview_path": pack.preview_path,
            "state_count": len(pack.states),
        }
        for pack in packs
    ]


class CharacterPackManager:
    """
    Manager for character packs.

    Provides methods for listing, applying, and managing character packs.
    """

    def __init__(self, config):
        """
        Initialize the character pack manager.

        Args:
            config: Config object for reading/writing settings
        """
        self._config = config
        self._packs_cache: Optional[List[CharacterPack]] = None

    def get_available_packs(self) -> List[CharacterPack]:
        """Get all available character packs."""
        if self._packs_cache is None:
            self._packs_cache = discover_packs()
        return self._packs_cache

    def refresh_packs(self) -> List[CharacterPack]:
        """Refresh the list of available packs."""
        self._packs_cache = None
        return self.get_available_packs()

    def get_pack(self, pack_id: str) -> Optional[CharacterPack]:
        """Get a specific pack by ID."""
        for pack in self.get_available_packs():
            if pack.id == pack_id:
                return pack
        return None

    def get_current_pack_id(self) -> Optional[str]:
        """Get the ID of the currently active pack, or None if using default."""
        custom_icon = self._config.widget_appearance.get("custom_icon", {})
        return custom_icon.get("character_pack")

    def apply_pack(self, pack_id: str) -> bool:
        """
        Apply a character pack to the current configuration.

        Args:
            pack_id: The pack ID to apply

        Returns:
            True if successful, False otherwise
        """
        pack = self.get_pack(pack_id)
        if pack is None:
            logger.error(f"Pack not found: {pack_id}")
            return False

        # Update config with pack settings
        custom_icon_config = pack.to_appearance_config()
        self._config.widget_appearance["custom_icon"] = custom_icon_config

        # Apply recommended size if specified
        recommended_size = pack.settings.get("recommended_size")
        if recommended_size and recommended_size in ("small", "medium", "large", "xlarge"):
            self._config.widget_size = recommended_size

        self._config.save()
        logger.info(f"Applied character pack: {pack.name}")
        return True

    def clear_pack(self) -> None:
        """Remove the current character pack and revert to default icons."""
        self._config.widget_appearance["custom_icon"] = {
            "enabled": False,
            "path": "",
            "per_state": False,
            "icons": {"idle": "", "recording": "", "processing": "", "success": "", "error": ""},
            "apply_state_tint": True,
            "tint_opacity": 0.3,
            "shape_mode": "auto",
            "character_pack": None,
        }
        self._config.save()
        logger.info("Cleared character pack, reverted to default")

    def is_pack_active(self, pack_id: str) -> bool:
        """Check if a specific pack is currently active."""
        return self.get_current_pack_id() == pack_id

    def get_pack_for_menu(self) -> List[Dict[str, Any]]:
        """
        Get packs formatted for menu display.

        Returns:
            List of dicts with id, name, description, active, builtin
        """
        current_pack_id = self.get_current_pack_id()
        packs = self.get_available_packs()

        result = []
        for pack in packs:
            result.append(
                {
                    "id": pack.id,
                    "name": pack.name,
                    "description": pack.description,
                    "active": pack.id == current_pack_id,
                    "builtin": pack.builtin,
                }
            )

        return result


def install_pack_from_directory(source_dir: str) -> Optional[CharacterPack]:
    """
    Install a character pack from a directory.

    Copies the pack to the user packs directory.

    Args:
        source_dir: Path to the source pack directory

    Returns:
        Installed CharacterPack or None if failed
    """
    import shutil
    import tempfile

    source_path = Path(source_dir).expanduser().resolve()
    if not source_path.exists() or not source_path.is_dir():
        logger.error(f"Source directory not found: {source_dir}")
        return None

    # Validate the pack first
    pack = load_pack_manifest(source_path)
    if pack is None:
        logger.error(f"Invalid pack in {source_dir}")
        return None

    # Create user packs directory
    user_dir = _get_user_packs_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(user_dir, 0o700)
    except Exception:
        pass

    # Copy to user directory using a manifest-driven allowlist.
    dest_dir = _get_safe_user_pack_dir(pack.id)
    if dest_dir is None:
        logger.error(f"Invalid pack id during install: {pack.id}")
        return None

    if dest_dir.exists():
        logger.warning(f"Pack {pack.id} already exists, overwriting")
        if dest_dir.is_symlink() or dest_dir.is_file():
            dest_dir.unlink()
        else:
            shutil.rmtree(dest_dir)

    temp_dir = Path(tempfile.mkdtemp(prefix=f".pack-install-{pack.id}-", dir=str(user_dir)))
    try:
        os.chmod(temp_dir, 0o700)
    except Exception:
        pass

    files_to_copy = {"manifest.json"}
    for state in pack.states.values():
        files_to_copy.add(state.file)
        # Frame sequences and per-state sounds must be copied too, otherwise the
        # manifest references them but they silently vanish on install.
        files_to_copy.update(state.frames)
        if state.sound:
            files_to_copy.add(state.sound)
    if pack.preview_image:
        files_to_copy.add(pack.preview_image)
    if pack.menubar_icon:
        files_to_copy.add(pack.menubar_icon)

    try:
        for relative_path in sorted(files_to_copy):
            source_member = _resolve_pack_member(source_path, relative_path)
            if source_member is None or not source_member.is_file():
                logger.error(f"Pack member is missing or unsafe: {relative_path}")
                return None

            destination = temp_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(destination.parent, 0o700)
            except Exception:
                pass
            shutil.copy2(source_member, destination)
            try:
                os.chmod(destination, 0o600)
            except Exception:
                pass

        shutil.move(str(temp_dir), str(dest_dir))
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Reload the pack from its new location
    installed_pack = load_pack_manifest(dest_dir)
    if installed_pack:
        installed_pack.builtin = False

    logger.info(f"Installed pack: {pack.name} to {dest_dir}")
    return installed_pack


def save_user_pack(
    pack_id: str, pack_name: str, description: str, processed_images: Dict[str, Any], image_processor
) -> Tuple[bool, str]:
    """
    Save a user-created character pack using atomic operations.

    Creates pack in a temp directory first, then moves atomically
    to avoid partial/corrupt packs on failure.

    Args:
        pack_id: Unique pack identifier (slug)
        pack_name: Human-readable pack name
        description: Pack description
        processed_images: Dict mapping state names to NSImage objects
        image_processor: ImageProcessor instance for saving images

    Returns:
        Tuple of (success, error_message or pack_path)
    """
    import shutil
    import tempfile

    # Validate pack_id
    if not pack_id or not pack_id.replace("-", "").replace("_", "").isalnum():
        return False, "Pack ID must be alphanumeric (dashes and underscores allowed)"

    # Required states
    required_states = ["idle", "recording", "processing", "error"]
    for state in required_states:
        if state not in processed_images or processed_images[state] is None:
            return False, f"Missing required state: {state}"

    # Final destination
    user_dir = _get_user_packs_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(user_dir, 0o700)
    except Exception:
        pass
    pack_dir = user_dir / pack_id

    # Check if pack already exists (early check)
    if pack_dir.exists():
        return False, f"A pack with ID '{pack_id}' already exists"

    # Create in temp directory first for atomicity
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"whisper_pack_{pack_id}_"))
        try:
            os.chmod(temp_dir, 0o700)
        except Exception:
            pass

        # Save each image to temp
        state_files = {}
        for state, image in processed_images.items():
            if image is None:
                continue

            filename = f"{state}.png"
            filepath = temp_dir / filename

            if not image_processor.save_image(image, str(filepath)):
                return False, f"Failed to save image for state: {state}"
            try:
                os.chmod(filepath, 0o600)
            except Exception:
                pass

            state_files[state] = filename

        # Success state falls back to the recording image only when the user
        # did not provide a distinct success image (pack_creator step 5).
        if "success" not in state_files and "recording" in state_files:
            state_files["success"] = state_files["recording"]

        # Create manifest
        manifest = {
            "id": pack_id,
            "name": pack_name,
            "description": description,
            "author": "User Created",
            "version": "1.0.0",
            "states": state_files,
            "settings": {"shape_mode": "alpha", "apply_state_tint": False, "recommended_size": "large"},
        }

        # Write manifest to temp
        manifest_path = temp_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        try:
            os.chmod(manifest_path, 0o600)
        except Exception:
            pass

        # Final check before atomic move (race condition window minimized)
        if pack_dir.exists():
            return False, f"A pack with ID '{pack_id}' already exists"

        # Atomic move from temp to final location
        shutil.move(str(temp_dir), str(pack_dir))
        temp_dir = None  # Moved successfully, don't clean up
        try:
            os.chmod(pack_dir, 0o700)
        except Exception:
            pass

        logger.info(f"Created user pack: {pack_name} at {pack_dir}")
        return True, str(pack_dir)

    except Exception as e:
        logger.error(f"Error creating pack: {e}")
        return False, f"Error creating pack: {str(e)}"

    finally:
        # Clean up temp dir if it still exists (move failed or error)
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def delete_user_pack(pack_id: str) -> Tuple[bool, str]:
    """
    Delete a user-created character pack.

    Args:
        pack_id: The pack ID to delete

    Returns:
        Tuple of (success, error_message)
    """
    import shutil

    pack_dir = _get_safe_user_pack_dir(pack_id)
    if pack_dir is None:
        return False, "Invalid pack ID"

    if not pack_dir.exists():
        return False, f"Pack '{pack_id}' not found"

    try:
        if pack_dir.is_symlink() or pack_dir.is_file():
            pack_dir.unlink()
        else:
            shutil.rmtree(pack_dir)
        logger.info(f"Deleted user pack: {pack_id}")
        return True, ""
    except Exception as e:
        logger.error(f"Error deleting pack {pack_id}: {e}")
        return False, f"Error deleting pack: {str(e)}"


def pack_id_exists(pack_id: str) -> bool:
    """Check if a pack ID already exists."""
    if not _is_valid_pack_id(pack_id):
        return False

    user_dir = _get_user_packs_dir()
    builtin_dir = _get_builtin_packs_dir()

    return (user_dir / pack_id).exists() or (builtin_dir / pack_id).exists()
