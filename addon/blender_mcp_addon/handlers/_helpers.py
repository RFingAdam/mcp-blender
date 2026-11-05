"""Module-level helper functions and constants for handler modules."""

import functools
import math
import os

import bpy

from .. import compat

_SOCKET_TYPE_MAP = {
    "FLOAT": "NodeSocketFloat",
    "VALUE": "NodeSocketFloat",
    "INT": "NodeSocketInt",
    "RGBA": "NodeSocketColor",
    "VECTOR": "NodeSocketVector",
    "SHADER": "NodeSocketShader",
    "BOOLEAN": "NodeSocketBool",
    "OBJECT": "NodeSocketObject",
    "COLLECTION": "NodeSocketCollection",
    "MATERIAL": "NodeSocketMaterial",
    "IMAGE": "NodeSocketImage",
    "STRING": "NodeSocketString",
}


def view3d_override():
    """Context override for an operator that needs a 3D viewport, or None when there is none.

    Walks the window manager rather than reading ``bpy.context.area``: the socket server
    runs handlers from a ``bpy.app.timers`` callback, where the context has no area or
    window even in the GUI. Background mode returns None.
    """
    # A .blend loaded in background mode still carries its saved windows and areas, but
    # they have no GPU context behind them and operators that use them crash.
    if bpy.app.background:
        return None
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        screen = window.screen
        for area in screen.areas if screen else ():
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    return {"window": window, "screen": screen, "area": area, "region": region}
    return None


def needs_view3d(tool: str) -> dict:
    """The honest reply for a tool whose operator needs a 3D viewport and has none."""
    return {"success": False, "error": f"{tool} needs an open 3D viewport"}


def restores_object_mode(handler=None, *, error_replies=False):
    """Leave Object mode as it was found when a handler fails after entering Edit or Sculpt mode.

    Many mesh handlers switch to Edit mode, run an operator and switch back. When the
    operator raises, the switch back never runs and the scene stays in Edit mode.

    Sculpt handlers usually report a failure as an error dict instead of raising, so
    with ``error_replies=True`` a reply with an ``error`` or ``success: False`` is a
    failure too. A reply that succeeds keeps whatever mode the handler left.
    """

    def decorate(handler):
        @functools.wraps(handler)
        def wrapper(self, params):
            was_object = bpy.context.mode == "OBJECT"

            def leave_to_object():
                if was_object and bpy.context.mode != "OBJECT":
                    try:
                        bpy.ops.object.mode_set(mode="OBJECT")
                    except RuntimeError:
                        pass

            try:
                reply = handler(self, params)
            except BaseException:
                leave_to_object()
                raise
            if (
                error_replies
                and isinstance(reply, dict)
                and (reply.get("error") or reply.get("success") is False)
            ):
                leave_to_object()
            return reply

        return wrapper

    return decorate if handler is None else decorate(handler)


# Bake channel configuration
_CHANNEL_BAKE_CONFIG = {
    "DIFFUSE": {
        "type": "DIFFUSE",
        "pass_filter": {"COLOR"},
        "color_space": "sRGB",
    },
    "ROUGHNESS": {
        "type": "ROUGHNESS",
        "pass_filter": set(),
        "color_space": "Non-Color",
    },
    "METALLIC": {
        "type": "EMIT",
        "pass_filter": set(),
        "color_space": "Non-Color",
        "metallic_trick": True,
    },
    "NORMAL": {
        "type": "NORMAL",
        "pass_filter": set(),
        "color_space": "Non-Color",
    },
    "AO": {
        "type": "AO",
        "pass_filter": set(),
        "color_space": "Non-Color",
    },
    "EMISSION": {
        "type": "EMIT",
        "pass_filter": set(),
        "color_space": "sRGB",
    },
    "DISPLACEMENT": {
        "type": "EMIT",
        "pass_filter": set(),
        "color_space": "Non-Color",
        "displacement_trick": True,
    },
    "COMBINED": {
        "type": "COMBINED",
        "pass_filter": set(),
        "color_space": "sRGB",
    },
}

_ALL_CHANNELS = list(_CHANNEL_BAKE_CONFIG.keys())

_FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "TARGA": ".tga",
    "OPEN_EXR": ".exr",
}


# ---------------------------------------------------------------------------
# Geometry Nodes helpers
# ---------------------------------------------------------------------------


def _build_socket_info(group):
    """Return (inputs, outputs) socket descriptions from a node group interface."""
    inputs = []
    outputs = []
    for item in group.interface.items_tree:
        if item.item_type != "SOCKET":
            continue
        info = {
            "name": item.name,
            "type": _socket_type_label(item),
            "bl_socket_idname": item.bl_socket_idname,
            "identifier": item.identifier,
        }
        if item.in_out == "INPUT":
            inputs.append(info)
        else:
            outputs.append(info)
    return inputs, outputs


