"""Modifier-related command handlers."""

import bpy

from ..utils import ensure_object_selected, get_object_or_error
from ..validation import (
    ValidationError,
    require_param,
)


class ModifierHandlersMixin:
    """Mixin for modifier-related handlers."""

    def _handle_modifier_add(self, params: dict) -> dict:
        """Add modifier to object with optional preset configuration."""
        object_name = require_param(params, "object_name", str)
        modifier_type = require_param(params, "modifier_type", str).upper()

        obj = get_object_or_error(object_name)

        if obj.type != "MESH":
            raise ValidationError(
                f"Cannot add modifier: '{obj.name}' is a {obj.type}, not a MESH"
            )

        if modifier_type not in self.MODIFIER_TYPES:
            raise ValidationError(
                f"Unknown modifier type: '{modifier_type}'. "
                f"Supported types: {', '.join(self.MODIFIER_TYPES[:10])}..."
            )

        mod_name = params.get("modifier_name") or modifier_type
        use_preset = params.get("use_preset", True)

        mod = obj.modifiers.new(name=mod_name, type=modifier_type)

        # Apply preset configuration if available and requested
        if use_preset and modifier_type in self.MODIFIER_PRESETS:
            preset = self.MODIFIER_PRESETS[modifier_type]
            for key, value in preset.items():
                if hasattr(mod, key):
                    try:
                        setattr(mod, key, value)
                    except (TypeError, AttributeError):
                        pass  # Skip incompatible presets

        # Apply any custom properties from params
        if "properties" in params:
            for key, value in params["properties"].items():
                if hasattr(mod, key):
                    setattr(mod, key, value)

        return {
            "object": obj.name,
            "modifier": mod.name,
            "type": mod.type,
            "preset_applied": use_preset and modifier_type in self.MODIFIER_PRESETS,
        }


    def _handle_modifier_remove(self, params: dict) -> dict:
        """Remove modifier from object."""
        object_name = require_param(params, "object_name", str)
        modifier_name = require_param(params, "modifier_name", str)

        obj = get_object_or_error(object_name)
        mod = obj.modifiers.get(modifier_name)

        if mod is None:
            available = [m.name for m in obj.modifiers]
            raise ValidationError(
                f"Modifier '{modifier_name}' not found on '{obj.name}'. "
                f"Available modifiers: {available or 'none'}"
            )

        obj.modifiers.remove(mod)
        return {"object": obj.name, "removed": modifier_name}


    def _handle_modifier_apply(self, params: dict) -> dict:
        """Apply modifier to mesh (makes it permanent)."""
        object_name = require_param(params, "object_name", str)
        modifier_name = require_param(params, "modifier_name", str)

        obj = get_object_or_error(object_name)

        if modifier_name not in obj.modifiers:
            raise ValidationError(f"Modifier '{modifier_name}' not found on '{obj.name}'")

        ensure_object_selected(obj)

        # Need to be in object mode to apply
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.modifier_apply(modifier=modifier_name)
        return {"object": obj.name, "applied": modifier_name}


    def _handle_modifier_configure(self, params: dict) -> dict:
        """Configure modifier properties."""
        object_name = require_param(params, "object_name", str)
        modifier_name = require_param(params, "modifier_name", str)
        properties = require_param(params, "properties", dict)

        obj = get_object_or_error(object_name)
        mod = obj.modifiers.get(modifier_name)

        if mod is None:
            raise ValidationError(f"Modifier '{modifier_name}' not found on '{obj.name}'")

        applied_props = []
        failed_props = []

        for key, value in properties.items():
            if hasattr(mod, key):
                try:
                    setattr(mod, key, value)
                    applied_props.append(key)
                except (TypeError, ValueError) as e:
                    failed_props.append(f"{key}: {e}")
            else:
                failed_props.append(f"{key}: property not found")

        result = {
            "object": obj.name,
            "modifier": mod.name,
            "applied_properties": applied_props,
        }

        if failed_props:
            result["failed_properties"] = failed_props

        return result


    def _handle_modifier_list(self, params: dict) -> dict:
        """List modifiers on an object or list available modifier types."""
        object_name = params.get("object_name")

        if object_name:
            obj = get_object_or_error(object_name)
            modifiers = []
            for mod in obj.modifiers:
                modifiers.append({
                    "name": mod.name,
                    "type": mod.type,
                    "show_viewport": mod.show_viewport,
                    "show_render": mod.show_render,
                })
            return {"object": obj.name, "modifiers": modifiers}
        else:
            return {"available_types": self.MODIFIER_TYPES}

    # ========== Animation Handlers ==========

    # Common animatable properties
    ANIMATABLE_PROPERTIES = [
        "location", "rotation_euler", "rotation_quaternion", "scale",
        "delta_location", "delta_rotation_euler", "delta_scale",
    ]

