"""Texture baking command handlers."""

import functools
import os

import bpy

from .. import compat
from ..validation import (
    require_param,
    validate_filepath,
)
from ._helpers import (
    _ALL_CHANNELS,
    _CHANNEL_BAKE_CONFIG,
    _FORMAT_EXTENSIONS,
    _bake_ensure_cycles,
)

_BAKE_FORMATS = ("PNG", "TARGA", "OPEN_EXR")


def _restores_scene(handler):
    """Put back the scene settings a bake handler changes, and report any that could not be.

    The restore runs after the handler returns or raises, so after its own material cleanup.
    A setting that cannot be put back, such as an add-on render engine that is no longer
    available, is named in the result's ``warnings`` instead of being left changed silently.
    """

    @functools.wraps(handler)
    def wrapper(self, params):
        state = self._bake_capture_scene()
        try:
            result = handler(self, params)
        except BaseException:
            unrestored = self._bake_restore_scene(state)
            if unrestored:
                print(f"Meshwire: bake could not restore {', '.join(unrestored)}")
            raise
        unrestored = self._bake_restore_scene(state)
        if unrestored and isinstance(result, dict):
            result.setdefault("warnings", []).append(
                "Could not restore scene settings after the bake: " + ", ".join(unrestored)
            )
        return result

    return wrapper


