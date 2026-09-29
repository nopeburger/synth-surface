"""Build the installable Blender add-on ZIP from an explicit runtime allowlist."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "displacementx_addon"
VERSION = "1.1"
OUTPUT = ROOT / "dist" / f"synth_surface_v{VERSION}.zip"

SOURCES = {
    "__init__.py": PACKAGE / "__init__.py",
    "addon.py": PACKAGE / "addon.py",
    "core.py": PACKAGE / "core.py",
    "scatter.py": PACKAGE / "scatter.py",
    "sprites/sprite_cache.npz": PACKAGE / "sprites" / "sprite_cache.npz",
    "LICENSE": ROOT / "LICENSE",
    "NOTICE.md": ROOT / "NOTICE.md",
}


def main():
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing release files: " + ", ".join(missing))
    OUTPUT.parent.mkdir(exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in SOURCES.items():
            archive.write(path, f"displacementx_addon/{name}")
    with ZipFile(OUTPUT) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Release ZIP failed CRC validation")
        for info in archive.infolist():
            print(f"{info.filename}: {info.file_size} bytes")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
