"""Texture painting workflow tools for livery creation."""

from pathlib import Path
from typing import Any

import bpy

# Paint layer presets for livery workflow
PAINT_LAYERS = {
    "primer": {
        "description": "Base primer coat (usually white or light gray)",
        "blend_mode": "MIX",
        "default_color": (0.95, 0.95, 0.95, 1.0),
    },
    "base_color": {
        "description": "Main fuselage color",
        "blend_mode": "MIX",
        "default_color": (1.0, 1.0, 1.0, 1.0),
    },
    "cheatline": {
        "description": "Window line stripe",
        "blend_mode": "MIX",
        "default_color": (0.0, 0.2, 0.5, 1.0),
    },
    "belly": {
        "description": "Aircraft belly color (typically gray)",
        "blend_mode": "MIX",
        "default_color": (0.6, 0.6, 0.6, 1.0),
    },
    "details": {
        "description": "Logos, text, and fine details",
        "blend_mode": "MIX",
        "default_color": (0.0, 0.0, 0.0, 1.0),
    },
    "decals": {
        "description": "Decals and stickers (registration, flags)",
        "blend_mode": "MIX",
        "default_color": (0.0, 0.0, 0.0, 1.0),
    },
    "weathering": {
        "description": "Dirt, wear, and weathering effects",
        "blend_mode": "MULTIPLY",
        "default_color": (0.8, 0.75, 0.7, 0.3),
    },
    "clearcoat": {
        "description": "Final clear coat / gloss layer reference",
        "blend_mode": "OVERLAY",
        "default_color": (1.0, 1.0, 1.0, 0.1),
    },
}

# Brush presets for livery painting
BRUSH_PRESETS = {
    "soft_airbrush": {
        "description": "Soft spray for gradients and large areas",
        "strength": 0.3,
        "size": 200,
        "falloff": "SMOOTH",
        "use_pressure_strength": True,
    },
    "hard_edge": {
        "description": "Hard edge for crisp lines and masks",
        "strength": 1.0,
        "size": 50,
        "falloff": "CONSTANT",
        "use_pressure_strength": False,
    },
    "detail_brush": {
        "description": "Fine detail work",
        "strength": 0.8,
        "size": 20,
        "falloff": "SHARP",
        "use_pressure_strength": True,
    },
    "smudge": {
        "description": "Blend and smudge colors",
        "strength": 0.5,
        "size": 100,
        "blend": "BLUR",
    },
    "clone": {
        "description": "Clone/stamp from reference",
        "strength": 1.0,
        "size": 100,
        "blend": "MIX",
    },
    "fill": {
        "description": "Fill large areas",
        "strength": 1.0,
        "size": 500,
        "falloff": "CONSTANT",
    },
}


