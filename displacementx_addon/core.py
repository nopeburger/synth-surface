"""Synth Surface core - procedural greeble texture generation (functional API).

Port of the Displacement X / JS Placement algorithm (github.com/satelllte/displacementx).
Generates a grayscale height map by stamping random geometric shapes and bundled
the original Displacement X sprite packs, then derives color and normal maps.
Pure numpy - no bpy dependency.
"""
from pathlib import Path
from collections import OrderedDict
import random
import numpy as np


SPRITE_PACKS = ("classic", "bigdata", "aggromaxx", "crappack", "circuitry")
COMPOSITION_MODES = (
    "color-burn",
    "color-dodge",
    "darken",
    "difference",
    "exclusion",
    "hard-light",
    "lighten",
    "lighter",
    "luminosity",
    "multiply",
    "overlay",
    "screen",
    "soft-light",
    "source-atop",
    "source-over",
    "xor",
)
SPRITE_PACK_LABELS = {
    "classic": "Classic",
    "bigdata": "Big Data",
    "aggromaxx": "Aggromaxx",
    "crappack": "Crap Pack",
    "circuitry": "Circuitry",
}
SPRITE_PACK_COUNTS = {
    "classic": 17,
    "bigdata": 5,
    "aggromaxx": 12,
    "crappack": 27,
    "circuitry": 10,
}

DEFAULT_COLOR_STOPS = (
    (0.0, (0, 0, 0)),
    (1.0 / 3.0, (128, 128, 128)),
    (2.0 / 3.0, (255, 255, 255)),
    (1.0, (255, 0, 0)),
)
_SPRITE_LIBRARY = None
_SPRITE_BLEND_CACHE = OrderedDict()
_SPRITE_BLEND_CACHE_LIMIT = 8

DEFAULT_SETTINGS = {
    "iterations": 1500,
    "background_brightness": 128,
    "seamless": False,
    "canvas_shape": "FULL",
    "mask_outside": "BACKGROUND",
    "mask_roundness": 0.15,
    "rect_enabled": True, "rect_brightness_min": 70, "rect_brightness_max": 180,
    "rect_alpha_min": 20, "rect_alpha_max": 90, "rect_scale_min": 20, "rect_scale_max": 120,
    "grid_enabled": True, "grid_brightness_min": 40, "grid_brightness_max": 150,
    "grid_alpha_min": 50, "grid_alpha_max": 70, "grid_scale_min": 20, "grid_scale_max": 160,
    "grid_amount_min": 4, "grid_amount_max": 10, "grid_gap_min": 200, "grid_gap_max": 400,
    "cols_enabled": True, "cols_brightness_min": 150, "cols_brightness_max": 230,
    "cols_alpha_min": 35, "cols_alpha_max": 55, "cols_scale_min": 30, "cols_scale_max": 60,
    "cols_amount_min": 5, "cols_amount_max": 12, "cols_gap_min": 800, "cols_gap_max": 1000,
    "rows_enabled": True, "rows_brightness_min": 100, "rows_brightness_max": 200,
    "rows_alpha_min": 25, "rows_alpha_max": 35, "rows_scale_min": 25, "rows_scale_max": 95,
    "rows_amount_min": 4, "rows_amount_max": 10, "rows_gap_min": 800, "rows_gap_max": 900,
    "lines_enabled": True, "lines_brightness_min": 160, "lines_brightness_max": 180,
    "lines_alpha_min": 45, "lines_alpha_max": 55, "lines_width_min": 40, "lines_width_max": 50,
    "sprites_enabled": False,
    "sprite_pack_classic": True,
    "sprite_pack_bigdata": False,
    "sprite_pack_aggromaxx": False,
    "sprite_pack_crappack": False,
    "sprite_pack_circuitry": False,
    "sprites_rotation_enabled": True,
    "comp_color-burn": False, "comp_color-dodge": False, "comp_darken": False,
    "comp_difference": False, "comp_exclusion": False, "comp_hard-light": False,
    "comp_lighten": False, "comp_lighter": False, "comp_luminosity": False,
    "comp_multiply": False, "comp_overlay": False, "comp_screen": False,
    "comp_soft-light": False, "comp_source-atop": False, "comp_source-over": True,
    "comp_xor": False,
}


