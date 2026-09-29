"""Smoke-test the built install ZIP with Blender --background --factory-startup."""

from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import sys

import bpy


ARCHIVE = Path(__file__).resolve().parents[1] / "dist" / "synth_surface_v1.2.zip"
EXPECTED = {
    "displacementx_addon/__init__.py",
    "displacementx_addon/addon.py",
    "displacementx_addon/core.py",
    "displacementx_addon/scatter.py",
    "displacementx_addon/sprites/sprite_cache.npz",
    "displacementx_addon/LICENSE",
    "displacementx_addon/NOTICE.md",
}

with ZipFile(ARCHIVE) as archive:
    assert set(archive.namelist()) == EXPECTED
    assert archive.testzip() is None
    with TemporaryDirectory(prefix="synth_release_") as directory:
        archive.extractall(directory)
        sys.path.insert(0, directory)
        import displacementx_addon as package
        from displacementx_addon import addon, core

        bpy.ops.wm.read_factory_settings(use_empty=True)
        package.register()
        assert len(core._load_sprite_library(("classic",))["classic"]) == 17
        bpy.ops.mesh.primitive_cube_add()
        props = bpy.context.scene.displacementx
        addon._initialize_scene_stops()
        props.iterations = 12
        props.resolution = 128
        props.auto_subdivision = False
        props.subdivision_level = 1
        props.sprites_enabled = True
        assert bpy.ops.dx.apply() == {"FINISHED"}
        assert bpy.context.object.active_material is not None
        assert bpy.data.images[addon.HEIGHT_IMAGE_NAME].packed_file is not None
        assert package.bl_info["version"] == (1, 2, 0)
        for name in (addon.HEIGHT_IMAGE_NAME, addon.COLOR_IMAGE_NAME, addon.NORMAL_IMAGE_NAME):
            assert bpy.data.images[name].is_float
        assert hasattr(bpy.ops.dx, "export_exr")
        package.unregister()
        print("RELEASE ZIP INTEGRATION PASS", flush=True)
