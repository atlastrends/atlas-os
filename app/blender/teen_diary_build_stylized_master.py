"""Constrói Bela e Maria como personagens 3D infantis originais e estilizados."""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "app" / "assets" / "teen_diary_3d" / "diario_master.blend"


def mat(name, color, roughness=0.72, metallic=0.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return material


SKIN = mat("SKIN_WARM", (0.72, 0.40, 0.28, 1))
SKIN_LIGHT = mat("SKIN_LIGHT", (0.93, 0.62, 0.45, 1))
WHITE = mat("EYE_WHITE", (0.98, 0.98, 0.96, 1))
BROWN = mat("EYE_BROWN", (0.18, 0.08, 0.035, 1), 0.35)
BLACK = mat("PUPIL", (0.01, 0.008, 0.006, 1), 0.25)
MOUTH = mat("MOUTH", (0.28, 0.025, 0.025, 1), 0.45)
HAIR_BELA = mat("HAIR_BELA", (0.16, 0.055, 0.025, 1), 0.45)
HAIR_MARIA = mat("HAIR_MARIA", (0.08, 0.025, 0.012, 1), 0.45)
HOODIE = mat("HOODIE_MUSTARD", (0.85, 0.38, 0.08, 1))
JEANS = mat("JEANS", (0.06, 0.17, 0.38, 1))
MARIA_TOP = mat("MARIA_TOP", (0.80, 0.16, 0.32, 1))
MARIA_OVERALL = mat("MARIA_OVERALL", (0.18, 0.48, 0.78, 1))
SHOE_WHITE = mat("SHOE_WHITE", (0.92, 0.91, 0.88, 1))


def smooth(obj):
    if obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        bevel = obj.modifiers.new("SoftBevel", "BEVEL")
        bevel.width = 0.025
        bevel.segments = 3
    return obj


def sphere(name, location, scale, material, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, location=location)
    obj = smooth(bpy.context.object)
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    if parent:
        obj.parent = parent
    return obj


def capsule(name, location, radius, depth, material, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=28, ring_count=18, location=location)
    obj = smooth(bpy.context.object)
    obj.name = name
    obj.scale = (radius, radius, depth / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    if parent:
        obj.parent = parent
    return obj


def cube(name, location, scale, material, parent=None, bevel=0.08):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    mod = obj.modifiers.new("RoundEdges", "BEVEL")
    mod.width = bevel
    mod.segments = 4
    if parent:
        obj.parent = parent
    return obj


def empty(name, location=(0, 0, 0), parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    if parent:
        obj.parent = parent
    return obj


def eye(prefix, root, x, z, eye_scale):
    eyeball = sphere(
        f"{prefix}_EYE",
        (x, -0.37 * eye_scale, z),
        (0.20 * eye_scale, 0.10 * eye_scale, 0.24 * eye_scale),
        WHITE,
        root,
    )
    iris = sphere(
        f"{prefix}_IRIS",
        (x, -0.465 * eye_scale, z),
        (0.105 * eye_scale, 0.025 * eye_scale, 0.14 * eye_scale),
        BROWN,
        root,
    )
    pupil = sphere(
        f"{prefix}_PUPIL",
        (x, -0.488 * eye_scale, z),
        (0.047 * eye_scale, 0.012 * eye_scale, 0.070 * eye_scale),
        BLACK,
        root,
    )
    highlight = sphere(
        f"{prefix}_HIGHLIGHT",
        (x - 0.025 * eye_scale, -0.504 * eye_scale, z + 0.045 * eye_scale),
        (0.018 * eye_scale,) * 3,
        WHITE,
        root,
    )
    return eyeball, iris, pupil, highlight


def create_character(
    character,
    scale,
    position,
    skin,
    hair_mat,
    top_mat,
    bottom_mat,
    pigtails=False,
):
    root = empty(f"CHAR_{character}", position)
    body_z = 1.15 * scale
    head_z = 2.15 * scale

    cube(f"{character}_TORSO", (0, 0, body_z), (0.42 * scale, 0.25 * scale, 0.55 * scale), top_mat, root, 0.16 * scale)
    capsule(f"{character}_HIPS", (0, 0, 0.72 * scale), 0.37 * scale, 0.48 * scale, bottom_mat, root)
    sphere(f"CHAR_{character}_BODY", (0, 0, head_z), (0.62 * scale, 0.50 * scale, 0.67 * scale), skin, root)

    # Hair cap and rounded locks.
    sphere(f"{character}_HAIR_CAP", (0, 0.10 * scale, head_z + 0.12 * scale), (0.64 * scale, 0.50 * scale, 0.66 * scale), hair_mat, root)
    sphere(f"{character}_FACE_MASK", (0, -0.13 * scale, head_z - 0.02 * scale), (0.56 * scale, 0.43 * scale, 0.58 * scale), skin, root)
    if pigtails:
        for side in (-1, 1):
            sphere(f"{character}_PIGTAIL_{side}", (0.58 * side * scale, 0.05 * scale, head_z), (0.25 * scale, 0.20 * scale, 0.30 * scale), hair_mat, root)
            capsule(f"{character}_BRAID_{side}", (0.66 * side * scale, 0.08 * scale, head_z - 0.35 * scale), 0.16 * scale, 0.52 * scale, hair_mat, root)
    else:
        for side in (-1, 1):
            capsule(f"{character}_HAIR_SIDE_{side}", (0.51 * side * scale, 0.08 * scale, head_z - 0.30 * scale), 0.20 * scale, 0.85 * scale, hair_mat, root)

    eye(f"{character}_L", root, -0.22 * scale, head_z + 0.05 * scale, scale)
    eye(f"{character}_R", root, 0.22 * scale, head_z + 0.05 * scale, scale)
    sphere(f"{character}_NOSE", (0, -0.49 * scale, head_z - 0.08 * scale), (0.055 * scale, 0.035 * scale, 0.060 * scale), skin, root)
    mouth = capsule(f"{character}_MOUTH", (0, -0.505 * scale, head_z - 0.27 * scale), 0.075 * scale, 0.028 * scale, MOUTH, root)
    mouth.scale.x = 1.45

    # Limb pivots make deterministic animation easy.
    for side, sign in (("L", -1), ("R", 1)):
        shoulder = empty(f"{character}_{side}_SHOULDER", (0.49 * sign * scale, -0.01 * scale, 1.42 * scale), root)
        capsule(f"{character}_{side}_UPPER_ARM", (0, 0, -0.30 * scale), 0.12 * scale, 0.62 * scale, skin, shoulder)
        elbow = empty(f"{character}_{side}_ELBOW", (0, 0, -0.60 * scale), shoulder)
        capsule(f"{character}_{side}_FOREARM", (0, 0, -0.27 * scale), 0.105 * scale, 0.55 * scale, skin, elbow)
        hand = sphere(f"{character}_{side}_HAND", (0, 0, -0.58 * scale), (0.14 * scale, 0.11 * scale, 0.17 * scale), skin, elbow)
        hand["hand_side"] = side

        hip = empty(f"{character}_{side}_HIP", (0.22 * sign * scale, 0, 0.70 * scale), root)
        capsule(f"{character}_{side}_THIGH", (0, 0, -0.34 * scale), 0.16 * scale, 0.70 * scale, bottom_mat, hip)
        knee = empty(f"{character}_{side}_KNEE", (0, 0, -0.68 * scale), hip)
        capsule(f"{character}_{side}_SHIN", (0, 0, -0.30 * scale), 0.13 * scale, 0.62 * scale, skin, knee)
        shoe = capsule(f"{character}_{side}_SHOE", (0, -0.09 * scale, -0.65 * scale), 0.16 * scale, 0.25 * scale, SHOE_WHITE, knee)
        shoe.scale.y = 1.65

    root["character_age"] = 13 if character == "ISABELA" else 6
    return root


def create_room(name, wall_color, floor_color, accent):
    collection = bpy.data.collections.new(f"SET_{name}")
    bpy.context.scene.collection.children.link(collection)
    collection.hide_render = True
    collection.hide_viewport = True
    for obj in (
        cube(f"{name}_FLOOR", (0, 1.4, -0.12), (4.8, 4.8, 0.12), floor_color, bevel=0.04),
        cube(f"{name}_BACK", (0, 5.8, 2.4), (4.8, 0.12, 2.5), wall_color, bevel=0.04),
        cube(f"{name}_LEFT", (-4.7, 1.5, 2.4), (0.12, 4.4, 2.5), wall_color, bevel=0.04),
        cube(f"{name}_TABLE", (1.45, 1.0, 0.72), (1.35, 0.65, 0.10), accent, bevel=0.08),
        cube(f"{name}_SHELF", (-2.8, 4.7, 1.1), (0.85, 0.35, 1.1), accent, bevel=0.08),
    ):
        for old in list(obj.users_collection):
            old.objects.unlink(obj)
        collection.objects.link(obj)
    return collection


def camera(name, location, target, lens):
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.object
    cam.name = f"CAM_{name}"
    cam.data.lens = lens
    cam.data.sensor_fit = "VERTICAL"
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    return cam


def create_prop(name, scale, color):
    collection = bpy.data.collections.get("PROPS") or bpy.data.collections.new("PROPS")
    if collection.name not in bpy.context.scene.collection.children:
        try:
            bpy.context.scene.collection.children.link(collection)
        except RuntimeError:
            pass
    obj = cube(f"PROP_{name}", (0, 0, -20), scale, color, bevel=min(scale) * 0.35)
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)
    obj.hide_render = True


def main():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)

    create_character("ISABELA", 0.92, (-0.65, 0, 0), SKIN_LIGHT, HAIR_BELA, HOODIE, JEANS)
    create_character("MARIA", 0.72, (0.65, 0, 0), SKIN_LIGHT, HAIR_MARIA, MARIA_TOP, MARIA_OVERALL, pigtails=True)

    palettes = {
        "BEDROOM": ((0.76, 0.60, 0.72, 1), (0.38, 0.25, 0.32, 1), (0.94, 0.65, 0.35, 1)),
        "KITCHEN": ((0.88, 0.78, 0.62, 1), (0.48, 0.34, 0.25, 1), (0.45, 0.72, 0.75, 1)),
        "LIVING_ROOM": ((0.72, 0.80, 0.86, 1), (0.38, 0.45, 0.53, 1), (0.88, 0.48, 0.30, 1)),
        "BATHROOM": ((0.76, 0.90, 0.93, 1), (0.42, 0.66, 0.70, 1), (0.32, 0.62, 0.72, 1)),
        "CLASSROOM": ((0.88, 0.82, 0.66, 1), (0.42, 0.32, 0.24, 1), (0.30, 0.56, 0.42, 1)),
        "SCHOOL_HALLWAY": ((0.72, 0.78, 0.84, 1), (0.36, 0.42, 0.50, 1), (0.78, 0.36, 0.28, 1)),
        "PLAYGROUND": ((0.48, 0.75, 0.92, 1), (0.35, 0.62, 0.30, 1), (0.94, 0.50, 0.16, 1)),
        "BACKYARD": ((0.55, 0.80, 0.92, 1), (0.30, 0.58, 0.26, 1), (0.72, 0.42, 0.22, 1)),
        "STREET": ((0.55, 0.68, 0.78, 1), (0.25, 0.27, 0.31, 1), (0.84, 0.48, 0.20, 1)),
        "SCHOOL_BUS": ((0.95, 0.70, 0.10, 1), (0.18, 0.18, 0.20, 1), (0.22, 0.38, 0.60, 1)),
    }
    for name, (wall, floor, accent) in palettes.items():
        create_room(name, mat(f"{name}_WALL", wall), mat(f"{name}_FLOOR", floor), mat(f"{name}_ACCENT", accent))

    camera("CLOSE_STATIC", (0, -3.7, 1.55), (0, 0, 1.45), 62)
    camera("MEDIUM_STATIC", (0, -5.2, 1.55), (0, 0, 1.35), 54)
    camera("WIDE_STATIC", (0, -7.2, 1.85), (0, 0.3, 1.25), 48)
    camera("CLOSE_PUSH_IN", (0, -4.1, 1.55), (0, 0, 1.45), 60)
    camera("MEDIUM_PAN", (0, -5.5, 1.65), (0, 0.2, 1.35), 52)
    camera("WIDE_TRACKING", (0, -7.5, 1.95), (0, 0.4, 1.25), 46)

    create_prop("STATIONERY", (0.15, 0.03, 0.22), mat("PROP_BLUE", (0.12, 0.42, 0.88, 1)))
    create_prop("BACKPACK", (0.23, 0.12, 0.30), mat("PROP_PINK", (0.84, 0.18, 0.38, 1)))
    create_prop("HEADPHONES", (0.20, 0.06, 0.20), BLACK)
    create_prop("BOOK", (0.17, 0.025, 0.23), mat("PROP_GREEN", (0.24, 0.68, 0.38, 1)))
    create_prop("TOY", (0.16, 0.16, 0.16), mat("PROP_ORANGE", (0.95, 0.50, 0.12, 1)))
    create_prop("WATER_BOTTLE", (0.075, 0.075, 0.22), mat("PROP_CYAN", (0.20, 0.72, 0.88, 1)))

    world = bpy.data.worlds.new("WORLD_DIARY")
    world.color = (0.055, 0.07, 0.10)
    bpy.context.scene.world = world
    bpy.ops.object.light_add(type="AREA", location=(2.5, -3.0, 5.5))
    bpy.context.object.name = "LIGHT_KEY"
    bpy.context.object.data.energy = 1100
    bpy.context.object.data.size = 5
    bpy.ops.object.light_add(type="AREA", location=(-3.0, -1.0, 3.0))
    bpy.context.object.name = "LIGHT_FILL"
    bpy.context.object.data.energy = 650
    bpy.context.object.data.size = 4

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    print(f"ATLAS_STYLIZED_MASTER_WRITTEN={OUTPUT}")


if __name__ == "__main__":
    main()
