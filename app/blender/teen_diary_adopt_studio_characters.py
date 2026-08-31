"""Substitui os protótipos por Ellie e Gabby, do Blender Studio."""

from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "app" / "assets" / "teen_diary_3d" / "diario_master.blend"
SOURCE = ROOT / "tools" / "blender_studio_characters"


def delete_hierarchy(root):
    for child in list(root.children_recursive):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(root, do_unlink=True)


def remove_prototype(name):
    root = bpy.data.objects.get(name)
    if root:
        delete_hierarchy(root)


def append_collection(path: Path, collection_name: str):
    with bpy.data.libraries.load(str(path), link=False) as (source, target):
        if collection_name not in source.collections:
            raise RuntimeError(f"{collection_name} ausente em {path}")
        target.collections = [collection_name]
    collection = target.collections[0]
    bpy.context.scene.collection.children.link(collection)
    return collection


def set_collection_render(collection, visible=True):
    collection.hide_render = not visible
    collection.hide_viewport = not visible
    for child in collection.children:
        set_collection_render(child, visible)


def find_rig(collection, expected):
    for obj in collection.all_objects:
        if obj.type == "ARMATURE" and obj.name == expected:
            return obj
    raise RuntimeError(f"rig ausente: {expected}")


def hide_objects(collection, prefixes):
    for obj in collection.all_objects:
        if obj is not None and obj.name.startswith(prefixes):
            obj.hide_render = True
            obj.hide_viewport = True


def remove_objects(collection, prefixes):
    for obj in list(collection.all_objects):
        if obj is not None and obj.name.startswith(prefixes):
            bpy.data.objects.remove(obj, do_unlink=True)


def hide_child_collections(collection, prefixes):
    for child in collection.children_recursive:
        if child.name.startswith(prefixes):
            child.hide_render = True
            child.hide_viewport = True
            for obj in child.all_objects:
                if obj is not None:
                    obj.hide_render = True
                    obj.hide_viewport = True


def tag_meshes(collection, character):
    meshes = [
        obj for obj in collection.all_objects
        if obj is not None and obj.type == "MESH"
    ]
    if not meshes:
        raise RuntimeError(f"{character}: nenhum mesh")
    body = next(
        (
            obj for obj in meshes
            if any(token in obj.name.lower() for token in ("body", "head"))
        ),
        meshes[0],
    )
    body.name = f"CHAR_{character}_BODY"
    for obj in collection.all_objects:
        if obj is not None:
            obj["atlas_character"] = character.lower()
            if obj.name.startswith(
                (
                    "WGT-", "META-", "RIG-smear", "GEO-smear", "CUR-smear",
                    "GEO-ellie_hair_cage", "GEO-ellie_hair_sim",
                )
            ):
                obj["atlas_render_geometry"] = False
            else:
                obj["atlas_render_geometry"] = (
                    obj.type in ("MESH", "CURVE") and not obj.hide_render
                )


def brown_material():
    material = bpy.data.materials.get("MARIA_HAIR_BROWN")
    if material:
        return material
    material = bpy.data.materials.new("MARIA_HAIR_BROWN")
    material.diffuse_color = (0.12, 0.035, 0.015, 1)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = material.diffuse_color
    bsdf.inputs["Roughness"].default_value = 0.55
    return material


def eye_material(name, color, roughness):
    material = bpy.data.materials.get(name)
    if material:
        return material
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    return material


def replace_gabby_pupils(collection, rig):
    remove_objects(collection, ("GEO-eye_pupil", "GEO-eye_highlight"))
    iris_mat = eye_material(
        "MARIA_IRIS_BROWN", (0.10, 0.035, 0.012, 1), 0.30
    )
    pupil_mat = eye_material(
        "MARIA_PUPIL_BLACK", (0.005, 0.004, 0.003, 1), 0.22
    )
    highlight_mat = eye_material(
        "MARIA_EYE_HIGHLIGHT", (1.0, 1.0, 1.0, 1), 0.12
    )
    created = []
    for index, x in enumerate((0.0615, -0.0615)):
        center = Vector((x, -0.164, 0.605))
        for suffix, offset, scale, material in (
            (
                "IRIS",
                Vector((0, -0.018, 0)),
                (0.025, 0.010, 0.032),
                iris_mat,
            ),
            (
                "PUPIL",
                Vector((0, -0.027, 0)),
                (0.011, 0.006, 0.015),
                pupil_mat,
            ),
            (
                "HIGHLIGHT",
                Vector((-0.006, -0.034, 0.008)),
                (0.0045,) * 3,
                highlight_mat,
            ),
        ):
            bpy.ops.mesh.primitive_uv_sphere_add(
                segments=20,
                ring_count=12,
                location=center + offset,
            )
            obj = bpy.context.object
            obj.name = f"MARIA_EYE_{index}_{suffix}"
            obj.scale = scale
            bpy.ops.object.transform_apply(
                location=False,
                rotation=False,
                scale=True,
            )
            obj.data.materials.append(material)
            obj["atlas_character"] = "maria"
            obj["atlas_render_geometry"] = True
            obj.parent = rig
            obj.location = center + offset
            created.append(obj)


