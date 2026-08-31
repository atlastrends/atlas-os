"""Renderiza thumbnails dos personagens GLB prontos para escolha."""

from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools" / "kenney_mini-characters" / "Models" / "GLB format"
OUTPUT = ROOT / "app" / "assets" / "teen_diary_3d" / "model_choices" / "kenney"


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.materials, bpy.data.images):
        for item in list(block):
            block.remove(item)


def bounds(objects):
    points = [
        obj.matrix_world @ Vector(corner)
        for obj in objects
        if obj.type == "MESH"
        for corner in obj.bound_box
    ]
    minimum = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    maximum = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return minimum, maximum


def render(path: Path, output: Path):
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = list(bpy.context.scene.objects)
    minimum, maximum = bounds(objects)
    center = (minimum + maximum) / 2
    height = maximum.z - minimum.z

    bpy.ops.object.camera_add(location=(center.x, center.y - height * 2.8, center.z + height * 0.05))
    camera = bpy.context.object
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 55
    camera.data.sensor_fit = "VERTICAL"
    bpy.context.scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(center.x + 2, center.y - 3, center.z + 3))
    bpy.context.object.data.energy = 900
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 4
    bpy.ops.object.light_add(type="AREA", location=(center.x - 3, center.y, center.z + 1))
    bpy.context.object.data.energy = 450
    bpy.context.object.data.size = 3

    world = bpy.data.worlds.new("ChoiceWorld")
    world.color = (0.035, 0.04, 0.055)
    scene = bpy.context.scene
    scene.world = world
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 450
    scene.render.resolution_y = 600
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)


OUTPUT.mkdir(parents=True, exist_ok=True)
for letter in "abcdef":
    render(
        SOURCE / f"character-female-{letter}.glb",
        OUTPUT / f"female-{letter.upper()}.png",
    )
