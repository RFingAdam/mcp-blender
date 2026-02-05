"""MSFS animation tools and tags."""

from typing import Any

import bpy

# MSFS animation tags/events
ANIMATION_TAGS = {
    # State events
    "start": "ANIM_START",
    "end": "ANIM_END",
    "loop_start": "ANIM_LOOP_START",
    "loop_end": "ANIM_LOOP_END",

    # Sound triggers
    "sound": "ANIM_SOUND",
    "sound_start": "ANIM_SOUND_START",
    "sound_stop": "ANIM_SOUND_STOP",

    # Effect triggers
    "effect": "ANIM_EFFECT",
    "effect_start": "ANIM_EFFECT_START",
    "effect_stop": "ANIM_EFFECT_STOP",

    # Visibility
    "show": "ANIM_VISIBILITY_SHOW",
    "hide": "ANIM_VISIBILITY_HIDE",

    # Custom event
    "event": "ANIM_EVENT",
}

# Animation behavior types
ANIMATION_BEHAVIORS = {
    "once": "PLAY_ONCE",
    "loop": "LOOP",
    "ping_pong": "PING_PONG",
    "hold": "HOLD",
}


def add_animation_tag(
    object_name: str,
    tag_type: str,
    frame: int,
    tag_data: str | None = None,
) -> dict[str, Any]:
    """Add an animation tag/event marker.

    Tags are stored as markers and custom properties for glTF export.

    Args:
        object_name: Name of the animated object
        tag_type: Type of tag (start, end, sound, effect, etc.)
        frame: Frame number for the tag
        tag_data: Optional data string (e.g., sound file name)

    Returns:
        Dictionary with tag info
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    if tag_type not in ANIMATION_TAGS:
        return {
            "error": f"Invalid tag type: {tag_type}",
            "valid_types": list(ANIMATION_TAGS.keys()),
        }

    msfs_tag = ANIMATION_TAGS[tag_type]

    # Create timeline marker
    marker_name = f"{object_name}_{msfs_tag}_{frame}"
    scene = bpy.context.scene

    # Remove existing marker at same frame with same name pattern
    for marker in scene.timeline_markers:
        if marker.frame == frame and marker.name.startswith(f"{object_name}_{msfs_tag}"):
            scene.timeline_markers.remove(marker)
            break

    # Add new marker
    marker = scene.timeline_markers.new(marker_name, frame=frame)

    # Store tag data as custom property on the object
    if "MSFS_animation_tags" not in obj:
        obj["MSFS_animation_tags"] = {}

    tags = dict(obj["MSFS_animation_tags"])
    tag_key = f"{frame}_{tag_type}"
    tags[tag_key] = {
        "type": msfs_tag,
        "frame": frame,
        "data": tag_data or "",
    }
    obj["MSFS_animation_tags"] = tags

    return {
        "object": object_name,
        "tag_type": tag_type,
        "msfs_tag": msfs_tag,
        "frame": frame,
        "data": tag_data,
        "marker_name": marker_name,
    }


def remove_animation_tag(
    object_name: str,
    frame: int,
    tag_type: str | None = None,
) -> dict[str, Any]:
    """Remove an animation tag.

    Args:
        object_name: Name of the animated object
        frame: Frame number of the tag
        tag_type: Optional specific tag type to remove

    Returns:
        Dictionary with removal info
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    removed = []
    scene = bpy.context.scene

    # Remove markers
    markers_to_remove = []
    for marker in scene.timeline_markers:
        if marker.frame == frame and marker.name.startswith(object_name):
            if tag_type is None or ANIMATION_TAGS.get(tag_type, "") in marker.name:
                markers_to_remove.append(marker)

    for marker in markers_to_remove:
        removed.append(marker.name)
        scene.timeline_markers.remove(marker)

    # Remove from custom properties
    if "MSFS_animation_tags" in obj:
        tags = dict(obj["MSFS_animation_tags"])
        keys_to_remove = []
        for key in tags:
            if key.startswith(f"{frame}_"):
                if tag_type is None or key.endswith(f"_{tag_type}"):
                    keys_to_remove.append(key)
        for key in keys_to_remove:
            del tags[key]
        obj["MSFS_animation_tags"] = tags

    return {
        "object": object_name,
        "frame": frame,
        "removed_markers": removed,
        "count": len(removed),
    }