def _randi(rng, a, b):
    lo, hi = sorted((int(a), int(b)))
    return rng.randint(lo, hi)


def _randf(rng, a, b):
    lo, hi = sorted((float(a), float(b)))
    return rng.uniform(lo, hi)


def _load_sprite_library(packs=None):
    """Load requested packs from the build-time SVG raster cache on demand.

    The original SVG sources remain in the source repository under
    ``sprites/<pack>``. They are rasterized before release because Blender does not consistently ship an
    SVG image decoder. The compressed cache keeps the installed add-on entirely
    offline and avoids depending on Pillow, CairoSVG, or an enabled SVG importer.
    """
    global _SPRITE_LIBRARY
    if _SPRITE_LIBRARY is None:
        _SPRITE_LIBRARY = {}
    requested_packs = tuple(packs) if packs is not None else SPRITE_PACKS
    missing_packs = [pack for pack in requested_packs if pack not in _SPRITE_LIBRARY]
    if not missing_packs:
        return _SPRITE_LIBRARY

    cache_path = Path(__file__).with_name("sprites") / "sprite_cache.npz"
    if not cache_path.is_file():
        for pack in missing_packs:
            _SPRITE_LIBRARY[pack] = ()
        return _SPRITE_LIBRARY

    try:
        with np.load(str(cache_path), allow_pickle=False) as cache:
            for pack in missing_packs:
                gray_key = pack + "_gray"
                alpha_key = pack + "_alpha"
                if gray_key not in cache or alpha_key not in cache:
                    _SPRITE_LIBRARY[pack] = ()
                    continue
                gray = np.asarray(cache[gray_key], dtype=np.uint8)
                alpha = np.asarray(cache[alpha_key], dtype=np.uint8)
                if gray.ndim != 3 or gray.shape != alpha.shape:
                    _SPRITE_LIBRARY[pack] = ()
                    continue
                _SPRITE_LIBRARY[pack] = tuple(zip(gray, alpha))
    except (OSError, ValueError, KeyError):
        # Generation still works with the geometric generators if the cache is
        # missing or damaged; the Blender operator reports a clearer UI warning.
        for pack in missing_packs:
            _SPRITE_LIBRARY[pack] = ()
    return _SPRITE_LIBRARY


def get_sprite_pack_counts():
    """Return the number of usable bundled sprites in each pack."""
    return dict(SPRITE_PACK_COUNTS)


def _get_params(s, name, rng):
    return {
        "brightness": _randi(rng, s.get(name + "_brightness_min", 0), s.get(name + "_brightness_max", 255)),
        "alpha": _randf(rng, s.get(name + "_alpha_min", 0), s.get(name + "_alpha_max", 100)) / 100.0,
        "scale": _randi(rng, s.get(name + "_scale_min", 1), s.get(name + "_scale_max", 4096)),
        "amount": _randi(rng, s.get(name + "_amount_min", 1), s.get(name + "_amount_max", 100)),
        "gap": _randi(rng, s.get(name + "_gap_min", 0), s.get(name + "_gap_max", 4096)),
        "width": _randi(rng, s.get(name + "_width_min", 1), s.get(name + "_width_max", 4096)),
    }


