"""Tests for MCP server."""

import asyncio

from mcp_types import CallToolRequestParams

from mcp_blender import server as server_module
from mcp_blender.server import TOOLS, create_server


class TestToolDefinitions:
    """Test that tool definitions are valid."""

    def test_all_tools_have_required_fields(self):
        """All tools should have name, description, and inputSchema."""
        for tool in TOOLS:
            assert tool.name, "Tool missing name"
            assert tool.description, f"Tool {tool.name} missing description"
            assert tool.input_schema, f"Tool {tool.name} missing inputSchema"

    def test_tool_names_are_unique(self):
        """Tool names should be unique."""
        names = [tool.name for tool in TOOLS]
        assert len(names) == len(set(names)), "Duplicate tool names found"

    def test_tool_names_have_blender_prefix(self):
        """All tool names should start with 'blender_'."""
        for tool in TOOLS:
            assert tool.name.startswith("blender_"), f"Tool {tool.name} missing 'blender_' prefix"

    def test_input_schemas_are_valid(self):
        """Input schemas should be valid JSON Schema objects."""
        for tool in TOOLS:
            schema = tool.input_schema
            assert schema.get("type") == "object", (
                f"Tool {tool.name} schema type should be 'object'"
            )
            assert "properties" in schema, f"Tool {tool.name} schema missing 'properties'"
            assert "required" in schema, f"Tool {tool.name} schema missing 'required'"

    def test_required_fields_exist_in_properties(self):
        """Required fields should be defined in properties."""
        for tool in TOOLS:
            schema = tool.input_schema
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            for req in required:
                assert req in properties, (
                    f"Tool {tool.name}: required field '{req}' not in properties"
                )

    def test_tool_count(self):
        """Verify expected number of tools."""
        # 155 base + 63 new tools:
        # 7 materials + 7 measurement + 8 collections/system + 6 baking
        # + 7 geonode + 8 sculpting + 8 rigging + 6 physics + 6 annotation
        assert len(TOOLS) == 225, f"Expected 225 tools, got {len(TOOLS)}"


class TestServerCreation:
    """Test server creation."""

    def test_create_server(self):
        """Server should be created successfully."""
        server = create_server("127.0.0.1", 9876)
        assert server is not None
        assert server.name == "meshwire"


