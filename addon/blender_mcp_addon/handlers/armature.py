"""Armature and rigging command handlers."""

import json
import math

import bpy

from ..utils import (
    ensure_object_selected,
    get_object_or_error,
)
from ..validation import (
    ValidationError,
    require_param,
    validate_enum,
)


class ArmatureHandlersMixin:
    """Mixin for armature and rigging handlers."""

    def _handle_armature_create(self, params: dict) -> dict:
        """Create an armature from a list of bone definitions."""
        name = params.get("name", "Armature")
        bones_data = require_param(params, "bones")
        display_type = params.get("display_type", "OCTAHEDRAL")
        display_type = validate_enum(
            display_type, "display_type",
            ["OCTAHEDRAL", "STICK", "BBONE", "WIRE", "ENVELOPE"],
        )

        if not isinstance(bones_data, list) or len(bones_data) == 0:
            raise ValidationError("'bones' must be a non-empty array of bone definitions")

        # Validate bone data
        for i, bone_def in enumerate(bones_data):
            if not isinstance(bone_def, dict):
                raise ValidationError(f"Bone at index {i} must be an object")
            if "name" not in bone_def:
                raise ValidationError(f"Bone at index {i} missing 'name'")
            if "head" not in bone_def or "tail" not in bone_def:
                raise ValidationError(f"Bone '{bone_def.get('name', i)}' missing 'head' or 'tail'")
            head = bone_def["head"]
            tail = bone_def["tail"]
            if not isinstance(head, (list, tuple)) or len(head) != 3:
                raise ValidationError(f"Bone '{bone_def['name']}' head must be [x, y, z]")
            if not isinstance(tail, (list, tuple)) or len(tail) != 3:
                raise ValidationError(f"Bone '{bone_def['name']}' tail must be [x, y, z]")

        # Create armature data and object
        arm_data = bpy.data.armatures.new(name)
        arm_data.display_type = display_type
        arm_obj = bpy.data.objects.new(name, arm_data)
        bpy.context.collection.objects.link(arm_obj)

        # Select and make active
        ensure_object_selected(arm_obj)

        # Enter edit mode to add bones
        bpy.ops.object.mode_set(mode="EDIT")

        # Remove the default bone if one was created
        for bone in arm_data.edit_bones:
            arm_data.edit_bones.remove(bone)

        # Create bones in order
        bone_names_created = []
        for bone_def in bones_data:
            bone_name = bone_def["name"]
            head = bone_def["head"]
            tail = bone_def["tail"]
            roll = math.radians(bone_def.get("roll", 0))

            edit_bone = arm_data.edit_bones.new(bone_name)
            edit_bone.head = (float(head[0]), float(head[1]), float(head[2]))
            edit_bone.tail = (float(tail[0]), float(tail[1]), float(tail[2]))
            edit_bone.roll = roll

            bone_names_created.append(bone_name)

        # Second pass: set parents (all bones must exist first)
        for bone_def in bones_data:
            parent_name = bone_def.get("parent")
            connected = bone_def.get("connected", False)
            if parent_name:
                bone = arm_data.edit_bones.get(bone_def["name"])
                parent_bone = arm_data.edit_bones.get(parent_name)
                if parent_bone is None:
                    bpy.ops.object.mode_set(mode="OBJECT")
                    raise ValidationError(
                        f"Parent bone '{parent_name}' not found for bone '{bone_def['name']}'"
                    )
                bone.parent = parent_bone
                bone.use_connect = connected

        # Return to object mode
        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": arm_obj.name,
            "display_type": display_type,
            "bone_count": len(bone_names_created),
            "bones": bone_names_created,
        }


    def _handle_autorig_preset(self, params: dict) -> dict:
        """Generate a complete rig from a preset type."""
        object_name = require_param(params, "object_name", str)
        preset = require_param(params, "preset", str)
        preset = validate_enum(
            preset, "preset",
            [
                "BIPED", "QUADRUPED", "VEHICLE", "MECHANICAL_ARM",
                "TURRET", "WHEEL_ASSEMBLY", "DOOR_HINGE", "PISTON",
                "LANDING_GEAR",
            ],
        )
        auto_weight = params.get("auto_weight", True)
        msfs_compatible = params.get("msfs_compatible", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh, got {obj.type}")

        # Get object dimensions for scaling the rig
        dims = obj.dimensions
        sx, sy, sz = dims.x, dims.y, dims.z

        # Prefix for MSFS naming
        pfx = "bone_" if msfs_compatible else ""

        # Generate bone definitions based on preset
        bones = []
        constraints = []

        if preset == "BIPED":
            h = sz  # height
            bones = [
                {"name": f"{pfx}root", "head": [0, 0, 0], "tail": [0, 0, h * 0.1]},
                {"name": f"{pfx}spine", "head": [0, 0, h * 0.1], "tail": [0, 0, h * 0.3],
                 "parent": f"{pfx}root", "connected": True},
                {"name": f"{pfx}chest", "head": [0, 0, h * 0.3], "tail": [0, 0, h * 0.55],
                 "parent": f"{pfx}spine", "connected": True},
                {"name": f"{pfx}neck", "head": [0, 0, h * 0.55], "tail": [0, 0, h * 0.65],
                 "parent": f"{pfx}chest", "connected": True},
                {"name": f"{pfx}head", "head": [0, 0, h * 0.65], "tail": [0, 0, h * 0.85],
                 "parent": f"{pfx}neck", "connected": True},
                # Left arm
                {"name": f"{pfx}shoulder.L", "head": [0, 0, h * 0.55], "tail": [sx * 0.2, 0, h * 0.55],
                 "parent": f"{pfx}chest"},
                {"name": f"{pfx}upper_arm.L", "head": [sx * 0.2, 0, h * 0.55], "tail": [sx * 0.35, 0, h * 0.35],
                 "parent": f"{pfx}shoulder.L", "connected": True},
                {"name": f"{pfx}forearm.L", "head": [sx * 0.35, 0, h * 0.35], "tail": [sx * 0.5, 0, h * 0.15],
                 "parent": f"{pfx}upper_arm.L", "connected": True},
                {"name": f"{pfx}hand.L", "head": [sx * 0.5, 0, h * 0.15], "tail": [sx * 0.55, 0, h * 0.1],
                 "parent": f"{pfx}forearm.L", "connected": True},
                # Right arm
                {"name": f"{pfx}shoulder.R", "head": [0, 0, h * 0.55], "tail": [-sx * 0.2, 0, h * 0.55],
                 "parent": f"{pfx}chest"},
                {"name": f"{pfx}upper_arm.R", "head": [-sx * 0.2, 0, h * 0.55], "tail": [-sx * 0.35, 0, h * 0.35],
                 "parent": f"{pfx}shoulder.R", "connected": True},
                {"name": f"{pfx}forearm.R", "head": [-sx * 0.35, 0, h * 0.35], "tail": [-sx * 0.5, 0, h * 0.15],
                 "parent": f"{pfx}upper_arm.R", "connected": True},
                {"name": f"{pfx}hand.R", "head": [-sx * 0.5, 0, h * 0.15], "tail": [-sx * 0.55, 0, h * 0.1],
                 "parent": f"{pfx}forearm.R", "connected": True},
                # Left leg
                {"name": f"{pfx}thigh.L", "head": [sx * 0.1, 0, h * 0.1], "tail": [sx * 0.1, 0.02, -h * 0.15],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}shin.L", "head": [sx * 0.1, 0.02, -h * 0.15], "tail": [sx * 0.1, 0, -h * 0.45],
                 "parent": f"{pfx}thigh.L", "connected": True},
                {"name": f"{pfx}foot.L", "head": [sx * 0.1, 0, -h * 0.45], "tail": [sx * 0.1, -0.08 * h, -h * 0.48],
                 "parent": f"{pfx}shin.L", "connected": True},
                # Right leg
                {"name": f"{pfx}thigh.R", "head": [-sx * 0.1, 0, h * 0.1], "tail": [-sx * 0.1, 0.02, -h * 0.15],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}shin.R", "head": [-sx * 0.1, 0.02, -h * 0.15], "tail": [-sx * 0.1, 0, -h * 0.45],
                 "parent": f"{pfx}thigh.R", "connected": True},
                {"name": f"{pfx}foot.R", "head": [-sx * 0.1, 0, -h * 0.45], "tail": [-sx * 0.1, -0.08 * h, -h * 0.48],
                 "parent": f"{pfx}shin.R", "connected": True},
            ]

        elif preset == "QUADRUPED":
            bones = [
                {"name": f"{pfx}root", "head": [0, 0, sz * 0.5], "tail": [0, sy * 0.1, sz * 0.5]},
                {"name": f"{pfx}spine_front", "head": [0, sy * 0.3, sz * 0.5], "tail": [0, sy * 0.45, sz * 0.55],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}spine_back", "head": [0, -sy * 0.3, sz * 0.5], "tail": [0, -sy * 0.45, sz * 0.5],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}neck", "head": [0, sy * 0.45, sz * 0.55], "tail": [0, sy * 0.5, sz * 0.75],
                 "parent": f"{pfx}spine_front", "connected": True},
                {"name": f"{pfx}head", "head": [0, sy * 0.5, sz * 0.75], "tail": [0, sy * 0.6, sz * 0.8],
                 "parent": f"{pfx}neck", "connected": True},
                {"name": f"{pfx}tail", "head": [0, -sy * 0.45, sz * 0.5], "tail": [0, -sy * 0.6, sz * 0.55],
                 "parent": f"{pfx}spine_back", "connected": True},
                # Front legs
                {"name": f"{pfx}front_upper.L", "head": [sx * 0.15, sy * 0.35, sz * 0.4], "tail": [sx * 0.15, sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_front"},
                {"name": f"{pfx}front_lower.L", "head": [sx * 0.15, sy * 0.35, sz * 0.2], "tail": [sx * 0.15, sy * 0.35, 0],
                 "parent": f"{pfx}front_upper.L", "connected": True},
                {"name": f"{pfx}front_upper.R", "head": [-sx * 0.15, sy * 0.35, sz * 0.4], "tail": [-sx * 0.15, sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_front"},
                {"name": f"{pfx}front_lower.R", "head": [-sx * 0.15, sy * 0.35, sz * 0.2], "tail": [-sx * 0.15, sy * 0.35, 0],
                 "parent": f"{pfx}front_upper.R", "connected": True},
                # Rear legs
                {"name": f"{pfx}rear_upper.L", "head": [sx * 0.15, -sy * 0.35, sz * 0.4], "tail": [sx * 0.15, -sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_back"},
                {"name": f"{pfx}rear_lower.L", "head": [sx * 0.15, -sy * 0.35, sz * 0.2], "tail": [sx * 0.15, -sy * 0.35, 0],
                 "parent": f"{pfx}rear_upper.L", "connected": True},
                {"name": f"{pfx}rear_upper.R", "head": [-sx * 0.15, -sy * 0.35, sz * 0.4], "tail": [-sx * 0.15, -sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_back"},
                {"name": f"{pfx}rear_lower.R", "head": [-sx * 0.15, -sy * 0.35, sz * 0.2], "tail": [-sx * 0.15, -sy * 0.35, 0],
                 "parent": f"{pfx}rear_upper.R", "connected": True},
            ]

        elif preset == "VEHICLE":
            # Vehicle rig: body, 4 wheels with suspension, steering
            hw = sx * 0.4  # half wheel track width
            wb_f = sy * 0.35  # front axle offset
            wb_r = -sy * 0.35  # rear axle offset
            wh = sz * 0.15  # wheel center height
            susp_top = sz * 0.4
            bones = [
                {"name": f"{pfx}body", "head": [0, 0, sz * 0.3], "tail": [0, sy * 0.2, sz * 0.3]},
                {"name": f"{pfx}steering", "head": [0, wb_f, susp_top], "tail": [0, wb_f + 0.05, susp_top],
                 "parent": f"{pfx}body"},
                # Front left
                {"name": f"{pfx}suspension_fl", "head": [hw, wb_f, susp_top], "tail": [hw, wb_f, wh],
                 "parent": f"{pfx}steering"},
                {"name": f"{pfx}wheel_fl", "head": [hw, wb_f, wh], "tail": [hw + 0.05, wb_f, wh],
                 "parent": f"{pfx}suspension_fl", "connected": True},
                # Front right
                {"name": f"{pfx}suspension_fr", "head": [-hw, wb_f, susp_top], "tail": [-hw, wb_f, wh],
                 "parent": f"{pfx}steering"},
                {"name": f"{pfx}wheel_fr", "head": [-hw, wb_f, wh], "tail": [-hw - 0.05, wb_f, wh],
                 "parent": f"{pfx}suspension_fr", "connected": True},
                # Rear left
                {"name": f"{pfx}suspension_rl", "head": [hw, wb_r, susp_top], "tail": [hw, wb_r, wh],
                 "parent": f"{pfx}body"},
                {"name": f"{pfx}wheel_rl", "head": [hw, wb_r, wh], "tail": [hw + 0.05, wb_r, wh],
                 "parent": f"{pfx}suspension_rl", "connected": True},
                # Rear right
                {"name": f"{pfx}suspension_rr", "head": [-hw, wb_r, susp_top], "tail": [-hw, wb_r, wh],
                 "parent": f"{pfx}body"},
                {"name": f"{pfx}wheel_rr", "head": [-hw, wb_r, wh], "tail": [-hw - 0.05, wb_r, wh],
                 "parent": f"{pfx}suspension_rr", "connected": True},
            ]

        elif preset == "MECHANICAL_ARM":
            # Chain of arm segments with IK target
            seg_len = sz * 0.25
            bones = [
                {"name": f"{pfx}arm_base", "head": [0, 0, 0], "tail": [0, 0, seg_len]},
                {"name": f"{pfx}arm_seg1", "head": [0, 0, seg_len], "tail": [0, 0, seg_len * 2],
                 "parent": f"{pfx}arm_base", "connected": True},
                {"name": f"{pfx}arm_seg2", "head": [0, 0, seg_len * 2], "tail": [0, 0, seg_len * 3],
                 "parent": f"{pfx}arm_seg1", "connected": True},
                {"name": f"{pfx}arm_seg3", "head": [0, 0, seg_len * 3], "tail": [0, 0, seg_len * 4],
                 "parent": f"{pfx}arm_seg2", "connected": True},
                {"name": f"{pfx}arm_tip", "head": [0, 0, seg_len * 4], "tail": [0, 0, seg_len * 4.2],
                 "parent": f"{pfx}arm_seg3", "connected": True},
                {"name": f"{pfx}arm_ik_target", "head": [0, seg_len, seg_len * 3], "tail": [0, seg_len, seg_len * 3.2]},
            ]
            constraints.append({
                "bone": f"{pfx}arm_tip",
                "type": "IK",
                "target_bone": f"{pfx}arm_ik_target",
                "chain_count": 4,
            })

        elif preset == "TURRET":
            base_h = sz * 0.3
            barrel_len = sy * 0.4
            bones = [
                {"name": f"{pfx}turret_base", "head": [0, 0, 0], "tail": [0, 0, base_h]},
                {"name": f"{pfx}turret_rotation", "head": [0, 0, base_h], "tail": [0, 0.05, base_h],
                 "parent": f"{pfx}turret_base", "connected": True},
                {"name": f"{pfx}turret_elevation", "head": [0, 0, base_h], "tail": [0, barrel_len, base_h],
                 "parent": f"{pfx}turret_rotation"},
            ]

        elif preset == "WHEEL_ASSEMBLY":
            axle_len = sx * 0.3
            bones = [
                {"name": f"{pfx}axle", "head": [0, 0, 0], "tail": [axle_len, 0, 0]},
                {"name": f"{pfx}wheel", "head": [axle_len, 0, 0], "tail": [axle_len + 0.05, 0, 0],
                 "parent": f"{pfx}axle", "connected": True},
            ]

        elif preset == "DOOR_HINGE":
            door_h = sz * 0.8
            bones = [
                {"name": f"{pfx}hinge", "head": [0, 0, 0], "tail": [0, 0, door_h]},
                {"name": f"{pfx}door", "head": [0, 0, door_h * 0.5], "tail": [sx * 0.5, 0, door_h * 0.5],
                 "parent": f"{pfx}hinge"},
            ]
            constraints.append({
                "bone": f"{pfx}hinge",
                "type": "LIMIT_ROTATION",
                "settings": {
                    "use_limit_z": True,
                    "min_z": math.radians(-120),
                    "max_z": 0,
                    "owner_space": "LOCAL",
                },
            })

        elif preset == "PISTON":
            piston_len = sy * 0.4
            bones = [
                {"name": f"{pfx}piston_cylinder", "head": [0, 0, 0], "tail": [0, piston_len * 0.6, 0]},
                {"name": f"{pfx}piston_rod", "head": [0, piston_len * 0.4, 0], "tail": [0, piston_len, 0]},
            ]
            constraints.append({
                "bone": f"{pfx}piston_rod",
                "type": "STRETCH_TO",
                "target_bone": f"{pfx}piston_cylinder",
            })

        elif preset == "LANDING_GEAR":
            gear_h = sz * 0.6
            bones = [
                {"name": f"{pfx}gear_mount", "head": [0, 0, gear_h], "tail": [0, 0.02, gear_h]},
                {"name": f"{pfx}gear_strut_upper", "head": [0, 0, gear_h], "tail": [0, 0, gear_h * 0.6],
                 "parent": f"{pfx}gear_mount", "connected": True},
                {"name": f"{pfx}gear_strut_lower", "head": [0, 0, gear_h * 0.6], "tail": [0, 0, gear_h * 0.15],
                 "parent": f"{pfx}gear_strut_upper", "connected": True},
                {"name": f"{pfx}gear_wheel", "head": [0, 0, gear_h * 0.15], "tail": [0.05, 0, gear_h * 0.15],
                 "parent": f"{pfx}gear_strut_lower", "connected": True},
                {"name": f"{pfx}gear_retract_target", "head": [0, sy * 0.3, gear_h], "tail": [0, sy * 0.3 + 0.05, gear_h]},
            ]

        else:
            return {"error": f"Preset '{preset}' not implemented"}

        # Create the armature using armature_create logic
        arm_name = f"{object_name}_{preset.lower()}_rig"
        arm_data = bpy.data.armatures.new(arm_name)
        arm_data.display_type = "OCTAHEDRAL"
        arm_obj = bpy.data.objects.new(arm_name, arm_data)
        bpy.context.collection.objects.link(arm_obj)

        # Position armature at object location
        arm_obj.location = obj.location.copy()

        ensure_object_selected(arm_obj)
        bpy.ops.object.mode_set(mode="EDIT")

        # Create bones
        for bone_def in bones:
            head = bone_def["head"]
            tail = bone_def["tail"]
            roll = math.radians(bone_def.get("roll", 0))

            edit_bone = arm_data.edit_bones.new(bone_def["name"])
            edit_bone.head = (float(head[0]), float(head[1]), float(head[2]))
            edit_bone.tail = (float(tail[0]), float(tail[1]), float(tail[2]))
            edit_bone.roll = roll

        # Set parents
        for bone_def in bones:
            parent_name = bone_def.get("parent")
            if parent_name:
                bone = arm_data.edit_bones.get(bone_def["name"])
                parent = arm_data.edit_bones.get(parent_name)
                if bone and parent:
                    bone.parent = parent
                    bone.use_connect = bone_def.get("connected", False)

        bpy.ops.object.mode_set(mode="OBJECT")

        # Apply constraints if any
        if constraints:
            ensure_object_selected(arm_obj)
            bpy.ops.object.mode_set(mode="POSE")

            for c_def in constraints:
                pose_bone = arm_obj.pose.bones.get(c_def["bone"])
                if pose_bone is None:
                    continue

                c_type = c_def["type"]
                constraint = pose_bone.constraints.new(type=c_type)

                if "target_bone" in c_def:
                    constraint.target = arm_obj
                    constraint.subtarget = c_def["target_bone"]

                if "chain_count" in c_def and hasattr(constraint, "chain_count"):
                    constraint.chain_count = c_def["chain_count"]

                settings = c_def.get("settings", {})
                for key, value in settings.items():
                    if hasattr(constraint, key):
                        setattr(constraint, key, value)

            bpy.ops.object.mode_set(mode="OBJECT")

        # Auto-weight if requested
        weight_result = "skipped"
        if auto_weight:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                arm_obj.select_set(True)
                bpy.context.view_layer.objects.active = arm_obj
                bpy.ops.object.parent_set(type="ARMATURE_AUTO")
                weight_result = "success"
            except RuntimeError as e:
                weight_result = f"failed: {str(e)}"

        return {
            "success": True,
            "armature": arm_obj.name,
            "mesh_object": object_name,
            "preset": preset,
            "bone_count": len(bones),
            "bone_names": [b["name"] for b in bones],
            "constraint_count": len(constraints),
            "auto_weight": weight_result,
            "msfs_compatible": msfs_compatible,
        }


    def _handle_constraint_add(self, params: dict) -> dict:
        """Add a constraint to a bone or object."""
        armature_name = params.get("armature_name")
        bone_name = params.get("bone_name")
        object_name = params.get("object_name")
        constraint_type = require_param(params, "constraint_type", str)
        constraint_type = validate_enum(
            constraint_type, "constraint_type",
            [
                "IK", "COPY_ROTATION", "COPY_LOCATION", "COPY_SCALE",
                "TRACK_TO", "DAMPED_TRACK", "STRETCH_TO",
                "LIMIT_ROTATION", "LIMIT_LOCATION", "FLOOR", "CHILD_OF",
            ],
        )
        target_object_name = params.get("target_object")
        target_bone_name = params.get("target_bone")
        influence = float(params.get("influence", 1.0))
        settings = params.get("settings", {})

        # Determine what to add the constraint to
        constraint_owner = None
        owner_desc = ""

        if bone_name and armature_name:
            # Bone constraint
            arm_obj = get_object_or_error(armature_name)
            if arm_obj.type != "ARMATURE":
                raise ValidationError(f"Object '{armature_name}' is not an armature")

            ensure_object_selected(arm_obj)
            if bpy.context.mode != "POSE":
                if bpy.context.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.mode_set(mode="POSE")

            pose_bone = arm_obj.pose.bones.get(bone_name)
            if pose_bone is None:
                available = [b.name for b in arm_obj.pose.bones]
                raise ValidationError(
                    f"Bone '{bone_name}' not found in armature '{armature_name}'. "
                    f"Available: {available}"
                )
            constraint_owner = pose_bone
            owner_desc = f"bone '{bone_name}' in '{armature_name}'"

        elif object_name:
            # Object constraint
            target_obj = get_object_or_error(object_name)
            constraint_owner = target_obj
            owner_desc = f"object '{object_name}'"
        else:
            raise ValidationError(
                "Must specify either (armature_name + bone_name) for bone constraint, "
                "or object_name for object constraint"
            )

        # Create the constraint
        constraint = constraint_owner.constraints.new(type=constraint_type)
        constraint.influence = influence

        # Set target
        if target_object_name:
            target_obj = bpy.data.objects.get(target_object_name)
            if target_obj is None:
                raise ValidationError(f"Target object '{target_object_name}' not found")
            constraint.target = target_obj

            if target_bone_name and hasattr(constraint, "subtarget"):
                constraint.subtarget = target_bone_name

        # Apply type-specific settings
        if isinstance(settings, dict):
            for key, value in settings.items():
                if hasattr(constraint, key):
                    try:
                        setattr(constraint, key, value)
                    except (TypeError, AttributeError):
                        pass  # Skip incompatible settings

        # Return to object mode if we were working with bones
        if bone_name and armature_name:
            bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "owner": owner_desc,
            "constraint_type": constraint_type,
            "constraint_name": constraint.name,
            "target": target_object_name,
            "target_bone": target_bone_name,
            "influence": influence,
        }


    def _handle_constraint_preset(self, params: dict) -> dict:
        """Apply preset constraint setups requiring multiple coordinated constraints."""
        armature_name = require_param(params, "armature_name", str)
        preset = require_param(params, "preset", str)
        preset = validate_enum(
            preset, "preset",
            ["IK_ARM", "IK_LEG", "PISTON_PAIR", "WHEEL_SPIN", "DOOR_SWING", "TURRET_TRACK"],
        )
        bones = require_param(params, "bones")
        if not isinstance(bones, dict):
            raise ValidationError("'bones' must be an object with bone name mappings")

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        constraints_added = []

        def get_pose_bone(name):
            pb = arm_obj.pose.bones.get(name)
            if pb is None:
                raise ValidationError(
                    f"Bone '{name}' not found in armature '{armature_name}'. "
                    f"Available: {[b.name for b in arm_obj.pose.bones]}"
                )
            return pb

        if preset == "IK_ARM":
            ik_bone_name = require_param(bones, "ik_bone", str)
            pole_target_name = bones.get("pole_target")
            chain_count = int(bones.get("chain_count", 3))

            ik_bone = get_pose_bone(ik_bone_name)
            c = ik_bone.constraints.new(type="IK")
            c.chain_count = chain_count

            if pole_target_name:
                get_pose_bone(pole_target_name)
                c.pole_target = arm_obj
                c.pole_subtarget = pole_target_name
                c.pole_angle = math.radians(90)

            constraints_added.append({"bone": ik_bone_name, "type": "IK", "chain_count": chain_count})

        elif preset == "IK_LEG":
            ik_bone_name = require_param(bones, "ik_bone", str)
            pole_target_name = bones.get("pole_target")
            foot_bone_name = bones.get("foot_bone")
            chain_count = int(bones.get("chain_count", 2))

            ik_bone = get_pose_bone(ik_bone_name)
            c = ik_bone.constraints.new(type="IK")
            c.chain_count = chain_count

            if pole_target_name:
                c.pole_target = arm_obj
                c.pole_subtarget = pole_target_name
                c.pole_angle = math.radians(-90)

            constraints_added.append({"bone": ik_bone_name, "type": "IK", "chain_count": chain_count})

            # Add copy rotation to foot bone for foot roll
            if foot_bone_name:
                foot_bone = get_pose_bone(foot_bone_name)
                cr = foot_bone.constraints.new(type="COPY_ROTATION")
                cr.target = arm_obj
                cr.subtarget = ik_bone_name
                cr.use_x = True
                cr.use_y = False
                cr.use_z = False
                cr.mix_mode = "ADD"
                cr.target_space = "LOCAL"
                cr.owner_space = "LOCAL"
                constraints_added.append({"bone": foot_bone_name, "type": "COPY_ROTATION"})

        elif preset == "PISTON_PAIR":
            bone_a_name = require_param(bones, "bone_a", str)
            bone_b_name = require_param(bones, "bone_b", str)

            bone_a = get_pose_bone(bone_a_name)
            bone_b = get_pose_bone(bone_b_name)

            # bone_a stretches to bone_b tail
            sa = bone_a.constraints.new(type="STRETCH_TO")
            sa.target = arm_obj
            sa.subtarget = bone_b_name
            sa.rest_length = 0
            sa.bulge = 1.0
            constraints_added.append({"bone": bone_a_name, "type": "STRETCH_TO", "target": bone_b_name})

            # bone_b tracks bone_a
            tb = bone_b.constraints.new(type="DAMPED_TRACK")
            tb.target = arm_obj
            tb.subtarget = bone_a_name
            constraints_added.append({"bone": bone_b_name, "type": "DAMPED_TRACK", "target": bone_a_name})

        elif preset == "WHEEL_SPIN":
            wheel_bone_name = require_param(bones, "wheel_bone", str)
            axis = bones.get("axis", "X").upper()
            if axis not in ("X", "Y", "Z"):
                axis = "X"

            wheel_bone = get_pose_bone(wheel_bone_name)

            # Add a limit rotation to prevent unwanted rotation on other axes
            lr = wheel_bone.constraints.new(type="LIMIT_ROTATION")
            lr.owner_space = "LOCAL"
            lr.use_limit_x = (axis != "X")
            lr.use_limit_y = (axis != "Y")
            lr.use_limit_z = (axis != "Z")
            if axis != "X":
                lr.min_x = 0
                lr.max_x = 0
            if axis != "Y":
                lr.min_y = 0
                lr.max_y = 0
            if axis != "Z":
                lr.min_z = 0
                lr.max_z = 0

            constraints_added.append({
                "bone": wheel_bone_name,
                "type": "LIMIT_ROTATION",
                "free_axis": axis,
            })

        elif preset == "DOOR_SWING":
            hinge_bone_name = require_param(bones, "hinge_bone", str)
            min_angle = float(bones.get("min_angle", -120))
            max_angle = float(bones.get("max_angle", 0))
            axis = bones.get("axis", "Z").upper()
            if axis not in ("X", "Y", "Z"):
                axis = "Z"

            hinge_bone = get_pose_bone(hinge_bone_name)

            lr = hinge_bone.constraints.new(type="LIMIT_ROTATION")
            lr.owner_space = "LOCAL"
            lr.use_limit_x = True
            lr.use_limit_y = True
            lr.use_limit_z = True

            # Allow rotation only on the specified axis
            if axis == "X":
                lr.min_x = math.radians(min_angle)
                lr.max_x = math.radians(max_angle)
            else:
                lr.min_x = 0
                lr.max_x = 0

            if axis == "Y":
                lr.min_y = math.radians(min_angle)
                lr.max_y = math.radians(max_angle)
            else:
                lr.min_y = 0
                lr.max_y = 0

            if axis == "Z":
                lr.min_z = math.radians(min_angle)
                lr.max_z = math.radians(max_angle)
            else:
                lr.min_z = 0
                lr.max_z = 0

            constraints_added.append({
                "bone": hinge_bone_name,
                "type": "LIMIT_ROTATION",
                "axis": axis,
                "min_angle": min_angle,
                "max_angle": max_angle,
            })

        elif preset == "TURRET_TRACK":
            base_bone_name = require_param(bones, "base_bone", str)
            elev_bone_name = require_param(bones, "elevation_bone", str)
            target_bone_name = bones.get("target_bone")

            base_bone = get_pose_bone(base_bone_name)
            elev_bone = get_pose_bone(elev_bone_name)

            # Base bone: track target on Z axis only (horizontal rotation)
            if target_bone_name:
                dt_base = base_bone.constraints.new(type="DAMPED_TRACK")
                dt_base.target = arm_obj
                dt_base.subtarget = target_bone_name
                dt_base.track_axis = "TRACK_Y"

                # Lock to Z-axis rotation only
                lr_base = base_bone.constraints.new(type="LIMIT_ROTATION")
                lr_base.owner_space = "LOCAL"
                lr_base.use_limit_x = True
                lr_base.use_limit_y = True
                lr_base.min_x = 0
                lr_base.max_x = 0
                lr_base.min_y = 0
                lr_base.max_y = 0

                constraints_added.append({"bone": base_bone_name, "type": "DAMPED_TRACK"})
                constraints_added.append({"bone": base_bone_name, "type": "LIMIT_ROTATION"})

                # Elevation bone: track target on local X axis (vertical rotation)
                dt_elev = elev_bone.constraints.new(type="DAMPED_TRACK")
                dt_elev.target = arm_obj
                dt_elev.subtarget = target_bone_name
                dt_elev.track_axis = "TRACK_Y"

                # Limit elevation
                lr_elev = elev_bone.constraints.new(type="LIMIT_ROTATION")
                lr_elev.owner_space = "LOCAL"
                lr_elev.use_limit_x = True
                lr_elev.use_limit_y = True
                lr_elev.use_limit_z = True
                lr_elev.min_x = math.radians(-45)
                lr_elev.max_x = math.radians(30)
                lr_elev.min_y = 0
                lr_elev.max_y = 0
                lr_elev.min_z = 0
                lr_elev.max_z = 0

                constraints_added.append({"bone": elev_bone_name, "type": "DAMPED_TRACK"})
                constraints_added.append({"bone": elev_bone_name, "type": "LIMIT_ROTATION"})

        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": armature_name,
            "preset": preset,
            "constraints_added": constraints_added,
            "total_constraints": len(constraints_added),
        }


    def _handle_bone_shape_assign(self, params: dict) -> dict:
        """Assign a custom wireframe control shape to a bone."""
        armature_name = require_param(params, "armature_name", str)
        bone_name = require_param(params, "bone_name", str)
        shape = require_param(params, "shape", str)
        shape = validate_enum(
            shape, "shape",
            ["CIRCLE", "SQUARE", "CUBE", "SPHERE", "ARROW", "DIAMOND", "CROSS"],
        )
        scale = float(params.get("scale", 1.0))

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        # Check bone exists
        if bone_name not in arm_obj.data.bones:
            available = [b.name for b in arm_obj.data.bones]
            raise ValidationError(
                f"Bone '{bone_name}' not found. Available: {available}"
            )

        # Create or find the shape widget object
        widget_name = f"WGT_{shape.lower()}"
        widget_obj = bpy.data.objects.get(widget_name)

        if widget_obj is None:
            import bmesh

            bm = bmesh.new()

            if shape == "CIRCLE":
                segments = 16
                for i in range(segments):
                    angle = 2 * math.pi * i / segments
                    bm.verts.new((math.cos(angle), math.sin(angle), 0))
                bm.verts.ensure_lookup_table()
                for i in range(segments):
                    bm.edges.new((bm.verts[i], bm.verts[(i + 1) % segments]))

            elif shape == "SQUARE":
                verts = [
                    bm.verts.new((-1, -1, 0)),
                    bm.verts.new((1, -1, 0)),
                    bm.verts.new((1, 1, 0)),
                    bm.verts.new((-1, 1, 0)),
                ]
                for i in range(4):
                    bm.edges.new((verts[i], verts[(i + 1) % 4]))

            elif shape == "CUBE":
                # Wireframe cube
                coords = [
                    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
                ]
                for c in coords:
                    bm.verts.new(c)
                bm.verts.ensure_lookup_table()
                edges_idx = [
                    (0, 1), (1, 2), (2, 3), (3, 0),
                    (4, 5), (5, 6), (6, 7), (7, 4),
                    (0, 4), (1, 5), (2, 6), (3, 7),
                ]
                for a, b in edges_idx:
                    bm.edges.new((bm.verts[a], bm.verts[b]))

            elif shape == "SPHERE":
                # Simple wireframe sphere (3 circles)
                segments = 16
                for axis in range(3):
                    offset = len(bm.verts)
                    for i in range(segments):
                        angle = 2 * math.pi * i / segments
                        if axis == 0:
                            bm.verts.new((0, math.cos(angle), math.sin(angle)))
                        elif axis == 1:
                            bm.verts.new((math.cos(angle), 0, math.sin(angle)))
                        else:
                            bm.verts.new((math.cos(angle), math.sin(angle), 0))
                    bm.verts.ensure_lookup_table()
                    for i in range(segments):
                        bm.edges.new((bm.verts[offset + i], bm.verts[offset + (i + 1) % segments]))

            elif shape == "ARROW":
                verts = [
                    bm.verts.new((0, 0, 0)),
                    bm.verts.new((0, 2, 0)),
                    bm.verts.new((-0.5, 1.5, 0)),
                    bm.verts.new((0.5, 1.5, 0)),
                ]
                bm.edges.new((verts[0], verts[1]))
                bm.edges.new((verts[1], verts[2]))
                bm.edges.new((verts[1], verts[3]))

            elif shape == "DIAMOND":
                verts = [
                    bm.verts.new((0, -1, 0)),
                    bm.verts.new((1, 0, 0)),
                    bm.verts.new((0, 1, 0)),
                    bm.verts.new((-1, 0, 0)),
                    bm.verts.new((0, 0, 1)),
                    bm.verts.new((0, 0, -1)),
                ]
                edges_idx = [
                    (0, 1), (1, 2), (2, 3), (3, 0),
                    (0, 4), (1, 4), (2, 4), (3, 4),
                    (0, 5), (1, 5), (2, 5), (3, 5),
                ]
                for a, b in edges_idx:
                    bm.edges.new((verts[a], verts[b]))

            elif shape == "CROSS":
                verts = [
                    bm.verts.new((-1, 0, 0)),
                    bm.verts.new((1, 0, 0)),
                    bm.verts.new((0, -1, 0)),
                    bm.verts.new((0, 1, 0)),
                    bm.verts.new((0, 0, -1)),
                    bm.verts.new((0, 0, 1)),
                ]
                bm.edges.new((verts[0], verts[1]))
                bm.edges.new((verts[2], verts[3]))
                bm.edges.new((verts[4], verts[5]))

            # Create mesh and object
            mesh = bpy.data.meshes.new(widget_name)
            bm.to_mesh(mesh)
            bm.free()

            widget_obj = bpy.data.objects.new(widget_name, mesh)
            # Put in a hidden collection for widgets
            wgt_collection = bpy.data.collections.get("Widgets")
            if wgt_collection is None:
                wgt_collection = bpy.data.collections.new("Widgets")
                bpy.context.scene.collection.children.link(wgt_collection)
                # Hide the widgets collection
                layer_collection = bpy.context.view_layer.layer_collection
                for child in layer_collection.children:
                    if child.collection == wgt_collection:
                        child.hide_viewport = True
                        break
            wgt_collection.objects.link(widget_obj)
            widget_obj.display_type = "WIRE"
            widget_obj.hide_render = True

        # Assign shape to bone
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        pose_bone = arm_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            bpy.ops.object.mode_set(mode="OBJECT")
            raise ValidationError(f"Pose bone '{bone_name}' not found")

        pose_bone.custom_shape = widget_obj
        pose_bone.custom_shape_scale_xyz = (scale, scale, scale)
        pose_bone.use_custom_shape_bone_size = True

        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": armature_name,
            "bone": bone_name,
            "shape": shape,
            "widget_object": widget_obj.name,
            "scale": scale,
        }


    def _handle_pose_library_save(self, params: dict) -> dict:
        """Save the current pose as a named pose in custom properties."""
        armature_name = require_param(params, "armature_name", str)
        pose_name = require_param(params, "pose_name", str)
        bone_filter = params.get("bone_filter")

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        # Enter pose mode to read pose bone transforms
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        pose_data = {}
        bones_saved = []

        for pose_bone in arm_obj.pose.bones:
            if bone_filter and pose_bone.name not in bone_filter:
                continue

            # Store location, rotation (quaternion), and scale
            pose_data[pose_bone.name] = {
                "location": list(pose_bone.location),
                "rotation_quaternion": list(pose_bone.rotation_quaternion),
                "rotation_euler": list(pose_bone.rotation_euler),
                "rotation_mode": pose_bone.rotation_mode,
                "scale": list(pose_bone.scale),
            }
            bones_saved.append(pose_bone.name)

        bpy.ops.object.mode_set(mode="OBJECT")

        # Store in custom property as JSON
        prop_key = f"_pose_lib_{pose_name}"
        arm_obj[prop_key] = json.dumps(pose_data)

        # Also maintain an index of saved poses
        index_key = "_pose_lib_index"
        existing_index = json.loads(arm_obj.get(index_key, "[]"))
        if pose_name not in existing_index:
            existing_index.append(pose_name)
        arm_obj[index_key] = json.dumps(existing_index)

        return {
            "success": True,
            "armature": armature_name,
            "pose_name": pose_name,
            "bones_saved": bones_saved,
            "bone_count": len(bones_saved),
            "all_saved_poses": existing_index,
        }


    def _handle_pose_library_apply(self, params: dict) -> dict:
        """Apply a previously saved pose to an armature."""
        from mathutils import Euler, Quaternion, Vector

        armature_name = require_param(params, "armature_name", str)
        pose_name = require_param(params, "pose_name", str)
        blend_factor = float(params.get("blend_factor", 1.0))
        blend_factor = max(0.0, min(1.0, blend_factor))

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        # Load pose data from custom property
        prop_key = f"_pose_lib_{pose_name}"
        pose_json = arm_obj.get(prop_key)
        if pose_json is None:
            # List available poses
            index_key = "_pose_lib_index"
            available = json.loads(arm_obj.get(index_key, "[]"))
            raise ValidationError(
                f"Pose '{pose_name}' not found. Available poses: {available}"
            )

        pose_data = json.loads(pose_json)

        # Enter pose mode
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        bones_applied = []
        bones_skipped = []

        for bone_name, transforms in pose_data.items():
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if pose_bone is None:
                bones_skipped.append(bone_name)
                continue

            saved_loc = Vector(transforms["location"])
            saved_scale = Vector(transforms["scale"])
            saved_rot_mode = transforms["rotation_mode"]

            if blend_factor >= 1.0:
                # Full application
                pose_bone.location = saved_loc
                pose_bone.scale = saved_scale
                if saved_rot_mode == "QUATERNION":
                    pose_bone.rotation_mode = "QUATERNION"
                    pose_bone.rotation_quaternion = Quaternion(transforms["rotation_quaternion"])
                else:
                    pose_bone.rotation_mode = saved_rot_mode
                    pose_bone.rotation_euler = Euler(transforms["rotation_euler"])
            else:
                # Blend with current pose
                current_loc = pose_bone.location.copy()
                current_scale = pose_bone.scale.copy()

                pose_bone.location = current_loc.lerp(saved_loc, blend_factor)
                pose_bone.scale = current_scale.lerp(saved_scale, blend_factor)

                if saved_rot_mode == "QUATERNION":
                    current_quat = pose_bone.rotation_quaternion.copy()
                    saved_quat = Quaternion(transforms["rotation_quaternion"])
                    pose_bone.rotation_mode = "QUATERNION"
                    pose_bone.rotation_quaternion = current_quat.slerp(saved_quat, blend_factor)
                else:
                    current_euler = pose_bone.rotation_euler.copy()
                    saved_euler = Euler(transforms["rotation_euler"])
                    # Linear interpolation for Euler angles
                    pose_bone.rotation_mode = saved_rot_mode
                    pose_bone.rotation_euler = Euler((
                        current_euler.x + (saved_euler.x - current_euler.x) * blend_factor,
                        current_euler.y + (saved_euler.y - current_euler.y) * blend_factor,
                        current_euler.z + (saved_euler.z - current_euler.z) * blend_factor,
                    ))

            bones_applied.append(bone_name)

        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": armature_name,
            "pose_name": pose_name,
            "blend_factor": blend_factor,
            "bones_applied": bones_applied,
            "bones_skipped": bones_skipped,
        }


    def _handle_rig_validate(self, params: dict) -> dict:
        """Validate an armature rig for export compatibility."""
        armature_name = require_param(params, "armature_name", str)
        target_format = params.get("target_format", "GENERIC")
        target_format = validate_enum(
            target_format, "target_format", ["MIXAMO", "UE5", "MSFS", "GENERIC"]
        )

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        arm_data = arm_obj.data
        issues = []
        warnings = []
        info = []

        bone_count = len(arm_data.bones)

        # Basic checks (all formats)
        # Check for zero-length bones
        for bone in arm_data.bones:
            length = (bone.tail_local - bone.head_local).length
            if length < 0.0001:
                issues.append(f"Zero-length bone: '{bone.name}' (will cause export issues)")

        # Check for non-uniform armature scale
        scale = arm_obj.scale
        if abs(scale.x - 1.0) > 0.01 or abs(scale.y - 1.0) > 0.01 or abs(scale.z - 1.0) > 0.01:
            warnings.append(
                f"Armature has non-unit scale ({scale.x:.3f}, {scale.y:.3f}, {scale.z:.3f}). "
                "Apply scale before export."
            )

        # Check rotation
        rot = arm_obj.rotation_euler
        if abs(rot.x) > 0.01 or abs(rot.y) > 0.01 or abs(rot.z) > 0.01:
            warnings.append(
                "Armature has non-zero rotation. Apply rotation before export."
            )

        # Check for bones without deform flag
        deform_bones = [b for b in arm_data.bones if b.use_deform]
        non_deform_bones = [b for b in arm_data.bones if not b.use_deform]
        info.append(f"Deform bones: {len(deform_bones)}, Non-deform: {len(non_deform_bones)}")

        # Check for disconnected bone hierarchy (orphan bones)
        root_bones = [b for b in arm_data.bones if b.parent is None]
        if len(root_bones) > 1:
            root_names = [b.name for b in root_bones]
            warnings.append(f"Multiple root bones found: {root_names}. Most formats expect a single root.")

        # Check constraints
        constraint_count = 0
        constraint_issues = []
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        for pose_bone in arm_obj.pose.bones:
            for c in pose_bone.constraints:
                constraint_count += 1
                if c.mute:
                    continue
                # Check for missing targets
                if hasattr(c, "target") and c.target is None:
                    constraint_issues.append(
                        f"Bone '{pose_bone.name}' constraint '{c.name}' ({c.type}) has no target"
                    )

        bpy.ops.object.mode_set(mode="OBJECT")

        if constraint_issues:
            issues.extend(constraint_issues)

        # Format-specific checks
        if target_format == "MIXAMO":
            # Mixamo expects specific bone naming
            mixamo_required = ["Hips", "Spine", "Head"]
            mixamo_found = []
            for req in mixamo_required:
                found = any(req.lower() in b.name.lower() for b in arm_data.bones)
                if found:
                    mixamo_found.append(req)
                else:
                    warnings.append(f"Mixamo: missing expected bone containing '{req}'")
            info.append(f"Mixamo bones found: {mixamo_found}")

        elif target_format == "UE5":
            # UE5 expects root bone at origin
            if root_bones:
                root = root_bones[0]
                if root.head_local.length > 0.01:
                    warnings.append(
                        f"UE5: root bone '{root.name}' head is not at origin "
                        f"({list(root.head_local)})"
                    )
            # Check max bone count
            if bone_count > 256:
                issues.append(f"UE5: bone count ({bone_count}) exceeds recommended max of 256")

        elif target_format == "MSFS":
            # MSFS checks
            if bone_count > 128:
                warnings.append(f"MSFS: bone count ({bone_count}) is high; consider simplifying")
            # Check for special naming
            msfs_bones = [b for b in arm_data.bones if b.name.startswith("bone_")]
            if msfs_bones:
                info.append(f"MSFS-prefixed bones: {len(msfs_bones)}")

        # Check attached meshes
        child_meshes = [
            child for child in arm_obj.children
            if child.type == "MESH"
        ]
        mesh_info = []
        for mesh_obj in child_meshes:
            # Check for armature modifier
            has_armature_mod = any(
                mod.type == "ARMATURE" and mod.object == arm_obj
                for mod in mesh_obj.modifiers
            )
            # Check vertex groups match bones
            vg_names = [vg.name for vg in mesh_obj.vertex_groups]
            matching_bones = [name for name in vg_names if name in arm_data.bones]
            unmatched_groups = [name for name in vg_names if name not in arm_data.bones]

            mesh_info.append({
                "mesh": mesh_obj.name,
                "has_armature_modifier": has_armature_mod,
                "vertex_groups": len(vg_names),
                "matching_bone_groups": len(matching_bones),
                "unmatched_groups": len(unmatched_groups),
            })

            if not has_armature_mod:
                warnings.append(f"Mesh '{mesh_obj.name}' is child but has no Armature modifier")
            if unmatched_groups:
                warnings.append(
                    f"Mesh '{mesh_obj.name}' has {len(unmatched_groups)} vertex groups "
                    f"not matching any bone"
                )

        # Calculate compatibility score
        max_score = 100
        score = max_score
        score -= len(issues) * 15  # Critical issues
        score -= len(warnings) * 5  # Warnings
        score = max(0, min(100, score))

        return {
            "success": True,
            "armature": armature_name,
            "target_format": target_format,
            "compatibility_score": score,
            "bone_count": bone_count,
            "root_bones": [b.name for b in root_bones],
            "deform_bone_count": len(deform_bones),
            "constraint_count": constraint_count,
            "child_meshes": mesh_info,
            "issues": issues,
            "warnings": warnings,
            "info": info,
        }


    # ========== Physics Simulation Handlers ==========

