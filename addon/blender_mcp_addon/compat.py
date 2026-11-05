"""Blender compatibility layer, from 4.2 LTS through 5.x.

Every API difference between Blender series goes through this module. Each
function detects what the running Blender offers (``hasattr``, ``bl_rna``
properties and enum items, ``dir(bpy.ops.x)``) and never compares version
numbers, so a series nobody tested yet still works if it offers a known shape.
Handlers call these functions and do not branch on the version themselves.
"""

import bpy


def _enum_identifiers(rna_type, prop: str) -> set:
    """Identifiers of an enum property on an RNA type, or an empty set."""
    try:
        return {item.identifier for item in rna_type.bl_rna.properties[prop].enum_items}
    except (AttributeError, KeyError):
        return set()


def _has_compositing_group() -> bool:
    return "compositing_node_group" in bpy.types.Scene.bl_rna.properties


def get_version_info() -> dict:
    """Get Blender version information and which API shapes this build offers."""
    return {
        "version": list(bpy.app.version),
        "version_string": bpy.app.version_string,
        "features": {
            "layered_actions": "layers" in bpy.types.Action.bl_rna.properties,
            "annotation_datablock": _annotation_scene_property() == "annotation",
            "compositing_node_group": _has_compositing_group(),
            "modifier_properties_api": "properties" in bpy.types.NodesModifier.bl_rna.properties,
        },
    }


def get_fcurves(action, slot=None):
    """Get the FCurves of an action, for either action layout.

    A layered action keeps them in channelbags, one per slot, inside the
    keyframe strips of its layers. A legacy action keeps them in
    ``action.fcurves``. Pass ``slot`` to keep only that slot's curves.
    """
    layers = getattr(action, "layers", None)
    if layers is not None and len(layers) > 0:
        fcurves = []
        for layer in layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", ()):
                    if slot is not None and bag.slot_handle != slot.handle:
                        continue
                    fcurves.extend(bag.fcurves)
        return fcurves
    return list(getattr(action, "fcurves", ()))


def create_action(name: str):
    """Create a new action. Slots, where offered, appear when keys are inserted."""
    return bpy.data.actions.new(name)


def assign_action_to_object(obj, action):
    """Assign an action to an object. Blender binds the slot where slots exist."""
    if obj.animation_data is None:
        obj.animation_data_create()
    obj.animation_data.action = action


def get_action_keyframe_points(action, data_path: str, index: int = -1):
    """
    Get keyframe points for a data path from an action.

    Args:
        action: The action to search
        data_path: The data path (e.g., 'location')
        index: Array index (-1 for all)

    Returns:
        List of (frame, value) tuples
    """
    keyframes = []
    fcurves = get_fcurves(action)

    for fc in fcurves:
        if fc.data_path == data_path:
            if index == -1 or fc.array_index == index:
                for kp in fc.keyframe_points:
                    keyframes.append({
                        "frame": kp.co[0],
                        "value": kp.co[1],
                        "array_index": fc.array_index,
                        "interpolation": kp.interpolation,
                    })

    return keyframes


def get_object_keyframes(obj):
    """
    Get all keyframes for an object.

    Returns:
        Dict with data_path as keys and list of keyframe info as values
    """
    if obj.animation_data is None or obj.animation_data.action is None:
        return {}

    action = obj.animation_data.action
    slot = getattr(obj.animation_data, "action_slot", None)

    keyframes = {}
    for fc in get_fcurves(action, slot):
        path = fc.data_path
        if path not in keyframes:
            keyframes[path] = []

        for kp in fc.keyframe_points:
            keyframes[path].append({
                "frame": kp.co[0],
                "value": kp.co[1],
                "array_index": fc.array_index,
            })

    return keyframes


def insert_keyframe_compat(obj, data_path: str, frame: int, index: int = -1):
    """
    Insert a keyframe with version compatibility.

    This handles differences in how keyframes are inserted between versions.
    """
    # Store current frame
    current_frame = bpy.context.scene.frame_current

    # Set to target frame
    bpy.context.scene.frame_set(frame)

    # Insert keyframe
    obj.keyframe_insert(data_path=data_path, index=index, frame=frame)

    # Restore frame
    bpy.context.scene.frame_set(current_frame)

    return True


def delete_keyframe_compat(obj, data_path: str, frame: int, index: int = -1):
    """
    Delete a keyframe with version compatibility.
    """
    try:
        obj.keyframe_delete(data_path=data_path, index=index, frame=frame)
        return True
    except RuntimeError:
        # Keyframe might not exist
        return False


def list_actions():
    """List all actions in the file."""
    actions = []
    for action in bpy.data.actions:
        info = {
            "name": action.name,
            "users": action.users,
            "frame_range": list(action.frame_range),
            "fcurves": len(get_fcurves(action)),
        }
        if hasattr(action, "slots"):
            info["slots"] = len(action.slots)
        actions.append(info)

    return actions


