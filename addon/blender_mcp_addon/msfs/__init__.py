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

# Livery tools
from .livery import (
    SUPPORTED_AIRCRAFT,
    # Transfer
    analyze_livery,
    convert_to_dds,
    create_livery_package,
    create_paint_layers,
    download_template,
    # Export
    export_livery_textures,
    export_uv_layout,
    extract_color_palette,
    # Templates
    get_aircraft_templates,
    get_template_info,
    load_template_overlay,
    map_design_elements,
    sample_color_from_image,
    set_paint_brush,
    # Painting
    setup_paint_mode,
    transfer_livery,
    validate_livery_package,
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
    # Livery - Painting
    "setup_paint_mode",
    "create_paint_layers",
    "load_template_overlay",
    "export_uv_layout",
    "set_paint_brush",
    "sample_color_from_image",
    # Livery - Templates
    "get_aircraft_templates",
    "get_template_info",
    "download_template",
    "SUPPORTED_AIRCRAFT",
    # Livery - Transfer
    "analyze_livery",
    "transfer_livery",
    "extract_color_palette",
    "map_design_elements",
    # Livery - Export
    "export_livery_textures",
    "create_livery_package",
    "convert_to_dds",
    "validate_livery_package",
]
