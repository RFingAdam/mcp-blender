#!/usr/bin/env python3
"""
Package the Meshwire add-on as a Blender extension ZIP.

Blender installs the ZIP from Edit > Preferences > Get Extensions > Install from Disk. The
manifest and the package files sit at the root of the ZIP.

Usage:
    python scripts/package_addon.py [--output OUTPUT_PATH]
"""

import argparse
import os
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, which only unit tests run on
    import tomli as tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = PROJECT_ROOT / "addon" / "blender_mcp_addon"


def get_version() -> str:
    """The add-on version, read from the extension manifest."""
    manifest = tomllib.loads((ADDON_DIR / "blender_manifest.toml").read_text(encoding="utf-8"))
    return manifest["version"]


def _excluded(name: str) -> bool:
    return (
        name.startswith(".")
        or name == "__pycache__"
        or name.endswith((".pyc", ".pyo"))
        or name.endswith(".egg-info")
    )


def package_addon(output_path: str | Path | None = None) -> bool:
    """Create the extension ZIP."""
    if not ADDON_DIR.exists():
        print(f"ERROR: Addon directory not found: {ADDON_DIR}")
        return False

    version = get_version()

    if output_path is None:
        dist_dir = PROJECT_ROOT / "dist"
        dist_dir.mkdir(exist_ok=True)
        output_path = dist_dir / f"meshwire-addon-{version}.zip"
    else:
        output_path = Path(output_path)

    print(f"Packaging addon version {version}")
    print(f"Output: {output_path}")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ADDON_DIR):
            dirs[:] = sorted(d for d in dirs if not _excluded(d))
            for file in sorted(files):
                if _excluded(file):
                    continue
                file_path = Path(root) / file
                arc_name = file_path.relative_to(ADDON_DIR)
                zf.write(file_path, arc_name)
                print(f"  Added: {arc_name}")

    print(f"\nSuccessfully created: {output_path}")
    print(f"Size: {output_path.stat().st_size / 1024:.1f} KB")

    return True


def main():
    parser = argparse.ArgumentParser(description="Package the Meshwire addon")
    parser.add_argument(
        "--output",
        "-o",
        help="Output ZIP file path (default: dist/meshwire-addon-VERSION.zip)",
    )
    args = parser.parse_args()

    success = package_addon(args.output)
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