def _blend_grayscale(backdrop, source, mode):
    """Apply a Canvas/W3C blend function to straight grayscale colors."""
    backdrop = np.asarray(backdrop, dtype=np.float32) / 255.0
    source = np.asarray(source, dtype=np.float32) / 255.0

    if mode in {"source-over", "source-atop", "luminosity"}:
        result = source
    elif mode == "multiply":
        result = backdrop * source
    elif mode == "screen":
        result = backdrop + source - backdrop * source
    elif mode == "overlay":
        result = np.where(
            backdrop <= 0.5,
            2.0 * backdrop * source,
            1.0 - 2.0 * (1.0 - backdrop) * (1.0 - source),
        )
    elif mode == "hard-light":
        result = np.where(
            source <= 0.5,
            2.0 * backdrop * source,
            1.0 - 2.0 * (1.0 - backdrop) * (1.0 - source),
        )
    elif mode == "darken":
        result = np.minimum(backdrop, source)
    elif mode == "lighten":
        result = np.maximum(backdrop, source)
    elif mode == "difference":
        result = np.abs(backdrop - source)
    elif mode == "exclusion":
        result = backdrop + source - 2.0 * backdrop * source
    elif mode == "color-dodge":
        denominator = 1.0 - source
        divided = np.divide(
            backdrop,
            denominator,
            out=np.ones(np.broadcast(backdrop, source).shape, dtype=np.float32),
            where=denominator > 0.0,
        )
        result = np.minimum(1.0, divided)
    elif mode == "color-burn":
        divided = np.divide(
            1.0 - backdrop,
            source,
            out=np.ones(np.broadcast(backdrop, source).shape, dtype=np.float32),
            where=source > 0.0,
        )
        result = 1.0 - np.minimum(1.0, divided)
    elif mode == "soft-light":
        curve = np.where(
            backdrop <= 0.25,
            ((16.0 * backdrop - 12.0) * backdrop + 4.0) * backdrop,
            np.sqrt(backdrop),
        )
        result = np.where(
            source <= 0.5,
            backdrop - (1.0 - 2.0 * source) * backdrop * (1.0 - backdrop),
            backdrop + (2.0 * source - 1.0) * (curve - backdrop),
        )
    else:
        result = source
    return np.clip(result * 255.0, 0.0, 255.0)


def _composite_premultiplied(
    destination,
    destination_alpha,
    source_premultiplied,
    source_alpha,
    mode,
):
    """Composite a grayscale source using Canvas globalCompositeOperation rules.

    Color buffers use 0..255 premultiplied values; alpha is stored as uint8.
    This preserves the Porter-Duff behavior of source-atop, lighter, and xor,
    while the remaining modes use source-over plus their W3C blend function.
    """
    source_alpha = np.asarray(source_alpha, dtype=np.float32)
    if source_alpha.ndim == 0 and source_alpha <= 0.0:
        return

    destination_p = destination.astype(np.float32)
    opaque_backdrop = destination_alpha is None
    backdrop_alpha = (
        1.0
        if opaque_backdrop
        else destination_alpha.astype(np.float32) / 255.0
    )
    source_p = np.asarray(source_premultiplied, dtype=np.float32)

    if mode == "source-over":
        output_p = source_p + destination_p * (1.0 - source_alpha)
        output_alpha = source_alpha + backdrop_alpha * (1.0 - source_alpha)
    elif mode == "source-atop":
        output_p = source_p * backdrop_alpha + destination_p * (1.0 - source_alpha)
        output_alpha = backdrop_alpha
    elif mode == "xor":
        output_p = (
            source_p * (1.0 - backdrop_alpha)
            + destination_p * (1.0 - source_alpha)
        )
        output_alpha = (
            source_alpha * (1.0 - backdrop_alpha)
            + backdrop_alpha * (1.0 - source_alpha)
        )
    elif mode == "lighter":
        output_p = np.minimum(255.0, source_p + destination_p)
        output_alpha = np.minimum(1.0, source_alpha + backdrop_alpha)
    else:
        source_p = np.broadcast_to(source_p, destination.shape)
        source_alpha = np.broadcast_to(source_alpha, destination.shape)
        source_color = np.divide(
            source_p,
            source_alpha,
            out=np.zeros(destination.shape, dtype=np.float32),
            where=source_alpha > 0.0,
        )
        if opaque_backdrop:
            backdrop_color = destination_p
        else:
            backdrop_color = np.divide(
                destination_p,
                backdrop_alpha,
                out=np.zeros(destination.shape, dtype=np.float32),
                where=backdrop_alpha > 0.0,
            )
        blended = _blend_grayscale(backdrop_color, source_color, mode)
        blended_source = (
            (1.0 - backdrop_alpha) * source_color + backdrop_alpha * blended
        )
        output_p = (
            source_alpha * blended_source
            + destination_p * (1.0 - source_alpha)
        )
        output_alpha = source_alpha + backdrop_alpha * (1.0 - source_alpha)

    destination[:] = np.clip(np.rint(output_p), 0, 255).astype(np.uint8)
    if not opaque_backdrop:
        destination_alpha[:] = np.clip(
            np.rint(output_alpha * 255.0), 0, 255
        ).astype(np.uint8)


