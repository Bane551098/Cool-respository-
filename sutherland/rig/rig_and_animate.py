"""
Sutherland rig + animation builder for Roblox.

Rigs a Sutherland model made of separate rigid mesh parts (see PART CONTRACT
below), authors the animation set, and exports FBX files that Roblox's
3D Importer / Animation Editor can read.

Usage (Blender GUI or headless):
    blender -b sutherland.blend --python rig_and_animate.py -- --out export
or with the bpy module:
    python rig_and_animate.py --blend sutherland.blend --out export
Test without the real model (builds a gray-box stand-in, never exported as
the real thing):
    python rig_and_animate.py --proxy --out export_proxy

PART CONTRACT
    One mesh object per rigid piece, object origin at the pivot it rotates
    around. Model faces -Y, Z up, meters, feet on Z=0. _L / _R are the
    mech's own left (+X) and right (-X).
    Objects that don't match a bone name are attached to the bone of their
    nearest matched parent object, else to the nearest bone.

Output
    Sutherland_Rigged.fbx       meshes + armature (import with 3D Importer)
    Anim_<Name>.fbx             one per animation (Animation Editor ->
                                Import -> From FBX Animation)
    Sutherland_Rigged.blend     the rigged scene, all actions included
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

FPS = 30
MODEL_HEIGHT = 4.4  # reference height (m) the default skeleton is built for

# bone: (parent, default head, default tail, extra object-name aliases)
# Positions are meters for a 4.4 m tall mech facing -Y.
SKELETON = {
    "Root":          (None,         (0, 0, 0),             (0, 0, 0.6),          []),
    "Hips":          ("Root",       (0, 0, 2.1),           (0, 0, 2.4),          ["Pelvis", "Waist"]),
    "Torso":         ("Hips",       (0, 0, 2.4),           (0, 0, 3.4),          ["Chest", "Body"]),
    "Cockpit":       ("Torso",      (0, 0.35, 2.9),        (0, 0.85, 2.9),       ["CockpitBlock"]),
    "Head":          ("Torso",      (0, 0, 3.5),           (0, 0, 3.9),          []),
    "Factsphere":    ("Head",       (0, -0.25, 3.7),       (0, -0.45, 3.7),      ["FactSphere", "Sensor"]),
    "Harken_L":      ("Torso",      (0.4, -0.4, 2.9),      (0.4, -0.75, 2.9),    ["SlashHarken_L"]),
    "Harken_R":      ("Torso",      (-0.4, -0.4, 2.9),     (-0.4, -0.75, 2.9),   ["SlashHarken_R"]),
    "Shoulder_L":    ("Torso",      (0.75, 0, 3.2),        (1.0, 0, 3.2),        ["Pauldron_L"]),
    "UpperArm_L":    ("Shoulder_L", (1.0, 0, 3.1),         (1.0, 0, 2.45),       []),
    "LowerArm_L":    ("UpperArm_L", (1.0, 0, 2.45),        (1.0, 0, 1.85),       ["Forearm_L"]),
    "Hand_L":        ("LowerArm_L", (1.0, 0, 1.85),        (1.0, 0, 1.6),        []),
    "Tonfa_L":       ("LowerArm_L", (1.13, 0, 2.2),        (1.13, 0, 1.8),       ["StunTonfa_L"]),
    "Shoulder_R":    ("Torso",      (-0.75, 0, 3.2),       (-1.0, 0, 3.2),       ["Pauldron_R"]),
    "UpperArm_R":    ("Shoulder_R", (-1.0, 0, 3.1),        (-1.0, 0, 2.45),      []),
    "LowerArm_R":    ("UpperArm_R", (-1.0, 0, 2.45),       (-1.0, 0, 1.85),      ["Forearm_R"]),
    "Hand_R":        ("LowerArm_R", (-1.0, 0, 1.85),       (-1.0, 0, 1.6),       []),
    "Tonfa_R":       ("LowerArm_R", (-1.13, 0, 2.2),       (-1.13, 0, 1.8),      ["StunTonfa_R"]),
    "Rifle":         ("Hand_R",     (-1.0, -0.1, 1.7),     (-1.0, -0.9, 1.7),    ["AssaultRifle", "Gun"]),
    "Thigh_L":       ("Hips",       (0.35, 0, 2.1),        (0.35, 0, 1.15),      ["UpperLeg_L"]),
    "Shin_L":        ("Thigh_L",    (0.35, 0, 1.15),       (0.35, 0, 0.25),      ["LowerLeg_L"]),
    "Foot_L":        ("Shin_L",     (0.35, 0, 0.25),       (0.35, -0.4, 0.05),   []),
    "Landspinner_L": ("Foot_L",     (0.5, 0.15, 0.2),      (0.65, 0.15, 0.2),    ["Wheel_L"]),
    "Thigh_R":       ("Hips",       (-0.35, 0, 2.1),       (-0.35, 0, 1.15),     ["UpperLeg_R"]),
    "Shin_R":        ("Thigh_R",    (-0.35, 0, 1.15),      (-0.35, 0, 0.25),     ["LowerLeg_R"]),
    "Foot_R":        ("Shin_R",     (-0.35, 0, 0.25),      (-0.35, -0.4, 0.05),  []),
    "Landspinner_R": ("Foot_R",     (-0.5, 0.15, 0.2),     (-0.65, 0.15, 0.2),   ["Wheel_R"]),
}

# For chain bones, point the tail at the child's joint when that part exists.
TAIL_CHILD = {
    "Hips": "Torso", "UpperArm_L": "LowerArm_L", "LowerArm_L": "Hand_L",
    "UpperArm_R": "LowerArm_R", "LowerArm_R": "Hand_R",
    "Thigh_L": "Shin_L", "Shin_L": "Foot_L", "Thigh_R": "Shin_R", "Shin_R": "Foot_R",
}


def norm(name):
    return "".join(c for c in name.lower() if c.isalnum())


# --------------------------------------------------------------------------
# Finding parts
# --------------------------------------------------------------------------

def find_parts():
    """Map bone name -> mesh object, by exact contract name then aliases."""
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    by_norm = {}
    for o in meshes:
        by_norm.setdefault(norm(o.name.split(".")[0]), o)
    found = {}
    for bone, (_, _, _, aliases) in SKELETON.items():
        for cand in [bone] + aliases:
            for key in (norm("SM_" + cand), norm(cand)):
                if key in by_norm:
                    found[bone] = by_norm[key]
                    break
            if bone in found:
                break
    return found, meshes


def model_scale(meshes):
    if not meshes:
        return 1.0
    zs = [(o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box]
    height = max(zs) - min(zs)
    return height / MODEL_HEIGHT if height > 0.01 else 1.0


# --------------------------------------------------------------------------
# Armature
# --------------------------------------------------------------------------

def build_armature(found, scale):
    arm_data = bpy.data.armatures.new("SutherlandRig")
    arm = bpy.data.objects.new("Sutherland", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")

    heads = {}
    for bone, (_, head, _, _) in SKELETON.items():
        obj = found.get(bone)
        heads[bone] = obj.matrix_world.translation.copy() if obj else Vector(head) * scale

    for bone, (parent, head, tail, _) in SKELETON.items():
        eb = arm_data.edit_bones.new(bone)
        eb.head = heads[bone]
        child = TAIL_CHILD.get(bone)
        if child and child in found and (heads[child] - heads[bone]).length > 0.05:
            eb.tail = heads[child]
        else:
            eb.tail = heads[bone] + (Vector(tail) - Vector(head)) * scale
        eb.roll = 0.0
    for bone, (parent, *_rest) in SKELETON.items():
        if parent:
            eb = arm_data.edit_bones[bone]
            eb.parent = arm_data.edit_bones[parent]
            eb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def nearest_bone(arm, point):
    best, best_d = "Root", 1e9
    for b in arm.data.bones:
        h, t = arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local
        seg = t - h
        k = max(0.0, min(1.0, (point - h).dot(seg) / max(seg.length_squared, 1e-9)))
        d = (h + seg * k - point).length
        if d < best_d:
            best, best_d = b.name, d
    return best


def skin_rigid(arm, found, meshes):
    """Weight every vertex of each part 100% to its bone (rigid skinning).

    Parts stay separate objects (keeps each MeshPart under Roblox's
    triangle limit) but all share one armature, which is what the 3D
    Importer expects for an animatable rig.
    """
    obj_to_bone = {o.name: b for b, o in found.items()}
    assignments = {}
    for o in meshes:
        bone = obj_to_bone.get(o.name)
        p = o.parent
        while bone is None and p is not None:
            bone = obj_to_bone.get(p.name)
            p = p.parent
        if bone is None:
            centre = sum((o.matrix_world @ Vector(c) for c in o.bound_box), Vector()) / 8
            bone = nearest_bone(arm, centre)
        assignments[o] = bone

    for o, bone in assignments.items():
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.vertex_groups.clear()
        vg = o.vertex_groups.new(name=bone)
        vg.add(range(len(o.data.vertices)), 1.0, "REPLACE")
        for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
            o.modifiers.remove(m)
        mod = o.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        o.parent = arm
        o.matrix_parent_inverse = arm.matrix_world.inverted()
    return assignments


# --------------------------------------------------------------------------
# Posing helpers. Rotations/offsets are given in ARMATURE axes
# (X = mech's left, -Y = forward, Z = up) and converted into each bone's
# rest frame, so animations don't depend on bone roll or the model's
# exact proportions.
# --------------------------------------------------------------------------

class Animator:
    def __init__(self, arm, scale):
        self.arm = arm
        self.scale = scale
        for pb in arm.pose.bones:
            pb.rotation_mode = "QUATERNION"

    def new_action(self, name):
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        if self.arm.animation_data is None:
            self.arm.animation_data_create()
        self.arm.animation_data.action = action
        self.reset()
        return action

    def reset(self):
        for pb in self.arm.pose.bones:
            pb.rotation_quaternion = Quaternion()
            pb.location = Vector()

    def key(self, frame, pose):
        """pose: {bone: dict(rx, ry, rz in degrees, loc=(x,y,z) meters)}.

        Every bone is keyed on every key frame (unlisted bones at rest) so
        poses never bleed between keys.
        """
        for pb in self.arm.pose.bones:
            spec = pose.get(pb.name, {})
            rest = pb.bone.matrix_local.to_3x3()
            r_arm = Euler((math.radians(spec.get("rx", 0)),
                           math.radians(spec.get("ry", 0)),
                           math.radians(spec.get("rz", 0))), "XYZ").to_matrix()
            local = rest.inverted() @ r_arm @ rest
            pb.rotation_quaternion = local.to_quaternion()
            loc = Vector(spec.get("loc", (0, 0, 0))) * self.scale
            pb.location = rest.inverted() @ loc
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            pb.keyframe_insert("location", frame=frame)

    def finish(self, action, start, end, cyclic=False, linear_bones=()):
        action.frame_range = (start, end)
        action.use_frame_range = True
        action.use_cyclic = cyclic
        for fc in iter_fcurves(action):
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.easing = "AUTO"
            if any(f'"{b}"' in fc.data_path for b in linear_bones):
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"


def iter_fcurves(action):
    """F-curves of an action, for both legacy and layered (Blender 4.4+) actions."""
    if hasattr(action, "layers") and len(action.layers):
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from getattr(action, "fcurves", [])


# --------------------------------------------------------------------------
# Animation set
# --------------------------------------------------------------------------

def sine(t, phase=0.0):
    return math.sin(2 * math.pi * (t + phase))


def anim_idle(a):
    """Idle: 4 s loop. Engine-hum sway, factsphere scan, head glance."""
    act = a.new_action("Idle")
    length = 120
    for f in range(0, length + 1, 10):
        t = f / length
        a.key(f + 1, {
            "Hips": {"loc": (0, 0, -0.02 + 0.015 * sine(t * 2))},
            "Torso": {"rx": 1.0 * sine(t * 2), "rz": 2.0 * sine(t)},
            "Head": {"rz": 12 * sine(t, 0.1)},
            "Factsphere": {"ry": 360 * t},
            "UpperArm_L": {"ry": -4, "rx": 1.5 * sine(t * 2, 0.2)},
            "UpperArm_R": {"ry": 4, "rx": -6 + 1.5 * sine(t * 2, 0.2)},
            "LowerArm_R": {"rx": -25},
            "Thigh_L": {"rx": -3}, "Shin_L": {"rx": 6}, "Foot_L": {"rx": -3},
            "Thigh_R": {"rx": -3}, "Shin_R": {"rx": 6}, "Foot_R": {"rx": -3},
        })
    a.finish(act, 1, length + 1, cyclic=True, linear_bones=("Factsphere",))


def anim_walk(a):
    """Walk: 1.33 s heavy stomp cycle (two steps)."""
    act = a.new_action("Walk")
    length = 40
    for f in range(0, length + 1, 5):
        t = f / length
        s = sine(t)          # +: left leg forward
        lift_l = max(0.0, sine(t, 0.25))
        lift_r = max(0.0, sine(t, 0.75))
        a.key(f + 1, {
            "Hips": {"loc": (0.05 * sine(t, 0.25), 0, -0.04 + 0.05 * abs(sine(t * 2))), "rz": 5 * s},
            "Torso": {"rz": -7 * s, "rx": 3},
            "Head": {"rz": 3 * s},
            "Thigh_L": {"rx": -28 * s - 10 * lift_l},
            "Shin_L": {"rx": 40 * lift_l + 5},
            "Foot_L": {"rx": 14 * s - 10 * lift_l},
            "Thigh_R": {"rx": 28 * s - 10 * lift_r},
            "Shin_R": {"rx": 40 * lift_r + 5},
            "Foot_R": {"rx": -14 * s - 10 * lift_r},
            "UpperArm_L": {"rx": 14 * s, "ry": -4},
            "LowerArm_L": {"rx": -15},
            "UpperArm_R": {"rx": -14 * s - 6, "ry": 4},
            "LowerArm_R": {"rx": -25},
        })
    a.finish(act, 1, length + 1, cyclic=True)


def anim_landspinner(a):
    """Landspinner: 1 s loop. Low glide stance, wheels spinning, slight weave."""
    act = a.new_action("Landspinner")
    length = 30
    for f in range(0, length + 1, 3):
        t = f / length
        a.key(f + 1, {
            "Hips": {"loc": (0.06 * sine(t), 0, -0.35), "ry": 3 * sine(t)},
            "Torso": {"rx": -14, "ry": -3 * sine(t)},
            "Head": {"rx": 10},
            "Thigh_L": {"rx": -38, "ry": 4}, "Shin_L": {"rx": 62}, "Foot_L": {"rx": -24},
            "Thigh_R": {"rx": -30, "ry": -4}, "Shin_R": {"rx": 56}, "Foot_R": {"rx": -26},
            # wheels spin backwards relative to travel (-X rotation rolls forward)
            "Landspinner_L": {"rx": -720 * t},
            "Landspinner_R": {"rx": -720 * t},
            "UpperArm_L": {"rx": 18, "ry": -10},
            "LowerArm_L": {"rx": -30},
            "UpperArm_R": {"rx": 10, "ry": 10},
            "LowerArm_R": {"rx": -35},
        })
    a.finish(act, 1, length + 1, cyclic=True,
             linear_bones=("Landspinner_L", "Landspinner_R"))


AIM_POSE = {
    "Torso": {"rz": -12},
    "Head": {"rz": 8, "rx": 4},
    "UpperArm_R": {"rx": -82, "rz": -10},
    "LowerArm_R": {"rx": -8},
    "Hand_R": {"rx": 88},  # keep the barrel level once the arm is raised
    "UpperArm_L": {"rx": -60, "rz": -50},
    "LowerArm_L": {"rx": -45, "rz": -20},
    "Thigh_L": {"rx": -12}, "Shin_L": {"rx": 16}, "Foot_L": {"rx": -4},
    "Thigh_R": {"rx": 6}, "Shin_R": {"rx": 10}, "Foot_R": {"rx": -16},
    "Hips": {"loc": (0, 0, -0.08)},
}


def anim_aim(a):
    """Aim: raise rifle into firing stance, then hold (play once, freeze)."""
    act = a.new_action("Aim")
    a.key(1, {"UpperArm_R": {"rx": -6}, "LowerArm_R": {"rx": -25}})
    mid = {k: {kk: (vv * 0.6 if kk != "loc" else tuple(x * 0.6 for x in vv))
               for kk, vv in v.items()} for k, v in AIM_POSE.items()}
    a.key(7, mid)
    a.key(13, AIM_POSE)
    a.key(20, AIM_POSE)
    a.finish(act, 1, 20)


def anim_fire(a):
    """Fire: one recoil cycle from the aim pose, 0.2 s, loopable for bursts."""
    act = a.new_action("Fire")

    def recoil(amount):
        pose = {k: dict(v) for k, v in AIM_POSE.items()}
        pose["UpperArm_R"] = {"rx": -82 + 6 * amount, "rz": -10}
        pose["LowerArm_R"] = {"rx": -8 - 10 * amount}
        pose["Rifle"] = {"loc": (0, 0.08 * amount, 0)}
        pose["UpperArm_L"] = {"rx": -60 + 4 * amount, "rz": -50}
        pose["Torso"] = {"rz": -12, "rx": 1.5 * amount}
        return pose

    a.key(1, recoil(0))
    a.key(2, recoil(1))
    a.key(4, recoil(0.4))
    a.key(7, recoil(0))
    a.finish(act, 1, 7, cyclic=True)


def anim_harken(a, side="L"):
    """Slash harken: brace, shoot the harken out ~12 m, hold, reel back in."""
    other = "R" if side == "L" else "L"
    sx = 1 if side == "L" else -1
    act = a.new_action(f"Harken_{side}")
    brace = {
        "Hips": {"loc": (0, 0, -0.12)},
        "Torso": {"rx": -6, "rz": 8 * sx},
        "Thigh_L": {"rx": -18}, "Shin_L": {"rx": 22}, "Foot_L": {"rx": -4},
        "Thigh_R": {"rx": 10}, "Shin_R": {"rx": 14}, "Foot_R": {"rx": -24},
        "UpperArm_L": {"rx": 10, "ry": -12},
        "UpperArm_R": {"rx": 10, "ry": 12},
        "LowerArm_L": {"rx": -30}, "LowerArm_R": {"rx": -30},
    }

    def with_harken(dist, recoil=0.0):
        pose = {k: dict(v) for k, v in brace.items()}
        pose[f"Harken_{side}"] = {"loc": (0, -dist, 0)}
        pose["Torso"] = {"rx": -6 + 4 * recoil, "rz": 8 * sx}
        pose[f"Harken_{other}"] = {}
        return pose

    a.key(1, {})
    a.key(6, with_harken(0))
    a.key(8, with_harken(1.5, 1))
    a.key(14, with_harken(12, 0.3))
    a.key(30, with_harken(12))
    a.key(42, with_harken(0.3))
    a.key(46, with_harken(0))
    a.key(54, {})
    a.finish(act, 1, 54)


ANIMATIONS = [anim_idle, anim_walk, anim_landspinner, anim_aim, anim_fire,
              lambda a: anim_harken(a, "L"), lambda a: anim_harken(a, "R")]


# --------------------------------------------------------------------------
# Gray-box stand-in (testing only)
# --------------------------------------------------------------------------

def build_proxy():
    for bone, (parent, head, tail, _) in SKELETON.items():
        if bone == "Root":
            continue
        h, t = Vector(head), Vector(tail)
        size = Vector((0.35, 0.35, 0.35))
        axis = max(range(3), key=lambda i: abs(t[i] - h[i]))
        size[axis] = max(abs(t[axis] - h[axis]), 0.2)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(h + t) / 2)
        o = bpy.context.active_object
        o.name = "SM_" + bone
        o.scale = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        # move origin to the joint pivot, as the contract requires
        offset = h - o.location
        o.data.transform(Matrix.Translation(-offset))
        o.location = h


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def select_only(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


FBX_COMMON = dict(
    use_selection=True,
    add_leaf_bones=False,
    axis_forward="-Z",
    axis_up="Y",
    apply_scale_options="FBX_SCALE_ALL",
    mesh_smooth_type="FACE",
)


def export(arm, meshes, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    scene.render.fps = FPS

    arm.animation_data.action = None
    arm.data.pose_position = "REST"
    select_only([arm] + meshes)
    bpy.ops.export_scene.fbx(filepath=os.path.join(out_dir, "Sutherland_Rigged.fbx"),
                             object_types={"ARMATURE", "MESH"}, bake_anim=False,
                             **FBX_COMMON)
    arm.data.pose_position = "POSE"

    for action in [a for a in bpy.data.actions if a.use_fake_user]:
        arm.animation_data.action = action
        start, end = (int(x) for x in action.frame_range)
        scene.frame_start, scene.frame_end = start, end
        select_only([arm] + meshes)
        bpy.ops.export_scene.fbx(filepath=os.path.join(out_dir, f"Anim_{action.name}.fbx"),
                                 object_types={"ARMATURE", "MESH"}, bake_anim=True,
                                 bake_anim_use_all_actions=False,
                                 bake_anim_use_nla_strips=False,
                                 bake_anim_force_startend_keying=True,
                                 bake_anim_simplify_factor=0.0,
                                 **FBX_COMMON)

    arm.animation_data.action = bpy.data.actions.get("Idle")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(
        os.path.join(out_dir, "Sutherland_Rigged.blend")))


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--blend", help="model .blend to open (bpy-module mode)")
    p.add_argument("--out", default="export")
    p.add_argument("--proxy", action="store_true",
                   help="ignore the scene and rig a gray-box stand-in (testing)")
    args = p.parse_args(argv)

    if args.blend:
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args.blend))
    if args.proxy:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        build_proxy()
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        bpy.data.objects.remove(o)

    found, meshes = find_parts()
    if not meshes:
        sys.exit("No mesh objects in the scene. Open the model first, or use --proxy.")
    scale = model_scale(meshes)
    missing = [b for b in SKELETON if b != "Root" and b not in found]
    print(f"[rig] model scale {scale:.2f}; matched {len(found)} parts; "
          f"missing (default joint used): {', '.join(missing) or 'none'}")

    arm = build_armature(found, scale)
    assignments = skin_rigid(arm, found, meshes)
    for o, bone in sorted(assignments.items(), key=lambda kv: kv[1]):
        print(f"[rig]   {o.name:28s} -> {bone}")

    animator = Animator(arm, scale)
    for build in ANIMATIONS:
        build(animator)
    print("[rig] actions: " + ", ".join(a.name for a in bpy.data.actions if a.use_fake_user))

    export(arm, meshes, args.out)
    print(f"[rig] exported to {os.path.abspath(args.out)}")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    main(argv)
