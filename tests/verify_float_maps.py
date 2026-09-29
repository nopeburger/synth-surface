"""Verify float precision, color conversion, displacement, EXR and packed persistence.

Run Blender background with a system temporary working directory and an
absolute --python path. All generated files are removed with their temp folder.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import struct
import sys
import time

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


def exr_channel_types(raw):
    assert raw[:4] == b"\x76\x2f\x31\x01", "Packed/exported map must be EXR"
    offset = 8
    while raw[offset]:
        end = raw.index(b"\0", offset)
        name = raw[offset:end]
        offset = end + 1
        end = raw.index(b"\0", offset)
        kind = raw[offset:end]
        offset = end + 1
        length = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        payload = raw[offset:offset + length]
        offset += length
        if name == b"channels":
            assert kind == b"chlist"
            types = []
            cursor = 0
            while payload[cursor]:
                cursor = payload.index(b"\0", cursor) + 1
                types.append(struct.unpack_from("<i", payload, cursor)[0])
                cursor += 16
            return types
    raise AssertionError("Missing EXR channel list")


def verify_core():
    source, alpha, initial = 0.7312345, 0.234567, 0.4123456
    expected = source * alpha + initial * (1 - alpha)
    destination = np.full((1, 1), initial, dtype=np.float32)
    core._composite_premultiplied(destination, None, source * alpha, alpha, "source-over")
    np.testing.assert_allclose(destination, expected, atol=1e-7)
    assert abs(float(destination[0, 0]) * 255 - round(float(destination[0, 0]) * 255)) > 0.01
    for mode in core.COMPOSITION_MODES:
        destination = np.full((2, 2), initial, dtype=np.float32)
        opacity = np.full((2, 2), 0.63, dtype=np.float32)
        core._composite_premultiplied(destination, opacity, source * alpha, alpha, mode)
        assert np.isfinite(destination).all() and np.isfinite(opacity).all()
        assert 0 <= destination.min() <= destination.max() <= 1
        assert 0 <= opacity.min() <= opacity.max() <= 1
    settings = dict(core.DEFAULT_SETTINGS, iterations=120, sprites_enabled=True)
    height = core.generate_height(settings, (256, 128), seed=91)
    assert height.dtype == np.float32 and np.isfinite(height).all()
    assert len(np.unique(height)) > 256
    assert np.array_equal(height, core.generate_height(settings, (256, 128), seed=91))
    for mode in core.COMPOSITION_MODES:
        config = dict(settings, iterations=30)
        config.update({"comp_" + name: name == mode for name in core.COMPOSITION_MODES})
        generated = core.generate_height(config, (64, 32), seed=12)
        assert generated.dtype == np.float32 and np.isfinite(generated).all()
        assert 0 <= generated.min() <= generated.max() <= 1
    ramp = np.linspace(0, 1, 2049, dtype=np.float32)[None, :]
    color = core.generate_color(ramp, [(0, (0, 0, 0)), (1, (255, 127.123456, 31.234567))])
    assert color.dtype == np.float32 and len(np.unique(color[..., 0])) == 2049
    np.testing.assert_allclose(color[..., 1], ramp * (127.123456 / 255), atol=1e-7)
    sharp = core.generate_color(ramp, [(0, (31.234567, 0, 0)), (0.5, (255, 0, 0))], sharp=True)
    np.testing.assert_allclose(sharp[0, 0, 0], 31.234567 / 255, atol=1e-7)
    normal = core.generate_normal(ramp)
    assert normal.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(normal * 2 - 1, axis=2), 1, atol=2e-7)
    np.testing.assert_array_equal(core.generate_normal(np.full((2, 2), 0.5, np.float32)),
                                  np.broadcast_to([0.5, 0.5, 1], (2, 2, 3)))
    masked = core.generate_height(dict(settings, canvas_shape="CIRCLE", mask_outside="NEUTRAL"),
                                  (64, 32), seed=4)
    assert masked[0, 0] == 0.5
    emission = scatter.generate_emission({"lights_enabled": True, "lights_density": 1,
        "lights_randomness": 0, "lights_scale": 0.1, "lights_scale_randomness": 0,
        "lights_intensity_randomness": 0, "lights_shape": "SQUARE",
        "lights_color": (0.1234567, 0.2345678, 0.3456789)}, 128)
    assert emission.dtype == np.float32
    np.testing.assert_allclose(emission[64, 64], [0.1234567, 0.2345678, 0.3456789], atol=1e-7)
    print("FLOAT CORE PRECISION PASS", flush=True)


def verify_blender():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    package.register()
    bpy.ops.mesh.primitive_plane_add()
    props = bpy.context.scene.displacementx
    addon._initialize_scene_stops()
    props.resolution = 128
    props.iterations = 80
    props.sprites_enabled = True
    props.lights_enabled = True
    props.lights_scale = 2
    props.auto_subdivision = False
    props.subdivision_level = 0
    props.displacement_strength = 1
    # A byte image from an existing 1.1 project must be replaced on Apply.
    bpy.data.images.new(addon.HEIGHT_IMAGE_NAME, width=128, height=128, alpha=True)
    assert bpy.ops.dx.apply() == {"FINISHED"}
    names = (addon.COLOR_IMAGE_NAME, addon.HEIGHT_IMAGE_NAME,
             addon.NORMAL_IMAGE_NAME, addon.EMISSION_IMAGE_NAME)
    for name in names:
        image = bpy.data.images[name]
        assert image.is_float and image.packed_file is not None
        assert set(exr_channel_types(image.packed_file.data)) == {2}, "Packed EXR must use FLOAT channels"
    assert len([im for im in bpy.data.images if im.name.startswith(addon.HEIGHT_IMAGE_NAME)]) == 1
    original_height = pixels(bpy.data.images[addon.HEIGHT_IMAGE_NAME]).copy()
    props.invert = True
    bpy.ops.dx.apply()
    np.testing.assert_allclose(pixels(bpy.data.images[addon.HEIGHT_IMAGE_NAME])[..., :3],
                               1 - original_height[..., :3], atol=1e-7)
    props.invert = False
    bpy.ops.dx.apply()
    value = np.float32(0.50012345)
    addon._make_image(addon.HEIGHT_IMAGE_NAME, np.full((128, 128), value, np.float32), "Non-Color")
    bpy.context.view_layer.update()
    evaluated = bpy.context.object.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        np.testing.assert_allclose([v.co.z for v in mesh.vertices], float(value) - 0.5, atol=2e-7)
    finally:
        evaluated.to_mesh_clear()
    swatch = addon._make_image("Float Color Probe", np.full((2, 2, 3), 0.5, np.float32), "sRGB")
    np.testing.assert_allclose(pixels(swatch)[..., :3], ((0.5 + 0.055) / 1.055) ** 2.4, atol=1e-7)
    assert bpy.ops.dx.update_preview() == {"FINISHED"}
    snapshots = {name: pixels(bpy.data.images[name]).copy() for name in names}
    render_settings = (bpy.context.scene.render.image_settings.file_format,
                       bpy.context.scene.render.image_settings.color_depth)
    with TemporaryDirectory(prefix="synth_float_") as directory:
        assert bpy.ops.dx.export_exr(directory=directory) == {"FINISHED"}
        outputs = {"synth_surface_color.exr": names[0], "synth_surface_height.exr": names[1],
                   "synth_surface_normal.exr": names[2], "synth_surface_lights.exr": names[3]}
        for filename, name in outputs.items():
            path = Path(directory) / filename
            assert set(exr_channel_types(path.read_bytes())) == {2}
            loaded = bpy.data.images.load(str(path), check_existing=False)
            np.testing.assert_allclose(pixels(loaded), snapshots[name], atol=1e-7)
            bpy.data.images.remove(loaded)
        assert render_settings == (bpy.context.scene.render.image_settings.file_format,
                                   bpy.context.scene.render.image_settings.color_depth)
        previous_cwd = os.getcwd()
        try:
            os.chdir(directory)
            blend = str(Path(directory) / "float_maps.blend")
            bpy.ops.wm.save_as_mainfile(filepath=blend)
        finally:
            os.chdir(previous_cwd)
        bpy.ops.wm.open_mainfile(filepath=blend)
        for name in names:
            image = bpy.data.images[name]
            assert image.is_float
            np.testing.assert_allclose(pixels(image), snapshots[name], atol=1e-7)
    package.unregister()
    print("FLOAT BLENDER / EXR / PACKED PERSISTENCE PASS", flush=True)


def verify_large():
    """Optional 4K upload/packing check, without subdividing a large mesh."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    package.register()
    bpy.ops.mesh.primitive_plane_add()
    props = bpy.context.scene.displacementx
    addon._initialize_scene_stops()
    props.iterations = 40
    props.auto_subdivision = False
    props.subdivision_level = 0
    props.lights_enabled = True
    props.lights_density = 80
    props.resolution = 128
    bpy.ops.dx.apply()
    props.resolution = 4096
    start = time.monotonic()
    assert bpy.ops.dx.apply() == {"FINISHED"}
    for name in (addon.COLOR_IMAGE_NAME, addon.HEIGHT_IMAGE_NAME,
                 addon.NORMAL_IMAGE_NAME, addon.EMISSION_IMAGE_NAME):
        image = bpy.data.images[name]
        assert image.is_float and tuple(image.size) == (4096, 4096)
        assert set(exr_channel_types(image.packed_file.data)) == {2}
        assert len([im for im in bpy.data.images if im.name.startswith(name)]) == 1
    print("4K FLOAT GENERATION / RESIZE / PACKING PASS: %.2fs" % (time.monotonic() - start), flush=True)
    package.unregister()


verify_core()
verify_blender()
if "--large" in sys.argv:
    verify_large()
