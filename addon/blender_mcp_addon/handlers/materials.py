"""Material-related command handlers."""

import os
import tempfile
from typing import Any

import bpy

from .. import compat
from ..utils import (
    get_material_or_error,
    get_object_or_error,
    serialize_material,
)
from ..validation import (
    ValidationError,
    require_param,
    validate_color,
)
from ._helpers import (
    _PRESET_BUILDERS,
    _SOCKET_TYPE_MAP,
    _extract_pbr_values,
)


class MaterialHandlersMixin:
    """Mixin for material-related handlers."""

    def _handle_material_create(self, params: dict) -> dict:
        """Create a new material."""
        name = params.get("name", "Material")
        use_nodes = params.get("use_nodes", True)

        mat = bpy.data.materials.new(name)
        mat.use_nodes = use_nodes

        return serialize_material(mat)


    def _handle_material_assign(self, params: dict) -> dict:
        """Assign a material to an object."""
        object_name = require_param(params, "object_name", str)
        material_name = require_param(params, "material_name", str)

        obj = get_object_or_error(object_name)
        mat = get_material_or_error(material_name)

        if obj.type != "MESH":
            raise ValidationError(
                f"Cannot assign material: '{obj.name}' is a {obj.type}, not a MESH"
            )

        slot_index = params.get("slot_index")
        if slot_index is not None and slot_index < len(obj.material_slots):
            obj.material_slots[slot_index].material = mat
        else:
            obj.data.materials.append(mat)

        return {"object": obj.name, "material": mat.name}


    def _handle_material_set_color(self, params: dict) -> dict:
        """Set material base color."""
        material_name = require_param(params, "material_name", str)
        mat = get_material_or_error(material_name)
        color = validate_color(params.get("color"), "color")

        if not mat.use_nodes:
            mat.use_nodes = True

        # Find Principled BSDF
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                node.inputs["Base Color"].default_value = color
                break

        return {"material": mat.name, "color": list(color)}


    def _handle_material_set_principled(self, params: dict) -> dict:
        """Configure Principled BSDF parameters."""
        mat = get_material_or_error(params["material_name"])

        if not mat.use_nodes:
            mat.use_nodes = True

        input_mapping = compat.get_principled_bsdf_inputs()

        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                for key, value in params.items():
                    if key == "material_name":
                        continue
                    input_name = input_mapping.get(key)
                    if input_name and input_name in node.inputs:
                        inp = node.inputs[input_name]
                        if isinstance(value, (list, tuple)):
                            inp.default_value = value
                        else:
                            inp.default_value = float(value)
                break

        return serialize_material(mat)


    def _handle_material_add_texture(self, params: dict) -> dict:
        """Add image texture node to material."""
        mat = get_material_or_error(params["material_name"])
        image_path = params["image_path"]
        connect_to = params.get("connect_to", "Base Color")

        if not mat.use_nodes:
            mat.use_nodes = True

        # Load image
        image = bpy.data.images.load(image_path)

        # Create texture node
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        tex_node.location = (-300, 300)

        # Find Principled BSDF and connect
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                if connect_to in node.inputs:
                    mat.node_tree.links.new(tex_node.outputs["Color"], node.inputs[connect_to])
                break

        return {"material": mat.name, "image": image.name}


    def _handle_material_list(self, params: dict) -> dict:
        """List all materials."""
        materials = [{"name": mat.name, "users": mat.users} for mat in bpy.data.materials]
        return {"materials": materials}

    # ========== Modifier Handlers ==========

    # Common modifier types supported
    MODIFIER_TYPES = [
        "SUBSURF", "BEVEL", "SOLIDIFY", "ARRAY", "MIRROR", "BOOLEAN",
        "DECIMATE", "SMOOTH", "WEIGHTED_NORMAL", "TRIANGULATE", "WIREFRAME",
        "SKIN", "REMESH", "SCREW", "SHRINKWRAP", "SIMPLE_DEFORM", "WELD",
        "EDGE_SPLIT", "MASK", "LATTICE", "CURVE", "CAST", "WAVE",
        "DISPLACE", "BUILD", "OCEAN", "CLOTH", "COLLISION", "SOFT_BODY",
    ]

    # Default configurations for common modifiers
    MODIFIER_PRESETS = {
        "SUBSURF": {"levels": 2, "render_levels": 2},
        "BEVEL": {"width": 0.02, "segments": 3},
        "SOLIDIFY": {"thickness": 0.1},
        "ARRAY": {"count": 3, "relative_offset_displace": (1, 0, 0)},
        "MIRROR": {"use_axis": (True, False, False)},
        "DECIMATE": {"ratio": 0.5},
        "SMOOTH": {"factor": 0.5, "iterations": 1},
        "WIREFRAME": {"thickness": 0.02},
        "TRIANGULATE": {"quad_method": "BEAUTY"},
    }


    def _handle_material_inspect_graph(self, params: dict) -> dict:
        """Return the full shader node graph as structured JSON."""
        material_name = require_param(params, "material_name", str)
        mat = get_material_or_error(material_name)

        if not mat.use_nodes or mat.node_tree is None:
            return {
                "material": mat.name,
                "use_nodes": False,
                "nodes": [],
                "links": [],
            }

        tree = mat.node_tree

        # --- Serialise nodes ---
        nodes_out = []
        for node in tree.nodes:
            node_data = {
                "name": node.name,
                "type": node.type,
                "bl_idname": node.bl_idname,
                "label": node.label,
                "location": [node.location.x, node.location.y],
                "inputs": [],
                "outputs": [],
            }

            # Inputs
            for inp in node.inputs:
                inp_data: dict[str, Any] = {
                    "name": inp.name,
                    "type": inp.type,
                    "is_linked": inp.is_linked,
                }
                if hasattr(inp, "default_value"):
                    try:
                        val = inp.default_value
                        if hasattr(val, "__iter__") and not isinstance(val, str):
                            inp_data["default_value"] = [float(v) for v in val]
                        else:
                            inp_data["default_value"] = float(val)
                    except (TypeError, ValueError):
                        inp_data["default_value"] = str(val)
                node_data["inputs"].append(inp_data)

            # Outputs
            for out in node.outputs:
                out_data: dict[str, Any] = {
                    "name": out.name,
                    "type": out.type,
                    "is_linked": out.is_linked,
                }
                node_data["outputs"].append(out_data)

            nodes_out.append(node_data)

        # --- Serialise links ---
        links_out = []
        for link in tree.links:
            links_out.append({
                "from_node": link.from_node.name,
                "from_output": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_input": link.to_socket.name,
            })

        return {
            "material": mat.name,
            "use_nodes": True,
            "node_count": len(nodes_out),
            "link_count": len(links_out),
            "nodes": nodes_out,
            "links": links_out,
        }


    # =====================================================================
    # 2. material_node_add

    # =====================================================================


    def _handle_material_node_add(self, params: dict) -> dict:
        """Add a shader node to a material."""
        material_name = require_param(params, "material_name", str)
        node_type = require_param(params, "node_type", str)
        mat = get_material_or_error(material_name)

        if not mat.use_nodes:
            mat.use_nodes = True

        tree = mat.node_tree

        try:
            node = tree.nodes.new(node_type)
        except RuntimeError as exc:
            return {"error": f"Failed to create node of type '{node_type}': {exc}"}

        # Optional name
        name = params.get("name")
        if name:
            node.name = name
            node.label = name

        # Optional location
        location = params.get("location")
        if location and isinstance(location, (list, tuple)) and len(location) >= 2:
            node.location = (float(location[0]), float(location[1]))

        # Optional input default values
        inputs = params.get("inputs")
        if inputs and isinstance(inputs, dict):
            for input_name, value in inputs.items():
                if input_name in node.inputs:
                    inp = node.inputs[input_name]
                    if hasattr(inp, "default_value"):
                        try:
                            if isinstance(value, (list, tuple)):
                                inp.default_value = value
                            else:
                                inp.default_value = float(value)
                        except (TypeError, ValueError):
                            pass  # skip incompatible types silently

        return {
            "material": mat.name,
            "node_name": node.name,
            "node_type": node.bl_idname,
            "location": [node.location.x, node.location.y],
        }


    # =====================================================================
    # 3. material_node_connect

    # =====================================================================


    def _handle_material_node_connect(self, params: dict) -> dict:
        """Connect two nodes in a material's node graph."""
        material_name = require_param(params, "material_name", str)
        from_node_name = require_param(params, "from_node", str)
        from_output_name = require_param(params, "from_output", str)
        to_node_name = require_param(params, "to_node", str)
        to_input_name = require_param(params, "to_input", str)

        mat = get_material_or_error(material_name)

        if not mat.use_nodes or mat.node_tree is None:
            return {"error": f"Material '{material_name}' has no node tree"}

        tree = mat.node_tree

        # Look up nodes
        from_node = tree.nodes.get(from_node_name)
        if from_node is None:
            return {"error": f"Node not found: '{from_node_name}'"}

        to_node = tree.nodes.get(to_node_name)
        if to_node is None:
            return {"error": f"Node not found: '{to_node_name}'"}

        # Look up sockets
        from_socket = from_node.outputs.get(from_output_name)
        if from_socket is None:
            available = [o.name for o in from_node.outputs]
            return {"error": f"Output '{from_output_name}' not found on '{from_node_name}'. Available: {available}"}

        to_socket = to_node.inputs.get(to_input_name)
        if to_socket is None:
            available = [i.name for i in to_node.inputs]
            return {"error": f"Input '{to_input_name}' not found on '{to_node_name}'. Available: {available}"}

        tree.links.new(from_socket, to_socket)

        return {
            "material": mat.name,
            "link": {
                "from_node": from_node.name,
                "from_output": from_socket.name,
                "to_node": to_node.name,
                "to_input": to_socket.name,
            },
        }


    # =====================================================================
    # 4. material_node_group_create

    # =====================================================================


    def _handle_material_node_group_create(self, params: dict) -> dict:
        """Create a reusable shader node group."""
        name = require_param(params, "name", str)

        group = bpy.data.node_groups.new(name, "ShaderNodeTree")

        # The group always has a Group Input and Group Output node
        input_node = group.nodes.new("NodeGroupInput")
        input_node.location = (-400, 0)
        output_node = group.nodes.new("NodeGroupOutput")
        output_node.location = (400, 0)

        inputs_spec = params.get("inputs", [])
        outputs_spec = params.get("outputs", [])

        created_inputs = []
        created_outputs = []

        # Add input sockets
        for inp_def in inputs_spec:
            inp_name = inp_def.get("name", "Input")
            inp_type = inp_def.get("type", "FLOAT").upper()
            socket_type = _SOCKET_TYPE_MAP.get(inp_type, "NodeSocketFloat")

            group.interface.new_socket(name=inp_name, in_out="INPUT", socket_type=socket_type)
            created_inputs.append({"name": inp_name, "type": inp_type})

            # Set default value if provided
            default = inp_def.get("default")
            if default is not None:
                # Defaults are set on the Group Input node's outputs
                idx = len(created_inputs) - 1
                if idx < len(input_node.outputs) - 1:  # -1 for the virtual socket
                    sock = input_node.outputs[idx]
                    if hasattr(sock, "default_value"):
                        try:
                            if isinstance(default, (list, tuple)):
                                sock.default_value = default
                            else:
                                sock.default_value = float(default)
                        except (TypeError, ValueError):
                            pass

        # Add output sockets
        for out_def in outputs_spec:
            out_name = out_def.get("name", "Output")
            out_type = out_def.get("type", "FLOAT").upper()
            socket_type = _SOCKET_TYPE_MAP.get(out_type, "NodeSocketFloat")

            group.interface.new_socket(name=out_name, in_out="OUTPUT", socket_type=socket_type)
            created_outputs.append({"name": out_name, "type": out_type})

        return {
            "name": group.name,
            "inputs": created_inputs,
            "outputs": created_outputs,
        }


    # =====================================================================
    # 5. material_procedural_preset

    # =====================================================================


    def _handle_material_procedural_preset(self, params: dict) -> dict:
        """Create a complex procedural material from a preset."""
        name = require_param(params, "name", str)
        preset = require_param(params, "preset", str).upper()

        valid_presets = [
            "VEHICLE_PAINT", "BRUSHED_METAL", "CHROME", "RUBBER",
            "CARBON_FIBER", "ASPHALT", "TARMAC", "WORN_METAL",
            "GLASS", "PLASTIC_GLOSSY", "PLASTIC_MATTE", "CONCRETE",
            "FABRIC", "REFLECTIVE_TAPE", "LED_DISPLAY", "RUST",
            "GOLD", "COPPER", "SCRATCHED_PAINT", "SNOW", "WATER",
            "WOOD", "BRICK",
        ]
        if preset not in valid_presets:
            return {"error": f"Unknown preset '{preset}'. Valid: {valid_presets}"}

        color = params.get("color")
        wear_amount = float(params.get("wear_amount", 0.5))
        scale = float(params.get("scale", 1.0))

        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        tree = mat.node_tree

        # Clear default nodes
        for n in list(tree.nodes):
            tree.nodes.remove(n)

        # Dispatch to per-preset builder
        builder = _PRESET_BUILDERS.get(preset)
        if builder is None:
            return {"error": f"Preset builder not implemented for '{preset}'"}

        try:
            builder(tree, color, wear_amount, scale)
        except Exception as exc:
            return {"error": f"Failed to build preset '{preset}': {exc}"}

        return {
            "material": mat.name,
            "preset": preset,
            "node_count": len(tree.nodes),
            "link_count": len(tree.links),
        }


    # =====================================================================
    # 6. material_convert_to_pbr

    # =====================================================================


    def _handle_material_convert_to_pbr(self, params: dict) -> dict:
        """Convert a material to a clean Principled BSDF setup."""
        material_name = require_param(params, "material_name", str)
        target_format = require_param(params, "target_format", str).upper()

        valid_formats = ["GLTF", "MSFS", "UE5", "GENERIC"]
        if target_format not in valid_formats:
            return {"error": f"Unknown target_format '{target_format}'. Valid: {valid_formats}"}

        mat = get_material_or_error(material_name)

        if not mat.use_nodes or mat.node_tree is None:
            mat.use_nodes = True

        tree = mat.node_tree

        # ── Phase 1: extract values from existing graph ──────────────
        extracted = _extract_pbr_values(tree)

        # ── Phase 2: clear and rebuild ───────────────────────────────
        for node in list(tree.nodes):
            tree.nodes.remove(node)

        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (300, 0)
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        # Apply extracted values
        bsdf.inputs["Base Color"].default_value = extracted["base_color"]
        bsdf.inputs["Metallic"].default_value = extracted["metallic"]
        bsdf.inputs["Roughness"].default_value = extracted["roughness"]
        bsdf.inputs["Alpha"].default_value = extracted["alpha"]

        if extracted.get("emission_color"):
            bsdf.inputs["Emission Color"].default_value = extracted["emission_color"]
            bsdf.inputs["Emission Strength"].default_value = extracted.get("emission_strength", 1.0)

        if extracted.get("transmission"):
            bsdf.inputs["Transmission Weight"].default_value = extracted["transmission"]

        # ── Phase 3: format-specific adjustments ────────────────────
        texture_nodes_info = []

        if extracted.get("base_color_image"):
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.location = (-400, 300)
            tex.image = extracted["base_color_image"]
            tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            texture_nodes_info.append({"type": "base_color", "image": tex.image.name})

        if target_format == "GLTF":
            # glTF expects ORM packed texture; we just ensure clean Principled
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
        elif target_format == "MSFS":
            # MSFS uses standard Principled but needs specific naming
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
        elif target_format == "UE5":
            # UE5 uses a similar PBR model but spec = 0.5 default
            bsdf.inputs["Specular IOR Level"].default_value = 0.5

        return {
            "material": mat.name,
            "target_format": target_format,
            "extracted": {
                "base_color": list(extracted["base_color"]),
                "metallic": extracted["metallic"],
                "roughness": extracted["roughness"],
                "alpha": extracted["alpha"],
                "has_emission": bool(extracted.get("emission_color")),
                "has_transmission": bool(extracted.get("transmission")),
                "has_textures": len(texture_nodes_info) > 0,
            },
            "textures": texture_nodes_info,
            "node_count": len(tree.nodes),
        }


    # =====================================================================
    # 7. material_preview_render

    # =====================================================================


    def _handle_material_preview_render(self, params: dict) -> dict:
        """Render a material preview on a standard shape."""
        material_name = require_param(params, "material_name", str)
        mat = get_material_or_error(material_name)

        preview_shape = params.get("preview_shape", "SPHERE").upper()
        if preview_shape not in ("SPHERE", "CUBE", "PLANE", "CYLINDER"):
            return {"error": f"Invalid preview_shape '{preview_shape}'. Must be SPHERE, CUBE, PLANE, or CYLINDER."}

        resolution = int(params.get("resolution", 512))
        engine = params.get("engine", "EEVEE").upper()
        if engine not in ("EEVEE", "CYCLES"):
            return {"error": f"Invalid engine '{engine}'. Must be EEVEE or CYCLES."}

        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in material_name)
        output_path = params.get("output_path", os.path.join(tempfile.gettempdir(), f"material_preview_{safe_name}.png"))

        # Remember current state
        original_scene = bpy.context.window.scene

        try:
            # ── Create temporary scene ──────────────────────────────
            preview_scene = bpy.data.scenes.new("__mat_preview_tmp__")
            bpy.context.window.scene = preview_scene

            # Set render settings
            preview_scene.render.resolution_x = resolution
            preview_scene.render.resolution_y = resolution
            preview_scene.render.resolution_percentage = 100
            preview_scene.render.image_settings.file_format = "PNG"
            preview_scene.render.filepath = output_path

            if engine == "EEVEE":
                preview_scene.render.engine = compat.get_eevee_engine_name()
            else:
                preview_scene.render.engine = "CYCLES"
                preview_scene.cycles.samples = 64
                preview_scene.cycles.use_denoising = True

            # World background
            if preview_scene.world is None:
                preview_scene.world = bpy.data.worlds.new("__preview_world__")
            preview_scene.world.use_nodes = True
            bg_node = preview_scene.world.node_tree.nodes.get("Background")
            if bg_node:
                bg_node.inputs["Color"].default_value = (0.15, 0.15, 0.15, 1.0)
                bg_node.inputs["Strength"].default_value = 0.5

            # ── Create preview object ───────────────────────────────
            if preview_shape == "SPHERE":
                bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1.0, location=(0, 0, 0))
                bpy.ops.object.shade_smooth()
            elif preview_shape == "CUBE":
                bpy.ops.mesh.primitive_cube_add(size=1.6, location=(0, 0, 0))
            elif preview_shape == "PLANE":
                bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
            elif preview_shape == "CYLINDER":
                bpy.ops.mesh.primitive_cylinder_add(radius=0.8, depth=1.6, vertices=64, location=(0, 0, 0))
                bpy.ops.object.shade_smooth()

            preview_obj = bpy.context.active_object
            preview_obj.name = "__mat_preview_obj__"

            # Assign material
            preview_obj.data.materials.append(mat)

            # ── Create camera ───────────────────────────────────────
            cam_data = bpy.data.cameras.new("__preview_cam__")
            cam_obj = bpy.data.objects.new("__preview_cam__", cam_data)
            preview_scene.collection.objects.link(cam_obj)
            preview_scene.camera = cam_obj

            # Position camera at a nice angle
            cam_obj.location = (2.5, -2.5, 2.0)
            # Point at origin
            direction = cam_obj.location.copy()
            direction.negate()
            rot_quat = direction.to_track_quat('-Z', 'Y')
            cam_obj.rotation_euler = rot_quat.to_euler()

            # ── Create lighting ─────────────────────────────────────
            # Key light
            key_data = bpy.data.lights.new("__preview_key__", "AREA")
            key_data.energy = 100
            key_data.size = 3.0
            key_obj = bpy.data.objects.new("__preview_key__", key_data)
            key_obj.location = (3.0, -2.0, 4.0)
            preview_scene.collection.objects.link(key_obj)

            # Fill light
            fill_data = bpy.data.lights.new("__preview_fill__", "AREA")
            fill_data.energy = 30
            fill_data.size = 2.0
            fill_obj = bpy.data.objects.new("__preview_fill__", fill_data)
            fill_obj.location = (-3.0, -1.0, 2.0)
            preview_scene.collection.objects.link(fill_obj)

            # ── Render ──────────────────────────────────────────────
            bpy.ops.render.render(write_still=True, scene=preview_scene.name)

            return {
                "material": mat.name,
                "preview_shape": preview_shape,
                "engine": engine,
                "resolution": resolution,
                "output_path": output_path,
            }

        except Exception as exc:
            return {"error": f"Preview render failed: {exc}"}

        finally:
            # ── Cleanup temporary scene ─────────────────────────────
            bpy.context.window.scene = original_scene

            # Remove temp scene and its objects
            if "__mat_preview_tmp__" in bpy.data.scenes:
                tmp_scene = bpy.data.scenes["__mat_preview_tmp__"]
                # Remove objects created in the temp scene
                for obj in list(tmp_scene.collection.objects):
                    data = obj.data
                    bpy.data.objects.remove(obj, do_unlink=True)
                    # Clean up associated data blocks
                    if data is not None:
                        if isinstance(data, bpy.types.Mesh):
                            bpy.data.meshes.remove(data)
                        elif isinstance(data, bpy.types.Camera):
                            bpy.data.cameras.remove(data)
                        elif isinstance(data, bpy.types.Light):
                            bpy.data.lights.remove(data)
                bpy.data.scenes.remove(tmp_scene)

            # Clean up temp world
            if "__preview_world__" in bpy.data.worlds:
                bpy.data.worlds.remove(bpy.data.worlds["__preview_world__"])


    # ========== Measurement & Validation Handlers ==========

