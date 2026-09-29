# Changelog

## 1.2.0

- Preserve float32 values through height blending, sprite resampling, color gradients, normal generation, and scatter-light antialiasing.
- Create full-float Blender images and pack them as 32-bit EXRs, preserving fractional values when projects are saved and reopened.
- Store color maps in scene-linear RGB while retaining the existing gradient appearance; keep height, normal, and light maps as Non-Color data.
- Add **Export Maps (32-bit EXR)** under Output, using full-float channels and lossless ZIP compression.
- Replace earlier byte images when Generate & Apply is used; retain the existing package identifier, settings, and 8192-pixel maximum dimension.

## 1.1.0

- Blender port of Displacement X with geometric generators, bundled sprite packs, composition modes, canvas masks, color gradients, and displacement.
- Scatter Lights with round/square shapes, independent seed, editable palette, and material emission.
- Installation guide, contributor tools, and documentation renders.
