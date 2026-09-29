"""Synth Surface - Blender add-on for procedural greeble textures.

Port of https://github.com/satelllte/displacementx (formerly JS Placement).
Generates color, height and normal maps from a set of tunable parameters, shows a
live preview, and applies the result to the selected object as a material + displacement.
"""
import bpy
import os
import random
import tempfile
import numpy as np
from bpy.props import (StringProperty, IntProperty, FloatProperty, BoolProperty,
                       FloatVectorProperty, CollectionProperty, EnumProperty)
from bpy.types import Panel, Operator, PropertyGroup
from .core import (generate_height, generate_normal, generate_color,
                   generate_canvas_mask,
                   randomize, get_sprite_pack_counts, DEFAULT_SETTINGS,
                   DEFAULT_COLOR_STOPS, COMPOSITION_MODES,
                   SPRITE_PACKS, SPRITE_PACK_LABELS)
from .scatter import (DEFAULT_LIGHT_PALETTE, generate_emission,
                      preview_with_lights)


_PREVIEW_COLLECTIONS = {}
PREVIEW_ICON_KEY = "displacementx_generated_preview"
_PREVIEW_REVISION = 0
_CURRENT_PREVIEW_FILE = None
_DEFAULT_STOP_TIMER_PENDING = False
AUTO_SUBDIV_MAX_FACES = 2_000_000
COLOR_IMAGE_NAME = "Synth Surface Color"
NORMAL_IMAGE_NAME = "Synth Surface Normal"
HEIGHT_IMAGE_NAME = "Synth Surface Height"
EMISSION_IMAGE_NAME = "Synth Surface Lights"
PREVIEW_IMAGE_NAME = "Synth Surface Preview"
MATERIAL_NAME = "Synth Surface"
DISPLACE_TEXTURE_NAME = "Synth Surface Displacement"
WELD_MODIFIER_NAME = "Synth Surface Weld"
SUBDIVISION_MODIFIER_NAME = "Synth Surface Subdivision"
DISPLACE_MODIFIER_NAME = "Synth Surface Displace"
ASPECT_PRESETS = {
    "SQUARE": (1, 1),
    "LANDSCAPE_2_1": (2, 1),
    "LANDSCAPE_4_1": (4, 1),
    "WIDESCREEN_16_9": (16, 9),
    "PORTRAIT_1_2": (1, 2),
    "PORTRAIT_9_16": (9, 16),
}
OUTPUT_PIXEL_WARNING = 32_000_000


def _output_dimensions(props):
    """Resolve the UI preset/custom controls to (width, height)."""
    if props.aspect_ratio == "CUSTOM":
        return max(1, int(props.custom_width)), max(1, int(props.custom_height))
    ratio_width, ratio_height = ASPECT_PRESETS.get(
        props.aspect_ratio, ASPECT_PRESETS["SQUARE"]
    )
    long_edge = max(1, int(props.resolution))
    if ratio_width >= ratio_height:
        return long_edge, max(1, round(long_edge * ratio_height / ratio_width))
    return max(1, round(long_edge * ratio_width / ratio_height)), long_edge


