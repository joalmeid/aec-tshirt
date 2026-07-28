# Building a reusable pipeline

This repo renders one shirt for one event. The goal is many: a new layout each
year, and eventually a store with several garments — a female tee, a tank top —
each available in several designs.

This is a **design guide**, not a description of code that exists. Where it
proposes a format, it says so.

---

## The property everything rests on

**A flat-pattern UV set turns a layout into data.**

Because the model's UVs are the real sewing pattern measured in millimetres,
"where does this logo go" has an answer that is independent of the renderer, the
texture resolution and the camera: *145 mm from the left edge of the front panel,
215 mm down.* A layout is nothing more than a set of per-panel millimetre
drawings.

That is why most of this pipeline is already generic. Only one stage —
`build_print_textures.py`'s design spec — knows anything about *this* event.

| stage | generic? |
|---|---|
| `extract_pattern.py` | ✅ any garment with flat-pattern UVs |
| `pdf_to_svg.py` | ✅ any vector artwork |
| `seams.py` + seam classification | ✅ derived from the mesh, no per-garment tuning |
| `make_weave_normal.py` | ✅ fabric, not garment |
| `preview_render.py`, `make_calibration.py` | ✅ |
| the Babylon runtime | ✅ apart from its hardcoded `PANELS` table |
| **the design spec in `build_print_textures.py`** | ❌ **per layout** |
| **artwork → pattern registration** | ❌ **per garment × artwork** |

Two things to build, then: a **layout format** and a **model registry**.

---

## 1. The contract a garment model must satisfy

Not every model can enter this pipeline. Before buying or commissioning one,
check:

1. **Flat-pattern UVs.** Run `extract_pattern.py` and read the texel-density
   ratio. Under ~1.05 means a real sewing-pattern unwrap. A projected or
   auto-unwrapped model will show much higher numbers, and the whole
   millimetre-space approach collapses — a point in the texture no longer
   corresponds to a fixed point on the fabric.
2. **One UV island per panel**, with pieces separated. Marvelous Designer and
   CLO3D exports satisfy this naturally; game-art assets usually do not.
3. **Named nodes**, so panels can be identified reliably. Do *not* rely on vertex
   counts or world position — both have silently picked the wrong mesh here.
4. **UV units.** This model happens to use millimetres with metre positions. A
   different exporter may use centimetres or normalised UVs; `extract_pattern.py`
   reports the density constant, which reveals the scale (≈1000 here = mm per
   metre).

Worth stating plainly: **sourcing models is the hard constraint on a store**, not
the rendering. A model that fails (1) needs re-unwrapping before it is usable.

---

## 2. A layout manifest — *proposed*

Lift the design spec out of Python into data. Today it is module constants in
`build_print_textures.py`: `ART_FRONT_TORSO`, `BODY_STRIPES_FRONT`,
`SCARPA_ABOVE_CUFF_MM`, the stripe palette, and so on. Adding a second event
currently means editing that file, which does not scale and cannot be done by a
designer.

A manifest turns "edit the builder" into "add a layout":

```yaml
# layouts/aec-2026.yaml   (proposed)
name: Alimenta Esta Corrida 2026
garment: unisex-tee            # -> models/unisex-tee.yaml
artwork: design/artwork/official-artwork.svg

palette:
  stripe_light: "#c0d174"
  stripe_mid:   "#98a64f"
  stripe_dark:  "#6e7a33"
  ink:          "#222221"

panels:
  front:
    px_per_mm: 3
    fit: {from: artwork_bbox, path: 0}   # artwork torso silhouette -> panel
    elements:
      - {type: paths, ids: [1-6, 27-32, 46-48], bleed: 260mm}
      - {type: paths, ids: [88-96]}
      - {type: paths, ids: [97-120]}
      - {type: stencil, image: mark.png, at: {artwork_box: [71.25, 65.61, 76.56, 69.98]}}
  sleeve_l:
    px_per_mm: 3
    unprinted_hem: 20mm
    elements:
      - type: stencil
        image: scarpa.png
        across: 0.5            # outer face of the tube
        above_hem: 50mm
        size: [105mm, 12.6mm]
```

Design notes that matter more than the syntax:

- **Every placement is a real measurement.** `50mm above the hem`, not `y: 0.75`.
  Fractions are treacherous on a sleeve, where pattern `v` is not linear with how
  far down the sleeve something *looks* — see [decisions.md](decisions.md) §7.
- **Keep the two placement idioms that already exist**: fit-a-bbox for artwork
  that was drawn at pattern proportions, and place-by-measurement for everything
  else.
- **Stitching should not be in the manifest.** It is derived from the mesh and is
  a property of the garment, not the layout.

---

## 3. A panel-name contract

Layouts should be portable across garments where the design allows. That needs
shared panel names mapping to per-garment nodes:

```yaml
# models/unisex-tee.yaml   (proposed)
glb: assets/tshirt.glb
panels:
  front:    Body_Front_Node_4
  back:     Body_Back_Node_5
  sleeve_r: Sleeves_Node_7      # wearer's right
  sleeve_l: Sleeves_Node_6      # wearer's left
  collar_a: Ribbing_Node_2
  collar_b: Ribbing_Node_3
```

Names follow the **wearer**, as they already do here.

Be honest about the limits: **a tank top has no sleeves.** A layout that puts a
sponsor badge on a sleeve cannot be applied to one unchanged. Options, in
increasing effort: declare required panels per layout and refuse mismatches;
allow per-garment overrides; or accept that some layouts are garment-specific.
The first is enough to start and fails loudly rather than silently.

Note `extract_pattern.py`'s `PANEL_GROUPS` is already this table, hardcoded —
extracting it is the actual first step.

---

## 4. What the runtime needs

The scene's `PANELS` table already carries exactly one garment's node names and
transforms, generated from `panels.json`. That table **is** the seam along which
a model registry gets introduced: emit it per model instead of hand-pasting one,
and have the page pick a model + layout.

For a store, also consider:

- **Texture memory per variant.** Roughly 33 MB with mipmaps today (front at
  3 px/mm, back at 2). Several variants live at once needs KTX2/Basis
  compression, which was deferred and is the obvious next lever.
- **Shared assets.** The knit normal map and the environment are garment- and
  layout-independent — load them once across variants.
- **The `.glb` dominates download** at 6.8 MB. Draco or Meshopt compression
  matters more than texture size if several garments are offered.

---

## 5. Adding a new event today

Without any of the above built, the honest current procedure:

1. Get the print artwork as **vector PDF**. Run `pdf_to_svg.py` and read the path
   report to find which indices are which design element.
2. Check whether the technical flat is drawn at flat-pattern proportions — fit
   the torso silhouette bbox to the panel and see whether the x and y scales
   agree. They did here to within 3%, which made registration a scale and a
   translate. **If they disagree badly, that is the real work**, and the
   place to spend effort.
3. Edit the design spec in `build_print_textures.py`.
4. Rebuild, render, compare against the reference, confirm in a browser.

Steps 1, 2 and 4 generalise. Step 3 is what the manifest is for.

---

## 6. Suggested order of work

1. **Extract `PANEL_GROUPS` into a model file.** Smallest change, removes the
   most duplication, and is a precondition for everything else.
2. **Move the design spec into a layout manifest**, with the current event as the
   first one — proving the format against a real design rather than a guess.
3. **Emit the runtime `PANELS` table from `panels.json`** instead of pasting it,
   closing the last hand-copied step.
4. **Add a second garment** and find out what actually breaks. Do not design for
   the tank top before you have one; the panel-name contract will be wrong in
   ways this document cannot predict.
