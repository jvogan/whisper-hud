#!/usr/bin/env python3
"""
Generate Sparkle appcast.xml for WhisperHUD releases.

This script creates the appcast.xml file that Sparkle uses to check for updates.
It can be run manually or as part of the release process.

Usage:
    python scripts/generate-appcast.py <version> <dmg_path>
    python scripts/generate-appcast.py 1.0.0 dist/WhisperHUD-1.0.0.dmg

    # Or auto-detect from dist/
    python scripts/generate-appcast.py

The script will:
1. Calculate the DMG file size and signature
2. Generate appcast.xml with the new release entry
3. Optionally merge with existing appcast.xml to keep history

Requirements:
    - Python 3.8+
    - Optional: openssl for EdDSA signing
"""

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Configuration
GITHUB_REPO = "jvogan/whisper-hud"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
DOWNLOAD_BASE_URL = f"https://github.com/{GITHUB_REPO}/releases/download"
APPCAST_FILENAME = "appcast.xml"
SCRIPT_DIR = Path(__file__).resolve().parent


def get_file_size(path: Path) -> int:
    """Get file size in bytes."""
    return path.stat().st_size


def get_file_sha256(path: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _default_private_key_locations() -> List[Path]:
    """Return trusted default locations for the Sparkle private key."""
    locations: List[Path] = []
    env_key = os.environ.get("SPARKLE_PRIVATE_KEY_PATH")
    if env_key:
        locations.append(Path(env_key).expanduser())
    locations.append(Path.home() / ".sparkle" / "eddsa_private.key")
    locations.append(SCRIPT_DIR.parent / "keys" / "eddsa_private.key")
    return locations


def sign_file_eddsa(path: Path, private_key_path: Optional[Path] = None) -> Optional[str]:
    """
    Sign a file with EdDSA for Sparkle 2.x.

    Returns the base64-encoded signature or None if signing fails.
    """
    if private_key_path is None:
        # Look for key in trusted locations.
        for key_loc in _default_private_key_locations():
            if key_loc.exists():
                private_key_path = key_loc
                break

    if private_key_path is None or not private_key_path.exists():
        print("Warning: EdDSA private key not found. Update will not be signed.")
        print("  To generate a key: ./scripts/generate-sparkle-keys.sh")
        return None

    try:
        # Sign using openssl
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(private_key_path),
                "-in",
                str(path),
            ],
            capture_output=True,
            check=True,
        )
        import base64

        return base64.b64encode(result.stdout).decode("ascii")
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to sign file: {e}")
        return None
    except FileNotFoundError:
        print("Warning: openssl not found, cannot sign update")
        return None


def create_release_notes_html(version: str, changes: Optional[str] = None) -> str:
    """Create HTML release notes."""
    if changes:
        notes = f"<h2>WhisperHUD {version}</h2>\n<ul>\n"
        for line in changes.strip().split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                line = line[1:].strip()
            if line:
                notes += f"  <li>{line}</li>\n"
        notes += "</ul>"
    else:
        notes = f"<h2>WhisperHUD {version}</h2>\n<p>Bug fixes and improvements.</p>"

    return notes


def get_changelog_for_version(version: str) -> Optional[str]:
    """Extract changelog entry for a specific version from CHANGELOG.md."""
    changelog_path = Path(__file__).parent.parent / "CHANGELOG.md"

    if not changelog_path.exists():
        return None

    with open(changelog_path, "r") as f:
        content = f.read()

    # Find section for this version
    import re

    pattern = rf"##\s*\[?{re.escape(version)}\]?.*?\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        return match.group(1).strip()

    return None


def create_appcast_item(
    version: str,
    dmg_path: Path,
    signature: Optional[str] = None,
    min_os_version: str = "12.0",
    changes: Optional[str] = None,
) -> ET.Element:
    """Create an appcast item element for a release."""
    item = ET.Element("item")

    # Title
    title = ET.SubElement(item, "title")
    title.text = f"WhisperHUD {version}"

    # Publication date
    pub_date = ET.SubElement(item, "pubDate")
    pub_date.text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

    # Release notes (as CDATA in description)
    description = ET.SubElement(item, "description")
    notes = create_release_notes_html(version, changes)
    description.text = notes

    # Sparkle-specific elements
    sparkle_ns = "http://www.andymatuschak.org/xml-namespaces/sparkle"

    # Version
    ET.SubElement(item, f"{{{sparkle_ns}}}version").text = version
    ET.SubElement(item, f"{{{sparkle_ns}}}shortVersionString").text = version

    # Minimum OS version
    ET.SubElement(item, f"{{{sparkle_ns}}}minimumSystemVersion").text = min_os_version

    # Enclosure (the download)
    download_url = f"{DOWNLOAD_BASE_URL}/v{version}/{dmg_path.name}"
    enclosure = ET.SubElement(item, "enclosure")
    enclosure.set("url", download_url)
    enclosure.set("length", str(get_file_size(dmg_path)))
    enclosure.set("type", "application/octet-stream")

    # EdDSA signature
    if signature:
        enclosure.set(f"{{{sparkle_ns}}}edSignature", signature)

    return item


