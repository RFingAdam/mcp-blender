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


    def _handle_server_restart(self, params: dict) -> dict:
        """Cycle the MCP socket server: stop, then start a fresh listener.

        This recovers a connection that has gone stale/unresponsive without
        needing the user to click anything in the addon panel. It does
        **not** reload addon source code - if handler code on disk changed,
        this restart will keep serving the old code, exactly like it did
        before the restart. Only Blender's own "Reload Scripts" (or a full
        Blender restart) picks up new code, and neither of those can safely
        be triggered from in here: reloading the very module that is
        handling this request tears down the server without restarting it,
        so it requires a manual restart anyway - there is no advantage to
        attempting it remotely.

        Because stopping the server closes the socket this very request
        arrived on, the response below will typically fail to reach the
        caller (connection reset). That is expected, not an error: reconnect
        and call ``ping`` to confirm the new server is up.
        """
        bpy.ops.mcp.stop_server()
        bpy.ops.mcp.start_server()
        return {"success": True, "note": "Server cycled; reconnect and ping to confirm."}

    # ========== Object Handlers ==========