class TestToolCategories:
    """Test that tools are organized by category."""

    def test_scene_tools(self):
        """Scene tools should exist."""
        scene_tools = [
            t
            for t in TOOLS
            if t.name.startswith("blender_scene_") or t.name == "blender_get_version"
        ]
        assert len(scene_tools) >= 5

    def test_object_tools(self):
        """Object tools should exist."""
        object_tools = [t for t in TOOLS if t.name.startswith("blender_object_")]
        assert len(object_tools) >= 10

    def test_material_tools(self):
        """Material tools should exist."""
        material_tools = [t for t in TOOLS if t.name.startswith("blender_material_")]
        assert len(material_tools) >= 6

    def test_modifier_tools(self):
        """Modifier tools should exist."""
        modifier_tools = [t for t in TOOLS if t.name.startswith("blender_modifier_")]
        assert len(modifier_tools) >= 4

    def test_animation_tools(self):
        """Animation tools should exist."""
        animation_tools = [
            t
            for t in TOOLS
            if t.name.startswith("blender_keyframe_")
            or t.name.startswith("blender_action_")
            or t.name.startswith("blender_animation_")
        ]
        assert len(animation_tools) >= 5

    def test_render_tools(self):
        """Render tools should exist."""
        render_tools = [t for t in TOOLS if t.name.startswith("blender_render_")]
        assert len(render_tools) >= 5

    def test_export_tools(self):
        """Export tools should exist."""
        export_tools = [
            t
            for t in TOOLS
            if t.name.startswith("blender_export_") or t.name.startswith("blender_import_")
        ]
        assert len(export_tools) >= 5

    def test_external_tools(self):
        """External integration tools should exist."""
        external_tools = [
            t
            for t in TOOLS
            if t.name.startswith("blender_polyhaven_") or t.name.startswith("blender_ai_")
        ]
        assert len(external_tools) >= 8

    def test_texture_tools(self):
        """AI texture generation tools should exist."""
        texture_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_ai_generate_texture",
                "blender_ai_generate_texture_sync",
                "blender_ai_generate_reference_image",
                "blender_ai_inpaint_texture",
                "blender_ai_texture_from_render",
            )
        ]
        assert len(texture_tools) == 5, f"Expected 5 texture tools, got {len(texture_tools)}"

    def test_msfs_tools(self):
        """MSFS content creation tools should exist."""
        msfs_tools = [
            t for t in TOOLS if t.name.startswith("blender_msfs_") and "livery" not in t.name
        ]
        # LOD (4) + Materials (4) + Collision (4) + Animation (4) + Export (4) = 20
        assert len(msfs_tools) >= 18, f"Expected at least 18 MSFS tools, got {len(msfs_tools)}"

        # Verify key MSFS tool categories
        lod_tools = [t for t in msfs_tools if "lod" in t.name]
        assert len(lod_tools) >= 4, "Should have LOD tools"

        material_tools = [
            t
            for t in msfs_tools
            if "material" in t.name or "glass" in t.name or "emissive" in t.name
        ]
        assert len(material_tools) >= 3, "Should have material tools"

        collision_tools = [t for t in msfs_tools if "collision" in t.name]
        assert len(collision_tools) >= 4, "Should have collision tools"

        animation_tools = [t for t in msfs_tools if "animation" in t.name or "visibility" in t.name]
        assert len(animation_tools) >= 3, "Should have animation tools"

        export_tools = [t for t in msfs_tools if "export" in t.name or "validate" in t.name]
        assert len(export_tools) >= 3, "Should have export tools"

    def test_msfs_livery_tools(self):
        """MSFS livery tools should exist."""
        livery_tools = [t for t in TOOLS if "livery" in t.name]
        # Painting (7) + Templates (3) + Transfer (4) + Export (4) = 18
        assert len(livery_tools) >= 16, (
            f"Expected at least 16 livery tools, got {len(livery_tools)}"
        )

        # Verify key livery tool categories
        paint_tools = [
            t for t in livery_tools if any(x in t.name for x in ["paint", "brush", "layer"])
        ]
        assert len(paint_tools) >= 3, "Should have paint tools"

        template_tools = [t for t in livery_tools if "template" in t.name or "aircraft" in t.name]
        assert len(template_tools) >= 3, "Should have template tools"

        transfer_tools = [
            t
            for t in livery_tools
            if any(x in t.name for x in ["transfer", "analyze", "extract", "map"])
        ]
        assert len(transfer_tools) >= 4, "Should have transfer tools"

        export_tools = [
            t
            for t in livery_tools
            if any(x in t.name for x in ["export", "package", "dds", "validate"])
        ]
        assert len(export_tools) >= 4, "Should have livery export tools"

    def test_vehicle_modeling_toolkit(self):
        """Vehicle modeling toolkit tools should exist."""
        # Selection tools (6)
        selection_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_mesh_select",
                "blender_mesh_select_trait",
                "blender_mesh_select_linked_flat",
                "blender_mesh_select_shortest_path",
                "blender_mesh_get_selection",
                "blender_mesh_select_edge_loops",
            )
        ]
        assert len(selection_tools) == 6, f"Expected 6 selection tools, got {len(selection_tools)}"

        # Shading tools (4)
        shading_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_shade_smooth",
                "blender_mesh_crease",
                "blender_mesh_mark_sharp",
                "blender_mesh_mark_seam",
            )
        ]
        assert len(shading_tools) == 4, f"Expected 4 shading tools, got {len(shading_tools)}"

        # Topology tools (7)
        topology_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_mesh_dissolve",
                "blender_mesh_merge",
                "blender_mesh_bridge",
                "blender_mesh_fill",
                "blender_mesh_subdivide",
                "blender_mesh_edge_slide",
                "blender_mesh_tris_to_quads",
            )
        ]
        assert len(topology_tools) == 7, f"Expected 7 topology tools, got {len(topology_tools)}"

        # Cutting tools (4)
        cutting_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_mesh_knife_project",
                "blender_mesh_bisect",
                "blender_mesh_separate_selected",
                "blender_mesh_split",
            )
        ]
        assert len(cutting_tools) == 4, f"Expected 4 cutting tools, got {len(cutting_tools)}"

        # Reference tools (3)
        reference_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_silhouette_compare",
                "blender_measure",
                "blender_reference_image_setup",
            )
        ]
        assert len(reference_tools) == 3, f"Expected 3 reference tools, got {len(reference_tools)}"

        # Detail tools (3)
        detail_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_array_along_curve",
                "blender_scatter_on_surface",
                "blender_collection_instance",
            )
        ]
        assert len(detail_tools) == 3, f"Expected 3 detail tools, got {len(detail_tools)}"

        # Transform tools (3)
        transform_tools = [
            t
            for t in TOOLS
            if t.name
            in (
                "blender_mesh_proportional_transform",
                "blender_mesh_shrinkwrap",
                "blender_mesh_flatten",
            )
        ]
        assert len(transform_tools) == 3, f"Expected 3 transform tools, got {len(transform_tools)}"