def _preview_dimensions(width, height, max_edge=256):
    """Fit output dimensions inside the preview box without changing ratio."""
    scale = min(1.0, float(max_edge) / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _transparent_canvas_mask(settings, width, height):
    """Return an alpha mask only for the Transparent outside-mask mode."""
    if (
        settings.get("canvas_shape", "FULL") == "FULL"
        or settings.get("mask_outside", "BACKGROUND") != "TRANSPARENT"
    ):
        return None
    return generate_canvas_mask(
        (width, height),
        settings.get("canvas_shape", "FULL"),
        settings.get("mask_roundness", 0.15),
    )


def _get_or_migrate_datablock(collection, name, legacy_names=()):
    """Reuse a Synth Surface block or rename an earlier Displacement X block."""
    datablock = collection.get(name)
    if datablock is not None:
        return datablock
    for legacy_name in legacy_names:
        datablock = collection.get(legacy_name)
        if datablock is not None:
            datablock.name = name
            return datablock
    return None


def _recommended_subdivision_level(resolution):
    """Target about one displaced vertex for every eight texture pixels."""
    target_segments = max(1, (int(resolution) + 7) // 8)
    level = 0
    segments = 1
    while segments < target_segments and level < 10:
        segments *= 2
        level += 1
    return level


def _safe_auto_subdivision_level(obj, desired_level):
    """Avoid multiplying an already-dense mesh beyond a practical face count."""
    polygon_count = max(1, len(obj.data.polygons))
    level = int(desired_level)
    while level > 0 and polygon_count * (4 ** level) > AUTO_SUBDIV_MAX_FACES:
        level -= 1
    return level


def _core_settings_from_props(props):
    d = dict(DEFAULT_SETTINGS)
    d["iterations"] = props.iterations
    d["background_brightness"] = props.background_brightness
    d["seamless"] = props.seamless
    d["canvas_shape"] = props.canvas_shape
    d["mask_outside"] = props.mask_outside
    d["mask_roundness"] = props.mask_roundness
    for s in ["rect", "grid", "cols", "rows"]:
        d[s + "_enabled"] = getattr(props, s + "_enabled")
        d[s + "_brightness_min"] = getattr(props, s + "_brightness_min")
        d[s + "_brightness_max"] = getattr(props, s + "_brightness_max")
        d[s + "_alpha_min"] = getattr(props, s + "_alpha_min")
        d[s + "_alpha_max"] = getattr(props, s + "_alpha_max")
        d[s + "_scale_min"] = getattr(props, s + "_scale_min")
        d[s + "_scale_max"] = getattr(props, s + "_scale_max")
    d["lines_enabled"] = props.lines_enabled
    d["lines_brightness_min"] = props.lines_brightness_min
    d["lines_brightness_max"] = props.lines_brightness_max
    d["lines_alpha_min"] = props.lines_alpha_min
    d["lines_alpha_max"] = props.lines_alpha_max
    for s in ["grid", "cols", "rows"]:
        d[s + "_amount_min"] = getattr(props, s + "_amount_min")
        d[s + "_amount_max"] = getattr(props, s + "_amount_max")
        d[s + "_gap_min"] = getattr(props, s + "_gap_min")
        d[s + "_gap_max"] = getattr(props, s + "_gap_max")
    d["lines_width_min"] = props.lines_width_min
    d["lines_width_max"] = props.lines_width_max
    d["sprites_enabled"] = props.sprites_enabled
    d["sprites_rotation_enabled"] = props.sprites_rotation_enabled
    for pack in SPRITE_PACKS:
        d["sprite_pack_" + pack] = getattr(props, "sprite_pack_" + pack)
    for m in COMPOSITION_MODES:
        d["comp_" + m] = getattr(props, "comp_" + m.replace("-", "_"))
    for name in ("enabled", "shape", "scale", "density", "intensity",
                 "randomness", "scale_randomness", "intensity_randomness",
                 "seed", "color_mode"):
        d["lights_" + name] = getattr(props, "lights_" + name)
    d["lights_scale"] = props.lights_scale / 100.0
    d["lights_color"] = _clamp_color(props.lights_color)
    return d


def _set_default_stops(props):
    props.stops.clear()
    for position, color in DEFAULT_COLOR_STOPS:
        stop = props.stops.add()
        stop.pos = position
        stop.color = tuple(channel / 255.0 for channel in color)


def _set_default_light_palette(props):
    props.light_palette.clear()
    for color in DEFAULT_LIGHT_PALETTE:
        props.light_palette.add().color = color


def _light_palette_from_props(props):
    if not props.light_palette:
        _set_default_light_palette(props)
    return [_clamp_color(entry.color) for entry in props.light_palette]


def _clamp_color(color):
    """Return a finite SDR color Blender and the 8-bit renderer can share."""
    channels = []
    for channel in color[:3]:
        value = float(channel)
        if not np.isfinite(value):
            value = 0.0
        channels.append(max(0.0, min(1.0, value)))
    return tuple(channels)


def _normalize_stop_colors(props):
    """Repair HDR/out-of-range values written by older unbounded pickers."""
    for stop in props.stops:
        current = tuple(float(channel) for channel in stop.color[:3])
        repaired = _clamp_color(current)
        if repaired != current:
            stop.color = repaired


def _ensure_default_stops(props):
    """Populate the usable default gradient whenever a scene has no stops."""
    if len(props.stops) == 0:
        _set_default_stops(props)
    else:
        _normalize_stop_colors(props)


def _initialize_scene_stops():
    """Timer callback: edit scene data outside Blender's restricted UI draw."""
    global _DEFAULT_STOP_TIMER_PENDING
    _DEFAULT_STOP_TIMER_PENDING = False
    for scene in tuple(bpy.data.scenes):
        props = getattr(scene, "displacementx", None)
        if props is not None:
            try:
                _ensure_default_stops(props)
                _light_palette_from_props(props)
            except (AttributeError, ReferenceError, RuntimeError):
                # A linked/read-only scene should not prevent other scenes from
                # receiving their defaults or break Blender's timer handler.
                continue
    return None


def _schedule_scene_stop_initialization():
    """Queue one safe initialization pass without ever breaking panel drawing."""
    global _DEFAULT_STOP_TIMER_PENDING
    if _DEFAULT_STOP_TIMER_PENDING:
        return
    try:
        timers = bpy.app.timers
        if not timers.is_registered(_initialize_scene_stops):
            timers.register(_initialize_scene_stops, first_interval=0.0)
        _DEFAULT_STOP_TIMER_PENDING = True
    except (AttributeError, RuntimeError, ValueError):
        # Operators still initialize stops synchronously if a particular
        # Blender build cannot schedule the timer.
        _DEFAULT_STOP_TIMER_PENDING = False


def _stops_from_props(props):
    _ensure_default_stops(props)
    stops = []
    for st in props.stops:
        color = _clamp_color(st.color)
        stops.append((st.pos, tuple(int(channel * 255) for channel in color)))
    if not stops:
        stops = list(DEFAULT_COLOR_STOPS)
    return stops


def _make_image(name, arr, colorspace, legacy_names=()):
    """Create/replace a Blender image from a uint8 HxW, HxWx3, or HxWx4 array."""
    arr = np.asarray(arr)
    if arr.ndim not in (2, 3) or (arr.ndim == 3 and arr.shape[2] not in (3, 4)):
        raise ValueError("Expected an HxW, HxWx3, or HxWx4 image array")
    h, w = arr.shape[0], arr.shape[1]
    img = _get_or_migrate_datablock(
        bpy.data.images, name, legacy_names=legacy_names
    )
    if img is not None and (
        tuple(img.size) != (w, h) or getattr(img, "channels", 4) != 4
    ):
        # In Blender 5.1, Image.scale() can update Image.size before its RNA
        # pixel collection is resized. An immediate foreach_set() then expects
        # the old buffer length (for example 2048 RGBA while writing 4096 RGBA).
        # Generated images are safe to replace, and material nodes are rebuilt
        # below after all maps have been uploaded.
        try:
            bpy.data.images.remove(img, do_unlink=True)
        except TypeError:
            bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, width=w, height=h, alpha=True)

    # Set before writing pixels: some Blender versions clear the image buffer
    # when its color space changes. Reusing the image also prevents orphaned
    # data blocks from accumulating after repeated generation.
    img.colorspace_settings.name = colorspace
    pixels = np.empty((h, w, 4), dtype=np.float32)
    scale = np.float32(1.0 / 255.0)
    if arr.ndim == 2:
        for channel in range(3):
            np.multiply(arr, scale, out=pixels[..., channel], casting="unsafe")
        pixels[..., 3] = 1.0
    else:
        np.multiply(arr[..., :3], scale, out=pixels[..., :3], casting="unsafe")
        if arr.shape[2] == 4:
            np.multiply(arr[..., 3], scale, out=pixels[..., 3], casting="unsafe")
        else:
            pixels[..., 3] = 1.0
    img.pixels.foreach_set(pixels.ravel())
    del pixels
    img.update()
    try:
        img.pack()
    except Exception:
        pass
    return img


class DXStop(PropertyGroup):
    pos: FloatProperty(name="Position", default=0.5, min=0.0, max=1.0)
    color: FloatVectorProperty(
        name="Color",
        subtype="COLOR",
        size=3,
        default=(0.5, 0.0, 1.0),
        min=0.0,
        max=1.0,
        soft_min=0.0,
        soft_max=1.0,
    )


class DXLightColor(PropertyGroup):
    color: FloatVectorProperty(
        name="Light Color", subtype="COLOR", size=3,
        default=DEFAULT_LIGHT_PALETTE[0], min=0.0, max=1.0,
    )


class DisplacementXSettings(PropertyGroup):
    iterations: IntProperty(name="Iterations", default=1500, min=1, max=10000)
    background_brightness: IntProperty(name="Background", default=128, min=0, max=255)
    seamless: BoolProperty(name="Seamless", default=False)
    aspect_ratio: EnumProperty(
        name="Aspect Ratio",
        description="Output proportions; existing scenes remain Square by default",
        items=(
            ("SQUARE", "Square (1:1)", "Square output"),
            ("LANDSCAPE_2_1", "Landscape (2:1)", "Twice as wide as tall"),
            ("LANDSCAPE_4_1", "Landscape (4:1)", "Four times as wide as tall"),
            ("WIDESCREEN_16_9", "Widescreen (16:9)", "Widescreen landscape output"),
            ("PORTRAIT_1_2", "Portrait (1:2)", "Twice as tall as wide"),
            ("PORTRAIT_9_16", "Portrait (9:16)", "Widescreen portrait output"),
            ("CUSTOM", "Custom", "Set width and height independently"),
        ),
        default="SQUARE",
    )
    resolution: IntProperty(
        name="Long Edge",
        description="Pixel size of the longest output edge for aspect-ratio presets",
        default=2048,
        min=64,
        max=8192,
    )
    custom_width: IntProperty(name="Width", default=2048, min=64, max=8192)
    custom_height: IntProperty(name="Height", default=2048, min=64, max=8192)
    canvas_shape: EnumProperty(
        name="Canvas Shape",
        description="Limit generation to a geometric mask inside the image canvas",
        items=(
            ("FULL", "Full Rectangle", "Use the complete rectangular image"),
            ("ROUNDED", "Rounded Rectangle", "Mask the corners with a configurable radius"),
            ("CIRCLE", "Circle", "Use a centered true circle based on the shorter edge"),
            ("HEXAGON", "Hexagon", "Use a centered regular hexagonal mask"),
        ),
        default="FULL",
    )
    mask_outside: EnumProperty(
        name="Outside Mask",
        description="How pixels outside a non-rectangular canvas shape are written",
        items=(
            ("BACKGROUND", "Background", "Fill with the selected Background brightness"),
            ("NEUTRAL", "Neutral Height", "Fill with mid-grey so physical displacement stays neutral"),
            ("TRANSPARENT", "Transparent Color", "Use neutral height and transparent material color"),
        ),
        default="BACKGROUND",
    )
    mask_roundness: FloatProperty(
        name="Corner Radius",
        description="Rounded-corner radius as a fraction of the shorter image edge",
        default=0.15,
        min=0.0,
        max=0.5,
        subtype="FACTOR",
    )
    invert: BoolProperty(name="Invert", default=False)
    seed: IntProperty(name="Seed", default=0)
    displacement_strength: FloatProperty(
        name="Displacement Strength",
        description="Distance the generated height map displaces the surface",
        default=0.05,
        min=-10.0,
        max=10.0,
        soft_min=-1.0,
        soft_max=1.0,
    )
    subdivision_level: IntProperty(
        name="Subdivision Level",
        description="Manual Simple subdivision level used when Auto Subdivision is disabled",
        default=8,
        min=0,
        max=10,
    )
    auto_subdivision: BoolProperty(
        name="Auto Subdivision",
        description="Choose mesh density from the longest output dimension and cap it for already-dense meshes",
        default=True,
    )
    weld_seams: BoolProperty(
        name="Weld Coincident Vertices",
        description="Add a Weld modifier before subdivision to prevent disconnected faces from tearing apart",
        default=True,
    )
    displacement_coordinates: EnumProperty(
        name="Displacement Mapping",
        description="Coordinates used by the Displace modifier",
        items=(
            ("UV", "UV", "Use the mesh's active UV map (recommended)"),
            ("LOCAL", "Local", "Use object-local coordinates"),
            ("GLOBAL", "Global", "Use world coordinates"),
        ),
        default="UV",
    )

    rect_enabled: BoolProperty(default=True)
    rect_brightness_min: IntProperty(default=70, min=0, max=255)
    rect_brightness_max: IntProperty(default=180, min=0, max=255)
    rect_alpha_min: IntProperty(default=20, min=0, max=100)
    rect_alpha_max: IntProperty(default=90, min=0, max=100)
    rect_scale_min: IntProperty(default=20, min=1, max=4096)
    rect_scale_max: IntProperty(default=120, min=1, max=4096)

    grid_enabled: BoolProperty(default=True)
    grid_brightness_min: IntProperty(default=40, min=0, max=255)
    grid_brightness_max: IntProperty(default=150, min=0, max=255)
    grid_alpha_min: IntProperty(default=50, min=0, max=100)
    grid_alpha_max: IntProperty(default=70, min=0, max=100)
    grid_scale_min: IntProperty(default=20, min=1, max=4096)
    grid_scale_max: IntProperty(default=160, min=1, max=4096)
    grid_amount_min: IntProperty(default=4, min=1, max=100)
    grid_amount_max: IntProperty(default=10, min=1, max=100)
    grid_gap_min: IntProperty(default=200, min=0, max=4096)
    grid_gap_max: IntProperty(default=400, min=0, max=4096)

    cols_enabled: BoolProperty(default=True)
    cols_brightness_min: IntProperty(default=150, min=0, max=255)
    cols_brightness_max: IntProperty(default=230, min=0, max=255)
    cols_alpha_min: IntProperty(default=35, min=0, max=100)
    cols_alpha_max: IntProperty(default=55, min=0, max=100)
    cols_scale_min: IntProperty(default=30, min=1, max=4096)
    cols_scale_max: IntProperty(default=60, min=1, max=4096)
    cols_amount_min: IntProperty(default=5, min=1, max=100)
    cols_amount_max: IntProperty(default=12, min=1, max=100)
    cols_gap_min: IntProperty(default=800, min=0, max=4096)
    cols_gap_max: IntProperty(default=1000, min=0, max=4096)

    rows_enabled: BoolProperty(default=True)
    rows_brightness_min: IntProperty(default=100, min=0, max=255)
    rows_brightness_max: IntProperty(default=200, min=0, max=255)
    rows_alpha_min: IntProperty(default=25, min=0, max=100)
    rows_alpha_max: IntProperty(default=35, min=0, max=100)
    rows_scale_min: IntProperty(default=25, min=1, max=4096)
    rows_scale_max: IntProperty(default=95, min=1, max=4096)
    rows_amount_min: IntProperty(default=4, min=1, max=100)
    rows_amount_max: IntProperty(default=10, min=1, max=100)
    rows_gap_min: IntProperty(default=800, min=0, max=4096)
    rows_gap_max: IntProperty(default=900, min=0, max=4096)

    lines_enabled: BoolProperty(default=True)
    lines_brightness_min: IntProperty(default=160, min=0, max=255)
    lines_brightness_max: IntProperty(default=180, min=0, max=255)
    lines_alpha_min: IntProperty(default=45, min=0, max=100)
    lines_alpha_max: IntProperty(default=55, min=0, max=100)
    lines_width_min: IntProperty(default=40, min=1, max=4096)
    lines_width_max: IntProperty(default=50, min=1, max=4096)

    sprites_enabled: BoolProperty(
        name="Sprites",
        description="Stamp shapes from the bundled Synth Surface SVG sprite packs",
        default=False,
    )
    sprite_pack_classic: BoolProperty(name="Classic", default=True)
    sprite_pack_bigdata: BoolProperty(name="Big Data", default=False)
    sprite_pack_aggromaxx: BoolProperty(name="Aggromaxx", default=False)
    sprite_pack_crappack: BoolProperty(name="Crap Pack", default=False)
    sprite_pack_circuitry: BoolProperty(name="Circuitry", default=False)
    sprites_rotation_enabled: BoolProperty(
        name="Rotate Sprites",
        description="Randomly rotate sprite stamps in 90 degree increments",
        default=True,
    )

    comp_color_burn: BoolProperty(default=False)
    comp_color_dodge: BoolProperty(default=False)
    comp_darken: BoolProperty(default=False)
    comp_difference: BoolProperty(default=False)
    comp_exclusion: BoolProperty(default=False)
    comp_hard_light: BoolProperty(default=False)
    comp_lighten: BoolProperty(default=False)
    comp_lighter: BoolProperty(default=False)
    comp_luminosity: BoolProperty(default=False)
    comp_multiply: BoolProperty(default=False)
    comp_overlay: BoolProperty(default=False)
    comp_screen: BoolProperty(default=False)
    comp_soft_light: BoolProperty(default=False)
    comp_source_atop: BoolProperty(default=False)
    comp_source_over: BoolProperty(default=True)
    comp_xor: BoolProperty(default=False)

    sharp_color_edges: BoolProperty(
        name="Sharp Color Edges",
        description=(
            "Use hard color-stop bands and nearest texture sampling to reduce "
            "color smearing on steep displaced surfaces"
        ),
        default=False,
    )
    stops: CollectionProperty(type=DXStop)
    lights_enabled: BoolProperty(
        name="Scatter Lights", default=False,
        description="Generate small emissive lights across the surface texture",
    )
    lights_shape: EnumProperty(
        name="Light Shape",
        items=(("ROUND", "Round", "Circular lights"),
               ("SQUARE", "Square", "Square lights aligned with the texture")),
        default="ROUND",
    )
    lights_scale: FloatProperty(
        name="Light Scale (%)", default=0.4, min=0.01, max=10.0,
        soft_max=2.0, precision=2,
        description="Light diameter / square width as a percentage of the shorter texture edge",
    )
    lights_density: IntProperty(
        name="Density", default=800, min=0, max=50000, soft_max=5000,
        description="Number of lights over the full texture before canvas masking; independent of resolution",
    )
    lights_intensity: FloatProperty(
        name="Intensity", default=5.0, min=0.0, max=1000.0, soft_max=25.0,
        description="Emission strength; zero turns off the glow when applied",
    )
    lights_randomness: FloatProperty(
        name="Position Randomness", default=1.0, min=0.0, max=1.0,
        subtype="FACTOR", description="Zero aligns lights in a grid; one jitters each light throughout its grid cell",
    )
    lights_scale_randomness: FloatProperty(
        name="Size Variation", default=0.5, min=0.0, max=1.0,
        subtype="FACTOR", description="Randomly reduce each light from Light Scale down to this fraction smaller",
    )
    lights_intensity_randomness: FloatProperty(
        name="Intensity Variation", default=0.4, min=0.0, max=1.0,
        subtype="FACTOR", description="Randomly dim individual lights; zero gives equal intensity",
    )
    lights_seed: IntProperty(
        name="Light Seed", default=0,
        description="Rearrange lights independently of the surface Seed",
    )
    lights_color_mode: EnumProperty(
        name="Color Mode",
        items=(("SINGLE", "Single Color", "Use one color for every light"),
               ("PALETTE", "Random Palette", "Choose one color per light from the editable palette")),
        default="SINGLE",
    )
    lights_color: FloatVectorProperty(
        name="Color", subtype="COLOR", size=3,
        default=DEFAULT_LIGHT_PALETTE[0], min=0.0, max=1.0,
    )
    light_palette: CollectionProperty(type=DXLightColor)
    preview_image: StringProperty(default="")


def _preview_color(props):
    core = _core_settings_from_props(props)
    width, height = _preview_dimensions(*_output_dimensions(props))
    h = generate_height(core, (width, height), seed=props.seed)
    if props.invert:
        h = (255 - h).astype(np.uint8)
    c = generate_color(h, _stops_from_props(props), sharp=props.sharp_color_edges,
                       alpha_mask=_transparent_canvas_mask(core, width, height))
    emission = generate_emission(core, (width, height), _light_palette_from_props(props))
    return preview_with_lights(c, emission, props.lights_intensity)


class DX_OT_UpdatePreview(Operator):
    bl_idname = "dx.update_preview"
    bl_label = "Update Preview"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.displacementx
        c = _preview_color(props)
        img = _make_image(
            PREVIEW_IMAGE_NAME, c, "sRGB", legacy_names=("DX_Preview",)
        )
        props.preview_image = img.name
        if not _update_inline_preview(img, context):
            self.report({"WARNING"}, "Preview generated, but Blender could not draw it in the panel")
        _tag_view3d_redraw(context)
        return {"FINISHED"}


class DX_OT_Randomize(Operator):
    bl_idname = "dx.randomize"
    bl_label = "Randomize All"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.displacementx
        core = randomize(_core_settings_from_props(props))
        props.iterations = core["iterations"]
        props.background_brightness = core["background_brightness"]
        for s in ["rect", "grid", "cols", "rows"]:
            setattr(props, s + "_enabled", core[s + "_enabled"])
            setattr(props, s + "_brightness_min", core[s + "_brightness_min"])
            setattr(props, s + "_brightness_max", core[s + "_brightness_max"])
            setattr(props, s + "_alpha_min", core[s + "_alpha_min"])
            setattr(props, s + "_alpha_max", core[s + "_alpha_max"])
            setattr(props, s + "_scale_min", core[s + "_scale_min"])
            setattr(props, s + "_scale_max", core[s + "_scale_max"])
        props.lines_enabled = core["lines_enabled"]
        props.lines_brightness_min = core["lines_brightness_min"]
        props.lines_brightness_max = core["lines_brightness_max"]
        props.lines_alpha_min = core["lines_alpha_min"]
        props.lines_alpha_max = core["lines_alpha_max"]
        for s in ["grid", "cols", "rows"]:
            setattr(props, s + "_amount_min", core[s + "_amount_min"])
            setattr(props, s + "_amount_max", core[s + "_amount_max"])
            setattr(props, s + "_gap_min", core[s + "_gap_min"])
            setattr(props, s + "_gap_max", core[s + "_gap_max"])
        props.lines_width_min = core["lines_width_min"]
        props.lines_width_max = core["lines_width_max"]
        props.sprites_enabled = core["sprites_enabled"]
        props.sprites_rotation_enabled = core["sprites_rotation_enabled"]
        for pack in SPRITE_PACKS:
            setattr(props, "sprite_pack_" + pack, core["sprite_pack_" + pack])
        for m in COMPOSITION_MODES:
            setattr(props, "comp_" + m.replace("-", "_"), core["comp_" + m])
        props.seed = random.randint(0, 100000)
        return {"FINISHED"}


class DX_OT_AddStop(Operator):
    bl_idname = "dx.add_stop"
    bl_label = "Add Color Stop"

    def execute(self, context):
        props = context.scene.displacementx
        _ensure_default_stops(props)
        st = props.stops.add()
        st.pos = random.uniform(0.0, 1.0)
        st.color = (random.random(), random.random(), random.random())
        return {"FINISHED"}


class DX_OT_DeleteStop(Operator):
    bl_idname = "dx.delete_stop"
    bl_label = "Delete Color Stop"
    index: IntProperty()

    def execute(self, context):
        props = context.scene.displacementx
        if 0 <= self.index < len(props.stops):
            props.stops.remove(self.index)
        return {"FINISHED"}


class DX_OT_ResetStops(Operator):
    bl_idname = "dx.reset_stops"
    bl_label = "Reset Color Stops"
    bl_description = "Restore the black, grey, white, and red default gradient"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _set_default_stops(context.scene.displacementx)
        return {"FINISHED"}


class DX_OT_AddLightColor(Operator):
    bl_idname = "dx.add_light_color"
    bl_label = "Add Light Color"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.displacementx
        _light_palette_from_props(props)
        props.light_palette.add().color = DEFAULT_LIGHT_PALETTE[
            (len(props.light_palette) - 1) % len(DEFAULT_LIGHT_PALETTE)]
        return {"FINISHED"}


class DX_OT_DeleteLightColor(Operator):
    bl_idname = "dx.delete_light_color"
    bl_label = "Remove Light Color"
    bl_options = {"REGISTER", "UNDO"}
    index: IntProperty()

    def execute(self, context):
        palette = context.scene.displacementx.light_palette
        if len(palette) > 1 and 0 <= self.index < len(palette):
            palette.remove(self.index)
        return {"FINISHED"}


class DX_OT_ResetLightPalette(Operator):
    bl_idname = "dx.reset_light_palette"
    bl_label = "Reset Light Palette"
    bl_description = "Restore pink, cyan, green, warm white, and violet lights"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _set_default_light_palette(context.scene.displacementx)
        return {"FINISHED"}


class DX_OT_Apply(Operator):
    bl_idname = "dx.apply"
    bl_label = "Generate & Apply to Selected Object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first")
            return {"CANCELLED"}
        props = context.scene.displacementx
        core = _core_settings_from_props(props)
        stops = _stops_from_props(props)
        width, height = _output_dimensions(props)
        self.report({"INFO"}, "Generating %dx%d texture..." % (width, height))
        h = generate_height(core, (width, height), seed=props.seed)
        if props.invert:
            h = (255 - h).astype(np.uint8)
        alpha_mask = _transparent_canvas_mask(core, width, height)
        c = generate_color(
            h,
            stops,
            sharp=props.sharp_color_edges,
            alpha_mask=alpha_mask,
        )
        n = generate_normal(h)

        img_c = _make_image(
            COLOR_IMAGE_NAME, c, "sRGB", legacy_names=("DX_Color",)
        )
        img_n = _make_image(
            NORMAL_IMAGE_NAME, n, "Non-Color", legacy_names=("DX_Normal",)
        )
        img_h = _make_image(
            HEIGHT_IMAGE_NAME, h, "Non-Color", legacy_names=("DX_Height",)
        )
        # Build after uploading other maps to keep peak memory bounded. Linear
        # RGB matches Blender's light pickers; HDR intensity lives in the shader.
        del c, n, h
        emission = generate_emission(core, (width, height), _light_palette_from_props(props))
        img_e = None
        if emission is not None:
            img_e = _make_image(EMISSION_IMAGE_NAME, emission, "Non-Color")
            del emission

        mat = _get_or_migrate_datablock(
            bpy.data.materials, MATERIAL_NAME, legacy_names=("DisplacementX",)
        )
        if mat is None:
            mat = bpy.data.materials.new(MATERIAL_NAME)
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (600, 0)
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (300, 0)
        tex_c = nt.nodes.new("ShaderNodeTexImage"); tex_c.location = (-300, 200)
        tex_c.image = img_c
        tex_n = nt.nodes.new("ShaderNodeTexImage"); tex_n.location = (-300, -100)
        tex_n.image = img_n
        for image_node in (tex_c, tex_n):
            image_node.extension = "REPEAT" if props.seamless else "EXTEND"
        tex_c.interpolation = "Closest" if props.sharp_color_edges else "Linear"
        tex_n.interpolation = "Cubic"
        normal_map = nt.nodes.new("ShaderNodeNormalMap"); normal_map.location = (50, -100)
        nt.links.new(tex_c.outputs["Color"], bsdf.inputs["Base Color"])
        if img_e is not None:
            tex_e = nt.nodes.new("ShaderNodeTexImage")
            tex_e.name = "Synth Surface Scatter Lights"
            tex_e.label = "Scatter Lights"
            tex_e.location = (-300, 500)
            tex_e.image = img_e
            tex_e.extension = "REPEAT" if props.seamless else "EXTEND"
            tex_e.interpolation = "Linear"
            # Blender 4 renamed Emission to Emission Color.
            emission_input = bsdf.inputs.get("Emission Color")
            if emission_input is None:
                emission_input = bsdf.inputs["Emission"]
            nt.links.new(tex_e.outputs["Color"], emission_input)
            bsdf.inputs["Emission Strength"].default_value = props.lights_intensity
        if alpha_mask is not None:
            nt.links.new(tex_c.outputs["Alpha"], bsdf.inputs["Alpha"])
            try:
                mat.surface_render_method = "DITHERED"
            except (AttributeError, TypeError, ValueError):
                try:
                    mat.blend_method = "HASHED"
                except (AttributeError, TypeError, ValueError):
                    pass
        nt.links.new(tex_n.outputs["Color"], normal_map.inputs["Color"])
        nt.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        try:
            # Physical displacement is handled once by the modifier below.
            # Keeping the material in bump mode prevents Cycles from applying
            # the height map a second time and opening cracks at UV seams.
            mat.displacement_method = "BUMP"
        except Exception:
            pass
        # Replace only the active material slot. Clearing every slot destroyed
        # unrelated materials and face assignments on multi-material meshes.
        if len(obj.data.materials) == 0:
            obj.data.materials.append(mat)
        else:
            obj.active_material = mat
        # create an ImageTexture wrapping the height map for the Displace modifier
        btex = _get_or_migrate_datablock(
            bpy.data.textures,
            DISPLACE_TEXTURE_NAME,
            legacy_names=("DX_DisplaceTex",),
        )
        if btex is None:
            btex = bpy.data.textures.new(DISPLACE_TEXTURE_NAME, type='IMAGE')
        btex.image = img_h
        btex.extension = 'REPEAT' if props.seamless else 'EXTEND'
        btex.use_interpolation = True
        try:
            btex.use_mipmap = True
            btex.use_mipmap_gauss = True
        except AttributeError:
            pass

        # Refresh only modifiers owned by this add-on. Simple subdivision adds
        # surface density without rounding a cube like Catmull-Clark would.
        for modifier_name in (
            WELD_MODIFIER_NAME,
            SUBDIVISION_MODIFIER_NAME,
            DISPLACE_MODIFIER_NAME,
            "DX_Weld",
            "DX_Subdivision",
            "DX_Displace",
        ):
            old_modifier = obj.modifiers.get(modifier_name)
            if old_modifier is not None:
                obj.modifiers.remove(old_modifier)
        if props.weld_seams:
            weld = obj.modifiers.new(name=WELD_MODIFIER_NAME, type='WELD')
            weld.merge_threshold = 0.0001
        requested_subdivision_level = int(props.subdivision_level)
        if props.auto_subdivision:
            recommended_level = _recommended_subdivision_level(max(width, height))
            requested_subdivision_level = _safe_auto_subdivision_level(
                obj, recommended_level
            )
            if requested_subdivision_level < recommended_level:
                self.report(
                    {"WARNING"},
                    "Auto subdivision reduced from level %d to %d to stay below approximately %s faces"
                    % (
                        recommended_level,
                        requested_subdivision_level,
                        format(AUTO_SUBDIV_MAX_FACES, ","),
                    ),
                )
        if requested_subdivision_level > 0:
            subdivision = obj.modifiers.new(
                name=SUBDIVISION_MODIFIER_NAME, type='SUBSURF'
            )
            subdivision.subdivision_type = 'SIMPLE'
            subdivision.levels = requested_subdivision_level
            subdivision.render_levels = requested_subdivision_level

        dm = obj.modifiers.new(name=DISPLACE_MODIFIER_NAME, type='DISPLACE')
        dm.texture = btex
        dm.strength = props.displacement_strength
        dm.mid_level = 0.5
        dm.direction = 'NORMAL'
        dm.texture_coords = props.displacement_coordinates
        if props.displacement_coordinates == 'UV':
            uv_layers = getattr(obj.data, "uv_layers", None)
            active_uv = uv_layers.active if uv_layers else None
            if active_uv is not None:
                dm.uv_layer = active_uv.name
            else:
                dm.texture_coords = 'LOCAL'
                self.report(
                    {"WARNING"},
                    "Object has no UV map; Synth Surface used Local mapping instead",
                )
        self.report(
            {"INFO"},
            "Applied Synth Surface material + displacement to '%s'" % obj.name,
        )
        return {"FINISHED"}


