"""MSFS (Microsoft Flight Simulator) content creation command handlers."""



from ..validation import (
    require_param,
)


class MSFSHandlersMixin:
    """Mixin for MSFS content creation handlers."""

    def _handle_msfs_create_lod_hierarchy(self, params: dict) -> dict:
        """Create LOD hierarchy from a base object."""
        from .msfs import create_lod_hierarchy
        return create_lod_hierarchy(
            base_object_name=require_param(params, "base_object_name", str),
            lod_count=params.get("lod_count", 4),
            auto_decimate=params.get("auto_decimate", True),
            decimate_ratios=params.get("decimate_ratios"),
        )


    def _handle_msfs_decimate_for_lod(self, params: dict) -> dict:
        """Decimate a mesh for LOD creation."""
        from .msfs import decimate_for_lod
        return decimate_for_lod(
            object_name=require_param(params, "object_name", str),
            ratio=require_param(params, "ratio", (int, float)),
            preserve_uvs=params.get("preserve_uvs", True),
            preserve_vertex_groups=params.get("preserve_vertex_groups", True),
        )


    def _handle_msfs_setup_lod_distances(self, params: dict) -> dict:
        """Set up LOD switching distances."""
        from .msfs import setup_lod_distances
        return setup_lod_distances(
            base_name=require_param(params, "base_name", str),
            distances=params.get("distances"),
        )


    def _handle_msfs_get_lod_info(self, params: dict) -> dict:
        """Get information about an LOD hierarchy."""
        from .msfs import get_lod_info
        return get_lod_info(
            base_name=require_param(params, "base_name", str),
        )


    def _handle_msfs_setup_material(self, params: dict) -> dict:
        """Set up a material with MSFS-specific properties."""
        from .msfs import setup_msfs_material
        return setup_msfs_material(
            material_name=require_param(params, "material_name", str),
            msfs_type=params.get("msfs_type", "standard"),
            base_color=params.get("base_color"),
            metallic=params.get("metallic", 0.0),
            roughness=params.get("roughness", 0.5),
            emissive_color=params.get("emissive_color"),
            emissive_strength=params.get("emissive_strength", 0.0),
            alpha=params.get("alpha", 1.0),
            double_sided=params.get("double_sided", False),
        )


    def _handle_msfs_create_glass_material(self, params: dict) -> dict:
        """Create a glass material optimized for MSFS."""
        from .msfs import create_glass_material
        return create_glass_material(
            material_name=require_param(params, "material_name", str),
            tint_color=params.get("tint_color"),
            opacity=params.get("opacity", 0.1),
            ior=params.get("ior", 1.45),
            is_windshield=params.get("is_windshield", False),
        )


    def _handle_msfs_create_emissive_material(self, params: dict) -> dict:
        """Create an emissive/light material for MSFS."""
        from .msfs import create_emissive_material
        return create_emissive_material(
            material_name=require_param(params, "material_name", str),
            base_color=params.get("base_color"),
            emissive_color=params.get("emissive_color"),
            emissive_strength=params.get("emissive_strength", 1.0),
            is_day_night=params.get("is_day_night", False),
        )


    def _handle_msfs_get_material_presets(self, params: dict) -> dict:
        """Get list of available material presets."""
        from .msfs import get_material_presets
        return get_material_presets()


    def _handle_msfs_create_collision_mesh(self, params: dict) -> dict:
        """Create a collision mesh from a source object."""
        from .msfs import create_collision_mesh
        return create_collision_mesh(
            source_object_name=require_param(params, "source_object_name", str),
            collision_type=params.get("collision_type", "collider"),
            simplify=params.get("simplify", True),
            simplify_ratio=params.get("simplify_ratio", 0.3),
        )


    def _handle_msfs_create_collision_box(self, params: dict) -> dict:
        """Create a box collision primitive for an object."""
        from .msfs import create_collision_box
        return create_collision_box(
            object_name=require_param(params, "object_name", str),
            collision_type=params.get("collision_type", "collider"),
            padding=params.get("padding", 0.0),
        )


    def _handle_msfs_create_collision_convex(self, params: dict) -> dict:
        """Create a convex hull collision mesh."""
        from .msfs import create_collision_convex
        return create_collision_convex(
            object_name=require_param(params, "object_name", str),
            collision_type=params.get("collision_type", "collider"),
        )


    def _handle_msfs_tag_collision_type(self, params: dict) -> dict:
        """Tag an existing object as a collision mesh."""
        from .msfs.collision import tag_collision_type
        return tag_collision_type(
            object_name=require_param(params, "object_name", str),
            collision_type=require_param(params, "collision_type", str),
        )


    def _handle_msfs_add_animation_tag(self, params: dict) -> dict:
        """Add an animation tag/event marker."""
        from .msfs import add_animation_tag
        return add_animation_tag(
            object_name=require_param(params, "object_name", str),
            tag_type=require_param(params, "tag_type", str),
            frame=require_param(params, "frame", int),
            tag_data=params.get("tag_data"),
        )


    def _handle_msfs_setup_visibility_animation(self, params: dict) -> dict:
        """Set up visibility animation for an object."""
        from .msfs import setup_visibility_animation
        return setup_visibility_animation(
            object_name=require_param(params, "object_name", str),
            visible_range=params.get("visible_range"),
            hidden_range=params.get("hidden_range"),
        )


    def _handle_msfs_configure_animation_loop(self, params: dict) -> dict:
        """Configure animation looping behavior."""
        from .msfs import configure_animation_loop
        return configure_animation_loop(
            object_name=require_param(params, "object_name", str),
            behavior=params.get("behavior", "loop"),
            loop_start=params.get("loop_start"),
            loop_end=params.get("loop_end"),
            loop_count=params.get("loop_count", 0),
        )


    def _handle_msfs_list_animation_tags(self, params: dict) -> dict:
        """List all animation tags."""
        from .msfs import list_animation_tags
        return list_animation_tags(
            object_name=params.get("object_name"),
        )


    def _handle_msfs_export_model(self, params: dict) -> dict:
        """Export model(s) in MSFS-compatible glTF format."""
        from .msfs import export_msfs_model
        return export_msfs_model(
            filepath=require_param(params, "filepath", str),
            objects=params.get("objects"),
            include_lods=params.get("include_lods", True),
            include_collision=params.get("include_collision", True),
            include_animations=params.get("include_animations", True),
            export_format=params.get("export_format", "GLB"),
        )


    def _handle_msfs_validate_for_export(self, params: dict) -> dict:
        """Validate model(s) for MSFS compatibility."""
        from .msfs import validate_for_msfs
        return validate_for_msfs(
            object_name=params.get("object_name"),
        )


    def _handle_msfs_get_export_settings(self, params: dict) -> dict:
        """Get available export settings and their defaults."""
        from .msfs import get_export_settings
        return get_export_settings()


    def _handle_msfs_batch_export_lods(self, params: dict) -> dict:
        """Export LOD hierarchy with proper MSFS structure."""
        from .msfs import batch_export_lods
        return batch_export_lods(
            base_name=require_param(params, "base_name", str),
            output_dir=require_param(params, "output_dir", str),
            separate_files=params.get("separate_files", False),
        )

    # ========== MSFS Livery Handlers ==========


    def _handle_msfs_livery_setup_paint_mode(self, params: dict) -> dict:
        """Set up an object for texture painting."""
        from .msfs.livery import setup_paint_mode
        resolution = params.get("texture_resolution", [4096, 4096])
        return setup_paint_mode(
            object_name=require_param(params, "object_name", str),
            texture_resolution=tuple(resolution),
            create_uvs=params.get("create_uvs", True),
        )


    def _handle_msfs_livery_create_paint_layers(self, params: dict) -> dict:
        """Create paint layer images for livery workflow."""
        from .msfs.livery import create_paint_layers
        resolution = params.get("texture_resolution", [4096, 4096])
        return create_paint_layers(
            object_name=require_param(params, "object_name", str),
            layers=params.get("layers"),
            texture_resolution=tuple(resolution),
        )


    def _handle_msfs_livery_load_template_overlay(self, params: dict) -> dict:
        """Load a reference template image as overlay."""
        from .msfs.livery import load_template_overlay
        return load_template_overlay(
            image_path=require_param(params, "image_path", str),
            object_name=params.get("object_name"),
            opacity=params.get("opacity", 0.5),
        )


    def _handle_msfs_livery_export_uv_layout(self, params: dict) -> dict:
        """Export UV layout as image for painting reference."""
        from .msfs.livery import export_uv_layout
        resolution = params.get("resolution", [4096, 4096])
        return export_uv_layout(
            object_name=require_param(params, "object_name", str),
            output_path=require_param(params, "output_path", str),
            resolution=tuple(resolution),
            fill_opacity=params.get("fill_opacity", 0.0),
            line_thickness=params.get("line_thickness", 1.0),
        )


    def _handle_msfs_livery_set_paint_brush(self, params: dict) -> dict:
        """Configure paint brush settings."""
        from .msfs.livery import set_paint_brush
        return set_paint_brush(
            preset=params.get("preset"),
            color=params.get("color"),
            size=params.get("size"),
            strength=params.get("strength"),
        )


    def _handle_msfs_livery_sample_color(self, params: dict) -> dict:
        """Sample a color from an image."""
        from .msfs.livery import sample_color_from_image
        return sample_color_from_image(
            image_path=require_param(params, "image_path", str),
            x=require_param(params, "x", int),
            y=require_param(params, "y", int),
        )


    def _handle_msfs_livery_get_paint_presets(self, params: dict) -> dict:
        """Get available paint presets."""
        from .msfs.livery.painting import get_paint_presets
        return get_paint_presets()


    def _handle_msfs_livery_get_aircraft_templates(self, params: dict) -> dict:
        """Get list of supported aircraft templates."""
        from .msfs.livery import get_aircraft_templates
        return get_aircraft_templates()


    def _handle_msfs_livery_get_template_info(self, params: dict) -> dict:
        """Get detailed template info for an aircraft."""
        from .msfs.livery import get_template_info
        return get_template_info(
            aircraft_id=require_param(params, "aircraft_id", str),
        )


    def _handle_msfs_livery_download_template(self, params: dict) -> dict:
        """Download or generate template files."""
        from .msfs.livery import download_template
        return download_template(
            aircraft_id=require_param(params, "aircraft_id", str),
            output_dir=require_param(params, "output_dir", str),
        )


    def _handle_msfs_livery_analyze(self, params: dict) -> dict:
        """Analyze a livery image for colors, patterns, elements."""
        from .msfs.livery import analyze_livery
        return analyze_livery(
            image_path=require_param(params, "image_path", str),
            aircraft_type=params.get("aircraft_type"),
        )


    def _handle_msfs_livery_transfer(self, params: dict) -> dict:
        """Transfer livery design between aircraft."""
        from .msfs.livery import transfer_livery
        return transfer_livery(
            source_image=require_param(params, "source_image", str),
            source_aircraft=require_param(params, "source_aircraft", str),
            target_aircraft=require_param(params, "target_aircraft", str),
            output_dir=require_param(params, "output_dir", str),
            preserve_colors=params.get("preserve_colors", True),
            preserve_text=params.get("preserve_text", True),
        )


    def _handle_msfs_livery_extract_colors(self, params: dict) -> dict:
        """Extract color palette from livery image."""
        from .msfs.livery import extract_color_palette
        return extract_color_palette(
            image_path=require_param(params, "image_path", str),
            num_colors=params.get("num_colors", 8),
            exclude_white=params.get("exclude_white", True),
        )


    def _handle_msfs_livery_map_elements(self, params: dict) -> dict:
        """Map design elements between aircraft templates."""
        from .msfs.livery import map_design_elements
        return map_design_elements(
            source_aircraft=require_param(params, "source_aircraft", str),
            target_aircraft=require_param(params, "target_aircraft", str),
            elements=params.get("elements"),
        )


    def _handle_msfs_livery_export_textures(self, params: dict) -> dict:
        """Export livery textures from an object."""
        from .msfs.livery import export_livery_textures
        return export_livery_textures(
            object_name=require_param(params, "object_name", str),
            output_dir=require_param(params, "output_dir", str),
            texture_types=params.get("texture_types"),
            format=params.get("format", "PNG"),
        )


    def _handle_msfs_livery_create_package(self, params: dict) -> dict:
        """Create MSFS livery package folder structure."""
        from .msfs.livery import create_livery_package
        return create_livery_package(
            aircraft_id=require_param(params, "aircraft_id", str),
            livery_name=require_param(params, "livery_name", str),
            output_dir=require_param(params, "output_dir", str),
            texture_dir=params.get("texture_dir"),
            airline=params.get("airline", ""),
            description=params.get("description", ""),
            author=params.get("author", ""),
        )


    def _handle_msfs_livery_convert_to_dds(self, params: dict) -> dict:
        """Convert texture to DDS format for MSFS."""
        from .msfs.livery import convert_to_dds
        return convert_to_dds(
            input_path=require_param(params, "input_path", str),
            output_path=params.get("output_path"),
            texture_type=params.get("texture_type", "albedo"),
        )


    def _handle_msfs_livery_validate_package(self, params: dict) -> dict:
        """Validate a livery package structure."""
        from .msfs.livery import validate_livery_package
        return validate_livery_package(
            package_dir=require_param(params, "package_dir", str),
        )

    # ========== Boolean Operations Handler ==========