def get_principled_bsdf_inputs():
    """
    Get the mapping of Principled BSDF input names across versions.

    Input names are the same for 4.2+ and 5.0.
    """
    return {
        "base_color": "Base Color",
        "metallic": "Metallic",
        "roughness": "Roughness",
        "alpha": "Alpha",
        "specular_ior_level": "Specular IOR Level",
        "specular_tint": "Specular Tint",
        "anisotropic": "Anisotropic",
        "sheen_weight": "Sheen Weight",
        "coat_weight": "Coat Weight",
        "emission_color": "Emission Color",
        "emission_strength": "Emission Strength",
    }


def convert_mathutils_value(value):
    """
    Convert mathutils values to standard Python types.

    In Blender 5.0, mathutils uses float32 internally.
    This ensures consistent float handling.
    """
    if hasattr(value, "__iter__") and not isinstance(value, str):
        return [float(v) for v in value]
    return float(value)


def get_eevee_engine_name():
    """
    Get the EEVEE engine identifier this Blender registers.

    EEVEE Next shipped as ``BLENDER_EEVEE_NEXT`` in 4.2, then 5.0 dropped the
    legacy engine and gave the name ``BLENDER_EEVEE`` back to it. Read the
    engine enum rather than guess, so the answer holds for series nobody has
    tried yet.
    """
    identifiers = _enum_identifiers(bpy.types.RenderSettings, "engine")
    if "BLENDER_EEVEE_NEXT" in identifiers:
        return "BLENDER_EEVEE_NEXT"
    return "BLENDER_EEVEE"


