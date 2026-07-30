#!/usr/bin/env python3
"""
Blender Integration Tests for MCP Addon.

Run with: blender --background --python tests/blender_integration_test.py

This script tests all handler functionality directly inside Blender.
"""

import os
import sys
import tempfile
import traceback

# Add addon to path
addon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "addon")
if addon_path not in sys.path:
    sys.path.insert(0, addon_path)

try:
    import bmesh
    import bpy
except ImportError:
    print("ERROR: This script must be run inside Blender")
    print("Usage: blender --background --python tests/blender_integration_test.py")
    sys.exit(1)

from blender_mcp_addon import compat
from blender_mcp_addon.handlers import CommandHandlers


class TestRunner:
    """Simple test runner for Blender integration tests."""

    def __init__(self):
        self.handlers = CommandHandlers()
        self.passed = 0
        self.failed = 0
        self.errors = []

    def run_test(self, name: str, test_func):
        """Run a single test function."""
        print(f"  Testing {name}...", end=" ")
        try:
            test_func()
            print("PASSED")
            self.passed += 1
        except AssertionError as e:
            print(f"FAILED: {e}")
            self.failed += 1
            self.errors.append((name, str(e)))
        except Exception as e:
            print(f"ERROR: {e}")
            self.failed += 1
            self.errors.append((name, traceback.format_exc()))

    def reset_scene(self):
        """Reset the scene to a clean state."""
        bpy.ops.wm.read_homefile(use_empty=True)

    def summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print(f"Tests: {self.passed + self.failed}, Passed: {self.passed}, Failed: {self.failed}")
        if self.errors:
            print("\nFailures:")
            for name, error in self.errors:
                print(f"  - {name}: {error[:100]}")
        print("=" * 60)
        return self.failed == 0


def test_version_info(runner: TestRunner):
    """Test get_version handler."""
    result = runner.handlers.handle("get_version", {})
    assert "version" in result, "Missing version"
    assert "version_string" in result, "Missing version_string"
    assert isinstance(result["version"], list), "Version should be a list"


def test_ping(runner: TestRunner):
    """Test ping handler."""
    result = runner.handlers.handle("ping", {})
    assert result.get("pong") is True, "Ping should return pong: true"
    assert "blender_version" in result, "Should include blender_version"


def test_scene_info(runner: TestRunner):
    """Test scene_info handler."""
    result = runner.handlers.handle("scene_info", {})
    assert "name" in result, "Missing scene name"
    assert "frame_start" in result, "Missing frame_start"
    assert "frame_end" in result, "Missing frame_end"
    assert "object_count" in result, "Missing object_count"


def test_scene_set_frame_range(runner: TestRunner):
    """Test scene_set_frame_range handler."""
    result = runner.handlers.handle("scene_set_frame_range", {"start": 10, "end": 100})
    assert result["frame_start"] == 10, "Frame start not set"
    assert result["frame_end"] == 100, "Frame end not set"


def test_scene_clear(runner: TestRunner):
    """Test scene_clear handler."""
    # First create an object
    bpy.ops.mesh.primitive_cube_add()
    assert len(bpy.context.scene.objects) > 0, "Should have objects"

    # Clear the scene
    result = runner.handlers.handle("scene_clear", {})
    assert result.get("cleared") is True, "Should return cleared: true"
    assert len(bpy.context.scene.objects) == 0, "Scene should be empty"


def test_object_create_cube(runner: TestRunner):
    """Test object_create handler with cube."""
    runner.reset_scene()
    result = runner.handlers.handle("object_create", {
        "type": "cube",
        "name": "TestCube",
        "location": [1, 2, 3],
    })
    assert result["name"] == "TestCube", f"Name mismatch: {result['name']}"
    assert result["type"] == "MESH", f"Type mismatch: {result['type']}"

    obj = bpy.data.objects.get("TestCube")
    assert obj is not None, "Object not created"
    assert abs(obj.location.x - 1) < 0.01, "X location wrong"
    assert abs(obj.location.y - 2) < 0.01, "Y location wrong"
    assert abs(obj.location.z - 3) < 0.01, "Z location wrong"


def test_object_create_sphere(runner: TestRunner):
    """Test object_create handler with sphere."""
    runner.reset_scene()
    result = runner.handlers.handle("object_create", {"type": "sphere"})
    assert result["type"] == "MESH", "Sphere should be a mesh"


