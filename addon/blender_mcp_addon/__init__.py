"""Blender MCP Addon - Socket server for MCP integration."""

bl_info = {
    "name": "MCP Server Addon",
    "author": "MCP Blender Contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > MCP Server",
    "description": "Socket server for Model Context Protocol integration with AI assistants",
    "category": "Interface",
}

import bpy

from .socket_server import MCPSocketServer

# Global server instance
_server: MCPSocketServer | None = None


def get_server() -> MCPSocketServer | None:
    """Get the global server instance."""
    global _server
    return _server


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

        props = context.scene.mcp_server_props
        _server = MCPSocketServer(host=props.host, port=props.port)
        _server.start()
        self.report({"INFO"}, f"MCP server started on {props.host}:{props.port}")
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


class MCP_PT_ServerPanel(bpy.types.Panel):
    """MCP Server control panel"""

    bl_label = "MCP Server"
    bl_idname = "MCP_PT_server_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP Server"

    def draw(self, context):
        layout = self.layout
        props = context.scene.mcp_server_props

        # Connection settings
        box = layout.box()
        box.label(text="Connection Settings")
        row = box.row()
        row.prop(props, "host")
        row = box.row()
        row.prop(props, "port")

        # Server status and controls
        layout.separator()

        global _server
        if _server is not None and _server.is_running:
            layout.label(text="Status: Running", icon="PLAY")
            layout.operator("mcp.stop_server", icon="PAUSE")
            # Show connected clients count
            client_count = _server.client_count
            layout.label(text=f"Connected clients: {client_count}")
        else:
            layout.label(text="Status: Stopped", icon="SNAP_FACE")
            layout.operator("mcp.start_server", icon="PLAY")


class MCPServerProperties(bpy.types.PropertyGroup):
    """Properties for MCP server configuration"""

    host: bpy.props.StringProperty(
        name="Host",
        description="Host address to bind the server",
        default="127.0.0.1",
    )
    port: bpy.props.IntProperty(
        name="Port",
        description="Port to listen on",
        default=9876,
        min=1024,
        max=65535,
    )


classes = (
    MCPServerProperties,
    MCP_OT_StartServer,
    MCP_OT_StopServer,
    MCP_PT_ServerPanel,
)


def register():
    """Register addon classes and properties."""
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mcp_server_props = bpy.props.PointerProperty(type=MCPServerProperties)


def unregister():
    """Unregister addon classes and properties."""
    global _server
    if _server is not None and _server.is_running:
        _server.stop()
        _server = None

    del bpy.types.Scene.mcp_server_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
