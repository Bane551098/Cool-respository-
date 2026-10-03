"""
Procedural RPI-11 Sutherland (Code Geass) Knightmare Frame for Roblox.

Builds the whole mech from code with Blender's Python API (bpy):
  * hard-surface armor, inner frame, Landspinners and cockpit block
  * weapons: assault rifle, twin chest Slash Harkens (with stretching cables),
    forearm Stun Tonfas, and the head Factsphere with opening shutters
  * a bone rig with rigid (100%) skinning, Roblox-friendly bone names
  * animations: Idle, Walk, LandspinnerDash, RifleFire, SlashHarken,
    TonfaStrikeL, TonfaStrikeR, FactsphereScan
  * PBR textures (Color / Metalness / Roughness / Normal) baked with Cycles
    from a procedural paint + edge-wear + grime shader
  * FBX export for the Roblox 3D Importer (model + one FBX per animation)

Run either way (Blender 4.2+ / 5.x):
    python3 build_sutherland.py            # with `pip install bpy`
    blender -b -P build_sutherland.py      # with a Blender install
Options (after `--` when run through blender):
    --res 1024      texture size per mesh (Roblox caps SurfaceAppearance at 1024)
    --samples 16    Cycles samples used when baking
    --no-bake       skip texture baking (fast geometry/rig iteration)
    --no-render     skip the preview renders
    --render-samples 48

All geometry is authored in meters (the Sutherland is ~4.4 m tall) and
converted to Roblox studs (1 stud = 0.28 m), so 1 Blender unit = 1 stud.
"""

import argparse
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "export")
TEX = os.path.join(OUT, "textures")
ANIM = os.path.join(OUT, "anims")
PREVIEW = os.path.join(HERE, "previews")

S = 1 / 0.28  # studs per meter
FPS = 30


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--res", type=int, default=1024)
    p.add_argument("--samples", type=int, default=16)
    p.add_argument("--no-bake", action="store_true")
    p.add_argument("--no-render", action="store_true")
    p.add_argument("--render-samples", type=int, default=48)
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Paint / material styles: tint is linear RGBA, mat = (roughness, metallic, wear)
# ---------------------------------------------------------------------------

def srgb(r, g, b):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (c(r), c(g), c(b), 1.0)


PAINT = dict(tint=srgb(98, 58, 138), mat=(0.40, 0.0, 1.0))       # Britannian purple
PAINT_DARK = dict(tint=srgb(60, 36, 88), mat=(0.44, 0.0, 1.0))
FRAME = dict(tint=srgb(50, 50, 56), mat=(0.48, 0.85, 0.55))      # inner frame
JOINT = dict(tint=srgb(28, 28, 32), mat=(0.55, 0.7, 0.35))
GUN = dict(tint=srgb(70, 72, 78), mat=(0.36, 0.85, 0.7))
GUN_DARK = dict(tint=srgb(34, 35, 40), mat=(0.5, 0.6, 0.5))
STEEL = dict(tint=srgb(175, 177, 184), mat=(0.22, 1.0, 0.15))
RUBBER = dict(tint=srgb(22, 22, 24), mat=(0.85, 0.0, 0.1))
GLOW = dict(tint=srgb(255, 196, 64), mat=(0.3, 0.0, 0.0))        # stun electrodes
LENS = dict(tint=srgb(235, 40, 120), mat=(0.05, 0.0, 0.0))       # Factsphere lens
SENSOR = dict(tint=srgb(12, 12, 16), mat=(0.08, 0.3, 0.0))

# Mesh groups -> one Roblox MeshPart + SurfaceAppearance each
GROUPS = ["ArmorUpper", "ArmorLower", "Frame", "Weapons", "Factsphere"]


# ---------------------------------------------------------------------------
# Geometry helpers (all inputs in meters, in the current local frame)
# ---------------------------------------------------------------------------

_XF = [Matrix.Identity(4)]
PARTS = []  # (object, group)
COLL = None


class frame:
    """Author parts in a local coordinate frame (used for the rifle)."""

    def __init__(self, m):
        self.m = m

    def __enter__(self):
        _XF.append(_XF[-1] @ self.m)

    def __exit__(self, *a):
        _XF.pop()


def to_world(p):
    """Local meters -> world studs."""
    return (_XF[-1] @ Vector(p)) * S


def finish(bm, name, group, bone, style, weight_fn=None):
    bmesh.ops.transform(bm, matrix=Matrix.Scale(S, 4) @ _XF[-1], verts=bm.verts)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    COLL.objects.link(ob)
    tint = me.color_attributes.new("Tint", "FLOAT_COLOR", "POINT")
    mat = me.color_attributes.new("Mat", "FLOAT_COLOR", "POINT")
    m = style["mat"]
    tint.data.foreach_set("color", list(style["tint"]) * len(me.vertices))
    mat.data.foreach_set("color", [m[0], m[1], m[2], 1.0] * len(me.vertices))
    if weight_fn is None:
        ob.vertex_groups.new(name=bone).add(list(range(len(me.vertices))), 1.0, "REPLACE")
    else:
        for v in me.vertices:
            for b, w in weight_fn(v.co):
                vg = ob.vertex_groups.get(b) or ob.vertex_groups.new(name=b)
                vg.add([v.index], w, "REPLACE")
    PARTS.append((ob, group))
    return ob


def _bevel(bm, amount, segs=1):
    if amount > 0:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=amount, offset_type="OFFSET",
                        segments=segs, profile=0.5, affect="EDGES", clamp_overlap=True)


def hull(name, group, bone, style, pts, bevel=0.015, **kw):
    bm = bmesh.new()
    vs = [bm.verts.new(Vector(p)) for p in pts]
    res = bmesh.ops.convex_hull(bm, input=vs, use_existing_faces=False)
    junk = list({g for g in res["geom_interior"] + res["geom_unused"] if isinstance(g, bmesh.types.BMVert)})
    if junk:
        bmesh.ops.delete(bm, geom=junk, context="VERTS")
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(1.0), verts=bm.verts[:], edges=bm.edges[:])
    _bevel(bm, bevel)
    return finish(bm, name, group, bone, style, **kw)


def box(name, group, bone, style, c, s, bevel=0.015, top=(1, 1), top_off=(0, 0)):
    pts = []
    for z, sc, off in ((-1, (1, 1), (0, 0)), (1, top, top_off)):
        for x in (-1, 1):
            for y in (-1, 1):
                pts.append((c[0] + x * s[0] / 2 * sc[0] + off[0],
                            c[1] + y * s[1] / 2 * sc[1] + off[1],
                            c[2] + z * s[2] / 2))
    return hull(name, group, bone, style, pts, bevel=min(bevel, min(s) * 0.3))