def test_object_create_all_primitives(runner: TestRunner):
    """Test creating all primitive types."""
    runner.reset_scene()
    primitives = ["cube", "sphere", "cylinder", "plane", "cone", "torus", "monkey"]

    for prim in primitives:
        result = runner.handlers.handle("object_create", {"type": prim})
        assert "name" in result, f"Failed to create {prim}"


def test_object_list(runner: TestRunner):
    """Test object_list handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "Cube1"})
    runner.handlers.handle("object_create", {"type": "sphere", "name": "Sphere1"})

    result = runner.handlers.handle("object_list", {})
    assert "objects" in result, "Missing objects list"
    assert len(result["objects"]) == 2, f"Expected 2 objects, got {len(result['objects'])}"

    names = [obj["name"] for obj in result["objects"]]
    assert "Cube1" in names, "Cube1 not in list"
    assert "Sphere1" in names, "Sphere1 not in list"


def test_object_get(runner: TestRunner):
    """Test object_get handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "TestCube"})

    result = runner.handlers.handle("object_get", {"name": "TestCube"})
    assert result["name"] == "TestCube", "Name mismatch"
    assert result["type"] == "MESH", "Type mismatch"
    assert "location" in result, "Missing location"
    assert "rotation_euler" in result, "Missing rotation"
    assert "scale" in result, "Missing scale"


def test_object_transform(runner: TestRunner):
    """Test object_transform handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "TestCube"})

    result = runner.handlers.handle("object_transform", {
        "name": "TestCube",
        "location": [5, 6, 7],
        "scale": [2, 2, 2],
    })

    obj = bpy.data.objects.get("TestCube")
    assert abs(obj.location.x - 5) < 0.01, "X location not updated"
    assert abs(obj.scale.x - 2) < 0.01, "Scale not updated"


def test_object_delete(runner: TestRunner):
    """Test object_delete handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "ToDelete"})
    assert bpy.data.objects.get("ToDelete") is not None, "Object not created"

    result = runner.handlers.handle("object_delete", {"name": "ToDelete"})
    assert result["deleted"] == "ToDelete", "Wrong deleted name"
    assert bpy.data.objects.get("ToDelete") is None, "Object not deleted"


def test_object_duplicate(runner: TestRunner):
    """Test object_duplicate handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "Original"})

    result = runner.handlers.handle("object_duplicate", {
        "name": "Original",
        "new_name": "Copy",
    })

    assert bpy.data.objects.get("Original") is not None, "Original should exist"
    assert bpy.data.objects.get("Copy") is not None, "Copy should exist"


def test_object_select(runner: TestRunner):
    """Test object_select handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "Cube1"})
    runner.handlers.handle("object_create", {"type": "cube", "name": "Cube2"})

    result = runner.handlers.handle("object_select", {"names": ["Cube1"]})
    assert "Cube1" in result["selected"], "Cube1 should be selected"


def test_material_create(runner: TestRunner):
    """Test material_create handler."""
    result = runner.handlers.handle("material_create", {"name": "TestMaterial"})
    assert result["name"] == "TestMaterial", "Name mismatch"

    mat = bpy.data.materials.get("TestMaterial")
    assert mat is not None, "Material not created"
    assert mat.use_nodes is True, "Should use nodes by default"


def test_material_assign(runner: TestRunner):
    """Test material_assign handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "TestCube"})
    runner.handlers.handle("material_create", {"name": "TestMat"})

    result = runner.handlers.handle("material_assign", {
        "object_name": "TestCube",
        "material_name": "TestMat",
    })

    obj = bpy.data.objects.get("TestCube")
    assert len(obj.material_slots) > 0, "No material slots"
    assert obj.material_slots[0].material.name == "TestMat", "Material not assigned"


def test_material_set_color(runner: TestRunner):
    """Test material_set_color handler."""
    runner.handlers.handle("material_create", {"name": "ColorMat"})

    result = runner.handlers.handle("material_set_color", {
        "material_name": "ColorMat",
        "color": [1.0, 0.0, 0.0, 1.0],  # Red
    })

    mat = bpy.data.materials.get("ColorMat")
    # Find Principled BSDF
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            color = node.inputs["Base Color"].default_value
            assert abs(color[0] - 1.0) < 0.01, "Red not set"
            assert abs(color[1] - 0.0) < 0.01, "Green should be 0"
            break


def test_material_list(runner: TestRunner):
    """Test material_list handler."""
    runner.handlers.handle("material_create", {"name": "ListMat1"})
    runner.handlers.handle("material_create", {"name": "ListMat2"})

    result = runner.handlers.handle("material_list", {})
    names = [m["name"] for m in result["materials"]]
    assert "ListMat1" in names, "ListMat1 not found"
    assert "ListMat2" in names, "ListMat2 not found"


def test_modifier_add(runner: TestRunner):
    """Test modifier_add handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "ModCube"})

    result = runner.handlers.handle("modifier_add", {
        "object_name": "ModCube",
        "modifier_type": "SUBSURF",
    })

    obj = bpy.data.objects.get("ModCube")
    assert len(obj.modifiers) > 0, "No modifiers added"
    assert obj.modifiers[0].type == "SUBSURF", "Wrong modifier type"


