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
        # Baking is slow at its production defaults (2048 px, 128 samples). The cases
        # test the handlers, so keep each bake tiny; the defaults stay as they are.
        "bake_pbr_batch": _over(
            object_name="Cube", output_dir="{TMP}", resolution=32, samples=1, margin=2
        ),
        "bake_highpoly_to_lowpoly": _over(
            lowpoly_name="Cube",
            highpoly_name="Sphere",
            output_dir="{TMP}",
            resolution=32,
            samples=1,
            margin=2,
        ),
        "bake_from_multires": _over(
            object_name="MultiresSphere", output_path="{TMP}/out.png", resolution=32, margin=2
        ),
        "bake_to_vertex_colors": _over(object_name="Cube", samples=1),
        "bake_curvature": _over(object_name="Cube", output_path="{TMP}/out.png", resolution=32),
        "bake_id_map": _over(object_name="Cube", output_path="{TMP}/out.png", resolution=32),
        "sculpt_extract_mask": _over(object_name="MaskedSphere"),
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
        "msfs_batch_export_lods": _over(base_name="Hull", output_dir="{TMP}/lods"),
        "msfs_get_lod_info": _over(base_name="Hull"),
        "msfs_setup_lod_distances": _over(base_name="Hull"),
        "boolean_op": _over(target="Cube", tool="Sphere", operation="UNION"),
        "mesh_merge": _over(object_name="Cube", vertex_indices=[0, 1]),
    }
)

# Extra params for one enum case, keyed by (tool, param, value). For a param
# whose requirements depend on another param's value, which the JSON Schema
# here does not express.
ENUM_OVERRIDES: dict[tuple[str, str, str], dict] = {
    ("measure", "mode", "DISTANCE"): _over(point_a=[0.0, 0.0, 0.0], point_b=[1.0, 0.0, 0.0]),
    ("measure", "mode", "EDGE_LENGTH"): _over(edge_indices=[0, 1]),
    ("measure", "mode", "VERTEX_DISTANCE"): _over(vertex_indices=[0, 1]),
}

# Cases the harness cannot reach, keyed by tool name, with the reason.
# Informational only: baselines record each case's true class regardless.
KNOWN_UNREACHED: dict[str, str] = {
    "undo": "Blender disables undo in background mode",
    "redo": "Blender disables undo in background mode",
    "ai_model_status": "needs a job id that only a live AI backend can issue",
    "ai_pipeline_status": "needs a pipeline id that only a live AI backend can issue",
    "refine_get_session": "needs a session id from a prior refine_create_session call",
}

# SOFT_FAIL classes the baselines may keep, keyed by tool name, with the reason.
# Benign means the harness environment is the cause, not the tool: offline, a
# fixture id or fixture limit, or background mode.
# M3 is done only when both defect tables below are empty.
SOFT_FAIL_ALLOWED: dict[str, str] = {
    "ai_generate_model": "no AI backend is reachable offline",
    "ai_generate_model_sync": "no AI backend is reachable offline",
    "ai_generate_reference_image": "no AI backend is reachable offline",
    "ai_generate_texture": "no AI backend is reachable offline",
    "ai_generate_texture_sync": "no AI backend is reachable offline",
    "ai_inpaint_texture": "no AI backend is reachable offline",
    "ai_pipeline_generate": "no AI backend is reachable offline",
    "annotation_add": "Blender 4.3 to 4.5 offers no Python call that creates an annotation stroke, so the tool says so; the socket test annotation_add_draws_or_says_why checks both outcomes",
    "msfs_livery_convert_to_dds": "needs texconv from DirectXTex, which is not installed here",
    "msfs_livery_export_uv_layout": "the UV exporter draws on the GPU, which background mode lacks; the socket test checks it in a GUI",
    "msfs_livery_set_paint_brush": "needs texture paint mode from a prior msfs_livery_setup_paint_mode call, which a fresh-scene case cannot make; the socket test msfs_paint_brush_after_setup runs both",
    "mesh_edge_slide": "needs a 3D viewport; socket lane covers it",
    "mesh_knife_project": "needs a 3D viewport; socket lane covers it",
    "mesh_loop_cut": "needs a 3D viewport; socket lane covers it",
    "render_screenshot": "needs a 3D viewport; socket lane covers it",
    "sculpt_face_set_create": "face_sets_init crashes Blender in background mode, so it needs a 3D viewport; socket lane covers it",
    "sculpt_mask_by_topology": "the mask operators need a 3D viewport and crash Blender in background mode; socket lane covers it",
    "sculpt_mesh_filter": "needs a 3D viewport; socket lane covers it",
    "sculpt_multires_reshape": "the fixture mesh has no subdivision levels to rebuild or unsubdivide",
}

# Tools whose SOFT_FAIL hides a real defect. A tool with both benign and
# defective cases belongs here.
SOFT_FAIL_DEFECTS: dict[str, str] = {
    "ai_texture_from_render": "depth and normal control types send a beauty render, not a depth or normal pass",
}

# Tools that report success shape but hide a failure in the payload.
FALSE_PASS_DEFECTS: dict[str, str] = {
    "grease_pencil_markup": "the compositor fallback draws nothing (annotations_drawn: 0) yet reports success",
}
