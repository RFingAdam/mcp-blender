"""Meshwire addon: socket server for MCP clients."""

import logging

_logger = logging.getLogger(__name__)
_logger.info("Meshwire addon loaded")

import bpy

from . import security, wire
from .socket_server import BindError, MCPSocketServer, TokenError

# The id Blender files this add-on's preferences under. It is the package name, so it
# follows the add-on when it is installed as an extension. Never spell it out elsewhere.
ADDON_ID = __package__

# The module name of add-ons installed from a zip older than 0.5.0. An extension does not
# replace that copy, so the two can be enabled together.
LEGACY_ADDON_ID = "blender_mcp_addon"
LEGACY_WARNING = (
    f"An older Meshwire add-on ({LEGACY_ADDON_ID}) is still enabled. "
    "Remove it in Preferences > Add-ons, then restart Blender."
)

DEFAULT_HOST = "127.0.0.1"

# Global server instance
_server: MCPSocketServer | None = None


def get_server() -> MCPSocketServer | None:
    """Get the global server instance."""
    global _server
    return _server


def get_preferences():
    """Return the add-on preferences, or None when Blender has no entry for the add-on.

    There is no entry when the add-on was loaded without being enabled, as the test
    harness does. Callers then use the defaults.
    """
    try:
        addon = bpy.context.preferences.addons.get(ADDON_ID)
        return addon.preferences if addon else None
    except Exception:
        return None


def legacy_addon_enabled() -> bool:
    """True when the older copy is enabled next to this one.

    The test harness loads the source folder under the old name. That is this add-on, not
    a second copy, so it never counts.
    """
    if ADDON_ID == LEGACY_ADDON_ID:
        return False
    try:
        return LEGACY_ADDON_ID in bpy.context.preferences.addons
    except Exception:
        return False


def server_address() -> tuple[str, int]:
    """Host and port from Preferences. Port 0 means pick the first free one."""
    prefs = get_preferences()
    if prefs is None:
        return DEFAULT_HOST, 0
    return prefs.host, prefs.port


