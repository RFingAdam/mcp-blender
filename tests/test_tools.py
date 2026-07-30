"""Tests for tool functionality.

These tests use a mock server to test that tools are properly wired up.
"""


from mcp_blender.server import TOOLS


class TestToolSchemas:
    """Test tool input schemas."""

    def test_object_create_schema(self):
        """Test object_create tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_object_create")
        schema = tool.inputSchema

        # Should have type property with enum
        assert "type" in schema["properties"]
        assert "enum" in schema["properties"]["type"]
        assert "cube" in schema["properties"]["type"]["enum"]
        assert "sphere" in schema["properties"]["type"]["enum"]

        # type should be required
        assert "type" in schema["required"]

    def test_object_transform_schema(self):
        """Test object_transform tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_object_transform")
        schema = tool.inputSchema

        # Should have name, location, rotation, scale
        assert "name" in schema["properties"]
        assert "location" in schema["properties"]
        assert "rotation" in schema["properties"]
        assert "scale" in schema["properties"]

        # Only name should be required
        assert schema["required"] == ["name"]

    def test_material_set_color_schema(self):
        """Test material_set_color tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_material_set_color")
        schema = tool.inputSchema

        assert "material_name" in schema["properties"]
        assert "color" in schema["properties"]
        assert schema["properties"]["color"]["type"] == "array"

        # Both should be required
        assert "material_name" in schema["required"]
        assert "color" in schema["required"]

    def test_modifier_add_schema(self):
        """Test modifier_add tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_modifier_add")
        schema = tool.inputSchema

        assert "object_name" in schema["properties"]
        assert "modifier_type" in schema["properties"]
        # modifier_type uses description with examples instead of enum for flexibility
        assert "description" in schema["properties"]["modifier_type"]
        assert "SUBSURF" in schema["properties"]["modifier_type"]["description"]

    def test_render_set_engine_schema(self):
        """Test render_set_engine tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_render_set_engine")
        schema = tool.inputSchema

        assert "engine" in schema["properties"]
        assert "enum" in schema["properties"]["engine"]
        engines = schema["properties"]["engine"]["enum"]
        assert "CYCLES" in engines
        assert "BLENDER_EEVEE_NEXT" in engines

    def test_export_gltf_schema(self):
        """Test export_gltf tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_export_gltf")
        schema = tool.inputSchema

        assert "filepath" in schema["properties"]
        assert "export_format" in schema["properties"]
        assert "selected_only" in schema["properties"]
        assert "filepath" in schema["required"]

    def test_polyhaven_search_schema(self):
        """Test polyhaven_search tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_polyhaven_search")
        schema = tool.inputSchema

        assert "query" in schema["properties"]
        assert "asset_type" in schema["properties"]
        assert "enum" in schema["properties"]["asset_type"]
        assert "hdris" in schema["properties"]["asset_type"]["enum"]

    def test_ai_generate_model_schema(self):
        """Test ai_generate_model tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_generate_model")
        schema = tool.inputSchema

        # Should have prompt and image_path for text-to-3D and image-to-3D
        assert "prompt" in schema["properties"]
        assert "image_path" in schema["properties"]
        # Style should have enum with options
        assert "style" in schema["properties"]
        assert "enum" in schema["properties"]["style"]
        assert "realistic" in schema["properties"]["style"]["enum"]
        # Quality and output_format should also have enums
        assert "quality" in schema["properties"]
        assert "output_format" in schema["properties"]
        # Neither prompt nor image_path is strictly required (one or the other)
        assert schema["required"] == []

    def test_ai_generate_texture_schema(self):
        """Test ai_generate_texture tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_generate_texture")
        schema = tool.inputSchema

        assert "prompt" in schema["properties"]
        assert "object_name" in schema["properties"]
        assert "resolution" in schema["properties"]
        assert "auto_apply" in schema["properties"]
        assert "prompt" in schema["required"]

    def test_ai_generate_texture_sync_schema(self):
        """Test ai_generate_texture_sync tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_generate_texture_sync")
        schema = tool.inputSchema

        assert "prompt" in schema["properties"]
        assert "object_name" in schema["properties"]
        assert "resolution" in schema["properties"]
        assert "auto_apply" in schema["properties"]
        assert "timeout" in schema["properties"]
        assert schema["properties"]["timeout"]["type"] == "integer"
        assert "prompt" in schema["required"]

    def test_ai_generate_reference_image_schema(self):
        """Test ai_generate_reference_image tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_generate_reference_image")
        schema = tool.inputSchema

        assert "prompt" in schema["properties"]
        assert "resolution" in schema["properties"]
        assert "prompt" in schema["required"]

    def test_ai_inpaint_texture_schema(self):
        """Test ai_inpaint_texture tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_inpaint_texture")
        schema = tool.inputSchema

        assert "image_path" in schema["properties"]
        assert "mask_path" in schema["properties"]
        assert "prompt" in schema["properties"]
        assert "strength" in schema["properties"]
        assert "image_path" in schema["required"]
        assert "mask_path" in schema["required"]
        assert "prompt" in schema["required"]

    def test_ai_texture_from_render_schema(self):
        """Test ai_texture_from_render tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_texture_from_render")
        schema = tool.inputSchema

        assert "object_name" in schema["properties"]
        assert "prompt" in schema["properties"]
        assert "control_type" in schema["properties"]
        assert "enum" in schema["properties"]["control_type"]
        assert "depth" in schema["properties"]["control_type"]["enum"]
        assert "normal" in schema["properties"]["control_type"]["enum"]
        assert "object_name" in schema["required"]
        assert "prompt" in schema["required"]


    def test_ai_evaluate_schema(self):
        """Test ai_evaluate tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_evaluate")
        schema = tool.inputSchema

        assert "render_path" in schema["properties"]
        assert "category" in schema["properties"]
        assert "enum" in schema["properties"]["category"]
        assert "model" in schema["properties"]["category"]["enum"]
        assert "texture" in schema["properties"]["category"]["enum"]
        assert "animation" in schema["properties"]["category"]["enum"]
        assert "reference_image" in schema["properties"]
        assert schema["required"] == ["render_path"]

    def test_ai_refine_schema(self):
        """Test ai_refine tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_ai_refine")
        schema = tool.inputSchema

        assert "object_name" in schema["properties"]
        assert "prompt" in schema["properties"]
        assert "category" in schema["properties"]
        assert "max_iterations" in schema["properties"]
        assert "quality_threshold" in schema["properties"]
        assert "materials" in schema["properties"]
        assert schema["properties"]["materials"]["type"] == "array"
        assert "object_name" in schema["required"]
        assert "prompt" in schema["required"]

    def test_text_create_schema(self):
        """Test text_create tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_text_create")
        schema = tool.inputSchema

        assert "content" in schema["properties"]
        assert "extrude" in schema["properties"]
        assert "bevel_depth" in schema["properties"]
        assert "align_x" in schema["properties"]
        assert "LEFT" in schema["properties"]["align_x"]["enum"]
        assert "fill_type" in schema["properties"]
        assert "BOTH" in schema["properties"]["fill_type"]["enum"]
        assert schema["required"] == ["content"]

    def test_text_to_mesh_schema(self):
        """Test text_to_mesh tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_text_to_mesh")
        schema = tool.inputSchema

        assert "object_name" in schema["properties"]
        assert "keep_original" in schema["properties"]
        assert schema["required"] == ["object_name"]

    def test_object_rename_schema(self):
        """Test object_rename tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_object_rename")
        schema = tool.inputSchema

        assert "name" in schema["properties"]
        assert "new_name" in schema["properties"]
        assert schema["required"] == ["name", "new_name"]

    def test_object_get_bounds_schema(self):
        """Test object_get_bounds tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_object_get_bounds")
        schema = tool.inputSchema

        assert "name" in schema["properties"]
        assert schema["required"] == ["name"]

    def test_mesh_triangulate_schema(self):
        """Test mesh_triangulate tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_mesh_triangulate")
        schema = tool.inputSchema

        assert "object_name" in schema["properties"]
        assert "quad_method" in schema["properties"]
        assert "BEAUTY" in schema["properties"]["quad_method"]["enum"]
        assert "ngon_method" in schema["properties"]
        assert schema["required"] == ["object_name"]

    def test_mesh_check_watertight_schema(self):
        """Test mesh_check_watertight tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_mesh_check_watertight")
        schema = tool.inputSchema

        assert "object_name" in schema["properties"]
        assert schema["required"] == ["object_name"]

    def test_text_add_relief_schema(self):
        """Test text_add_relief tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_text_add_relief")
        schema = tool.inputSchema

        assert "content" in schema["properties"]
        assert "target_object" in schema["properties"]
        assert "fit_box" in schema["properties"]
        assert "x_min" in schema["properties"]["fit_box"]["properties"]
        assert "z_bottom" in schema["properties"]
        assert "solver" in schema["properties"]
        assert "EXACT" in schema["properties"]["solver"]["enum"]
        assert set(schema["required"]) == {"content", "target_object", "fit_box", "z_bottom"}

    def test_server_restart_schema(self):
        """Test server_restart tool schema."""
        tool = next(t for t in TOOLS if t.name == "blender_server_restart")
        schema = tool.inputSchema

        assert schema["required"] == []


