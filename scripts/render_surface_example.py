"""Render the documented surface example in a fresh Blender background session.

Run Blender with a system temporary directory as its working directory.
This script writes only the intended render and height-map example images.
"""

from pathlib import Path
import sys

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "images"
OUTPUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

VARIANTS = {
    "steel": {
        "seed": 51,
        "iterations": 460,
        "strength": 0.065,
        "metallic": 0.18,
        "roughness": 0.68,
        "view_scale": 1.55,
        "file": "surface_panel.png",
        "colors": (
            (0, (0.01, 0.025, 0.04)),
            (0.32, (0.025, 0.075, 0.16)),
            (0.46, (0.025, 0.22, 0.27)),
            (0.52, (0.14, 0.22, 0.38)),
            (0.58, (0.35, 0.18, 0.08)),
            (0.64, (0.02, 0.25, 0.19)),
            (0.70, (0.20, 0.27, 0.42)),
            (0.76, (0.38, 0.30, 0.15)),
            (0.84, (0.28, 0.34, 0.29)),
            (1, (0.28, 0.34, 0.29)),
        ),
        "lights": ((0.85, 0.91, 1), (0.64, 0.82, 1), (1, 0.74, 0.56)),
    },
    "copper": {
        "seed": 84,
        "iterations": 580,
        "strength": 0.07,
        "metallic": 0.25,
        "roughness": 0.62,
        "view_scale": 1.3,
        "file": "surface_copper.png",
        "colors": (
            (0, (0.02, 0.018, 0.02)),
            (0.32, (0.02, 0.15, 0.17)),
            (0.46, (0.45, 0.12, 0.035)),
            (0.52, (0.03, 0.07, 0.12)),
            (0.58, (0.025, 0.25, 0.27)),
            (0.64, (0.48, 0.22, 0.08)),
            (0.70, (0.18, 0.06, 0.10)),
            (0.76, (0.35, 0.28, 0.11)),
            (0.84, (0.25, 0.18, 0.13)),
            (1, (0.25, 0.18, 0.13)),
        ),
        "lights": ((1, 0.84, 0.7), (0.72, 0.85, 1), (1, 0.56, 0.32)),
    },
    "violet": {
        "seed": 143,
        "iterations": 340,
        "strength": 0.045,
        "metallic": 0.20,
        "roughness": 0.64,
        "view_scale": 1.0,
        "file": "surface_violet.png",
        "colors": (
            (0, (0.018, 0.018, 0.037)),
            (0.32, (0.06, 0.05, 0.26)),
            (0.46, (0.23, 0.07, 0.35)),
            (0.52, (0.015, 0.25, 0.30)),
            (0.58, (0.43, 0.08, 0.26)),
            (0.64, (0.035, 0.08, 0.23)),
            (0.70, (0.31, 0.22, 0.49)),
            (0.76, (0.40, 0.17, 0.07)),
            (0.84, (0.16, 0.21, 0.36)),
            (1, (0.16, 0.21, 0.36)),
        ),
        "lights": ((0.87, 0.82, 1), (0.6, 0.76, 1), (1, 0.66, 0.8)),
    },
}
variant = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "steel"
if variant not in VARIANTS:
    raise ValueError("Unknown render variant: " + variant)
settings = VARIANTS[variant]

import displacementx_addon as package
from displacementx_addon import addon


bpy.ops.wm.read_factory_settings(use_empty=True)
package.register()
scene = bpy.context.scene
props = scene.displacementx
addon._initialize_scene_stops()
props.iterations = settings["iterations"]
props.seed = settings["seed"]
props.resolution = 2048
props.auto_subdivision = False
props.subdivision_level = 10
props.displacement_strength = settings["strength"]
props.sprites_enabled = True
props.sprite_pack_classic = variant != "steel"
props.sprite_pack_circuitry = True
props.sharp_color_edges = True
props.stops.clear()
for position, color in settings["colors"]:
    stop = props.stops.add()
    stop.pos = position
    stop.color = color

bpy.ops.mesh.primitive_plane_add(size=2.5)
panel = bpy.context.object
panel.name = "Synth Surface plane"
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.subdivide(number_cuts=1)
bpy.ops.object.mode_set(mode="OBJECT")
assert bpy.ops.dx.apply() == {"FINISHED"}
surface_bsdf = panel.active_material.node_tree.nodes.get("Principled BSDF")
surface_bsdf.inputs["Metallic"].default_value = settings.get("metallic", 0.55)
surface_bsdf.inputs["Roughness"].default_value = settings.get("roughness", 0.46)

if variant == "steel":
    height = bpy.data.images[addon.HEIGHT_IMAGE_NAME]
    height.filepath_raw = str(OUTPUT / "height_map.png")
    height.file_format = "PNG"
    height.save()

bpy.ops.object.camera_add(location=(2.5, -3.0, 5.0))
camera = bpy.context.object
camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.type = "ORTHO"
camera.data.ortho_scale = settings["view_scale"]
scene.camera = camera

for (location, energy, size), color in zip((
    ((-3, -2, 5), 650, 4),
    ((2, 2, 3), 500, 3),
    ((2, -3, 2), 280, 2),
), settings["lights"]):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.object
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size
    light.data.color = color

scene.world = bpy.data.worlds.new("Example world")
scene.world.use_nodes = True
scene.world.node_tree.nodes.get("Background").inputs["Color"].default_value = (0.018, 0.025, 0.036, 1)
scene.world.node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.6
scene.render.engine = "CYCLES"
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "AgX"
scene.render.filepath = str(OUTPUT / settings["file"])
bpy.ops.render.render(write_still=True)
if variant == "steel":
    camera.data.ortho_scale = 0.85
    scene.render.filepath = str(OUTPUT / "surface_detail.png")
    bpy.ops.render.render(write_still=True)
print("EXAMPLE RENDER PASS", flush=True)