def harmonize_gabby_hair(collection):
    material = brown_material()
    for obj in collection.all_objects:
        if obj is None or not obj.name.startswith("GEO-Hair"):
            continue
        if obj.type == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(material)


def add_ellie_hair(collection, rig):
    head = next(
        (
            obj for obj in collection.all_objects
            if obj is not None and obj.name == "CHAR_ISABELA_BODY"
        ),
        None,
    )
    if not head:
        return
    remove_objects(
        collection,
        ("GEO-ellie_hair", "GEO-ellie_scrunchy"),
    )
    points = [head.matrix_world @ Vector(corner) for corner in head.bound_box]
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
    dimensions = maximum - minimum
    material = eye_material(
        "BELA_HAIR_CHESTNUT", (0.12, 0.035, 0.012, 1), 0.48
    )
    created = []
    for name, location, scale in (
        (
            "BELA_HAIR_CAP",
            center + Vector((0, 0.035, dimensions.z * 0.16)),
            (
                dimensions.x * 0.58,
                dimensions.y * 0.58,
                dimensions.z * 0.58,
            ),
        ),
        (
            "BELA_HAIR_SIDE_L",
            center + Vector((dimensions.x * 0.42, 0.04, -dimensions.z * 0.15)),
            (
                dimensions.x * 0.20,
                dimensions.y * 0.24,
                dimensions.z * 0.46,
            ),
        ),
        (
            "BELA_HAIR_SIDE_R",
            center + Vector((-dimensions.x * 0.42, 0.04, -dimensions.z * 0.15)),
            (
                dimensions.x * 0.20,
                dimensions.y * 0.24,
                dimensions.z * 0.46,
            ),
        ),
        (
            "BELA_HALF_UP",
            center + Vector((0.10, 0.12, dimensions.z * 0.48)),
            (dimensions.x * 0.18,) * 3,
        ),
    ):
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=24,
            ring_count=16,
            location=location,
        )
        obj = bpy.context.object
        obj.name = name
        obj.scale = scale
        bpy.ops.object.transform_apply(
            location=False, rotation=False, scale=True
        )
        obj.data.materials.append(material)
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        obj["atlas_character"] = "isabela"
        obj["atlas_render_geometry"] = True
        created.append(obj)
    head_bone = next(
        (
            name for name in ("FK-Head", "ORG-Head")
            if rig.data.bones.get(name)
        ),
        "",
    )
    if head_bone:
        for obj in created:
            world = obj.matrix_world.copy()
            obj.parent = rig
            obj.parent_type = "BONE"
            obj.parent_bone = head_bone
            obj.matrix_world = world


def add_ellie_hair_from_gabby(ellie, gabby, bela_rig):
    source = next(
        (
            obj for obj in gabby.all_objects
            if obj is not None and obj.name == "GEO-Hair"
        ),
        None,
    )
    target_head = bpy.data.objects.get("CHAR_ISABELA_BODY")
    if not source or not target_head:
        return
    remove_objects(
        ellie,
        ("GEO-ellie_hair", "GEO-ellie_scrunchy"),
    )
    evaluated = source.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = bpy.data.meshes.new_from_object(evaluated)
    hair = bpy.data.objects.new("BELA_HAIR_ROUNDED", mesh)
    bpy.context.scene.collection.objects.link(hair)
    hair.data.materials.clear()
    hair.data.materials.append(
        eye_material(
            "BELA_HAIR_CHESTNUT", (0.12, 0.035, 0.012, 1), 0.48
        )
    )

    def world_bounds(obj):
        pts = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        minimum = Vector((
            min(p.x for p in pts),
            min(p.y for p in pts),
            min(p.z for p in pts),
        ))
        maximum = Vector((
            max(p.x for p in pts),
            max(p.y for p in pts),
            max(p.z for p in pts),
        ))
        return minimum, maximum

    target_min, target_max = world_bounds(target_head)
    target_size = target_max - target_min
    local_min = Vector((
        min(vertex.co.x for vertex in mesh.vertices),
        min(vertex.co.y for vertex in mesh.vertices),
        min(vertex.co.z for vertex in mesh.vertices),
    ))
    local_max = Vector((
        max(vertex.co.x for vertex in mesh.vertices),
        max(vertex.co.y for vertex in mesh.vertices),
        max(vertex.co.z for vertex in mesh.vertices),
    ))
    local_center = (local_min + local_max) / 2
    for vertex in mesh.vertices:
        vertex.co -= local_center
    source_size = local_max - local_min
    scale = (target_size.x / max(source_size.x, 0.001)) * 1.38
    hair.scale = (scale, scale, scale)
    hair["atlas_character"] = "isabela"
    hair["atlas_render_geometry"] = True
    hair.parent = bela_rig
    hair.parent_type = "OBJECT"
    target_center = (target_min + target_max) / 2
    target_world = (
        target_center
        + Vector((0, 0.025, target_size.z * 0.07))
    )
    hair.location = bela_rig.matrix_world.inverted() @ target_world

    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=24,
        ring_count=16,
        location=target_center + Vector((0, 0.035, target_size.z * 0.30)),
    )
    cap = bpy.context.object
    cap.name = "BELA_HAIR_TOP"
    cap.scale = (
        target_size.x * 0.56,
        target_size.y * 0.52,
        target_size.z * 0.38,
    )
    bpy.ops.object.transform_apply(
        location=False, rotation=False, scale=True
    )
    cap.data.materials.append(
        bpy.data.materials["BELA_HAIR_CHESTNUT"]
    )
    for polygon in cap.data.polygons:
        polygon.use_smooth = True
    cap["atlas_character"] = "isabela"
    cap["atlas_render_geometry"] = True
    world = cap.matrix_world.copy()
    cap.parent = bela_rig
    cap.parent_type = "OBJECT"
    cap.matrix_world = world