def _link(tree, from_socket, to_socket):
    """Shortcut: create a node link."""
    tree.links.new(from_socket, to_socket)


def _new_node(tree, bl_idname, label=None, location=(0, 0)):
    """Create a node, optionally set its label and position."""
    node = tree.nodes.new(type=bl_idname)
    if label:
        node.label = label
    node.location = location
    return node


def _get_gn_modifier(obj, modifier_name=None):
    """Return the first (or named) Geometry Nodes modifier, or None."""
    if modifier_name:
        mod = obj.modifiers.get(modifier_name)
        if mod and mod.type == "NODES":
            return mod
        return None
    for mod in obj.modifiers:
        if mod.type == "NODES":
            return mod
    return None


def _socket_type_label(socket):
    """Return a human-friendly type label for a node-group interface socket."""
    bl_type = socket.bl_socket_idname
    mapping = {
        "FLOAT": "NodeSocketFloat",
        "INT": "NodeSocketInt",
        "VECTOR": "NodeSocketVector",
        "BOOLEAN": "NodeSocketBool",
        "OBJECT": "NodeSocketObject",
        "COLLECTION": "NodeSocketCollection",
        "MATERIAL": "NodeSocketMaterial",
        "IMAGE": "NodeSocketImage",
        "STRING": "NodeSocketString",
        "GEOMETRY": "NodeSocketGeometry",
    }
    for label, bl_name in mapping.items():
        if bl_name == bl_type:
            return label
    return bl_type


def _read_modifier_input(modifier, identifier):
    """Read a modifier input value, converting Blender types to plain Python."""
    val = compat.get_modifier_input(modifier, identifier)
    if val is None:
        return None
    if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
        return [float(v) for v in val]
    if isinstance(val, (float, int, bool)):
        return val
    if val is not None and hasattr(val, "name"):
        return val.name
    return str(val) if val is not None else None


def _set_modifier_input(modifier, identifier, value, socket_type):
    """Set a modifier input value, coercing types as needed."""
    import bpy

    if socket_type in (
        "NodeSocketObject",
        "NodeSocketCollection",
        "NodeSocketMaterial",
        "NodeSocketImage",
    ):
        coll_map = {
            "NodeSocketObject": bpy.data.objects,
            "NodeSocketCollection": bpy.data.collections,
            "NodeSocketMaterial": bpy.data.materials,
            "NodeSocketImage": bpy.data.images,
        }
        data_coll = coll_map.get(socket_type)
        if data_coll and isinstance(value, str):
            compat.set_modifier_input(modifier, identifier, data_coll.get(value))
            return
    compat.set_modifier_input(modifier, identifier, value)


