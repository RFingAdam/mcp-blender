"""Aircraft template definitions and management for livery painting."""

from pathlib import Path
from typing import Any

import bpy

# Supported aircraft with template information
SUPPORTED_AIRCRAFT = {
    # FlyByWire
    "fbw_a32nx": {
        "name": "FlyByWire A32NX",
        "developer": "FlyByWire Simulations",
        "variants": ["A320neo", "A321neo"],
        "texture_size": (4096, 4096),
        "textures": {
            "fuselage": "A320_NEO_LIVERY_FUSELAGE_ALBD.png",
            "wings": "A320_NEO_LIVERY_WING_ALBD.png",
            "tail": "A320_NEO_LIVERY_TAIL_ALBD.png",
            "engines": "A320_NEO_LIVERY_ENGINE_ALBD.png",
        },
        "template_url": "https://github.com/flybywiresim/aircraft/wiki/Livery-Guide",
        "has_public_template": True,
        "uv_regions": {
            "fuselage_left": {"x": 0, "y": 0, "w": 2048, "h": 4096},
            "fuselage_right": {"x": 2048, "y": 0, "w": 2048, "h": 4096},
            "nose": {"x": 0, "y": 3072, "w": 1024, "h": 1024},
            "tail": {"x": 1024, "y": 3072, "w": 1024, "h": 1024},
        },
    },
    # Fenix
    "fenix_a320": {
        "name": "Fenix A320",
        "developer": "Fenix Simulations",
        "variants": ["A319", "A320", "A321"],
        "texture_size": (8192, 8192),
        "textures": {
            "fuselage": "FUSELAGE_ALBD.png",
            "wings": "WING_ALBD.png",
            "tail": "VSTAB_ALBD.png",
            "engines": "ENGINE_ALBD.png",
        },
        "template_url": None,  # Payware - no public template
        "has_public_template": False,
        "notes": "Extract UV from model or use community templates",
    },
    # PMDG
    "pmdg_737": {
        "name": "PMDG 737",
        "developer": "PMDG",
        "variants": ["737-600", "737-700", "737-800", "737-900"],
        "texture_size": (4096, 4096),
        "textures": {
            "fuselage": "B737_FUSELAGE_ALBD.png",
            "wings": "B737_WING_ALBD.png",
            "tail": "B737_TAIL_ALBD.png",
            "engines": "B737_ENGINE_ALBD.png",
        },
        "template_url": None,
        "has_public_template": False,
        "paint_kit_available": True,
    },
    "pmdg_777": {
        "name": "PMDG 777",
        "developer": "PMDG",
        "variants": ["777-200LR", "777-300ER", "777F"],
        "texture_size": (4096, 4096),
        "textures": {
            "fuselage": "B777_FUSELAGE_ALBD.png",
            "wings": "B777_WING_ALBD.png",
            "tail": "B777_TAIL_ALBD.png",
            "engines": "B777_ENGINE_ALBD.png",
        },
        "template_url": None,
        "has_public_template": False,
        "paint_kit_available": True,
    },
    # iniBuilds
    "ini_a310": {
        "name": "iniBuilds A310",
        "developer": "iniBuilds",
        "variants": ["A310-300"],
        "texture_size": (4096, 4096),
        "textures": {
            "fuselage": "A310_FUSELAGE_ALBD.png",
            "wings": "A310_WING_ALBD.png",
            "tail": "A310_TAIL_ALBD.png",
        },
        "template_url": "https://inibuilds.com/resources",
        "has_public_template": True,
    },
    "ini_a320neo": {
        "name": "iniBuilds A320neo",
        "developer": "iniBuilds",
        "variants": ["A320neo"],
        "texture_size": (4096, 4096),
        "textures": {
            "fuselage": "A320N_FUSELAGE_ALBD.png",
        },
        "has_public_template": True,
    },
    # Leonardo / Maddog
    "leonardo_md80": {
        "name": "Leonardo MD-80",
        "developer": "Leonardo Software",
        "variants": ["MD-82", "MD-83", "MD-88"],
        "texture_size": (4096, 4096),
        "has_public_template": False,
    },
    # Aerosoft
    "aerosoft_crj": {
        "name": "Aerosoft CRJ",
        "developer": "Aerosoft",
        "variants": ["CRJ-550", "CRJ-700", "CRJ-900", "CRJ-1000"],
        "texture_size": (4096, 4096),
        "has_public_template": True,
        "template_url": "https://aerosoft.com",
    },
    # Just Flight
    "justflight_bae146": {
        "name": "Just Flight BAe 146",
        "developer": "Just Flight",
        "variants": ["146-100", "146-200", "146-300"],
        "texture_size": (4096, 4096),
        "has_public_template": True,
    },
    # Generic template for custom aircraft
    "generic": {
        "name": "Generic Aircraft",
        "developer": "Custom",
        "texture_size": (4096, 4096),
        "textures": {
            "fuselage": "FUSELAGE_ALBD.png",
            "wings": "WING_ALBD.png",
            "tail": "TAIL_ALBD.png",
            "engines": "ENGINE_ALBD.png",
        },
        "has_public_template": True,
        "notes": "Generic template - adjust UV regions as needed",
    },
}

