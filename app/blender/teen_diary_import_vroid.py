"""Importa Bela/Maria VRM no master e normaliza os rigs para as ações."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = ROOT / "app" / "assets" / "teen_diary_3d"
CHAR_DIR = ASSET_DIR / "characters"
MASTER = ASSET_DIR / "diario_master.blend"

VRM_TO_CMU = {
    "J_Bip_C_Hips": "Hips",
    "J_Bip_C_Spine": "Spine",
    "J_Bip_C_Chest": "Spine1",
    "J_Bip_C_UpperChest": "Spine2",
    "J_Bip_C_Neck": "Neck1",
    "J_Bip_C_Head": "Head",
    "J_Bip_L_Shoulder": "LeftShoulder",
    "J_Bip_L_UpperArm": "LeftArm",
    "J_Bip_L_LowerArm": "LeftForeArm",
    "J_Bip_L_Hand": "LeftHand",
    "J_Bip_R_Shoulder": "RightShoulder",
    "J_Bip_R_UpperArm": "RightArm",
    "J_Bip_R_LowerArm": "RightForeArm",
    "J_Bip_R_Hand": "RightHand",
    "J_Bip_L_UpperLeg": "LeftUpLeg",
    "J_Bip_L_LowerLeg": "LeftLeg",
    "J_Bip_L_Foot": "LeftFoot",
    "J_Bip_R_UpperLeg": "RightUpLeg",
    "J_Bip_R_LowerLeg": "RightLeg",
    "J_Bip_R_Foot": "RightFoot",
}


def delete_hierarchy(root: bpy.types.Object) -> None:
    objects = list(root.children_recursive) + [root]
    for obj in reversed(objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def remove_old_character(character: str) -> None:
    for name in (f"CHAR_{character}", f"CHAR_{character}_BODY"):
        obj = bpy.data.objects.get(name)
        if obj:
            delete_hierarchy(obj)


def import_character(character: str, path: Path) -> bpy.types.Object:
    before = set(bpy.data.objects)
    result = bpy.ops.import_scene.vrm(
        filepath=str(path),
        use_addon_preferences=True,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"falha ao importar {path}")
    added = [obj for obj in bpy.data.objects if obj not in before]
    armatures = [obj for obj in added if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(
            f"{path.name}: esperado 1 armature, encontrados {len(armatures)}"
        )
    rig = armatures[0]
    rig.name = f"CHAR_{character}"
    for old, new in VRM_TO_CMU.items():
        bone = rig.data.bones.get(old)
        if bone:
            bone.name = new
    meshes = [obj for obj in added if obj.type == "MESH"]
    if meshes:
        meshes[0].name = f"CHAR_{character}_BODY"
    rig.location = (-0.65, 0, 0) if character == "ISABELA" else (0.65, 0, 0)
    return rig


def main() -> None:
    missing = [
        path for path in (CHAR_DIR / "bela.vrm", CHAR_DIR / "maria.vrm")
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError(f"VRM ausentes: {[str(path) for path in missing]}")
    remove_old_character("ISABELA")
    remove_old_character("MARIA")
    import_character("ISABELA", CHAR_DIR / "bela.vrm")
    import_character("MARIA", CHAR_DIR / "maria.vrm")
    bpy.ops.wm.save_as_mainfile(filepath=str(MASTER))
    print("ATLAS_VROID_CHARACTERS_IMPORTED")


if __name__ == "__main__":
    main()
