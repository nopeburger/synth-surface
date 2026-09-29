"""Build the runtime sprite cache from the bundled SVG source files.

This is a packaging/development helper, not a Blender runtime dependency.
It requires Inkscape, Pillow, and NumPy.
"""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile
from xml.etree import ElementTree

import numpy as np
from PIL import Image


PACKS = ("classic", "bigdata", "aggromaxx", "crappack", "circuitry")


def _numeric_sort_key(path):
    try:
        return int(path.stem)
    except ValueError:
        return path.stem


def _svg_export_dimensions(svg_path, size):
    """Fit an SVG page inside a square cache cell without stretching it."""
    root = ElementTree.parse(svg_path).getroot()
    view_box = root.get("viewBox")
    if not view_box:
        raise RuntimeError("SVG has no viewBox: " + str(svg_path))
    values = [float(value) for value in view_box.replace(",", " ").split()]
    if len(values) != 4 or values[2] <= 0.0 or values[3] <= 0.0:
        raise RuntimeError("SVG has an invalid viewBox: " + str(svg_path))

    width, height = values[2], values[3]
    if width >= height:
        return size, max(1, round(size * height / width))
    return max(1, round(size * width / height)), size


def build(sprite_root, output, size=1024):
    inkscape = shutil.which("inkscape")
    if not inkscape:
        raise RuntimeError("Inkscape was not found on PATH")

    arrays = {}
    with tempfile.TemporaryDirectory(prefix="dx-sprites-") as temp_dir:
        temp_root = Path(temp_dir)
        for pack in PACKS:
            svg_files = sorted((sprite_root / pack).glob("*.svg"), key=_numeric_sort_key)
            if not svg_files:
                raise RuntimeError("No SVG files found for pack: " + pack)

            gray_images = []
            alpha_images = []
            for index, svg_path in enumerate(svg_files):
                png_path = temp_root / (pack + "-" + str(index) + ".png")
                export_width, export_height = _svg_export_dimensions(svg_path, size)
                subprocess.run(
                    [
                        inkscape,
                        str(svg_path),
                        "--export-filename=" + str(png_path),
                        "--export-width=" + str(export_width),
                        "--export-height=" + str(export_height),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                with Image.open(png_path) as image:
                    rendered = image.convert("RGBA")
                    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                    offset = (
                        (size - rendered.width) // 2,
                        (size - rendered.height) // 2,
                    )
                    canvas.paste(rendered, offset)
                    rgba = np.asarray(canvas, dtype=np.uint8)
                rgb = rgba[..., :3].astype(np.uint16)
                gray = ((rgb[..., 0] * 77 + rgb[..., 1] * 150 + rgb[..., 2] * 29) >> 8).astype(np.uint8)
                gray_images.append(gray)
                alpha_images.append(rgba[..., 3])

            arrays[pack + "_gray"] = np.stack(gray_images)
            arrays[pack + "_alpha"] = np.stack(alpha_images)
            print(pack + ":", len(svg_files))

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, **arrays)
    print("Wrote", output)


def main():
    addon_root = Path(__file__).resolve().parents[1] / "displacementx_addon"
    parser = argparse.ArgumentParser()
    parser.add_argument("--sprite-root", type=Path, default=addon_root / "sprites")
    parser.add_argument("--output", type=Path, default=addon_root / "sprites" / "sprite_cache.npz")
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()
    build(args.sprite_root, args.output, args.size)


if __name__ == "__main__":
    main()