def test_modifier_configure(runner: TestRunner):
    """Test modifier_configure handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "ModCube"})
    runner.handlers.handle("modifier_add", {
        "object_name": "ModCube",
        "modifier_type": "SUBSURF",
        "modifier_name": "Subdivision",
    })

    result = runner.handlers.handle("modifier_configure", {
        "object_name": "ModCube",
        "modifier_name": "Subdivision",
        "properties": {"levels": 3},
    })

    obj = bpy.data.objects.get("ModCube")
    assert obj.modifiers["Subdivision"].levels == 3, "Levels not set"


def test_modifier_remove(runner: TestRunner):
    """Test modifier_remove handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "ModCube"})
    runner.handlers.handle("modifier_add", {
        "object_name": "ModCube",
        "modifier_type": "SUBSURF",
        "modifier_name": "ToRemove",
    })

    result = runner.handlers.handle("modifier_remove", {
        "object_name": "ModCube",
        "modifier_name": "ToRemove",
    })

    obj = bpy.data.objects.get("ModCube")
    assert "ToRemove" not in obj.modifiers, "Modifier not removed"


def test_keyframe_insert(runner: TestRunner):
    """Test keyframe_insert handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "AnimCube"})

    result = runner.handlers.handle("keyframe_insert", {
        "object_name": "AnimCube",
        "data_path": "location",
        "frame": 1,
    })

    obj = bpy.data.objects.get("AnimCube")
    assert obj.animation_data is not None, "No animation data"
    assert obj.animation_data.action is not None, "No action created"


def test_animation_goto_frame(runner: TestRunner):
    """Test animation_goto_frame handler."""
    result = runner.handlers.handle("animation_goto_frame", {"frame": 50})
    assert bpy.context.scene.frame_current == 50, "Frame not set"


def test_render_set_engine(runner: TestRunner):
    """Test render_set_engine handler."""
    result = runner.handlers.handle("render_set_engine", {"engine": "CYCLES"})
    assert bpy.context.scene.render.engine == "CYCLES", "Engine not set to Cycles"

    # Test EEVEE
    result = runner.handlers.handle("render_set_engine", {"engine": "EEVEE"})
    expected = compat.get_eevee_engine_name()
    assert bpy.context.scene.render.engine == expected, f"Engine not set to {expected}"


def test_render_set_resolution(runner: TestRunner):
    """Test render_set_resolution handler."""
    result = runner.handlers.handle("render_set_resolution", {
        "width": 1920,
        "height": 1080,
        "percentage": 50,
    })

    scene = bpy.context.scene
    assert scene.render.resolution_x == 1920, "Width not set"
    assert scene.render.resolution_y == 1080, "Height not set"
    assert scene.render.resolution_percentage == 50, "Percentage not set"


def test_render_image(runner: TestRunner):
    """Test render_image handler."""
    runner.reset_scene()
    # Add a light and camera for rendering
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 5))
    bpy.ops.object.camera_add(location=(0, -5, 2))
    bpy.context.scene.camera = bpy.context.active_object

    # Set small resolution for fast test
    runner.handlers.handle("render_set_resolution", {
        "width": 64,
        "height": 64,
        "percentage": 100,
    })

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        output_path = f.name

    try:
        result = runner.handlers.handle("render_image", {
            "output_path": output_path,
            "file_format": "PNG",
        })
        assert os.path.exists(output_path), "Render output not created"
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_export_gltf(runner: TestRunner):
    """Test export_gltf handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "ExportCube"})

    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
        output_path = f.name

    try:
        result = runner.handlers.handle("export_gltf", {
            "filepath": output_path,
            "export_format": "GLB",
        })
        assert os.path.exists(output_path), "GLB file not created"
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_export_obj(runner: TestRunner):
    """Test export_obj handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "ExportCube"})

    with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
        output_path = f.name

    try:
        result = runner.handlers.handle("export_obj", {
            "filepath": output_path,
        })
        assert os.path.exists(output_path), "OBJ file not created"
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_stl_roundtrip(runner: TestRunner):
    """Test export_stl followed by import_file on the same .stl."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "StlCube"})

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        output_path = f.name

    try:
        runner.handlers.handle("export_stl", {"filepath": output_path})
        assert os.path.exists(output_path), "STL file not created"

        runner.handlers.handle("scene_clear", {})
        result = runner.handlers.handle("import_file", {"filepath": output_path})
        assert result["count"] >= 1, f"STL import produced no objects: {result}"
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_mesh_fill_enum_values(runner: TestRunner):
    """Test that mesh_fill accepts its documented fill_type values."""
    from blender_mcp_addon.validation import ValidationError

    runner.reset_scene()
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4, size=2)
    grid = bpy.context.active_object
    grid.name = "FillGrid"

    # Punch a hole so the mesh has boundary edges to fill.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    grid.data.polygons[4].select = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.delete(type="FACE")
    bpy.ops.object.mode_set(mode="OBJECT")

    selection = runner.handlers.handle(
        "mesh_select_trait", {"object_name": "FillGrid", "trait": "BOUNDARY"}
    )
    edges = selection["selected_indices"]
    assert edges, "expected boundary edges after deleting a face"

    for fill_type in ("NGON", "TRIANGLE_FAN"):
        result = runner.handlers.handle("mesh_fill", {
            "object_name": "FillGrid",
            "edge_indices": edges,
            "fill_type": fill_type,
        })
        assert result["success"], f"mesh_fill rejected fill_type={fill_type}"

    # An invalid value must still be rejected.
    try:
        runner.handlers.handle("mesh_fill", {
            "object_name": "FillGrid",
            "edge_indices": edges,
            "fill_type": "NOT_A_FILL_TYPE",
        })
    except ValidationError:
        pass
    else:
        raise AssertionError("mesh_fill accepted an invalid fill_type")


