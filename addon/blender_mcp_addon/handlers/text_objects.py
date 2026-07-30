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


def _object_world_bounds(obj):
    """World-space (x_min, x_max), (y_min, y_max), (z_min, z_max) from bound_box."""
    from mathutils import Vector

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def _fit_and_position(obj, fit_box, z_bottom, keep_aspect=False):
    """Scale obj's XY footprint to exactly fill fit_box and sit on z_bottom.

    Scale/location are applied as deltas on top of whatever the object
    already has, so this works whether obj was just created at the origin
    (scale/location still identity) or is an existing/imported object with
    its own transform.
    """
    (x0, x1), (y0, y1), _ = _object_world_bounds(obj)
    natural_w = x1 - x0
    natural_h = y1 - y0
    if natural_w <= 0 or natural_h <= 0:
        raise ValidationError(
            f"Object '{obj.name}' has zero-size XY bounds - nothing to fit"
        )

    target_w = fit_box["x_max"] - fit_box["x_min"]
    target_h = fit_box["y_max"] - fit_box["y_min"]
    if keep_aspect:
        s = min(target_w / natural_w, target_h / natural_h)
        sx = sy = s
    else:
        sx = target_w / natural_w
        sy = target_h / natural_h
    obj.scale = (obj.scale[0] * sx, obj.scale[1] * sy, obj.scale[2])

    (x0, x1), (y0, y1), (z0, z1) = _object_world_bounds(obj)
    target_cx = (fit_box["x_min"] + fit_box["x_max"]) / 2
    target_cy = (fit_box["y_min"] + fit_box["y_max"]) / 2
    cur_cx = (x0 + x1) / 2
    cur_cy = (y0 + y1) / 2
    obj.location = (
        obj.location[0] + (target_cx - cur_cx),
        obj.location[1] + (target_cy - cur_cy),
        obj.location[2] + (z_bottom - z0),
    )