def setup_paint_mode(
    object_name: str,
    texture_resolution: tuple[int, int] = (4096, 4096),
    create_uvs: bool = True,
) -> dict[str, Any]:
    """Set up an object for texture painting.

    Args:
        object_name: Name of the object to paint
        texture_resolution: Resolution for paint texture (width, height)
        create_uvs: Create UV map if none exists

    Returns:
        Dictionary with setup results
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    if obj.type != "MESH":
        return {"error": f"Object must be a mesh, got {obj.type}"}

    mesh = obj.data

    # Ensure UV map exists
    if not mesh.uv_layers:
        if create_uvs:
            mesh.uv_layers.new(name="UVMap")
        else:
            return {"error": "Object has no UV map. Set create_uvs=True to create one."}

    # Create or get paint texture
    tex_name = f"{object_name}_livery_paint"
    width, height = texture_resolution

    if tex_name in bpy.data.images:
        paint_image = bpy.data.images[tex_name]
        # Resize if needed
        if paint_image.size[0] != width or paint_image.size[1] != height:
            paint_image.scale(width, height)
    else:
        paint_image = bpy.data.images.new(
            name=tex_name,
            width=width,
            height=height,
            alpha=True,
        )
        paint_image.generated_color = (1, 1, 1, 1)

    # Create material with paint texture if needed
    mat_name = f"{object_name}_livery_material"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        # Create nodes
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = paint_image
        tex_node.location = (-300, 300)

        principled = nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (0, 300)

        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (300, 300)

        # Link nodes
        links.new(tex_node.outputs["Color"], principled.inputs["Base Color"])
        links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    # Assign material to object
    if mat.name not in [slot.material.name for slot in obj.material_slots if slot.material]:
        obj.data.materials.append(mat)

    # Select object and enter texture paint mode
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.mode_set(mode="TEXTURE_PAINT")

    # Set paint texture as active
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = "MATERIAL"

    # Configure paint settings
    paint = bpy.context.tool_settings.image_paint
    paint.mode = "IMAGE"
    paint.canvas = paint_image

    return {
        "object": object_name,
        "paint_texture": tex_name,
        "texture_size": [width, height],
        "material": mat_name,
        "uv_layer": mesh.uv_layers.active.name,
        "mode": "TEXTURE_PAINT",
    }


def create_paint_layers(
    object_name: str,
    layers: list[str] | None = None,
    texture_resolution: tuple[int, int] = (4096, 4096),
) -> dict[str, Any]:
    """Create paint layer images for livery workflow.

    Args:
        object_name: Name of the object
        layers: List of layer names to create (default: all preset layers)
        texture_resolution: Resolution for each layer

    Returns:
        Dictionary with created layers
    """
    if layers is None:
        layers = list(PAINT_LAYERS.keys())

    width, height = texture_resolution
    created_layers = []

    for layer_name in layers:
        if layer_name not in PAINT_LAYERS:
            continue

        preset = PAINT_LAYERS[layer_name]
        img_name = f"{object_name}_layer_{layer_name}"

        if img_name not in bpy.data.images:
            img = bpy.data.images.new(
                name=img_name,
                width=width,
                height=height,
                alpha=True,
            )
            # Set default color
            img.generated_color = preset["default_color"]

            created_layers.append({
                "name": layer_name,
                "image": img_name,
                "description": preset["description"],
                "blend_mode": preset["blend_mode"],
            })
        else:
            created_layers.append({
                "name": layer_name,
                "image": img_name,
                "description": preset["description"],
                "already_exists": True,
            })

    return {
        "object": object_name,
        "layers": created_layers,
        "layer_count": len(created_layers),
        "texture_size": [width, height],
        "tip": "Use set_paint_brush to switch between layers for painting",
    }


def load_template_overlay(
    image_path: str,
    object_name: str | None = None,
    opacity: float = 0.5,
) -> dict[str, Any]:
    """Load a reference template image as overlay for painting.

    Args:
        image_path: Path to template image
        object_name: Object to use as reference (optional)
        opacity: Overlay opacity (0-1)

    Returns:
        Dictionary with load results
    """
    path = Path(image_path)
    if not path.exists():
        return {"error": f"Image not found: {image_path}"}

    # Load image
    img_name = f"template_{path.stem}"
    if img_name in bpy.data.images:
        template_img = bpy.data.images[img_name]
        template_img.reload()
    else:
        template_img = bpy.data.images.load(str(path))
        template_img.name = img_name

    # Add as background image in 3D view if we have an object
    result = {
        "template_image": img_name,
        "size": list(template_img.size),
        "filepath": str(path),
    }

    # Set up reference in image editor
    for area in bpy.context.screen.areas:
        if area.type == "IMAGE_EDITOR":
            for space in area.spaces:
                if space.type == "IMAGE_EDITOR":
                    # Store as reference
                    space.image = template_img
                    result["loaded_in_image_editor"] = True
                    break

    # If we have an object, set up material with template reference
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if obj and obj.type == "MESH":
            # Create reference material node setup
            mat = obj.active_material
            if mat and mat.use_nodes:
                nodes = mat.node_tree.nodes

                # Add template texture node
                ref_node = nodes.new("ShaderNodeTexImage")
                ref_node.image = template_img
                ref_node.name = "Template_Reference"
                ref_node.location = (-600, 300)
                ref_node.label = "Template Reference (disable for final)"

                result["added_to_material"] = True
                result["node_name"] = ref_node.name

    return result


def export_uv_layout(
    object_name: str,
    output_path: str,
    resolution: tuple[int, int] = (4096, 4096),
    fill_opacity: float = 0.0,
    line_thickness: float = 1.0,
) -> dict[str, Any]:
    """Export UV layout as an image for painting reference.

    Args:
        object_name: Name of the object
        output_path: Output image path
        resolution: Output resolution (width, height)
        fill_opacity: Fill opacity for UV faces (0 = wireframe only)
        line_thickness: UV edge line thickness

    Returns:
        Dictionary with export results
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    if obj.type != "MESH":
        return {"error": f"Object must be a mesh, got {obj.type}"}

    mesh = obj.data
    if not mesh.uv_layers:
        return {"error": "Object has no UV map"}

    # Select object and enter edit mode
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")

    # Export UV layout
    width, height = resolution
    bpy.ops.uv.export_layout(
        filepath=output_path,
        size=(width, height),
        opacity=fill_opacity,
        export_all=True,
    )

    # Return to object mode
    bpy.ops.object.mode_set(mode="OBJECT")

    return {
        "object": object_name,
        "output_path": output_path,
        "resolution": [width, height],
        "uv_layer": mesh.uv_layers.active.name,
    }


