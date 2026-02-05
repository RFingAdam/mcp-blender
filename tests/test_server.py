"""Tests for MCP server."""


from mcp_blender.server import TOOLS, create_server


class TestToolDefinitions:
    """Test that tool definitions are valid."""

    def test_all_tools_have_required_fields(self):
        """All tools should have name, description, and inputSchema."""
        for tool in TOOLS:
            assert tool.name, "Tool missing name"
            assert tool.description, f"Tool {tool.name} missing description"
            assert tool.inputSchema, f"Tool {tool.name} missing inputSchema"

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
            schema = tool.inputSchema
            assert schema.get("type") == "object", f"Tool {tool.name} schema type should be 'object'"
            assert "properties" in schema, f"Tool {tool.name} schema missing 'properties'"
            assert "required" in schema, f"Tool {tool.name} schema missing 'required'"

    def test_required_fields_exist_in_properties(self):
        """Required fields should be defined in properties."""
        for tool in TOOLS:
            schema = tool.inputSchema
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            for req in required:
                assert req in properties, f"Tool {tool.name}: required field '{req}' not in properties"

    def test_tool_count(self):
        """Verify expected number of tools."""
        # 5 scene + 10 object + 6 material + 5 modifier + 7 animation + 5 render + 6 export + 4 external + 20 MSFS + 18 livery = 86
        assert len(TOOLS) >= 80, f"Expected at least 80 tools, got {len(TOOLS)}"


class TestServerCreation:
    """Test server creation."""

    def test_create_server(self):
        """Server should be created successfully."""
        server = create_server("127.0.0.1", 9876)
        assert server is not None
        assert server.name == "mcp-blender"


class TestToolCategories:
    """Test that tools are organized by category."""

    def test_scene_tools(self):
        """Scene tools should exist."""
        scene_tools = [t for t in TOOLS if t.name.startswith("blender_scene_") or t.name == "blender_get_version"]
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
        animation_tools = [t for t in TOOLS if t.name.startswith("blender_keyframe_") or t.name.startswith("blender_action_") or t.name.startswith("blender_animation_")]
        assert len(animation_tools) >= 5

    def test_render_tools(self):
        """Render tools should exist."""
        render_tools = [t for t in TOOLS if t.name.startswith("blender_render_")]
        assert len(render_tools) >= 5

    def test_export_tools(self):
        """Export tools should exist."""
        export_tools = [t for t in TOOLS if t.name.startswith("blender_export_") or t.name.startswith("blender_import_")]
        assert len(export_tools) >= 5

    def test_external_tools(self):
        """External integration tools should exist."""
        external_tools = [t for t in TOOLS if t.name.startswith("blender_polyhaven_") or t.name.startswith("blender_ai_")]
        assert len(external_tools) >= 4

    def test_msfs_tools(self):
        """MSFS content creation tools should exist."""
        msfs_tools = [t for t in TOOLS if t.name.startswith("blender_msfs_") and "livery" not in t.name]
        # LOD (4) + Materials (4) + Collision (4) + Animation (4) + Export (4) = 20
        assert len(msfs_tools) >= 18, f"Expected at least 18 MSFS tools, got {len(msfs_tools)}"

        # Verify key MSFS tool categories
        lod_tools = [t for t in msfs_tools if "lod" in t.name]
        assert len(lod_tools) >= 4, "Should have LOD tools"

        material_tools = [t for t in msfs_tools if "material" in t.name or "glass" in t.name or "emissive" in t.name]
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
        assert len(livery_tools) >= 16, f"Expected at least 16 livery tools, got {len(livery_tools)}"

        # Verify key livery tool categories
        paint_tools = [t for t in livery_tools if any(x in t.name for x in ["paint", "brush", "layer"])]
        assert len(paint_tools) >= 3, "Should have paint tools"

        template_tools = [t for t in livery_tools if "template" in t.name or "aircraft" in t.name]
        assert len(template_tools) >= 3, "Should have template tools"

        transfer_tools = [t for t in livery_tools if any(x in t.name for x in ["transfer", "analyze", "extract", "map"])]
        assert len(transfer_tools) >= 4, "Should have transfer tools"

        export_tools = [t for t in livery_tools if any(x in t.name for x in ["export", "package", "dds", "validate"])]
        assert len(export_tools) >= 4, "Should have livery export tools"