def cyl(name, group, bone, style, p0, p1, r, r2=None, segs=16, caps=True, bevel=0.0, **kw):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=segs,
                          radius1=r, radius2=r if r2 is None else r2, depth=d.length)
    if bevel and caps:
        rim = [e for e in bm.edges if any(len(f.verts) > 4 for f in e.link_faces)]
        bmesh.ops.bevel(bm, geom=rim, offset=bevel, offset_type="OFFSET", segments=1,
                        profile=0.5, affect="EDGES", clamp_overlap=True)
    rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((p0 + p1) / 2) @ rot, verts=bm.verts)
    return finish(bm, name, group, bone, style, **kw)


def sphere(name, group, bone, style, c, r, u=16, v=10):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)
    bmesh.ops.translate(bm, vec=Vector(c), verts=bm.verts)
    return finish(bm, name, group, bone, style)


SIDES = (("L", 1), ("R", -1))  # character faces -Y, so its left is +X

# Key dimensions (meters)
AX = 0.74      # arm X
LX = 0.38      # leg / foot X
SH_Z = 3.38    # shoulder pivot height
EL_Z = 2.76    # elbow
WR_Z = 2.16    # wrist
HP_Z = 2.20    # hip joint
KN_Z = 1.45    # knee
AN_Z = 0.45    # ankle
HARKEN_X, HARKEN_Z = 0.20, 3.15
WHEEL_Y, WHEEL_Z, WHEEL_R = 0.24, 0.14, 0.13
FIST = Vector((-AX, 0.0, 1.97))             # right fist centre = rifle grip
RIFLE_XF = Matrix.Translation(FIST) @ Matrix.Rotation(math.radians(90), 4, "X")
RIFLE_MUZZLE = (0, -1.42, 0.25)             # rifle-local (aim frame)


def build_torso():
    G, B = "ArmorUpper", "Chest"
    hull("Chest", G, B, PAINT, [
        (-0.32, -0.26, 2.72), (0.32, -0.26, 2.72), (-0.32, 0.26, 2.72), (0.32, 0.26, 2.72),
        (-0.52, -0.43, 3.12), (0.52, -0.43, 3.12), (-0.52, 0.30, 3.12), (0.52, 0.30, 3.12),
        (0.0, -0.49, 3.22),
        (-0.50, -0.36, 3.46), (0.50, -0.36, 3.46), (-0.50, 0.30, 3.46), (0.50, 0.30, 3.46),
        (-0.34, -0.22, 3.56), (0.34, -0.22, 3.56), (-0.34, 0.24, 3.56), (0.34, 0.24, 3.56),
    ], bevel=0.02)
    box("Collar", G, B, PAINT_DARK, (0, 0.10, 3.58), (0.46, 0.26, 0.12), top=(0.85, 0.8))
    for i, x in enumerate((-0.30, -0.20, 0.20, 0.30)):  # chest underside vents
        box(f"ChestVent{i}", "Frame", B, FRAME, (x, -0.33, 2.74), (0.06, 0.06, 0.05))
    # Slash Harken ports: open tube with a dark back plate
    for side, sx in SIDES:
        x = sx * HARKEN_X
        cyl(f"HarkenPort.{side}", "Frame", B, JOINT, (x, -0.29, HARKEN_Z), (x, -0.475, HARKEN_Z),
            0.088, segs=16, caps=False)
        cyl(f"HarkenPortRim.{side}", "Frame", B, FRAME, (x, -0.44, HARKEN_Z), (x, -0.48, HARKEN_Z),
            0.105, segs=16)
        cyl(f"HarkenPortBack.{side}", "Frame", B, JOINT, (x, -0.28, HARKEN_Z), (x, -0.30, HARKEN_Z),
            0.088, segs=16)
    # Abdomen / waist
    cyl("WaistFrame", "Frame", "Waist", FRAME, (0, 0, 2.40), (0, 0, 2.76), 0.19, segs=16, bevel=0.01)
    for i, z in enumerate((2.50, 2.62)):
        box(f"Abdomen{i}", G, "Waist", PAINT_DARK, (0, -0.05, z), (0.40 + i * 0.06, 0.40, 0.09),
            top=(1.04, 1.04))
    # Neck
    cyl("Neck", "Frame", "Neck", FRAME, (0, 0, 3.50), (0, 0, 3.76), 0.09, segs=12)
    # Cockpit block (the Sutherland's ejectable cockpit on its back)
    hull("Cockpit", G, "Cockpit", PAINT, [
        (-0.30, 0.26, 2.86), (0.30, 0.26, 2.86), (-0.33, 0.26, 3.54), (0.33, 0.26, 3.54),
        (-0.25, 0.94, 2.96), (0.25, 0.94, 2.96), (-0.27, 0.94, 3.40), (0.27, 0.94, 3.40),
        (-0.29, 0.70, 3.60), (0.29, 0.70, 3.60),
    ], bevel=0.025)
    box("CockpitHatch", "Frame", "Cockpit", FRAME, (0, 0.95, 3.18), (0.36, 0.04, 0.34))
    box("CockpitStripe", G, "Cockpit", PAINT_DARK, (0, 0.62, 3.585), (0.12, 0.40, 0.04))
    for side, sx in SIDES:
        cyl(f"Thruster.{side}", "Frame", "Cockpit", JOINT, (sx * 0.14, 0.74, 2.95),
            (sx * 0.14, 0.74, 2.80), 0.07, r2=0.085, segs=12)


def build_head():
    G, B = "ArmorUpper", "Head"
    box("HeadCore", "Frame", B, JOINT, (0, 0.0, 3.90), (0.24, 0.34, 0.30))
    sphere("FactsphereSocket", "Frame", B, JOINT, (0, -0.15, 3.90), 0.115, u=16, v=10)
    for side, sx in SIDES:
        hull(f"HeadCheek.{side}", G, B, PAINT, [
            (sx * 0.10, -0.24, 3.76), (sx * 0.10, -0.24, 4.04),
            (sx * 0.145, -0.22, 3.76), (sx * 0.145, -0.22, 4.04),
            (sx * 0.18, 0.04, 3.74), (sx * 0.18, 0.04, 4.08),
            (sx * 0.16, 0.20, 3.78), (sx * 0.16, 0.20, 4.06),
            (sx * 0.10, 0.21, 3.76), (sx * 0.10, 0.21, 4.08),
        ], bevel=0.012)
        cyl(f"Antenna.{side}", "Frame", B, FRAME, (sx * 0.17, 0.12, 4.00), (sx * 0.24, 0.40, 4.14),
            0.014, r2=0.006, segs=6)
    hull("HeadTop", G, B, PAINT, [
        (-0.11, -0.21, 4.04), (0.11, -0.21, 4.04), (-0.12, 0.19, 4.07), (0.12, 0.19, 4.07),
        (-0.06, -0.13, 4.15), (0.06, -0.13, 4.15), (-0.07, 0.13, 4.17), (0.07, 0.13, 4.17),
        (0, -0.29, 4.06),
    ], bevel=0.012)
    hull("HeadCrest", G, B, PAINT_DARK, [
        (x, y, z) for x in (-0.016, 0.016)
        for (y, z) in ((-0.10, 4.15), (0.18, 4.16), (0.27, 4.34), (0.04, 4.20))
    ], bevel=0.005)
    box("Chin", G, B, PAINT_DARK, (0, -0.10, 3.74), (0.20, 0.24, 0.06))
    box("HeadBack", G, B, PAINT, (0, 0.17, 3.92), (0.22, 0.10, 0.30))
    # Factsphere: lens on its own bone + two armored shutters
    sphere("FactsphereLens", "Factsphere", "Factsphere", LENS, (0, -0.19, 3.90), 0.09, u=20, v=12)
    cyl("FactsphereIris", "Factsphere", "Factsphere", SENSOR, (0, -0.26, 3.90), (0, -0.285, 3.90),
        0.04, segs=16)
    th = 0.03
    top = [(-0.10, -0.24, 4.03), (-0.10, -0.29, 3.98), (-0.10, -0.31, 3.90)]
    for name, bone, sgn in (("ShutterTop", "ShutterTop", 1), ("ShutterBottom", "ShutterBottom", -1)):
        pts = []
        for x in (-0.10, 0.10):
            for (_, y, z) in top:
                zz = 3.90 + sgn * (z - 3.90)
                pts += [(x, y, zz), (x, y - th, zz)]
        hull(name, G, bone, PAINT, pts, bevel=0.006)


