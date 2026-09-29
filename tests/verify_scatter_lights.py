"""Run with Blender --background --factory-startup --python this_file.py."""
import sys
import os
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import displacementx_addon as package
from displacementx_addon import addon, core, scatter


def pixels(image):
    data = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(data)
    return data.reshape(image.size[1], image.size[0], 4)


def verify_core():
    s = {"lights_enabled": True, "lights_density": 80, "lights_seed": -51,
         "lights_scale": 0.03, "lights_color_mode": "PALETTE"}
    first = scatter.generate_emission(s, (512, 256))
    assert np.array_equal(first, scatter.generate_emission(s, (512, 256)))
    assert not np.array_equal(first, scatter.generate_emission(dict(s, lights_seed=52), (512, 256)))
    assert scatter.generate_emission(dict(s, lights_enabled=False), 128) is None
    assert not scatter.generate_emission(dict(s, lights_density=0), 128).any()
    # Actual positions/diameters remain identical in normalized coordinates.
    assert np.array_equal(scatter.light_layout(s, (512, 256)), scatter.light_layout(s, (2048, 1024)))
    grid = scatter.light_layout(dict(s, lights_randomness=0, lights_density=64), 256)
    assert len(np.unique(grid[:, 0])) == len(np.unique(grid[:, 1])) == 8
    assert np.array_equal(grid[:, :2], scatter.light_layout(dict(s, lights_randomness=0,
        lights_density=64, lights_scale=0.07, lights_color_mode="SINGLE"), 256)[:, :2])
    # Isolated shapes remain round/square on rectangular canvases.
    single = dict(s, lights_density=1, lights_randomness=0, lights_scale=0.1,
                  lights_scale_randomness=0, lights_intensity_randomness=0,
                  lights_color_mode="SINGLE", lights_color=(1, 0, 0))
    circle = scatter.generate_emission(single, (512, 256))
    square = scatter.generate_emission(dict(single, lights_shape="SQUARE"), (512, 256))
    yy, xx = np.where(circle[:, :, 0] > 128)
    assert np.ptp(xx) == np.ptp(yy)
    assert 0.72 < circle.sum() / square.sum() < 0.85
    assert not circle[:, :, 1:].any()
    assert np.array_equal(square, scatter.generate_emission(
        dict(single, lights_shape="SQUARE", lights_intensity=100), (512, 256)))
    # Palette uses whole per-light colors, with no interpolation between entries.
    palette = scatter.generate_emission(dict(s, lights_scale=0.008), 512, [(1, 0, 0), (0, 0, 1)])
    assert palette[:, :, 0].any() and palette[:, :, 2].any()
    assert not palette[:, :, 1].any()
    assert scatter.generate_emission(s, 128, []).any()
    for shape in ("CIRCLE", "HEXAGON", "ROUNDED"):
        masked = scatter.generate_emission(dict(s, canvas_shape=shape), (256, 128))
        mask = core.generate_canvas_mask((256, 128), shape)
        assert not masked[~mask].any()
    # Stamp at a boundary: periodic wrapping preserves its energy.
    wrapped = np.zeros((64, 64, 3), dtype=np.uint8)
    centered = wrapped.copy()
    clipped = wrapped.copy()
    for shape in ("ROUND", "SQUARE"):
        wrapped.fill(0); centered.fill(0); clipped.fill(0)
        scatter._stamp_light(wrapped, 0, 0, 4, np.array([1, 0.5, 0]), shape, True)
        scatter._stamp_light(centered, 32, 32, 4, np.array([1, 0.5, 0]), shape, True)
        scatter._stamp_light(clipped, 0, 0, 4, np.array([1, 0.5, 0]), shape, False)
        assert wrapped.sum() == centered.sum()
        assert clipped.sum() * 4 == wrapped.sum()
    color = np.full((256, 512, 4), 40, dtype=np.uint8)
    color[:, :, 3] = 0
    preview = scatter.preview_with_lights(color, first, 5)
    assert np.array_equal(preview[:, :, 3], color[:, :, 3])
    assert preview[:, :, :3].sum() > color[:, :, :3].sum()
    assert scatter.preview_with_lights(color, first, 0) is color
    # Light settings cannot perturb the existing height map RNG.
    hs = dict(core.DEFAULT_SETTINGS, iterations=20)
    assert np.array_equal(core.generate_height(hs, 128, seed=8),
                          core.generate_height(dict(hs, **s), 128, seed=8))
    start = time.monotonic()
    large = scatter.generate_emission(dict(s, lights_density=5000, lights_scale=0.004), 2048)
    assert large.shape == (2048, 2048, 3)
    print("CORE PASS; 2K / 5,000 lights: %.3fs" % (time.monotonic() - start), flush=True)


