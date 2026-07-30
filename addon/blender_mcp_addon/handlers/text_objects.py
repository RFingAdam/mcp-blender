"""Text object command handlers.

Blender's native Text object (``bpy.types.TextCurve``, ``Object.type ==
"FONT"``) is a vector/curve-based letterform, so its extrude and bevel are
resolution-independent — round corners stay round at any scale. This is the
right tool for engraved or relief text (signage, badges, embossed logos):
raster/voxel reconstructions of individual glyphs stair-step at whatever
resolution they were sampled at, and no amount of post-hoc beveling can
un-stairstep them, since the underlying silhouette is already faceted.
"""

import os

import bpy

from ..utils import ensure_object_selected, get_object_or_error
from ..validation import (
    ValidationError,
    require_param,
    validate_enum,
    validate_filepath,
    validate_vector3,
)

_ALIGN_X = ["LEFT", "CENTER", "RIGHT", "JUSTIFY", "FLUSH"]
_ALIGN_Y = ["TOP_BASELINE", "TOP", "CENTER", "BOTTOM", "BOTTOM_BASELINE"]
# TextCurve.fill_mode has a different enum than a plain Curve's fill_mode
# (no FULL/HALF - BOTH is the text equivalent of FULL).
_FILL_TYPES = ["NONE", "BACK", "FRONT", "BOTH"]


def _load_font(font_path: str):
    """Load a font file, reusing an already-loaded VectorFont if present."""
    validate_filepath(font_path, "font_path", must_exist=True)
    abs_path = os.path.abspath(font_path)
    for f in bpy.data.fonts:
        if f.filepath and os.path.abspath(bpy.path.abspath(f.filepath)) == abs_path:
            return f
    try:
        return bpy.data.fonts.load(abs_path)
    except RuntimeError as e:
        raise ValidationError(f"Could not load font '{font_path}': {e}")


def _get_text_object_or_error(name: str):
    obj = get_object_or_error(name)
    if obj.type != "FONT":
        raise ValidationError(f"Object '{name}' is not a text object (type: {obj.type})")
    return obj


