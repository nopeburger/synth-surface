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

import displacementx_addon as package
from displacementx_addon import addon


bpy.ops.wm.read_factory_settings(use_empty=True)
package.register()
scene = bpy.context.scene
props = scene.displacementx
addon._initialize_scene_stops()
props.iterations = 460
props.seed = 51
props.resolution = 1024
props.auto_subdivision = False
props.subdivision_level = 7
props.displacement_strength = 0.3
props.sprites_enabled = True
props.sprite_pack_classic = True
props.sprite_pack_circuitry = True
props.stops.clear()
for position, color in (
    (0, (0.012, 0.025, 0.038)),
    (0.42, (0.055, 0.11, 0.15)),
    (0.78, (0.23, 0.39, 0.43)),
    (1, (0.7, 0.82, 0.73)),
):
    stop = props.stops.add()
    stop.pos = position
    stop.color = color

bpy.ops.mesh.primitive_plane_add(size=2.5)
panel = bpy.context.object
panel.name = "Synth Surface panel"
assert bpy.ops.dx.apply() == {"FINISHED"}
panel.active_material.node_tree.nodes.get("Principled BSDF").inputs["Metallic"].default_value = 0.55
panel.active_material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.46

height = bpy.data.images[addon.HEIGHT_IMAGE_NAME]
height.filepath_raw = str(OUTPUT / "height_map.png")
height.file_format = "PNG"
height.save()

solidify = panel.modifiers.new("Panel thickness", "SOLIDIFY")
solidify.thickness = 0.075
solidify.offset = -1

bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.17))
base = bpy.context.object
base.name = "Display plinth"
base.scale = (2.65, 2.65, 0.16)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bevel = base.modifiers.new("Soft corners", "BEVEL")
bevel.width = 0.04
bevel.segments = 3
base.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
base_mat = bpy.data.materials.new("Graphite plinth")
base_mat.diffuse_color = (0.018, 0.029, 0.039, 1)
base_mat.use_nodes = True
base_bsdf = base_mat.node_tree.nodes.get("Principled BSDF")
base_bsdf.inputs["Base Color"].default_value = base_mat.diffuse_color
base_bsdf.inputs["Metallic"].default_value = 0.65
base_bsdf.inputs["Roughness"].default_value = 0.35
base.data.materials.append(base_mat)

bpy.ops.object.camera_add(location=(3.3, -3.8, 3.25))
camera = bpy.context.object
camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.type = "ORTHO"
camera.data.ortho_scale = 4.3
scene.camera = camera

for location, energy, size, color in (
    ((-3, -2, 5), 650, 4, (0.75, 0.9, 1)),
    ((2, 2, 3), 500, 3, (0.47, 0.78, 1)),
    ((2, -3, 2), 280, 2, (1, 0.67, 0.42)),
):
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
scene.cycles.samples = 32
scene.cycles.use_denoising = True
scene.render.resolution_x = 1280
scene.render.resolution_y = 800
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "AgX"
scene.render.filepath = str(OUTPUT / "surface_panel.png")
bpy.ops.render.render(write_still=True)
print("EXAMPLE RENDER PASS", flush=True)
