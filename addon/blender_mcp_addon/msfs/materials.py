"""MSFS-specific material setup and extensions."""

from typing import Any

import bpy

# MSFS material type tags (stored as custom properties, exported to glTF extras)
MSFS_MATERIAL_TYPES = {
    "standard": "ASOBO_material_standard",
    "windshield": "ASOBO_material_windshield",
    "clear_coat": "ASOBO_material_clear_coat",
    "anisotropic": "ASOBO_material_anisotropic",
    "hair": "ASOBO_material_hair",
    "sss": "ASOBO_material_sss",
    "glass": "ASOBO_material_glass",
    "geo_decal": "ASOBO_material_geo_decal",
    "fresnel_fade": "ASOBO_material_fresnel_fade",
    "parallax_window": "ASOBO_material_parallax_window",
    "fake_terrain": "ASOBO_material_fake_terrain",
    "invisible": "ASOBO_material_invisible",
    "environment_occluder": "ASOBO_material_environment_occluder",
}

# Preset material configurations
MATERIAL_PRESETS = {
    "vehicle_paint": {
        "metallic": 0.1,
        "roughness": 0.35,
        "clearcoat": 0.8,
        "msfs_type": "clear_coat",
    },
    "chrome": {
        "metallic": 1.0,
        "roughness": 0.1,
        "msfs_type": "standard",
    },
    "brushed_metal": {
        "metallic": 0.9,
        "roughness": 0.4,
        "msfs_type": "anisotropic",
    },
    "rubber": {
        "metallic": 0.0,
        "roughness": 0.9,
        "msfs_type": "standard",
    },
    "plastic": {
        "metallic": 0.0,
        "roughness": 0.5,
        "msfs_type": "standard",
    },
    "glass_clear": {
        "metallic": 0.0,
        "roughness": 0.0,
        "alpha": 0.1,
        "msfs_type": "glass",
    },
    "glass_tinted": {
        "metallic": 0.0,
        "roughness": 0.0,
        "alpha": 0.3,
        "msfs_type": "glass",
    },
    "windshield": {
        "metallic": 0.0,
        "roughness": 0.0,
        "alpha": 0.05,
        "msfs_type": "windshield",
    },
    "fabric": {
        "metallic": 0.0,
        "roughness": 0.8,
        "msfs_type": "standard",
    },
    "concrete": {
        "metallic": 0.0,
        "roughness": 0.95,
        "msfs_type": "standard",
    },
    "asphalt": {
        "metallic": 0.0,
        "roughness": 0.9,
        "msfs_type": "fake_terrain",
    },
}


def setup_msfs_material(
    material_name: str,
    msfs_type: str = "standard",
    base_color: list[float] | None = None,
    metallic: float = 0.0,
    roughness: float = 0.5,
    emissive_color: list[float] | None = None,
    emissive_strength: float = 0.0,
    alpha: float = 1.0,
    double_sided: bool = False,
    **extra_properties,
) -> dict[str, Any]:
    """Set up a material with MSFS-specific properties.

    Args:
        material_name: Name of the material to configure
        msfs_type: MSFS material type (standard, windshield, glass, etc.)
        base_color: RGBA base color
        metallic: Metallic value (0-1)
        roughness: Roughness value (0-1)
        emissive_color: RGB emissive color
        emissive_strength: Emissive intensity
        alpha: Alpha/opacity (0-1)
        double_sided: Whether material is double-sided
        **extra_properties: Additional MSFS-specific properties

    Returns:
        Dictionary with material configuration
    """
    mat = bpy.data.materials.get(material_name)
    if not mat:
        mat = bpy.data.materials.new(name=material_name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear existing nodes
    nodes.clear()

    # Create Principled BSDF
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, 0)

    # Create output node
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    # Set base color
    if base_color:
        if len(base_color) == 3:
            base_color = [*base_color, 1.0]
        principled.inputs["Base Color"].default_value = base_color

    # Set PBR properties
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness

    # Set emissive
    if emissive_color and emissive_strength > 0:
        if len(emissive_color) == 3:
            emissive_color = [*emissive_color, 1.0]
        # Multiply emissive color by strength
        emission_value = [c * emissive_strength for c in emissive_color[:3]]
        emission_value.append(1.0)
        principled.inputs["Emission Color"].default_value = emission_value
        principled.inputs["Emission Strength"].default_value = emissive_strength

    # Set alpha
    if alpha < 1.0:
        principled.inputs["Alpha"].default_value = alpha
        mat.blend_method = "BLEND"
        mat.shadow_method = "HASHED"
    else:
        mat.blend_method = "OPAQUE"

    # Double-sided
    mat.use_backface_culling = not double_sided

    # Store MSFS type as custom property (exported to glTF extras)
    msfs_type_tag = MSFS_MATERIAL_TYPES.get(msfs_type, MSFS_MATERIAL_TYPES["standard"])
    mat["MSFS_material_type"] = msfs_type_tag

    # Store additional MSFS properties
    for key, value in extra_properties.items():
        mat[f"MSFS_{key}"] = value

    return {
        "material": material_name,
        "msfs_type": msfs_type,
        "msfs_tag": msfs_type_tag,
        "metallic": metallic,
        "roughness": roughness,
        "alpha": alpha,
        "double_sided": double_sided,
    }