class TextObjectHandlersMixin:
    """Mixin for native (vector/curve-based) text object handlers."""

    def _handle_text_create(self, params: dict) -> dict:
        """Create a 3D text object from Blender's native FONT/TextCurve data.

        Unlike a mesh rebuilt from a raster/height-map, the letterforms stay
        smooth curves regardless of ``extrude``/``bevel_depth`` — use this
        instead of reconstructing glyphs from pixel data when you need
        rounded, printable/engravable text.
        """
        name = params.get("name", "Text")
        content = require_param(params, "content", str)
        location = validate_vector3(params.get("location", [0, 0, 0]), "location")
        rotation = validate_vector3(params.get("rotation", [0, 0, 0]), "rotation")

        size = float(params.get("size", 1.0))
        extrude = float(params.get("extrude", 0.0))
        bevel_depth = float(params.get("bevel_depth", 0.0))
        bevel_resolution = int(params.get("bevel_resolution", 4))
        letter_spacing = float(params.get("letter_spacing", 1.0))
        word_spacing = float(params.get("word_spacing", 1.0))
        line_spacing = float(params.get("line_spacing", 1.0))
        align_x = validate_enum(params.get("align_x", "LEFT"), "align_x", _ALIGN_X)
        align_y = validate_enum(params.get("align_y", "BOTTOM_BASELINE"), "align_y", _ALIGN_Y)
        fill_type = validate_enum(params.get("fill_type", "BOTH"), "fill_type", _FILL_TYPES)
        font_path = params.get("font_path")

        text_data = bpy.data.curves.new(name=f"{name}_data", type="FONT")
        text_data.body = content
        text_data.size = size
        text_data.extrude = extrude
        text_data.bevel_depth = bevel_depth
        text_data.bevel_resolution = bevel_resolution
        text_data.space_character = letter_spacing
        text_data.space_word = word_spacing
        text_data.space_line = line_spacing
        text_data.align_x = align_x
        text_data.align_y = align_y
        text_data.fill_mode = fill_type

        if font_path:
            text_data.font = _load_font(font_path)

        text_obj = bpy.data.objects.new(name, text_data)
        text_obj.location = tuple(location)
        text_obj.rotation_euler = tuple(rotation)
        bpy.context.collection.objects.link(text_obj)

        return {
            "success": True,
            "name": text_obj.name,
            "content": content,
            "size": size,
            "extrude": extrude,
            "bevel_depth": bevel_depth,
            "font": text_data.font.name if text_data.font else None,
        }

    def _handle_text_set_properties(self, params: dict) -> dict:
        """Update an existing text object's content/font/extrude/bevel/spacing.

        Only parameters that are present in ``params`` are changed, so this
        can be called repeatedly to dial in a look (e.g. matching an existing
        engraved relief's depth and corner roundness) without recreating the
        object each time.
        """
        object_name = require_param(params, "object_name", str)
        obj = _get_text_object_or_error(object_name)
        data = obj.data
        changed = []

        if "content" in params:
            data.body = require_param(params, "content", str)
            changed.append("content")
        if "size" in params:
            data.size = float(params["size"])
            changed.append("size")
        if "extrude" in params:
            data.extrude = float(params["extrude"])
            changed.append("extrude")
        if "bevel_depth" in params:
            data.bevel_depth = float(params["bevel_depth"])
            changed.append("bevel_depth")
        if "bevel_resolution" in params:
            data.bevel_resolution = int(params["bevel_resolution"])
            changed.append("bevel_resolution")
        if "letter_spacing" in params:
            data.space_character = float(params["letter_spacing"])
            changed.append("letter_spacing")
        if "word_spacing" in params:
            data.space_word = float(params["word_spacing"])
            changed.append("word_spacing")
        if "line_spacing" in params:
            data.space_line = float(params["line_spacing"])
            changed.append("line_spacing")
        if "align_x" in params:
            data.align_x = validate_enum(params["align_x"], "align_x", _ALIGN_X)
            changed.append("align_x")
        if "align_y" in params:
            data.align_y = validate_enum(params["align_y"], "align_y", _ALIGN_Y)
            changed.append("align_y")
        if "fill_type" in params:
            data.fill_mode = validate_enum(params["fill_type"], "fill_type", _FILL_TYPES)
            changed.append("fill_type")
        if "font_path" in params:
            data.font = _load_font(params["font_path"])
            changed.append("font_path")
        if "location" in params:
            obj.location = tuple(validate_vector3(params["location"], "location"))
            changed.append("location")
        if "rotation" in params:
            obj.rotation_euler = tuple(validate_vector3(params["rotation"], "rotation"))
            changed.append("rotation")

        return {"success": True, "name": obj.name, "changed": changed}

    def _handle_text_to_mesh(self, params: dict) -> dict:
        """Convert a text object to a real mesh (bakes the vector letterforms).

        Do this once the size/extrude/bevel/spacing look right — the result
        is an ordinary mesh usable with ``boolean_op``, ``export_stl``, etc.
        """
        object_name = require_param(params, "object_name", str)
        keep_original = params.get("keep_original", False)

        obj = _get_text_object_or_error(object_name)

        if keep_original:
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.name = params.get("new_name", f"{object_name}_mesh")
            bpy.context.collection.objects.link(new_obj)
            target = new_obj
        else:
            target = obj

        ensure_object_selected(target)
        bpy.ops.object.convert(target="MESH")

        # bpy.ops.object.convert leaves duplicate coincident vertices at each
        # glyph spline's start/end seam, which reads as non-manifold edges.
        # Weld them - this is the same "Merge by Distance" pass every artist
        # runs by hand after Alt+C on a text object.
        import bmesh

        bm = bmesh.new()
        bm.from_mesh(target.data)
        verts_before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
        welded = verts_before - len(bm.verts)
        bm.to_mesh(target.data)
        bm.free()
        target.data.update()

        return {
            "success": True,
            "name": target.name,
            "vertices": len(target.data.vertices),
            "faces": len(target.data.polygons),
            "welded_duplicates": welded,
        }
