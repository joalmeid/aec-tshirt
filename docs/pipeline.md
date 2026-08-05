# The pipeline

Everything that turns a garment model and a print design into what the browser
renders. It is entirely offline: the browser loads finished PNGs and a `.glb`,
and does no generation of its own.

```
  assets/tshirt.glb ──────────► extract_pattern.py ──► pipeline-design/pattern/panels.json
   (garment model)                                     + mask/guide images
                                                              │
  T-shirt ...oficial 2026.pdf ─► pdf_to_svg.py ──► pipeline-design/artwork/
   (print artwork, vector)                          official-artwork.svg + .json
                                                    pdf-images/*.png (logo stencils)
                                                              │
                                                              ▼
                                        build_print_textures.py
                                        (+ vectorart.py, seams.py, glb.py)
                                                              │
                                                              ▼
                                        assets/textures/print-*.png   ◄── the deliverable
                                                              │
  sponsor logo .svg ─────► make_logo_stencil.py ───────────────┤
   (outside the artwork)     pipeline-design/artwork/logo-*.png │
                                                               │
  make_weave_normal.py ──► assets/textures/knit-normal.png     │
  make_calibration.py ──► assets/textures/calib-*.png          │
                                                              ▼
                                        src/index.html · src/playground.js
                                        (Babylon PBR scene)
                                                              │
                          assets/tshirt.glb ──► build_production_glb.py
                                                              │
                                                              ▼
                                        assets/tshirt-prod.glb  ◄── what ships
                                        src/index-prod.html
```

The last stage is separate on purpose: everything above it is how the design is
*developed*, and it leaves the UV mapping and materials to JavaScript.
`build_production_glb.py` folds those into the model so it stands alone. See
[production-delivery.md](production-delivery.md).

## Stages

### 1. Extract the pattern — `extract_pattern.py`

Reads the `.glb` and writes `pipeline-design/pattern/panels.json`: each panel's millimetre
extents, the `uScale/uOffset/vScale/vOffset` Babylon needs to map those onto
0..1, the texel-density statistics, and the u↔world-axis correlations.

This is the single point of truth for panel → glTF node mapping. Run it whenever
the model changes; the numbers in the scene's `PANELS` table are re-emitted from
its output.

### 2. Convert the artwork — `pdf_to_svg.py`

Parses the print PDF's content stream directly (no poppler, cairo or resvg on
this machine) into `official-artwork.svg`, a per-path report with colours and
bounding boxes in millimetres, and the embedded raster images — of which two are
the logo stencils the build uses.

Only needed when the print design changes.

### 3. Compose the textures — `build_print_textures.py`

The centre of the pipeline, and the only genuinely event-specific stage. For each
panel it:

1. fills the base colour
2. draws the design — artwork vector paths through a millimetre affine, procedural
   stripes, and logo stencils
3. blanks the sleeve below the cuff stitch
4. classifies the panel's boundary into seams and draws the topstitching
5. supersamples ×3 and downsamples

Everything is positioned in **pattern millimetres**, so a change here is a change
in real garment measurements. See [decisions.md](decisions.md) §1–§3, §7.

### 4. Fabric and diagnostics

- `make_weave_normal.py` — the tileable knit normal map. Rerun only if the fabric
  changes.
- `make_calibration.py` — millimetre-grid orientation textures. Rerun only if the
  pattern changes.

### 5. Runtime

`src/index.html` (and its Playground twin) loads the `.glb`, groups meshes by
glTF parent node, and assigns a `PBRMaterial` per panel with the print as albedo,
the knit map as a tiled normal, sheen enabled, and an IBL environment.

### 6. Production build

`build_production_glb.py` bakes all of §5's per-panel texturing into the model —
UVs, textures, samplers, materials, sheen, tangents — so the result renders
without any of this repo's JavaScript. `src/index-prod.html` (served at `/prod`)
is the test page and contains no material code at all. The environment and tone
mapping stay outside the file, because glTF has nowhere to put them.
Full reasoning and limits: [production-delivery.md](production-delivery.md).

## Running it

```bash
python3 tools/extract_pattern.py        # after a model change
python3 tools/pdf_to_svg.py             # after an artwork change
python3 tools/build_print_textures.py   # the usual one
python3 tools/make_logo_stencil.py      # after a sponsor logo changes
python3 tools/make_weave_normal.py      # rarely
python3 tools/make_calibration.py       # rarely

python3 tools/build_production_glb.py   # bake the shippable model

bun run dev                             # serve at :3000  ( / and /prod )
```

## Verifying

```bash
python3 tools/preview_render.py --textures print --view reference
python3 tools/preview_render.py --textures calib --view front
python3 tools/check_scene_sync.py
```

`preview_render.py` is a fast loop, **not** ground truth — it is a Lambert
rasteriser and cannot judge sheen, IBL or tone mapping, and it has been wrong
once in a way that cost real time. Confirm anything load-bearing in a browser.

`check_scene_sync.py` guards the invariant that `src/index.html` and
`src/playground.js` run the same scene. It compares code with comments stripped,
so their prose may differ but their behaviour may not. **Run it after touching
either file.**

The artwork PDF is an *input*, and one that arrives from outside. What it has
to satisfy to be usable — and how to check a delivery before accepting it — is
[reusable-pipeline.md](reusable-pipeline.md) §2, with a sendable brief in
[artwork-brief-pt.md](artwork-brief-pt.md).

## What lives where

| path | what |
|---|---|
| `src/` | the Babylon scene — page, Playground twin, dev server |
| `assets/` | everything fetched at runtime: model, textures, environment |
| `tools/` | the offline pipeline |
| `pipeline-design/` | the pipeline's design inputs and intermediates: supplier artwork PDF, converted artwork, pattern data, PSD exports, preview renders |
| `docs/` | this |

`assets/` deliberately sits at the repo root rather than under `src/`. It is
published content: `src/playground.js` fetches it over HTTP from
`raw.githubusercontent.com/.../main/assets/`, so the path is part of a public
URL and moving it would break saved Playground snippets.