def fix_gabby_eye_depth(collection):
    iris = eye_material(
        "MARIA_IRIS_OPAQUE", (0.05, 0.20, 0.16, 1), 0.25
    )
    highlight = eye_material(
        "MARIA_HIGHLIGHT_OPAQUE", (1.0, 1.0, 1.0, 1), 0.10
    )
    for obj in collection.all_objects:
        if obj is None:
            continue
        if obj.name.startswith("CUR-eye_white"):
            if hasattr(obj.data, "materials"):
                obj.data.materials.clear()
                obj.data.materials.append(iris)
        if obj.name.startswith(("GEO-eye_pupil", "GEO-eye_highlight")):
            obj.hide_render = True
            obj.hide_viewport = True
            if obj.type == "MESH":
                local_delta = (
                    obj.matrix_world.inverted().to_3x3()
                    @ Vector((0, -0.018, 0))
                )
                for vertex in obj.data.vertices:
                    vertex.co += local_delta
                obj.data.materials.clear()
                obj.data.materials.append(
                    iris
                    if obj.name.startswith("GEO-eye_pupil")
                    else highlight
                )


def main():
    remove_prototype("CHAR_ISABELA")
    remove_prototype("CHAR_MARIA")

    ellie = append_collection(SOURCE / "ellie.blend", "CH-ellie")
    gabby = append_collection(SOURCE / "gabby.blend", "CH-gabby")
    ellie.name = "CHARACTER_COLLECTION_ISABELA"
    gabby.name = "CHARACTER_COLLECTION_MARIA"
    set_collection_render(ellie)
    set_collection_render(gabby)

    bela_rig = find_rig(ellie, "RIG-Ellie")
    maria_rig = find_rig(gabby, "RIG-gabby")
    bela_rig.name = "CHAR_ISABELA"
    maria_rig.name = "CHAR_MARIA"
    bela_rig.location = (-0.62, 0, 0)
    maria_rig.location = (0.62, 0, 0)
    maria_rig.scale = (0.82, 0.82, 0.82)

    # Remove fantasy props that do not belong to a six-year-old diary scene.
    remove_objects(
        gabby,
        (
            "GEO-Goggles", "GEO-Compass", "GEO-smear", "CUR-smear",
        ),
    )
    for obj in list(bpy.data.objects):
        if obj.name.startswith(("GEO-ellie_fannypack", "CUR-fannypack")):
            bpy.data.objects.remove(obj, do_unlink=True)
    hide_objects(gabby, ("WGT-", "META-", "RIG-smear"))
    hide_objects(
        ellie,
        ("GEO-ellie_fannypack", "CUR-fannypack", "WGT-", "META-"),
    )
    hide_child_collections(ellie, ("ellie.hair",))
    tag_meshes(ellie, "ISABELA")
    tag_meshes(gabby, "MARIA")
    add_ellie_hair_from_gabby(ellie, gabby, bela_rig)

    bela_rig["character_age"] = 13
    maria_rig["character_age"] = 6
    bela_rig["source"] = "Blender Studio Ellie, CC-BY 4.0"
    maria_rig["source"] = "Blender Studio Gabby, CC-BY 4.0"

    bpy.ops.wm.save_as_mainfile(filepath=str(MASTER))
    print("ATLAS_STUDIO_CHARACTERS_ADOPTED")


if __name__ == "__main__":
    main()
