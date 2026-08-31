"""Renderiza uma thumbnail de um rig oficial Blender Studio."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main():
    args = parse()
    token = args.character.lower()
    meshes = [
        obj for obj in bpy.data.objects
        if obj.type == "MESH"
        and token in obj.name.lower()
        and not obj.hide_render
    ]
    if not meshes:
        meshes = [
            obj for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.name.startswith(("GEO-", "CUR-"))
            and not obj.hide_render
        ]
    if not meshes:
        raise RuntimeError(f"nenhum mesh encontrado para {token}")

    points = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes
        for corner in obj.bound_box
    ]
    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    center = (minimum + maximum) / 2
    height = maximum.z - minimum.z

    camera_data = bpy.data.cameras.new("PreviewCameraData")
    camera = bpy.data.objects.new("PreviewCamera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = (
        center.x,
        center.y - height * 2.8,
        center.z + height * 0.05,
    )
    camera.data.lens = 58
    camera.data.sensor_fit = "VERTICAL"
    camera.rotation_euler = (
        center - camera.location
    ).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera

    for index, (location, energy, size) in enumerate((
        ((center.x + height, center.y - height, center.z + height), 1300, 5),
        ((center.x - height, center.y, center.z + height * 0.5), 650, 4),
    )):
        light_data = bpy.data.lights.new(f"PreviewLightData{index}", "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = size
        light = bpy.data.objects.new(f"PreviewLight{index}", light_data)
        light.location = location
        bpy.context.scene.collection.objects.link(light)

    world = bpy.data.worlds.get("PreviewWorld") or bpy.data.worlds.new("PreviewWorld")
    world.color = (0.045, 0.055, 0.075)
    scene = bpy.context.scene
    if scene.render.is_movie_format:
        old_scene = scene
        scene = bpy.data.scenes.new("PreviewScene")
        for obj in old_scene.objects:
            if obj.name not in scene.collection.objects:
                try:
                    scene.collection.objects.link(obj)
                except RuntimeError:
                    pass
        scene.camera = camera
    scene.world = world
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 450
    scene.render.resolution_y = 600
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(Path(args.output))
    bpy.ops.render.render(write_still=True, scene=scene.name)


if __name__ == "__main__":
    main()