class DX_PT_Main(Panel):
    bl_label = "Synth Surface"
    bl_idname = "DX_PT_Main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Synth Surface"

    def draw(self, context):
        layout = self.layout
        props = context.scene.displacementx
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("dx.randomize", icon="FILE_REFRESH")
        row.operator("dx.update_preview", icon="FILE_REFRESH")
        if props.preview_image and props.preview_image in bpy.data.images:
            img = bpy.data.images[props.preview_image]
            _draw_inline_preview(col)
            row = col.row(align=True)
            row.label(text="Preview: %dx%d" % tuple(img.size))
            row.operator("dx.open_preview", text="Open Large", icon="IMAGE_DATA")
        row = col.row(align=True)
        row.operator("dx.apply", icon="MATERIAL")
        col.separator()
        col.label(text="Basics")
        col.prop(props, "iterations")
        col.prop(props, "background_brightness")
        col.prop(props, "seamless", text="Seamless")
        col.prop(props, "seed")
        lights = col.box()
        lights.prop(props, "lights_enabled")
        if props.lights_enabled:
            lights.prop(props, "lights_shape", expand=True)
            lights.prop(props, "lights_scale")
            lights.prop(props, "lights_density")
            lights.prop(props, "lights_intensity")
            lights.prop(props, "lights_color_mode")
            if props.lights_color_mode == "SINGLE":
                lights.prop(props, "lights_color")
            else:
                if not props.light_palette:
                    _schedule_scene_stop_initialization()
                    lights.label(text="Loading light palette...", icon="INFO")
                for index, entry in enumerate(props.light_palette):
                    row = lights.row(align=True)
                    row.prop(entry, "color", text="Color %d" % (index + 1))
                    remove = row.row(align=True)
                    remove.enabled = len(props.light_palette) > 1
                    remove.operator("dx.delete_light_color", text="", icon="X").index = index
                row = lights.row(align=True)
                row.operator("dx.add_light_color", text="Add Color", icon="ADD")
                row.operator("dx.reset_light_palette", text="Reset", icon="FILE_REFRESH")
            lights.prop(props, "lights_randomness", slider=True)
            lights.prop(props, "lights_scale_randomness", slider=True)
            lights.prop(props, "lights_intensity_randomness", slider=True)
            lights.prop(props, "lights_seed")
            lights.label(text="Update Preview / Generate & Apply", icon="INFO")
        col.separator()
        col.label(text="Rect")
        col.prop(props, "rect_enabled")
        col.prop(props, "rect_brightness_min")
        col.prop(props, "rect_brightness_max")
        col.prop(props, "rect_alpha_min")
        col.prop(props, "rect_alpha_max")
        col.prop(props, "rect_scale_min")
        col.prop(props, "rect_scale_max")
        col.separator()
        col.label(text="Grid")
        col.prop(props, "grid_enabled")
        col.prop(props, "grid_brightness_min")
        col.prop(props, "grid_brightness_max")
        col.prop(props, "grid_alpha_min")
        col.prop(props, "grid_alpha_max")
        col.prop(props, "grid_scale_min")
        col.prop(props, "grid_scale_max")
        col.prop(props, "grid_amount_min")
        col.prop(props, "grid_amount_max")
        col.prop(props, "grid_gap_min")
        col.prop(props, "grid_gap_max")
        col.separator()
        col.label(text="Cols")
        col.prop(props, "cols_enabled")
        col.prop(props, "cols_brightness_min")
        col.prop(props, "cols_brightness_max")
        col.prop(props, "cols_alpha_min")
        col.prop(props, "cols_alpha_max")
        col.prop(props, "cols_scale_min")
        col.prop(props, "cols_scale_max")
        col.prop(props, "cols_amount_min")
        col.prop(props, "cols_amount_max")
        col.prop(props, "cols_gap_min")
        col.prop(props, "cols_gap_max")
        col.separator()
        col.label(text="Rows")
        col.prop(props, "rows_enabled")
        col.prop(props, "rows_brightness_min")
        col.prop(props, "rows_brightness_max")
        col.prop(props, "rows_alpha_min")
        col.prop(props, "rows_alpha_max")
        col.prop(props, "rows_scale_min")
        col.prop(props, "rows_scale_max")
        col.prop(props, "rows_amount_min")
        col.prop(props, "rows_amount_max")
        col.prop(props, "rows_gap_min")
        col.prop(props, "rows_gap_max")
        col.separator()
        col.label(text="Lines")
        col.prop(props, "lines_enabled")
        col.prop(props, "lines_brightness_min")
        col.prop(props, "lines_brightness_max")
        col.prop(props, "lines_alpha_min")
        col.prop(props, "lines_alpha_max")
        col.prop(props, "lines_width_min")
        col.prop(props, "lines_width_max")
        col.separator()
        sprite_box = col.box()
        sprite_box.prop(props, "sprites_enabled")
        if props.sprites_enabled:
            sprite_box.prop(props, "sprites_rotation_enabled")
            sprite_box.label(text="Packs:")
            pack_grid = sprite_box.grid_flow(columns=2, align=True)
            for pack in SPRITE_PACKS:
                pack_grid.prop(
                    props,
                    "sprite_pack_" + pack,
                    text=SPRITE_PACK_LABELS[pack],
                )
            counts = get_sprite_pack_counts()
            selected_count = sum(
                counts.get(pack, 0)
                for pack in SPRITE_PACKS
                if getattr(props, "sprite_pack_" + pack)
            )
            if selected_count:
                sprite_box.label(text="%d bundled sprites selected" % selected_count, icon="IMAGE_DATA")
            else:
                sprite_box.label(text="Select at least one available pack", icon="ERROR")
        col.separator()
        col.label(text="Color Stops")
        if len(props.stops) == 0:
            _schedule_scene_stop_initialization()
            col.label(text="Loading default color stops...", icon="INFO")
        else:
            for i, st in enumerate(props.stops):
                row = col.row(align=True)
                row.prop(st, "pos")
                row.prop(st, "color")
                row.operator("dx.delete_stop", icon="X").index = i
        row = col.row(align=True)
        row.operator("dx.add_stop", icon="ADD")
        row.operator("dx.reset_stops", text="Reset", icon="FILE_REFRESH")
        col.prop(props, "sharp_color_edges")
        col.separator()
        col.label(text="Composition")
        for m in COMPOSITION_MODES:
            col.prop(props, "comp_" + m.replace("-", "_"))
        col.separator()
        col.label(text="Output")
        col.prop(props, "aspect_ratio")
        if props.aspect_ratio == "CUSTOM":
            dimension_row = col.row(align=True)
            dimension_row.prop(props, "custom_width")
            dimension_row.prop(props, "custom_height")
        else:
            col.prop(props, "resolution")
        output_width, output_height = _output_dimensions(props)
        pixel_count = output_width * output_height
        col.label(
            text="Output: %d x %d (%.1f MP)"
            % (output_width, output_height, pixel_count / 1_000_000.0),
            icon="IMAGE_DATA",
        )
        if pixel_count > OUTPUT_PIXEL_WARNING:
            col.label(text="Large output: high memory use", icon="ERROR")
        col.prop(props, "canvas_shape")
        if props.canvas_shape != "FULL":
            col.prop(props, "mask_outside")
            if props.canvas_shape == "ROUNDED":
                col.prop(props, "mask_roundness")
            if props.mask_outside == "TRANSPARENT":
                col.label(text="Height stays neutral outside mask", icon="INFO")
            if props.seamless:
                col.label(text="Masked edges are not seamless", icon="INFO")
        col.prop(props, "invert", text="Invert")
        col.prop(props, "displacement_strength")
        col.prop(props, "auto_subdivision")
        if props.auto_subdivision:
            level = _recommended_subdivision_level(max(output_width, output_height))
            col.label(
                text="Recommended level: %d (%d samples/edge)" % (level, 2 ** level),
                icon="MOD_SUBSURF",
            )
        else:
            col.prop(props, "subdivision_level")
        col.prop(props, "weld_seams")
        col.prop(props, "displacement_coordinates")