_CLOTH_PRESETS = {
    "SILK": {
        "quality": 8,
        "mass": 0.15,
        "air_damping": 1.0,
        "tension_stiffness": 5.0,
        "compression_stiffness": 5.0,
        "bending_stiffness": 0.05,
        "tension_damping": 0.0,
        "compression_damping": 0.0,
        "bending_damping": 0.5,
    },
    "COTTON": {
        "quality": 7,
        "mass": 0.3,
        "air_damping": 1.0,
        "tension_stiffness": 15.0,
        "compression_stiffness": 15.0,
        "bending_stiffness": 0.5,
        "tension_damping": 5.0,
        "compression_damping": 5.0,
        "bending_damping": 0.5,
    },
    "DENIM": {
        "quality": 12,
        "mass": 0.4,
        "air_damping": 1.0,
        "tension_stiffness": 40.0,
        "compression_stiffness": 40.0,
        "bending_stiffness": 10.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
    "LEATHER": {
        "quality": 15,
        "mass": 0.4,
        "air_damping": 1.0,
        "tension_stiffness": 80.0,
        "compression_stiffness": 80.0,
        "bending_stiffness": 15.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
    "RUBBER": {
        "quality": 7,
        "mass": 3.0,
        "air_damping": 1.0,
        "tension_stiffness": 15.0,
        "compression_stiffness": 15.0,
        "bending_stiffness": 25.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
    "CANVAS": {
        "quality": 10,
        "mass": 0.35,
        "air_damping": 1.0,
        "tension_stiffness": 30.0,
        "compression_stiffness": 30.0,
        "bending_stiffness": 5.0,
        "tension_damping": 15.0,
        "compression_damping": 15.0,
        "bending_damping": 0.5,
    },
    "TARP": {
        "quality": 12,
        "mass": 0.5,
        "air_damping": 1.0,
        "tension_stiffness": 60.0,
        "compression_stiffness": 60.0,
        "bending_stiffness": 20.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
}


def _markup_with_pillow(render_path, annotations, output_path, Image, ImageDraw, ImageFont):
    """Draw markup annotations using Pillow."""
    img = Image.open(render_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    annotation_count = 0

    for ann in annotations:
        ann_type = ann.get("type", "").lower()
        color_str = ann.get("color", "red")
        thickness = int(ann.get("thickness", 3))

        if ann_type == "arrow":
            start = ann.get("start")
            end = ann.get("end")
            if not start or not end:
                continue
            sx, sy = int(start[0]), int(start[1])
            ex, ey = int(end[0]), int(end[1])

            # Draw the line
            draw.line([(sx, sy), (ex, ey)], fill=color_str, width=thickness)

            # Draw arrowhead
            angle = math.atan2(ey - sy, ex - sx)
            arrow_len = max(10, thickness * 4)
            for da in [math.pi * 0.8, -math.pi * 0.8]:
                ax = ex + arrow_len * math.cos(angle + da)
                ay = ey + arrow_len * math.sin(angle + da)
                draw.line(
                    [(ex, ey), (int(ax), int(ay))],
                    fill=color_str,
                    width=thickness,
                )
            annotation_count += 1

        elif ann_type == "circle":
            center = ann.get("center")
            radius = ann.get("radius")
            if not center or radius is None:
                continue
            cx, cy = int(center[0]), int(center[1])
            r = int(radius)
            draw.ellipse(
                [(cx - r, cy - r), (cx + r, cy + r)],
                outline=color_str,
                width=thickness,
            )
            annotation_count += 1

        elif ann_type == "rectangle":
            start = ann.get("start")
            end = ann.get("end")
            if not start or not end:
                continue
            sx, sy = int(start[0]), int(start[1])
            ex, ey = int(end[0]), int(end[1])
            draw.rectangle(
                [(sx, sy), (ex, ey)],
                outline=color_str,
                width=thickness,
            )
            annotation_count += 1

        elif ann_type == "text":
            position = ann.get("position")
            text = ann.get("text", "")
            if not position or not text:
                continue
            px, py = int(position[0]), int(position[1])
            font_size = int(ann.get("font_size", 24))

            # Try to load a font, fall back to default
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    font_size,
                )
            except (OSError, IOError):
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/TTF/DejaVuSans.ttf",
                        font_size,
                    )
                except (OSError, IOError):
                    font = ImageFont.load_default()

            draw.text((px, py), text, fill=color_str, font=font)
            annotation_count += 1

    # Composite overlay onto image
    result = Image.alpha_composite(img, overlay)
    result.save(output_path)

    return {
        "success": annotation_count > 0,
        "output_path": output_path,
        "annotations_drawn": annotation_count,
        "image_size": list(img.size),
        "method": "pillow",
    }


_MARKUP_COLORS = {
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "lime": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "magenta": (255, 0, 255),
    "cyan": (0, 255, 255),
    "pink": (255, 192, 203),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
}

_MARKUP_TEXT_REASON = (
    "text cannot be drawn: blf draws nothing into an image buffer here "
    "(checked on 4.5 and 5.2) and Pillow is not installed in Blender's Python"
)


def _parse_markup_color(value):
    """CSS-style name or #RGB, #RRGGBB, #RRGGBBAA to (r, g, b, a) floats in 0..1."""
    text = str(value).strip().lower()
    if text in _MARKUP_COLORS:
        r, g, b = _MARKUP_COLORS[text]
        return (r / 255.0, g / 255.0, b / 255.0, 1.0)
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) in (6, 8):
            try:
                parts = [int(digits[i : i + 2], 16) / 255.0 for i in range(0, len(digits), 2)]
            except ValueError:
                raise ValueError(f"unknown color {value!r}") from None
            if len(parts) == 3:
                parts.append(1.0)
            return tuple(parts)
    raise ValueError(f"unknown color {value!r}")


def _segment_mask(xx, yy, x0, y0, x1, y1, half):
    """Boolean mask of pixels within ``half`` of the segment (x0, y0) to (x1, y1)."""
    import numpy as np

    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        t = 0.0
    else:
        t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / length_sq, 0.0, 1.0)
    return np.hypot(xx - (x0 + t * dx), yy - (y0 + t * dy)) <= half


def _markup_point(ann, key):
    value = ann.get(key)
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError(f"'{key}' must be [x, y]")
    return float(value[0]), float(value[1])


def _markup_mask(ann, ann_type, xx, yy):
    """Mask for one shape, in top-left pixel coordinates. Raises ValueError if malformed."""
    thickness = max(float(ann.get("thickness", 3)), 1.0)
    half = max(thickness / 2.0, 0.75)
    if ann_type in ("arrow", "rectangle"):
        sx, sy = _markup_point(ann, "start")
        ex, ey = _markup_point(ann, "end")
        if ann_type == "arrow":
            mask = _segment_mask(xx, yy, sx, sy, ex, ey, half)
            angle = math.atan2(ey - sy, ex - sx)
            head = max(10.0, thickness * 4)
            for delta in (math.pi * 0.8, -math.pi * 0.8):
                hx = ex + head * math.cos(angle + delta)
                hy = ey + head * math.sin(angle + delta)
                mask |= _segment_mask(xx, yy, ex, ey, hx, hy, half)
            return mask
        left, right = sorted((sx, ex))
        top, bottom = sorted((sy, ey))
        outer = (xx >= left) & (xx <= right) & (yy >= top) & (yy <= bottom)
        inner = (
            (xx > left + thickness - 1) & (xx < right - thickness + 1)
            & (yy > top + thickness - 1) & (yy < bottom - thickness + 1)
        )  # fmt: skip
        return outer & ~inner
    import numpy as np

    cx, cy = _markup_point(ann, "center")
    if ann.get("radius") is None:
        raise ValueError("'radius' is required")
    radius = float(ann["radius"])
    return np.abs(np.hypot(xx - cx, yy - cy) - radius) <= half


def _markup_with_pixels(render_path, annotations, output_path):
    """Draw arrows, circles and rectangles straight into the image pixels.

    Needs only Blender and numpy. The image is loaded with ``bpy.data.images.load``,
    drawn into a numpy array and saved to ``output_path``. Annotation coordinates are
    pixels from the top-left; Blender image rows start at the bottom, so the array is
    viewed upside down while drawing. Text is reported in ``skipped``, never faked.
    """
    import numpy as np

    img = bpy.data.images.load(render_path, check_existing=False)
    try:
        width, height = img.size[0], img.size[1]
        channels = img.channels
        if width == 0 or height == 0 or channels != 4:
            raise RuntimeError(f"could not read {render_path} as an RGBA image")
        pixels = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
        canvas = pixels.reshape(height, width, 4)
        top_down = canvas[::-1]  # a view: row 0 is the top of the picture
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)

        drawn = 0
        skipped = []
        for index, ann in enumerate(annotations):
            ann_type = str(ann.get("type", "")).lower()
            if ann_type == "text":
                skipped.append({"index": index, "type": "text", "reason": _MARKUP_TEXT_REASON})
                continue
            if ann_type not in ("arrow", "circle", "rectangle"):
                skipped.append(
                    {"index": index, "type": ann_type, "reason": f"unknown type {ann_type!r}"}
                )
                continue
            try:
                color = _parse_markup_color(ann.get("color", "red"))
                mask = _markup_mask(ann, ann_type, xx, yy)
            except (ValueError, TypeError) as exc:
                skipped.append({"index": index, "type": ann_type, "reason": str(exc)})
                continue
            top_down[mask] = color
            drawn += 1

        result = {
            "success": drawn > 0,
            "output_path": output_path,
            "annotations_drawn": drawn,
            "skipped": skipped,
            "image_size": [width, height],
            "method": "pixels",
        }
        if drawn == 0:
            result["error"] = (
                "Nothing was drawn; see 'skipped' for the reason each annotation was left out"
            )
            return result

        img.pixels.foreach_set(pixels)
        img.update()
        img.filepath_raw = output_path
        ext = os.path.splitext(output_path)[1].lower()
        img.file_format = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
        img.save()
        return result
    finally:
        bpy.data.images.remove(img)