def test_text_create_and_to_mesh(runner: TestRunner):
    """Test creating a native vector text object and baking it to a mesh."""
    runner.reset_scene()
    result = runner.handlers.handle("text_create", {
        "name": "SignText",
        "content": "AB",
        "size": 5,
        "extrude": 1.0,
        "bevel_depth": 0.2,
        "bevel_resolution": 4,
    })
    assert result["success"], "text_create failed"

    obj = bpy.data.objects.get("SignText")
    assert obj is not None, "text object not created"
    assert obj.type == "FONT", f"expected FONT object, got {obj.type}"

    mesh_result = runner.handlers.handle("text_to_mesh", {"object_name": "SignText"})
    assert mesh_result["success"], "text_to_mesh failed"
    assert mesh_result["vertices"] > 0, "converted mesh has no vertices"
    assert mesh_result["faces"] > 0, "converted mesh has no faces"

    mesh_obj = bpy.data.objects.get("SignText")
    assert mesh_obj.type == "MESH", "object was not converted to MESH"

    # text_to_mesh must weld the duplicate seam vertices bpy.ops.object.convert
    # leaves behind - otherwise every glyph reads as non-manifold.
    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    assert non_manifold == 0, f"{non_manifold} non-manifold edges after text_to_mesh"


def test_text_set_properties(runner: TestRunner):
    """Test updating an existing text object's font/extrude/bevel/spacing."""
    from blender_mcp_addon.validation import ValidationError

    runner.reset_scene()
    runner.handlers.handle("text_create", {"name": "SignText2", "content": "Hi"})

    result = runner.handlers.handle("text_set_properties", {
        "object_name": "SignText2",
        "extrude": 0.5,
        "bevel_depth": 0.1,
        "align_x": "CENTER",
    })
    assert result["success"], "text_set_properties failed"
    assert set(result["changed"]) == {"extrude", "bevel_depth", "align_x"}

    obj = bpy.data.objects["SignText2"]
    assert abs(obj.data.extrude - 0.5) < 1e-6, "extrude not applied"
    assert obj.data.align_x == "CENTER", "align_x not applied"

    # An invalid enum value must be rejected without changing the object.
    try:
        runner.handlers.handle("text_set_properties", {
            "object_name": "SignText2", "align_x": "NOT_A_VALUE",
        })
    except ValidationError:
        pass
    else:
        raise AssertionError("text_set_properties accepted an invalid align_x")

    # Must reject non-text objects.
    bpy.ops.mesh.primitive_cube_add()
    try:
        runner.handlers.handle("text_set_properties", {"object_name": "Cube", "size": 2})
    except ValidationError:
        pass
    else:
        raise AssertionError("text_set_properties accepted a non-text object")