PREVIEW_SCREEN_NAME = "Synth Surface Preview"
LEGACY_PREVIEW_SCREEN_NAME = "DisplacementX Preview"


def _preview_filepath(revision):
    temp_root = getattr(bpy.app, "tempdir", "") or tempfile.gettempdir()
    return os.path.join(
        temp_root,
        "synth_surface_panel_preview_%d_%d.png" % (os.getpid(), revision),
    )


def _update_inline_preview(img, context):
    """Save a generated Blender image and load it as a panel preview icon.

    Loading through ``bpy.utils.previews`` is more reliable across Blender
    versions than assigning ImagePreview pixel buffers directly.
    """
    global _CURRENT_PREVIEW_FILE, _PREVIEW_REVISION

    collection = _PREVIEW_COLLECTIONS.get("main")
    if collection is None:
        return False

    _PREVIEW_REVISION += 1
    filepath = _preview_filepath(_PREVIEW_REVISION)
    previous_filepath = _CURRENT_PREVIEW_FILE
    try:
        img.save_render(filepath, scene=context.scene)
        if PREVIEW_ICON_KEY in collection:
            del collection[PREVIEW_ICON_KEY]
        collection.load(PREVIEW_ICON_KEY, filepath, 'IMAGE')
    except Exception as exc:
        print("Synth Surface: could not create inline preview:", exc)
        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
        except OSError:
            pass
        if previous_filepath and os.path.isfile(previous_filepath):
            try:
                if PREVIEW_ICON_KEY not in collection:
                    collection.load(PREVIEW_ICON_KEY, previous_filepath, 'IMAGE')
            except Exception:
                pass
        return False

    _CURRENT_PREVIEW_FILE = filepath
    if previous_filepath and previous_filepath != filepath:
        try:
            if os.path.isfile(previous_filepath):
                os.remove(previous_filepath)
        except OSError:
            pass
    return True


