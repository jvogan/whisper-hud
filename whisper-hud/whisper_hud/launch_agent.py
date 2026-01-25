"""
Launch at login management for macOS.

Uses launchd Launch Agents to start WhisperHUD at login.
"""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .logging_config import get_logger

logger = get_logger("launch_agent")

BUNDLE_ID = "com.whisper-hud.app"
LAUNCH_AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCH_AGENT_PLIST = LAUNCH_AGENT_DIR / f"{BUNDLE_ID}.plist"


def get_app_executable() -> str:
    """Get the path to the WhisperHUD executable."""
    # Check if running from a .app bundle
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller bundle
        return sys.executable

    # Check if running as installed package
    # Try to find whisper-hud in PATH
    try:
        result = subprocess.run(
            ["which", "whisper-hud"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    # Fallback: use Python to run the module
    return sys.executable


def get_launch_agent_plist() -> dict:
    """Generate the launch agent plist content."""
    executable = get_app_executable()

    # Determine how to launch
    if executable == sys.executable and not hasattr(sys, '_MEIPASS'):
        # Running as Python module
        program_args = [executable, "-m", "whisper_hud"]
    else:
        # Running as standalone executable
        program_args = [executable]

    return {
        "Label": BUNDLE_ID,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
        "StandardOutPath": str(Path.home() / "Library" / "Logs" / "whisper-hud.log"),
        "StandardErrorPath": str(Path.home() / "Library" / "Logs" / "whisper-hud.error.log"),
    }


def is_launch_at_login_enabled() -> bool:
    """Check if launch at login is currently enabled."""
    return LAUNCH_AGENT_PLIST.exists()


def enable_launch_at_login() -> tuple[bool, str]:
    """
    Enable launch at login.

    Returns:
        Tuple of (success, message)
    """
    try:
        # Create LaunchAgents directory if needed
        LAUNCH_AGENT_DIR.mkdir(parents=True, exist_ok=True)

        # Create logs directory
        logs_dir = Path.home() / "Library" / "Logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Write plist file
        plist_content = get_launch_agent_plist()
        with open(LAUNCH_AGENT_PLIST, "wb") as f:
            plistlib.dump(plist_content, f)

        # Load the launch agent
        subprocess.run(
            ["launchctl", "load", str(LAUNCH_AGENT_PLIST)],
            capture_output=True
        )

        logger.info(f"Enabled launch at login: {LAUNCH_AGENT_PLIST}")
        return True, "WhisperHUD will now start at login"

    except Exception as e:
        logger.error(f"Failed to enable launch at login: {e}")
        return False, f"Failed to enable: {str(e)}"


def disable_launch_at_login() -> tuple[bool, str]:
    """
    Disable launch at login.

    Returns:
        Tuple of (success, message)
    """
    try:
        if not LAUNCH_AGENT_PLIST.exists():
            return True, "Launch at login was not enabled"

        # Unload the launch agent
        subprocess.run(
            ["launchctl", "unload", str(LAUNCH_AGENT_PLIST)],
            capture_output=True
        )

        # Remove plist file
        LAUNCH_AGENT_PLIST.unlink()

        logger.info("Disabled launch at login")
        return True, "WhisperHUD will no longer start at login"

    except Exception as e:
        logger.error(f"Failed to disable launch at login: {e}")
        return False, f"Failed to disable: {str(e)}"


def toggle_launch_at_login(enable: bool) -> tuple[bool, str]:
    """
    Toggle launch at login.

    Args:
        enable: True to enable, False to disable

    Returns:
        Tuple of (success, message)
    """
    if enable:
        return enable_launch_at_login()
    else:
        return disable_launch_at_login()