class TestToolDescriptions:
    """Test that tool descriptions are helpful."""

    def test_descriptions_not_empty(self):
        """All tools should have non-empty descriptions."""
        for tool in TOOLS:
            assert len(tool.description) > 10, f"Tool {tool.name} has too short description"

    def test_descriptions_are_actionable(self):
        """Descriptions should describe what the tool does."""
        action_words = ["get", "set", "create", "delete", "list", "add", "remove", "insert", "export", "import", "render", "search", "download", "generate", "check", "configure", "apply", "assign", "capture", "play", "pause", "jump", "duplicate", "join", "separate", "select", "return", "tag", "decimate", "validate", "batch", "load", "sample", "extract", "map", "transfer", "analyze", "convert", "mark", "fill", "slide", "cut", "measure", "instance", "move", "snap", "calculate", "undo", "redo", "save", "place", "run", "probe", "clear", "enter", "overlay", "manage", "deform"]

        for tool in TOOLS:
            desc_lower = tool.description.lower()
            has_action = any(word in desc_lower for word in action_words)
            assert has_action, f"Tool {tool.name} description should describe an action"


class TestToolNaming:
    """Test tool naming conventions."""

    def test_scene_tools_naming(self):
        """Scene tools should follow naming convention."""
        scene_tools = [t for t in TOOLS if "scene" in t.name]
        for tool in scene_tools:
            # Should be blender_scene_* or blender_get_version
            assert tool.name.startswith("blender_scene_") or tool.name == "blender_get_version"

    def test_object_tools_naming(self):
        """Object tools should follow naming convention."""
        object_tools = [t for t in TOOLS if "object" in t.name]
        for tool in object_tools:
            assert tool.name.startswith("blender_object_")

    def test_material_tools_naming(self):
        """Material tools should follow naming convention."""
        # Exclude MSFS tools which follow a different naming pattern
        material_tools = [t for t in TOOLS if "material" in t.name and "msfs" not in t.name]
        for tool in material_tools:
            assert tool.name.startswith("blender_material_")

    def test_modifier_tools_naming(self):
        """Modifier tools should follow naming convention."""
        modifier_tools = [t for t in TOOLS if "modifier" in t.name]
        for tool in modifier_tools:
            assert tool.name.startswith("blender_modifier_")

    def test_render_tools_naming(self):
        """Render tools should follow naming convention."""
        render_tools = [t for t in TOOLS if "render" in t.name and "ai_" not in t.name and "material_" not in t.name]
        for tool in render_tools:
            assert tool.name.startswith("blender_render_")

    def test_export_tools_naming(self):
        """Export tools should follow naming convention."""
        # Exclude MSFS tools which follow a different naming pattern
        export_tools = [t for t in TOOLS if ("export" in t.name or "import" in t.name) and "msfs" not in t.name]
        for tool in export_tools:
            assert tool.name.startswith("blender_export_") or tool.name.startswith("blender_import_")

    def test_text_tools_naming(self):
        """Text object tools should follow naming convention."""
        text_tools = [t for t in TOOLS if t.name.startswith("blender_text_")]
        assert len(text_tools) >= 3, f"Expected at least 3 text tools, found {len(text_tools)}"
        for tool in text_tools:
            assert tool.name.startswith("blender_text_")

    def test_msfs_tools_naming(self):
        """MSFS tools should follow naming convention."""
        msfs_tools = [t for t in TOOLS if "msfs" in t.name]
        for tool in msfs_tools:
            assert tool.name.startswith("blender_msfs_"), f"MSFS tool {tool.name} should start with blender_msfs_"
        # Should have at least 36 MSFS tools (LOD, materials, collision, animation, export + livery)
        assert len(msfs_tools) >= 36, f"Expected at least 36 MSFS tools, found {len(msfs_tools)}"
