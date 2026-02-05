"""Livery export and packaging tools for MSFS."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import bpy

from .templates import SUPPORTED_AIRCRAFT

# MSFS livery package structure
PACKAGE_STRUCTURE = {
    "texture": "SimObjects/Airplanes/{aircraft}/TEXTURE.{livery_name}",
    "aircraft_cfg": "SimObjects/Airplanes/{aircraft}/aircraft.cfg",
    "manifest": "manifest.json",
    "layout": "layout.json",
}

# DDS format settings for MSFS
DDS_SETTINGS = {
    "albedo": {
        "format": "BC7_UNORM",
        "description": "Base color/albedo texture",
        "suffix": "_ALBD",
    },
    "normal": {
        "format": "BC5_UNORM",
        "description": "Normal map",
        "suffix": "_NORM",
    },
    "composite": {
        "format": "BC7_UNORM",
        "description": "Metallic/Roughness/AO composite",
        "suffix": "_COMP",
    },
    "emissive": {
        "format": "BC7_UNORM",
        "description": "Emissive texture",
        "suffix": "_EMIS",
    },
}


def export_livery_textures(
    object_name: str,
    output_dir: str,
    texture_types: list[str] | None = None,
    format: str = "PNG",
) -> dict[str, Any]:
    """Export livery textures from an object.

    Args:
        object_name: Name of the object with livery materials
        output_dir: Directory to save exported textures
        texture_types: Types to export (albedo, normal, composite, emissive)
        format: Output format (PNG, TARGA, or DDS if converter available)

    Returns:
        Dictionary with export results
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if texture_types is None:
        texture_types = ["albedo"]

    exported = []

    # Find all images associated with the object's materials
    for mat_slot in obj.material_slots:
        mat = mat_slot.material
        if not mat or not mat.use_nodes:
            continue

        for node in mat.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue

            img = node.image

            # Determine texture type from node name or connections
            tex_type = _determine_texture_type(node, mat)
            if tex_type not in texture_types:
                continue

            # Generate filename
            suffix = DDS_SETTINGS.get(tex_type, {}).get("suffix", "")
            filename = f"{object_name}{suffix}.{format.lower()}"
            filepath = output_path / filename

            # Save image
            img.filepath_raw = str(filepath)
            img.file_format = format
            img.save()

            exported.append({
                "type": tex_type,
                "filepath": str(filepath),
                "size": list(img.size),
                "format": format,
            })

    # Also export any layer images created by painting workflow
    layer_prefix = f"{object_name}_layer_"
    for img in bpy.data.images:
        if img.name.startswith(layer_prefix):
            layer_name = img.name[len(layer_prefix):]
            filename = f"{object_name}_layer_{layer_name}.{format.lower()}"
            filepath = output_path / filename

            img.filepath_raw = str(filepath)
            img.file_format = format
            img.save()

            exported.append({
                "type": f"layer_{layer_name}",
                "filepath": str(filepath),
                "size": list(img.size),
                "format": format,
            })

    return {
        "object": object_name,
        "output_dir": str(output_path),
        "exported": exported,
        "count": len(exported),
    }


def _determine_texture_type(node: bpy.types.Node, material: bpy.types.Material) -> str:
    """Determine texture type from node context."""
    # Check node name/label
    name_lower = node.name.lower() + node.label.lower()
    if any(x in name_lower for x in ["albedo", "albd", "base", "diffuse", "color"]):
        return "albedo"
    if any(x in name_lower for x in ["normal", "norm", "nrm"]):
        return "normal"
    if any(x in name_lower for x in ["composite", "comp", "orm", "metal", "rough"]):
        return "composite"
    if any(x in name_lower for x in ["emissive", "emis", "glow"]):
        return "emissive"

    # Check what the node is connected to
    for output in node.outputs:
        for link in output.links:
            input_name = link.to_socket.name.lower()
            if "color" in input_name or "base" in input_name:
                return "albedo"
            if "normal" in input_name:
                return "normal"
            if "metallic" in input_name or "roughness" in input_name:
                return "composite"
            if "emission" in input_name:
                return "emissive"

    return "albedo"  # Default