def build_arms():
    for side, sx in SIDES:
        x = sx * AX
        UA, FA, HD = f"UpperArm.{side}", f"Forearm.{side}", f"Hand.{side}"
        sphere(f"ShoulderJoint.{side}", "Frame", UA, JOINT, (sx * 0.68, 0, SH_Z), 0.15)
        hull(f"Pauldron.{side}", "ArmorUpper", UA, PAINT, [
            (sx * 0.52, -0.24, 3.76), (sx * 0.52, 0.24, 3.76),
            (sx * 0.60, -0.30, 3.74), (sx * 0.60, 0.30, 3.74),
            (sx * 0.96, -0.31, 3.58), (sx * 0.96, 0.31, 3.58),
            (sx * 1.05, -0.28, 3.40), (sx * 1.05, 0.28, 3.40),
            (sx * 1.04, -0.30, 3.06), (sx * 1.04, 0.30, 3.06),
            (sx * 0.90, -0.27, 2.98), (sx * 0.90, 0.27, 2.98),
            (sx * 0.58, -0.24, 3.30), (sx * 0.58, 0.24, 3.30),
            (sx * 0.90, -0.39, 3.40), (sx * 0.90, 0.36, 3.40),
        ], bevel=0.025)
        box(f"PauldronTrim.{side}", "ArmorUpper", UA, PAINT_DARK, (sx * 0.99, 0, 3.02),
            (0.10, 0.60, 0.07))
        cyl(f"UpperArmFrame.{side}", "Frame", UA, FRAME, (x, 0, 3.25), (x, 0, 2.82), 0.10, segs=12)
        box(f"Bicep.{side}", "ArmorUpper", UA, PAINT_DARK, (x, 0, 2.98), (0.24, 0.26, 0.30))
        sphere(f"Elbow.{side}", "Frame", FA, JOINT, (x, 0, EL_Z), 0.11, u=12, v=8)
        box(f"Forearm.{side}", "ArmorUpper", FA, PAINT, (x, -0.005, 2.46), (0.30, 0.31, 0.52),
            top=(0.8, 0.8))
        box(f"WristGuard.{side}", "ArmorUpper", FA, PAINT_DARK, (x, -0.005, 2.21), (0.31, 0.32, 0.08))
        box(f"TonfaMount.{side}", "Frame", FA, FRAME, (sx * (AX + 0.16), 0, 2.30), (0.05, 0.12, 0.14))
        # Stun Tonfa, folded up along the forearm, pivoting at the wrist
        T, tx = f"Tonfa.{side}", sx * (AX + 0.20)
        cyl(f"TonfaHub.{side}", "Weapons", T, GUN_DARK, (sx * (AX + 0.17), 0, 2.27),
            (sx * (AX + 0.23), 0, 2.27), 0.06, segs=12)
        cyl(f"TonfaRod.{side}", "Weapons", T, GUN, (tx, 0, 2.27), (tx, 0, 2.86), 0.035, segs=10)
        cyl(f"TonfaTip.{side}", "Weapons", T, STEEL, (tx, 0, 2.86), (tx, 0, 2.92), 0.048, segs=10)
        for i, z in enumerate((2.70, 2.78)):
            cyl(f"TonfaCoil{i}.{side}", "Weapons", T, GLOW, (tx, 0, z), (tx, 0, z + 0.025), 0.045, segs=10)
        # Fist
        box(f"Palm.{side}", "Frame", HD, FRAME, (x, 0, 2.04), (0.15, 0.20, 0.18))
        for i in range(4):
            box(f"Finger{i}.{side}", "Frame", HD, JOINT, (x - sx * 0.02, -0.075 + 0.05 * i, 1.925),
                (0.13, 0.042, 0.09), bevel=0.01)
        box(f"Thumb.{side}", "Frame", HD, JOINT, (x - sx * 0.07, -0.10, 2.0), (0.05, 0.05, 0.12))
        box(f"HandGuard.{side}", "ArmorUpper", HD, PAINT_DARK, (x + sx * 0.085, 0, 2.04),
            (0.04, 0.21, 0.2))


