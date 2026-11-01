"""Build the fixture .blend the harness reloads before every case."""

import bpy


def build(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 10

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
    bpy.context.active_object.name = "Sphere"

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
    bpy.context.active_object.name = "Camera"
    bpy.ops.object.light_add(type="POINT", location=(0, 0, 6))
    bpy.context.active_object.name = "Light"
    bpy.ops.object.empty_add(location=(0, -4, 0))
    bpy.context.active_object.name = "Empty"

    scene.collection.children.link(bpy.data.collections.new("Collection"))
    bpy.data.images.new("Image", 16, 16).use_fake_user = True

    bpy.ops.wm.save_as_mainfile(filepath=str(path))