def verify_blender():
    package.register()
    p = bpy.context.scene.displacementx
    assert not p.lights_enabled  # Safe default for existing projects.
    addon._initialize_scene_stops()
    assert len(p.light_palette) == 5
    bpy.ops.dx.add_light_color()
    assert len(p.light_palette) == 6
    bpy.ops.dx.delete_light_color(index=5)
    for unused in range(10):
        bpy.ops.dx.delete_light_color(index=0)
    assert len(p.light_palette) == 1
    bpy.ops.dx.reset_light_palette()
    assert len(p.light_palette) == 5
    p.iterations = 10
    p.resolution = 128
    p.auto_subdivision = False
    p.subdivision_level = 0
    p.displacement_strength = 0
    bpy.ops.dx.apply()
    original_height = pixels(bpy.data.images[addon.HEIGHT_IMAGE_NAME]).copy()
    original_color = pixels(bpy.data.images[addon.COLOR_IMAGE_NAME]).copy()
    original_normal = pixels(bpy.data.images[addon.NORMAL_IMAGE_NAME]).copy()
    p.lights_enabled = True
    p.lights_color_mode = "PALETTE"
    p.lights_intensity = 7.5
    p.lights_scale = 2.5
    p.lights_density = 50
    p.seamless = True
    bpy.ops.dx.apply()
    # seamless also changes base generation; turn it off for regression comparison.
    p.seamless = False
    bpy.ops.dx.apply()
    assert np.array_equal(original_height, pixels(bpy.data.images[addon.HEIGHT_IMAGE_NAME]))
    assert np.array_equal(original_color, pixels(bpy.data.images[addon.COLOR_IMAGE_NAME]))
    assert np.array_equal(original_normal, pixels(bpy.data.images[addon.NORMAL_IMAGE_NAME]))
    mat = bpy.context.object.active_material
    node = mat.node_tree.nodes["Synth Surface Scatter Lights"]
    assert node.image.name == addon.EMISSION_IMAGE_NAME
    assert node.image.packed_file is not None
    assert node.image.colorspace_settings.name == "Non-Color"
    expected = scatter.generate_emission(addon._core_settings_from_props(p), 128,
                                        addon._light_palette_from_props(p))
    np.testing.assert_allclose(pixels(node.image)[:, :, :3], expected / 255, atol=1e-7)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    assert bsdf.inputs["Emission Color"].is_linked
    assert bsdf.inputs["Emission Strength"].default_value == 7.5
    p.aspect_ratio = "LANDSCAPE_2_1"
    p.resolution = 256
    p.canvas_shape = "CIRCLE"
    p.mask_outside = "TRANSPARENT"
    p.lights_shape = "SQUARE"
    p.seamless = True
    bpy.ops.dx.apply()
    node = mat.node_tree.nodes["Synth Surface Scatter Lights"]
    assert tuple(node.image.size) == (256, 128)
    assert node.extension == "REPEAT"
    assert not pixels(node.image)[0, 0, :3].any()
    assert pixels(bpy.data.images[addon.COLOR_IMAGE_NAME])[0, 0, 3] == 0
    preview = addon._preview_color(p)
    assert preview.shape == (128, 256, 4)
    assert not preview[0, 0, 3]
    assert len([im for im in bpy.data.images if im.name.startswith(addon.EMISSION_IMAGE_NAME)]) == 1
    # Exercise the actual preview operator / icon upload twice.
    assert bpy.ops.dx.update_preview() == {"FINISHED"}
    p.lights_seed += 1
    assert bpy.ops.dx.update_preview() == {"FINISHED"}
    p.lights_enabled = False
    bpy.ops.dx.apply()
    assert "Synth Surface Scatter Lights" not in mat.node_tree.nodes
    p.lights_enabled = True
    bpy.ops.dx.apply()
    saved_emission = pixels(bpy.data.images[addon.EMISSION_IMAGE_NAME]).copy()
    # Save/reopen verifies registered settings and packed image persistence.
    with tempfile.TemporaryDirectory(prefix="synth_lights_") as temp:
        path = str(Path(temp) / "verify.blend")
        previous_cwd = os.getcwd()
        try:
            os.chdir(temp)
            bpy.ops.wm.save_as_mainfile(filepath=path)
        finally:
            os.chdir(previous_cwd)
        bpy.ops.wm.open_mainfile(filepath=path)
        p = bpy.context.scene.displacementx
        assert p.lights_enabled and p.lights_shape == "SQUARE"
        assert len(p.light_palette) == 5
        assert bpy.data.images[addon.EMISSION_IMAGE_NAME].packed_file is not None
        np.testing.assert_allclose(pixels(bpy.data.images[addon.EMISSION_IMAGE_NAME]),
                                   saved_emission, atol=1.0 / 255.0)
        bpy.ops.dx.apply()
    package.unregister()
    package.register()
    p = bpy.context.scene.displacementx
    assert p.lights_enabled and p.lights_shape == "SQUARE"
    assert p.lights_scale == 2.5 and len(p.light_palette) == 5
    package.unregister()
    print("BLENDER INTEGRATION PASS", flush=True)


verify_core()
verify_blender()