def build_pelvis_and_legs():
    G, B = "ArmorLower", "Hips"
    box("Pelvis", "Frame", B, FRAME, (0, 0, 2.25), (0.58, 0.40, 0.30))
    hull("FrontSkirt", G, B, PAINT, [
        (-0.24, -0.22, 2.46), (0.24, -0.22, 2.46), (-0.24, -0.12, 2.46), (0.24, -0.12, 2.46),
        (-0.13, -0.31, 2.02), (0.13, -0.31, 2.02), (-0.13, -0.21, 2.02), (0.13, -0.21, 2.02),
        (0, -0.35, 2.26),
    ], bevel=0.015)
    hull("RearSkirt", G, B, PAINT_DARK, [
        (-0.25, 0.20, 2.46), (0.25, 0.20, 2.46), (-0.25, 0.28, 2.46), (0.25, 0.28, 2.46),
        (-0.20, 0.31, 2.08), (0.20, 0.31, 2.08), (-0.20, 0.24, 2.08), (0.20, 0.24, 2.08),
    ])
    for side, sx in SIDES:
        hull(f"SideSkirt.{side}", G, B, PAINT, [
            (sx * 0.47, -0.21, 2.48), (sx * 0.47, 0.21, 2.48), (sx * 0.53, -0.22, 2.48), (sx * 0.53, 0.22, 2.48),
            (sx * 0.55, -0.19, 2.04), (sx * 0.55, 0.19, 2.04), (sx * 0.60, -0.20, 2.04), (sx * 0.60, 0.20, 2.04),
        ])
        c = sx * LX
        TH, SN, FT, WH = f"Thigh.{side}", f"Shin.{side}", f"Foot.{side}", f"Wheel.{side}"
        sphere(f"HipJoint.{side}", "Frame", TH, JOINT, (sx * 0.30, 0, HP_Z), 0.14)
        cyl(f"ThighFrame.{side}", "Frame", TH, FRAME, (sx * 0.33, 0, 2.15), (sx * 0.37, 0, 1.55), 0.12, segs=12)
        box(f"ThighArmor.{side}", G, TH, PAINT, (sx * 0.36, -0.04, 1.84), (0.25, 0.26, 0.44), top=(1.1, 1.1))
        box(f"ThighPlate.{side}", G, TH, PAINT_DARK, (sx * 0.46, -0.01, 1.92), (0.05, 0.22, 0.32))
        sphere(f"Knee.{side}", "Frame", SN, JOINT, (sx * 0.37, 0, KN_Z), 0.13)
        hull(f"KneeCap.{side}", G, SN, PAINT_DARK, [
            (sx * 0.37 - 0.13, -0.12, 1.62), (sx * 0.37 + 0.13, -0.12, 1.62),
            (sx * 0.37 - 0.13, -0.12, 1.30), (sx * 0.37 + 0.13, -0.12, 1.30),
            (sx * 0.37 - 0.08, -0.05, 1.47), (sx * 0.37 + 0.08, -0.05, 1.47),
            (sx * 0.37, -0.30, 1.48),
        ], bevel=0.012)
        hull(f"Shin.{side}", G, SN, PAINT, [
            (c - 0.16, -0.21, 1.38), (c + 0.16, -0.21, 1.38), (c - 0.16, 0.15, 1.38), (c + 0.16, 0.15, 1.38),
            (c - 0.11, -0.16, 0.60), (c + 0.11, -0.16, 0.60), (c - 0.11, 0.15, 0.60), (c + 0.11, 0.15, 0.60),
            (c, -0.25, 1.16), (c - 0.12, 0.23, 1.08), (c + 0.12, 0.23, 1.08),
        ], bevel=0.02)
        box(f"ShinVent.{side}", "Frame", SN, FRAME, (c + sx * 0.14, 0.0, 1.00), (0.03, 0.16, 0.34))
        box(f"ShinStripe.{side}", G, SN, PAINT_DARK, (c, -0.205, 0.86), (0.09, 0.04, 0.26))
        sphere(f"Ankle.{side}", "Frame", FT, JOINT, (c, 0, AN_Z), 0.10, u=12, v=8)
        hull(f"Foot.{side}", G, FT, PAINT, [
            (c - 0.15, 0.22, 0.04), (c + 0.15, 0.22, 0.04), (c - 0.15, 0.22, 0.24), (c + 0.15, 0.22, 0.24),
            (c - 0.11, -0.08, 0.38), (c + 0.11, -0.08, 0.38), (c - 0.11, 0.12, 0.38), (c + 0.11, 0.12, 0.38),
            (c - 0.06, -0.56, 0.04), (c + 0.06, -0.56, 0.04), (c - 0.04, -0.54, 0.09), (c + 0.04, -0.54, 0.09),
            (c - 0.14, -0.30, 0.04), (c + 0.14, -0.30, 0.04), (c - 0.12, -0.28, 0.20), (c + 0.12, -0.28, 0.20),
        ], bevel=0.018)
        box(f"Sole.{side}", "Frame", FT, FRAME, (c, -0.13, 0.025), (0.30, 0.72, 0.05), top=(1, 1), top_off=(0, 0))
        box(f"WheelHousing.{side}", "Frame", FT, FRAME, (c, WHEEL_Y, WHEEL_Z + 0.03), (0.33, 0.20, 0.20))
        # Landspinners: a wheel each side of the heel, spinning on one bone
        for j, o in enumerate((-1, 1)):
            x0, x1 = c + o * 0.165, c + o * 0.235
            cyl(f"Tire{j}.{side}", "Frame", WH, RUBBER, (x0, WHEEL_Y, WHEEL_Z), (x1, WHEEL_Y, WHEEL_Z),
                WHEEL_R, segs=20, bevel=0.01)
            cyl(f"Hub{j}.{side}", "Frame", WH, STEEL, (x0, WHEEL_Y, WHEEL_Z), (x1 + o * 0.012, WHEEL_Y, WHEEL_Z),
                0.075, segs=12)
            for k in range(3):  # hub spokes so the spin reads in motion
                a = k * math.pi / 3
                dy, dz = math.cos(a) * 0.115, math.sin(a) * 0.115
                cyl(f"Spoke{j}{k}.{side}", "Frame", WH, GUN_DARK,
                    (x1 + o * 0.004, WHEEL_Y - dy, WHEEL_Z - dz), (x1 + o * 0.004, WHEEL_Y + dy, WHEEL_Z + dz),
                    0.012, segs=6)


def build_rifle():
    G, B, D = "Weapons", "Rifle", GUN_DARK
    with frame(RIFLE_XF):  # aim frame: barrel along -Y, top along +Z, origin at grip
        box("RifleGrip", G, B, D, (0, 0.02, 0.02), (0.06, 0.09, 0.24))
        box("RifleReceiver", G, B, GUN, (0, -0.12, 0.24), (0.15, 0.70, 0.20))
        box("RifleRail", G, B, D, (0, -0.15, 0.355), (0.06, 0.50, 0.03))
        box("RifleStock", G, B, D, (0, 0.33, 0.26), (0.09, 0.20, 0.15), top=(1, 0.8))
        box("RifleHandguard", G, B, D, (0, -0.62, 0.24), (0.13, 0.32, 0.15))
        box("RifleEjector", G, B, D, (0.077, -0.10, 0.27), (0.012, 0.14, 0.06), bevel=0.003)
        hull("RifleMag", G, B, D, [
            (x, y, z) for x in (-0.04, 0.04)
            for (y, z) in ((-0.40, 0.14), (-0.26, 0.14), (-0.44, -0.12), (-0.32, -0.14))
        ], bevel=0.01)
        cyl("RifleBarrel", G, B, D, (0, -0.78, 0.25), (0, -1.30, 0.25), 0.035, segs=12)
        cyl("RifleMuzzle", G, B, GUN, (0, -1.30, 0.25), RIFLE_MUZZLE, 0.055, segs=12, bevel=0.008)
        box("RifleScopeMount", G, B, D, (0, -0.20, 0.385), (0.04, 0.12, 0.04))
        cyl("RifleScope", G, B, GUN, (0, -0.04, 0.43), (0, -0.36, 0.43), 0.045, segs=12, bevel=0.006)
        cyl("RifleScopeLens", "Factsphere", B, LENS, (0, -0.36, 0.43), (0, -0.365, 0.43), 0.036, segs=12)


