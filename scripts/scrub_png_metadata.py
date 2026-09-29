"""Remove PNG metadata from publishable documentation images without changing pixels."""

from pathlib import Path
import struct
import sys


SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"}
IMAGES = (
    "surface_panel.png",
    "surface_detail.png",
    "surface_copper.png",
    "surface_violet.png",
    "height_map.png",
    "scatter_lights.png",
    "scatterlights-torus.png",
)


def scrub(path: Path):
    raw = path.read_bytes()
    if not raw.startswith(SIGNATURE):
        raise ValueError(f"Not a PNG: {path}")
    result = bytearray(SIGNATURE)
    offset = len(SIGNATURE)
    chunks = []
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError(f"Truncated PNG chunk: {path}")
        length = struct.unpack_from(">I", raw, offset)[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + length + 12
        if end > len(raw):
            raise ValueError(f"Truncated PNG payload: {path}")
        if kind in KEEP:
            result.extend(raw[offset:end])
            chunks.append(kind)
        offset = end
        if kind == b"IEND":
            break
    if offset != len(raw) or b"IHDR" not in chunks or b"IDAT" not in chunks or chunks[-1] != b"IEND":
        raise ValueError(f"Invalid PNG structure: {path}")
    path.write_bytes(result)
    print(path.name, "kept", len(chunks), "image chunks")


def main():
    folder = Path(__file__).resolve().parents[1] / "docs" / "images"
    for name in IMAGES:
        scrub(folder / name)


if __name__ == "__main__":
    sys.exit(main())