_EEVEE_ALIASES = ("EEVEE", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")


def resolve_render_engine(name: str) -> str:
    """Map any spelling of EEVEE to the identifier this Blender registers.

    Other engines pass through unchanged.
    """
    if name.upper() in _EEVEE_ALIASES:
        return get_eevee_engine_name()
    return name


def boolean_solver(name: str) -> str:
    """Map a Boolean modifier solver to one this Blender offers.

    The quick solver is ``FAST`` in 4.x and ``FLOAT`` in 5.x. Any other name
    passes through, and Blender reports it if it is not valid.
    """
    offered = _enum_identifiers(bpy.types.BooleanModifier, "solver")
    swaps = {"FAST": "FLOAT", "FLOAT": "FAST"}
    if name not in offered and swaps.get(name) in offered:
        return swaps[name]
    return name


def select_edge_loops(ring: bool = False) -> None:
    """Select the edge loop or ring through each selected edge (edit mode).

    4.x offers one operator with a ``ring`` flag. 5.x split it into a loop
    operator and a ring operator.
    """
    ops = dir(bpy.ops.mesh)
    if "loop_multi_select" in ops:
        bpy.ops.mesh.loop_multi_select(ring=ring)
    elif ring:
        bpy.ops.mesh.select_edge_ring_multi()
    else:
        bpy.ops.mesh.select_edge_loop_multi()


def has_legacy_auto_smooth(mesh) -> bool:
    """True when the mesh still has the old ``use_auto_smooth`` switch."""
    return hasattr(mesh, "use_auto_smooth")


def get_modifier_input(modifier, identifier):
    """Read a Geometry Nodes modifier input by its socket identifier.

    Newer Blender keeps the inputs in ``modifier.properties.inputs``; older
    Blender stores them as custom properties on the modifier. Returns None
    for an input that does not exist or has no value (such as geometry).
    """
    inputs = _modifier_inputs(modifier)
    if inputs is not None:
        socket = getattr(inputs, identifier, None)
        return getattr(socket, "value", None)
    try:
        return modifier[identifier]
    except KeyError:
        return None


def set_modifier_input(modifier, identifier, value) -> None:
    """Set a Geometry Nodes modifier input by its socket identifier."""
    inputs = _modifier_inputs(modifier)
    if inputs is not None:
        socket = getattr(inputs, identifier, None)
        if socket is None:
            raise KeyError(identifier)
        socket.value = value
        return
    modifier[identifier] = value


def _modifier_inputs(modifier):
    props = getattr(modifier, "properties", None)
    return getattr(props, "inputs", None)


def set_material_shadow_hashed(mat) -> None:
    """Use hashed shadows on a transparent material where Blender offers the setting.

    ``Material.shadow_method`` survives in 4.2 but is gone from 4.5, where
    shadow behaviour follows the material's render method instead. Detect the
    property rather than compare versions.
    """
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "HASHED"


def safe_alembic_export(filepath: str, **kwargs) -> bool:
    """Export to Alembic through the operator. Returns False if it is unavailable."""
    try:
        bpy.ops.wm.alembic_export(filepath=filepath, **kwargs)
        return True
    except (AttributeError, RuntimeError):
        return False


# ---- Annotations and grease pencil -------------------------------------------
#
# Annotations have been their own datablock (``bpy.data.annotations``, pointed
# to by ``Scene.annotation``) since grease pencil v3 took over the object type.
# Before that they were legacy grease pencil data, pointed to by
# ``Scene.grease_pencil``. Grease pencil objects use the v3 data API where it
# exists, and the legacy one otherwise.


def _annotation_scene_property() -> str:
    props = bpy.types.Scene.bl_rna.properties
    return "annotation" if "annotation" in props else "grease_pencil"


def get_annotation_data(scene, create: bool = False, name: str = "Annotations"):
    """Return the scene's annotation datablock, optionally creating it."""
    prop = _annotation_scene_property()
    data = getattr(scene, prop)
    if data is None and create:
        collection = (
            bpy.data.annotations if hasattr(bpy.data, "annotations") else bpy.data.grease_pencils
        )
        data = collection.new(name)
        setattr(scene, prop, data)
    return data


def can_add_annotation_strokes() -> bool:
    """True when Python can create a stroke in an annotation frame.

    Some series dropped ``strokes.new`` from annotation frames without adding
    a replacement, and the only way left to draw is an interactive operator.
    """
    name = "AnnotationFrame" if hasattr(bpy.types, "AnnotationFrame") else "GPencilFrame"
    frame_type = getattr(bpy.types, name, None)
    if frame_type is None:
        return False
    srna = frame_type.bl_rna.properties["strokes"].srna
    return srna is not None and "new" in srna.functions.keys()


def add_annotation_stroke(frame, points, thickness: int, strength: float = 1.0) -> None:
    """Add one 3D-space stroke through ``points`` to an annotation frame.

    Check :func:`can_add_annotation_strokes` first.
    """
    stroke = frame.strokes.new()
    stroke.display_mode = "3DSPACE"
    if hasattr(stroke, "line_width"):
        stroke.line_width = thickness
    stroke.points.add(len(points))
    for i, pt in enumerate(points):
        stroke.points[i].co = (pt[0], pt[1], pt[2])
        if hasattr(stroke.points[i], "pressure"):
            stroke.points[i].pressure = 1.0
            stroke.points[i].strength = strength


def new_grease_pencil(name: str):
    """Create grease pencil data for an object."""
    # Test with hasattr: an empty collection is falsy.
    if hasattr(bpy.data, "grease_pencils_v3"):
        return bpy.data.grease_pencils_v3.new(name)
    return bpy.data.grease_pencils.new(name)


def layer_name(layer) -> str:
    """Name of a grease pencil or annotation layer (``info`` or ``name``)."""
    return layer.info if hasattr(layer, "info") else layer.name


def add_grease_pencil_strokes(gpd, strokes, color, frame_number: int, name: str = "Layer"):
    """Create a layer on grease pencil data and draw strokes on it.

    ``strokes`` is a list of ``(points, thickness)`` pairs with at least two
    points each. Returns the new layer.
    """
    layer = gpd.layers.new(name)
    frame = layer.frames.new(frame_number)
    if hasattr(frame, "drawing"):
        drawing = frame.drawing
        drawing.add_strokes(sizes=[len(pts) for pts, _ in strokes])
        new_strokes = list(drawing.strokes)[-len(strokes):]
        for stroke, (pts, thickness) in zip(new_strokes, strokes):
            for point, pt in zip(stroke.points, pts):
                point.position = (pt[0], pt[1], pt[2])
                point.radius = thickness / 2000.0
                point.opacity = color[3]
                point.vertex_color = (color[0], color[1], color[2], 1.0)
        return layer
    if hasattr(layer, "color"):
        layer.color = (color[0], color[1], color[2])
    for pts, thickness in strokes:
        add_annotation_stroke(frame, pts, thickness)
    return layer


# ---- Compositor ----------------------------------------------------------------


def get_compositor_tree(scene):
    """Return the scene's compositor node tree, creating it if there is none.

    Newer Blender keeps it in ``Scene.compositing_node_group``; older Blender
    keeps it in ``Scene.node_tree`` behind ``use_nodes``.
    """
    if _has_compositing_group():
        tree = scene.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        return tree
    scene.use_nodes = True
    return scene.node_tree


def new_compositor_output(tree):
    """Add the node that carries the composite to the render, and return it.

    Where the compositor is a node group, its group output is the result; elsewhere
    it is the Composite node. Both follow the same detection as the tree lookup.
    """
    if not _has_compositing_group():
        return tree.nodes.new("CompositorNodeComposite")
    has_output = any(
        item.item_type == "SOCKET" and item.in_out == "OUTPUT"
        for item in tree.interface.items_tree
    )
    if not has_output:
        tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    return tree.nodes.new("NodeGroupOutput")
