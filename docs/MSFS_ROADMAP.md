# MSFS 2020/2024 Content Creation Tools

This document describes the MSFS (Microsoft Flight Simulator) content creation tools available in the MCP Blender server.

## Overview

The MCP Blender server provides specialized tools for creating flight simulator-compatible 3D content. These tools support both MSFS 2020 and MSFS 2024, handling the specific requirements for LOD systems, material extensions, collision meshes, and animation events.

## Available Tools

### LOD (Level of Detail) System

Proper LOD implementation is critical for flight simulator performance.

| Tool | Description |
|------|-------------|
| `blender_msfs_create_lod_hierarchy` | Create LOD hierarchy from a base mesh |
| `blender_msfs_decimate_for_lod` | Decimate a mesh to a target ratio |
| `blender_msfs_setup_lod_distances` | Configure LOD switching distances |
| `blender_msfs_get_lod_info` | Get LOD hierarchy information |
| `blender_msfs_batch_export_lods` | Export all LODs with proper structure |

**Default LOD Distances:**
- LOD0: 0-50m (Full detail)
- LOD1: 50-200m (Medium detail, ~50% vertices)
- LOD2: 200-500m (Low detail, ~25% vertices)
- LOD3: 500m+ (Minimal detail, ~10% vertices)

**Example:**
```python
# Create LOD hierarchy from a vehicle model
blender_msfs_create_lod_hierarchy(
    base_object_name="Vehicle_Body",
    lod_count=4,
    auto_decimate=True
)

# Configure custom distances
blender_msfs_setup_lod_distances(
    base_name="Vehicle_Body",
    distances={"LOD0": 0, "LOD1": 30, "LOD2": 100, "LOD3": 300}
)
```

### MSFS Material Extensions

Flight simulators use glTF with custom material extensions.

| Tool | Description |
|------|-------------|
| `blender_msfs_setup_material` | Configure MSFS-specific material type |
| `blender_msfs_create_glass_material` | Create glass/windshield material |
| `blender_msfs_create_emissive_material` | Create emissive/light material |
| `blender_msfs_get_material_presets` | List available material presets |

**Supported Material Types:**
- `standard` - Standard PBR material
- `windshield` - Windshield with rain effects
- `clear_coat` - Vehicle paint, glossy surfaces
- `anisotropic` - Brushed metal
- `glass` - Transparent glass
- `parallax_window` - Fake interior depth
- `fake_terrain` - Ground shadows
- `geo_decal` - Decal textures
- `invisible` - Invisible collision only
- `environment_occluder` - Environment occlusion

**Available Presets:**
- `vehicle_paint` - Glossy car paint
- `chrome` - Reflective chrome
- `brushed_metal` - Anisotropic brushed metal
- `rubber` - Tire/rubber material
- `plastic` - General plastic
- `glass_clear` - Clear glass
- `glass_tinted` - Tinted glass
- `windshield` - Aircraft windshield
- `fabric` - Cloth/fabric
- `concrete` - Concrete surface
- `asphalt` - Road/runway surface

**Example:**
```python
# Create vehicle paint material
blender_msfs_setup_material(
    material_name="VehiclePaint",
    msfs_type="clear_coat",
    base_color=[0.8, 0.2, 0.1, 1.0],
    metallic=0.1,
    roughness=0.35
)

# Create cockpit glass
blender_msfs_create_glass_material(
    material_name="Windshield",
    opacity=0.05,
    is_windshield=True
)
```

### Collision Meshes

Collision meshes define physical interactions in the simulator.

| Tool | Description |
|------|-------------|
| `blender_msfs_create_collision_mesh` | Create simplified collision mesh |
| `blender_msfs_create_collision_box` | Create box collision primitive |
| `blender_msfs_create_collision_convex` | Create convex hull collision |
| `blender_msfs_tag_collision_type` | Tag existing mesh as collision |

**Collision Types:**
- `collider` - General physics collision
- `road` - Road/ground for vehicle pathfinding
- `water` - Water interaction zones
- `trigger` - Trigger volumes (enter/exit events)

**Example:**
```python
# Create simplified collision mesh
blender_msfs_create_collision_mesh(
    source_object_name="Vehicle_Body",
    collision_type="collider",
    simplify=True,
    simplify_ratio=0.3
)

# Create box collision for faster physics
blender_msfs_create_collision_box(
    object_name="Vehicle_Body",
    collision_type="collider",
    padding=0.05
)
```

### Animation Events

Flight simulators use animation tags for triggering sounds, effects, and state changes.

| Tool | Description |
|------|-------------|
| `blender_msfs_add_animation_tag` | Add animation event marker |
| `blender_msfs_setup_visibility_animation` | Configure show/hide animation |
| `blender_msfs_configure_animation_loop` | Set loop behavior |
| `blender_msfs_list_animation_tags` | List all animation tags |

