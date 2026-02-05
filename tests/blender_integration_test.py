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
    import bpy
except ImportError:
    print("ERROR: This script must be run inside Blender")
    print("Usage: blender --background --python tests/blender_integration_test.py")
    sys.exit(1)

from blender_mcp_addon.handlers import CommandHandlers
from blender_mcp_addon import compat


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
