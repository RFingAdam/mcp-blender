"""PBR texture applicator for Blender materials.

Applies generated PBR texture maps (diffuse, roughness, normal, metallic)
to Blender objects using Principled BSDF materials.
"""

from typing import Any

import bpy

from .. import compat

# Map type → (BSDF input name, color space)
_MAP_CONFIG = {
    "diffuse": ("Base Color", "sRGB"),
    "roughness": ("Roughness", "Non-Color"),
    "metallic": ("Metallic", "Non-Color"),
    "normal": ("Normal", "Non-Color"),
}

# Node layout constants
_TEX_X = -600
_TEX_Y_START = 300
_TEX_Y_STEP = -300
_MAPPING_X = -900
_COORD_X = -1100


def apply_pbr_textures(
    object_name: str,
    texture_maps: dict[str, str],
    material_name: str | None = None,
) -> dict[str, Any]:
    """Apply PBR texture maps to an object's material.

    Creates or reuses a Principled BSDF material and wires up texture
    image nodes for each provided map type.

    Args:
        object_name: Name of the Blender object.
        texture_maps: Dict mapping map type to file path.
            Supported types: diffuse, roughness, metallic, normal.
        material_name: Optional material name. Defaults to
            ``{object_name}_PBR``.

    Returns:
        Dict with success status and details.
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"success": False, "error": f"Object not found: {object_name}"}

    if obj.type != "MESH":
        return {"success": False, "error": f"Object '{object_name}' is not a mesh"}

    mat_name = material_name or f"{object_name}_PBR"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(name=mat_name)

    mat.use_nodes = True
    tree = mat.node_tree

    # Find or create Principled BSDF
    bsdf = None
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            bsdf = node
            break
    if not bsdf:
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 300)

    # Get version-safe input names
    input_names = compat.get_principled_bsdf_inputs()

    # Create shared Texture Coordinate → Mapping chain
    coord_node = tree.nodes.new("ShaderNodeTexCoord")
    coord_node.location = (_COORD_X, _TEX_Y_START)

    mapping_node = tree.nodes.new("ShaderNodeMapping")
    mapping_node.location = (_MAPPING_X, _TEX_Y_START)
    tree.links.new(coord_node.outputs["UV"], mapping_node.inputs["Vector"])

    applied = []
    y_offset = _TEX_Y_START

    for map_type, filepath in texture_maps.items():
        if map_type not in _MAP_CONFIG:
            continue

        bsdf_input_label, color_space = _MAP_CONFIG[map_type]

        # Load image
        image = bpy.data.images.load(filepath, check_existing=True)
        image.colorspace_settings.name = color_space

        # Create texture image node
        tex_node = tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        tex_node.location = (_TEX_X, y_offset)
        tex_node.label = map_type.capitalize()

        # Connect mapping → texture
        tree.links.new(mapping_node.outputs["Vector"], tex_node.inputs["Vector"])

        # Connect texture → BSDF (normal needs a NormalMap node)
        if map_type == "normal":
            normal_node = tree.nodes.new("ShaderNodeNormalMap")
            normal_node.location = (_TEX_X + 300, y_offset)
            tree.links.new(tex_node.outputs["Color"], normal_node.inputs["Color"])
            if "Normal" in bsdf.inputs:
                tree.links.new(normal_node.outputs["Normal"], bsdf.inputs["Normal"])
        else:
            # Resolve the actual input name for this Blender version
            resolved = input_names.get(bsdf_input_label.lower().replace(" ", "_"), bsdf_input_label)
            if resolved in bsdf.inputs:
                tree.links.new(tex_node.outputs["Color"], bsdf.inputs[resolved])

        applied.append(map_type)
        y_offset += _TEX_Y_STEP

    # Assign material to object if not already assigned
    if mat.name not in [slot.material.name for slot in obj.material_slots if slot.material]:
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

    return {
        "success": True,
        "object": object_name,
        "material": mat.name,
        "applied_maps": applied,
        "map_count": len(applied),
    }