class _RecordingClient:
    def __init__(self):
        self.calls = []

    async def send_command(self, command, arguments, timeout=None):
        self.calls.append((command, dict(arguments), timeout))
        return {"success": True}


def _call(monkeypatch, name, arguments):
    client = _RecordingClient()

    async def fake_get_client(host="127.0.0.1", port=9876):
        return client

    monkeypatch.setattr(server_module, "get_client", fake_get_client)
    entry = create_server("127.0.0.1", 9876)._request_handlers["tools/call"]
    asyncio.run(entry.handler(None, CallToolRequestParams(name=name, arguments=arguments)))
    return client.calls[0]


def _short(name):
    return name.removeprefix("blender_")


def _props(name):
    return next(t for t in TOOLS if t.name == name).input_schema["properties"]


class TestTimeoutReachesHandler:
    def test_timeout_reaches_a_handler_that_reads_it(self, monkeypatch):
        """Only a tool whose handler reads timeout receives it."""
        assert server_module.HANDLER_READS_TIMEOUT
        for short in server_module.HANDLER_READS_TIMEOUT:
            assert "timeout" in _props("blender_" + short), short
            command, args, timeout = _call(monkeypatch, "blender_" + short, {"timeout": 7})
            assert args.get("timeout") == 7, short
            # The server outwaits the handler's own limit, so the handler's reply arrives.
            assert timeout == 7 + server_module.REPLY_MARGIN, short
            assert command == short

    def test_server_wait_timeout_is_not_forwarded(self, monkeypatch):
        """A declared timeout that no handler reads is the server's wait only."""
        waiting = [
            t.name
            for t in TOOLS
            if "timeout" in t.input_schema["properties"]
            and _short(t.name) not in server_module.HANDLER_READS_TIMEOUT
        ]
        assert waiting
        for name in waiting:
            _, args, timeout = _call(monkeypatch, name, {"timeout": 7})
            assert "timeout" not in args, name
            assert timeout == 7, name

    def test_timeout_without_declaration_still_sets_wait(self, monkeypatch):
        _, args, timeout = _call(monkeypatch, "blender_scene_info", {})
        assert timeout == 30.0
        assert "timeout" not in args

    def test_timeout_is_not_forwarded_when_undeclared(self, monkeypatch):
        _, args, timeout = _call(monkeypatch, "blender_scene_info", {"timeout": 5})
        assert timeout == 5
        assert "timeout" not in args


class TestLongRunning:
    def test_every_bake_tool_is_long_running_and_declares_timeout(self):
        bakes = [t.name for t in TOOLS if _short(t.name).startswith("bake_")]
        assert bakes
        for name in bakes:
            assert _short(name) in server_module.LONG_RUNNING, name
            assert "timeout" in _props(name), name

    def test_long_running_names_only_real_tools(self):
        real = {_short(t.name) for t in TOOLS}
        assert sorted(server_module.LONG_RUNNING - real) == []

    def test_required_tools_are_long_running(self):
        required = {
            "msfs_export_model",
            "msfs_batch_export_lods",
            "physics_simulate",
            "physics_fluid_quick",
            "render_image",
            "material_preview_render",
            "ai_pipeline_generate",
            "ai_generate_model_sync",
            "ai_generate_texture_sync",
            "ai_auto_uv",
            "render_animation",
            "render_multi_angle",
            "ai_generate_model",
        }
        assert required <= server_module.LONG_RUNNING

    def test_every_long_running_tool_declares_a_documented_timeout(self):
        for short in server_module.LONG_RUNNING:
            prop = _props("blender_" + short).get("timeout")
            assert prop is not None, short
            if short in server_module.HANDLER_READS_TIMEOUT:
                continue
            assert prop["type"] == "number", short
            assert "server waits" in prop["description"], short
            assert "600" in prop["description"], short

    def test_long_running_default_wait_is_600(self, monkeypatch):
        for short in sorted(server_module.LONG_RUNNING):
            _, args, timeout = _call(monkeypatch, "blender_" + short, {})
            assert timeout == 600.0, short
            assert "timeout" not in args or short in server_module.HANDLER_READS_TIMEOUT, short

    def test_handler_reading_a_timeout_is_not_a_server_wait_tool(self):
        assert server_module.HANDLER_READS_TIMEOUT <= {
            _short(t.name) for t in TOOLS if "timeout" in t.input_schema["properties"]
        }