def build_harkens():
    for side, sx in SIDES:
        x, H = sx * HARKEN_X, f"Harken.{side}"
        cyl(f"HarkenBody.{side}", "Weapons", H, GUN, (x, -0.34, HARKEN_Z), (x, -0.46, HARKEN_Z), 0.062, segs=12)
        cyl(f"HarkenTip.{side}", "Weapons", H, STEEL, (x, -0.46, HARKEN_Z), (x, -0.60, HARKEN_Z),
            0.062, r2=0.004, segs=12)
        for k, (w, h) in enumerate(((0.165, 0.016), (0.016, 0.165))):
            box(f"HarkenFin{k}.{side}", "Weapons", H, STEEL, (x, -0.45, HARKEN_Z), (w, 0.09, h), bevel=0.004)

        # The cable is rigidly bound at both ends, so firing the harken stretches it
        def weights(co, H=H):
            back = co.y > -0.33 * S
            return [("Chest", 1.0)] if back else [(H, 1.0)]
        cyl(f"HarkenCable.{side}", "Weapons", "Chest", GUN_DARK, (x, -0.30, HARKEN_Z), (x, -0.36, HARKEN_Z),
            0.016, segs=6, weight_fn=weights)


# ---------------------------------------------------------------------------
# Rig
# ---------------------------------------------------------------------------

def bone_table():
    rifle_tail = RIFLE_XF @ Vector((0, -0.5, 0))
    muzzle = RIFLE_XF @ Vector(RIFLE_MUZZLE)
    t = [
        ("Root", (0, 0, 0), (0, 0, 0.5), None),
        ("Hips", (0, 0, 2.25), (0, 0, 2.50), "Root"),
        ("Waist", (0, 0, 2.50), (0, 0, 2.76), "Hips"),
        ("Chest", (0, 0, 2.76), (0, 0, 3.50), "Waist"),
        ("Neck", (0, 0, 3.50), (0, 0, 3.74), "Chest"),
        ("Head", (0, 0, 3.74), (0, 0, 4.15), "Neck"),
        ("Factsphere", (0, -0.19, 3.90), (0, -0.33, 3.90), "Head"),
        ("ShutterTop", (0, -0.255, 4.03), (0, -0.255, 4.13), "Head"),
        ("ShutterBottom", (0, -0.255, 3.77), (0, -0.255, 3.67), "Head"),
        ("Cockpit", (0, 0.30, 3.20), (0, 0.60, 3.20), "Chest"),
        ("Rifle", tuple(FIST), tuple(rifle_tail), "Hand.R"),
        ("Muzzle", tuple(muzzle), tuple(muzzle + Vector((0, 0, -0.15))), "Rifle"),
    ]
    for side, sx in SIDES:
        t += [
            (f"Harken.{side}", (sx * HARKEN_X, -0.40, HARKEN_Z), (sx * HARKEN_X, -0.60, HARKEN_Z), "Chest"),
            (f"UpperArm.{side}", (sx * AX, 0, SH_Z), (sx * AX, 0, EL_Z), "Chest"),
            (f"Forearm.{side}", (sx * AX, 0, EL_Z), (sx * AX, 0, WR_Z), f"UpperArm.{side}"),
            (f"Hand.{side}", (sx * AX, 0, WR_Z), (sx * AX, 0, 1.90), f"Forearm.{side}"),
            (f"Tonfa.{side}", (sx * (AX + 0.20), 0, 2.27), (sx * (AX + 0.20), 0, 2.86), f"Forearm.{side}"),
            (f"Thigh.{side}", (sx * 0.33, 0, HP_Z), (sx * 0.37, 0, KN_Z), "Hips"),
            (f"Shin.{side}", (sx * 0.37, 0, KN_Z), (sx * LX, 0, AN_Z), f"Thigh.{side}"),
            (f"Foot.{side}", (sx * LX, 0, AN_Z), (sx * LX, -0.40, 0.08), f"Shin.{side}"),
            (f"Wheel.{side}", (sx * LX, WHEEL_Y, WHEEL_Z), (sx * LX, WHEEL_Y, WHEEL_Z + 0.2), f"Foot.{side}"),
        ]
    return t


def build_rig():
    arm_data = bpy.data.armatures.new("Sutherland_Rig")
    arm = bpy.data.objects.new("Sutherland_Rig", arm_data)
    COLL.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    table = bone_table()
    for name, h, t, _ in table:
        eb = arm_data.edit_bones.new(name)
        eb.head, eb.tail = Vector(h) * S, Vector(t) * S
        eb.roll = 0
    for name, _, _, parent in table:
        if parent:
            arm_data.edit_bones[name].parent = arm_data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return arm


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

