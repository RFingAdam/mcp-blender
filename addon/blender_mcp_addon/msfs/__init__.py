"""MSFS 2020/2024 content creation tools."""

from .animation import (
    add_animation_tag,
    configure_animation_loop,
    list_animation_tags,
    setup_visibility_animation,
)
from .collision import (
    create_collision_box,
    create_collision_convex,
    create_collision_mesh,
    tag_collision_type,
)
from .export import (
    batch_export_lods,
    export_msfs_model,
    get_export_settings,
    validate_for_msfs,
)
from .lod import (
    create_lod_hierarchy,
    decimate_for_lod,
    get_lod_info,
    setup_lod_distances,
)
from .materials import (
    create_emissive_material,
    create_glass_material,
    get_material_presets,
    setup_msfs_material,
)

__all__ = [
    # LOD
    "create_lod_hierarchy",
    "decimate_for_lod",
    "setup_lod_distances",
    "get_lod_info",
    # Materials
    "setup_msfs_material",
    "create_glass_material",
    "create_emissive_material",
    "get_material_presets",
    # Collision
    "create_collision_mesh",
    "create_collision_box",
    "create_collision_convex",
    "tag_collision_type",
    # Animation
    "add_animation_tag",
    "setup_visibility_animation",
    "configure_animation_loop",
    "list_animation_tags",
    # Export
    "export_msfs_model",
    "validate_for_msfs",
    "get_export_settings",
    "batch_export_lods",
]
