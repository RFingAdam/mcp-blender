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
}

# Per-tool replacements for the whole minimal arg dict, keyed by bare tool name.
OVERRIDES: dict[str, dict] = {}
