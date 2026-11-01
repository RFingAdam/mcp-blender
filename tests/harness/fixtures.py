"""Fixture values for schema params, keyed by param name.

Object names refer to the scene built by the runner's scene module.
``{TMP}`` is a path placeholder the runner expands to a temp directory.
"""

from __future__ import annotations

from typing import Any

FIXTURES: dict[str, Any] = {
    "object_name": "Cube",
    "material_name": "Material",
    "armature_name": "Armature",
    "curve_name": "Curve",
    "collection_name": "Collection",
    "filepath": "{TMP}/harness.blend",
    "output_path": "{TMP}/out.png",
    "output_dir": "{TMP}",
    "render_path": "{TMP}/render.png",
    "image_path": "{TMP}/in.png",
    "input_path": "{TMP}/in.png",
    "mask_path": "{TMP}/mask.png",
    "source_image": "{TMP}/in.png",
    "reference_image": "{TMP}/in.png",
    "package_dir": "{TMP}",
    "location": [0.0, 0.0, 0.0],
    "offset": [0.0, 0.0, 0.0],
    "point_a": [0.0, 0.0, 0.0],
    "point_b": [1.0, 0.0, 0.0],
    "plane_point": [0.0, 0.0, 0.0],
    "plane_normal": [0.0, 0.0, 1.0],
    "color": [1.0, 1.0, 1.0, 1.0],
    "script": "pass",
    "name": "Cube",
    "names": ["Cube", "Sphere"],
    "object_names": ["Cube"],
    "prompt": "weathered red brick wall",
    "target_object": "Sphere",
    "source_object": "Cube",
    "instance_object": "Cube",
    "cutter_object": "Curve",
    "child": "Cube",
    "target": "Cube",
    "tool": "Sphere",
    "object_a": "Cube",
    "object_b": "Sphere",
    "domain_object": "Cube",
    "flow_object": "Sphere",
    "profile_object": "Curve",
    "lowpoly_name": "Cube",
    "highpoly_name": "Sphere",
    "base_name": "Cube",
    "base_object_name": "Cube",
    "source_object_name": "Cube",
    "target_collection": "Collection",
    "modifier_name": "Bevel",
    "node_group": "GeoGroup",
    "bone_name": "Bone",
    "pose_name": "Pose",
    "data_path": "location",
    "frame": 1,
    "indices": [0],
    "face_indices": [0],
    "vertex_indices": [0],
    "edge_indices": [0, 1, 2, 3],
    "loop1_edges": [0, 1, 2, 3],
    "loop2_edges": [6, 7, 8, 9],
    "edge_index": 0,
    "face_index": 0,
    "index_a": 0,
    "index_b": 2,
    "points": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
    "vertices": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
    "faces": [[0, 1, 2, 3]],
    "locations": [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
    "value": [0.0, 0.0, 0.5],
    "ratio": 0.5,
    "width": 640,
    "height": 480,
    "x": 1,
    "y": 1,
    "text": "note",
    "known_dimension": 2.0,
    "expected": {"length": 2.0},
    "properties": {"width": 0.05},
    "aircraft_id": "fbw_a32nx",
    "source_aircraft": "fbw_a32nx",
    "target_aircraft": "pmdg_737",
    "livery_name": "Harness",
    "asset_id": "brick_wall",
    "backend": "comfyui",
    "from_node": "Principled BSDF",
    "from_output": "BSDF",
    "to_node": "Material Output",
    "to_input": "Surface",
    "node_type": "ShaderNodeTexNoise",
    "target_format": "GLTF",
    "engine": "CYCLES",
    "modifier_type": "SUBSURF",
    "tag_type": "start",
    "collision_type": "collider",
    "strokes": [{"points": [[0, 0, 0], [1, 0, 0], [1, 1, 0]]}],
    "annotations": [{"type": "text", "text": "note", "position": [8, 8]}],
}

# Per-tool replacements for the whole minimal arg dict, keyed by bare tool name.
OVERRIDES: dict[str, dict] = {}


def _over(**args: Any) -> dict:
    return args


OVERRIDES.update(
    {
        "armature_create": _over(bones=[{"name": "B1", "head": [0, 0, 0], "tail": [0, 0, 1]}]),
        "constraint_add": _over(
            constraint_type="COPY_LOCATION",
            armature_name="Armature",
            bone_name="Bone.001",
            target_object="Cube",
        ),
        "constraint_preset": _over(
            armature_name="Armature",
            preset="IK_ARM",
            bones={
                "ik_bone": "Bone.001",
                "pole_target": "Bone",
                "foot_bone": "Bone.001",
                "bone_a": "Bone",
                "bone_b": "Bone.001",
                "wheel_bone": "Bone",
                "hinge_bone": "Bone",
                "base_bone": "Bone",
                "elevation_bone": "Bone.001",
            },
        ),
        "geonode_inspect": _over(object_name="Sphere"),
        "bake_from_multires": _over(object_name="Sphere", output_path="{TMP}/out.png"),
        "sculpt_multires_reshape": _over(object_name="Sphere", action="SUBDIVIDE"),
        "modifier_apply": _over(object_name="Sphere", modifier_name="Bevel"),
        "modifier_remove": _over(object_name="Sphere", modifier_name="Bevel"),
        "modifier_configure": _over(
            object_name="Sphere", modifier_name="Bevel", properties={"width": 0.05}
        ),
        "import_file": _over(filepath="{TMP}/in.glb"),
        "object_join": _over(names=["Cube", "Sphere"]),
        "ai_generate_model": _over(prompt="a small wooden crate"),
        "ai_generate_model_sync": _over(prompt="a small wooden crate"),
        "export_fbx": _over(filepath="{TMP}/out.fbx"),
        "export_gltf": _over(filepath="{TMP}/out.glb"),
        "export_obj": _over(filepath="{TMP}/out.obj"),
        "export_stl": _over(filepath="{TMP}/out.stl"),
        "export_usd": _over(filepath="{TMP}/out.usd"),
        "msfs_export_model": _over(filepath="{TMP}/out.glb"),
        "boolean_op": _over(target="Cube", tool="Sphere", operation="UNION"),
    }
)

# Cases the harness cannot reach, keyed by tool name, with the reason.
KNOWN_UNREACHED: dict[str, str] = {
    "undo": "Blender disables undo in background mode",
    "redo": "Blender disables undo in background mode",
    "render_screenshot": "screenshot_area needs a UI area, absent in background mode",
    "ai_model_status": "needs a job id that only a live AI backend can issue",
    "ai_pipeline_status": "needs a pipeline id that only a live AI backend can issue",
    "refine_get_session": "needs a session id from a prior refine_create_session call",
}