def test_text_add_relief(runner: TestRunner):
    """Test the full create/fit/convert/separate/union-per-glyph recipe."""
    runner.reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=20)
    target = bpy.context.active_object
    target.name = "ReliefTarget"
    target_verts_before = len(target.data.vertices)

    # The cube spans z [-10, 10] - z_bottom must sit at/near its top surface
    # so the extruded glyphs poke out above it. A z_bottom buried inside the
    # solid (e.g. mid-cube) makes the union a legitimate no-op: unioning a
    # solid fully contained within another adds nothing, which is correct
    # behavior, not the corruption this tool guards against.
    result = runner.handlers.handle("text_add_relief", {
        "content": "AB",
        "target_object": "ReliefTarget",
        "fit_box": {"x_min": -8.0, "x_max": 8.0, "y_min": -3.0, "y_max": 3.0},
        "z_bottom": 9.5,
        "extrude": 1.0,
        "bevel_depth": 0.1,
        "letter_spacing": 1.3,
    })
    assert result["success"], f"text_add_relief failed: {result}"
    assert result["glyph_count"] == 2, "AB should separate into 2 glyph pieces"
    assert len(result["union_log"]) == 2

    target = bpy.data.objects["ReliefTarget"]
    assert len(target.data.vertices) > target_verts_before, "union should have added geometry"
    assert len(target.data.vertices) == result["final_vertices"]

    # The glyph pieces must be fitted to fill fit_box, not left at their
    # natural (mismatched) font aspect ratio.
    bm = bmesh.new()
    bm.from_mesh(target.data)
    xs = [v.co.x for v in bm.verts if v.co.z > 10.5]  # verts above the cube's flat top (z=10)
    bm.free()
    if xs:
        assert (max(xs) - min(xs)) <= 16.5, "relief text should not overflow fit_box width"

    # target_object must be a mesh.
    from blender_mcp_addon.validation import ValidationError

    bpy.ops.object.text_add()
    bpy.context.active_object.name = "NotAMesh"
    try:
        runner.handlers.handle("text_add_relief", {
            "content": "X", "target_object": "NotAMesh",
            "fit_box": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}, "z_bottom": 0,
        })
    except ValidationError:
        pass
    else:
        raise AssertionError("text_add_relief accepted a non-mesh target_object")


def test_mesh_add_relief(runner: TestRunner):
    """Test the source-object generalization of text_add_relief: fit/join/union arbitrary meshes."""
    runner.reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=20)
    target = bpy.context.active_object
    target.name = "MeshReliefTarget"
    target_verts_before = len(target.data.vertices)

    # Two disjoint source pieces, standing in for e.g. two SVG-imported
    # glyphs that arrive as separate objects and must be joined before the
    # box-fit (so their relative offset/size to each other is preserved).
    bpy.ops.mesh.primitive_cube_add(size=1, location=(-3, 0, 0))
    piece_a = bpy.context.active_object
    piece_a.name = "ReliefPieceA"
    bpy.ops.mesh.primitive_cube_add(size=1, location=(3, 0, 0))
    piece_b = bpy.context.active_object
    piece_b.name = "ReliefPieceB"

    result = runner.handlers.handle("mesh_add_relief", {
        "source_objects": ["ReliefPieceA", "ReliefPieceB"],
        "target_object": "MeshReliefTarget",
        "fit_box": {"x_min": -8.0, "x_max": 8.0, "y_min": -3.0, "y_max": 3.0},
        "z_bottom": 9.5,
    })
    assert result["success"], f"mesh_add_relief failed: {result}"
    assert result["piece_count"] == 2, "two disjoint source cubes should separate into 2 pieces"
    assert len(result["union_log"]) == 2

    target = bpy.data.objects["MeshReliefTarget"]
    assert len(target.data.vertices) > target_verts_before, "union should have added geometry"
    assert len(target.data.vertices) == result["final_vertices"]

    # keep_aspect=True must scale uniformly rather than stretching independently.
    runner.reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=20)
    target2 = bpy.context.active_object
    target2.name = "AspectTarget"
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))  # 2x2 square footprint
    square = bpy.context.active_object
    square.name = "SquareSource"

    aspect_result = runner.handlers.handle("mesh_add_relief", {
        "source_objects": ["SquareSource"],
        "target_object": "AspectTarget",
        "fit_box": {"x_min": -8.0, "x_max": 8.0, "y_min": -1.0, "y_max": 1.0},
        "z_bottom": 9.5,
        "keep_aspect": True,
        "separate_loose": False,
    })
    assert aspect_result["success"], f"mesh_add_relief (keep_aspect) failed: {aspect_result}"
    assert aspect_result["piece_count"] == 1

    # source_objects cannot include target_object.
    from blender_mcp_addon.validation import ValidationError

    try:
        runner.handlers.handle("mesh_add_relief", {
            "source_objects": ["AspectTarget"], "target_object": "AspectTarget",
            "fit_box": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}, "z_bottom": 0,
        })
    except ValidationError:
        pass
    else:
        raise AssertionError("mesh_add_relief accepted target_object as its own source")