def convert_to_dds(
    input_path: str,
    output_path: str | None = None,
    texture_type: str = "albedo",
) -> dict[str, Any]:
    """Convert texture to DDS format for MSFS.

    Requires texconv.exe (Windows) or similar tool to be available.

    Args:
        input_path: Path to input image
        output_path: Path for output DDS (default: same location with .dds extension)
        texture_type: Type of texture for format selection (albedo, normal, composite)

    Returns:
        Dictionary with conversion results
    """
    input_file = Path(input_path)
    if not input_file.exists():
        return {"error": f"Input file not found: {input_path}"}

    if output_path is None:
        output_file = input_file.with_suffix(".dds")
    else:
        output_file = Path(output_path)

    dds_format = DDS_SETTINGS.get(texture_type, DDS_SETTINGS["albedo"])["format"]

    # Try to find texconv
    texconv_paths = [
        "texconv",
        "texconv.exe",
        Path.home() / "texconv" / "texconv.exe",
        Path("C:/texconv/texconv.exe"),
    ]

    texconv = None
    for path in texconv_paths:
        if shutil.which(str(path)):
            texconv = str(path)
            break

    if texconv is None:
        return {
            "error": "texconv not found. Install from: "
            "https://github.com/Microsoft/DirectXTex/releases",
            "manual_conversion": {
                "input": str(input_file),
                "output": str(output_file),
                "format": dds_format,
                "command": f"texconv -f {dds_format} -o {output_file.parent} {input_file}",
            },
        }

    # Run texconv
    try:
        result = subprocess.run(
            [
                texconv,
                "-f", dds_format,
                "-o", str(output_file.parent),
                "-y",  # Overwrite
                str(input_file),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return {
                "error": f"texconv failed: {result.stderr}",
                "stdout": result.stdout,
            }

        return {
            "input": str(input_file),
            "output": str(output_file),
            "format": dds_format,
            "texture_type": texture_type,
        }

    except subprocess.TimeoutExpired:
        return {"error": "texconv timed out"}
    except FileNotFoundError:
        return {"error": f"Could not execute texconv at: {texconv}"}


def create_livery_package(
    aircraft_id: str,
    livery_name: str,
    output_dir: str,
    texture_dir: str | None = None,
    airline: str = "",
    description: str = "",
    author: str = "",
) -> dict[str, Any]:
    """Create MSFS livery package folder structure.

    Args:
        aircraft_id: Aircraft identifier (e.g., 'fbw_a32nx', 'pmdg_737')
        livery_name: Name for the livery (used in folder names)
        output_dir: Base directory for the package
        texture_dir: Directory containing texture files to include
        airline: Airline name for aircraft.cfg
        description: Livery description
        author: Author name

    Returns:
        Dictionary with package creation results
    """
    if aircraft_id not in SUPPORTED_AIRCRAFT:
        return {
            "error": f"Unknown aircraft: {aircraft_id}",
            "available": list(SUPPORTED_AIRCRAFT.keys()),
        }

    aircraft_info = SUPPORTED_AIRCRAFT[aircraft_id]
    output_path = Path(output_dir)

    # Sanitize livery name for folder
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in livery_name)

    # Create package structure
    package_name = f"{aircraft_id}-livery-{safe_name}"
    package_path = output_path / package_name

    # Determine aircraft folder name based on aircraft type
    aircraft_folder = _get_aircraft_folder(aircraft_id)
    texture_folder = package_path / "SimObjects" / "Airplanes" / aircraft_folder / f"TEXTURE.{safe_name}"

    texture_folder.mkdir(parents=True, exist_ok=True)

    created_files = []

    # Copy textures if provided
    if texture_dir:
        tex_source = Path(texture_dir)
        if tex_source.exists():
            for tex_file in tex_source.glob("*"):
                if tex_file.suffix.lower() in [".png", ".dds", ".tga", ".jpg"]:
                    dest = texture_folder / tex_file.name
                    shutil.copy2(tex_file, dest)
                    created_files.append(str(dest))

    # Create manifest.json
    manifest = {
        "dependencies": [],
        "content_type": "LIVERY",
        "title": f"{airline} {aircraft_info['name']}" if airline else f"{livery_name} Livery",
        "manufacturer": author or "Custom",
        "creator": author or "MCP Blender",
        "package_version": "1.0.0",
        "minimum_game_version": "1.12.13.0",
        "release_notes": {
            "neutral": {
                "LastUpdate": "",
                "OlderHistory": "",
            }
        },
    }

    manifest_path = package_path / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    created_files.append(str(manifest_path))

    # Create layout.json
    layout = {"content": []}

    # Add all files to layout
    for file_path in package_path.rglob("*"):
        if file_path.is_file() and file_path.name != "layout.json":
            rel_path = file_path.relative_to(package_path)
            layout["content"].append({
                "path": str(rel_path).replace("\\", "/"),
                "size": file_path.stat().st_size,
                "date": int(file_path.stat().st_mtime),
            })

    layout_path = package_path / "layout.json"
    with open(layout_path, "w") as f:
        json.dump(layout, f, indent=2)
    created_files.append(str(layout_path))

    # Create aircraft.cfg snippet
    cfg_content = _generate_aircraft_cfg(
        aircraft_id=aircraft_id,
        livery_name=safe_name,
        airline=airline,
        description=description,
    )

    cfg_path = package_path / "aircraft.cfg.snippet"
    with open(cfg_path, "w") as f:
        f.write(cfg_content)
    created_files.append(str(cfg_path))

    return {
        "package_path": str(package_path),
        "aircraft": aircraft_id,
        "livery_name": safe_name,
        "texture_folder": str(texture_folder),
        "created_files": created_files,
        "next_steps": [
            "Add DDS textures to texture folder",
            "Merge aircraft.cfg.snippet into base aircraft.cfg",
            "Update layout.json with final file sizes",
            "Copy package to Community folder",
        ],
    }


def _get_aircraft_folder(aircraft_id: str) -> str:
    """Get the aircraft folder name for a given aircraft ID."""
    folder_names = {
        "fbw_a32nx": "FlyByWire_A320_NEO",
        "fenix_a320": "Fenix_A320",
        "pmdg_737": "PMDG_737",
        "pmdg_777": "PMDG_777",
        "ini_a310": "iniSimulations_A310",
        "ini_a320neo": "iniSimulations_A320neo",
        "aerosoft_crj": "Aerosoft_CRJ",
        "justflight_bae146": "JustFlight_BAe146",
        "leonardo_md80": "Leonardo_MD80",
        "generic": "Custom_Aircraft",
    }
    return folder_names.get(aircraft_id, aircraft_id)


def _generate_aircraft_cfg(
    aircraft_id: str,
    livery_name: str,
    airline: str,
    description: str,
) -> str:
    """Generate aircraft.cfg snippet for a livery."""
    aircraft_info = SUPPORTED_AIRCRAFT.get(aircraft_id, {})
    aircraft_name = aircraft_info.get("name", "Aircraft")

    cfg = f"""; {airline or livery_name} Livery
; Add this section to your aircraft.cfg

[FLTSIM.XX]  ; Replace XX with next available number
title = "{airline} {aircraft_name}" ; {livery_name}
description = "{description or f'{airline} livery for {aircraft_name}'}"
ui_variation = "{livery_name}"
ui_typerole = "Commercial Airliner"
ui_createdby = "MCP Blender"
texture = "TEXTURE.{livery_name}"

; Copy the TEXTURE.{livery_name} folder to your aircraft's directory
"""
    return cfg


def validate_livery_package(package_dir: str) -> dict[str, Any]:
    """Validate a livery package structure.

    Args:
        package_dir: Path to the livery package

    Returns:
        Dictionary with validation results
    """
    package_path = Path(package_dir)
    if not package_path.exists():
        return {"error": f"Package directory not found: {package_dir}"}

    issues = []
    warnings = []
    valid_files = []

    # Check manifest.json
    manifest_path = package_path / "manifest.json"
    if manifest_path.exists():
        valid_files.append("manifest.json")
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)

            required_fields = ["title", "content_type", "package_version"]
            for field in required_fields:
                if field not in manifest:
                    issues.append(f"manifest.json missing required field: {field}")

            if manifest.get("content_type") != "LIVERY":
                warnings.append("content_type should be 'LIVERY' for livery packages")

        except json.JSONDecodeError as e:
            issues.append(f"manifest.json is not valid JSON: {e}")
    else:
        issues.append("Missing manifest.json")

    # Check layout.json
    layout_path = package_path / "layout.json"
    if layout_path.exists():
        valid_files.append("layout.json")
        try:
            with open(layout_path) as f:
                layout = json.load(f)

            if "content" not in layout:
                issues.append("layout.json missing 'content' array")
            else:
                # Verify all listed files exist
                for item in layout["content"]:
                    file_path = package_path / item["path"]
                    if not file_path.exists():
                        issues.append(f"layout.json references missing file: {item['path']}")

        except json.JSONDecodeError as e:
            issues.append(f"layout.json is not valid JSON: {e}")
    else:
        issues.append("Missing layout.json")

    # Check for texture folder
    texture_folders = list(package_path.rglob("TEXTURE.*"))
    if not texture_folders:
        issues.append("No TEXTURE.* folder found")
    else:
        for tex_folder in texture_folders:
            valid_files.append(str(tex_folder.relative_to(package_path)))

            # Check for required textures
            dds_files = list(tex_folder.glob("*.dds"))
            png_files = list(tex_folder.glob("*.png"))

            if not dds_files and not png_files:
                warnings.append(f"No texture files found in {tex_folder.name}")
            elif not dds_files:
                warnings.append(
                    f"No DDS files in {tex_folder.name}. "
                    "MSFS prefers DDS format for performance."
                )

    # Check texture sizes
    for tex_folder in texture_folders:
        for img_file in tex_folder.glob("*"):
            if img_file.suffix.lower() in [".png", ".dds", ".tga"]:
                # For PNG files, we can check dimensions
                if img_file.suffix.lower() == ".png":
                    try:
                        img = bpy.data.images.load(str(img_file))
                        w, h = img.size
                        bpy.data.images.remove(img)

                        # Check power of 2
                        if not (w & (w - 1) == 0 and w != 0):
                            warnings.append(
                                f"{img_file.name}: width {w} is not power of 2"
                            )
                        if not (h & (h - 1) == 0 and h != 0):
                            warnings.append(
                                f"{img_file.name}: height {h} is not power of 2"
                            )
                    except Exception:
                        pass  # Can't verify image

    is_valid = len(issues) == 0

    return {
        "valid": is_valid,
        "package_path": str(package_path),
        "valid_files": valid_files,
        "issues": issues,
        "warnings": warnings,
        "summary": (
            "Package is valid" if is_valid
            else f"Package has {len(issues)} issue(s)"
        ),
    }