class BakingHandlersMixin:
    """Mixin for texture baking handlers."""

    # =================================================================
    # Bake helpers
    #
    # Baking needs a target Image Texture node in every material on the object, and
    # the metallic and displacement channels bake through a temporary emission
    # output. Both rewire the user's material, so every helper records exactly what
    # it added or flipped and undoes only that. Nothing is found by a name a user
    # could also use.
    # =================================================================

    def _bake_materials(self, obj) -> list:
        """Unique materials on ``obj`` that have a node tree, in slot order.

        Empty slots and materials without nodes are skipped, and a material shared
        by several slots is listed once.
        """
        found = []
        seen = set()
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat.node_tree is None:
                continue
            if mat.as_pointer() in seen:
                continue
            seen.add(mat.as_pointer())
            found.append(mat)
        return found

    def _bake_material_problem(self, obj) -> str | None:
        """Why ``obj`` cannot be baked, or None when at least one material can take a target."""
        if not obj.material_slots:
            return f"Object '{obj.name}' has no material. Add a material before baking."
        if not self._bake_materials(obj):
            return (
                f"Object '{obj.name}' has no material with nodes (empty slots or "
                "materials that do not use nodes). Assign a node material before baking."
            )
        return None

    def _bake_ensure_target_material(self, obj):
        """Give ``obj`` a throwaway material if it has no usable one.

        Returns an opaque token for ``_bake_drop_target_material``, or None when
        the object already had a node material and nothing was changed.
        """
        if self._bake_materials(obj):
            return None
        if any(slot.material is not None for slot in obj.material_slots):
            # A material exists but has no node tree: do not rewrite it.
            return None
        mat = bpy.data.materials.new(name=f"{obj.name}_BakeMat")
        try:
            mat.use_nodes = True
            if len(obj.material_slots) == 0:
                obj.data.materials.append(mat)
                return (mat, 0, True)
            obj.material_slots[0].material = mat
            return (mat, 0, False)
        except BaseException:
            # No token will reach the caller, so nothing else would remove it.
            bpy.data.materials.remove(mat)
            raise

    def _bake_drop_target_material(self, obj, token) -> None:
        """Undo ``_bake_ensure_target_material``."""
        if token is None:
            return
        mat, index, appended = token
        try:
            if appended:
                # The object had no slots at all, so clearing restores it exactly.
                obj.data.materials.clear()
            else:
                obj.material_slots[index].material = None
        finally:
            bpy.data.materials.remove(mat)

    @staticmethod
    def _bake_empty_slot_warnings(obj) -> list:
        """Warn about slots that cannot take a bake target, so a blank region is explained."""
        empty = [
            i
            for i, slot in enumerate(obj.material_slots)
            if slot.material is None or slot.material.node_tree is None
        ]
        if not empty:
            return []
        return [
            f"Material slots {empty} on '{obj.name}' have no material with nodes, "
            "so faces using them are blank in the baked maps."
        ]

    @staticmethod
    def _bake_settable(owner, only=None) -> list:
        """Names of plain (non-pointer) writable properties on ``owner``."""
        return [
            prop.identifier
            for prop in owner.bl_rna.properties
            if not prop.is_readonly
            and prop.type != "POINTER"
            and prop.identifier != "rna_type"
            and (only is None or only(prop.identifier))
        ]

    def _bake_capture_scene(self) -> dict:
        """Record what baking changes outside materials: engine, every bake setting, selection.

        Handlers get this through ``_restores_scene``, which passes it to ``_bake_restore_scene``.
        """
        scene = bpy.context.scene
        owners = [
            (
                "render",
                scene.render,
                self._bake_settable(scene.render, lambda n: n == "engine" or "bake" in n),
            ),
            ("render.bake", scene.render.bake, self._bake_settable(scene.render.bake)),
        ]
        if hasattr(scene, "cycles"):
            owners.append(("cycles", scene.cycles, ["samples"]))
        values = []
        for label, owner, names in owners:
            for name in names:
                value = getattr(owner, name)
                if isinstance(value, set):
                    value = set(value)
                elif hasattr(value, "__len__") and not isinstance(value, str):
                    value = tuple(value)
                values.append((owner, label, name, value))
        layer = bpy.context.view_layer
        return {
            "values": values,
            "selected": [o for o in layer.objects if o.select_get()],
            "active": layer.objects.active,
        }

    def _bake_restore_scene(self, state: dict) -> list:
        """Put back what ``_bake_capture_scene`` recorded. One failure does not skip the rest.

        Returns each setting that could not be put back, as ``"render.engine (LUXCORE)"``.
        """
        unrestored = []
        for owner, label, name, value in state["values"]:
            try:
                setattr(owner, name, value)
            except (AttributeError, TypeError, ValueError, RuntimeError, ReferenceError):
                unrestored.append(f"{label}.{name} ({value})")
        layer = bpy.context.view_layer
        keep = state["selected"]
        for obj in layer.objects:
            try:
                obj.select_set(obj in keep)
            except (RuntimeError, ReferenceError):
                pass
        try:
            layer.objects.active = state["active"]
        except (RuntimeError, ReferenceError):
            pass
        return unrestored

    def _bake_release(self, obj, image) -> None:
        """Remove this tool's image nodes from ``obj``, then the image, even if the first step raises."""
        try:
            self._bake_cleanup_image_nodes(obj)
        finally:
            if image is not None:
                bpy.data.images.remove(image)

    def _bake_finish_channel(self, obj, image, config: dict, restore_info) -> None:
        """Undo one channel's trick, image nodes and image. Every step runs even if an earlier one raises."""
        try:
            if restore_info is not None:
                if config.get("metallic_trick"):
                    self._bake_restore_metallic_trick(restore_info)
                elif config.get("displacement_trick"):
                    self._bake_restore_displacement_trick(restore_info)
        finally:
            self._bake_release(obj, image)

    def _bake_snapshot_slots(self, obj) -> dict:
        """Record material slots and face material indices so they can be put back."""
        mesh = obj.data
        slots = list(obj.material_slots)
        return {
            "data": list(mesh.materials),
            "links": [s.link for s in slots],
            "object": [s.material if s.link == "OBJECT" else None for s in slots],
            "indices": [p.material_index for p in mesh.polygons],
        }

    def _bake_restore_slots(self, obj, snap: dict) -> None:
        mesh = obj.data
        mesh.materials.clear()
        for mat in snap["data"]:
            mesh.materials.append(mat)
        for slot, link, mat in zip(obj.material_slots, snap["links"], snap["object"]):
            if link == "OBJECT":
                slot.link = "OBJECT"
                slot.material = mat
        indices = snap["indices"]
        if len(indices) == len(mesh.polygons):
            for poly, index in zip(mesh.polygons, indices):
                poly.material_index = index
        mesh.update()

    def _bake_create_image(self, name: str, resolution: int, color_space: str):
        """Create the bake target image. The caller removes it."""
        image = bpy.data.images.new(name, int(resolution), int(resolution), alpha=False)
        try:
            image.colorspace_settings.name = color_space
        except TypeError:
            bpy.data.images.remove(image)
            raise ValueError(f"Unknown color space '{color_space}'") from None
        return image

    def _bake_tracked(self) -> list:
        if not hasattr(self, "_bake_added_nodes"):
            self._bake_added_nodes = []
        return self._bake_added_nodes

    def _bake_set_active_image_node(self, obj, image) -> None:
        """Add an Image Texture node showing ``image`` to each material on ``obj``.

        The node is selected and active, as Cycles requires. What was selected and
        active before is recorded so ``_bake_cleanup_image_nodes`` can put it back.
        """
        mats = self._bake_materials(obj)
        if not mats:
            raise ValueError(
                self._bake_material_problem(obj)
                or f"Object '{obj.name}' has no material to bake onto"
            )
        for mat in mats:
            nodes = mat.node_tree.nodes
            entry = {
                "obj": obj.as_pointer(),
                "tree": mat.node_tree,
                "node": None,
                "active": nodes.active,
                "selected": [(n, n.select) for n in nodes],
                "outputs": self._bake_output_states(mat.node_tree),
            }
            self._bake_tracked().append(entry)
            node = nodes.new("ShaderNodeTexImage")
            entry["node"] = node
            node.image = image
            for other in nodes:
                other.select = False
            node.select = True
            nodes.active = node

    def _bake_cleanup_image_nodes(self, obj) -> None:
        """Remove the nodes ``_bake_set_active_image_node`` added for ``obj`` and restore selection."""
        tracked = self._bake_tracked()
        mine = [e for e in tracked if e["obj"] == obj.as_pointer()]
        tracked[:] = [e for e in tracked if e["obj"] != obj.as_pointer()]
        first = None
        for entry in reversed(mine):
            try:
                self._bake_undo_entry(entry)
            except Exception as exc:  # finish the rest, then report the first
                first = first or exc
        if first is not None:
            raise first

    @staticmethod
    def _bake_output_states(tree) -> list:
        """Each Material Output in ``tree`` with whether it is the active one."""
        return [(n, n.is_active_output) for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]

    @staticmethod
    def _bake_reactivate(outputs: list) -> None:
        """Re-activate the outputs that were active.

        Activating an output deactivates the ones it conflicts with, so only the
        active ones are set. Every one is tried; the first error is re-raised.
        """
        first = None
        for node, active in outputs:
            if not active:
                continue
            try:
                node.is_active_output = True
            except ReferenceError:
                pass
            except Exception as exc:
                first = first or exc
        if first is not None:
            raise first

    @staticmethod
    def _bake_undo_entry(entry: dict) -> None:
        """Remove the node, then restore selection and the active node. Each step runs regardless."""
        first = None
        tree = entry["tree"]
        try:
            nodes = tree.nodes
            node = entry["node"]
            if node is not None:
                try:
                    nodes.remove(node)
                except (ReferenceError, RuntimeError):
                    pass  # already gone
            for other, selected in entry["selected"]:
                try:
                    other.select = selected
                except ReferenceError:
                    pass
                except Exception as exc:
                    first = first or exc
            try:
                nodes.active = entry["active"]
            except ReferenceError:
                pass
            except Exception as exc:
                first = first or exc
            # Removing a node makes Blender re-pick the active Material Output, which
            # can switch a Cycles-only output off. Put the original choice back.
            try:
                BakingHandlersMixin._bake_reactivate(entry["outputs"])
            except Exception as exc:
                first = first or exc
        except ReferenceError:
            return  # the material itself is gone, nothing left to restore
        except Exception as exc:
            first = first or exc
        if first is not None:
            raise first

    def _bake_save_image(self, image, filepath: str, output_format: str) -> None:
        """Write ``image`` to ``filepath``. Raises if no file results."""
        if output_format not in _BAKE_FORMATS:
            raise ValueError(f"Unsupported output format '{output_format}'")
        image.file_format = output_format
        image.filepath_raw = filepath
        image.save()
        if not os.path.isfile(filepath):
            raise RuntimeError(f"Image was not written to {filepath}")

    # --- metallic and displacement tricks ------------------------------------
    #
    # Metallic and displacement have no bake pass of their own, so they are baked
    # as emission. Each trick adds an Emission node and a second Material Output
    # (target Cycles) that is made active, so the material's own links and socket
    # values are never touched. Restoring removes the added nodes and re-activates
    # the outputs that were active. If applying fails partway it undoes itself before raising.

    def _bake_emission_trick(self, obj, source) -> list:
        mats = self._bake_materials(obj)
        if not mats:
            raise ValueError(
                self._bake_material_problem(obj)
                or f"Object '{obj.name}' has no material with nodes"
            )
        info = []
        try:
            for mat in mats:
                tree = mat.node_tree
                entry = {
                    "tree": tree,
                    "added": [],
                    "outputs": self._bake_output_states(tree),
                }
                info.append(entry)
                emit = tree.nodes.new("ShaderNodeEmission")
                entry["added"].append(emit)
                # Read the user's wiring before our own output exists.
                source(tree, emit)
                out = tree.nodes.new("ShaderNodeOutputMaterial")
                entry["added"].append(out)
                # Baking always runs Cycles, which prefers an active output aimed at it
                # over one aimed at all renderers, so aim ours at Cycles.
                out.target = "CYCLES"
                tree.links.new(emit.outputs[0], out.inputs["Surface"])
                out.is_active_output = True
            return info
        except Exception:
            self._bake_undo_trick(info)
            raise

    @staticmethod
    def _bake_undo_trick(info: list) -> None:
        """Remove the added nodes and re-activate the outputs that were active.

        Every entry is finished even if one step raises; the first error is re-raised.
        """
        first = None
        for entry in reversed(info):
            tree = entry["tree"]
            for node in reversed(entry["added"]):
                try:
                    tree.nodes.remove(node)
                except (ReferenceError, RuntimeError):
                    pass  # already gone
                except Exception as exc:
                    first = first or exc
            try:
                BakingHandlersMixin._bake_reactivate(entry["outputs"])
            except Exception as exc:
                first = first or exc
        if first is not None:
            raise first

    @staticmethod
    def _bake_feed_emission(tree, emit, socket, fallback: float) -> None:
        """Drive the emission colour from ``socket``'s link or default, else ``fallback``."""
        if socket is not None and socket.is_linked:
            tree.links.new(socket.links[0].from_socket, emit.inputs["Color"])
            return
        value = fallback
        if socket is not None:
            value = socket.default_value
        emit.inputs["Color"].default_value = (value, value, value, 1.0)

    @staticmethod
    def _bake_active_output(tree):
        """The Material Output Cycles would use: an active Cycles-target one, else any active one."""
        active = [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output]
        for target in ("CYCLES", "ALL"):
            for node in active:
                if node.target == target:
                    return node
        return active[0] if active else None

    def _bake_surface_node(self, tree, node_type: str):
        """The node feeding the active output's Surface if it is ``node_type``, else the first of that type."""
        out = self._bake_active_output(tree)
        if out is not None and out.inputs["Surface"].is_linked:
            node = out.inputs["Surface"].links[0].from_node
            if node.type == node_type:
                return node
        return next((n for n in tree.nodes if n.type == node_type), None)

    def _bake_apply_metallic_trick(self, obj) -> list:
        """Make the Metallic value bake as emission. Returns the info for the restore."""
        socket_name = compat.get_principled_bsdf_inputs()["metallic"]

        def source(tree, emit):
            bsdf = self._bake_surface_node(tree, "BSDF_PRINCIPLED")
            socket = bsdf.inputs.get(socket_name) if bsdf is not None else None
            self._bake_feed_emission(tree, emit, socket, 0.0)

        return self._bake_emission_trick(obj, source)

    def _bake_restore_metallic_trick(self, restore_info: list) -> None:
        self._bake_undo_trick(restore_info)

    def _bake_apply_displacement_trick(self, obj) -> list:
        """Make the Displacement height bake as emission. Returns the info for the restore.

        A material with no displacement bakes the neutral height, 0.5.
        """

        def source(tree, emit):
            socket = None
            out = self._bake_active_output(tree)
            link_in = out.inputs.get("Displacement") if out is not None else None
            if link_in is not None and link_in.is_linked:
                node = link_in.links[0].from_node
                if node.type == "DISPLACEMENT":
                    socket = node.inputs["Height"]
                else:
                    tree.links.new(link_in.links[0].from_socket, emit.inputs["Color"])
                    return
            self._bake_feed_emission(tree, emit, socket, 0.5)

        return self._bake_emission_trick(obj, source)

    def _bake_restore_displacement_trick(self, restore_info: list) -> None:
        self._bake_undo_trick(restore_info)

    @staticmethod
    def _bake_nothing_written(channels, errors: dict) -> dict:
        """The error for a bake that produced no file, whatever the reason."""
        if errors:
            return {"error": "No channel was baked", "errors": errors}
        if not channels:
            return {"error": "No channels were requested, so nothing was baked"}
        return {"error": "Nothing was baked"}

    @_restores_scene
    def _handle_bake_pbr_batch(self, params: dict) -> dict:
        """Bake all requested PBR channels in one call."""

        object_name = require_param(params, "object_name", str)
        output_dir = validate_filepath(require_param(params, "output_dir", str), "output_dir")
        channels = params.get("channels", _ALL_CHANNELS)
        resolution = int(params.get("resolution", 2048))
        output_prefix = params.get("output_prefix", object_name)
        output_format = params.get("output_format", "PNG")
        margin = int(params.get("margin", 16))
        samples = int(params.get("samples", 128))
        use_cage = params.get("use_cage", False)
        cage_extrusion = float(params.get("cage_extrusion", 0.1))
        normal_space = params.get("normal_space", "TANGENT")

        # Validate
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        # Ensure UVs exist
        if not obj.data.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        problem = self._bake_material_problem(obj)
        if problem:
            return {"error": problem}

        # Ensure output dir exists
        os.makedirs(output_dir, exist_ok=True)

        # Switch to Cycles
        _bake_ensure_cycles()
        bpy.context.scene.cycles.samples = samples

        # Select only this object and make active
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        ext = _FORMAT_EXTENSIONS.get(output_format, ".png")
        baked_files = {}
        errors = {}

        for channel in channels:
            channel = channel.upper()
            config = _CHANNEL_BAKE_CONFIG.get(channel)
            if config is None:
                errors[channel] = f"Unknown channel: {channel}"
                continue

            color_space = config.get("color_space", "sRGB")
            img_name = f"__bake_{channel}__"
            image = self._bake_create_image(img_name, resolution, color_space)

            restore_info = None
            try:
                self._bake_set_active_image_node(obj, image)

                # Apply tricks if needed
                if config.get("metallic_trick"):
                    restore_info = self._bake_apply_metallic_trick(obj)
                elif config.get("displacement_trick"):
                    restore_info = self._bake_apply_displacement_trick(obj)

                # Configure bake settings
                bake_type = config["type"]
                bpy.context.scene.render.bake.use_pass_direct = False
                bpy.context.scene.render.bake.use_pass_indirect = False
                bpy.context.scene.render.bake.use_pass_color = True
                bpy.context.scene.render.bake.margin = margin
                bpy.context.scene.render.bake.use_cage = use_cage
                bpy.context.scene.render.bake.cage_extrusion = cage_extrusion

                if channel == "NORMAL":
                    bpy.context.scene.render.bake.normal_space = normal_space

                if channel == "DIFFUSE":
                    bpy.context.scene.render.bake.use_pass_direct = False
                    bpy.context.scene.render.bake.use_pass_indirect = False
                    bpy.context.scene.render.bake.use_pass_color = True

                # Perform the bake
                bpy.ops.object.bake(type=bake_type)

                # Save
                filepath = os.path.join(output_dir, f"{output_prefix}_{channel}{ext}")
                self._bake_save_image(image, filepath, output_format)
                baked_files[channel] = filepath

            except Exception as e:
                errors[channel] = str(e)
            finally:
                self._bake_finish_channel(obj, image, config, restore_info)

        if not baked_files:
            return self._bake_nothing_written(channels, errors)

        result = {
            "success": True,
            "object": object_name,
            "resolution": resolution,
            "output_format": output_format,
            "baked_files": baked_files,
        }
        if errors:
            result["errors"] = errors
        warnings = self._bake_empty_slot_warnings(obj)
        if warnings:
            result["warnings"] = warnings
        return result

    # =================================================================
    # 2. bake_highpoly_to_lowpoly

    # =================================================================

    @_restores_scene
    def _handle_bake_highpoly_to_lowpoly(self, params: dict) -> dict:
        """Bake detail from high-poly onto low-poly using selected_to_active."""

        lowpoly_name = require_param(params, "lowpoly_name", str)
        highpoly_name = require_param(params, "highpoly_name", str)
        output_dir = validate_filepath(require_param(params, "output_dir", str), "output_dir")
        channels = params.get("channels", ["NORMAL", "AO"])
        resolution = int(params.get("resolution", 2048))
        cage_extrusion = float(params.get("cage_extrusion", 0.1))
        output_prefix = params.get("output_prefix", lowpoly_name)
        output_format = params.get("output_format", "PNG")
        margin = int(params.get("margin", 16))
        samples = int(params.get("samples", 128))
        normal_space = params.get("normal_space", "TANGENT")

        # Validate objects
        lowpoly = bpy.data.objects.get(lowpoly_name)
        if lowpoly is None:
            return {"error": f"Low-poly object not found: {lowpoly_name}"}
        if lowpoly.type != "MESH":
            return {"error": f"Low-poly object '{lowpoly_name}' is not a mesh"}

        highpoly = bpy.data.objects.get(highpoly_name)
        if highpoly is None:
            return {"error": f"High-poly object not found: {highpoly_name}"}
        if highpoly.type != "MESH":
            return {"error": f"High-poly object '{highpoly_name}' is not a mesh"}

        if not lowpoly.data.uv_layers:
            return {"error": f"Low-poly object '{lowpoly_name}' has no UV map. Unwrap first."}

        os.makedirs(output_dir, exist_ok=True)

        # The low-poly needs a material to hold the bake target node. One that is
        # added here is removed again before returning.
        target_token = None
        try:
            target_token = self._bake_ensure_target_material(lowpoly)
            problem = self._bake_material_problem(lowpoly)
            if problem:
                return {"error": problem}
            return self._bake_highpoly_channels(
                lowpoly=lowpoly,
                highpoly=highpoly,
                output_dir=output_dir,
                channels=channels,
                resolution=resolution,
                cage_extrusion=cage_extrusion,
                output_prefix=output_prefix,
                output_format=output_format,
                margin=margin,
                samples=samples,
                normal_space=normal_space,
            )
        finally:
            self._bake_drop_target_material(lowpoly, target_token)

    def _bake_highpoly_channels(
        self,
        *,
        lowpoly,
        highpoly,
        output_dir,
        channels,
        resolution,
        cage_extrusion,
        output_prefix,
        output_format,
        margin,
        samples,
        normal_space,
    ) -> dict:
        # Switch to Cycles
        _bake_ensure_cycles()
        bpy.context.scene.cycles.samples = samples

        # Selection: highpoly selected, lowpoly active
        bpy.ops.object.select_all(action="DESELECT")
        highpoly.select_set(True)
        lowpoly.select_set(True)
        bpy.context.view_layer.objects.active = lowpoly

        # Enable selected-to-active
        bpy.context.scene.render.bake.use_selected_to_active = True
        bpy.context.scene.render.bake.cage_extrusion = cage_extrusion
        bpy.context.scene.render.bake.margin = margin

        ext = _FORMAT_EXTENSIONS.get(output_format, ".png")
        baked_files = {}
        errors = {}

        for channel in channels:
            channel = channel.upper()
            config = _CHANNEL_BAKE_CONFIG.get(channel)
            if config is None:
                errors[channel] = f"Unknown channel: {channel}"
                continue

            color_space = config.get("color_space", "sRGB")
            img_name = f"__bake_hp2lp_{channel}__"
            image = self._bake_create_image(img_name, resolution, color_space)

            restore_info = None
            try:
                self._bake_set_active_image_node(lowpoly, image)

                if config.get("metallic_trick"):
                    restore_info = self._bake_apply_metallic_trick(highpoly)
                elif config.get("displacement_trick"):
                    restore_info = self._bake_apply_displacement_trick(highpoly)

                bake_type = config["type"]

                if channel == "DIFFUSE":
                    bpy.context.scene.render.bake.use_pass_direct = False
                    bpy.context.scene.render.bake.use_pass_indirect = False
                    bpy.context.scene.render.bake.use_pass_color = True

                if channel == "NORMAL":
                    bpy.context.scene.render.bake.normal_space = normal_space

                bpy.ops.object.bake(type=bake_type)

                filepath = os.path.join(output_dir, f"{output_prefix}_{channel}{ext}")
                self._bake_save_image(image, filepath, output_format)
                baked_files[channel] = filepath

            except Exception as e:
                errors[channel] = str(e)
            finally:
                self._bake_finish_channel(lowpoly, image, config, restore_info)

        if not baked_files:
            return self._bake_nothing_written(channels, errors)

        result = {
            "success": True,
            "lowpoly": lowpoly.name,
            "highpoly": highpoly.name,
            "resolution": resolution,
            "output_format": output_format,
            "baked_files": baked_files,
        }
        if errors:
            result["errors"] = errors
        warnings = self._bake_empty_slot_warnings(lowpoly)
        if warnings:
            result["warnings"] = warnings
        return result

    # =================================================================
    # 3. bake_from_multires

    # =================================================================

    @_restores_scene
    def _handle_bake_from_multires(self, params: dict) -> dict:
        """Bake normals or displacement from a Multiresolution modifier."""

        object_name = require_param(params, "object_name", str)
        output_path = validate_filepath(require_param(params, "output_path", str), "output_path")
        map_type = params.get("map_type", "NORMALS").upper()
        resolution = int(params.get("resolution", 2048))
        margin = int(params.get("margin", 16))

        if map_type not in ("NORMALS", "DISPLACEMENT"):
            return {"error": f"map_type must be NORMALS or DISPLACEMENT, got '{map_type}'"}

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        if not obj.data.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        # Find multiresolution modifier
        multires_mod = None
        for mod in obj.modifiers:
            if mod.type == "MULTIRES":
                multires_mod = mod
                break

        if multires_mod is None:
            return {"error": f"Object '{object_name}' has no Multiresolution modifier"}

        if multires_mod.total_levels < 1:
            return {"error": "Multiresolution modifier has no subdivision levels"}

        # Ensure at least one material for bake target. One added here is removed
        # again before returning.
        target_token = None
        image = None
        restore_level = None
        try:
            target_token = self._bake_ensure_target_material(obj)
            problem = self._bake_material_problem(obj)
            if problem:
                return {"error": problem}

            # Ensure output dir exists
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            # Switch to Cycles
            _bake_ensure_cycles()

            # Select and activate
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            # The bake transfers detail from the top level down to the modifier's
            # viewport level. At the top level there is nothing to transfer (a
            # displacement map comes out flat), so bake to level 0 in that case and
            # put the user's level back afterwards.
            bake_level = multires_mod.levels
            if bake_level >= multires_mod.total_levels:
                restore_level = bake_level
                bake_level = 0
                multires_mod.levels = bake_level

            # Create bake target image
            color_space = "Non-Color"
            img_name = f"__bake_multires_{map_type}__"
            image = self._bake_create_image(img_name, resolution, color_space)
            self._bake_set_active_image_node(obj, image)

            # Multires baking is its own operator, switched on by scene settings that
            # live in different places across Blender versions. The scene state
            # captured above is restored afterwards: left on, use_multires would turn
            # every later bake into a multires bake.
            bake_settings = bpy.context.scene.render.bake
            if hasattr(bake_settings, "use_multires"):
                owner, names = bake_settings, ("use_multires", "type", "margin", "use_clear")
            else:
                owner = bpy.context.scene.render
                names = ("use_bake_multires", "bake_type", "bake_margin", "use_bake_clear")
            setattr(owner, names[0], True)
            setattr(owner, names[1], map_type)
            setattr(owner, names[2], margin)
            setattr(owner, names[3], True)
            bpy.ops.object.bake_image()

            self._bake_save_image(image, output_path, "PNG")

            result = {
                "success": True,
                "object": object_name,
                "map_type": map_type,
                "resolution": resolution,
                "output_path": output_path,
                "multires_levels": multires_mod.total_levels,
                "bake_level": bake_level,
            }
            warnings = self._bake_empty_slot_warnings(obj)
            if warnings:
                result["warnings"] = warnings
            return result
        except Exception as e:
            return {"error": f"Multires bake failed: {e}"}
        finally:
            try:
                if restore_level is not None:
                    multires_mod.levels = restore_level
            finally:
                try:
                    self._bake_release(obj, image)
                finally:
                    self._bake_drop_target_material(obj, target_token)

    # =================================================================
    # 4. bake_to_vertex_colors

    # =================================================================

    @_restores_scene
    def _handle_bake_to_vertex_colors(self, params: dict) -> dict:
        """Bake to a temporary image then transfer pixel data to vertex colors."""
        import numpy as np

        object_name = require_param(params, "object_name", str)
        bake_type = params.get("bake_type", "AO").upper()
        vertex_color_name = params.get("vertex_color_name", "BakedColor")
        samples = int(params.get("samples", 64))

        if bake_type not in ("AO", "DIFFUSE", "COMBINED"):
            return {"error": f"bake_type must be AO, DIFFUSE, or COMBINED, got '{bake_type}'"}

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        mesh = obj.data
        if not mesh.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        # Ensure at least one material. One added here is removed again before returning.
        target_token = None
        image = None
        try:
            target_token = self._bake_ensure_target_material(obj)
            problem = self._bake_material_problem(obj)
            if problem:
                return {"error": problem}

            # Switch to Cycles
            _bake_ensure_cycles()
            bpy.context.scene.cycles.samples = samples

            # Select and activate
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            # Use a moderate resolution for vertex color transfer
            temp_res = 1024
            img_name = "__bake_vertex_color_temp__"
            image = self._bake_create_image(img_name, temp_res, "sRGB")
            self._bake_set_active_image_node(obj, image)

            # Configure and bake
            if bake_type == "DIFFUSE":
                bpy.context.scene.render.bake.use_pass_direct = False
                bpy.context.scene.render.bake.use_pass_indirect = False
                bpy.context.scene.render.bake.use_pass_color = True

            bpy.ops.object.bake(type=bake_type)

            # Read pixel data from the baked image
            pixel_count = temp_res * temp_res
            pixels = np.zeros(pixel_count * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            pixels = pixels.reshape((temp_res, temp_res, 4))

            # Create or get vertex color layer
            if vertex_color_name in mesh.color_attributes:
                vcol = mesh.color_attributes[vertex_color_name]
            else:
                vcol = mesh.color_attributes.new(
                    name=vertex_color_name,
                    type="BYTE_COLOR",
                    domain="CORNER",
                )

            # Get active UV layer
            uv_layer = mesh.uv_layers.active

            # Transfer baked pixels to vertex colors by sampling the image at each
            # loop's UV coordinate
            for poly in mesh.polygons:
                for loop_idx in poly.loop_indices:
                    uv = uv_layer.data[loop_idx].uv
                    # Clamp UV to [0, 1]
                    u = max(0.0, min(uv[0], 1.0))
                    v = max(0.0, min(uv[1], 1.0))
                    # Pixel coordinates
                    px = int(u * (temp_res - 1))
                    py = int(v * (temp_res - 1))
                    color = pixels[py, px]
                    vcol.data[loop_idx].color = (
                        float(color[0]),
                        float(color[1]),
                        float(color[2]),
                        float(color[3]),
                    )

            result = {
                "success": True,
                "object": object_name,
                "bake_type": bake_type,
                "vertex_color_layer": vertex_color_name,
                "loop_count": len(mesh.loops),
            }
            warnings = self._bake_empty_slot_warnings(obj)
            if warnings:
                result["warnings"] = warnings
            return result
        except ImportError:
            # numpy not available -- fallback without numpy
            return {"error": "numpy is required for vertex color baking but is not available"}
        except Exception as e:
            return {"error": f"Vertex color bake failed: {e}"}
        finally:
            try:
                self._bake_release(obj, image)
            finally:
                self._bake_drop_target_material(obj, target_token)

    # =================================================================
    # 5. bake_curvature

    # =================================================================

    def _handle_bake_curvature(self, params: dict) -> dict:
        """Calculate per-vertex curvature via bmesh and bake to an image."""
        import bmesh
        import numpy as np
        from mathutils import Vector

        object_name = require_param(params, "object_name", str)
        output_path = validate_filepath(require_param(params, "output_path", str), "output_path")
        resolution = int(params.get("resolution", 2048))
        cavity_type = params.get("cavity_type", "BOTH").upper()

        if cavity_type not in ("CONCAVE", "CONVEX", "BOTH"):
            return {"error": f"cavity_type must be CONCAVE, CONVEX, or BOTH, got '{cavity_type}'"}

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        mesh = obj.data
        if not mesh.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        bm = None
        image = None
        try:
            # Calculate curvature using bmesh
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            # Per-vertex curvature: dot product of vertex normal vs average of
            # connected neighbor normals. Values < 0 = convex, > 0 = concave.
            vert_curvature = {}
            for vert in bm.verts:
                if not vert.link_edges:
                    vert_curvature[vert.index] = 0.5
                    continue

                # Average neighbor normal
                neighbor_normal = Vector((0.0, 0.0, 0.0))
                count = 0
                for edge in vert.link_edges:
                    other = edge.other_vert(vert)
                    neighbor_normal += other.normal
                    count += 1

                if count == 0:
                    vert_curvature[vert.index] = 0.5
                    continue

                neighbor_normal /= count
                neighbor_normal.normalize()

                # Dot product: 1 = same direction (flat), < 1 = curvature
                dot = vert.normal.dot(neighbor_normal)
                # Map to 0-1 range: 0.5 = flat, 0 = concave, 1 = convex
                # dot=1 (flat), dot<1 (curved)
                # Use cross product to determine concavity direction
                curvature_amount = 1.0 - dot  # 0 for flat, larger for more curved

                # Determine concave vs convex by checking if neighbor center is
                # above or below the vertex along its normal
                neighbor_center = Vector((0.0, 0.0, 0.0))
                for edge in vert.link_edges:
                    other = edge.other_vert(vert)
                    neighbor_center += other.co
                neighbor_center /= count
                direction = (neighbor_center - vert.co).dot(vert.normal)

                if cavity_type == "BOTH":
                    # Map: concave = dark (0), flat = 0.5, convex = bright (1)
                    if direction > 0:
                        # Concave
                        value = 0.5 - curvature_amount * 2.5
                    else:
                        # Convex
                        value = 0.5 + curvature_amount * 2.5
                    value = max(0.0, min(1.0, value))
                elif cavity_type == "CONCAVE":
                    # Only show concave: bright where concave, black elsewhere
                    if direction > 0:
                        value = min(1.0, curvature_amount * 5.0)
                    else:
                        value = 0.0
                else:  # CONVEX
                    # Only show convex: bright where convex, black elsewhere
                    if direction <= 0:
                        value = min(1.0, curvature_amount * 5.0)
                    else:
                        value = 0.0

                vert_curvature[vert.index] = value

            # Create output image
            image = bpy.data.images.new(
                "__bake_curvature__", width=resolution, height=resolution, alpha=False
            )
            pixel_count = resolution * resolution
            pixels = np.full(pixel_count * 4, 0.5, dtype=np.float32)
            # Set alpha to 1
            pixels[3::4] = 1.0

            # Rasterize curvature to UV space
            uv_layer_name = mesh.uv_layers.active.name

            # Get UV layer from bmesh
            bm_uv = bm.loops.layers.uv.get(uv_layer_name)
            if bm_uv is None:
                return {"error": "Could not find UV layer in bmesh"}

            # For each face, rasterize triangle by sampling curvature at vertices
            for face in bm.faces:
                face_loops = list(face.loops)
                if len(face_loops) < 3:
                    continue

                # Triangulate the face for rasterization
                for i in range(1, len(face_loops) - 1):
                    l0 = face_loops[0]
                    l1 = face_loops[i]
                    l2 = face_loops[i + 1]

                    uv0 = l0[bm_uv].uv
                    uv1 = l1[bm_uv].uv
                    uv2 = l2[bm_uv].uv

                    c0 = vert_curvature.get(l0.vert.index, 0.5)
                    c1 = vert_curvature.get(l1.vert.index, 0.5)
                    c2 = vert_curvature.get(l2.vert.index, 0.5)

                    # Bounding box in pixel space
                    min_u = max(0, int(min(uv0.x, uv1.x, uv2.x) * resolution))
                    max_u = min(resolution - 1, int(max(uv0.x, uv1.x, uv2.x) * resolution) + 1)
                    min_v = max(0, int(min(uv0.y, uv1.y, uv2.y) * resolution))
                    max_v = min(resolution - 1, int(max(uv0.y, uv1.y, uv2.y) * resolution) + 1)

                    # Rasterize using barycentric coordinates
                    for py in range(min_v, max_v + 1):
                        for px in range(min_u, max_u + 1):
                            # Point in UV space
                            p = (px / resolution, py / resolution)

                            # Barycentric coordinates
                            denom = (uv1.y - uv2.y) * (uv0.x - uv2.x) + (uv2.x - uv1.x) * (
                                uv0.y - uv2.y
                            )
                            if abs(denom) < 1e-10:
                                continue

                            w0 = (
                                (uv1.y - uv2.y) * (p[0] - uv2.x) + (uv2.x - uv1.x) * (p[1] - uv2.y)
                            ) / denom
                            w1 = (
                                (uv2.y - uv0.y) * (p[0] - uv2.x) + (uv0.x - uv2.x) * (p[1] - uv2.y)
                            ) / denom
                            w2 = 1.0 - w0 - w1

                            if w0 < -0.001 or w1 < -0.001 or w2 < -0.001:
                                continue

                            # Interpolate curvature
                            curv = w0 * c0 + w1 * c1 + w2 * c2
                            curv = max(0.0, min(1.0, curv))

                            idx = (py * resolution + px) * 4
                            pixels[idx] = curv
                            pixels[idx + 1] = curv
                            pixels[idx + 2] = curv
                            pixels[idx + 3] = 1.0

            # Write pixels to image
            image.pixels.foreach_set(pixels.tolist())
            self._bake_save_image(image, output_path, "PNG")

            return {
                "success": True,
                "object": object_name,
                "cavity_type": cavity_type,
                "resolution": resolution,
                "output_path": output_path,
                "vertex_count": len(vert_curvature),
            }
        except ImportError:
            return {"error": "numpy is required for curvature baking but is not available"}
        except Exception as e:
            return {"error": f"Curvature bake failed: {e}"}
        finally:
            if bm is not None:
                bm.free()
            if image is not None:
                bpy.data.images.remove(image)

    # =================================================================
    # 6. bake_id_map

    # =================================================================

    @_restores_scene
    def _handle_bake_id_map(self, params: dict) -> dict:
        """Bake a color ID map with distinct colors per material/object/face set."""
        import random

        object_name = require_param(params, "object_name", str)
        output_path = validate_filepath(require_param(params, "output_path", str), "output_path")
        resolution = int(params.get("resolution", 2048))
        color_mode = params.get("color_mode", "PER_MATERIAL").upper()

        if color_mode not in ("PER_MATERIAL", "PER_OBJECT", "PER_FACE_SET"):
            return {
                "error": f"color_mode must be PER_MATERIAL, PER_OBJECT, or PER_FACE_SET, got '{color_mode}'"
            }

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        mesh = obj.data
        if not mesh.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # Generate a palette of visually distinct colors
        def generate_distinct_colors(n):
            """Generate n visually distinct colors using golden ratio hue spacing."""
            colors = []
            golden_ratio = 0.618033988749895
            hue = random.random()
            for _ in range(max(n, 1)):
                hue = (hue + golden_ratio) % 1.0
                # HSV to RGB (saturation=0.85, value=0.9 for vivid distinct colors)
                import colorsys

                r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.9)
                colors.append((r, g, b, 1.0))
            return colors

        # Record slots and face material indices. They are put back in the finally
        # block below, on success and on failure alike.
        snap = self._bake_snapshot_slots(obj)
        original_materials = [slot.material for slot in obj.material_slots]

        def emission_material(name, color):
            mat = bpy.data.materials.new(name=name)
            temp_materials.append(mat)
            mat.use_nodes = True
            tree = mat.node_tree
            tree.nodes.clear()
            emit = tree.nodes.new("ShaderNodeEmission")
            emit.inputs["Color"].default_value = color
            emit.inputs["Strength"].default_value = 1.0
            output = tree.nodes.new("ShaderNodeOutputMaterial")
            tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
            return mat

        def assign_groups(groups, label_for):
            """Give each group of faces its own colour.

            ``groups`` maps a key to face indices; ``label_for`` names a key in the result.
            """
            import bmesh

            keys = sorted(groups)
            palette = generate_distinct_colors(len(keys))
            mats = []
            for i, key in enumerate(keys):
                mats.append(emission_material(f"__id_{i}__", palette[i]))
                id_colors[label_for(key)] = list(palette[i][:3])
            mesh.materials.clear()
            for mat in mats:
                mesh.materials.append(mat)
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                bm.faces.ensure_lookup_table()
                for i, key in enumerate(keys):
                    for face_idx in groups[key]:
                        bm.faces[face_idx].material_index = i
                bm.to_mesh(mesh)
            finally:
                bm.free()

        # Build color assignments depending on mode
        id_colors = {}
        temp_materials = []
        image = None

        try:
            # Switch to Cycles
            _bake_ensure_cycles()
            bpy.context.scene.cycles.samples = 1  # Emission needs minimal samples

            # Select and activate
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            if color_mode == "PER_MATERIAL":
                num_slots = max(len(obj.material_slots), 1)
                palette = generate_distinct_colors(num_slots)

                # For each material slot, create a temp emission material
                mats = []
                for i in range(num_slots):
                    mats.append(emission_material(f"__id_mat_{i}__", palette[i]))
                    orig = original_materials[i] if i < len(original_materials) else None
                    orig_name = orig.name if orig else f"Slot_{i}"
                    id_colors[orig_name] = list(palette[i][:3])

                # Ensure enough slots, then assign the temp materials
                while len(obj.material_slots) < num_slots:
                    obj.data.materials.append(None)
                for i in range(num_slots):
                    obj.material_slots[i].material = mats[i]

            elif color_mode == "PER_OBJECT":
                # For a single object, assign one color per loose part: connected
                # components of faces.
                import bmesh

                bm = bmesh.new()
                try:
                    bm.from_mesh(mesh)
                    bm.faces.ensure_lookup_table()
                    visited = set()
                    components = {}
                    for face in bm.faces:
                        if face.index in visited:
                            continue
                        component = []
                        stack = [face]
                        while stack:
                            f = stack.pop()
                            if f.index in visited:
                                continue
                            visited.add(f.index)
                            component.append(f.index)
                            for edge in f.edges:
                                for linked_face in edge.link_faces:
                                    if linked_face.index not in visited:
                                        stack.append(linked_face)
                        components[len(components)] = component
                finally:
                    bm.free()
                assign_groups(components, lambda key: f"Part_{key}")

            elif color_mode == "PER_FACE_SET":
                # Use sculpt face sets if available, else material index as the proxy.
                import bmesh

                bm = bmesh.new()
                try:
                    bm.from_mesh(mesh)
                    bm.faces.ensure_lookup_table()
                    face_set_layer = bm.faces.layers.int.get(".sculpt_face_set")
                    face_sets = {}
                    for face in bm.faces:
                        key = (
                            face.material_index if face_set_layer is None else face[face_set_layer]
                        )
                        face_sets.setdefault(key, []).append(face.index)
                finally:
                    bm.free()
                assign_groups(face_sets, lambda key: f"FaceSet_{key}")

            # Create bake target image
            img_name = "__bake_id_map__"
            image = self._bake_create_image(img_name, resolution, "sRGB")
            self._bake_set_active_image_node(obj, image)

            # Bake emission
            bpy.context.scene.render.bake.margin = 16
            bpy.ops.object.bake(type="EMIT")

            # Save
            self._bake_save_image(image, output_path, "PNG")

            return {
                "success": True,
                "object": object_name,
                "color_mode": color_mode,
                "resolution": resolution,
                "output_path": output_path,
                "id_colors": id_colors,
            }
        except Exception as e:
            return {"error": f"ID map bake failed: {e}"}
        finally:
            # Put the original materials, slots and face indices back before the temp
            # materials are removed, so nothing still points at them.
            try:
                self._bake_release(obj, image)
            finally:
                try:
                    self._bake_restore_slots(obj, snap)
                finally:
                    for mat in temp_materials:
                        bpy.data.materials.remove(mat)

    # ========== Geometry Nodes Handlers ==========