def create_appcast(items: List[ET.Element]) -> ET.Element:
    """Create the complete appcast XML structure."""
    # Register Sparkle namespace
    sparkle_ns = "http://www.andymatuschak.org/xml-namespaces/sparkle"
    ET.register_namespace("sparkle", sparkle_ns)

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
            f"xmlns:sparkle": sparkle_ns,
            "xmlns:dc": "http://purl.org/dc/elements/1.1/",
        },
    )

    channel = ET.SubElement(rss, "channel")

    # Channel metadata
    title = ET.SubElement(channel, "title")
    title.text = "WhisperHUD Updates"

    link = ET.SubElement(channel, "link")
    link.text = f"https://github.com/{GITHUB_REPO}"

    description = ET.SubElement(channel, "description")
    description.text = "Voice-to-text transcription for macOS"

    language = ET.SubElement(channel, "language")
    language.text = "en"

    # Add items (releases)
    for item in items:
        channel.append(item)

    return rss


def prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string."""
    rough_string = ET.tostring(elem, encoding="unicode")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")


def load_existing_appcast(path: Path) -> List[ET.Element]:
    """Load items from an existing appcast.xml."""
    if not path.exists():
        return []

    try:
        tree = ET.parse(path)
        root = tree.getroot()
        channel = root.find("channel")
        if channel is not None:
            return list(channel.findall("item"))
    except Exception as e:
        print(f"Warning: Could not parse existing appcast: {e}")

    return []


def find_latest_dmg(dist_dir: Path) -> Optional[Path]:
    """Find the latest DMG file in the dist directory."""
    dmg_files = list(dist_dir.glob("WhisperHUD-*.dmg"))
    if not dmg_files:
        dmg_files = list(dist_dir.glob("*.dmg"))

    if not dmg_files:
        return None

    # Sort by modification time, newest first
    dmg_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dmg_files[0]


def extract_version_from_dmg(dmg_path: Path) -> Optional[str]:
    """Extract version from DMG filename (e.g., WhisperHUD-1.0.0.dmg -> 1.0.0)."""
    import re

    match = re.search(r"(\d+\.\d+\.\d+)", dmg_path.name)
    if match:
        return match.group(1)
    return None


def main():
    parser = argparse.ArgumentParser(description="Generate Sparkle appcast.xml for WhisperHUD")
    parser.add_argument(
        "version", nargs="?", help="Version number (e.g., 1.0.0). Auto-detected from DMG filename if not provided."
    )
    parser.add_argument("dmg_path", nargs="?", help="Path to DMG file. Auto-detected from dist/ if not provided.")
    parser.add_argument(
        "--output", "-o", default="dist/appcast.xml", help="Output path for appcast.xml (default: dist/appcast.xml)"
    )
    parser.add_argument("--key", "-k", help="Path to EdDSA private key for signing")
    parser.add_argument("--min-os", default="12.0", help="Minimum macOS version (default: 12.0)")
    parser.add_argument(
        "--keep-history", action="store_true", help="Merge with existing appcast.xml to keep release history"
    )

    args = parser.parse_args()

    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    dist_dir = project_root / "dist"

    # Auto-detect DMG if not provided
    dmg_path = Path(args.dmg_path) if args.dmg_path else find_latest_dmg(dist_dir)
    if dmg_path is None or not dmg_path.exists():
        print("Error: No DMG file found. Build the app first with:")
        print("  make dmg")
        sys.exit(1)

    print(f"Using DMG: {dmg_path}")

    # Auto-detect version if not provided
    version = args.version or extract_version_from_dmg(dmg_path)
    if version is None:
        print("Error: Could not determine version. Please provide it as an argument.")
        sys.exit(1)

    print(f"Version: {version}")

    # Sign the DMG
    key_path = Path(args.key) if args.key else None
    signature = sign_file_eddsa(dmg_path, key_path)

    # Get changelog
    changes = get_changelog_for_version(version)
    if changes:
        print(f"Found changelog entry for v{version}")

    # Create the new item
    new_item = create_appcast_item(
        version=version,
        dmg_path=dmg_path,
        signature=signature,
        min_os_version=args.min_os,
        changes=changes,
    )

    # Load existing items if keeping history
    items = []
    output_path = Path(args.output)
    if args.keep_history and output_path.exists():
        items = load_existing_appcast(output_path)
        # Remove any existing item with same version
        items = [i for i in items if i.find("title").text != f"WhisperHUD {version}"]

    # Add new item at the beginning
    items.insert(0, new_item)

    # Create appcast
    rss = create_appcast(items)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    xml_content = prettify_xml(rss)
    with open(output_path, "w") as f:
        f.write(xml_content)

    print(f"\nGenerated: {output_path}")
    print(f"  Size: {get_file_size(dmg_path):,} bytes")
    print(f"  SHA256: {get_file_sha256(dmg_path)}")
    if signature:
        print(f"  EdDSA signature: {signature[:32]}...")
    print(f"\nUpload {dmg_path.name} and {output_path.name} to GitHub Releases.")


if __name__ == "__main__":
    main()
