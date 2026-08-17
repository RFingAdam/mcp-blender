"""Blender version compatibility layer for 4.2 LTS and 5.0."""

import bpy

# Version detection
BLENDER_VERSION = bpy.app.version
IS_5_0_OR_LATER = BLENDER_VERSION >= (5, 0, 0)
IS_4_2_OR_LATER = BLENDER_VERSION >= (4, 2, 0)


def get_version_info() -> dict:
    """Get Blender version information."""
    return {
        "version": list(BLENDER_VERSION),
        "version_string": bpy.app.version_string,
        "is_5_0": IS_5_0_OR_LATER,
        "is_4_2": IS_4_2_OR_LATER,
    }


def get_fcurves(action):
    """
    Get FCurves from an action, handling API differences between versions.

    In Blender 5.0, actions use a new slotted animation system.
    In Blender 4.2 and earlier, actions use direct fcurves.
    """
    if IS_5_0_OR_LATER:
        # Blender 5.0+ uses slots/layers/strips/channels
        fcurves = []
        for slot in action.slots:
            for layer in slot.layers:
                for strip in layer.strips:
                    fcurves.extend(strip.channels)
        return fcurves
    else:
        # Blender 4.2 and earlier use direct fcurves
        return list(action.fcurves)


def create_action(name: str):
    """
    Create a new action with proper initialization for the Blender version.
    """
    action = bpy.data.actions.new(name)

    if IS_5_0_OR_LATER:
        # Blender 5.0 uses the new slotted animation system
        # Slots are created automatically when keyframes are inserted
        # but we can also create them explicitly
        pass

    return action


def assign_action_to_object(obj, action):
    """
    Assign an action to an object, handling version differences.
    """
    if obj.animation_data is None:
        obj.animation_data_create()

    if IS_5_0_OR_LATER:
        # In 5.0, we assign the action and Blender handles slot binding
        obj.animation_data.action = action
        # For explicit slot binding (if needed):
        # slot = action.slots.get(obj.name) or action.slots.new(id_type='OBJECT')
        # obj.animation_data.action_slot = slot
    else:
        # In 4.2, direct assignment works
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
    fcurves = get_fcurves(action)

    keyframes = {}
    for fc in fcurves:
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
    """
    List all actions in the file with compatibility info.
    """
    actions = []
    for action in bpy.data.actions:
        info = {
            "name": action.name,
            "users": action.users,
            "frame_range": list(action.frame_range),
        }

        if IS_5_0_OR_LATER:
            info["slots"] = len(action.slots) if hasattr(action, "slots") else 0
        else:
            info["fcurves"] = len(action.fcurves)

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
    Get the correct EEVEE engine identifier for the Blender version.

    EEVEE Next shipped as ``BLENDER_EEVEE_NEXT`` in 4.2, then 5.0 dropped the
    legacy engine and renamed it back to ``BLENDER_EEVEE``. Query the enum
    rather than mapping from the version number so the addon keeps working on
    future releases too.
    """
    try:
        identifiers = {
            item.identifier
            for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
        }
    except (AttributeError, KeyError):
        identifiers = set()

    if "BLENDER_EEVEE_NEXT" in identifiers:
        return "BLENDER_EEVEE_NEXT"
    if "BLENDER_EEVEE" in identifiers:
        return "BLENDER_EEVEE"
    # Enum unavailable (headless edge cases); fall back to the version mapping.
    return "BLENDER_EEVEE_NEXT" if IS_4_2_OR_LATER else "BLENDER_EEVEE"


def get_compositor_node_mapping():
    """
    Get node type mappings for compositor nodes that changed between versions.
    """
    if IS_5_0_OR_LATER:
        return {
            "CompositorNodeGamma": "ShaderNodeGamma",
            # Add more mappings as needed
        }
    return {}


def safe_alembic_export(filepath: str, **kwargs) -> bool:
    """
    Safely export to Alembic, handling removal in 5.0.

    Returns True if export was successful, False if not available.
    """
    if IS_5_0_OR_LATER:
        # Scene.alembic_export was removed in 5.0
        # Use the operator instead
        try:
            bpy.ops.wm.alembic_export(filepath=filepath, **kwargs)
            return True
        except AttributeError:
            return False
    else:
        try:
            bpy.ops.wm.alembic_export(filepath=filepath, **kwargs)
            return True
        except Exception:
            return False
