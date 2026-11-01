"""Build the fixture .blend the harness reloads before every case."""

import json

import bpy


def build(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 10
    _make_renders_cheap(scene)

    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = bpy.context.active_object
    cube.name = "Cube"
    cube.data.name = "Cube"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    mat = bpy.data.materials.new("Material")
    mat.use_nodes = True
    cube.data.materials.append(mat)

    bpy.ops.mesh.primitive_uv_sphere_add(location=(4, 0, 0))
    sphere = bpy.context.active_object
    sphere.name = "Sphere"

    bpy.ops.curve.primitive_bezier_curve_add(location=(0, 4, 0))
    bpy.context.active_object.name = "Curve"

    bpy.ops.object.armature_add(location=(-4, 0, 0))
    arm = bpy.context.active_object
    arm.name = "Armature"
    bpy.ops.object.mode_set(mode="EDIT")
    bone = arm.data.edit_bones[0]
    bone.name = "Bone"
    child = arm.data.edit_bones.new("Bone.001")
    child.head = bone.tail
    child.tail = (bone.tail[0], bone.tail[1], bone.tail[2] + 1)
    child.parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.camera_add(location=(0, -8, 4))
    cam = bpy.context.active_object
    cam.name = "Camera"
    scene.camera = cam
    bpy.ops.object.light_add(type="POINT", location=(0, 0, 6))
    bpy.context.active_object.name = "Light"
    bpy.ops.object.empty_add(location=(0, -4, 0))
    bpy.context.active_object.name = "Empty"

    _add_lods()
    _add_state(scene, cube, sphere, arm)

    scene.collection.children.link(bpy.data.collections.new("Collection"))
    bpy.data.images.new("Image", 16, 16).use_fake_user = True

    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def _make_renders_cheap(scene):
    """The harness tests handlers, not render speed: keep every render tiny."""
    scene.render.resolution_x = 64
    scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    if hasattr(scene, "cycles"):
        scene.cycles.samples = 1
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 1


def _add_lods():
    """A two-level LOD set, Hull_LOD0 and Hull_LOD1, for the msfs_*_lod* tools."""
    for level in range(2):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(8, 4 * level, 0))
        bpy.context.active_object.name = f"Hull_LOD{level}"


def _add_state(scene, cube, sphere, arm):
    """State that tools need to find before they can act: modifiers, keys, poses."""
    group = bpy.data.node_groups.new("GeoGroup", "GeometryNodeTree")
    group.use_fake_user = True
    group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    node_in = group.nodes.new("NodeGroupInput")
    node_out = group.nodes.new("NodeGroupOutput")
    group.links.new(node_in.outputs[0], node_out.inputs[0])
    sphere.modifiers.new("Bevel", "BEVEL")
    sphere.modifiers.new("GeometryNodes", "NODES").node_group = group
    multires = sphere.modifiers.new("Multires", "MULTIRES")
    bpy.ops.object.select_all(action="DESELECT")
    sphere.select_set(True)
    bpy.context.view_layer.objects.active = sphere
    bpy.ops.object.multires_subdivide(modifier=multires.name, mode="CATMULL_CLARK")

    cube.location = (0, 0, 0)
    cube.keyframe_insert("location", frame=1)
    cube.location = (0, 0, 1)
    cube.keyframe_insert("location", frame=5)
    cube.location = (0, 0, 0)
    cube.animation_data.action.name = "CubeAction"

    pose = {
        b.name: {
            "location": [0.0, 0.0, 0.0],
            "rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "rotation_mode": "QUATERNION",
            "scale": [1.0, 1.0, 1.0],
        }
        for b in arm.pose.bones
    }
    arm["_pose_lib_Pose"] = json.dumps(pose)
    arm["_pose_lib_index"] = json.dumps(["Pose"])

    bpy.ops.rigidbody.world_add()
    sphere.select_set(True)
    bpy.context.view_layer.objects.active = sphere
    bpy.ops.rigidbody.object_add()