**Animation Tag Types:**
- `start` / `end` - Animation boundaries
- `loop_start` / `loop_end` - Loop points
- `sound` / `sound_start` / `sound_stop` - Audio triggers
- `effect` / `effect_start` / `effect_stop` - Visual effect triggers
- `show` / `hide` - Visibility toggles
- `event` - Custom events

**Loop Behaviors:**
- `once` - Play once and stop
- `loop` - Loop continuously
- `ping_pong` - Play forward then reverse
- `hold` - Play once and hold final frame

**Example:**
```python
# Add sound event to animation
blender_msfs_add_animation_tag(
    object_name="Door",
    tag_type="sound",
    frame=1,
    tag_data="door_open.wav"
)

# Configure looping animation
blender_msfs_configure_animation_loop(
    object_name="RotatingBeacon",
    behavior="loop",
    loop_start=1,
    loop_end=60
)
```

### Export

Export tools ensure compatibility with MSFS format requirements.

| Tool | Description |
|------|-------------|
| `blender_msfs_export_model` | Export with LODs, collision, animations |
| `blender_msfs_validate_for_export` | Validate for MSFS compatibility |
| `blender_msfs_get_export_settings` | Get export settings and recommendations |
| `blender_msfs_batch_export_lods` | Batch export LOD hierarchy |

**Example:**
```python
# Validate before export
result = blender_msfs_validate_for_export(object_name="Vehicle")
if result["valid"]:
    # Export complete model
    blender_msfs_export_model(
        filepath="/output/vehicle.glb",
        include_lods=True,
        include_collision=True,
        include_animations=True
    )
```

## Complete Workflow Example

### Creating a Ground Vehicle

```python
# 1. Create base model
blender_object_create(type="cube", name="Vehicle_Body")
blender_object_transform(name="Vehicle_Body", scale=[4, 2, 1.5])
blender_modifier_add(object_name="Vehicle_Body", modifier_type="BEVEL")
blender_modifier_add(object_name="Vehicle_Body", modifier_type="SUBSURF", properties={"levels": 2})

# 2. Set up materials
blender_msfs_setup_material(
    material_name="BodyPaint",
    msfs_type="clear_coat",
    base_color=[0.9, 0.9, 0.1, 1.0],
    metallic=0.1,
    roughness=0.35
)
blender_material_assign(object_name="Vehicle_Body", material_name="BodyPaint")

# 3. Create LOD hierarchy
blender_msfs_create_lod_hierarchy(
    base_object_name="Vehicle_Body",
    lod_count=4,
    auto_decimate=True
)

# 4. Set up collision
blender_msfs_create_collision_box(
    object_name="Vehicle_Body",
    collision_type="collider"
)

# 5. Add door animation
blender_keyframe_insert(object_name="Door", data_path="rotation_euler", frame=1, value=[0, 0, 0])
blender_keyframe_insert(object_name="Door", data_path="rotation_euler", frame=30, value=[0, 0, 1.57])
blender_msfs_add_animation_tag(object_name="Door", tag_type="sound_start", frame=1, tag_data="door_open.wav")
blender_msfs_add_animation_tag(object_name="Door", tag_type="sound_stop", frame=30)

# 6. Validate and export
validation = blender_msfs_validate_for_export()
if validation["valid"]:
    blender_msfs_export_model(
        filepath="/output/vehicle.glb",
        include_lods=True,
        include_collision=True,
        include_animations=True
    )
```

## Best Practices

### Performance Optimization

1. **LODs are mandatory** - Always create at least 3 LOD levels for any visible object
2. **Simplify collision meshes** - Use boxes or convex hulls when possible
3. **Texture sizes** - Max 4096x4096, use power-of-2 dimensions
4. **Vertex count targets**:
   - LOD0: <50,000 vertices for complex objects
   - LOD3: <1,000 vertices

### Material Setup

1. Use MSFS material types for correct rendering
2. Enable day/night cycle for cockpit lights
3. Use windshield type for rain effects on glass
4. Apply tangent normals (not object normals)

### Animation Guidelines

1. Add tags for sound synchronization
2. Use visibility animations for state changes
3. Configure proper loop behavior
4. Test frame ranges before export

### Export Checklist

- [ ] All objects have UV maps
- [ ] Materials assigned to all meshes
- [ ] LODs created and configured
- [ ] Collision meshes added
- [ ] Animations have proper tags
- [ ] Scale applied (no non-unit scale)
- [ ] Validation passes with no errors

## Related External Tools

For complete MSFS development workflows, consider these companion tools:

- **MSFS SDK** - Official Microsoft development kit
- **MSFS Blender Tools** - Asobo's official Blender addon
- **glTF Validator** - Verify export compatibility

## Format Reference

The tools export to glTF 2.0 format with MSFS-specific extensions:

- Custom properties stored in `extras` field
- Material types via `MSFS_material_type` property
- LOD distances via `MSFS_lod_min_distance` / `MSFS_lod_max_distance`
- Collision type via `MSFS_collision_type`
- Animation tags via `MSFS_animation_tags`

All custom properties are preserved during glTF export and recognized by MSFS import tools.