# Common livery design elements
LIVERY_ELEMENTS = {
    "cheatline": {
        "description": "Horizontal stripe along fuselage windows",
        "typical_location": "fuselage_side",
    },
    "belly": {
        "description": "Underside of fuselage, often gray/white",
        "typical_location": "fuselage_bottom",
    },
    "tail_logo": {
        "description": "Airline logo on vertical stabilizer",
        "typical_location": "tail",
    },
    "engine_nacelle": {
        "description": "Engine housing livery",
        "typical_location": "engines",
    },
    "winglet": {
        "description": "Wing tip device livery",
        "typical_location": "wings",
    },
    "registration": {
        "description": "Aircraft registration number",
        "typical_location": "fuselage_rear",
    },
    "titles": {
        "description": "Airline name text",
        "typical_location": "fuselage_front",
    },
    "flag": {
        "description": "National flag, often near tail",
        "typical_location": "fuselage_rear",
    },
}


def get_aircraft_templates() -> dict[str, Any]:
    """Get list of all supported aircraft templates.

    Returns:
        Dictionary with aircraft template information
    """
    templates = []
    for aircraft_id, info in SUPPORTED_AIRCRAFT.items():
        templates.append({
            "id": aircraft_id,
            "name": info["name"],
            "developer": info.get("developer", "Unknown"),
            "has_public_template": info.get("has_public_template", False),
            "variants": info.get("variants", []),
        })

    return {
        "aircraft": templates,
        "count": len(templates),
        "elements": list(LIVERY_ELEMENTS.keys()),
    }


def get_template_info(aircraft_id: str) -> dict[str, Any]:
    """Get detailed template information for an aircraft.

    Args:
        aircraft_id: Aircraft identifier (e.g., 'fbw_a32nx', 'pmdg_737')

    Returns:
        Dictionary with detailed template information
    """
    if aircraft_id not in SUPPORTED_AIRCRAFT:
        return {
            "error": f"Unknown aircraft: {aircraft_id}",
            "available": list(SUPPORTED_AIRCRAFT.keys()),
        }

    info = SUPPORTED_AIRCRAFT[aircraft_id].copy()
    info["id"] = aircraft_id

    return info


def download_template(
    aircraft_id: str,
    output_dir: str,
) -> dict[str, Any]:
    """Download or generate template files for an aircraft.

    For aircraft with public templates, provides download instructions.
    For others, can extract UV layout from loaded model.

    Args:
        aircraft_id: Aircraft identifier
        output_dir: Directory to save template files

    Returns:
        Dictionary with download/generation results
    """
    if aircraft_id not in SUPPORTED_AIRCRAFT:
        return {
            "error": f"Unknown aircraft: {aircraft_id}",
            "available": list(SUPPORTED_AIRCRAFT.keys()),
        }

    info = SUPPORTED_AIRCRAFT[aircraft_id]
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    result = {
        "aircraft": aircraft_id,
        "name": info["name"],
        "output_dir": str(output_path),
    }

    if info.get("has_public_template") and info.get("template_url"):
        result["template_url"] = info["template_url"]
        result["instructions"] = f"Download template from: {info['template_url']}"
    else:
        # Try to extract UV from currently loaded model
        result["instructions"] = (
            "No public template available. "
            "Load the aircraft model and use export_uv_layout to extract UV mapping."
        )

    # Generate blank template files at correct resolution
    if "texture_size" in info:
        width, height = info["texture_size"]
        result["texture_size"] = [width, height]
        result["generated_blanks"] = []

        textures = info.get("textures", {"fuselage": "FUSELAGE_ALBD.png"})
        for tex_type, filename in textures.items():
            # Create blank image at correct resolution
            img_name = f"{aircraft_id}_{tex_type}_template"
            if img_name not in bpy.data.images:
                img = bpy.data.images.new(
                    name=img_name,
                    width=width,
                    height=height,
                    alpha=True,
                )
                img.generated_color = (1, 1, 1, 1)  # White background

                # Save to output directory
                filepath = output_path / f"{tex_type}_template.png"
                img.filepath_raw = str(filepath)
                img.file_format = "PNG"
                img.save()

                result["generated_blanks"].append({
                    "type": tex_type,
                    "filepath": str(filepath),
                    "size": [width, height],
                })

    return result


def get_uv_regions(aircraft_id: str) -> dict[str, Any]:
    """Get UV region mapping for an aircraft.

    Args:
        aircraft_id: Aircraft identifier

    Returns:
        Dictionary with UV region definitions
    """
    if aircraft_id not in SUPPORTED_AIRCRAFT:
        return {"error": f"Unknown aircraft: {aircraft_id}"}

    info = SUPPORTED_AIRCRAFT[aircraft_id]

    if "uv_regions" in info:
        return {
            "aircraft": aircraft_id,
            "regions": info["uv_regions"],
            "texture_size": info.get("texture_size", [4096, 4096]),
        }
    else:
        return {
            "aircraft": aircraft_id,
            "regions": None,
            "note": "UV regions not defined. Use export_uv_layout to extract from model.",
        }