def test_mesh_bake_heightmap(runner: TestRunner):
    """Test mesh_bake_heightmap: hits over the mesh, misses outside it."""
    import numpy as np

    runner.reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2)  # spans x/y/z in [-1, 1]
    cube = bpy.context.active_object
    cube.name = "HeightmapCube"

    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
        output_path = f.name

    try:
        result = runner.handlers.handle("mesh_bake_heightmap", {
            "object_name": "HeightmapCube",
            "bb_min": [-0.9, -0.9, -5.0],
            "bb_max": [0.9, 0.9, 5.0],
            "output_path": output_path,
            "resolution": 5,
        })
        assert result["success"], f"mesh_bake_heightmap failed: {result}"
        assert result["shape"] == [5, 5]
        assert result["hit_ratio"] == 1.0, "box fully inside the cube's XY footprint should hit on every ray"
        assert abs(result["height_min"] - 1.0) < 1e-4, "ray from above should stop at the cube's top face (z=1)"
        assert abs(result["height_max"] - 1.0) < 1e-4

        grid = np.load(result["output_path"])
        assert grid.shape == (5, 5)
        assert np.allclose(grid, 1.0, atol=1e-4)

        # A box that doesn't overlap the mesh at all should miss every ray.
        miss_result = runner.handlers.handle("mesh_bake_heightmap", {
            "object_name": "HeightmapCube",
            "bb_min": [10.0, 10.0, -5.0],
            "bb_max": [11.0, 11.0, 5.0],
            "output_path": output_path,
            "resolution": 3,
            "miss_value": -1.0,
        })
        assert miss_result["hit_ratio"] == 0.0
        assert miss_result["height_min"] is None
        assert miss_result["height_max"] is None
        miss_grid = np.load(miss_result["output_path"])
        assert np.allclose(miss_grid, -1.0)
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_object_rename(runner: TestRunner):
    """Test object_rename handler."""
    runner.reset_scene()
    runner.handlers.handle("object_create", {"type": "cube", "name": "OldName"})

    result = runner.handlers.handle("object_rename", {"name": "OldName", "new_name": "NewName"})
    assert result["success"], "object_rename failed"
    assert result["name"] == "NewName", "returned name mismatch"
    assert bpy.data.objects.get("OldName") is None, "old name still present"
    assert bpy.data.objects.get("NewName") is not None, "new name not present"

    # Blender auto-suffixes on collision (e.g. "NewName.001") rather than erroring -
    # the handler must surface whatever name Blender actually assigned.
    runner.handlers.handle("object_create", {"type": "cube", "name": "Other"})
    collide_result = runner.handlers.handle("object_rename", {"name": "Other", "new_name": "NewName"})
    assert collide_result["name"] != "NewName", "collision should have been auto-suffixed"
    assert bpy.data.objects.get(collide_result["name"]) is not None