def set_paint_brush(
    preset: str | None = None,
    color: tuple[float, float, float, float] | None = None,
    size: int | None = None,
    strength: float | None = None,
) -> dict[str, Any]:
    """Configure paint brush settings.

    Args:
        preset: Brush preset name (soft_airbrush, hard_edge, detail_brush, etc.)
        color: RGBA paint color (0-1 range)
        size: Brush size in pixels
        strength: Brush strength (0-1)

    Returns:
        Dictionary with brush settings
    """
    # Ensure we're in texture paint mode
    if bpy.context.mode != "PAINT_TEXTURE":
        return {"error": "Not in texture paint mode. Use setup_paint_mode first."}

    brush = bpy.context.tool_settings.image_paint.brush
    if not brush:
        return {"error": "No active brush"}

    result = {"brush": brush.name}

    # Apply preset if specified
    if preset and preset in BRUSH_PRESETS:
        preset_data = BRUSH_PRESETS[preset]
        if "strength" in preset_data:
            brush.strength = preset_data["strength"]
        if "size" in preset_data:
            brush.size = preset_data["size"]
        if "falloff" in preset_data:
            brush.curve_preset = preset_data["falloff"]
        if "use_pressure_strength" in preset_data:
            brush.use_pressure_strength = preset_data["use_pressure_strength"]
        result["preset_applied"] = preset
        result["preset_description"] = preset_data.get("description", "")

    # Apply individual settings
    if color is not None:
        if len(color) >= 3:
            brush.color = color[:3]
        if len(color) >= 4:
            brush.strength = color[3]  # Use alpha as strength hint
        result["color"] = list(color)

    if size is not None:
        brush.size = size
        result["size"] = size

    if strength is not None:
        brush.strength = strength
        result["strength"] = strength

    # Return current settings
    result["current_settings"] = {
        "color": list(brush.color),
        "size": brush.size,
        "strength": brush.strength,
    }

    return result


def sample_color_from_image(
    image_path: str,
    x: int,
    y: int,
) -> dict[str, Any]:
    """Sample a color from an image at specific coordinates.

    Useful for matching colors from reference livery images.

    Args:
        image_path: Path to image file
        x: X coordinate to sample
        y: Y coordinate to sample

    Returns:
        Dictionary with sampled color
    """
    path = Path(image_path)
    if not path.exists():
        return {"error": f"Image not found: {image_path}"}

    # Load image
    img = bpy.data.images.load(str(path))
    width, height = img.size

    # Validate coordinates
    if x < 0 or x >= width or y < 0 or y >= height:
        return {
            "error": f"Coordinates ({x}, {y}) out of bounds for image size ({width}, {height})"
        }

    # Get pixel data
    pixels = img.pixels[:]

    # Calculate pixel index (Blender stores pixels bottom-to-top, RGBA)
    # Flip Y coordinate
    flipped_y = height - 1 - y
    pixel_index = (flipped_y * width + x) * 4

    r = pixels[pixel_index]
    g = pixels[pixel_index + 1]
    b = pixels[pixel_index + 2]
    a = pixels[pixel_index + 3]

    # Convert to hex
    hex_color = "#{:02x}{:02x}{:02x}".format(
        int(r * 255), int(g * 255), int(b * 255)
    )

    # Clean up loaded image
    bpy.data.images.remove(img)

    return {
        "color_rgba": [r, g, b, a],
        "color_rgb": [r, g, b],
        "color_hex": hex_color,
        "coordinates": [x, y],
        "image_size": [width, height],
    }


def get_paint_presets() -> dict[str, Any]:
    """Get available paint presets for livery painting.

    Returns:
        Dictionary with layer and brush presets
    """
    return {
        "layers": {
            name: {
                "description": data["description"],
                "blend_mode": data["blend_mode"],
            }
            for name, data in PAINT_LAYERS.items()
        },
        "brushes": {
            name: {
                "description": data["description"],
            }
            for name, data in BRUSH_PRESETS.items()
        },
    }
