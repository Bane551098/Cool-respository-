# Sutherland rig and animations (Roblox)

Rigs the Sutherland model, authors its animations in Blender, and exports
FBX files for Roblox. A Luau module plays them in-game and draws the slash
harken cables.

| File | What it is |
| --- | --- |
| `rig/rig_and_animate.py` | Blender script: builds the armature, skins the parts, authors the animations, exports FBX |
| `roblox/SutherlandAnimator.lua` | ModuleScript that plays the animations and draws harken cables |

## Animations

| Name | Length | Loops | Notes |
| --- | --- | --- | --- |
| `Idle` | 4 s | yes | sway, head glance, factsphere scan |
| `Walk` | 1.33 s | yes | heavy two-step stomp |
| `Landspinner` | 1 s | yes | low glide stance, wheels spinning |
| `Aim` | 0.67 s | no | raises the rifle; the module freezes it on the last frame |
| `Fire` | 0.2 s | per shot | one recoil kick from the aim pose |
| `Harken_L`, `Harken_R` | 1.8 s | no | brace, fire the harken ~12 m forward, reel it in |

## Rig

A custom rig (not R15): a mech needs bones R15 doesn't have (landspinner
wheels, harkens, factsphere, rifle). Each part is skinned 100% to one bone,
so it moves rigidly, and every part stays its own mesh so none hits
Roblox's triangle limit.

```
Root
└ Hips
  ├ Torso
  │ ├ Cockpit   ├ Head ─ Factsphere   ├ Harken_L   ├ Harken_R
  │ ├ Shoulder_L ─ UpperArm_L ─ LowerArm_L ┬ Hand_L
  │ │                                      └ Tonfa_L
  │ └ Shoulder_R ─ UpperArm_R ─ LowerArm_R ┬ Hand_R ─ Rifle
  │                                        └ Tonfa_R
  ├ Thigh_L ─ Shin_L ─ Foot_L ─ Landspinner_L
  └ Thigh_R ─ Shin_R ─ Foot_R ─ Landspinner_R
```

### Part names the script looks for

One mesh object per rigid piece, with its origin at the joint it pivots
around. Model faces -Y, Z up, meters, feet on Z = 0. `_L`/`_R` are the
mech's own left (+X) and right (-X).

`SM_Hips`, `SM_Torso`, `SM_Cockpit`, `SM_Head`, `SM_Factsphere`,
`SM_Shoulder_L/R`, `SM_UpperArm_L/R`, `SM_LowerArm_L/R`, `SM_Hand_L/R`,
`SM_Tonfa_L/R`, `SM_Rifle`, `SM_Harken_L/R`, `SM_Thigh_L/R`, `SM_Shin_L/R`,
`SM_Foot_L/R`, `SM_Landspinner_L/R`.

Matching ignores case and punctuation, and a few aliases work (`Chest`,
`Forearm_L`, `StunTonfa_L`, `SlashHarken_L`, `Wheel_L`…). Any other mesh
(trim, armor plates) follows its parent object's bone, or the nearest bone.
A missing part just gets a default joint position scaled to the model's
height.

## Running it

```bash
# Blender 4.4+ (tested with 5.0)
blender -b sutherland.blend --python sutherland/rig/rig_and_animate.py -- --out export

# or with the bpy module (pip install bpy)
python sutherland/rig/rig_and_animate.py --blend sutherland.blend --out export

# gray-box stand-in, to try the rig without the model
python sutherland/rig/rig_and_animate.py --proxy --out export_proxy
```

It prints which object went to which bone. Output in `export/`:
`Sutherland_Rigged.fbx`, one `Anim_<Name>.fbx` per animation, and
`Sutherland_Rigged.blend` with every action kept for hand-tweaking.

## Getting it into Roblox

1. **Model**: Studio → Avatar/Home → *Import 3D* → `Sutherland_Rigged.fbx`.
   Rig type: custom/general. Check the size in the preview and scale it to
   roughly 15–18 studs tall (about 3× a player). The importer adds an
   `AnimationController` with an `Animator`.
2. **Animations**: select the model → *Animation Editor* → `⋯` → *Import* →
   *From FBX Animation* → pick an `Anim_<Name>.fbx`. Publish it to Roblox
   (`⋯` → *Publish to Roblox*), set *Looping* for Idle/Walk/Landspinner,
   and copy the asset id. Repeat for each file.
3. **Code**: put `SutherlandAnimator.lua` in `ReplicatedStorage` as a
   ModuleScript, paste the asset ids into `ANIMATION_IDS`, then:

   ```lua
   local SutherlandAnimator = require(game.ReplicatedStorage.SutherlandAnimator)
   local anim = SutherlandAnimator.new(workspace.Sutherland)
   anim:setMovement(speed, true)   -- true = landspinners, false = walking
   anim:setAiming(true)
   anim:fire()
   anim:harken("L")
   ```

The harken cable is a `Beam` from the chest mount to the `Harken_L/R`
bone, so it stretches with the animation and hides when the harken is
back.