def test_object_get_bounds(runner: TestRunner):
    """Test object_get_bounds handler on a mesh and on a FONT object."""
    runner.reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2, location=(5, 0, 0))
    cube = bpy.context.active_object
    cube.name = "BoundsCube"

    result = runner.handlers.handle("object_get_bounds", {"name": "BoundsCube"})
    assert result["min"] == [4.0, -1.0, -1.0] or all(
        abs(a - b) < 1e-5 for a, b in zip(result["min"], [4.0, -1.0, -1.0])
    ), f"unexpected min {result['min']}"
    assert all(abs(a - b) < 1e-5 for a, b in zip(result["max"], [6.0, 1.0, 1.0]))
    assert all(abs(a - b) < 1e-5 for a, b in zip(result["dimensions"], [2.0, 2.0, 2.0]))
    assert all(abs(a - b) < 1e-5 for a, b in zip(result["center"], [5.0, 0.0, 0.0]))

    # Must also work on a FONT object before it is converted to a mesh -
    # this is the motivating use case (size/position text pre-text_to_mesh).
    runner.handlers.handle("text_create", {"name": "BoundsText", "content": "A", "size": 3})
    text_bounds = runner.handlers.handle("object_get_bounds", {"name": "BoundsText"})
    assert text_bounds["dimensions"][0] > 0, "FONT object bounds should have nonzero width"
    assert text_bounds["dimensions"][1] > 0, "FONT object bounds should have nonzero height"


def test_mesh_triangulate(runner: TestRunner):
    """Test mesh_triangulate handler."""
    runner.reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = bpy.context.active_object
    cube.name = "TriCube"
    assert len(cube.data.polygons) == 6, "cube should start as 6 quads"

    result = runner.handlers.handle("mesh_triangulate", {"object_name": "TriCube"})
    assert result["success"], "mesh_triangulate failed"
    assert result["faces_before"] == 6
    assert result["faces_after"] == 12, "6 quads should become 12 triangles"

    obj = bpy.data.objects["TriCube"]
    assert all(len(f.vertices) == 3 for f in obj.data.polygons), "non-triangle face remains"


def test_mesh_check_watertight(runner: TestRunner):
    """Test mesh_check_watertight handler: closed mesh, holed mesh, and multi-shell mesh."""
    runner.reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = bpy.context.active_object
    cube.name = "WatertightCube"

    result = runner.handlers.handle("mesh_check_watertight", {"object_name": "WatertightCube"})
    assert result["watertight"], "closed cube should be watertight"
    assert result["non_manifold_edge_count"] == 0
    assert result["boundary_edge_count"] == 0
    assert result["shell_count"] == 1
    assert result["signed_volume"] > 0, "signed volume should be positive for outward normals"
    assert abs(result["signed_volume"] - 8.0) < 1e-4, "2x2x2 cube should have volume 8"

    # A cube missing one face has an open boundary - must be reported, not silently ignored.
    bpy.ops.mesh.primitive_cube_add(size=2, location=(10, 0, 0))
    holed = bpy.context.active_object
    holed.name = "HoledCube"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    holed.data.polygons[0].select = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.delete(type="FACE")
    bpy.ops.object.mode_set(mode="OBJECT")

    holed_result = runner.handlers.handle("mesh_check_watertight", {"object_name": "HoledCube"})
    assert not holed_result["watertight"], "cube with a missing face must not be watertight"
    assert holed_result["boundary_edge_count"] > 0, "missing face should leave boundary edges"

    # Two disjoint cubes joined into one object is 2 shells - must not be reported as 1.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(20, 0, 0))
    part_a = bpy.context.active_object
    part_a.name = "MultiShellA"
    bpy.ops.mesh.primitive_cube_add(size=1, location=(25, 0, 0))
    part_b = bpy.context.active_object
    part_b.name = "MultiShellB"
    bpy.ops.object.select_all(action="DESELECT")
    part_a.select_set(True)
    part_b.select_set(True)
    bpy.context.view_layer.objects.active = part_a
    bpy.ops.object.join()

    shell_result = runner.handlers.handle("mesh_check_watertight", {"object_name": "MultiShellA"})
    assert shell_result["shell_count"] == 2, f"expected 2 shells, got {shell_result['shell_count']}"
    assert not shell_result["watertight"], "multi-shell mesh should not report watertight"


def test_compat_version_detection(runner: TestRunner):
    """Test version compatibility detection."""
    info = compat.get_version_info()
    assert "is_5_0" in info, "Missing is_5_0"
    assert "is_4_2" in info, "Missing is_4_2"
    assert isinstance(info["is_5_0"], bool), "is_5_0 should be bool"