def _draw_rect(h, h_alpha, s, rng, width, height, composition_mode):
    if not s.get("rect_enabled", True):
        return
    p = _get_params(s, "rect", rng)
    w = max(2, int(p["scale"] * rng.uniform(0.3, 1.0)))
    hh = max(2, int(p["scale"] * rng.uniform(0.3, 1.0)))
    x = rng.randint(0, width - 1)
    y = rng.randint(0, height - 1)
    _blend_solid_stamp(
        h,
        h_alpha,
        p["brightness"],
        p["alpha"],
        x,
        y,
        w,
        hh,
        width,
        height,
        bool(s.get("seamless", False)),
        composition_mode,
    )


def _draw_grid(h, h_alpha, s, rng, width, height, composition_mode):
    if not s.get("grid_enabled", True):
        return
    p = _get_params(s, "grid", rng)
    cell = max(2, int(p["scale"] * rng.uniform(0.5, 1.0)))
    gap = max(0, p["gap"])
    step = cell + gap
    if step <= 0:
        return
    for gy in range(0, height, step):
        for gx in range(0, width, step):
            _blend_solid_stamp(
                h,
                h_alpha,
                p["brightness"],
                p["alpha"],
                gx,
                gy,
                cell,
                cell,
                width,
                height,
                bool(s.get("seamless", False)),
                composition_mode,
            )


