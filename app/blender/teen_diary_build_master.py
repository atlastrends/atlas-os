"""Constrói o arquivo mestre 3D inicial do Diário da Bela."""

from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "app" / "assets" / "teen_diary_3d" / "diario_master.blend"


def dynamic_import(package_suffix: str, key: str):
    for module_name in sys.modules:
        if module_name.endswith(package_suffix):
            module = importlib.import_module(module_name)
            if hasattr(module, key):
                return getattr(module, key)
    raise RuntimeError(f"MPFB module not loaded: {package_suffix}.{key}")


HumanService = dynamic_import("mpfb.services.humanservice", "HumanService")
TargetService = dynamic_import("mpfb.services.targetservice", "TargetService")
AssetService = dynamic_import("mpfb.services.assetservice", "AssetService")
LocationService = dynamic_import(
    "mpfb.services.locationservice", "LocationService"
)
HumanProps = dynamic_import(
    "mpfb.entities.objectproperties", "HumanObjectProperties"
)


def asset(subdir: str, name: str) -> str:
    path = AssetService.find_asset_absolute_path(name, asset_subdir=subdir)
    if not path:
        raise RuntimeError(f"MPFB asset ausente: {subdir}/{name}")
    return path


def create_character(
    character: str,
    age: float,
    height: float,
    hair: str,
    clothes: str,
    location: tuple[float, float, float],
) -> bpy.types.Object:
    body = HumanService.create_human()
    body.name = f"CHAR_{character}_BODY"
    values = {
        "gender": 0.0,
        "age": age,
        "height": height,
        "weight": 0.42,
        "muscle": 0.35,
        "proportions": 0.48,
        "african": 0.12,
        "asian": 0.28,
        "caucasian": 0.60,
    }
    for key, value in values.items():
        HumanProps.set_value(key, value, entity_reference=body)
    TargetService.reapply_macro_details(body)

    targets_root = LocationService.get_mpfb_data("targets")
    cartoon_targets = {
        "l-eye-scale-incr.target.gz": ("eyes", 0.65),
        "r-eye-scale-incr.target.gz": ("eyes", 0.65),
        "l-eye-height2-incr.target.gz": ("eyes", 0.25),
        "r-eye-height2-incr.target.gz": ("eyes", 0.25),
        "head-round.target.gz": ("head", 0.55),
        "head-scale-horiz-incr.target.gz": ("head", 0.18),
        "head-scale-vert-incr.target.gz": ("head", 0.12),
        "nose-volume-decr.target.gz": ("nose", 0.60),
        "nose-scale-depth-decr.target.gz": ("nose", 0.45),
        "nose-scale-horiz-decr.target.gz": ("nose", 0.30),
        "l-cheek-volume-incr.target.gz": ("cheek", 0.20),
        "r-cheek-volume-incr.target.gz": ("cheek", 0.20),
        "chin-height-decr.target.gz": ("chin", 0.25),
        "chin-width-decr.target.gz": ("chin", 0.18),
    }
    for filename, (subdir, weight) in cartoon_targets.items():
        TargetService.load_target(
            body,
            os.path.join(targets_root, subdir, filename),
            weight=weight,
        )

    HumanService.set_character_skin(
        asset("skins", "young_caucasian_female2.mhmat"),
        body,
        skin_type="GAMEENGINE",
    )
    rig = HumanService.add_builtin_rig(body, "cmu_mb")
    rig.name = f"CHAR_{character}"
    for subdir, filename, asset_type in (
        ("eyes", "low-poly.mhclo", "Eyes"),
        ("eyebrows", "eyebrow001.mhclo", "Eyebrows"),
        ("eyelashes", "eyelashes01.mhclo", "Eyelashes"),
        ("tongue", "tongue01.mhclo", "Tongue"),
        ("teeth", "teeth_base.mhclo", "Teeth"),
        ("hair", hair, "Hair"),
        ("clothes", clothes, "Clothes"),
        ("clothes", "shoes01.mhclo", "Clothes"),
    ):
        HumanService.add_mhclo_asset(
            asset(subdir, filename),
            body,
            asset_type=asset_type,
            material_type="GAMEENGINE",
        )
    rig.location = location
    return rig


def material(name: str, color: tuple[float, float, float, float]):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.75
    return mat


