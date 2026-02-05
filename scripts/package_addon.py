#!/usr/bin/env python3
"""
Package the Blender MCP addon as a ZIP file for distribution.

Usage:
    python scripts/package_addon.py [--output OUTPUT_PATH]
"""

import argparse
import os
import shutil
import zipfile
from pathlib import Path


def get_version():
    """Get addon version from __init__.py."""
    init_path = Path(__file__).parent.parent / "addon" / "blender_mcp_addon" / "__init__.py"
    with open(init_path) as f:
        for line in f:
            if '"version":' in line:
                # Extract version tuple from line like: "version": (0, 1, 0),
                import re
                match = re.search(r'\((\d+),\s*(\d+),\s*(\d+)\)', line)
                if match:
                    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    return "0.0.0"


def package_addon(output_path: str | None = None):
    """Create a ZIP file of the addon."""
    project_root = Path(__file__).parent.parent
    addon_dir = project_root / "addon" / "blender_mcp_addon"

    if not addon_dir.exists():
        print(f"ERROR: Addon directory not found: {addon_dir}")
        return False

    version = get_version()

    if output_path is None:
        dist_dir = project_root / "dist"
        dist_dir.mkdir(exist_ok=True)
        output_path = dist_dir / f"blender_mcp_addon-{version}.zip"
    else:
        output_path = Path(output_path)

    print(f"Packaging addon version {version}")
    print(f"Output: {output_path}")

    # Files to exclude
    exclude_patterns = {
        "__pycache__",
        "*.pyc",
        "*.pyo",
        ".DS_Store",
        "*.egg-info",
        ".git",
    }

    def should_exclude(path: Path) -> bool:
        """Check if a path should be excluded."""
        for pattern in exclude_patterns:
            if pattern.startswith("*"):
                if path.name.endswith(pattern[1:]):
                    return True
            elif pattern in path.parts:
                return True
        return False

    # Create ZIP file
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(addon_dir):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d)]

            for file in files:
                file_path = Path(root) / file
                if should_exclude(file_path):
                    continue

                # Archive path preserves the addon directory structure
                arc_name = Path("blender_mcp_addon") / file_path.relative_to(addon_dir)
                zf.write(file_path, arc_name)
                print(f"  Added: {arc_name}")

    print(f"\nSuccessfully created: {output_path}")
    print(f"Size: {output_path.stat().st_size / 1024:.1f} KB")

    return True


def main():
    parser = argparse.ArgumentParser(description="Package Blender MCP addon")
    parser.add_argument(
        "--output", "-o",
        help="Output ZIP file path (default: dist/blender_mcp_addon-VERSION.zip)",
    )
    args = parser.parse_args()

    success = package_addon(args.output)
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
