"""MSFS aircraft livery painting and transfer tools."""

from .export import (
    convert_to_dds,
    create_livery_package,
    export_livery_textures,
    validate_livery_package,
)
from .painting import (
    create_paint_layers,
    export_uv_layout,
    load_template_overlay,
    sample_color_from_image,
    set_paint_brush,
    setup_paint_mode,
)
from .templates import (
    SUPPORTED_AIRCRAFT,
    download_template,
    get_aircraft_templates,
    get_template_info,
)
from .transfer import (
    analyze_livery,
    extract_color_palette,
    map_design_elements,
    transfer_livery,
)

__all__ = [
    # Painting
    "setup_paint_mode",
    "create_paint_layers",
    "load_template_overlay",
    "export_uv_layout",
    "set_paint_brush",
    "sample_color_from_image",
    # Templates
    "get_aircraft_templates",
    "get_template_info",
    "download_template",
    "SUPPORTED_AIRCRAFT",
    # Transfer
    "analyze_livery",
    "transfer_livery",
    "extract_color_palette",
    "map_design_elements",
    # Export
    "export_livery_textures",
    "create_livery_package",
    "convert_to_dds",
    "validate_livery_package",
]
