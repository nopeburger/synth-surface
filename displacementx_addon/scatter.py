"""Deterministic, resolution-independent emission stamps (NumPy only).

Colors are scene-linear RGB in 0..1, matching Blender's light color pickers.
The emission texture stores linear RGB in float32; material strength supplies HDR.
"""
import math
import numpy as np

from .core import _axis_segments, _canvas_dimensions, generate_canvas_mask


DEFAULT_LIGHT_PALETTE = (
    (1.0, 0.06, 0.35),
    (0.08, 0.65, 1.0),
    (0.35, 1.0, 0.12),
    (1.0, 0.8, 0.5),
    (0.55, 0.12, 1.0),
)


def light_layout(settings, size):
    """Return x/y, diameter, brightness and color samples in shorter-edge units.

    A separate random stream leaves the surface generators untouched. Sampling
    every attribute up front also keeps positions fixed when shape, size, color
    or brightness settings change. Density is the count over the full canvas
    before clipping by the canvas mask.
    """
    width, height = _canvas_dimensions(size)
    count = min(50000, max(0, int(settings.get("lights_density", 800))))
    rng = np.random.default_rng(int(settings.get("lights_seed", 0)) % (2 ** 64))
    samples = rng.random((count, 5))
    if not count:
        return samples
    short_edge = min(width, height)
    nx = max(1, round(math.sqrt(count * width / height)))
    ny = math.ceil(count / nx)
    # Select an evenly distributed subset when the grid has spare cells.
    cells = np.floor((np.arange(count) + 0.5) * (nx * ny) / count).astype(int)
    jitter = np.clip(settings.get("lights_randomness", 1.0), 0.0, 1.0)
    samples[:, 0] = ((cells % nx + 0.5 + (samples[:, 0] - 0.5) * jitter)
                     / nx * width / short_edge)
    samples[:, 1] = ((cells // nx + 0.5 + (samples[:, 1] - 0.5) * jitter)
                     / ny * height / short_edge)
    scale = np.clip(settings.get("lights_scale", 0.004), 0.0001, 0.1)
    variation = np.clip(settings.get("lights_scale_randomness", 0.5), 0.0, 1.0)
    samples[:, 2] = scale * (1.0 - variation * samples[:, 2])
    variation = np.clip(settings.get("lights_intensity_randomness", 0.4), 0.0, 1.0)
    samples[:, 3] = 1.0 - variation * samples[:, 3]
    return samples


def _stamp_light(target, cx, cy, radius, color, shape, seamless):
    """Antialias a light into a bounded patch, wrapping at texture boundaries."""
    height, width = target.shape[:2]
    x0 = math.floor(cx - radius - 1)
    y0 = math.floor(cy - radius - 1)
    x1 = math.ceil(cx + radius + 1)
    y1 = math.ceil(cy + radius + 1)
    x = np.arange(x0, x1, dtype=np.float32)
    y = np.arange(y0, y1, dtype=np.float32)
    if shape == "SQUARE":
        # Exact pixel coverage of an axis-aligned square, even below one pixel.
        dx = np.maximum(0.0, np.minimum(x + 1, cx + radius) - np.maximum(x, cx - radius))
        dy = np.maximum(0.0, np.minimum(y + 1, cy + radius) - np.maximum(y, cy - radius))
        coverage = dy[:, None] * dx[None, :]
    elif radius < 0.5:
        # Preserve tiny lights' energy in the reduced preview instead of
        # dropping lights whose centers fall between pixel samples.
        dx = np.maximum(0.0, 1.0 - np.abs(x + 0.5 - cx))
        dy = np.maximum(0.0, 1.0 - np.abs(y + 0.5 - cy))
        coverage = dy[:, None] * dx[None, :] * (math.pi * radius * radius)
    else:
        distance = np.hypot(x[None, :] + 0.5 - cx, y[:, None] + 0.5 - cy)
        coverage = np.clip(radius + 0.5 - distance, 0.0, 1.0)
    stamp = (coverage[..., None] * color).astype(np.float32)
    for tx0, tx1, sx0, sx1 in _axis_segments(x0, x1 - x0, width, seamless):
        for ty0, ty1, sy0, sy1 in _axis_segments(y0, y1 - y0, height, seamless):
            region = target[ty0:ty1, tx0:tx1]
            # Max blending prevents density/overlap from inflating brightness.
            np.maximum(region, stamp[sy0:sy1, sx0:sx1], out=region)


def generate_emission(settings, size, palette=None):
    """Return a black-backed HxWx3 float32 linear emission map, or None if off."""
    if not settings.get("lights_enabled", False):
        return None
    width, height = _canvas_dimensions(size)
    out = np.zeros((height, width, 3), dtype=np.float32)
    samples = light_layout(settings, size)
    if not len(samples):
        return out
    color = np.asarray(settings.get("lights_color", DEFAULT_LIGHT_PALETTE[0]), dtype=np.float32)
    if settings.get("lights_color_mode", "SINGLE") == "PALETTE":
        colors = np.asarray(palette if palette is not None and len(palette) else DEFAULT_LIGHT_PALETTE,
                            dtype=np.float32)
    else:
        colors = color[None, :]
    colors = np.clip(np.nan_to_num(colors), 0.0, 1.0)
    if colors.ndim != 2 or colors.shape[1] != 3:
        raise ValueError("Light colors must contain three RGB channels")
    shape = settings.get("lights_shape", "ROUND")
    if shape not in {"ROUND", "SQUARE"}:
        raise ValueError("Unsupported light shape: " + str(shape))
    short_edge = min(width, height)
    seamless = settings.get("seamless", False)
    for x, y, diameter, brightness, color_sample in samples:
        tint = colors[min(len(colors) - 1, int(color_sample * len(colors)))] * brightness
        _stamp_light(out, x * short_edge, y * short_edge, diameter * short_edge * 0.5,
                     tint, shape, seamless)
    mask = generate_canvas_mask(size, settings.get("canvas_shape", "FULL"),
                                settings.get("mask_roundness", 0.15))
    if mask is not None:
        out[~mask] = 0
    return out


def preview_with_lights(color, emission, intensity):
    """Add emission in linear light to an SDR color preview, preserving alpha."""
    if emission is None or intensity <= 0:
        return color
    out = color.copy()
    # Bounded row buffers also allow this helper to preview larger images.
    for y0 in range(0, color.shape[0], 256):
        rgb = color[y0:y0 + 256, :, :3]
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        linear += emission[y0:y0 + 256] * float(intensity)
        linear = np.clip(linear, 0.0, 1.0)
        rgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1.0 / 2.4) - 0.055)
        out[y0:y0 + 256, :, :3] = np.clip(rgb, 0.0, 1.0)
    return out
