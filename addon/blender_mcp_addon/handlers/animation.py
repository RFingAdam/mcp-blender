"""Animation-related command handlers."""

import bpy

from .. import compat
from ..utils import get_object_or_error
from ..validation import (
    ValidationError,
    require_param,
)


class AnimationHandlersMixin:
    """Mixin for animation-related handlers."""

    def _handle_keyframe_insert(self, params: dict) -> dict:
        """Insert keyframe for an object property."""
        object_name = require_param(params, "object_name", str)
        data_path = require_param(params, "data_path", str)

        obj = get_object_or_error(object_name)
        frame = params.get("frame", bpy.context.scene.frame_current)
        index = params.get("index", -1)

        # Optionally set value before inserting keyframe
        if "value" in params:
            value = params["value"]
            try:
                if index >= 0:
                    getattr(obj, data_path)[index] = value
                else:
                    setattr(obj, data_path, value)
            except (AttributeError, TypeError, IndexError) as e:
                raise ValidationError(f"Cannot set {data_path}: {e}")

        try:
            compat.insert_keyframe_compat(obj, data_path, frame, index)
        except RuntimeError as e:
            raise ValidationError(f"Failed to insert keyframe: {e}")

        return {
            "object": obj.name,
            "data_path": data_path,
            "frame": frame,
            "index": index,
        }


    def _handle_keyframe_delete(self, params: dict) -> dict:
        """Delete keyframe from an object property."""
        object_name = require_param(params, "object_name", str)
        data_path = require_param(params, "data_path", str)

        obj = get_object_or_error(object_name)
        frame = params.get("frame", bpy.context.scene.frame_current)
        index = params.get("index", -1)

        success = compat.delete_keyframe_compat(obj, data_path, frame, index)

        return {
            "object": obj.name,
            "data_path": data_path,
            "frame": frame,
            "deleted": success,
        }


    def _handle_keyframe_list(self, params: dict) -> dict:
        """List all keyframes for an object."""
        object_name = require_param(params, "object_name", str)
        obj = get_object_or_error(object_name)

        keyframes = compat.get_object_keyframes(obj)

        return {
            "object": obj.name,
            "has_animation": obj.animation_data is not None,
            "action": obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None,
            "keyframes": keyframes,
        }


    def _handle_action_create(self, params: dict) -> dict:
        """Create a new action and optionally assign to object."""
        name = params.get("name", "Action")
        action = compat.create_action(name)

        result = {
            "action": action.name,
            "frame_range": list(action.frame_range),
        }

        if params.get("object_name"):
            obj = get_object_or_error(params["object_name"])
            compat.assign_action_to_object(obj, action)
            result["assigned_to"] = obj.name

        return result


    def _handle_action_list(self, params: dict) -> dict:
        """List all actions in the file."""
        actions = compat.list_actions()
        return {"actions": actions, "count": len(actions)}


    def _handle_animation_play(self, params: dict) -> dict:
        """Play or pause the animation playback."""
        play = params.get("play", True)
        if play:
            bpy.ops.screen.animation_play()
        else:
            bpy.ops.screen.animation_cancel()
        return {
            "playing": play,
            "frame": bpy.context.scene.frame_current,
        }


    def _handle_animation_goto_frame(self, params: dict) -> dict:
        """Jump to a specific frame."""
        frame = require_param(params, "frame", int)

        scene = bpy.context.scene
        scene.frame_set(frame)

        return {
            "frame": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        }

    # ========== Render Handlers ==========

