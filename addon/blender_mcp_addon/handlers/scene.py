"""Scene-related command handlers."""

import bpy

from .. import compat
from ..utils import serialize_scene


class SceneHandlersMixin:
    """Mixin for scene-related handlers."""

    def _handle_ping(self, params: dict) -> dict:
        """Simple ping/pong for connectivity testing."""
        return {
            "pong": True,
            "blender_version": bpy.app.version_string,
            "handler_count": len(self._handlers),
            "has_ai_list_backends": "ai_list_backends" in self._handlers,
            "has_ai_queue_list": "ai_queue_list" in self._handlers,
        }


    def _handle_scene_info(self, params: dict) -> dict:
        """Get current scene information."""
        return serialize_scene(bpy.context.scene)


    def _handle_scene_new(self, params: dict) -> dict:
        """Create a new scene."""
        name = params.get("name", "New Scene")
        scene = bpy.data.scenes.new(name)
        bpy.context.window.scene = scene
        return {"name": scene.name}


    def _handle_scene_clear(self, params: dict) -> dict:
        """Remove all objects from the current scene."""
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        return {"cleared": True}


    def _handle_scene_set_frame_range(self, params: dict) -> dict:
        """Set animation frame range."""
        scene = bpy.context.scene
        scene.frame_start = params.get("start", 1)
        scene.frame_end = params.get("end", 250)
        return {
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        }


    def _handle_get_version(self, params: dict) -> dict:
        """Get Blender version information."""
        return compat.get_version_info()

    # ========== Object Handlers ==========

