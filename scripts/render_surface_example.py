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
            (0, (0.012, 0.025, 0.038)),
            (0.34, (0.035, 0.085, 0.13)),
            (0.48, (0.065, 0.2, 0.23)),
            (0.58, (0.19, 0.26, 0.3)),
            (0.67, (0.31, 0.24, 0.17)),
            (0.76, (0.14, 0.29, 0.3)),
            (1, (0.31, 0.39, 0.37)),
        ),
        "lights": ((0.85, 0.91, 1), (0.64, 0.82, 1), (1, 0.74, 0.56)),
    },
    "copper": {
        "seed": 84,
        "iterations": 580,
        "strength": 0.07,
        "view_scale": 1.3,
        "file": "surface_copper.png",
        "colors": (
            (0, (0.018, 0.02, 0.025)),
            (0.34, (0.035, 0.075, 0.09)),
            (0.48, (0.13, 0.12, 0.1)),
            (0.58, (0.29, 0.14, 0.075)),
            (0.67, (0.1, 0.2, 0.23)),
            (0.76, (0.39, 0.24, 0.13)),
            (1, (0.5, 0.34, 0.21)),
        ),
        "lights": ((1, 0.84, 0.7), (0.72, 0.85, 1), (1, 0.56, 0.32)),
    },
    "violet": {
        "seed": 143,
        "iterations": 340,
        "strength": 0.045,
        "view_scale": 1.0,
        "file": "surface_violet.png",
        "colors": (
            (0, (0.018, 0.018, 0.037)),
            (0.34, (0.055, 0.045, 0.12)),
            (0.48, (0.09, 0.12, 0.24)),
            (0.58, (0.27, 0.1, 0.27)),
            (0.67, (0.09, 0.21, 0.25)),
            (0.76, (0.29, 0.21, 0.37)),
            (1, (0.42, 0.33, 0.49)),
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
props.resolution = 1024
props.auto_subdivision = False
props.subdivision_level = 10
props.displacement_strength = settings["strength"]
props.sprites_enabled = True
props.sprite_pack_classic = variant != "steel"
props.sprite_pack_circuitry = True
props.stops.clear()
for position, color in settings["colors"]:
    stop = props.stops.add()
    stop.pos = position
    stop.color = color

bpy.ops.mesh.primitive_plane_add(size=2.5)
panel = bpy.context.object
panel.name = "Synth Surface plane"
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