def setup_visibility_animation(
    object_name: str,
    visible_range: tuple[int, int] | None = None,
    hidden_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Set up visibility animation for an object.

    Args:
        object_name: Name of the object
        visible_range: Frame range when object is visible (start, end)
        hidden_range: Frame range when object is hidden (start, end)

    Returns:
        Dictionary with visibility animation info
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    keyframes = []

    # Ensure animation data exists
    if not obj.animation_data:
        obj.animation_data_create()

    # Create action if needed
    if not obj.animation_data.action:
        action = bpy.data.actions.new(name=f"{object_name}_visibility")
        obj.animation_data.action = action

    # Set up visibility keyframes
    if visible_range:
        start, end = visible_range
        # Hidden before visible range
        if start > 1:
            obj.hide_viewport = True
            obj.hide_render = True
            obj.keyframe_insert(data_path="hide_viewport", frame=start - 1)
            obj.keyframe_insert(data_path="hide_render", frame=start - 1)
            keyframes.append({"frame": start - 1, "visible": False})

        # Visible during range
        obj.hide_viewport = False
        obj.hide_render = False
        obj.keyframe_insert(data_path="hide_viewport", frame=start)
        obj.keyframe_insert(data_path="hide_render", frame=start)
        keyframes.append({"frame": start, "visible": True})

        # Hidden after range
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=end + 1)
        obj.keyframe_insert(data_path="hide_render", frame=end + 1)
        keyframes.append({"frame": end + 1, "visible": False})

    if hidden_range:
        start, end = hidden_range
        # Visible before hidden range
        if start > 1:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.keyframe_insert(data_path="hide_viewport", frame=start - 1)
            obj.keyframe_insert(data_path="hide_render", frame=start - 1)
            keyframes.append({"frame": start - 1, "visible": True})

        # Hidden during range
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=start)
        obj.keyframe_insert(data_path="hide_render", frame=start)
        keyframes.append({"frame": start, "visible": False})

        # Visible after range
        obj.hide_viewport = False
        obj.hide_render = False
        obj.keyframe_insert(data_path="hide_viewport", frame=end + 1)
        obj.keyframe_insert(data_path="hide_render", frame=end + 1)
        keyframes.append({"frame": end + 1, "visible": True})

    # Mark as MSFS visibility animation
    obj["MSFS_visibility_animation"] = True

    return {
        "object": object_name,
        "keyframes": keyframes,
        "visible_range": visible_range,
        "hidden_range": hidden_range,
    }


def configure_animation_loop(
    object_name: str,
    behavior: str = "loop",
    loop_start: int | None = None,
    loop_end: int | None = None,
    loop_count: int = 0,
) -> dict[str, Any]:
    """Configure animation looping behavior.

    Args:
        object_name: Name of the animated object
        behavior: Animation behavior (once, loop, ping_pong, hold)
        loop_start: Start frame of loop (defaults to action start)
        loop_end: End frame of loop (defaults to action end)
        loop_count: Number of loops (0 = infinite)

    Returns:
        Dictionary with loop configuration
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    if behavior not in ANIMATION_BEHAVIORS:
        return {
            "error": f"Invalid behavior: {behavior}",
            "valid_behaviors": list(ANIMATION_BEHAVIORS.keys()),
        }

    # Get action
    if not obj.animation_data or not obj.animation_data.action:
        return {"error": f"Object has no animation: {object_name}"}

    action = obj.animation_data.action

    # Determine frame range
    if loop_start is None:
        loop_start = int(action.frame_range[0])
    if loop_end is None:
        loop_end = int(action.frame_range[1])

    # Store loop configuration as custom properties
    obj["MSFS_anim_behavior"] = ANIMATION_BEHAVIORS[behavior]
    obj["MSFS_anim_loop_start"] = loop_start
    obj["MSFS_anim_loop_end"] = loop_end
    obj["MSFS_anim_loop_count"] = loop_count

    # Add loop markers
    if behavior in ("loop", "ping_pong"):
        add_animation_tag(object_name, "loop_start", loop_start)
        add_animation_tag(object_name, "loop_end", loop_end)

    return {
        "object": object_name,
        "behavior": behavior,
        "msfs_behavior": ANIMATION_BEHAVIORS[behavior],
        "loop_start": loop_start,
        "loop_end": loop_end,
        "loop_count": loop_count,
    }


def list_animation_tags(object_name: str | None = None) -> dict[str, Any]:
    """List all animation tags.

    Args:
        object_name: Optional filter by object name

    Returns:
        Dictionary with animation tags
    """
    result = {"tags": [], "markers": []}

    scene = bpy.context.scene

    # Get markers
    for marker in scene.timeline_markers:
        if object_name is None or marker.name.startswith(object_name):
            result["markers"].append({
                "name": marker.name,
                "frame": marker.frame,
            })

    # Get tags from objects
    for obj in bpy.data.objects:
        if object_name and obj.name != object_name:
            continue

        if "MSFS_animation_tags" in obj:
            tags = obj["MSFS_animation_tags"]
            for key, tag_data in tags.items():
                result["tags"].append({
                    "object": obj.name,
                    "key": key,
                    "type": tag_data.get("type"),
                    "frame": tag_data.get("frame"),
                    "data": tag_data.get("data"),
                })

    result["tag_count"] = len(result["tags"])
    result["marker_count"] = len(result["markers"])

    return result


def get_animation_info(object_name: str) -> dict[str, Any]:
    """Get comprehensive animation info for an object.

    Args:
        object_name: Name of the object

    Returns:
        Dictionary with animation information
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    info = {
        "object": object_name,
        "has_animation": obj.animation_data is not None,
    }

    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        info["action_name"] = action.name
        info["frame_range"] = list(action.frame_range)
        info["fcurve_count"] = len(action.fcurves)

        # Get animated properties
        animated_props = set()
        for fc in action.fcurves:
            animated_props.add(fc.data_path)
        info["animated_properties"] = list(animated_props)

    # MSFS-specific info
    if "MSFS_anim_behavior" in obj:
        info["msfs_behavior"] = obj["MSFS_anim_behavior"]
    if "MSFS_anim_loop_start" in obj:
        info["loop_start"] = obj["MSFS_anim_loop_start"]
    if "MSFS_anim_loop_end" in obj:
        info["loop_end"] = obj["MSFS_anim_loop_end"]
    if "MSFS_animation_tags" in obj:
        info["tag_count"] = len(obj["MSFS_animation_tags"])

    return info