def _convert_weld_triangulate(obj, triangulate=True):
    """Bake obj to a mesh (if it isn't one already), weld seam duplicates, triangulate."""
    import bmesh

    ensure_object_selected(obj)
    if obj.type != "MESH":
        bpy.ops.object.convert(target="MESH")

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
    if triangulate:
        bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _separate_into_pieces(obj):
    """Split obj by loose parts (e.g. one piece per glyph) and return the piece objects."""
    ensure_object_selected(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    return [o for o in bpy.context.selected_objects if o.type == "MESH"]


def _union_pieces_onto_target(pieces, target_obj, solver):
    """Boolean-UNION each piece onto target_obj one at a time, detecting silent solver corruption.

    See _handle_text_add_relief's docstring for why one-at-a-time is required.
    """
    union_log = []
    verts_before = len(target_obj.data.vertices)
    for piece in pieces:
        mod = target_obj.modifiers.new(name="Boolean_UNION", type="BOOLEAN")
        mod.operation = "UNION"
        mod.solver = solver
        mod.object = piece

        ctx = bpy.context.copy()
        ctx["object"] = target_obj
        with bpy.context.temp_override(**ctx):
            bpy.ops.object.modifier_apply(modifier=mod.name)

        verts_after = len(target_obj.data.vertices)
        piece.hide_set(True)
        piece.hide_render = True
        union_log.append({
            "piece": piece.name,
            "verts_before": verts_before,
            "verts_after": verts_after,
        })
        if verts_after == verts_before:
            return {
                "success": False,
                "error": (
                    f"Union with piece '{piece.name}' left the target's vertex "
                    f"count unchanged ({verts_after}) - this is the signature of the "
                    "EXACT solver silently corrupting a multi-island/complex union. "
                    "Stopped here instead of continuing over a corrupted target."
                ),
                "union_log": union_log,
                "remaining_pieces": [p.name for p in pieces if p.name not in
                                     {u["piece"] for u in union_log}],
            }
        verts_before = verts_after

    return {
        "success": True,
        "union_log": union_log,
        "final_vertices": len(target_obj.data.vertices),
        "final_faces": len(target_obj.data.polygons),
    }


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

    def _handle_text_add_relief(self, params: dict) -> dict:
        """Create text, fit it to an XY box, and boolean-union it onto a target mesh.

        Automates the full "engraved/relief lettering" recipe in one call:
        create a native vector text object, scale its X and Y independently
        so it exactly fills ``fit_box`` (font aspect ratio rarely matches the
        target footprint), position its bottom at ``z_bottom``, convert to a
        mesh, triangulate, separate into one piece per glyph, and boolean
        UNION each piece onto ``target_object`` individually.

        The per-glyph separation and one-at-a-time union order are load-bearing,
        not stylistic choices: unioning a single tool object containing several
        disjoint glyph islands in one modifier can silently corrupt the result
        (confirmed by direct experiment against Blender 5.2's EXACT solver -
        the target can collapse to a handful of vertices with no error
        reported). Handling glyphs one union at a time avoids this.

        On the first glyph whose union does not change the target's vertex
        count, this stops immediately and reports which glyph failed rather
        than silently continuing - as the same corrupted-collapse failure mode
        can otherwise slip through unnoticed.
        """
        content = require_param(params, "content", str)
        target_name = require_param(params, "target_object", str)
        fit_box = require_param(params, "fit_box", dict)
        for key in ("x_min", "x_max", "y_min", "y_max"):
            if key not in fit_box:
                raise ValidationError(f"fit_box missing '{key}'")
        z_bottom = float(require_param(params, "z_bottom", (int, float)))

        size = float(params.get("size", 10.0))
        extrude = float(params.get("extrude", 1.0))
        bevel_depth = float(params.get("bevel_depth", 0.0))
        bevel_resolution = int(params.get("bevel_resolution", 4))
        letter_spacing = float(params.get("letter_spacing", 1.0))
        solver = validate_enum(params.get("solver", "EXACT"), "solver", ["FAST", "EXACT"])
        triangulate = params.get("triangulate", True)
        font_path = params.get("font_path")

        target_obj = get_object_or_error(target_name)
        if target_obj.type != "MESH":
            raise ValidationError(f"target_object '{target_name}' is not a mesh")

        text_data = bpy.data.curves.new(name=f"{content}_relief_data", type="FONT")
        text_data.body = content
        text_data.size = size
        text_data.extrude = extrude
        text_data.bevel_depth = bevel_depth
        text_data.bevel_resolution = bevel_resolution
        text_data.space_character = letter_spacing
        text_data.align_x = "CENTER"
        text_data.align_y = "CENTER"
        text_data.fill_mode = "BOTH"
        if font_path:
            text_data.font = _load_font(font_path)

        text_obj = bpy.data.objects.new(f"{content}_relief", text_data)
        bpy.context.collection.objects.link(text_obj)

        (x0, x1), (y0, y1), _ = _object_world_bounds(text_obj)
        if (x1 - x0) <= 0 or (y1 - y0) <= 0:
            bpy.data.objects.remove(text_obj, do_unlink=True)
            raise ValidationError(f"Text '{content}' produced zero-size bounds - check font_path/content")

        _fit_and_position(text_obj, fit_box, z_bottom)
        _convert_weld_triangulate(text_obj, triangulate)
        glyph_pieces = _separate_into_pieces(text_obj)
        result = _union_pieces_onto_target(glyph_pieces, target_obj, solver)

        if not result["success"]:
            result["target"] = target_name
            return result

        return {
            "success": True,
            "target": target_name,
            "content": content,
            "glyph_count": len(glyph_pieces),
            "union_log": result["union_log"],
            "final_vertices": result["final_vertices"],
            "final_faces": result["final_faces"],
        }

    def _handle_mesh_add_relief(self, params: dict) -> dict:
        """Fit one or more existing objects to an XY box and boolean-union them onto a target mesh.

        This is the same "fit into a box, convert to mesh, separate into
        pieces, union one piece at a time onto the target" recipe as
        ``text_add_relief``, generalized to work on any already-existing
        source object(s) - imported SVG curves, an imported logo mesh,
        anything - instead of only Blender's native FONT text. Use this when
        the lettering/artwork isn't (or can't be) built as native text, e.g.
        importing font glyphs as SVG paths to route around a solver bug that
        only reproduces on native TextCurve conversion for a particular
        target mesh.

        If more than one ``source_objects`` name is given, they are joined
        into a single object first (SVG import typically creates one object
        per path/glyph), then that combined object's bounding box drives the
        fit-to-box scale/position, preserving the glyphs' relative
        positions and sizes to each other.

        See ``text_add_relief`` for why the per-piece, one-at-a-time union
        order matters (silent EXACT-solver corruption otherwise) - this tool
        applies the same corruption check and stops immediately on the first
        piece whose union doesn't change the target's vertex count.
        """
        source_names = require_param(params, "source_objects", list)
        if not source_names:
            raise ValidationError("source_objects must contain at least one object name")
        target_name = require_param(params, "target_object", str)
        fit_box = require_param(params, "fit_box", dict)
        for key in ("x_min", "x_max", "y_min", "y_max"):
            if key not in fit_box:
                raise ValidationError(f"fit_box missing '{key}'")
        z_bottom = float(require_param(params, "z_bottom", (int, float)))

        keep_aspect = bool(params.get("keep_aspect", False))
        solver = validate_enum(params.get("solver", "EXACT"), "solver", ["FAST", "EXACT"])
        triangulate = params.get("triangulate", True)
        separate_loose = params.get("separate_loose", True)

        target_obj = get_object_or_error(target_name)
        if target_obj.type != "MESH":
            raise ValidationError(f"target_object '{target_name}' is not a mesh")

        source_objs = [get_object_or_error(n) for n in source_names]
        for obj in source_objs:
            if obj.name == target_obj.name:
                raise ValidationError("source_objects cannot include target_object")

        bpy.ops.object.select_all(action="DESELECT")
        for obj in source_objs:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = source_objs[0]
        if len(source_objs) > 1:
            bpy.ops.object.join()
        source_obj = bpy.context.view_layer.objects.active

        _fit_and_position(source_obj, fit_box, z_bottom, keep_aspect=keep_aspect)
        _convert_weld_triangulate(source_obj, triangulate)
        pieces = _separate_into_pieces(source_obj) if separate_loose else [source_obj]
        result = _union_pieces_onto_target(pieces, target_obj, solver)

        if not result["success"]:
            result["target"] = target_name
            result["source_objects"] = source_names
            return result

        return {
            "success": True,
            "target": target_name,
            "source_objects": source_names,
            "piece_count": len(pieces),
            "union_log": result["union_log"],
            "final_vertices": result["final_vertices"],
            "final_faces": result["final_faces"],
        }