class MeshwirePreferences(bpy.types.AddonPreferences):
    """Add-on settings. Preferences are stored per user, so a shared .blend file carries none."""

    bl_idname = ADDON_ID

    host: bpy.props.StringProperty(
        name="Host",
        description="Address the server binds to",
        default=DEFAULT_HOST,
    )
    port: bpy.props.IntProperty(
        name="Port",
        description=f"0 picks the first free port from {wire.PORT_FIRST} to {wire.PORT_LAST}. Otherwise 1024 to 65535",
        default=0,
        min=0,
        max=65535,
    )
    rodin_api_key: bpy.props.StringProperty(
        name="Rodin API key",
        subtype="PASSWORD",
        default="",
    )
    meshy_api_key: bpy.props.StringProperty(
        name="Meshy API key",
        subtype="PASSWORD",
        default="",
    )
    comfyui_workflow: bpy.props.StringProperty(
        name="ComfyUI workflow",
        description="Workflow JSON file ComfyUI generation uses instead of the built-in one",
        subtype="FILE_PATH",
        default="",
    )

    triposr_python: bpy.props.StringProperty(
        name="TripoSR Python",
        description="System Python with torch for TripoSR. Empty uses python3",
        subtype="FILE_PATH",
        default="",
    )
    triposr_path: bpy.props.StringProperty(
        name="TripoSR folder",
        description="TripoSR install folder",
        subtype="DIR_PATH",
        default="",
    )
    triposr_model: bpy.props.StringProperty(
        name="TripoSR model",
        description="Model id or folder for TripoSR. Empty uses the built-in model",
        default="",
    )
    hunyuan3d_model: bpy.props.StringProperty(
        name="Hunyuan3D model",
        description="Model id or folder for Hunyuan3D. Empty uses the built-in model",
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.prop(self, "rodin_api_key")
        layout.prop(self, "meshy_api_key")
        layout.prop(self, "comfyui_workflow")
        layout.prop(self, "triposr_python")
        layout.prop(self, "triposr_path")
        layout.prop(self, "triposr_model")
        layout.prop(self, "hunyuan3d_model")


class MCP_OT_StartServer(bpy.types.Operator):
    """Start the MCP socket server"""

    bl_idname = "mcp.start_server"
    bl_label = "Start Server"
    bl_description = "Start the MCP socket server for AI integration"

    def execute(self, context):
        global _server
        if _server is not None and _server.is_running:
            self.report({"WARNING"}, "Server is already running")
            return {"CANCELLED"}

        if legacy_addon_enabled():
            self.report({"ERROR"}, LEGACY_WARNING)
            return {"CANCELLED"}

        host, port = server_address()
        server = MCPSocketServer(host=host, port=port)
        try:
            server.start()
        except (BindError, TokenError) as e:
            _server = None
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        _server = server
        self.report({"INFO"}, f"MCP server started on {host}:{server.port}")
        if server.discovery_warning:
            self.report({"WARNING"}, server.discovery_warning)
        return {"FINISHED"}


class MCP_OT_StopServer(bpy.types.Operator):
    """Stop the MCP socket server"""

    bl_idname = "mcp.stop_server"
    bl_label = "Stop Server"
    bl_description = "Stop the MCP socket server"

    def execute(self, context):
        global _server
        if _server is None or not _server.is_running:
            self.report({"WARNING"}, "Server is not running")
            return {"CANCELLED"}

        _server.stop()
        _server = None
        self.report({"INFO"}, "MCP server stopped")
        return {"FINISHED"}


class MESHWIRE_OT_TogglePython(bpy.types.Operator):
    """Allow or refuse the execute_script tool until Blender closes"""

    bl_idname = "meshwire.toggle_python"
    bl_label = "Allow Python"
    bl_description = (
        "Let connected clients run Python through execute_script. "
        "Off every time Blender starts, and never saved"
    )

    def execute(self, context):
        on = not security.python_allowed()
        security.set_python_allowed(on)
        self.report({"WARNING" if on else "INFO"}, f"Python execution {'on' if on else 'off'}")
        return {"FINISHED"}


class MESHWIRE_OT_CopyToken(bpy.types.Operator):
    """Copy the Meshwire token to the clipboard"""

    bl_idname = "meshwire.copy_token"
    bl_label = "Copy token"
    bl_description = (
        "Copy the token a Meshwire server needs to connect, for setting MESHWIRE_TOKEN on "
        "another machine. Anyone holding it can drive this Blender"
    )

    def execute(self, context):
        if _server is not None and _server.is_running:
            token = _server.token  # what the running server accepts, not whatever the file says now
        else:
            try:
                token = wire.ensure_token()
            except OSError as e:
                self.report(
                    {"ERROR"},
                    f"Could not read or create the Meshwire token at {wire.token_path()}: {e}",
                )
                return {"CANCELLED"}
        context.window_manager.clipboard = token
        self.report({"INFO"}, "Token copied to the clipboard")
        return {"FINISHED"}


class MCP_PT_ServerPanel(bpy.types.Panel):
    """MCP Server control panel"""

    bl_label = "Meshwire"
    bl_idname = "MCP_PT_server_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Meshwire"

    def draw(self, context):
        layout = self.layout
        prefs = get_preferences()

        # Connection settings
        box = layout.box()
        box.label(text="Connection Settings")
        if prefs is not None:
            box.prop(prefs, "host")
            box.prop(prefs, "port")
        else:
            box.label(text="Enable the add-on in Preferences to edit these")

        # Server status and controls
        layout.separator()

        running = get_server()
        if legacy_addon_enabled() and not (running is not None and running.is_running):
            layout.label(text=LEGACY_WARNING, icon="ERROR")
            return

        global _server
        if _server is not None and _server.is_running:
            layout.label(text="Status: Running", icon="PLAY")
            layout.operator("mcp.stop_server", icon="PAUSE")
            # Show connected clients count
            client_count = _server.client_count
            layout.label(text=f"Connected clients: {client_count}")
            if _server.discovery_warning:
                layout.label(text=_server.discovery_warning, icon="ERROR")
            layout.operator("meshwire.copy_token", icon="COPYDOWN")
        else:
            layout.label(text="Status: Stopped", icon="SNAP_FACE")
            layout.operator("mcp.start_server", icon="PLAY")

        # Python execution
        layout.separator()
        row = layout.row()
        on = security.python_allowed()
        row.alert = on
        row.operator(
            "meshwire.toggle_python",
            text="Allow Python: on" if on else "Allow Python: off",
            icon="ERROR" if on else "CHECKBOX_DEHLT",
            depress=on,
        )
        layout.label(text="Off every time Blender starts")


classes = (
    MeshwirePreferences,
    MCP_OT_StartServer,
    MCP_OT_StopServer,
    MESHWIRE_OT_TogglePython,
    MESHWIRE_OT_CopyToken,
    MCP_PT_ServerPanel,
)


def register():
    """Register addon classes."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister addon classes."""
    global _server
    if _server is not None and _server.is_running:
        _server.stop()
        _server = None

    # The switch is runtime-only. Disabling the add-on leaves it off.
    security.set_python_allowed(False)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