def cube(
    name: str,
    location,
    scale,
    color,
    collection: bpy.types.Collection,
    bevel: float = 0.08,
):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        modifier = obj.modifiers.new("SoftEdges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    obj.data.materials.append(material(f"MAT_{name}", color))
    for old_collection in list(obj.users_collection):
        old_collection.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def create_set(name: str, palette: tuple) -> bpy.types.Collection:
    collection = bpy.data.collections.new(f"SET_{name}")
    bpy.context.scene.collection.children.link(collection)
    collection.hide_render = True
    collection.hide_viewport = True
    floor, wall, accent = palette
    cube(f"{name}_FLOOR", (0, 0, -0.15), (5, 5, 0.15), floor, collection)
    cube(f"{name}_BACK", (0, 4.9, 2.5), (5, 0.12, 2.5), wall, collection)
    cube(f"{name}_LEFT", (-4.9, 0, 2.5), (0.12, 5, 2.5), wall, collection)
    cube(f"{name}_TABLE", (0.8, 1.3, 0.75), (1.6, 0.8, 0.12), accent, collection)
    cube(f"{name}_CABINET", (-2.6, 3.8, 1.2), (1.0, 0.45, 1.2), accent, collection)
    return collection


def create_camera(name: str, location, lens: float):
    bpy.ops.object.camera_add(location=location)
    camera = bpy.context.object
    camera.name = f"CAM_{name}"
    camera.data.lens = lens
    camera.data.sensor_fit = "VERTICAL"
    direction = Vector((0, 0, 1.25)) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return camera


def create_action(
    rig: bpy.types.Object,
    name: str,
    frames: dict[int, dict[str, tuple[float, float, float]]],
):
    action = bpy.data.actions.new(f"ACT_{name.upper()}")
    action.use_fake_user = True
    if rig.animation_data is None:
        rig.animation_data_create()
    rig.animation_data.action = action
    for bone in rig.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
    for frame, pose in frames.items():
        for bone_name, degrees in pose.items():
            bone = rig.pose.bones.get(bone_name)
            if not bone:
                continue
            bone.rotation_euler = tuple(math.radians(v) for v in degrees)
            bone.keyframe_insert("rotation_euler", frame=frame, group=bone_name)
    return action


def create_actions(rig: bpy.types.Object) -> None:
    neutral = {
        1: {"Head": (0, 0, 0), "LeftArm": (0, 0, -10), "RightArm": (0, 0, 10)},
        48: {"Head": (0, 0, 3), "LeftArm": (0, 0, -14), "RightArm": (0, 0, 14)},
        96: {"Head": (0, 0, 0), "LeftArm": (0, 0, -10), "RightArm": (0, 0, 10)},
    }
    stretch = {
        1: {"LeftArm": (0, 0, -15), "RightArm": (0, 0, 15)},
        48: {"LeftArm": (0, 0, -155), "RightArm": (0, 0, 155), "Head": (-8, 0, 0)},
        96: {"LeftArm": (0, 0, -15), "RightArm": (0, 0, 15)},
    }
    point = {
        1: {"RightArm": (0, 0, 20), "RightForeArm": (0, 0, 0)},
        48: {"RightArm": (0, -80, 65), "RightForeArm": (0, 0, -20)},
        96: {"RightArm": (0, 0, 20), "RightForeArm": (0, 0, 0)},
    }
    bend = {
        1: {"Spine": (0, 0, 0), "LeftUpLeg": (0, 0, 0), "RightUpLeg": (0, 0, 0)},
        48: {"Spine": (45, 0, 0), "LeftUpLeg": (-25, 0, 0), "RightUpLeg": (-25, 0, 0)},
        96: {"Spine": (0, 0, 0), "LeftUpLeg": (0, 0, 0), "RightUpLeg": (0, 0, 0)},
    }
    sit = {
        1: {"LeftUpLeg": (-75, 0, 0), "RightUpLeg": (-75, 0, 0), "LeftLeg": (75, 0, 0), "RightLeg": (75, 0, 0)},
        96: {"LeftUpLeg": (-75, 0, 0), "RightUpLeg": (-75, 0, 0), "LeftLeg": (75, 0, 0), "RightLeg": (75, 0, 0)},
    }
    action_templates = {
        "wake_stretch": stretch,
        "talk_idle": neutral,
        "look_around": neutral,
        "walk": neutral,
        "run": neutral,
        "sit": sit,
        "stand": neutral,
        "point": point,
        "pick_up": bend,
        "hold_object": neutral,
        "put_down": bend,
        "eat": neutral,
        "laugh": neutral,
        "giggle": neutral,
        "sigh": neutral,
        "eye_roll": neutral,
        "cross_arms": neutral,
        "shrug": neutral,
        "wave": point,
        "hug": neutral,
        "look_at_phone": neutral,
        "open_door": point,
        "close_door": point,
        "draw": neutral,
        "write_notes": neutral,
        "show_product": point,
        "pack_backpack": bend,
        "wear_backpack": neutral,
        "put_on_headphones": stretch,
        "listen_music": neutral,
        "read_book": neutral,
        "hold_book": neutral,
        "play_with_toy": neutral,
        "hold_toy": neutral,
        "drink_water": neutral,
        "hold_bottle": neutral,
    }
    for name, frames in action_templates.items():
        create_action(rig, name, frames)


def create_prop(name: str, scale, color):
    collection = bpy.data.collections.get("PROPS")
    if not collection:
        collection = bpy.data.collections.new("PROPS")
        bpy.context.scene.collection.children.link(collection)
    prop = cube(f"PROP_{name}", (0, 0, -20), scale, color, collection, 0.05)
    prop.hide_render = True
    return prop


def main():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)

    bela = create_character(
        "ISABELA", 0.255, 0.38, "long01.mhclo",
        "female_sportsuit01.mhclo", (-0.8, 0, 0),
    )
    create_character(
        "MARIA", 0.13, 0.20, "braid01.mhclo",
        "female_casualsuit01.mhclo", (0.8, 0, 0),
    )
    create_actions(bela)

    palettes = {
        "BEDROOM": ((0.55, 0.35, 0.48, 1), (0.75, 0.55, 0.70, 1), (0.95, 0.72, 0.45, 1)),
        "KITCHEN": ((0.55, 0.42, 0.30, 1), (0.88, 0.76, 0.58, 1), (0.55, 0.75, 0.78, 1)),
        "LIVING_ROOM": ((0.48, 0.55, 0.62, 1), (0.76, 0.82, 0.86, 1), (0.92, 0.58, 0.38, 1)),
        "BATHROOM": ((0.55, 0.72, 0.76, 1), (0.80, 0.92, 0.94, 1), (0.38, 0.68, 0.76, 1)),
        "CLASSROOM": ((0.48, 0.40, 0.30, 1), (0.88, 0.82, 0.66, 1), (0.34, 0.62, 0.48, 1)),
        "SCHOOL_HALLWAY": ((0.40, 0.46, 0.55, 1), (0.72, 0.78, 0.84, 1), (0.82, 0.45, 0.38, 1)),
        "PLAYGROUND": ((0.42, 0.68, 0.38, 1), (0.48, 0.75, 0.92, 1), (0.94, 0.55, 0.22, 1)),
        "BACKYARD": ((0.38, 0.65, 0.32, 1), (0.55, 0.80, 0.92, 1), (0.76, 0.48, 0.28, 1)),
        "STREET": ((0.30, 0.32, 0.36, 1), (0.55, 0.68, 0.78, 1), (0.86, 0.55, 0.24, 1)),
        "SCHOOL_BUS": ((0.22, 0.22, 0.24, 1), (0.96, 0.72, 0.10, 1), (0.24, 0.42, 0.65, 1)),
    }
    for name, palette in palettes.items():
        create_set(name, palette)

    create_camera("CLOSE_STATIC", (0, -2.6, 1.50), 58)
    create_camera("MEDIUM_STATIC", (0, -3.8, 1.48), 52)
    create_camera("WIDE_STATIC", (0, -5.7, 1.75), 45)
    create_camera("CLOSE_PUSH_IN", (0, -3.0, 1.50), 56)
    create_camera("MEDIUM_PAN", (0, -4.1, 1.55), 50)
    create_camera("WIDE_TRACKING", (0, -6.0, 1.85), 43)

    create_prop("STATIONERY", (0.14, 0.018, 0.20), (0.20, 0.45, 0.90, 1))
    create_prop("BACKPACK", (0.22, 0.10, 0.30), (0.85, 0.28, 0.48, 1))
    create_prop("HEADPHONES", (0.18, 0.05, 0.18), (0.20, 0.20, 0.24, 1))
    create_prop("BOOK", (0.16, 0.025, 0.22), (0.35, 0.70, 0.42, 1))
    create_prop("TOY", (0.16, 0.16, 0.16), (0.94, 0.55, 0.18, 1))
    create_prop("WATER_BOTTLE", (0.07, 0.07, 0.20), (0.30, 0.72, 0.88, 1))

    world = bpy.data.worlds.new("WORLD_DIARY")
    world.color = (0.06, 0.08, 0.12)
    bpy.context.scene.world = world
    bpy.ops.object.light_add(type="AREA", location=(2, -3, 5))
    key = bpy.context.object
    key.name = "LIGHT_KEY"
    key.data.energy = 1300
    key.data.shape = "DISK"
    key.data.size = 5
    bpy.ops.object.light_add(type="AREA", location=(-3, 1, 3))
    fill = bpy.context.object
    fill.name = "LIGHT_FILL"
    fill.data.energy = 700
    fill.data.size = 4

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    print(f"ATLAS_DIARY_MASTER_WRITTEN={OUTPUT}")


if __name__ == "__main__":
    main()
