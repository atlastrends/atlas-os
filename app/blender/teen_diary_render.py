"""Executado pelo Blender em modo background para renderizar um shot."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


REQUIRED_CHARACTERS = {"CHAR_ISABELA", "CHAR_MARIA"}
REQUIRED_LOCATIONS = {
    "SET_BEDROOM", "SET_KITCHEN", "SET_LIVING_ROOM", "SET_BATHROOM",
    "SET_CLASSROOM", "SET_SCHOOL_HALLWAY", "SET_PLAYGROUND",
    "SET_BACKYARD", "SET_STREET", "SET_SCHOOL_BUS",
}
REQUIRED_CAMERAS = {
    "CAM_CLOSE_STATIC", "CAM_MEDIUM_STATIC", "CAM_WIDE_STATIC",
    "CAM_CLOSE_PUSH_IN", "CAM_MEDIUM_PAN", "CAM_WIDE_TRACKING",
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--shot")
    parser.add_argument("--output-dir")
    parser.add_argument("--resume-frame", type=int, default=1)
    return parser.parse_args(argv)


def require_names(collection, names: set[str], kind: str) -> None:
    missing = sorted(name for name in names if collection.get(name) is None)
    if missing:
        raise RuntimeError(f"{kind} ausentes no master blend: {missing}")


def validate_master() -> None:
    require_names(bpy.data.objects, REQUIRED_CHARACTERS, "personagens")
    require_names(bpy.data.collections, REQUIRED_LOCATIONS, "cenarios")
    require_names(bpy.data.objects, REQUIRED_CAMERAS, "cameras")
    if bpy.data.worlds.get("WORLD_DIARY") is None:
        raise RuntimeError("world ausente: WORLD_DIARY")


def set_visible_collection(active_name: str) -> None:
    for name in REQUIRED_LOCATIONS:
        collection = bpy.data.collections[name]
        visible = name == active_name
        collection.hide_render = not visible
        collection.hide_viewport = not visible


def set_character(
    character_id: str,
    action_id: str,
    emotion_id: str,
    visible_characters: list[str],
) -> bpy.types.Object:
    for candidate in ("ISABELA", "MARIA"):
        collection = bpy.data.collections.get(
            f"CHARACTER_COLLECTION_{candidate}"
        )
        if collection:
            visible = candidate.lower() in visible_characters
            collection.hide_render = not visible
            collection.hide_viewport = not visible
    for obj in bpy.data.objects:
        tagged = obj.get("atlas_character")
        if tagged in ("isabela", "maria"):
            visible = tagged in visible_characters
            if obj.type in ("MESH", "CURVE"):
                visible = visible and obj.get(
                    "atlas_render_geometry", False
                )
            obj.hide_render = not visible
            obj.hide_viewport = not visible
    for candidate in ("ISABELA", "MARIA"):
        visible = candidate.lower() in visible_characters
        obj = bpy.data.objects.get(f"CHAR_{candidate}")
        if obj:
            obj.hide_render = not visible
            obj.hide_viewport = not visible

    actor_name = "CHAR_ISABELA" if character_id == "isabela" else "CHAR_MARIA"
    actor = bpy.data.objects[actor_name]
    for secondary_id in visible_characters:
        if secondary_id == character_id:
            continue
        secondary_name = (
            "CHAR_ISABELA"
            if secondary_id == "isabela"
            else "CHAR_MARIA"
        )
        secondary = bpy.data.objects.get(secondary_name)
        if not secondary:
            continue
        secondary.location.x = (
            -0.65 if secondary_id == "isabela" else 0.65
        )
        if secondary.type == "ARMATURE":
            animate_cloudrig(secondary, "talk_idle")
        else:
            animate_stylized_character(secondary_name, "talk_idle")
    if len(visible_characters) == 1:
        actor.location.x = 0.0
    else:
        actor.location.x = -0.65 if character_id == "isabela" else 0.65
    if actor.type == "ARMATURE":
        action = bpy.data.actions.get(f"ACT_{action_id.upper()}")
        if action is not None:
            if actor.animation_data is None:
                actor.animation_data_create()
            actor.animation_data.action = action
        else:
            animate_cloudrig(actor, action_id)
    else:
        animate_stylized_character(actor_name, action_id)

    body = bpy.data.objects.get(f"{actor_name}_BODY")
    if body and body.data and getattr(body.data, "shape_keys", None):
        for key in body.data.shape_keys.key_blocks:
            if key.name.startswith("EMO_"):
                key.value = 0.0
        emotion = body.data.shape_keys.key_blocks.get(
            f"EMO_{emotion_id.upper()}"
        )
        if emotion:
            emotion.value = 1.0
    return actor


def _part(actor_name: str, suffix: str):
    return bpy.data.objects.get(f"{actor_name.removeprefix('CHAR_')}_{suffix}")


def _key_rotation(obj, frame: int, degrees):
    if not obj:
        return
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = tuple(math.radians(value) for value in degrees)
    obj.keyframe_insert("rotation_euler", frame=frame)


def _key_location(obj, frame: int, location):
    if not obj:
        return
    obj.location = location
    obj.keyframe_insert("location", frame=frame)


def _key_pose_position(bone, frame: int, position):
    if not bone:
        return
    matrix = bone.matrix.copy()
    matrix.translation = Vector(position)
    bone.matrix = matrix
    bone.keyframe_insert("location", frame=frame)


def animate_stylized_character(actor_name: str, action_id: str) -> None:
    """Biblioteca procedural de gestos para os personagens originais."""
    prefix = actor_name.removeprefix("CHAR_")
    actor = bpy.data.objects[actor_name]
    actor.animation_data_clear()
    for child in actor.children_recursive:
        child.animation_data_clear()

    l_shoulder = _part(actor_name, "L_SHOULDER")
    r_shoulder = _part(actor_name, "R_SHOULDER")
    l_elbow = _part(actor_name, "L_ELBOW")
    r_elbow = _part(actor_name, "R_ELBOW")
    l_hip = _part(actor_name, "L_HIP")
    r_hip = _part(actor_name, "R_HIP")
    l_knee = _part(actor_name, "L_KNEE")
    r_knee = _part(actor_name, "R_KNEE")
    mouth = bpy.data.objects.get(f"{prefix}_MOUTH")
    frames = (1, 48, 96)

    # Neutral breathing and alternating mouth movement.
    initial = actor.location.copy()
    for frame, dz in zip(frames, (0.0, 0.025, 0.0)):
        _key_location(actor, frame, (initial.x, initial.y, initial.z + dz))
    if mouth:
        for frame, scale_z in ((1, 1.0), (16, 2.2), (30, 0.8), (48, 2.0), (70, 0.7), (96, 1.0)):
            mouth.scale.z = scale_z
            mouth.keyframe_insert("scale", frame=frame)

    if action_id == "wake_stretch":
        for arm, sign in ((l_shoulder, -1), (r_shoulder, 1)):
            _key_rotation(arm, 1, (0, 0, sign * 12))
            _key_rotation(arm, 48, (0, -12, sign * 155))
            _key_rotation(arm, 96, (0, 0, sign * 12))
    elif action_id in {"point", "show_product", "wave", "open_door", "close_door"}:
        _key_rotation(r_shoulder, 1, (0, 0, 12))
        _key_rotation(r_shoulder, 40, (-20, -55, 75))
        _key_rotation(r_shoulder, 96, (0, 0, 12))
        _key_rotation(r_elbow, 40, (0, 0, -35))
    elif action_id in {"pick_up", "put_down", "pack_backpack"}:
        for hip in (l_hip, r_hip):
            _key_rotation(hip, 1, (0, 0, 0))
            _key_rotation(hip, 48, (-28, 0, 0))
            _key_rotation(hip, 96, (0, 0, 0))
        actor.rotation_euler = (0, 0, 0)
        actor.keyframe_insert("rotation_euler", frame=1)
        actor.rotation_euler.x = math.radians(28)
        actor.keyframe_insert("rotation_euler", frame=48)
        actor.rotation_euler.x = 0
        actor.keyframe_insert("rotation_euler", frame=96)
    elif action_id == "sit":
        for hip in (l_hip, r_hip):
            _key_rotation(hip, 1, (-75, 0, 0))
            _key_rotation(hip, 96, (-75, 0, 0))
        for knee in (l_knee, r_knee):
            _key_rotation(knee, 1, (75, 0, 0))
            _key_rotation(knee, 96, (75, 0, 0))
    elif action_id in {"walk", "run"}:
        amplitude = 38 if action_id == "walk" else 58
        for frame, direction in ((1, 1), (25, -1), (49, 1), (73, -1), (96, 1)):
            _key_rotation(l_hip, frame, (direction * amplitude, 0, 0))
            _key_rotation(r_hip, frame, (-direction * amplitude, 0, 0))
            _key_rotation(l_shoulder, frame, (-direction * amplitude * 0.6, 0, -8))
            _key_rotation(r_shoulder, frame, (direction * amplitude * 0.6, 0, 8))
    elif action_id in {"laugh", "giggle", "shrug"}:
        for arm, sign in ((l_shoulder, -1), (r_shoulder, 1)):
            _key_rotation(arm, 1, (0, 0, sign * 10))
            _key_rotation(arm, 48, (-25, 0, sign * 55))
            _key_rotation(arm, 96, (0, 0, sign * 10))
    elif action_id in {"cross_arms", "hold_object", "hold_book", "hold_toy", "hold_bottle", "read_book", "drink_water", "eat", "draw", "write_notes", "look_at_phone", "put_on_headphones", "listen_music"}:
        _key_rotation(l_shoulder, 1, (-20, -35, -45))
        _key_rotation(r_shoulder, 1, (-20, 35, 45))
        _key_rotation(l_shoulder, 96, (-20, -35, -45))
        _key_rotation(r_shoulder, 96, (-20, 35, 45))
        _key_rotation(l_elbow, 1, (0, 0, 55))
        _key_rotation(r_elbow, 1, (0, 0, -55))


def _pose_bone(rig, *names):
    for name in names:
        bone = rig.pose.bones.get(name)
        if bone:
            bone.rotation_mode = "XYZ"
            return bone
    return None


def animate_cloudrig(rig: bpy.types.Object, action_id: str) -> None:
    """Anima os controles FK comuns aos rigs oficiais CloudRig."""
    if rig.animation_data:
        rig.animation_data_clear()
    upper_l = _pose_bone(rig, "FK-UpperArm.L", "FK-Upperarm.L")
    upper_r = _pose_bone(rig, "FK-UpperArm.R", "FK-Upperarm.R")
    fore_l = _pose_bone(rig, "FK-Forearm.L")
    fore_r = _pose_bone(rig, "FK-Forearm.R")
    thigh_l = _pose_bone(rig, "FK-Thigh.L")
    thigh_r = _pose_bone(rig, "FK-Thigh.R")
    shin_l = _pose_bone(rig, "FK-Shin.L")
    shin_r = _pose_bone(rig, "FK-Shin.R")
    head = _pose_bone(rig, "FK-Head", "FK-HNG-Head")
    torso = _pose_bone(rig, "MSTR-Torso", "MSTR-Spine_Torso")
    hand_l = _pose_bone(
        rig, "IK-MSTR-Wrist.L", "IK-MSTR-Hand.L",
        "IK-Wrist.L", "IK-Hand.L",
    )
    hand_r = _pose_bone(
        rig, "IK-MSTR-Wrist.R", "IK-MSTR-Hand.R",
        "IK-Wrist.R", "IK-Hand.R",
    )
    is_maria = rig.name == "CHAR_MARIA"
    rest_z = 0.30 if is_maria else 0.55
    rest_x = 0.22 if is_maria else 0.28

    for frame, angle in ((1, -3), (48, 3), (96, -3)):
        _key_rotation(head, frame, (0, 0, angle))
        _key_rotation(torso, frame, (0, angle * 0.35, 0))

    # CloudRig opens in a T-pose. Its upper-arm controls must first be
    # rotated around their local Y axis to create a natural resting pose.
    def neutral_arms(frame: int):
        _key_pose_position(hand_l, frame, (rest_x, -0.02, rest_z))
        _key_pose_position(hand_r, frame, (-rest_x, -0.02, rest_z))
        _key_rotation(upper_l, frame, (0, -72, -6))
        _key_rotation(upper_r, frame, (0, 72, 6))
        _key_rotation(fore_l, frame, (0, 0, 8))
        _key_rotation(fore_r, frame, (0, 0, -8))

    if action_id == "wake_stretch":
        neutral_arms(1)
        _key_pose_position(
            hand_l, 48, (rest_x * 0.75, 0.0, rest_z + 0.72)
        )
        _key_pose_position(
            hand_r, 48, (-rest_x * 0.75, 0.0, rest_z + 0.72)
        )
        _key_rotation(upper_l, 48, (0, 68, -10))
        _key_rotation(upper_r, 48, (0, -68, 10))
        neutral_arms(96)
    elif action_id in {"show_product", "point", "wave", "open_door", "close_door"}:
        neutral_arms(1)
        _key_pose_position(
            hand_r, 48, (-0.10, -0.28, rest_z + 0.30)
        )
        _key_rotation(upper_r, 48, (-55, 20, 12))
        _key_rotation(fore_r, 48, (0, 0, -78))
        neutral_arms(96)
    elif action_id in {"pick_up", "put_down", "pack_backpack"}:
        neutral_arms(1)
        _key_pose_position(
            hand_l, 48, (0.18, -0.25, 0.18 if is_maria else 0.32)
        )
        _key_pose_position(
            hand_r, 48, (-0.18, -0.25, 0.18 if is_maria else 0.32)
        )
        neutral_arms(96)
        _key_rotation(torso, 1, (0, 0, 0))
        _key_rotation(torso, 48, (30, 0, 0))
        _key_rotation(torso, 96, (0, 0, 0))
    elif action_id == "sit":
        for bone in (thigh_l, thigh_r):
            _key_rotation(bone, 1, (-72, 0, 0))
            _key_rotation(bone, 96, (-72, 0, 0))
        for bone in (shin_l, shin_r):
            _key_rotation(bone, 1, (70, 0, 0))
            _key_rotation(bone, 96, (70, 0, 0))
    elif action_id in {"walk", "run"}:
        amplitude = 32 if action_id == "walk" else 52
        for frame, sign in ((1, 1), (25, -1), (49, 1), (73, -1), (96, 1)):
            _key_rotation(thigh_l, frame, (sign * amplitude, 0, 0))
            _key_rotation(thigh_r, frame, (-sign * amplitude, 0, 0))
            _key_rotation(upper_l, frame, (-sign * amplitude * 0.35, -72, -6))
            _key_rotation(upper_r, frame, (sign * amplitude * 0.35, 72, 6))
            _key_pose_position(
                hand_l,
                frame,
                (rest_x, -0.10 * sign, rest_z),
            )
            _key_pose_position(
                hand_r,
                frame,
                (-rest_x, 0.10 * sign, rest_z),
            )
    else:
        neutral_arms(1)
        _key_pose_position(
            hand_l, 48, (rest_x * 0.92, -0.05, rest_z + 0.04)
        )
        _key_pose_position(
            hand_r, 48, (-rest_x * 0.92, -0.05, rest_z + 0.04)
        )
        _key_rotation(upper_l, 48, (-7, -68, -9))
        _key_rotation(upper_r, 48, (7, 68, 9))
        neutral_arms(96)


def set_product_prop(
    actor: bpy.types.Object,
    prop_id: str,
    action_id: str,
) -> None:
    for name in (
        "STATIONERY", "BACKPACK", "HEADPHONES",
        "BOOK", "TOY", "WATER_BOTTLE",
    ):
        prop = bpy.data.objects.get(f"PROP_{name}")
        if prop:
            prop.hide_render = True
            prop.hide_viewport = True
    if not prop_id:
        return
    prop = bpy.data.objects.get(f"PROP_{prop_id.upper()}")
    if not prop:
        raise RuntimeError(f"prop ausente: PROP_{prop_id.upper()}")
    prop.hide_render = False
    prop.hide_viewport = False
    prop.parent = actor
    prop.parent_type = "OBJECT"
    is_maria = actor.name == "CHAR_MARIA"
    if action_id == "show_product":
        prop.location = (0.42, -0.30, 0.42 if is_maria else 0.55)
        prop.rotation_euler = (math.radians(82), 0, 0)
    elif action_id in {"write_notes", "draw", "read_book"}:
        prop.location = (0.25, -0.20, 0.38 if is_maria else 0.62)
        prop.rotation_euler = (
            math.radians(12), 0, math.radians(-12)
        )
    else:
        prop.location = (0.15, -0.18, 0.50 if is_maria else 0.75)
        prop.rotation_euler = (0, 0, 0)


def configure_render(
    shot: dict,
    output_dir: str,
    resume_frame: int = 1,
) -> None:
    scene = bpy.context.scene
    fps = int(shot["fps"])
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.fps = fps
    scene.frame_start = max(1, int(resume_frame))
    scene.frame_end = max(2, round(float(shot["duration"]) * fps))
    scene.render.resolution_x = int(shot["width"])
    scene.render.resolution_y = int(shot["height"])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    os.makedirs(output_dir, exist_ok=True)
    scene.render.filepath = str(Path(output_dir) / "frame_")
    scene.world = bpy.data.worlds["WORLD_DIARY"]

    camera_name = f"CAM_{shot['camera_id'].upper()}"
    camera = bpy.data.objects[camera_name]
    scene.camera = camera
    visible_ids = set(shot.get("visible_characters") or [shot["speaker"]])
    actor_meshes = [
        obj for obj in scene.objects
        if obj.type == "MESH"
        and not obj.hide_render
        and obj.get("atlas_character") in visible_ids
        and obj.get("atlas_render_geometry", False)
    ]
    if actor_meshes:
        points = [
            obj.matrix_world @ Vector(corner)
            for obj in actor_meshes
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
        width = max(0.5, maximum.x - minimum.x)
        height = max(0.8, maximum.z - minimum.z)
        if "close" in shot["camera_id"]:
            frame_height = height * 0.62
            center.z = maximum.z - frame_height * 0.48
        elif "medium" in shot["camera_id"]:
            frame_height = height * 1.15
        else:
            frame_height = height * 1.45
        vertical_fov = 2 * math.atan(
            camera.data.sensor_height / (2 * camera.data.lens)
        )
        distance_height = (frame_height / 2) / max(
            0.05, math.tan(vertical_fov / 2)
        )
        # Also account for two actors side by side in a vertical frame.
        aspect = (
            float(scene.render.resolution_x)
            / float(scene.render.resolution_y)
        )
        distance_width = (width * 0.62) / max(
            0.05, math.tan(vertical_fov / 2) * aspect
        )
        distance = max(distance_height, distance_width, 2.2)
        camera.location = (center.x, minimum.y - distance, center.z)
        camera.rotation_euler = (
            center - camera.location
        ).to_track_quat("-Z", "Y").to_euler()
    camera.animation_data_clear()
    if shot["camera_id"] == "close_push_in":
        start = camera.location.copy()
        camera.keyframe_insert("location", frame=scene.frame_start)
        camera.location.y += 0.8
        camera.keyframe_insert("location", frame=scene.frame_end)
        camera.location = start
    elif shot["camera_id"] == "medium_pan":
        camera.rotation_euler.z -= 0.10
        camera.keyframe_insert("rotation_euler", frame=scene.frame_start)
        camera.rotation_euler.z += 0.20
        camera.keyframe_insert("rotation_euler", frame=scene.frame_end)


def main() -> None:
    args = parse_args()
    validate_master()
    if args.validate_only:
        print("ATLAS_DIARY_BLEND_MASTER_OK")
        return
    if not args.shot or not args.output_dir:
        raise RuntimeError("--shot e --output-dir sao obrigatorios")

    shot = json.loads(Path(args.shot).read_text(encoding="utf-8"))
    location = f"SET_{shot['location_id'].upper()}"
    set_visible_collection(location)
    visible = shot.get("visible_characters") or [shot["speaker"]]
    actor = set_character(
        shot["speaker"],
        shot["action_id"],
        shot["emotion_id"],
        visible,
    )
    set_product_prop(
        actor,
        shot.get("prop_id", ""),
        shot["action_id"],
    )
    bpy.context.view_layer.update()
    configure_render(shot, args.output_dir, args.resume_frame)
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
