# MSFS 2020/2024 Content Creation Roadmap

This document outlines planned enhancements for Microsoft Flight Simulator content creation, specifically for ground service vehicles and equipment (GSX-like functionality).

## Current Capabilities

The MCP Blender server already supports:

- **Modeling**: Create and manipulate 3D objects, apply modifiers (subdivision, bevel, mirror, array, boolean)
- **Materials**: PBR materials via Principled BSDF (metallic, roughness, normal maps)
- **Texturing**: Image texture support with UV mapping
- **Animation**: Keyframe animation for location, rotation, scale
- **Export**: glTF/GLB (MSFS native), FBX, OBJ formats

## Planned MSFS-Specific Tools

### Phase 1: LOD System (High Priority)

```
blender_msfs_lod_create        - Create LOD hierarchy from base mesh
blender_msfs_lod_setup         - Configure LOD distances
blender_msfs_lod_decimate      - Auto-generate lower LODs with decimation
blender_msfs_lod_export        - Export all LODs with MSFS naming convention
```

**LOD Requirements for MSFS:**
- LOD0: Full detail (0-50m)
- LOD1: Medium detail (50-200m)
- LOD2: Low detail (200-500m)
- LOD3: Minimal detail (500m+)

### Phase 2: MSFS Material Extensions (High Priority)

```
blender_msfs_material_setup    - Configure MSFS-specific material properties
blender_msfs_material_glass    - Set up glass/windshield materials
blender_msfs_material_emissive - Configure emissive/light materials
blender_msfs_material_detail   - Add detail/decal textures
```

**MSFS Material Properties:**
- `ASOBO_material_windshield` - Windshield rain effects
- `ASOBO_material_clear_coat` - Car paint, glossy surfaces
- `ASOBO_material_anisotropic` - Brushed metal
- `ASOBO_material_parallax_window` - Fake interior depth
- `ASOBO_material_fake_terrain` - Ground shadows

### Phase 3: Collision & Physics (High Priority)

```
blender_msfs_collision_create  - Create collision mesh from object
blender_msfs_collision_box     - Add box collision primitive
blender_msfs_collision_convex  - Generate convex hull collision
blender_msfs_road_collision    - Set up road/ground collision tags
```

**Collision Types:**
- `فІЗИКА` (Physics) - Physical collision
- `ROAD` - Ground vehicle pathfinding
- `WATER` - Water interaction

### Phase 4: Animation Tools (Medium Priority)

```
blender_msfs_anim_tag          - Add MSFS animation tag/event
blender_msfs_anim_visibility   - Set up visibility animations
blender_msfs_anim_loop         - Configure looping animations
blender_msfs_anim_export       - Export with MSFS animation metadata
```

**Ground Service Animations:**
- Door open/close sequences
- Conveyor belt loops
- Lift platform raise/lower
- Vehicle steering
- Light on/off states

### Phase 5: Batch Export & SDK Integration (Medium Priority)

```
blender_msfs_export_vehicle    - Full vehicle export (mesh + LODs + collision + anims)
blender_msfs_export_package    - Create complete MSFS package structure
blender_msfs_xml_generate      - Generate model behavior XML
```

## Ground Service Vehicle Workflow

### 1. Modeling the Vehicle

```
# Create base vehicle
blender_object_create(type="cube", name="FuelTruck_Body")
blender_object_transform(name="FuelTruck_Body", scale=[4, 2, 1.5])

# Add details with modifiers
blender_modifier_add(object_name="FuelTruck_Body", modifier_type="BEVEL")
blender_modifier_add(object_name="FuelTruck_Body", modifier_type="SUBSURF", params={"levels": 2})
```

### 2. Setting Up Materials

```
# Create PBR material
blender_material_create(name="FuelTruck_Paint")
blender_material_set_principled(
    material_name="FuelTruck_Paint",
    base_color=[0.8, 0.2, 0.1, 1.0],  # Red
    metallic=0.1,
    roughness=0.4
)
blender_material_add_texture(material_name="FuelTruck_Paint", texture_path="/textures/truck_diffuse.png")
```

### 3. Creating Animations

```
# Animate fuel hose arm
blender_keyframe_insert(object_name="FuelArm", data_path="rotation_euler", frame=1)
blender_object_transform(name="FuelArm", rotation=[0, 0, 45])
blender_keyframe_insert(object_name="FuelArm", data_path="rotation_euler", frame=60)
```

### 4. Generating LODs (Planned)

```
# Auto-generate LODs
blender_msfs_lod_create(base_object="FuelTruck", lod_count=4)
blender_msfs_lod_decimate(object_name="FuelTruck_LOD1", ratio=0.5)
blender_msfs_lod_decimate(object_name="FuelTruck_LOD2", ratio=0.25)
blender_msfs_lod_decimate(object_name="FuelTruck_LOD3", ratio=0.1)
```

### 5. Export for MSFS (Planned)

```
# Export complete vehicle package
blender_msfs_export_vehicle(
    base_object="FuelTruck",
    output_dir="/path/to/msfs/package/",
    include_lods=True,
    include_collision=True,
    include_animations=True
)
```

## Integration with Ground Master

For your GSX-like "Ground Master" application, the MCP Blender tools would handle:

1. **Asset Creation Pipeline**
   - Model ground vehicles (tugs, fuel trucks, baggage carts, stairs, etc.)
   - Create animations for vehicle operations
   - Generate LODs for performance
   - Export glTF with MSFS extensions

2. **Batch Processing**
   - AI-assisted modeling via prompts
   - Automated LOD generation
   - Consistent material setup across fleet

3. **Iteration Workflow**
   - Quick modifications via Claude Code
   - Test renders before export
   - Animation preview and adjustment

## Blender Addons to Consider

For MSFS content, these Blender addons are commonly used:

1. **MSFS Blender Tools** (FlyByWire/Asobo) - Official SDK integration
2. **Blender2MSFS** - Community glTF exporter with MSFS extensions
3. **glTF Validator** - Verify export compatibility

The MCP server could potentially integrate with these addons for full MSFS workflow support.

## Next Steps

1. Implement LOD generation tools
2. Add MSFS material extension support in glTF export
3. Create collision mesh tools
4. Add animation tag/event system
5. Build batch export for complete vehicle packages

---

*This roadmap is for the MCP Blender integration with Ground Master framework.*