# ── Preset builder helpers ────────────────────────────────────────────


def _add_principled(tree, loc=(0, 0)):
    """Create a Principled BSDF and Material Output, connected."""
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = loc
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    out.location = (loc[0] + 300, loc[1])
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf, out


def _set_color(bsdf, color, fallback):
    """Set Base Color on a Principled BSDF. *color* is an optional RGBA list."""
    c = color if color else fallback
    if len(c) == 3:
        c = list(c) + [1.0]
    bsdf.inputs["Base Color"].default_value = c


def _add_noise(tree, loc=(-600, 0), scale=5.0, detail=2.0, roughness=0.5):
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.location = loc
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    noise.inputs["Roughness"].default_value = roughness
    return noise


def _add_bump(tree, loc=(-200, -300), strength=0.1, distance=0.02):
    bump = tree.nodes.new("ShaderNodeBump")
    bump.location = loc
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    return bump


def _add_color_ramp(tree, loc=(-300, 0)):
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.location = loc
    return ramp


def _add_mapping(tree, loc=(-900, 0), scale_val=None):
    coord = tree.nodes.new("ShaderNodeTexCoord")
    coord.location = (loc[0] - 200, loc[1])
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.location = loc
    tree.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    if scale_val:
        mapping.inputs["Scale"].default_value = (scale_val, scale_val, scale_val)
    return coord, mapping


