"""Tests for version compatibility layer.

Note: These tests can only run inside Blender. They are structured to be
run via `blender --background --python tests/test_compat.py`.
"""

# These tests are designed to run inside Blender
# Run with: blender --background --python tests/test_compat.py

import sys


def test_in_blender():
    """Test compatibility functions inside Blender."""
    try:
        import bpy
    except ImportError:
        print("SKIP: Not running inside Blender")
        return

    # Add addon path to sys.path
    import os

    addon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "addon")
    if addon_path not in sys.path:
        sys.path.insert(0, addon_path)

    from blender_mcp_addon import compat

    # Test version detection
    version_info = compat.get_version_info()
    assert "version" in version_info
    assert "version_string" in version_info
    assert "is_5_0" in version_info
    assert "is_4_2" in version_info
    print(f"Blender version: {version_info['version_string']}")

    # Test EEVEE engine name
    engine_name = compat.get_eevee_engine_name()
    assert engine_name in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")
    print(f"EEVEE engine name: {engine_name}")

    # Test Principled BSDF input mapping
    inputs = compat.get_principled_bsdf_inputs()
    assert "base_color" in inputs
    assert "metallic" in inputs
    assert "roughness" in inputs
    print(f"Principled BSDF inputs: {list(inputs.keys())}")

    # Test action creation
    action = compat.create_action("TestAction")
    assert action is not None
    assert action.name == "TestAction"
    print(f"Created action: {action.name}")

    # Clean up
    bpy.data.actions.remove(action)

    # Test FCurves access (create a simple animation first)
    cube = bpy.data.objects.get("Cube")
    if cube is None:
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.active_object

    cube.location = (0, 0, 0)
    cube.keyframe_insert(data_path="location", frame=1)
    cube.location = (1, 1, 1)
    cube.keyframe_insert(data_path="location", frame=10)

    if cube.animation_data and cube.animation_data.action:
        fcurves = compat.get_fcurves(cube.animation_data.action)
        assert len(fcurves) > 0
        print(f"Got {len(fcurves)} FCurves")

    print("\nAll compatibility tests passed!")


if __name__ == "__main__":
    test_in_blender()