def _draw_cols(h, h_alpha, s, rng, width, height, composition_mode):
    if not s.get("cols_enabled", True):
        return
    p = _get_params(s, "cols", rng)
    count = max(1, p["amount"])
    gap = max(0, p["gap"])
    total_gap = gap * (count - 1)
    avail = max(1, width - total_gap)
    slot = max(1, avail // count)
    x = rng.randint(0, max(1, width - 1))
    for i in range(count):
        if i > 0:
            x += gap + max(1, slot)
        if x >= width:
            break
        w = max(2, min(slot, int(p["scale"] * rng.uniform(0.4, 1.0))))
        x0 = min(width - 1, x)
        _blend_solid_stamp(
            h,
            h_alpha,
            p["brightness"],
            p["alpha"],
            x0,
            0,
            w,
            height,
            width,
            height,
            bool(s.get("seamless", False)),
            composition_mode,
        )


def _draw_rows(h, h_alpha, s, rng, width, height, composition_mode):
    if not s.get("rows_enabled", True):
        return
    p = _get_params(s, "rows", rng)
    count = max(1, p["amount"])
    gap = max(0, p["gap"])
    total_gap = gap * (count - 1)
    avail = max(1, height - total_gap)
    slot = max(1, avail // count)
    y = rng.randint(0, max(1, height - 1))
    for i in range(count):
        if i > 0:
            y += gap + max(1, slot)
        if y >= height:
            break
        hh = max(2, min(slot, int(p["scale"] * rng.uniform(0.4, 1.0))))
        y0 = min(height - 1, y)
        _blend_solid_stamp(
            h,
            h_alpha,
            p["brightness"],
            p["alpha"],
            0,
            y0,
            width,
            hh,
            width,
            height,
            bool(s.get("seamless", False)),
            composition_mode,
        )


def _draw_lines(h, h_alpha, s, rng, width, height, composition_mode):
    if not s.get("lines_enabled", True):
        return
    p = _get_params(s, "lines", rng)
    thickness = max(1, p["width"])
    if rng.random() < 0.5:
        y = rng.randint(0, height - 1)
        _blend_solid_stamp(
            h, h_alpha, p["brightness"], p["alpha"], 0, y,
            width, thickness, width, height,
            bool(s.get("seamless", False)), composition_mode,
        )
    else:
        x = rng.randint(0, width - 1)
        _blend_solid_stamp(
            h, h_alpha, p["brightness"], p["alpha"], x, 0,
            thickness, height, width, height,
            bool(s.get("seamless", False)), composition_mode,
        )


def _axis_segments(start, length, canvas_size, seamless):
    """Yield target/source intervals for a clipped or wrapping stamp axis."""
    if seamless:
        target = start % canvas_size
        source = 0
        remaining = length
        while remaining:
            take = min(remaining, canvas_size - target)
            yield target, target + take, source, source + take
            source += take
            remaining -= take
            target = 0
        return

    target_start = max(0, start)
    target_end = min(canvas_size, start + length)
    if target_start < target_end:
        yield target_start, target_end, target_start - start, target_end - start


def _blend_solid_stamp(
    target,
    target_alpha,
    brightness,
    alpha,
    x,
    y,
    width,
    height,
    canvas_width,
    canvas_height,
    seamless,
    composition_mode,
):
    """Draw a clipped/wrapping grayscale rectangle with Canvas-style alpha."""
    if width <= 0 or height <= 0 or alpha <= 0.0:
        return
    source_premultiplied = float(brightness) * float(alpha)
    x_ranges = tuple(_axis_segments(x, width, canvas_width, seamless))
    y_ranges = tuple(_axis_segments(y, height, canvas_height, seamless))
    for target_x0, target_x1, _source_x0, _source_x1 in x_ranges:
        for target_y0, target_y1, _source_y0, _source_y1 in y_ranges:
            destination = target[target_y0:target_y1, target_x0:target_x1]
            destination_alpha = (
                target_alpha[target_y0:target_y1, target_x0:target_x1]
                if target_alpha is not None
                else None
            )
            _composite_premultiplied(
                destination,
                destination_alpha,
                source_premultiplied,
                float(alpha),
                composition_mode,
            )


def _linear_axis_samples(start, end, source_size, stamp_size):
    """Return bilinear sample indices and weights for one scaled stamp axis."""
    coordinates = (
        (np.arange(start, end, dtype=np.float32) + 0.5)
        * (source_size / float(stamp_size))
        - 0.5
    )
    coordinates = np.clip(coordinates, 0.0, source_size - 1.0)
    lower = np.floor(coordinates).astype(np.int64)
    upper = np.minimum(lower + 1, source_size - 1)
    weight = (coordinates - lower).astype(np.float32)
    return lower, upper, weight


def _bilinear_sample(source, x0, x1, x_weight, y0, y1, y_weight):
    top = (
        source[y0[:, None], x0[None, :]] * (1.0 - x_weight[None, :])
        + source[y0[:, None], x1[None, :]] * x_weight[None, :]
    )
    bottom = (
        source[y1[:, None], x0[None, :]] * (1.0 - x_weight[None, :])
        + source[y1[:, None], x1[None, :]] * x_weight[None, :]
    )
    return top * (1.0 - y_weight[:, None]) + bottom * y_weight[:, None]


def _sprite_blend_arrays(gray, alpha):
    """Lazily cache a bounded set of float sprite buffers for repeated stamps."""
    cache_key = (id(gray), id(alpha))
    cached = _SPRITE_BLEND_CACHE.get(cache_key)
    if cached is not None:
        _SPRITE_BLEND_CACHE.move_to_end(cache_key)
        return cached

    source_alpha = alpha.astype(np.float32) / 255.0
    premultiplied = gray.astype(np.float32) * source_alpha
    cached = (premultiplied, source_alpha)
    _SPRITE_BLEND_CACHE[cache_key] = cached
    if len(_SPRITE_BLEND_CACHE) > _SPRITE_BLEND_CACHE_LIMIT:
        _SPRITE_BLEND_CACHE.popitem(last=False)
    return cached


def _blend_sprite_region(
    target,
    target_alpha,
    premultiplied,
    source_alpha,
    x_range,
    y_range,
    stamp_size,
    composition_mode,
):
    """Smoothly scale and composite one clipped sprite region."""
    tx0, tx1, sx0, sx1 = x_range
    ty0, ty1, sy0, sy1 = y_range
    source_h, source_w = premultiplied.shape
    x0, x1, x_weight = _linear_axis_samples(sx0, sx1, source_w, stamp_size)

    # Chunk rows to cap temporary allocations when generating 4K/8K textures.
    chunk_rows = 128
    for source_y0 in range(sy0, sy1, chunk_rows):
        source_y1 = min(sy1, source_y0 + chunk_rows)
        y0, y1, y_weight = _linear_axis_samples(
            source_y0, source_y1, source_h, stamp_size
        )
        sampled_premultiplied = _bilinear_sample(
            premultiplied, x0, x1, x_weight, y0, y1, y_weight
        )
        sampled_alpha = _bilinear_sample(
            source_alpha, x0, x1, x_weight, y0, y1, y_weight
        )
        target_y0 = ty0 + (source_y0 - sy0)
        target_y1 = target_y0 + (source_y1 - source_y0)
        destination = target[target_y0:target_y1, tx0:tx1]
        destination_alpha = (
            target_alpha[target_y0:target_y1, tx0:tx1]
            if target_alpha is not None
            else None
        )
        _composite_premultiplied(
            destination,
            destination_alpha,
            sampled_premultiplied,
            sampled_alpha,
            composition_mode,
        )


def _draw_sprite(h, h_alpha, s, rng, width, height, sprites, composition_mode):
    if not sprites:
        return

    gray, alpha = rng.choice(sprites)
    premultiplied, source_alpha = _sprite_blend_arrays(gray, alpha)
    if s.get("sprites_rotation_enabled", True):
        turns = rng.randint(0, 3)
        if turns:
            premultiplied = np.rot90(premultiplied, turns)
            source_alpha = np.rot90(source_alpha, turns)

    reference_size = min(width, height)
    stamp_size = rng.randint(
        max(2, reference_size // 32), max(2, reference_size // 2)
    )
    seamless = bool(s.get("seamless", False))
    if seamless:
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
    else:
        margin = max(1, reference_size // 16)
        x = rng.randint(-margin, width - 1)
        y = rng.randint(-margin, height - 1)

    x_ranges = tuple(_axis_segments(x, stamp_size, width, seamless))
    y_ranges = tuple(_axis_segments(y, stamp_size, height, seamless))
    for y_range in y_ranges:
        for x_range in x_ranges:
            _blend_sprite_region(
                h,
                h_alpha,
                premultiplied,
                source_alpha,
                x_range,
                y_range,
                stamp_size,
                composition_mode,
            )


def _canvas_dimensions(size):
    """Return (width, height), accepting the legacy scalar square size."""
    if isinstance(size, (tuple, list)):
        if len(size) != 2:
            raise ValueError("canvas dimensions must contain width and height")
        width, height = int(size[0]), int(size[1])
    else:
        width = height = int(size)
    if width < 1 or height < 1:
        raise ValueError("canvas width and height must be at least 1")
    return width, height


def generate_canvas_mask(size, shape="FULL", roundness=0.15):
    """Return a pixel-space boolean mask, or None for a full canvas."""
    width, height = _canvas_dimensions(size)
    shape = str(shape).upper()
    if shape == "FULL":
        return None
    if shape not in {"ROUNDED", "CIRCLE", "HEXAGON"}:
        raise ValueError("Unsupported canvas shape: " + shape)

    center_x = (width - 1) * 0.5
    center_y = (height - 1) * 0.5
    x = np.arange(width, dtype=np.float32) - center_x
    mask = np.empty((height, width), dtype=bool)
    chunk_rows = 512

    if shape == "CIRCLE":
        radius = max(0.5, min(width, height) * 0.5)
        radius_squared = radius * radius
        for y0 in range(0, height, chunk_rows):
            y1 = min(height, y0 + chunk_rows)
            y = np.arange(y0, y1, dtype=np.float32) - center_y
            mask[y0:y1] = (
                x[None, :] * x[None, :] + y[:, None] * y[:, None]
                <= radius_squared
            )
        return mask

    if shape == "HEXAGON":
        sqrt_three = np.float32(np.sqrt(3.0))
        radius = max(
            0.5,
            min(width * 0.5, height / float(sqrt_three)),
        )
        abs_x = np.abs(x)
        for y0 in range(0, height, chunk_rows):
            y1 = min(height, y0 + chunk_rows)
            abs_y = np.abs(np.arange(y0, y1, dtype=np.float32) - center_y)
            mask[y0:y1] = (
                (abs_x[None, :] <= radius)
                & (abs_y[:, None] <= sqrt_three * radius * 0.5)
                & (
                    sqrt_three * abs_x[None, :] + abs_y[:, None]
                    <= sqrt_three * radius
                )
            )
        return mask

    roundness = min(0.5, max(0.0, float(roundness)))
    if roundness == 0.0:
        mask.fill(True)
        return mask
    radius = max(
        0.5,
        roundness * min(width, height),
    )
    inner_x = max(0.0, width * 0.5 - radius)
    inner_y = max(0.0, height * 0.5 - radius)
    dx = np.maximum(np.abs(x) - inner_x, 0.0)
    for y0 in range(0, height, chunk_rows):
        y1 = min(height, y0 + chunk_rows)
        y = np.arange(y0, y1, dtype=np.float32) - center_y
        dy = np.maximum(np.abs(y) - inner_y, 0.0)
        mask[y0:y1] = (
            dx[None, :] * dx[None, :] + dy[:, None] * dy[:, None]
            <= radius * radius
        )
    return mask


def generate_height(settings, size, seed=0):
    """Generate a uint8 height map for a scalar or (width, height) size."""
    width, height = _canvas_dimensions(size)
    rng = random.Random(seed)
    # All drawing values are 8-bit. Keeping the canvas uint8 cuts height-map
    # memory to one quarter of the previous int32 allocation (notably at 8K).
    h = np.full(
        (height, width),
        int(settings.get("background_brightness", 128)),
        dtype=np.uint8,
    )
    n = int(settings.get("iterations", 1500))

    sprites = []
    if settings.get("sprites_enabled", False):
        selected_packs = [
            pack
            for pack in SPRITE_PACKS
            if settings.get("sprite_pack_" + pack, False)
        ]
        library = _load_sprite_library(selected_packs)
        for pack in selected_packs:
            sprites.extend(library.get(pack, ()))

    composition_modes = [
        mode
        for mode in COMPOSITION_MODES
        if settings.get("comp_" + mode, False)
    ]
    if not composition_modes:
        composition_modes = ["source-over"]
    # The opaque background stays opaque for every supported operation except
    # xor, so only that mode needs a second full-resolution alpha canvas.
    h_alpha = (
        np.full((height, width), 255, dtype=np.uint8)
        if "xor" in composition_modes
        else None
    )

    # Match the original draw loop: choose one of all six generator slots per
    # iteration, then let a disabled slot become a no-op. This preserves the
    # original density relationship when generators are toggled on and off.
    drawers = (
        lambda mode: _draw_rect(h, h_alpha, settings, rng, width, height, mode),
        lambda mode: _draw_grid(h, h_alpha, settings, rng, width, height, mode),
        lambda mode: _draw_cols(h, h_alpha, settings, rng, width, height, mode),
        lambda mode: _draw_rows(h, h_alpha, settings, rng, width, height, mode),
        lambda mode: _draw_lines(h, h_alpha, settings, rng, width, height, mode),
        lambda mode: _draw_sprite(
            h, h_alpha, settings, rng, width, height, sprites, mode
        )
        if settings.get("sprites_enabled", False)
        else None,
    )
    for _ in range(n):
        composition_mode = rng.choice(composition_modes)
        rng.choice(drawers)(composition_mode)
    mask = generate_canvas_mask(
        (width, height),
        settings.get("canvas_shape", "FULL"),
        settings.get("mask_roundness", 0.15),
    )
    if mask is not None:
        outside_mode = settings.get("mask_outside", "BACKGROUND")
        outside_value = (
            int(settings.get("background_brightness", 128))
            if outside_mode == "BACKGROUND"
            else 128
        )
        h[~mask] = np.uint8(max(0, min(255, outside_value)))
    return h


def generate_color(height, stops, sharp=False, alpha_mask=None):
    """Map grayscale height (0-255) through a color gradient.
    stops: list of (pos 0..1, (r,g,b) 0..255). Returns HxWx3 uint8,
    or HxWx4 when a boolean alpha mask is supplied.
    When sharp is true, each pixel uses the color of the preceding stop rather
    than interpolating, matching a constant-interpolation color ramp.
    """
    if not stops:
        stops = DEFAULT_COLOR_STOPS
    stops = sorted(stops, key=lambda s: s[0])
    pos = np.array([s[0] * 255.0 for s in stops], dtype=np.float32)
    col = np.array([s[1] for s in stops], dtype=np.float32)
    if alpha_mask is not None:
        alpha_mask = np.asarray(alpha_mask, dtype=bool)
        if alpha_mask.shape != height.shape:
            raise ValueError("alpha mask must match the height-map dimensions")
    channels = 4 if alpha_mask is not None else 3
    out = np.empty((height.shape[0], height.shape[1], channels), dtype=np.uint8)

    # NumPy interpolation returns float64. Processing bounded row chunks avoids
    # several full-resolution floating-point temporaries at 4K/8K.
    chunk_rows = 256
    for y0 in range(0, height.shape[0], chunk_rows):
        y1 = min(height.shape[0], y0 + chunk_rows)
        values = height[y0:y1].ravel()
        if sharp:
            stop_indices = np.searchsorted(pos, values, side="right") - 1
            stop_indices = np.clip(stop_indices, 0, len(stops) - 1)
            mapped = np.clip(col[stop_indices], 0, 255).astype(np.uint8)
            out[y0:y1, :, :3] = mapped.reshape(
                y1 - y0, height.shape[1], 3
            )
        else:
            for channel in range(3):
                interpolated = np.interp(values, pos, col[:, channel])
                out[y0:y1, :, channel] = np.clip(
                    interpolated.reshape(y1 - y0, height.shape[1]), 0, 255
                ).astype(np.uint8)
        if alpha_mask is not None:
            out[y0:y1, :, 3] = np.where(alpha_mask[y0:y1], 255, 0).astype(
                np.uint8
            )
    return out


def generate_normal(height, strength=2.0):
    """Compute a tangent-space normal map from a grayscale height map."""
    rows, columns = height.shape
    out = np.empty((rows, columns, 3), dtype=np.uint8)
    chunk_rows = 256
    for y0 in range(0, rows, chunk_rows):
        y1 = min(rows, y0 + chunk_rows)
        read_y0 = max(0, y0 - 1)
        read_y1 = min(rows, y1 + 1)
        sample = height[read_y0:read_y1].astype(np.float32) / 255.0
        dx = (
            np.gradient(sample, axis=1) * strength
            if columns > 1
            else np.zeros_like(sample)
        )
        dy = (
            np.gradient(sample, axis=0) * strength
            if rows > 1
            else np.zeros_like(sample)
        )
        local_y0 = y0 - read_y0
        local_y1 = local_y0 + (y1 - y0)
        dx = dx[local_y0:local_y1]
        dy = dy[local_y0:local_y1]
        norm = np.sqrt(dx * dx + dy * dy + 1.0)
        out[y0:y1, :, 0] = np.clip((-dx / norm * 0.5 + 0.5) * 255, 0, 255)
        out[y0:y1, :, 1] = np.clip((-dy / norm * 0.5 + 0.5) * 255, 0, 255)
        out[y0:y1, :, 2] = np.clip((1.0 / norm * 0.5 + 0.5) * 255, 0, 255)
    return out


def randomize(settings):
    """Return a new settings dict with randomized values (for 'Randomize all')."""
    rng = random.Random()
    d = dict(settings)
    d["iterations"] = rng.randint(500, 3000)
    d["background_brightness"] = rng.randint(0, 255)
    for s in ["rect", "grid", "cols", "rows", "lines"]:
        d[s + "_enabled"] = rng.random() < 0.8
        d[s + "_brightness_min"] = rng.randint(0, 128)
        d[s + "_brightness_max"] = rng.randint(128, 255)
        d[s + "_alpha_min"] = rng.randint(0, 50)
        d[s + "_alpha_max"] = rng.randint(50, 100)
        d[s + "_scale_min"] = rng.randint(5, 64)
        d[s + "_scale_max"] = rng.randint(64, 512)
    for s in ["grid", "cols", "rows"]:
        d[s + "_amount_min"] = rng.randint(2, 6)
        d[s + "_amount_max"] = rng.randint(6, 20)
        d[s + "_gap_min"] = rng.randint(0, 200)
        d[s + "_gap_max"] = rng.randint(200, 1200)
    d["lines_width_min"] = rng.randint(2, 20)
    d["lines_width_max"] = rng.randint(20, 80)
    d["sprites_enabled"] = rng.random() < 0.8
    selected_pack = False
    for pack in SPRITE_PACKS:
        enabled = rng.random() < 0.5
        d["sprite_pack_" + pack] = enabled
        selected_pack = selected_pack or enabled
    if d["sprites_enabled"] and not selected_pack:
        d["sprite_pack_" + rng.choice(SPRITE_PACKS)] = True
    d["sprites_rotation_enabled"] = rng.random() < 0.8
    selected_composition = False
    for m in COMPOSITION_MODES:
        d["comp_" + m] = rng.random() < 0.5
        selected_composition = selected_composition or d["comp_" + m]
    if not selected_composition:
        d["comp_source-over"] = True
    return d