# ── Individual preset builders ────────────────────────────────────────


def _build_vehicle_paint(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.0, 0.15, 0.6, 1.0])
    bsdf.inputs["Metallic"].default_value = 0.4
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.05

    # Metallic flake noise
    noise = _add_noise(tree, (-600, -100), scale=200.0 * scale, detail=4.0)
    ramp = _add_color_ramp(tree, (-400, -100))
    ramp.color_ramp.elements[0].position = 0.45
    ramp.color_ramp.elements[1].position = 0.55
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    bump = _add_bump(tree, (-200, -300), strength=0.02)
    tree.links.new(ramp.outputs["Color"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_brushed_metal(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.6, 0.6, 0.6, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Anisotropic"].default_value = 0.8

    # Anisotropic brush direction via noise
    noise = _add_noise(tree, (-600, 0), scale=100.0 * scale, detail=0.0, roughness=1.0)
    noise.noise_dimensions = "2D"

    bump = _add_bump(tree, (-200, -300), strength=0.05)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_chrome(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.9, 0.9, 0.9, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.05


def _build_rubber(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.02, 0.02, 0.02, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.8

    noise = _add_noise(tree, (-600, -100), scale=30.0 * scale, detail=6.0)
    bump = _add_bump(tree, (-200, -300), strength=0.15)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_carbon_fiber(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.01, 0.01, 0.01, 1.0])
    bsdf.inputs["Metallic"].default_value = 0.3
    bsdf.inputs["Roughness"].default_value = 0.2
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.05

    # Wave texture for weave pattern
    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, 0)
    wave.inputs["Scale"].default_value = 20.0 * scale
    wave.wave_type = "RINGS"
    wave.rings_direction = "SPHERICAL"

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_asphalt(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.05, 0.05, 0.05, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.9

    noise = _add_noise(tree, (-600, 0), scale=15.0 * scale, detail=8.0)
    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].color = (0.03, 0.03, 0.03, 1.0)
    ramp.color_ramp.elements[1].color = (0.08, 0.08, 0.08, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.3)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_tarmac(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.08, 0.08, 0.08, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.85

    noise = _add_noise(tree, (-600, 0), scale=8.0 * scale, detail=10.0)
    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].color = (0.05, 0.05, 0.05, 1.0)
    ramp.color_ramp.elements[1].color = (0.12, 0.11, 0.10, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.25)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_worn_metal(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.5, 0.5, 0.5, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.4

    # Edge wear via noise + color ramp
    noise = _add_noise(tree, (-800, 0), scale=10.0 * scale, detail=6.0)
    ramp = _add_color_ramp(tree, (-600, 0))
    ramp.color_ramp.elements[0].position = 0.5 - wear * 0.3
    ramp.color_ramp.elements[1].position = 0.5 + wear * 0.2
    ramp.color_ramp.elements[0].color = (0.2, 0.15, 0.1, 1.0)  # worn / rust tint
    ramp.color_ramp.elements[1].color = (0.5, 0.5, 0.5, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness variation
    ramp2 = _add_color_ramp(tree, (-600, -250))
    ramp2.color_ramp.elements[0].position = 0.4
    ramp2.color_ramp.elements[0].color = (0.7, 0.7, 0.7, 1.0)
    ramp2.color_ramp.elements[1].color = (0.3, 0.3, 0.3, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp2.inputs["Fac"])
    tree.links.new(ramp2.outputs["Color"], bsdf.inputs["Roughness"])

    bump = _add_bump(tree, (-200, -400), strength=0.2 * wear)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_glass(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [1.0, 1.0, 1.0, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.0
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["IOR"].default_value = 1.45


def _build_plastic_glossy(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.8, 0.1, 0.1, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["Specular IOR Level"].default_value = 0.5


def _build_plastic_matte(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.3, 0.3, 0.35, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.inputs["Specular IOR Level"].default_value = 0.3


def _build_concrete(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.45, 0.43, 0.40, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.85

    # Voronoi for aggregate
    voronoi = tree.nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (-800, 0)
    voronoi.inputs["Scale"].default_value = 10.0 * scale

    noise = _add_noise(tree, (-800, -250), scale=20.0 * scale, detail=8.0)

    # Mix voronoi and noise for surface variation
    mix = tree.nodes.new("ShaderNodeMix")
    mix.location = (-500, 0)
    mix.data_type = "RGBA"
    mix.inputs[0].default_value = 0.3  # Factor
    tree.links.new(voronoi.outputs["Distance"], mix.inputs[6])
    tree.links.new(noise.outputs["Fac"], mix.inputs[7])

    bump = _add_bump(tree, (-200, -300), strength=0.3)
    tree.links.new(mix.outputs[2], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_fabric(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.2, 0.1, 0.05, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.8
    bsdf.inputs["Sheen Weight"].default_value = 0.5

    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, 0)
    wave.inputs["Scale"].default_value = 40.0 * scale
    wave.wave_type = "BANDS"
    wave.inputs["Distortion"].default_value = 2.0

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_reflective_tape(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.9, 0.9, 0.1, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.1
    bsdf.inputs["Specular IOR Level"].default_value = 1.0
    bsdf.inputs["Emission Color"].default_value = (0.9, 0.9, 0.1, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 0.5

    # Micro-bead pattern
    noise = _add_noise(tree, (-600, -100), scale=200.0 * scale, detail=2.0)
    bump = _add_bump(tree, (-200, -300), strength=0.03)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_led_display(tree, color, wear, scale):
    # Emission-based with grid pattern
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    c = color if color else [0.0, 1.0, 0.0, 1.0]
    if len(c) == 3:
        c = list(c) + [1.0]
    emission.inputs["Color"].default_value = c
    emission.inputs["Strength"].default_value = 5.0

    out = tree.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    tree.links.new(emission.outputs["Emission"], out.inputs["Surface"])

    # Grid pattern via checker
    checker = tree.nodes.new("ShaderNodeTexChecker")
    checker.location = (-600, 0)
    checker.inputs["Scale"].default_value = 50.0 * scale
    checker.inputs["Color1"].default_value = (0.0, 0.0, 0.0, 1.0)
    checker.inputs["Color2"].default_value = (1.0, 1.0, 1.0, 1.0)

    # Multiply emission by grid
    mix = tree.nodes.new("ShaderNodeMix")
    mix.location = (-300, 0)
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    mix.inputs[6].default_value = c
    tree.links.new(checker.outputs["Color"], mix.inputs[7])
    tree.links.new(mix.outputs[2], emission.inputs["Color"])


def _build_rust(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    bsdf.inputs["Metallic"].default_value = 0.6
    bsdf.inputs["Roughness"].default_value = 0.75

    noise = _add_noise(tree, (-800, 0), scale=6.0 * scale, detail=8.0)
    noise2 = _add_noise(tree, (-800, -250), scale=15.0 * scale, detail=4.0)

    ramp = _add_color_ramp(tree, (-600, 0))
    # Rust color gradient
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = (0.1, 0.03, 0.01, 1.0)  # dark rust
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = (0.5, 0.15, 0.02, 1.0)  # bright rust
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    if color:
        # Mix user color with rust based on wear
        mix = tree.nodes.new("ShaderNodeMix")
        mix.location = (-300, 0)
        mix.data_type = "RGBA"
        mix.inputs[0].default_value = wear
        c = list(color) if len(color) >= 4 else list(color) + [1.0]
        mix.inputs[6].default_value = c
        tree.links.new(ramp.outputs["Color"], mix.inputs[7])
        tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    else:
        tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -400), strength=0.4)
    tree.links.new(noise2.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_gold(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [1.0, 0.766, 0.336, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.2


def _build_copper(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.72, 0.45, 0.2, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.25

    # Patina noise
    noise = _add_noise(tree, (-600, 0), scale=5.0 * scale, detail=6.0)
    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].position = 0.5 - wear * 0.3
    ramp.color_ramp.elements[0].color = (0.72, 0.45, 0.2, 1.0)  # copper
    ramp.color_ramp.elements[1].position = 0.5 + wear * 0.3
    ramp.color_ramp.elements[1].color = (0.2, 0.5, 0.4, 1.0)  # green patina
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_scratched_paint(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.0, 0.15, 0.6, 1.0])
    bsdf.inputs["Metallic"].default_value = 0.4
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.05

    # Scratch overlay
    scratch_noise = _add_noise(tree, (-800, -200), scale=50.0 * scale, detail=10.0, roughness=1.0)
    scratch_ramp = _add_color_ramp(tree, (-600, -200))
    thresh = 0.85 - wear * 0.3  # more wear = more scratches
    scratch_ramp.color_ramp.elements[0].position = thresh
    scratch_ramp.color_ramp.elements[1].position = thresh + 0.05
    tree.links.new(scratch_noise.outputs["Fac"], scratch_ramp.inputs["Fac"])

    # Mix paint color with exposed metal at scratches
    mix = tree.nodes.new("ShaderNodeMix")
    mix.location = (-300, 0)
    mix.data_type = "RGBA"
    paint_c = color if color else [0.0, 0.15, 0.6, 1.0]
    if len(paint_c) == 3:
        paint_c = list(paint_c) + [1.0]
    mix.inputs[6].default_value = paint_c
    mix.inputs[7].default_value = (0.5, 0.5, 0.5, 1.0)  # bare metal
    tree.links.new(scratch_ramp.outputs["Color"], mix.inputs[0])
    tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])

    # Scratches affect roughness
    mix_r = tree.nodes.new("ShaderNodeMix")
    mix_r.location = (-300, -250)
    mix_r.data_type = "FLOAT"
    mix_r.inputs[2].default_value = 0.15  # paint roughness
    mix_r.inputs[3].default_value = 0.5  # scratch roughness
    tree.links.new(scratch_ramp.outputs["Color"], mix_r.inputs[0])
    tree.links.new(mix_r.outputs[0], bsdf.inputs["Roughness"])

    # Scratches affect metallic
    mix_m = tree.nodes.new("ShaderNodeMix")
    mix_m.location = (-300, -400)
    mix_m.data_type = "FLOAT"
    mix_m.inputs[2].default_value = 0.0  # paint metallic
    mix_m.inputs[3].default_value = 1.0  # scratch metallic
    tree.links.new(scratch_ramp.outputs["Color"], mix_m.inputs[0])
    tree.links.new(mix_m.outputs[0], bsdf.inputs["Metallic"])


def _build_snow(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.95, 0.95, 0.97, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.inputs["Subsurface Weight"].default_value = 0.1
    bsdf.inputs["Subsurface Radius"].default_value = (0.5, 0.5, 0.5)

    # Sparkle noise
    noise = _add_noise(tree, (-600, -100), scale=100.0 * scale, detail=2.0)
    ramp = _add_color_ramp(tree, (-400, -100))
    ramp.color_ramp.elements[0].position = 0.7
    ramp.color_ramp.elements[1].position = 0.75
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    # Sparkle slightly reduces roughness
    mix_r = tree.nodes.new("ShaderNodeMix")
    mix_r.location = (-200, -200)
    mix_r.data_type = "FLOAT"
    mix_r.inputs[2].default_value = 0.6
    mix_r.inputs[3].default_value = 0.1  # sparkle = very smooth
    tree.links.new(ramp.outputs["Color"], mix_r.inputs[0])
    tree.links.new(mix_r.outputs[0], bsdf.inputs["Roughness"])

    bump = _add_bump(tree, (-200, -400), strength=0.15)
    noise2 = _add_noise(tree, (-600, -400), scale=8.0 * scale, detail=5.0)
    tree.links.new(noise2.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_water(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.01, 0.04, 0.08, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.0
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["IOR"].default_value = 1.33

    # Wave normal
    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, -100)
    wave.inputs["Scale"].default_value = 5.0 * scale
    wave.inputs["Distortion"].default_value = 4.0
    wave.inputs["Detail"].default_value = 3.0
    wave.wave_type = "BANDS"

    bump = _add_bump(tree, (-200, -300), strength=0.05)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_wood(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    bsdf.inputs["Roughness"].default_value = 0.5

    # Wave texture for grain
    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, 0)
    wave.inputs["Scale"].default_value = 3.0 * scale
    wave.inputs["Distortion"].default_value = 8.0
    wave.inputs["Detail"].default_value = 3.0
    wave.wave_type = "BANDS"

    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].color = (0.15, 0.08, 0.03, 1.0)  # dark grain
    ramp.color_ramp.elements[1].color = (0.4, 0.22, 0.1, 1.0)  # light grain
    tree.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])

    if color:
        # Tint the wood grain towards user color
        mix = tree.nodes.new("ShaderNodeMix")
        mix.location = (-200, 0)
        mix.data_type = "RGBA"
        mix.inputs[0].default_value = 0.3
        c = list(color) if len(color) >= 4 else list(color) + [1.0]
        mix.inputs[7].default_value = c
        tree.links.new(ramp.outputs["Color"], mix.inputs[6])
        tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    else:
        tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_brick(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    bsdf.inputs["Roughness"].default_value = 0.8

    brick = tree.nodes.new("ShaderNodeTexBrick")
    brick.location = (-600, 0)
    brick.inputs["Scale"].default_value = 5.0 * scale
    c = color if color else [0.55, 0.2, 0.1, 1.0]
    if len(c) == 3:
        c = list(c) + [1.0]
    brick.inputs["Color1"].default_value = c
    brick.inputs["Color2"].default_value = (c[0] * 0.7, c[1] * 0.7, c[2] * 0.7, 1.0)
    brick.inputs["Mortar"].default_value = (0.7, 0.7, 0.65, 1.0)
    brick.inputs["Mortar Size"].default_value = 0.02

    tree.links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.3)
    tree.links.new(brick.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


# Registry of all preset builders

_PRESET_BUILDERS = {
    "VEHICLE_PAINT": _build_vehicle_paint,
    "BRUSHED_METAL": _build_brushed_metal,
    "CHROME": _build_chrome,
    "RUBBER": _build_rubber,
    "CARBON_FIBER": _build_carbon_fiber,
    "ASPHALT": _build_asphalt,
    "TARMAC": _build_tarmac,
    "WORN_METAL": _build_worn_metal,
    "GLASS": _build_glass,
    "PLASTIC_GLOSSY": _build_plastic_glossy,
    "PLASTIC_MATTE": _build_plastic_matte,
    "CONCRETE": _build_concrete,
    "FABRIC": _build_fabric,
    "REFLECTIVE_TAPE": _build_reflective_tape,
    "LED_DISPLAY": _build_led_display,
    "RUST": _build_rust,
    "GOLD": _build_gold,
    "COPPER": _build_copper,
    "SCRATCHED_PAINT": _build_scratched_paint,
    "SNOW": _build_snow,
    "WATER": _build_water,
    "WOOD": _build_wood,
    "BRICK": _build_brick,
}


def _extract_pbr_values(tree) -> dict:
    """Analyze an existing node tree and extract PBR-relevant values."""
    result = {
        "base_color": [0.8, 0.8, 0.8, 1.0],
        "metallic": 0.0,
        "roughness": 0.5,
        "alpha": 1.0,
        "emission_color": None,
        "emission_strength": 0.0,
        "transmission": 0.0,
        "base_color_image": None,
    }

    for node in tree.nodes:
        # ── Principled BSDF ──
        if node.type == "BSDF_PRINCIPLED":
            if hasattr(node.inputs["Base Color"], "default_value"):
                result["base_color"] = list(node.inputs["Base Color"].default_value)
            result["metallic"] = node.inputs["Metallic"].default_value
            result["roughness"] = node.inputs["Roughness"].default_value
            result["alpha"] = node.inputs["Alpha"].default_value

            if "Emission Color" in node.inputs:
                ec = node.inputs["Emission Color"].default_value
                result["emission_color"] = list(ec)
            if "Emission Strength" in node.inputs:
                result["emission_strength"] = node.inputs["Emission Strength"].default_value

            if "Transmission Weight" in node.inputs:
                result["transmission"] = node.inputs["Transmission Weight"].default_value
            elif "Transmission" in node.inputs:
                result["transmission"] = node.inputs["Transmission"].default_value

            # Check for connected base color texture
            bc_input = node.inputs["Base Color"]
            if bc_input.is_linked:
                linked_node = bc_input.links[0].from_node
                if linked_node.type == "TEX_IMAGE" and linked_node.image:
                    result["base_color_image"] = linked_node.image

            break  # Principled found, no need to keep searching

        # ── Diffuse BSDF fallback ──
        elif node.type == "BSDF_DIFFUSE":
            if hasattr(node.inputs["Color"], "default_value"):
                c = list(node.inputs["Color"].default_value)
                result["base_color"] = c if len(c) == 4 else c + [1.0]
            result["roughness"] = node.inputs["Roughness"].default_value
            # Don't break; a Principled might exist elsewhere

        # ── Glossy BSDF fallback ──
        elif node.type == "BSDF_GLOSSY":
            if hasattr(node.inputs["Color"], "default_value"):
                c = list(node.inputs["Color"].default_value)
                result["base_color"] = c if len(c) == 4 else c + [1.0]
            result["roughness"] = node.inputs["Roughness"].default_value
            result["metallic"] = 1.0

        # ── Emission fallback ──
        elif node.type == "EMISSION":
            if hasattr(node.inputs["Color"], "default_value"):
                result["emission_color"] = list(node.inputs["Color"].default_value)
            if "Strength" in node.inputs:
                result["emission_strength"] = node.inputs["Strength"].default_value

        # ── Glass BSDF fallback ──
        elif node.type == "BSDF_GLASS":
            if hasattr(node.inputs["Color"], "default_value"):
                c = list(node.inputs["Color"].default_value)
                result["base_color"] = c if len(c) == 4 else c + [1.0]
            result["roughness"] = node.inputs["Roughness"].default_value
            result["transmission"] = 1.0

    return result


def _bake_ensure_cycles():
    """Ensure the render engine is set to Cycles for baking."""
    if bpy.context.scene.render.engine != "CYCLES":
        bpy.context.scene.render.engine = "CYCLES"