def test_compat_eevee_name(runner: TestRunner):
    """Test EEVEE engine name detection."""
    name = compat.get_eevee_engine_name()
    assert name in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"), f"Unexpected EEVEE name: {name}"

    # The reported name must be one this Blender build actually accepts.
    valid = {item.identifier
             for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    assert name in valid, f"EEVEE name {name} not in this build's engines: {sorted(valid)}"


def test_compat_principled_inputs(runner: TestRunner):
    """Test Principled BSDF input mapping."""
    inputs = compat.get_principled_bsdf_inputs()
    assert "base_color" in inputs, "Missing base_color"
    assert "metallic" in inputs, "Missing metallic"
    assert "roughness" in inputs, "Missing roughness"


def main():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print("Blender MCP Addon Integration Tests")
    print(f"Blender Version: {bpy.app.version_string}")
    print("=" * 60 + "\n")

    runner = TestRunner()

    # Scene tests
    print("Scene Tests:")
    runner.run_test("ping", lambda: test_ping(runner))
    runner.run_test("get_version", lambda: test_version_info(runner))
    runner.run_test("scene_info", lambda: test_scene_info(runner))
    runner.run_test("scene_set_frame_range", lambda: test_scene_set_frame_range(runner))
    runner.run_test("scene_clear", lambda: test_scene_clear(runner))

    # Object tests
    print("\nObject Tests:")
    runner.run_test("object_create_cube", lambda: test_object_create_cube(runner))
    runner.run_test("object_create_sphere", lambda: test_object_create_sphere(runner))
    runner.run_test("object_create_all_primitives", lambda: test_object_create_all_primitives(runner))
    runner.run_test("object_list", lambda: test_object_list(runner))
    runner.run_test("object_get", lambda: test_object_get(runner))
    runner.run_test("object_transform", lambda: test_object_transform(runner))
    runner.run_test("object_delete", lambda: test_object_delete(runner))
    runner.run_test("object_duplicate", lambda: test_object_duplicate(runner))
    runner.run_test("object_select", lambda: test_object_select(runner))
    runner.run_test("object_rename", lambda: test_object_rename(runner))
    runner.run_test("object_get_bounds", lambda: test_object_get_bounds(runner))

    # Material tests
    print("\nMaterial Tests:")
    runner.run_test("material_create", lambda: test_material_create(runner))
    runner.run_test("material_assign", lambda: test_material_assign(runner))
    runner.run_test("material_set_color", lambda: test_material_set_color(runner))
    runner.run_test("material_list", lambda: test_material_list(runner))

    # Modifier tests
    print("\nModifier Tests:")
    runner.run_test("modifier_add", lambda: test_modifier_add(runner))
    runner.run_test("modifier_configure", lambda: test_modifier_configure(runner))
    runner.run_test("modifier_remove", lambda: test_modifier_remove(runner))

    # Animation tests
    print("\nAnimation Tests:")
    runner.run_test("keyframe_insert", lambda: test_keyframe_insert(runner))
    runner.run_test("animation_goto_frame", lambda: test_animation_goto_frame(runner))

    # Render tests
    print("\nRender Tests:")
    runner.run_test("render_set_engine", lambda: test_render_set_engine(runner))
    runner.run_test("render_set_resolution", lambda: test_render_set_resolution(runner))
    runner.run_test("render_image", lambda: test_render_image(runner))

    # Export tests
    print("\nExport Tests:")
    runner.run_test("export_gltf", lambda: test_export_gltf(runner))
    runner.run_test("export_obj", lambda: test_export_obj(runner))
    runner.run_test("stl_roundtrip", lambda: test_stl_roundtrip(runner))

    # Mesh editing tests
    print("\nMesh Editing Tests:")
    runner.run_test("mesh_fill_enum_values", lambda: test_mesh_fill_enum_values(runner))
    runner.run_test("mesh_triangulate", lambda: test_mesh_triangulate(runner))
    runner.run_test("mesh_check_watertight", lambda: test_mesh_check_watertight(runner))
    runner.run_test("mesh_bake_heightmap", lambda: test_mesh_bake_heightmap(runner))

    # Text object tests
    print("\nText Object Tests:")
    runner.run_test("text_create_and_to_mesh", lambda: test_text_create_and_to_mesh(runner))
    runner.run_test("text_set_properties", lambda: test_text_set_properties(runner))
    runner.run_test("text_add_relief", lambda: test_text_add_relief(runner))
    runner.run_test("mesh_add_relief", lambda: test_mesh_add_relief(runner))

    # Compatibility tests
    print("\nCompatibility Tests:")
    runner.run_test("compat_version_detection", lambda: test_compat_version_detection(runner))
    runner.run_test("compat_eevee_name", lambda: test_compat_eevee_name(runner))
    runner.run_test("compat_principled_inputs", lambda: test_compat_principled_inputs(runner))

    # Summary
    success = runner.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
