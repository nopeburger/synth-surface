# Contributing

Synth Surface is a Blender port of [Displacement X](https://github.com/satelllte/displacementx). Keep attribution and the GPL-3.0 license with any modified distribution. The root `LICENSE` is the upstream license text; `NOTICE.md` describes the port and sprite sources.

## Make a change

1. Edit the Python code in `displacementx_addon/`. Blender imports that package directly. Keep the `displacementx_addon` package name for existing project compatibility.
2. Run `python -m compileall -q displacementx_addon` for a syntax check. This creates ignored `__pycache__` directories locally.
3. Test in Blender with the package on its Python path, or build and install the release ZIP. For the included integration tests (`tests/verify_scatter_lights.py` and `tests/verify_release.py`), run Blender in background mode with an OS temporary directory as its working directory and absolute paths for `--python` and log output. The scatter-light test creates a temporary `.blend` and removes it afterward.
4. Run `python scripts/build_release.py` to make `dist/synth_surface_v1.1.zip`. The script includes only runtime files and required legal notices. Inspect archive contents before distributing.

If SVG sprites change, run `python scripts/build_sprite_cache.py` before building. This development-only step requires Inkscape on `PATH`, Pillow, and NumPy. The built cache is used by Blender; no SVG converter is needed at runtime.

The documentation render can be regenerated with `scripts/render_surface_example.py` in Blender background mode from a system temporary working directory. Save only intended images under `docs/images/`, then run `python scripts/scrub_png_metadata.py` to remove scene and file metadata from all published PNGs. The scatter-light comparison image is a render made with the same add-on; retain it unless its lighting example changes.

Keep generated scenes, rendered previews, test reports, logs, archives, personal paths, credentials, and machine-specific settings out of commits. `.gitignore` excludes common generated files; review `git status` and the release ZIP file list before publishing.
