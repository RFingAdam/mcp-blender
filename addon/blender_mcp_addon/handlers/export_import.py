"""Export and import command handlers."""

import os

import bpy

from ..validation import (
    ValidationError,
    require_param,
    validate_enum,
    validate_filepath,
)


class ExportImportHandlersMixin:
    """Mixin for export/import handlers."""

    def _handle_export_gltf(self, params: dict) -> dict:
        """Export to glTF/GLB."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )
        export_format = validate_enum(
            params.get("export_format", "GLB"),
            "export_format",
            ["GLB", "GLTF_SEPARATE", "GLTF_EMBEDDED"]
        )

        bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format=export_format,
            use_selection=params.get("selected_only", False),
            export_animations=params.get("export_animations", True),
            export_materials="EXPORT" if params.get("export_materials", True) else "NONE",
        )
        return {"filepath": filepath}


    def _handle_export_fbx(self, params: dict) -> dict:
        """Export to FBX with comprehensive options."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "use_selection": params.get("selected_only", False),
            "use_mesh_modifiers": params.get("apply_modifiers", True),
        }

        # Optional parameters
        if "scale" in params:
            export_kwargs["global_scale"] = params["scale"]
        if "apply_unit_scale" in params:
            export_kwargs["apply_unit_scale"] = params["apply_unit_scale"]
        if "bake_anim" in params:
            export_kwargs["bake_anim"] = params["bake_anim"]
        if "axis_forward" in params:
            export_kwargs["axis_forward"] = params["axis_forward"]
        if "axis_up" in params:
            export_kwargs["axis_up"] = params["axis_up"]

        bpy.ops.export_scene.fbx(**export_kwargs)

        return {
            "filepath": filepath,
            "format": "FBX",
            "selected_only": export_kwargs["use_selection"],
        }


    def _handle_export_obj(self, params: dict) -> dict:
        """Export to OBJ with options."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "export_selected_objects": params.get("selected_only", False),
            "apply_modifiers": params.get("apply_modifiers", True),
        }

        # Optional parameters
        if "scale" in params:
            export_kwargs["global_scale"] = params["scale"]
        if "forward_axis" in params:
            export_kwargs["forward_axis"] = params["forward_axis"]
        if "up_axis" in params:
            export_kwargs["up_axis"] = params["up_axis"]
        if "export_materials" in params:
            export_kwargs["export_materials"] = params["export_materials"]

        bpy.ops.wm.obj_export(**export_kwargs)

        return {
            "filepath": filepath,
            "format": "OBJ",
            "selected_only": export_kwargs["export_selected_objects"],
        }


    def _handle_export_stl(self, params: dict) -> dict:
        """Export to STL (for 3D printing)."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "use_selection": params.get("selected_only", False),
            "use_mesh_modifiers": params.get("apply_modifiers", True),
        }

        # Optional parameters
        if "scale" in params:
            export_kwargs["global_scale"] = params["scale"]
        if "ascii" in params:
            export_kwargs["ascii"] = params["ascii"]

        # Use new STL export operator (Blender 4.x+)
        stl_kwargs = {
            "filepath": filepath,
            "export_selected_objects": export_kwargs.get("use_selection", False),
        }
        if "global_scale" in export_kwargs:
            stl_kwargs["global_scale"] = export_kwargs["global_scale"]
        if "ascii" in export_kwargs:
            stl_kwargs["ascii_format"] = export_kwargs["ascii"]
        bpy.ops.wm.stl_export(**stl_kwargs)

        return {
            "filepath": filepath,
            "format": "STL",
            "selected_only": export_kwargs["use_selection"],
        }


    def _handle_import_file(self, params: dict) -> dict:
        """Import file with auto-format detection."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath",
            must_exist=True
        )
        ext = os.path.splitext(filepath)[1].lower()

        # Count objects before import
        objects_before = set(obj.name for obj in bpy.data.objects)

        import_ops = {
            ".gltf": lambda: bpy.ops.import_scene.gltf(filepath=filepath),
            ".glb": lambda: bpy.ops.import_scene.gltf(filepath=filepath),
            ".fbx": lambda: bpy.ops.import_scene.fbx(filepath=filepath),
            ".obj": lambda: bpy.ops.wm.obj_import(filepath=filepath),
            ".stl": lambda: bpy.ops.import_mesh.stl(filepath=filepath),
            ".dae": lambda: bpy.ops.wm.collada_import(filepath=filepath),
            ".abc": lambda: bpy.ops.wm.alembic_import(filepath=filepath),
            ".usd": lambda: bpy.ops.wm.usd_import(filepath=filepath),
            ".usda": lambda: bpy.ops.wm.usd_import(filepath=filepath),
            ".usdc": lambda: bpy.ops.wm.usd_import(filepath=filepath),
            ".ply": lambda: bpy.ops.wm.ply_import(filepath=filepath),
            ".svg": lambda: bpy.ops.import_curve.svg(filepath=filepath),
        }

        if ext not in import_ops:
            supported = ", ".join(sorted(import_ops.keys()))
            raise ValidationError(
                f"Unsupported file format: '{ext}'. Supported: {supported}"
            )

        import_ops[ext]()

        # Identify imported objects
        objects_after = set(obj.name for obj in bpy.data.objects)
        imported_objects = list(objects_after - objects_before)

        return {
            "filepath": filepath,
            "format": ext[1:].upper(),
            "imported_objects": imported_objects,
            "count": len(imported_objects),
        }


    def _handle_export_usd(self, params: dict) -> dict:
        """Export to Universal Scene Description (USD) format."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "selected_objects_only": params.get("selected_only", False),
        }

        if "export_animation" in params:
            export_kwargs["export_animation"] = params["export_animation"]
        if "export_materials" in params:
            export_kwargs["export_materials"] = params["export_materials"]

        bpy.ops.wm.usd_export(**export_kwargs)

        return {
            "filepath": filepath,
            "format": "USD",
        }

    # ========== External Integration Handlers ==========

