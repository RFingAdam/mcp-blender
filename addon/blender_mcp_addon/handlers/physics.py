"""Physics simulation command handlers."""

import math

import bpy

from ..utils import (
    ensure_object_selected,
    get_object_or_error,
)
from ..validation import (
    require_param,
    validate_enum,
)
from ._helpers import _CLOTH_PRESETS


class PhysicsHandlersMixin:
    """Mixin for physics simulation handlers."""

    def _handle_physics_rigid_body_add(self, params: dict) -> dict:
        """Add a rigid body physics simulation to an object."""
        object_name = require_param(params, "object_name", str)
        body_type = params.get("body_type", "ACTIVE")
        mass = float(params.get("mass", 1.0))
        friction = float(params.get("friction", 0.5))
        bounciness = float(params.get("bounciness", 0.0))
        collision_shape = params.get("collision_shape", "CONVEX_HULL")

        # Validate enums
        body_type = validate_enum(
            body_type, "body_type", ["ACTIVE", "PASSIVE"]
        )
        collision_shape = validate_enum(
            collision_shape,
            "collision_shape",
            ["BOX", "SPHERE", "CAPSULE", "CYLINDER", "CONE", "CONVEX_HULL", "MESH"],
        )

        obj = get_object_or_error(object_name)

        # Ensure rigid body world exists
        scene = bpy.context.scene
        if scene.rigidbody_world is None:
            bpy.ops.rigidbody.world_add()

        # Select and activate the object
        ensure_object_selected(obj)

        # Add rigid body
        bpy.ops.rigidbody.object_add(type=body_type)

        # Configure rigid body properties
        rb = obj.rigid_body
        rb.mass = mass
        rb.friction = friction
        rb.restitution = bounciness
        rb.collision_shape = collision_shape

        return {
            "success": True,
            "object": obj.name,
            "body_type": body_type,
            "mass": mass,
            "friction": friction,
            "bounciness": bounciness,
            "collision_shape": collision_shape,
        }


    def _handle_physics_rigid_body_batch(self, params: dict) -> dict:
        """Add rigid bodies to multiple objects at once."""
        object_names = require_param(params, "object_names", list)
        body_type = params.get("body_type", "ACTIVE")
        mass = float(params.get("mass", 1.0))
        ground_object = params.get("ground_object")

        body_type = validate_enum(
            body_type, "body_type", ["ACTIVE", "PASSIVE"]
        )

        # Ensure rigid body world exists
        scene = bpy.context.scene
        if scene.rigidbody_world is None:
            bpy.ops.rigidbody.world_add()

        results = []
        errors = []

        # Process each object
        for name in object_names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                errors.append(f"Object not found: {name}")
                continue

            ensure_object_selected(obj)

            try:
                bpy.ops.rigidbody.object_add(type=body_type)
                obj.rigid_body.mass = mass
                results.append({
                    "object": obj.name,
                    "body_type": body_type,
                    "mass": mass,
                })
            except Exception as e:
                errors.append(f"Failed to add rigid body to '{name}': {str(e)}")

        # Handle ground object separately
        ground_result = None
        if ground_object:
            g_obj = bpy.data.objects.get(ground_object)
            if g_obj is None:
                errors.append(f"Ground object not found: {ground_object}")
            else:
                ensure_object_selected(g_obj)
                try:
                    # Remove existing rigid body if any, then add as PASSIVE
                    if g_obj.rigid_body is not None:
                        bpy.ops.rigidbody.object_remove()
                    bpy.ops.rigidbody.object_add(type="PASSIVE")
                    g_obj.rigid_body.friction = 0.5
                    g_obj.rigid_body.collision_shape = "MESH"
                    ground_result = {
                        "object": g_obj.name,
                        "body_type": "PASSIVE",
                        "collision_shape": "MESH",
                    }
                except Exception as e:
                    errors.append(
                        f"Failed to set ground object '{ground_object}': {str(e)}"
                    )

        response = {
            "success": True,
            "objects_processed": len(results),
            "results": results,
        }
        if ground_result:
            response["ground_object"] = ground_result
        if errors:
            response["errors"] = errors
            # Still mark success if at least some objects were processed
            response["success"] = len(results) > 0 or ground_result is not None

        return response


    def _handle_physics_simulate(self, params: dict) -> dict:
        """Run physics simulation and optionally apply results."""
        frame_start = int(params.get("frame_start", 1))
        frame_end = int(params.get("frame_end", 250))
        apply_results = params.get("apply_results", False)

        scene = bpy.context.scene

        # Ensure rigid body world exists
        if scene.rigidbody_world is None:
            return {"error": "No rigid body world found. Add rigid bodies first."}

        # Set frame range
        scene.frame_start = frame_start
        scene.frame_end = frame_end
        scene.rigidbody_world.point_cache.frame_start = frame_start
        scene.rigidbody_world.point_cache.frame_end = frame_end

        # Bake the simulation
        try:
            # Free existing bake first
            bpy.ops.ptcache.free_bake_all()
            bpy.ops.ptcache.bake_all(bake=True)
        except Exception as e:
            return {"error": f"Failed to bake simulation: {str(e)}"}

        # Move to the last frame to capture final positions
        scene.frame_set(frame_end)

        # Collect final positions of rigid body objects
        final_positions = {}
        rb_group = scene.rigidbody_world.group
        if rb_group:
            for obj in rb_group.objects:
                final_positions[obj.name] = {
                    "location": [round(v, 6) for v in obj.location],
                    "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
                }

        # Apply results if requested
        applied_objects = []
        if apply_results:
            if rb_group:
                # Iterate over a copy of the list since we modify it
                for obj in list(rb_group.objects):
                    ensure_object_selected(obj)
                    try:
                        # Apply visual transform to mesh
                        bpy.ops.object.visual_transform_apply()
                        # Remove rigid body
                        bpy.ops.rigidbody.object_remove()
                        applied_objects.append(obj.name)
                    except Exception:
                        # Skip objects that fail
                        pass

        response = {
            "success": True,
            "frame_range": [frame_start, frame_end],
            "final_positions": final_positions,
            "rigid_body_count": len(final_positions),
        }
        if apply_results:
            response["applied_objects"] = applied_objects
            response["results_applied"] = True

        return response


    # Cloth simulation presets: {quality_steps, mass, air_damping, tension_stiffness,
    #   compression_stiffness, bending_stiffness, tension_damping, compression_damping,
    #   bending_damping}


    def _handle_physics_cloth_add(self, params: dict) -> dict:
        """Add cloth simulation to a mesh object."""
        object_name = require_param(params, "object_name", str)
        preset_name = params.get("preset", "COTTON")
        pin_vertex_group = params.get("pin_vertex_group")
        collision_objects = params.get("collision_objects", [])
        wind_strength = float(params.get("wind_strength", 0.0))
        wind_direction = params.get("wind_direction", [1, 0, 0])

        preset_name = validate_enum(
            preset_name,
            "preset",
            ["SILK", "COTTON", "DENIM", "LEATHER", "RUBBER", "CANVAS", "TARP"],
        )

        obj = get_object_or_error(object_name)

        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is type {obj.type}, not MESH. Cloth requires a mesh object."}

        # Select and activate the object
        ensure_object_selected(obj)

        # Add cloth modifier
        bpy.ops.object.modifier_add(type='CLOTH')
        cloth_mod = obj.modifiers.get("Cloth")
        if cloth_mod is None:
            return {"error": "Failed to add cloth modifier"}

        cloth_settings = cloth_mod.settings

        # Apply preset
        preset = _CLOTH_PRESETS[preset_name]
        cloth_settings.quality = preset["quality"]
        cloth_settings.mass = preset["mass"]
        cloth_settings.air_damping = preset["air_damping"]
        cloth_settings.tension_stiffness = preset["tension_stiffness"]
        cloth_settings.compression_stiffness = preset["compression_stiffness"]
        cloth_settings.bending_stiffness = preset["bending_stiffness"]
        cloth_settings.tension_damping = preset["tension_damping"]
        cloth_settings.compression_damping = preset["compression_damping"]
        cloth_settings.bending_damping = preset["bending_damping"]

        # Set up pin group if specified
        if pin_vertex_group:
            vg = obj.vertex_groups.get(pin_vertex_group)
            if vg is None:
                return {
                    "error": f"Vertex group '{pin_vertex_group}' not found on '{object_name}'. "
                    f"Available: {[vg.name for vg in obj.vertex_groups]}"
                }
            cloth_settings.vertex_group_mass = pin_vertex_group

        # Add collision modifiers to collision objects
        collision_results = []
        collision_errors = []
        for col_name in collision_objects:
            col_obj = bpy.data.objects.get(col_name)
            if col_obj is None:
                collision_errors.append(f"Collision object not found: {col_name}")
                continue

            # Check if it already has a collision modifier
            has_collision = any(m.type == 'COLLISION' for m in col_obj.modifiers)
            if not has_collision:
                ensure_object_selected(col_obj)
                try:
                    bpy.ops.object.modifier_add(type='COLLISION')
                    collision_results.append(col_name)
                except Exception as e:
                    collision_errors.append(
                        f"Failed to add collision to '{col_name}': {str(e)}"
                    )
            else:
                collision_results.append(f"{col_name} (already had collision)")

        # Set up wind force field if wind_strength > 0
        wind_obj_name = None
        if wind_strength > 0:
            # Validate wind direction
            if not isinstance(wind_direction, (list, tuple)) or len(wind_direction) != 3:
                wind_direction = [1, 0, 0]

            # Calculate rotation from direction vector
            dx, dy, dz = [float(v) for v in wind_direction]
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if length > 0:
                dx, dy, dz = dx / length, dy / length, dz / length

            # Create a wind force field
            bpy.ops.object.effector_add(type='WIND', location=(0, 0, 0))
            wind_obj = bpy.context.active_object
            wind_obj.name = f"Wind_{object_name}"
            wind_obj.field.strength = wind_strength

            # Set rotation to match direction
            # Wind default direction is -Z, so we compute rotation to align
            # Using atan2 for azimuth and elevation
            wind_obj.rotation_euler[0] = math.asin(dy) if abs(dy) <= 1 else 0
            wind_obj.rotation_euler[1] = 0
            wind_obj.rotation_euler[2] = math.atan2(dx, -dz)

            wind_obj_name = wind_obj.name

        response = {
            "success": True,
            "object": obj.name,
            "preset": preset_name,
            "preset_settings": preset,
        }
        if pin_vertex_group:
            response["pin_group"] = pin_vertex_group
        if collision_results:
            response["collision_objects"] = collision_results
        if collision_errors:
            response["collision_errors"] = collision_errors
        if wind_obj_name:
            response["wind_object"] = wind_obj_name
            response["wind_strength"] = wind_strength
            response["wind_direction"] = [float(v) for v in wind_direction]

        return response


    def _handle_physics_soft_body_add(self, params: dict) -> dict:
        """Add soft body simulation to a mesh object."""
        object_name = require_param(params, "object_name", str)
        goal_strength = float(params.get("goal_strength", 0.7))
        mass = float(params.get("mass", 1.0))
        friction = float(params.get("friction", 0.5))

        obj = get_object_or_error(object_name)

        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is type {obj.type}, not MESH. Soft body requires a mesh object."}

        # Select and activate the object
        ensure_object_selected(obj)

        # Add soft body modifier
        bpy.ops.object.modifier_add(type='SOFT_BODY')
        sb_mod = obj.modifiers.get("Softbody")
        if sb_mod is None:
            # Blender may name it differently
            for mod in obj.modifiers:
                if mod.type == 'SOFT_BODY':
                    sb_mod = mod
                    break
        if sb_mod is None:
            return {"error": "Failed to add soft body modifier"}

        # Configure soft body settings
        sb = obj.modifiers[sb_mod.name].settings

        # Goal settings (how strongly vertices stick to original position)
        sb.goal_spring = goal_strength
        sb.goal_friction = 0.5

        # Mass
        sb.mass = mass

        # Friction (edge spring friction in Blender soft body)
        sb.friction = friction

        # Enable self-collision for better results
        sb.use_self_collision = True

        return {
            "success": True,
            "object": obj.name,
            "goal_strength": goal_strength,
            "mass": mass,
            "friction": friction,
            "modifier": sb_mod.name,
        }


    def _handle_physics_fluid_quick(self, params: dict) -> dict:
        """Quick fluid simulation setup with domain and flow objects."""
        domain_name = require_param(params, "domain_object", str)
        flow_name = require_param(params, "flow_object", str)
        fluid_type = params.get("fluid_type", "LIQUID")
        resolution = int(params.get("resolution", 64))
        viscosity = float(params.get("viscosity", 0.0))

        fluid_type = validate_enum(
            fluid_type, "fluid_type", ["LIQUID", "GAS"]
        )

        domain_obj = get_object_or_error(domain_name)
        flow_obj = get_object_or_error(flow_name)

        if domain_obj.type != "MESH":
            return {"error": f"Domain object '{domain_name}' is type {domain_obj.type}, not MESH."}
        if flow_obj.type != "MESH":
            return {"error": f"Flow object '{flow_name}' is type {flow_obj.type}, not MESH."}

        # --- Set up domain object ---
        ensure_object_selected(domain_obj)

        # Add fluid modifier as domain
        bpy.ops.object.modifier_add(type='FLUID')
        fluid_mod = None
        for mod in domain_obj.modifiers:
            if mod.type == 'FLUID':
                fluid_mod = mod
                break
        if fluid_mod is None:
            return {"error": "Failed to add fluid modifier to domain object"}

        # Set as domain
        fluid_mod.fluid_type = 'DOMAIN'
        domain_settings = fluid_mod.domain_settings

        # Configure domain type
        domain_settings.domain_type = fluid_type

        # Set resolution
        domain_settings.resolution_max = resolution

        # Set viscosity for liquid
        if fluid_type == "LIQUID" and viscosity > 0:
            domain_settings.use_viscosity = True
            domain_settings.viscosity_value = viscosity

        # Set cache type to modular for better control
        domain_settings.cache_type = 'MODULAR'

        # --- Set up flow object ---
        ensure_object_selected(flow_obj)

        bpy.ops.object.modifier_add(type='FLUID')
        flow_mod = None
        for mod in flow_obj.modifiers:
            if mod.type == 'FLUID':
                flow_mod = mod
                break
        if flow_mod is None:
            return {"error": "Failed to add fluid modifier to flow object"}

        # Set as flow (inflow)
        flow_mod.fluid_type = 'FLOW'
        flow_settings = flow_mod.flow_settings
        flow_settings.flow_type = fluid_type
        flow_settings.flow_behavior = 'INFLOW'

        return {
            "success": True,
            "domain": {
                "object": domain_obj.name,
                "type": "DOMAIN",
                "domain_type": fluid_type,
                "resolution": resolution,
                "viscosity": viscosity,
            },
            "flow": {
                "object": flow_obj.name,
                "type": "FLOW",
                "flow_type": fluid_type,
                "behavior": "INFLOW",
            },
            "note": "Use bpy.ops.fluid.bake_all() or the Physics tab to bake the simulation before rendering.",
        }


    # ========== Annotation & Grease Pencil Handlers ==========