def create_glass_material(
    material_name: str,
    tint_color: list[float] | None = None,
    opacity: float = 0.1,
    ior: float = 1.45,
    is_windshield: bool = False,
) -> dict[str, Any]:
    """Create a glass material optimized for MSFS.

    Args:
        material_name: Name for the new material
        tint_color: Optional RGB tint color
        opacity: Glass opacity (0 = fully transparent)
        ior: Index of refraction
        is_windshield: Use windshield material type (rain effects)

    Returns:
        Dictionary with material info
    """
    mat = bpy.data.materials.get(material_name)
    if not mat:
        mat = bpy.data.materials.new(name=material_name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Create Principled BSDF
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, 0)

    # Create output
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    # Glass settings
    base_color = tint_color if tint_color else [0.8, 0.8, 0.8]
    if len(base_color) == 3:
        base_color = [*base_color, 1.0]

    principled.inputs["Base Color"].default_value = base_color
    principled.inputs["Metallic"].default_value = 0.0
    principled.inputs["Roughness"].default_value = 0.0
    principled.inputs["IOR"].default_value = ior
    principled.inputs["Alpha"].default_value = opacity
    principled.inputs["Transmission Weight"].default_value = 1.0 - opacity

    # Material settings
    mat.blend_method = "BLEND"
    mat.shadow_method = "HASHED"
    mat.use_backface_culling = False

    # MSFS type
    msfs_type = "windshield" if is_windshield else "glass"
    mat["MSFS_material_type"] = MSFS_MATERIAL_TYPES[msfs_type]

    if is_windshield:
        mat["MSFS_wiper_mask"] = True
        mat["MSFS_rain_drop_scale"] = 1.0

    return {
        "material": material_name,
        "msfs_type": msfs_type,
        "opacity": opacity,
        "ior": ior,
        "is_windshield": is_windshield,
    }


def create_emissive_material(
    material_name: str,
    base_color: list[float] | None = None,
    emissive_color: list[float] | None = None,
    emissive_strength: float = 1.0,
    is_day_night: bool = False,
) -> dict[str, Any]:
    """Create an emissive/light material for MSFS.

    Args:
        material_name: Name for the material
        base_color: RGBA base color (daytime appearance)
        emissive_color: RGB emissive color
        emissive_strength: Emission intensity
        is_day_night: Whether emission varies with time of day

    Returns:
        Dictionary with material info
    """
    mat = bpy.data.materials.get(material_name)
    if not mat:
        mat = bpy.data.materials.new(name=material_name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Create Principled BSDF
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, 0)

    # Create output
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    # Base color
    if base_color:
        if len(base_color) == 3:
            base_color = [*base_color, 1.0]
        principled.inputs["Base Color"].default_value = base_color

    # Emissive
    if emissive_color is None:
        emissive_color = [1.0, 1.0, 1.0]
    if len(emissive_color) == 3:
        emissive_color = [*emissive_color, 1.0]

    principled.inputs["Emission Color"].default_value = emissive_color
    principled.inputs["Emission Strength"].default_value = emissive_strength

    # Non-metallic for lights
    principled.inputs["Metallic"].default_value = 0.0
    principled.inputs["Roughness"].default_value = 1.0

    # MSFS properties
    mat["MSFS_material_type"] = MSFS_MATERIAL_TYPES["standard"]
    mat["MSFS_emissive_multiplier"] = emissive_strength

    if is_day_night:
        mat["MSFS_day_night_cycle"] = True
        mat["MSFS_emissive_mode"] = "NIGHT_ONLY"

    return {
        "material": material_name,
        "emissive_color": list(emissive_color[:3]),
        "emissive_strength": emissive_strength,
        "is_day_night": is_day_night,
    }


def apply_material_preset(
    material_name: str,
    preset_name: str,
    base_color: list[float] | None = None,
) -> dict[str, Any]:
    """Apply a predefined material preset.

    Args:
        material_name: Name of the material
        preset_name: Name of the preset to apply
        base_color: Optional override for base color

    Returns:
        Dictionary with applied preset info
    """
    if preset_name not in MATERIAL_PRESETS:
        return {
            "error": f"Unknown preset: {preset_name}",
            "available_presets": list(MATERIAL_PRESETS.keys()),
        }

    preset = MATERIAL_PRESETS[preset_name].copy()
    msfs_type = preset.pop("msfs_type", "standard")

    # Apply preset with optional color override
    if base_color:
        preset["base_color"] = base_color

    return setup_msfs_material(
        material_name=material_name,
        msfs_type=msfs_type,
        **preset,
    )


def get_material_presets() -> dict[str, Any]:
    """Get list of available material presets.

    Returns:
        Dictionary with preset information
    """
    presets = []
    for name, config in MATERIAL_PRESETS.items():
        presets.append({
            "name": name,
            "msfs_type": config.get("msfs_type", "standard"),
            "metallic": config.get("metallic", 0.0),
            "roughness": config.get("roughness", 0.5),
        })

    return {
        "presets": presets,
        "msfs_types": list(MSFS_MATERIAL_TYPES.keys()),
    }
