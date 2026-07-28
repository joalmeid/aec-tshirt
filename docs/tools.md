# Tools

Eleven Python files in `tools/`. All are dependency-free beyond `numpy` and
`Pillow` — deliberately, because this machine has no poppler, cairo, resvg,
scipy, OpenCV or headless browser, and the pipeline should not need them.

Run everything from the repo root.

---

## `extract_pattern.py` — read the garment's pattern out of the model

**Need.** Everything downstream is positioned in millimetres of fabric, so the
pipeline has to know how each panel's UVs map to real measurements — and which
glTF node each panel actually is, which the project has got wrong repeatedly.

**Does.** Reads `assets/tshirt.glb`, and per panel writes the millimetre extents,
the Babylon `uScale/uOffset/vScale/vOffset`, texel-density statistics and the
u↔world-axis correlations to `pipeline-design/pattern/panels.json`, plus mask and
millimetre-grid guide images.

The texel-density ratio is the interesting output: near 1.0 means the unwrap is a
true flat pattern and the whole approach applies. It is the first thing to check
on any new model.

```bash
python3 tools/extract_pattern.py
```

---

## `pdf_to_svg.py` — recover the print artwork as vector

**Need.** The authoritative design is a print-ready PDF. The PSD alternative is a
2D mockup with no UV information (see [decisions.md](decisions.md) §2), and there
is no PDF library available.

**Does.** Parses the PDF content stream directly — only the operator subset this
artwork uses — and emits `official-artwork.svg`, a per-path JSON report with
fills and millimetre bounding boxes, a rasterised preview, and every embedded
image. Two of those images are the logo stencils the build consumes.

```bash
python3 tools/pdf_to_svg.py
```

---

## `build_print_textures.py` — compose the panel textures

**Need.** Turn the design into one base-colour texture per pattern piece, with
every element placed by real garment measurement rather than by pixel-nudging.

**Does.** The main event. Base colour, artwork paths through a millimetre affine,
procedural stripes, logo stencils, the blank cuff band, and topstitching — then
supersample and downsample. This is the **only** stage that is specific to this
event's design; everything else is garment-generic.

```bash
python3 tools/build_print_textures.py
```

---

## `build_production_glb.py` — bake the runtime into the model

**Need.** `src/index.html` applies the UV mapping, textures and materials in
JavaScript, so anything that loads `assets/tshirt.glb` without running that page
— a partner's site, `<model-viewer>`, Blender, a supplier — gets an untextured
shirt.

**Does.** Writes `assets/tshirt-prod.glb`: `TEXCOORD_0` rewritten so the per-panel
`uScale/uOffset` is already applied, `TEXCOORD_1` for the knit tiling, generated
`TANGENT`, the seven PNGs embedded, two samplers, and six materials with
`KHR_materials_sheen`. No extension is needed for the UV mapping itself — baking
the attribute beats `KHR_texture_transform` for portability, and removes a
convention this project has got wrong before.

Panel geometry comes from `panels.json` and node names from
`extract_pattern.py`'s `PANEL_GROUPS`, imported rather than copied, so the bake
cannot drift from what was measured. It reads back what it wrote and fails if any
panel's UVs left 0..1.

Compression is deliberately *not* here — it needs external binaries. The command
is printed at the end. See [production-delivery.md](production-delivery.md).

```bash
python3 tools/build_production_glb.py
python3 tools/build_production_glb.py --textures calib   # the acceptance build
```

---

## `seams.py` — garment seams as geometry

**Need.** Topstitching has to land on the real seams. Since a UV island's
boundary *is* a seam, they can be recovered from the mesh instead of drawn.

**Does.** Boundary-loop extraction, inward offsetting (with rejection of contours
the offset turns inside out), open-run offsetting with one-sided ends, end
trimming, arc-length dashing, and the proximity helper that lets the caller
classify which seam is which. Pure geometry — the garment policy lives in
`build_print_textures.py`.

Library, not a script.

---

## `vectorart.py` — load and rasterise the converted artwork

**Need.** Draw the PDF's paths into a texture at a given millimetre-to-pixel
scale, with glyph counters staying open.

**Does.** Loads `official-artwork.svg`, flattens béziers, and fills each path's
contours as one shape by XOR-compositing them — the even-odd rule, which is what
keeps the holes in **A**, **O**, **R**, **D**, **0** and **6**.

Library, not a script.

---

## `glb.py` — minimal glTF reader

**Need.** Read positions, normals, UVs and indices without pulling in a 3D
library.

**Does.** Covers exactly what `assets/tshirt.glb` uses — single binary chunk,
non-sparse accessors, triangles, static node hierarchy with transforms composed
down the tree. No animation, skinning or Draco.

Library, not a script.

---

## `make_weave_normal.py` — the knit fabric normal map

**Need.** PBR sheen needs surface structure to catch the light; a flat normal
reads as plastic.

**Does.** Generates a tileable jersey-knit normal map analytically — loop legs
converging per course, plus the loop head, over frequency-filtered noise so the
tile is periodic by construction. The tile represents a real 15 mm patch of
fabric, which is what lets the runtime set `uScale = 1/15` and get the same
density on every panel.

```bash
python3 tools/make_weave_normal.py
```

---

## `make_calibration.py` — orientation test textures

**Need.** Which way a panel's texture faces depends on the pattern's u↔X sign,
the glTF V convention and the camera's handedness all at once. Reasoning about
them together is unreliable — it has produced a wrong answer that survived
several commits.

**Does.** Writes a millimetre grid per panel with coloured edges (top red, bottom
blue), corner coordinates and a large asymmetric **F**, so one render settles
orientation and texel density by observation.

```bash
python3 tools/make_calibration.py
python3 tools/preview_render.py --textures calib --view front
```

---

## `preview_render.py` — software render, no browser

**Need.** A fast loop: bake a texture, see it on the real mesh, without a
browser, a screenshot, or a round trip through a human.

**Does.** A z-buffered Lambert rasteriser that reproduces Babylon's left-handed
camera basis and the same UV normalisation, so what it says about orientation,
mirroring, stitch placement and panel coverage transfers.

**Trust it only that far.** It cannot judge sheen, IBL or tone mapping, and it
once had its handedness backwards, which mirrored every render and put a wrong
sign into the scene. Confirm anything load-bearing in a browser.

```bash
python3 tools/preview_render.py --textures print --view reference
python3 tools/preview_render.py --textures print --view left
```

Views are named from the **wearer's** point of view, like everything else here.

---

## `check_scene_sync.py` — keep the two scene files honest

**Need.** `src/index.html` and `src/playground.js` are the same scene twice. A
fix applied to one and not the other produces a bug in whichever copy nobody is
looking at — which has happened.

**Does.** Strips comments and blank lines from both and diffs the remaining code,
allowing only the differences that are meant to exist: `ASSET_ROOT`, and the page
scaffolding the Playground supplies for itself. Exits non-zero on drift.

```bash
python3 tools/check_scene_sync.py
```
