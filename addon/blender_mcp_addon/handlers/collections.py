"""Collection and system command handlers."""

import os

import bpy

from ..validation import (
    ValidationError,
    require_param,
    validate_enum,
)


class CollectionHandlersMixin:
    """Mixin for collection and system handlers."""

    def _handle_collection_create(self, params: dict) -> dict:
        """Create a new collection and link it to a parent collection."""
        name = require_param(params, "name", str)
        parent_name = params.get("parent")
        color_tag = params.get("color_tag", "NONE")

        # Validate color_tag if provided
        valid_tags = [
            "NONE",
            "COLOR_01", "COLOR_02", "COLOR_03", "COLOR_04",
            "COLOR_05", "COLOR_06", "COLOR_07", "COLOR_08",
        ]
        color_tag = validate_enum(color_tag, "color_tag", valid_tags)

        # Create the collection
        new_collection = bpy.data.collections.new(name)
        new_collection.color_tag = color_tag

        # Determine parent collection
        if parent_name:
            parent_collection = bpy.data.collections.get(parent_name)
            if parent_collection is None:
                # Check if it's the scene collection by name
                scene_col = bpy.context.scene.collection
                if scene_col.name == parent_name:
                    parent_collection = scene_col
                else:
                    # Clean up the orphan collection we just created
                    bpy.data.collections.remove(new_collection)
                    raise ValidationError(
                        f"Parent collection '{parent_name}' not found. "
                        f"Available: {[c.name for c in bpy.data.collections]} "
                        f"+ scene collection '{scene_col.name}'"
                    )
            parent_collection.children.link(new_collection)
            parent_path = parent_name
        else:
            # Link to the scene's root collection
            bpy.context.scene.collection.children.link(new_collection)
            parent_path = bpy.context.scene.collection.name

        # Build the full path
        full_path = f"{parent_path}/{new_collection.name}"

        return {
            "success": True,
            "name": new_collection.name,
            "parent": parent_path,
            "path": full_path,
            "color_tag": new_collection.color_tag,
        }


    def _handle_collection_list(self, params: dict) -> dict:
        """List all collections with hierarchy as a nested tree."""

        def _find_layer_collection(layer_col, name):
            """Recursively find a LayerCollection by collection name."""
            if layer_col.collection.name == name:
                return layer_col
            for child in layer_col.children:
                result = _find_layer_collection(child, name)
                if result is not None:
                    return result
            return None

        def _build_tree(collection, layer_collection_root):
            """Recursively build collection tree structure."""
            # Get layer collection for visibility info
            lc = _find_layer_collection(layer_collection_root, collection.name)

            objects = [obj.name for obj in collection.objects]
            children = []
            for child in collection.children:
                children.append(_build_tree(child, layer_collection_root))

            result = {
                "name": collection.name,
                "objects": objects,
                "children": children,
                "color_tag": getattr(collection, "color_tag", "NONE"),
            }

            if lc is not None:
                result["visible"] = not lc.hide_viewport
                result["excluded"] = lc.exclude
                result["render_visible"] = not collection.hide_render
                result["selectable"] = not collection.hide_select
            else:
                result["visible"] = True
                result["excluded"] = False
                result["render_visible"] = not collection.hide_render
                result["selectable"] = not collection.hide_select

            return result

        scene = bpy.context.scene
        root = scene.collection
        layer_root = bpy.context.view_layer.layer_collection

        # Build tree from root scene collection
        tree = {
            "name": root.name,
            "objects": [obj.name for obj in root.objects],
            "children": [
                _build_tree(child, layer_root)
                for child in root.children
            ],
            "visible": True,
            "excluded": False,
            "render_visible": True,
            "selectable": True,
        }

        # Count totals
        total_collections = len(bpy.data.collections)

        return {
            "success": True,
            "hierarchy": tree,
            "total_collections": total_collections,
        }


    def _handle_collection_move(self, params: dict) -> dict:
        """Move objects between collections."""
        object_names = require_param(params, "object_names", list)
        target_name = require_param(params, "target_collection", str)
        remove_from_current = params.get("remove_from_current", True)

        # Find the target collection
        target_collection = bpy.data.collections.get(target_name)
        if target_collection is None:
            # Check if it's the scene collection
            scene_col = bpy.context.scene.collection
            if scene_col.name == target_name:
                target_collection = scene_col
            else:
                raise ValidationError(
                    f"Target collection '{target_name}' not found. "
                    f"Available: {[c.name for c in bpy.data.collections]} "
                    f"+ scene collection '{scene_col.name}'"
                )

        moved = []
        errors = []

        for obj_name in object_names:
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                errors.append(f"Object '{obj_name}' not found")
                continue

            # Remove from current collections if requested
            if remove_from_current:
                # Collect all collections this object is in
                current_collections = [
                    c for c in bpy.data.collections if obj.name in c.objects
                ]
                # Also check scene collection
                scene_col = bpy.context.scene.collection
                if obj.name in scene_col.objects:
                    current_collections.append(scene_col)

                for col in current_collections:
                    col.objects.unlink(obj)

            # Link to target collection (skip if already linked)
            if obj.name not in target_collection.objects:
                target_collection.objects.link(obj)

            moved.append(obj_name)

        result = {
            "success": len(errors) == 0,
            "moved_count": len(moved),
            "objects": moved,
            "target_collection": target_name,
        }
        if errors:
            result["errors"] = errors

        return result


    def _handle_collection_visibility(self, params: dict) -> dict:
        """Toggle collection visibility, renderability, and selectability."""
        collection_name = require_param(params, "collection_name", str)

        # Find the bpy.data collection
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            raise ValidationError(
                f"Collection '{collection_name}' not found. "
                f"Available: {[c.name for c in bpy.data.collections]}"
            )

        # Find the corresponding LayerCollection by walking the tree
        def _find_layer_collection(layer_col, name):
            """Recursively find a LayerCollection by collection name."""
            if layer_col.collection.name == name:
                return layer_col
            for child in layer_col.children:
                result = _find_layer_collection(child, name)
                if result is not None:
                    return result
            return None

        layer_root = bpy.context.view_layer.layer_collection
        layer_col = _find_layer_collection(layer_root, collection_name)

        if layer_col is None:
            raise ValidationError(
                f"Collection '{collection_name}' not found in the current view layer. "
                f"It may not be linked to the active scene."
            )

        # Apply requested changes
        changes = {}

        if "visible" in params:
            visible = bool(params["visible"])
            layer_col.hide_viewport = not visible
            changes["visible"] = visible

        if "renderable" in params:
            renderable = bool(params["renderable"])
            collection.hide_render = not renderable
            changes["renderable"] = renderable

        if "selectable" in params:
            selectable = bool(params["selectable"])
            collection.hide_select = not selectable
            changes["selectable"] = selectable

        # Return current state after changes
        return {
            "success": True,
            "collection": collection_name,
            "changes_applied": changes,
            "current_state": {
                "visible": not layer_col.hide_viewport,
                "excluded": layer_col.exclude,
                "renderable": not collection.hide_render,
                "selectable": not collection.hide_select,
            },
        }


    # ========== System Handlers ==========


    def _handle_undo(self, params: dict) -> dict:
        """Undo the last operation."""
        try:
            bpy.ops.ed.undo()
            # Try to get the current undo step name
            undo_name = None
            try:
                undo_name = bpy.context.window_manager.undo_steps_data[-1].name
            except (AttributeError, IndexError):
                pass

            result = {"success": True}
            if undo_name:
                result["operation"] = undo_name
            return result
        except RuntimeError as e:
            return {"success": False, "error": f"Undo failed: {e}"}


    def _handle_redo(self, params: dict) -> dict:
        """Redo the last undone operation."""
        try:
            bpy.ops.ed.redo()
            return {"success": True}
        except RuntimeError as e:
            return {"success": False, "error": f"Redo failed: {e}"}


    def _handle_save(self, params: dict) -> dict:
        """Save the current file."""
        compress = params.get("compress", False)

        # Check if the file has ever been saved
        filepath = bpy.data.filepath
        if not filepath:
            return {
                "success": False,
                "error": "File has never been saved. Use save_as with a filepath instead.",
            }

        bpy.ops.wm.save_mainfile(compress=bool(compress))

        # Get file size
        try:
            filesize = os.path.getsize(filepath)
        except OSError:
            filesize = None

        result = {
            "success": True,
            "filepath": filepath,
        }
        if filesize is not None:
            result["filesize"] = filesize
            result["filesize_mb"] = round(filesize / (1024 * 1024), 2)

        return result


    def _handle_save_as(self, params: dict) -> dict:
        """Save to a new file path."""
        filepath = require_param(params, "filepath", str)
        compress = params.get("compress", False)
        copy = params.get("copy", False)

        # Ensure filepath ends with .blend
        if not filepath.lower().endswith(".blend"):
            filepath += ".blend"

        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(filepath)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        bpy.ops.wm.save_as_mainfile(
            filepath=filepath,
            compress=bool(compress),
            copy=bool(copy),
        )

        # Get file size
        try:
            filesize = os.path.getsize(filepath)
        except OSError:
            filesize = None

        result = {
            "success": True,
            "filepath": filepath,
            "copy": copy,
        }
        if filesize is not None:
            result["filesize"] = filesize
            result["filesize_mb"] = round(filesize / (1024 * 1024), 2)

        return result


    # ========== Baking Handlers ==========