def _draw_inline_preview(layout):
    collection = _PREVIEW_COLLECTIONS.get("main")
    preview = collection.get(PREVIEW_ICON_KEY) if collection is not None else None
    if preview is None or not preview.icon_id:
        return False
    try:
        layout.template_icon(icon_value=preview.icon_id, scale=10.0)
    except (AttributeError, TypeError):
        layout.label(text="Preview ready", icon_value=preview.icon_id)
    return True


def _tag_view3d_redraw(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def _ensure_preview_window(context, img):
    """Show *img* in a dedicated Image Editor window (created once, reused after)."""
    wins = context.window_manager.windows
    # reuse the marked preview window (even if its image slot now dangles)
    for win in wins:
        if win.screen is None or win.screen.name not in {
            PREVIEW_SCREEN_NAME,
            LEGACY_PREVIEW_SCREEN_NAME,
        }:
            continue
        win.screen.name = PREVIEW_SCREEN_NAME
        for area in win.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = img
        return True
    before = {w.as_pointer() for w in wins}
    try:
        try:
            bpy.ops.wm.window_new()
        except AttributeError:
            bpy.ops.window.new()
    except Exception:
        return False
    new_win = next((w for w in wins if w.as_pointer() not in before), None)
    if new_win is None or new_win.screen is None:
        return False
    new_win.screen.name = PREVIEW_SCREEN_NAME
    for area in new_win.screen.areas:
        area.type = "IMAGE_EDITOR"
    for area in new_win.screen.areas:
        if area.type == "IMAGE_EDITOR":
            area.spaces.active.image = img
    return True


class DX_OT_OpenPreview(Operator):
    bl_idname = "dx.open_preview"
    bl_label = "Open Preview"
    bl_description = "Show the generated preview texture in a dedicated Image Editor window"

    def execute(self, context):
        props = context.scene.displacementx
        img = bpy.data.images.get(props.preview_image) if props.preview_image else None
        if img is None:
            c = _preview_color(props)
            img = _make_image(
                PREVIEW_IMAGE_NAME, c, "sRGB", legacy_names=("DX_Preview",)
            )
            props.preview_image = img.name
            _update_inline_preview(img, context)
            _tag_view3d_redraw(context)
        if _ensure_preview_window(context, img):
            return {"FINISHED"}
        self.report({"WARNING"}, "Could not open a preview window")
        return {"CANCELLED"}


classes = (DXStop, DXLightColor, DisplacementXSettings, DX_OT_UpdatePreview, DX_OT_Randomize,
           DX_OT_AddStop, DX_OT_DeleteStop, DX_OT_ResetStops,
           DX_OT_AddLightColor, DX_OT_DeleteLightColor, DX_OT_ResetLightPalette,
           DX_OT_Apply, DX_OT_OpenPreview,
           DX_PT_Main)


def register():
    import bpy.utils.previews

    if "main" not in _PREVIEW_COLLECTIONS:
        _PREVIEW_COLLECTIONS["main"] = bpy.utils.previews.new()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.displacementx = bpy.props.PointerProperty(type=DisplacementXSettings)
    _schedule_scene_stop_initialization()


def unregister():
    import bpy.utils.previews

    global _CURRENT_PREVIEW_FILE, _DEFAULT_STOP_TIMER_PENDING

    try:
        if bpy.app.timers.is_registered(_initialize_scene_stops):
            bpy.app.timers.unregister(_initialize_scene_stops)
    except (AttributeError, RuntimeError, ValueError):
        pass
    _DEFAULT_STOP_TIMER_PENDING = False

    try:
        del bpy.types.Scene.displacementx
    except Exception:
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    for collection in _PREVIEW_COLLECTIONS.values():
        bpy.utils.previews.remove(collection)
    _PREVIEW_COLLECTIONS.clear()
    if _CURRENT_PREVIEW_FILE:
        try:
            if os.path.isfile(_CURRENT_PREVIEW_FILE):
                os.remove(_CURRENT_PREVIEW_FILE)
        except OSError:
            pass
    _CURRENT_PREVIEW_FILE = None