class NodeBuilder:
    def __init__(self, nt):
        self.nt = nt
        self.x = 0

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        n.location = (self.x, 0)
        self.x += 40
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def math(self, op, a, b=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                self.link(v, n.inputs[i])
        return n.outputs[0]

    def maprange(self, v, f0, f1, t0=0.0, t1=1.0):
        n = self.node("ShaderNodeMapRange", clamp=True)
        self.link(v, n.inputs["Value"])
        n.inputs["From Min"].default_value, n.inputs["From Max"].default_value = f0, f1
        n.inputs["To Min"].default_value, n.inputs["To Max"].default_value = t0, t1
        return n.outputs["Result"]

    def noise(self, vec, scale, detail=4.0, rough=0.55):
        n = self.node("ShaderNodeTexNoise")
        self.link(vec, n.inputs["Vector"])
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = rough
        return n.outputs["Fac"]

    def mix_color(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="RGBA")
        sock = {s.identifier: s for s in n.inputs}
        for key, v in (("Factor_Float", fac), ("A_Color", a), ("B_Color", b)):
            if isinstance(v, tuple):
                sock[key].default_value = v
            elif isinstance(v, (int, float)):
                sock[key].default_value = v
            else:
                self.link(v, sock[key])
        return next(s for s in n.outputs if s.identifier == "Result_Color")


def procedural_material(name):
    """Paint/metal shader driven by the per-part Tint and Mat attributes.

    Returns the material plus the sockets used for baking each map.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    b = NodeBuilder(nt)
    out = b.node("ShaderNodeOutputMaterial")
    bsdf = b.node("ShaderNodeBsdfPrincipled")
    tint = b.node("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="Tint").outputs["Color"]
    sep = b.node("ShaderNodeSeparateColor")
    b.link(b.node("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="Mat").outputs["Color"],
           sep.inputs["Color"])
    rough0, metal0, wear_amt = sep.outputs["Red"], sep.outputs["Green"], sep.outputs["Blue"]
    co = b.node("ShaderNodeTexCoord").outputs["Object"]
    geo = b.node("ShaderNodeNewGeometry")

    # Broad paint variation
    n_broad = b.noise(co, 0.35, detail=6)
    shade = b.maprange(n_broad, 0.3, 0.7, 0.86, 1.10)
    vs = b.node("ShaderNodeVectorMath", operation="SCALE")
    b.link(tint, vs.inputs[0])
    b.link(shade, vs.inputs["Scale"])
    paint = vs.outputs["Vector"]

    # Edge wear: where a wide bevel normal disagrees with the true face normal
    bev_wide = b.node("ShaderNodeBevel", samples=8)
    bev_wide.inputs["Radius"].default_value = 0.07
    dot = b.node("ShaderNodeVectorMath", operation="DOT_PRODUCT")
    b.link(bev_wide.outputs["Normal"], dot.inputs[0])
    b.link(geo.outputs["True Normal"], dot.inputs[1])
    edge = b.maprange(dot.outputs["Value"], 0.995, 0.80)
    chips = b.maprange(b.noise(co, 4.5, detail=8, rough=0.7), 0.42, 0.66)
    wear = b.math("MULTIPLY", b.maprange(b.math("MULTIPLY", edge, chips), 0.25, 0.45), wear_amt)
    wear = b.math("MULTIPLY", wear, 0.9)

    # Grime in crevices + faint vertical streaking
    ao = b.node("ShaderNodeAmbientOcclusion", samples=8, only_local=False)
    ao.inputs["Distance"].default_value = 1.2
    cavity = b.maprange(b.math("SUBTRACT", 1.0, ao.outputs["AO"]), 0.10, 0.65)
    mp = b.node("ShaderNodeMapping")
    b.link(co, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (5.0, 5.0, 0.35)
    streak = b.maprange(b.noise(mp.outputs["Vector"], 1.0, detail=3), 0.45, 0.8, 0.0, 0.35)
    grime = b.math("MINIMUM", b.math("ADD", b.math("MULTIPLY", cavity,
                                                   b.maprange(b.noise(co, 1.6), 0.3, 0.7, 0.45, 1.0)),
                                     streak), 1.0)

    bare = (0.55, 0.55, 0.57, 1.0)
    dirt = (0.075, 0.066, 0.055, 1.0)
    color = b.mix_color(wear, paint, bare)
    color = b.mix_color(b.math("MULTIPLY", grime, 0.55), color, dirt)

    metal = b.math("ADD", metal0, b.math("MULTIPLY", wear, b.math("SUBTRACT", 1.0, metal0)), clamp=True)
    micro = b.noise(co, 9.0, detail=4)
    rough = b.math("ADD", rough0, b.maprange(micro, 0.3, 0.7, -0.07, 0.07))
    rough = b.math("ADD", rough, b.math("MULTIPLY", grime, 0.22))
    rough = b.math("SUBTRACT", rough, b.math("MULTIPLY", wear, 0.12), clamp=True)

    # Normal: soft bevel on hard edges + fine surface pitting
    bev = b.node("ShaderNodeBevel", samples=8)
    bev.inputs["Radius"].default_value = 0.035
    bump = b.node("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.10
    bump.inputs["Distance"].default_value = 0.02
    b.link(b.noise(co, 28.0, detail=3), bump.inputs["Height"])
    b.link(bev.outputs["Normal"], bump.inputs["Normal"])

    b.link(color, bsdf.inputs["Base Color"])
    b.link(metal, bsdf.inputs["Metallic"])
    b.link(rough, bsdf.inputs["Roughness"])
    b.link(bump.outputs["Normal"], bsdf.inputs["Normal"])
    b.link(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat, dict(Color=color, Metalness=metal, Roughness=rough, bsdf=bsdf, out=out)


def pbr_material(name, maps):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF") or nt.nodes.new("ShaderNodeBsdfPrincipled")

    def tex(img):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        return n
    nt.links.new(tex(maps["Color"]).outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex(maps["Metalness"]).outputs["Color"], bsdf.inputs["Metallic"])
    nt.links.new(tex(maps["Roughness"]).outputs["Color"], bsdf.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(tex(maps["Normal"]).outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# ---------------------------------------------------------------------------
# Assembly, UVs, baking
# ---------------------------------------------------------------------------

def select_only(objs, active=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[0]


def join_groups(arm):
    meshes = {}
    for g in GROUPS:
        objs = [o for o, grp in PARTS if grp == g]
        if not objs:
            continue
        select_only(objs)
        bpy.ops.object.join()
        ob = bpy.context.view_layer.objects.active
        ob.name = ob.data.name = f"Sutherland_{g}"
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30), keep_sharp_edges=True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=0.0005)
        bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.006,
                                 area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
        bpy.ops.uv.pack_islands(rotate=True, margin=0.004)
        bpy.ops.object.mode_set(mode="OBJECT")
        ob.parent = arm
        mod = ob.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        meshes[g] = ob
    return meshes


def bake(meshes, res, samples):
    scene = bpy.context.scene
    scene.cycles.samples = samples
    scene.render.bake.margin = 6
    scene.render.bake.margin_type = "EXTEND"
    os.makedirs(TEX, exist_ok=True)
    for g, ob in meshes.items():
        mat, socks = procedural_material(f"M_{g}_Procedural")
        ob.data.materials.clear()
        ob.data.materials.append(mat)
        nt = mat.node_tree
        size = res if g != "Factsphere" else max(256, res // 4)
        texnode = nt.nodes.new("ShaderNodeTexImage")
        emit = nt.nodes.new("ShaderNodeEmission")
        maps = {}
        select_only([ob])
        for kind in ("Color", "Metalness", "Roughness", "Normal"):
            img = bpy.data.images.new(f"Sutherland_{g}_{kind}", size, size, alpha=False)
            img.colorspace_settings.name = "sRGB" if kind == "Color" else "Non-Color"
            texnode.image = img
            nt.nodes.active = texnode
            texnode.select = True
            print(f"[bake] {g} {kind} {size}px", flush=True)
            if kind == "Normal":
                nt.links.new(socks["bsdf"].outputs["BSDF"], socks["out"].inputs["Surface"])
                bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")
            else:
                nt.links.new(socks[kind], emit.inputs["Color"])
                nt.links.new(emit.outputs["Emission"], socks["out"].inputs["Surface"])
                bpy.ops.object.bake(type="EMIT")
            img.filepath_raw = os.path.join(TEX, f"Sutherland_{g}_{kind}.png")
            img.file_format = "PNG"
            img.save()
            maps[kind] = img
        ob.data.materials.clear()
        ob.data.materials.append(pbr_material(f"M_{g}", maps))


def plain_materials(meshes):
    """Untextured fallback (--no-bake): vertex tint as base color."""
    for g, ob in meshes.items():
        mat, _ = procedural_material(f"M_{g}")
        ob.data.materials.clear()
        ob.data.materials.append(mat)


# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------
# A pose is {bone: [ops]} with ops ("rx"|"ry"|"rz", degrees) about world axes as
# they are at rest, or ("t", (x, y, z)) a rest-space offset in meters.
# Rotating +rx tips upward-pointing bones forward (toward -Y) and swings
# downward-pointing bones (arms, legs) backward.

AXES = {"rx": Vector((1, 0, 0)), "ry": Vector((0, 1, 0)), "rz": Vector((0, 0, 1))}


def to_local(pb, ops):
    rest = pb.bone.matrix_local.to_3x3()
    inv = rest.inverted()
    q = Quaternion()
    loc = Vector()
    for op, v in ops:
        if op == "t":
            loc += inv @ (Vector(v) * S)
        else:
            q = Quaternion(inv @ AXES[op], math.radians(v)) @ q
    return q, loc


def action_fcurves(act):
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                out += list(cb.fcurves)
    return out


def make_action(arm, name, keys, linear_bones=()):
    """keys: list of (frame, pose). Bones not named in a pose rest at identity."""
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data_create()
    arm.animation_data.action = act
    bones = sorted(set().union(*[set(p) for _, p in keys]))
    for f, pose in keys:
        for bn in bones:
            pb = arm.pose.bones[bn]
            q, loc = to_local(pb, pose.get(bn, []))
            pb.rotation_quaternion, pb.location = q, loc
            pb.keyframe_insert("rotation_quaternion", frame=f, group=bn)
            pb.keyframe_insert("location", frame=f, group=bn)
    for fc in action_fcurves(act):
        if any(f'"{b}"' in fc.data_path for b in linear_bones):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
    act.frame_range = (keys[0][0], keys[-1][0])
    act["roblox_loop"] = keys[0][1] == keys[-1][1]
    return act


def walk_leg(thigh, shin):
    """Leg pose that keeps the foot level."""
    return thigh, shin, -(thigh + shin)


def build_animations(arm):
    acts = []
    R = "rx"

    # Idle: slow breathing sway
    idle_a = {"Chest": [(R, 0)], "Head": [("rz", 0)]}
    idle_b = {"Hips": [("t", (0, 0, -0.03))], "Chest": [(R, 2)], "Head": [("rz", 8), (R, -2)],
              "UpperArm.L": [(R, -2)], "UpperArm.R": [(R, -2)]}
    for s in ("L", "R"):
        idle_b[f"Thigh.{s}"], idle_b[f"Shin.{s}"], idle_b[f"Foot.{s}"] = ([(R, v)] for v in walk_leg(-4, 8))
    acts.append(make_action(arm, "Idle", [(0, idle_a), (30, idle_b), (60, idle_a)]))

    # Walk cycle (heavy, stomping gait)
    def walk_pose(phase):
        p = {}
        cycle = [(-24, 6), (-4, 14), (18, 16), (0, 58)]  # contact, pass, push-off, swing
        for s, off in (("L", 0), ("R", 2)):
            th, sh, ft = walk_leg(*cycle[(phase + off) % 4])
            p[f"Thigh.{s}"], p[f"Shin.{s}"], p[f"Foot.{s}"] = [(R, th)], [(R, sh)], [(R, ft)]
        swing = [16, 4, -14, -4][phase]  # left arm swings against left leg
        p["UpperArm.L"] = [(R, swing)]
        p["Forearm.L"] = [(R, -12)]
        p["UpperArm.R"] = [(R, -swing * 0.4)]
        p["Forearm.R"] = [(R, -8)]
        p["Hips"] = [("t", (0, 0, [-0.06, 0.0, -0.06, 0.0][phase])), ("rz", [4, 0, -4, 0][phase])]
        p["Chest"] = [(R, 4), ("rz", [-5, 0, 5, 0][phase])]
        p["Head"] = [("rz", [3, 0, -3, 0][phase])]
        return p
    acts.append(make_action(arm, "Walk", [(i * 10, walk_pose(i % 4)) for i in range(5)]))

    # Landspinner dash: crouched glide, wheels spinning (3 rev / second)
    def dash_pose(i):
        p = {"Hips": [("t", (0, 0.12, -0.25)), (R, 10), ("rz", [6, -6][i % 2] if i % 6 else 0)],
             "Chest": [(R, 14)], "Head": [(R, -20)],
             "UpperArm.L": [(R, 25), ("ry", -12)], "Forearm.L": [(R, -30)],
             "UpperArm.R": [(R, -35)], "Forearm.R": [(R, -35)]}
        for s in ("L", "R"):
            p[f"Thigh.{s}"], p[f"Shin.{s}"], p[f"Foot.{s}"] = [(R, -55)], [(R, 60)], [(R, -15)]
            p[f"Wheel.{s}"] = [(R, 90 * i)]
        return p
    dash = [(i * 2.5, dash_pose(i)) for i in range(13)]
    for f, p in dash:  # gentle side-to-side carve on whole-second beats
        sway = math.sin(f / 30 * 2 * math.pi) * 6
        p["Hips"] = [("t", (0, 0.12, -0.25)), (R, 10), ("ry", sway)]
    acts.append(make_action(arm, "LandspinnerDash", dash, linear_bones=("Wheel.L", "Wheel.R")))

    # Rifle: raise, three-round burst with recoil, lower
    aim = {"UpperArm.R": [(R, -86)], "Forearm.R": [(R, -4)], "Chest": [("rz", -12)], "Head": [("rz", 8)],
           "UpperArm.L": [(R, -62), ("ry", 22)], "Forearm.L": [(R, -48)], "Rifle": []}
    kick = dict(aim, **{"UpperArm.R": [(R, -90)], "Rifle": [("t", (0, 0, 0.10))], "Chest": [("rz", -12), (R, -2)]})
    rest = {k: [] for k in aim}
    keys = [(0, rest), (10, aim)]
    for i in range(3):
        keys += [(12 + i * 6, kick), (15 + i * 6, aim)]
    keys += [(38, aim), (50, rest)]
    acts.append(make_action(arm, "RifleFire", keys))

    # Slash Harkens: brace, fire both anchors ~11 studs, reel in
    rest = {"Chest": [], "Harken.L": [], "Harken.R": [], "Hips": []}
    brace = {"Chest": [(R, -6)], "Hips": [("t", (0, 0.04, -0.05))], "Harken.L": [], "Harken.R": []}
    fired = dict(brace, **{"Harken.L": [("t", (0.08, -3.0, 0.05))], "Harken.R": [("t", (-0.08, -3.0, 0.05))]})
    acts.append(make_action(arm, "SlashHarken", [(0, rest), (4, brace), (9, fired), (22, fired),
                                                   (34, brace), (45, rest)]))

    # Stun Tonfa strikes: tonfa flips out from the forearm as the punch lands
    for side, sx in (("L", 1), ("R", -1)):
        U, F, T = f"UpperArm.{side}", f"Forearm.{side}", f"Tonfa.{side}"
        rest = {U: [], F: [], T: [], "Chest": [], "Hips": []}
        wind = {U: [(R, 30)], F: [(R, -70)], T: [(R, 90)], "Chest": [("rz", 16 * sx)], "Hips": [("rz", 5 * sx)]}
        hit = {U: [(R, -82)], F: [(R, -6)], T: [(R, 180)], "Chest": [("rz", -22 * sx), (R, 6)],
               "Hips": [("rz", -8 * sx), ("t", (0, -0.05, -0.06))]}
        back = dict(hit, **{T: [(R, 90)]})
        acts.append(make_action(arm, f"TonfaStrike{side}", [(0, rest), (7, wind), (12, hit), (22, hit),
                                                             (30, back), (38, rest)]))

    # Factsphere: shutters open, sensor extends and sweeps, then closes
    closed = {"ShutterTop": [], "ShutterBottom": [], "Factsphere": [], "Head": []}
    opened = {"ShutterTop": [(R, -150)], "ShutterBottom": [(R, 140)], "Factsphere": [("t", (0, -0.06, 0))],
              "Head": []}

    def look(deg):
        return dict(opened, **{"Factsphere": [("t", (0, -0.05, 0)), ("rz", deg * 1.5)], "Head": [("rz", deg)]})
    acts.append(make_action(arm, "FactsphereScan", [(0, closed), (5, dict(opened, ShutterTop=[(R, -75)],
                                                                           ShutterBottom=[(R, 70)])),
                                                    (10, opened), (22, look(20)), (38, look(-20)),
                                                    (50, opened), (60, closed)]))
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion, pb.location = Quaternion(), Vector()
    return acts


# ---------------------------------------------------------------------------
# Export + previews
# ---------------------------------------------------------------------------

FBX_COMMON = dict(
    use_selection=True, apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
    axis_forward="-Z", axis_up="Y", add_leaf_bones=False, use_armature_deform_only=False,
    armature_nodetype="NULL", mesh_smooth_type="FACE", use_tspace=False,
)


def export(arm, meshes, acts):
    os.makedirs(ANIM, exist_ok=True)
    scene = bpy.context.scene
    arm.animation_data.action = None
    select_only([arm] + list(meshes.values()), arm)
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, "Sutherland.fbx"), object_types={"ARMATURE", "MESH"},
                             bake_anim=False, path_mode="COPY", embed_textures=True, **FBX_COMMON)
    for act in acts:
        arm.animation_data.action = act
        scene.frame_start, scene.frame_end = (int(round(v)) for v in act.frame_range)
        select_only([arm])
        bpy.ops.export_scene.fbx(filepath=os.path.join(ANIM, f"Sutherland_{act.name}.fbx"),
                                 object_types={"ARMATURE"}, bake_anim=True, bake_anim_use_all_actions=False,
                                 bake_anim_use_nla_strips=False, bake_anim_force_startend_keying=True,
                                 bake_anim_step=1.0, bake_anim_simplify_factor=0.0, **FBX_COMMON)
    arm.animation_data.action = None
    scene.frame_start, scene.frame_end = 0, 60


def setup_render_scene():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.32, 0.34, 0.38, 1)
    bg.inputs["Strength"].default_value = 0.6
    scene.world = world
    for name, loc, energy, size in (("Key", (14, -16, 22), 9000, 8), ("Rim", (-12, 16, 18), 6000, 6),
                                    ("Fill", (-18, -10, 6), 2500, 10)):
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, "AREA"))
        light.data.energy, light.data.size = energy, size
        light.location = loc
        COLL.objects.link(light)
        light.rotation_euler = (Vector((0, 0, 7)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.ops.mesh.primitive_plane_add(size=200)
    floor = bpy.context.object
    floor.name = "Floor"
    fm = bpy.data.materials.new("Floor")
    fm.use_nodes = True
    p = fm.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.2, 0.2, 0.21, 1)
    p.inputs["Roughness"].default_value = 0.8
    floor.data.materials.append(fm)
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    COLL.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = 720, 960
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    return cam, floor


def render(arm, cam, shots, samples):
    scene = bpy.context.scene
    scene.cycles.samples = samples
    try:
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    os.makedirs(PREVIEW, exist_ok=True)
    for name, act, frame_no, loc, target, lens in shots:
        arm.animation_data.action = None
        for pb in arm.pose.bones:
            pb.rotation_quaternion, pb.location = Quaternion(), Vector()
        arm.animation_data.action = bpy.data.actions[act] if act else None
        scene.frame_set(frame_no)
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = lens
        scene.render.filepath = os.path.join(PREVIEW, f"{name}.png")
        print(f"[render] {name}", flush=True)
        bpy.ops.render.render(write_still=True)
    arm.animation_data.action = None
    scene.frame_set(0)


def main():
    global COLL
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.render.fps = FPS
    scene.unit_settings.system = "NONE"  # 1 Blender unit = 1 Roblox stud
    COLL = bpy.data.collections.new("Sutherland")
    scene.collection.children.link(COLL)

    build_torso()
    build_head()
    build_arms()
    build_harkens()
    build_rifle()
    build_pelvis_and_legs()
    arm = build_rig()
    meshes = join_groups(arm)

    print("\nMesh budget (Roblox MeshPart limit 20,000 tris):")
    for g, ob in meshes.items():
        tris = sum(len(p.vertices) - 2 for p in ob.data.polygons)
        print(f"  {ob.name:28s} {tris:6d} tris")
        assert tris < 20000, ob.name
    dims = [ob for ob in meshes.values()]
    zmax = max((ob.matrix_world @ Vector(c)).z for ob in dims for c in ob.bound_box)
    print(f"  height: {zmax:.2f} studs ({zmax * 0.28:.2f} m), bones: {len(arm.data.bones)}\n")

    if args.no_bake:
        plain_materials(meshes)
    else:
        bake(meshes, args.res, args.samples)
    acts = build_animations(arm)
    os.makedirs(OUT, exist_ok=True)
    export(arm, meshes, acts)

    if not args.no_render:
        cam, floor = setup_render_scene()
        mid = (0, 0, 7.6)
        render(arm, cam, [
            ("front", None, 0, (17, -30, 12), mid, 50),
            ("back", None, 0, (-18, 28, 13), mid, 50),
            ("rifle_fire", "RifleFire", 12, (-24, -20, 10), (-2, -4, 8), 45),
            ("slash_harken", "SlashHarken", 14, (26, -20, 13), (0, -5, 10), 40),
            ("tonfa_strike", "TonfaStrikeL", 14, (20, -22, 10), (1, -2, 8), 45),
            ("landspinner_dash", "LandspinnerDash", 5, (24, -14, 6), (0, 0, 6), 50),
            ("factsphere", "FactsphereScan", 22, (3.0, -9.0, 14.8), (0, -0.9, 13.9), 70),
        ], args.render_samples)
        bpy.data.objects.remove(floor)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "Sutherland.blend"), compress=True,
                                relative_remap=True, copy=False)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_mainfile(compress=True)
    print("done:", OUT)


if __name__ == "__main__":
    main()
