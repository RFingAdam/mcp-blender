"""Geometry Nodes command handlers."""

import math

import bpy

from ..utils import get_object_or_error
from ..validation import (
    require_param,
    validate_enum,
)
from ._helpers import (
    _SOCKET_TYPE_MAP,
    _build_socket_info,
    _get_gn_modifier,
    _link,
    _new_node,
    _read_modifier_input,
    _set_modifier_input,
)


class GeoNodesHandlersMixin:
    """Mixin for Geometry Nodes handlers."""

    def _handle_geonode_create_group(self, params: dict) -> dict:
        """Create a new GeometryNodeTree with typed sockets."""


        name = require_param(params, "name", str)
        extra_inputs = params.get("inputs", [])
        extra_outputs = params.get("outputs", [])

        # Create the node group
        group = bpy.data.node_groups.new(name, 'GeometryNodeTree')

        # Blender 4.x: default Geometry in/out are created automatically
        # when we create a GeometryNodeTree.  Verify they exist, or add them.
        existing_input_names = set()
        existing_output_names = set()
        for item in group.interface.items_tree:
            if item.item_type != 'SOCKET':
                continue
            if item.in_out == 'INPUT':
                existing_input_names.add(item.name)
            else:
                existing_output_names.add(item.name)

        if "Geometry" not in existing_input_names:
            group.interface.new_socket(
                name="Geometry", in_out='INPUT',
                socket_type='NodeSocketGeometry',
            )
        if "Geometry" not in existing_output_names:
            group.interface.new_socket(
                name="Geometry", in_out='OUTPUT',
                socket_type='NodeSocketGeometry',
            )

        # Add Group Input and Group Output nodes if not present
        has_input_node = any(n.type == 'GROUP_INPUT' for n in group.nodes)
        has_output_node = any(n.type == 'GROUP_OUTPUT' for n in group.nodes)
        if not has_input_node:
            _new_node(group, 'NodeGroupInput', location=(-300, 0))
        if not has_output_node:
            _new_node(group, 'NodeGroupOutput', location=(300, 0))

        # Wire default Geometry through
        input_node = next(n for n in group.nodes if n.type == 'GROUP_INPUT')
        output_node = next(n for n in group.nodes if n.type == 'GROUP_OUTPUT')
        # Connect Geometry pass-through if no links yet
        if not group.links:
            geo_out = None
            geo_in = None
            for out in input_node.outputs:
                if out.bl_idname == 'NodeSocketGeometry' or out.name == 'Geometry':
                    geo_out = out
                    break
            for inp in output_node.inputs:
                if inp.bl_idname == 'NodeSocketGeometry' or inp.name == 'Geometry':
                    geo_in = inp
                    break
            if geo_out and geo_in:
                _link(group, geo_out, geo_in)

        # Add extra input sockets
        for spec in extra_inputs:
            sock_name = spec.get("name", "Value")
            sock_type = spec.get("type", "FLOAT").upper()
            bl_type = _SOCKET_TYPE_MAP.get(sock_type)
            if bl_type is None:
                continue
            sock = group.interface.new_socket(
                name=sock_name, in_out='INPUT', socket_type=bl_type,
            )
            # Set default value if provided
            default = spec.get("default")
            if default is not None and hasattr(sock, "default_value"):
                try:
                    if sock_type == "VECTOR" and isinstance(default, (list, tuple)):
                        sock.default_value = tuple(float(v) for v in default[:3])
                    elif sock_type == "BOOLEAN":
                        sock.default_value = bool(default)
                    elif sock_type == "INT":
                        sock.default_value = int(default)
                    elif sock_type == "FLOAT":
                        sock.default_value = float(default)
                    elif sock_type == "STRING":
                        sock.default_value = str(default)
                except (TypeError, ValueError):
                    pass  # skip bad defaults silently

        # Add extra output sockets
        for spec in extra_outputs:
            sock_name = spec.get("name", "Value")
            sock_type = spec.get("type", "FLOAT").upper()
            bl_type = _SOCKET_TYPE_MAP.get(sock_type)
            if bl_type is None:
                continue
            group.interface.new_socket(
                name=sock_name, in_out='OUTPUT', socket_type=bl_type,
            )

        inputs_info, outputs_info = _build_socket_info(group)
        return {
            "success": True,
            "node_group": group.name,
            "inputs": inputs_info,
            "outputs": outputs_info,
        }

    # ── 2. Apply ─────────────────────────────────────────────────────


    def _handle_geonode_apply(self, params: dict) -> dict:
        """Apply a GN group as a modifier and set input values."""

        from ..utils import get_object_or_error

        object_name = require_param(params, "object_name", str)
        group_name = require_param(params, "node_group", str)
        input_values = params.get("inputs", {})

        obj = get_object_or_error(object_name)
        group = bpy.data.node_groups.get(group_name)
        if group is None:
            return {"error": f"Node group not found: {group_name}"}
        if group.bl_idname != 'GeometryNodeTree':
            return {"error": f"'{group_name}' is not a GeometryNodeTree"}

        # Add modifier
        mod_name = group_name
        modifier = obj.modifiers.new(name=mod_name, type='NODES')
        modifier.node_group = group

        # Set input values
        if input_values and isinstance(input_values, dict):
            # Build a name→(identifier, bl_socket_idname) map from the interface
            socket_map: dict[str, tuple[str, str]] = {}
            for item in group.interface.items_tree:
                if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
                    socket_map[item.name] = (item.identifier, item.bl_socket_idname)

            for inp_name, inp_value in input_values.items():
                if inp_name not in socket_map:
                    continue
                identifier, bl_type = socket_map[inp_name]
                _set_modifier_input(modifier, identifier, inp_value, bl_type)

        # Read back current state
        result_inputs = {}
        for item in group.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
                result_inputs[item.name] = _read_modifier_input(modifier, item.identifier)

        return {
            "success": True,
            "object": object_name,
            "modifier": modifier.name,
            "node_group": group.name,
            "inputs": result_inputs,
        }

    # ── 3. Scatter Instances ─────────────────────────────────────────


    def _handle_geonode_scatter_instances(self, params: dict) -> dict:
        """Build a full scatter-instances GN setup in one call."""

        from ..utils import get_object_or_error

        target_name = require_param(params, "target_object", str)
        instance_name = require_param(params, "instance_object", str)
        density = float(params.get("density", 10.0))
        seed = int(params.get("seed", 0))
        min_distance = float(params.get("min_distance", 0.0))
        scale_min = float(params.get("scale_min", 1.0))
        scale_max = float(params.get("scale_max", 1.0))
        rotation_random = params.get("rotation_random", [0, 0, 0])
        align_to_normal = params.get("align_to_normal", True)

        target_obj = get_object_or_error(target_name)
        instance_obj = get_object_or_error(instance_name)

        # -- Build node tree --
        tree_name = f"Scatter_{instance_name}_on_{target_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Ensure Geometry in/out sockets exist
        has_geo_in = False
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET':
                if item.in_out == 'INPUT' and item.name == 'Geometry':
                    has_geo_in = True
                if item.in_out == 'OUTPUT' and item.name == 'Geometry':
                    has_geo_out = True
        if not has_geo_in:
            tree.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

        # Nodes
        n_input = _new_node(tree, 'NodeGroupInput', location=(-800, 0))
        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Distribute Points on Faces
        n_dist = _new_node(tree, 'GeometryNodeDistributePointsOnFaces',
                           label='Distribute', location=(-400, 0))
        if min_distance > 0:
            # Poisson Disk
            n_dist.distribute_method = 'POISSON'
            # Poisson uses "Distance Min" input (index 2) and "Density Max" (index 4)
            n_dist.inputs['Distance Min'].default_value = min_distance
            n_dist.inputs['Density Max'].default_value = density
        else:
            n_dist.distribute_method = 'RANDOM'
            n_dist.inputs['Density'].default_value = density
        n_dist.inputs['Seed'].default_value = seed

        # Instance on Points
        n_iop = _new_node(tree, 'GeometryNodeInstanceOnPoints',
                          label='Instance on Points', location=(0, 0))

        # Object Info (to get instance geometry)
        n_obj = _new_node(tree, 'GeometryNodeObjectInfo',
                          label='Instance Object', location=(-400, -300))
        n_obj.inputs['Object'].default_value = instance_obj
        n_obj.transform_space = 'RELATIVE'

        # -- Random scale --
        if scale_min != scale_max:
            n_rand_scale = _new_node(tree, 'FunctionNodeRandomValue',
                                     label='Random Scale', location=(-200, -200))
            # Set data type to FLOAT_VECTOR for uniform xyz
            n_rand_scale.data_type = 'FLOAT'
            n_rand_scale.inputs[2].default_value = scale_min  # Min
            n_rand_scale.inputs[3].default_value = scale_max  # Max

            # Combine XYZ to turn single float into vector scale
            n_combine = _new_node(tree, 'ShaderNodeCombineXYZ',
                                  label='Scale Vec', location=(-50, -200))
            _link(tree, n_rand_scale.outputs['Value'], n_combine.inputs['X'])
            _link(tree, n_rand_scale.outputs['Value'], n_combine.inputs['Y'])
            _link(tree, n_rand_scale.outputs['Value'], n_combine.inputs['Z'])
            _link(tree, n_combine.outputs['Vector'], n_iop.inputs['Scale'])
        else:
            # Uniform fixed scale — no node needed, just set default
            n_iop.inputs['Scale'].default_value = (scale_min, scale_min, scale_min)

        # -- Rotation --
        rot_degs = [float(r) for r in rotation_random[:3]] if rotation_random else [0, 0, 0]
        has_random_rot = any(abs(r) > 0.001 for r in rot_degs)

        if align_to_normal:
            # Connect Rotation from Distribute → Instance on Points
            _link(tree, n_dist.outputs['Rotation'], n_iop.inputs['Rotation'])

            if has_random_rot:
                # Add random rotation on top via Rotate Euler node
                n_rand_rot = _new_node(tree, 'FunctionNodeRandomValue',
                                       label='Random Rot', location=(-200, -400))
                n_rand_rot.data_type = 'FLOAT_VECTOR'
                rot_rads = [math.radians(r) for r in rot_degs]
                n_rand_rot.inputs[0].default_value = tuple(-r for r in rot_rads)  # Min
                n_rand_rot.inputs[1].default_value = tuple(rot_rads)  # Max

                n_rotate = _new_node(tree, 'FunctionNodeRotateEuler',
                                     label='Add Random Rot', location=(-50, -400))
                n_rotate.type = 'EULER'
                _link(tree, n_dist.outputs['Rotation'], n_rotate.inputs['Rotation'])
                _link(tree, n_rand_rot.outputs['Value'], n_rotate.inputs['Rotate By'])

                # Re-link rotation
                # Remove old link from dist rotation to IOP
                for lnk in list(tree.links):
                    if lnk.to_socket == n_iop.inputs['Rotation'] and lnk.from_node == n_dist:
                        tree.links.remove(lnk)
                _link(tree, n_rotate.outputs['Rotation'], n_iop.inputs['Rotation'])

        elif has_random_rot:
            n_rand_rot = _new_node(tree, 'FunctionNodeRandomValue',
                                   label='Random Rot', location=(-200, -400))
            n_rand_rot.data_type = 'FLOAT_VECTOR'
            rot_rads = [math.radians(r) for r in rot_degs]
            n_rand_rot.inputs[0].default_value = tuple(-r for r in rot_rads)
            n_rand_rot.inputs[1].default_value = tuple(rot_rads)

            # Euler to Rotation
            n_euler = _new_node(tree, 'FunctionNodeEulerToRotation',
                                label='To Rotation', location=(-50, -400))
            _link(tree, n_rand_rot.outputs['Value'], n_euler.inputs['Euler'])
            _link(tree, n_euler.outputs['Rotation'], n_iop.inputs['Rotation'])

        # -- Core wiring --
        _link(tree, n_input.outputs['Geometry'], n_dist.inputs['Mesh'])
        _link(tree, n_dist.outputs['Points'], n_iop.inputs['Points'])
        _link(tree, n_obj.outputs['Geometry'], n_iop.inputs['Instance'])
        _link(tree, n_iop.outputs['Instances'], n_output.inputs['Geometry'])

        # -- Apply modifier --
        modifier = target_obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "target": target_name,
            "instance": instance_name,
            "density": density,
            "distribute_method": "POISSON" if min_distance > 0 else "RANDOM",
        }

    # ── 4. Array / Grid ──────────────────────────────────────────────


    def _handle_geonode_array_grid(self, params: dict) -> dict:
        """Build a parametric array pattern via Geometry Nodes."""

        from ..utils import get_object_or_error

        object_name = require_param(params, "object_name", str)
        instance_name = require_param(params, "instance_object", str)
        grid_type = validate_enum(
            require_param(params, "grid_type", str),
            "grid_type",
            ["LINEAR", "GRID_2D", "RADIAL", "HEXAGONAL"],
        )

        count_x = int(params.get("count_x", 5))
        count_y = int(params.get("count_y", 5))
        spacing_x = float(params.get("spacing_x", 1.0))
        spacing_y = float(params.get("spacing_y", 1.0))
        radial_count = int(params.get("radial_count", 8))
        radial_radius = float(params.get("radial_radius", 1.0))

        obj = get_object_or_error(object_name)
        instance_obj = get_object_or_error(instance_name)

        tree_name = f"Array_{grid_type}_{instance_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Ensure Geometry output socket
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == 'Geometry':
                has_geo_out = True
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        # Remove default Geometry input if present (we generate our own points)
        for item in list(tree.interface.items_tree):
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == 'Geometry':
                tree.interface.remove(item)

        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Object Info for instance
        n_obj = _new_node(tree, 'GeometryNodeObjectInfo',
                          label='Instance', location=(-200, -300))
        n_obj.inputs['Object'].default_value = instance_obj
        n_obj.transform_space = 'RELATIVE'

        # Instance on Points
        n_iop = _new_node(tree, 'GeometryNodeInstanceOnPoints',
                          label='Instance on Points', location=(300, 0))

        if grid_type == "LINEAR":
            # Mesh Line node
            n_line = _new_node(tree, 'GeometryNodeMeshLine',
                               label='Line', location=(-200, 0))
            n_line.mode = 'OFFSET'
            n_line.inputs['Count'].default_value = count_x
            n_line.inputs['Offset'].default_value = (spacing_x, 0.0, 0.0)
            _link(tree, n_line.outputs['Mesh'], n_iop.inputs['Points'])

        elif grid_type == "GRID_2D":
            # Grid node (Mesh Grid)
            n_grid = _new_node(tree, 'GeometryNodeMeshGrid',
                               label='Grid', location=(-200, 0))
            n_grid.inputs['Vertices X'].default_value = count_x
            n_grid.inputs['Vertices Y'].default_value = count_y
            n_grid.inputs['Size X'].default_value = spacing_x * (count_x - 1)
            n_grid.inputs['Size Y'].default_value = spacing_y * (count_y - 1)
            _link(tree, n_grid.outputs['Mesh'], n_iop.inputs['Points'])

        elif grid_type == "RADIAL":
            # Mesh Circle (vertices only, no fill)
            n_circle = _new_node(tree, 'GeometryNodeMeshCircle',
                                 label='Circle', location=(-200, 0))
            n_circle.fill_type = 'NONE'
            n_circle.inputs['Vertices'].default_value = radial_count
            n_circle.inputs['Radius'].default_value = radial_radius
            _link(tree, n_circle.outputs['Mesh'], n_iop.inputs['Points'])

        elif grid_type == "HEXAGONAL":
            # Build hex grid via a regular grid + Set Position offset on odd rows
            n_grid = _new_node(tree, 'GeometryNodeMeshGrid',
                               label='Hex Grid', location=(-600, 0))
            n_grid.inputs['Vertices X'].default_value = count_x
            n_grid.inputs['Vertices Y'].default_value = count_y
            n_grid.inputs['Size X'].default_value = spacing_x * (count_x - 1)
            n_grid.inputs['Size Y'].default_value = spacing_y * (count_y - 1)

            # Index node
            n_index = _new_node(tree, 'GeometryNodeInputIndex',
                                label='Index', location=(-600, -200))

            # Math: row = index / count_x (integer division via floor)
            n_div = _new_node(tree, 'ShaderNodeMath',
                              label='Div', location=(-400, -200))
            n_div.operation = 'DIVIDE'
            _link(tree, n_index.outputs['Index'], n_div.inputs[0])
            n_div.inputs[1].default_value = float(count_x)

            n_floor = _new_node(tree, 'ShaderNodeMath',
                                label='Floor', location=(-250, -200))
            n_floor.operation = 'FLOOR'
            _link(tree, n_div.outputs['Value'], n_floor.inputs[0])

            # Modulo 2 to detect odd rows
            n_mod = _new_node(tree, 'ShaderNodeMath',
                              label='Mod2', location=(-100, -200))
            n_mod.operation = 'MODULO'
            _link(tree, n_floor.outputs['Value'], n_mod.inputs[0])
            n_mod.inputs[1].default_value = 2.0

            # Multiply by half spacing for offset
            n_mul = _new_node(tree, 'ShaderNodeMath',
                              label='HalfOffset', location=(50, -200))
            n_mul.operation = 'MULTIPLY'
            _link(tree, n_mod.outputs['Value'], n_mul.inputs[0])
            n_mul.inputs[1].default_value = spacing_x * 0.5

            # Combine XYZ (only X gets offset)
            n_combine = _new_node(tree, 'ShaderNodeCombineXYZ',
                                  label='Offset Vec', location=(200, -200))
            _link(tree, n_mul.outputs['Value'], n_combine.inputs['X'])

            # Set Position (offset)
            n_setpos = _new_node(tree, 'GeometryNodeSetPosition',
                                 label='Hex Offset', location=(-200, 0))
            _link(tree, n_grid.outputs['Mesh'], n_setpos.inputs['Geometry'])
            _link(tree, n_combine.outputs['Vector'], n_setpos.inputs['Offset'])

            _link(tree, n_setpos.outputs['Geometry'], n_iop.inputs['Points'])

        # Wire instance and output
        _link(tree, n_obj.outputs['Geometry'], n_iop.inputs['Instance'])
        _link(tree, n_iop.outputs['Instances'], n_output.inputs['Geometry'])

        # Apply modifier
        modifier = obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "object": object_name,
            "grid_type": grid_type,
        }

    # ── 5. Deform Along Curve ────────────────────────────────────────


    def _handle_geonode_deform_curve(self, params: dict) -> dict:
        """Deform a mesh along a curve using Geometry Nodes."""

        from ..utils import get_object_or_error

        object_name = require_param(params, "object_name", str)
        curve_name = require_param(params, "curve_name", str)
        stretch = params.get("stretch", True)

        mesh_obj = get_object_or_error(object_name)
        curve_obj = get_object_or_error(curve_name)
        if curve_obj.type != 'CURVE':
            return {"error": f"'{curve_name}' is not a curve object (type: {curve_obj.type})"}

        tree_name = f"DeformCurve_{object_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Sockets
        has_geo_in = False
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET':
                if item.in_out == 'INPUT' and item.name == 'Geometry':
                    has_geo_in = True
                if item.in_out == 'OUTPUT' and item.name == 'Geometry':
                    has_geo_out = True
        if not has_geo_in:
            tree.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

        n_input = _new_node(tree, 'NodeGroupInput', location=(-600, 0))
        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Object Info to get curve geometry
        n_curve_info = _new_node(tree, 'GeometryNodeObjectInfo',
                                 label='Curve Object', location=(-400, -200))
        n_curve_info.inputs['Object'].default_value = curve_obj
        n_curve_info.transform_space = 'RELATIVE'

        # Deform Curves on Surface is for curves-on-mesh; for mesh-along-curve
        # we use the Curve Deform approach via Set Position + Sample Curve.
        #
        # Strategy: Use "Deform on Curve" approach:
        # 1. Get mesh bounding box to find extent along deform axis (X)
        # 2. Normalize vertex X to 0..1 (factor along curve)
        # 3. Sample Curve at that factor to get position + tangent
        # 4. Set position from sampled curve point

        # Bounding Box
        n_bbox = _new_node(tree, 'GeometryNodeBoundBox',
                           label='BBox', location=(-400, 200))
        _link(tree, n_input.outputs['Geometry'], n_bbox.inputs['Geometry'])

        # Separate XYZ of Min and Max
        n_sep_min = _new_node(tree, 'ShaderNodeSeparateXYZ',
                              label='Sep Min', location=(-200, 300))
        _link(tree, n_bbox.outputs['Min'], n_sep_min.inputs['Vector'])

        n_sep_max = _new_node(tree, 'ShaderNodeSeparateXYZ',
                              label='Sep Max', location=(-200, 200))
        _link(tree, n_bbox.outputs['Max'], n_sep_max.inputs['Vector'])

        # Extent = max_x - min_x
        n_extent = _new_node(tree, 'ShaderNodeMath',
                             label='Extent', location=(0, 250))
        n_extent.operation = 'SUBTRACT'
        _link(tree, n_sep_max.outputs['X'], n_extent.inputs[0])
        _link(tree, n_sep_min.outputs['X'], n_extent.inputs[1])

        # Position node (vertex position)
        n_pos = _new_node(tree, 'GeometryNodeInputPosition',
                          label='Position', location=(-400, 0))

        # Separate XYZ of position
        n_sep_pos = _new_node(tree, 'ShaderNodeSeparateXYZ',
                              label='Sep Pos', location=(-200, 0))
        _link(tree, n_pos.outputs['Position'], n_sep_pos.inputs['Vector'])

        # Factor = (pos_x - min_x) / extent
        n_sub = _new_node(tree, 'ShaderNodeMath',
                          label='Sub Min', location=(0, 50))
        n_sub.operation = 'SUBTRACT'
        _link(tree, n_sep_pos.outputs['X'], n_sub.inputs[0])
        _link(tree, n_sep_min.outputs['X'], n_sub.inputs[1])

        n_factor = _new_node(tree, 'ShaderNodeMath',
                             label='Factor', location=(0, -50))
        n_factor.operation = 'DIVIDE'
        n_factor.use_clamp = not stretch
        _link(tree, n_sub.outputs['Value'], n_factor.inputs[0])
        _link(tree, n_extent.outputs['Value'], n_factor.inputs[1])

        # Sample Curve
        n_sample = _new_node(tree, 'GeometryNodeSampleCurve',
                             label='Sample Curve', location=(200, -100))
        n_sample.mode = 'FACTOR'
        n_sample.data_type = 'FLOAT'
        _link(tree, n_curve_info.outputs['Geometry'], n_sample.inputs['Curves'])
        _link(tree, n_factor.outputs['Value'], n_sample.inputs['Factor'])

        # Use Y/Z from original position for profile offset:
        # final_pos = sampled_position + tangent_y_offset + tangent_z_offset
        # Simplified: offset the sampled position by the local Y and Z of the vertex

        # Get the Normal and Tangent from Sample Curve to build local frame
        # For simplicity, use Set Position with sampled position directly,
        # adding Y/Z offsets perpendicular to curve tangent.
        # Blender's Sample Curve gives Position, Tangent, Normal.

        # Cross product of tangent and (0,0,1) → right vector; or use Normal output
        # The Sample Curve node outputs: Position, Tangent, Normal

        # Combine local Y/Z offset with curve frame:
        # offset = normal * local_y + cross(tangent, normal) * local_z
        n_scale_y = _new_node(tree, 'ShaderNodeVectorMath',
                              label='Scale Normal', location=(200, -300))
        n_scale_y.operation = 'SCALE'
        _link(tree, n_sample.outputs['Normal'], n_scale_y.inputs[0])
        _link(tree, n_sep_pos.outputs['Y'], n_scale_y.inputs['Scale'])

        # Bitangent: cross(tangent, normal)
        n_cross = _new_node(tree, 'ShaderNodeVectorMath',
                            label='Bitangent', location=(200, -500))
        n_cross.operation = 'CROSS_PRODUCT'
        _link(tree, n_sample.outputs['Tangent'], n_cross.inputs[0])
        _link(tree, n_sample.outputs['Normal'], n_cross.inputs[1])

        n_scale_z = _new_node(tree, 'ShaderNodeVectorMath',
                              label='Scale Bitangent', location=(350, -500))
        n_scale_z.operation = 'SCALE'
        _link(tree, n_cross.outputs['Vector'], n_scale_z.inputs[0])
        _link(tree, n_sep_pos.outputs['Z'], n_scale_z.inputs['Scale'])

        # Add sampled pos + y_offset + z_offset
        n_add1 = _new_node(tree, 'ShaderNodeVectorMath',
                           label='Add Y', location=(400, -100))
        n_add1.operation = 'ADD'
        _link(tree, n_sample.outputs['Position'], n_add1.inputs[0])
        _link(tree, n_scale_y.outputs['Vector'], n_add1.inputs[1])

        n_add2 = _new_node(tree, 'ShaderNodeVectorMath',
                           label='Add Z', location=(400, -250))
        n_add2.operation = 'ADD'
        _link(tree, n_add1.outputs['Vector'], n_add2.inputs[0])
        _link(tree, n_scale_z.outputs['Vector'], n_add2.inputs[1])

        # Set Position
        n_setpos = _new_node(tree, 'GeometryNodeSetPosition',
                             label='Set Position', location=(500, 0))
        _link(tree, n_input.outputs['Geometry'], n_setpos.inputs['Geometry'])
        _link(tree, n_add2.outputs['Vector'], n_setpos.inputs['Position'])

        _link(tree, n_setpos.outputs['Geometry'], n_output.inputs['Geometry'])

        # Apply modifier
        modifier = mesh_obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "object": object_name,
            "curve": curve_name,
            "stretch": stretch,
        }

    # ── 6. Extrude Profile Along Curve ───────────────────────────────


    def _handle_geonode_extrude_profile(self, params: dict) -> dict:
        """Extrude a profile along a curve via Curve to Mesh."""

        from ..utils import get_object_or_error

        profile_name = require_param(params, "profile_object", str)
        curve_name = require_param(params, "curve_name", str)
        result_name = params.get("name", "ExtrudedProfile")
        fill_caps = params.get("fill_caps", True)
        resolution = int(params.get("resolution", 12))

        profile_obj = get_object_or_error(profile_name)
        curve_obj = get_object_or_error(curve_name)

        if curve_obj.type != 'CURVE':
            return {"error": f"'{curve_name}' is not a curve object (type: {curve_obj.type})"}

        # Set curve resolution
        for spline in curve_obj.data.splines:
            spline.resolution_u = resolution
        curve_obj.data.resolution_u = resolution

        # Build GN tree
        tree_name = f"Extrude_{result_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Only need Geometry output
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == 'Geometry':
                has_geo_out = True
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        # Remove default input Geometry — we source from Object Info nodes
        for item in list(tree.interface.items_tree):
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == 'Geometry':
                tree.interface.remove(item)

        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Curve Object Info
        n_curve = _new_node(tree, 'GeometryNodeObjectInfo',
                            label='Curve', location=(-400, 100))
        n_curve.inputs['Object'].default_value = curve_obj
        n_curve.transform_space = 'RELATIVE'

        # Profile Object Info
        n_profile = _new_node(tree, 'GeometryNodeObjectInfo',
                              label='Profile', location=(-400, -100))
        n_profile.inputs['Object'].default_value = profile_obj
        n_profile.transform_space = 'RELATIVE'

        # If profile is a mesh, convert to curve first
        if profile_obj.type == 'MESH':
            n_mesh_to_curve = _new_node(tree, 'GeometryNodeMeshToCurve',
                                        label='Mesh to Curve', location=(-200, -100))
            _link(tree, n_profile.outputs['Geometry'], n_mesh_to_curve.inputs['Mesh'])
            profile_geo_output = n_mesh_to_curve.outputs['Curve']
        else:
            profile_geo_output = n_profile.outputs['Geometry']

        # Curve to Mesh
        n_c2m = _new_node(tree, 'GeometryNodeCurveToMesh',
                          label='Curve to Mesh', location=(200, 0))
        n_c2m.inputs['Fill Caps'].default_value = fill_caps
        _link(tree, n_curve.outputs['Geometry'], n_c2m.inputs['Curve'])
        _link(tree, profile_geo_output, n_c2m.inputs['Profile Curve'])

        _link(tree, n_c2m.outputs['Mesh'], n_output.inputs['Geometry'])

        # Create a new empty/mesh object to host the modifier
        mesh_data = bpy.data.meshes.new(result_name)
        result_obj = bpy.data.objects.new(result_name, mesh_data)
        bpy.context.collection.objects.link(result_obj)

        modifier = result_obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "object": result_obj.name,
            "curve": curve_name,
            "profile": profile_name,
            "fill_caps": fill_caps,
            "resolution": resolution,
        }

    # ── 7. Inspect ───────────────────────────────────────────────────


    def _handle_geonode_inspect(self, params: dict) -> dict:
        """Read the GN setup on an object: group name, inputs, outputs, values."""


        object_name = require_param(params, "object_name", str)
        modifier_name = params.get("modifier_name")

        obj = get_object_or_error(object_name)
        modifier = _get_gn_modifier(obj, modifier_name)
        if modifier is None:
            if modifier_name:
                return {"error": f"No Geometry Nodes modifier '{modifier_name}' on '{object_name}'"}
            return {"error": f"No Geometry Nodes modifier found on '{object_name}'"}

        group = modifier.node_group
        if group is None:
            return {"error": f"Modifier '{modifier.name}' has no node group assigned"}

        inputs_info, outputs_info = _build_socket_info(group)

        # Read current modifier input values
        input_values = {}
        for inp in inputs_info:
            val = _read_modifier_input(modifier, inp["identifier"])
            input_values[inp["name"]] = {
                "type": inp["type"],
                "identifier": inp["identifier"],
                "value": val,
            }

        # Count nodes
        node_count = len(group.nodes)
        link_count = len(group.links)

        # Node type summary
        node_types = {}
        for node in group.nodes:
            t = node.bl_idname
            node_types[t] = node_types.get(t, 0) + 1

        return {
            "success": True,
            "object": object_name,
            "modifier": modifier.name,
            "node_group": group.name,
            "inputs": input_values,
            "outputs": [{"name": o["name"], "type": o["type"]} for o in outputs_info],
            "node_count": node_count,
            "link_count": link_count,
            "node_types": node_types,
        }



# ---------------------------------------------------------------------------
# Geometry Nodes helpers
# ---------------------------------------------------------------------------

