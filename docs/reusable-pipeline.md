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

## 2. The contract the print artwork must satisfy

The artwork arrives from an external designer, so this has to be specified *up
front*, in the brief — not discovered after delivery. Re-requesting a corrected
file costs a round trip through someone who does not know or care what a UV
island is, and some of these failures are silent: the file opens fine in
Illustrator and looks perfect on screen.

There is a ready-to-send version of this in **[artwork-brief-pt.md](artwork-brief-pt.md)**,
in Portuguese, matching how the rest of this event's supplier communication is
done. This section is the reasoning behind it.

### Why a vector PDF specifically

Not a preference. `tools/pdf_to_svg.py` reads the PDF's **content stream** and
recovers each drawing operation as real geometry — bezier paths with their fill
colours and bounding boxes. That is what makes the artwork *measurable*: the
stripe angle of 10.44°, the 3.70 mm pitch and the exact palette were read out of
the file, not eyeballed off a picture. A raster PDF, a PNG, or a PDF that is just
a wrapper around a flattened image gives none of that.

The tool is deliberately dependency-free and implements only the PDF operator
subset this artwork uses. The requirements below are, almost one for one, that
subset — which is why they are worth stating precisely rather than as "send
vectors please".

### Hard requirements — the pipeline cannot proceed without these

**1. Real vector paths.** Path construction (`m l c v y h re`) and painting
(`f f* S B ...`) are what the parser understands. A flattened or
image-only PDF yields zero paths.
*Check:* `official-artwork.json` should hold on the order of a hundred paths.
This artwork has 121.

**2. All text converted to outlines.** No text operators are implemented at all —
`BT`/`Tj`/`TJ` are not in the interpreter. **Live text is invisible to the
extractor**: it will not appear in the SVG, the JSON or the render, and nothing
will report an error. This is the single most likely silent failure. It is also
ordinary print practice, so designers will not find it a strange thing to ask.

**3. Flat colour fills only — no gradients, no transparency, no blend modes.**
Supported colour operators are `rg RG g G k K sc scn SC SCN`, all of which set
one flat colour. Gradients are drawn with shading (`sh`) or pattern colour
spaces, which are not handled, so a gradient-filled shape comes out either the
wrong colour or the previous one. Flat colour is what screen printing and DTG
actually produce anyway.

**4. No clipping masks.** `W`/`W*` are parsed and then deliberately ignored —
clipping is not applied. Anything the designer hid behind a clipping mask
**reappears** in the extraction. This is the failure that looks like file
corruption: stray shapes, artwork bleeding across the page. Ask for masks to be
expanded or deleted before delivery.

**5. Dashed strokes expanded to filled paths.** The dash-pattern operator (`d`)
is not implemented, so a dashed stroke extracts as a solid line. Line caps and
joins are not modelled either. Solid strokes of constant width are read correctly
(with `w`), so this only matters for dashed or decorative strokes — but
"expand all strokes" is a simpler instruction to give than the exception.

**6. Drawn as a technical flat, at flat-pattern proportions.** The garment seen
head-on, laid flat, in real-world millimetres — **not** a mockup warped onto a
body, not a photograph, not a 3/4 view. This is the property that made
registration here a scale and a translate, and it is the requirement most likely
to be misunderstood, because a designer's instinct is to deliver something that
*looks* like the finished shirt. (That instinct produced this event's PSD, which
is why the PSD is unusable — see [decisions.md](decisions.md) §2.)

**7. Full bleed at every panel edge.** Artwork that runs to a seam must be drawn
*past* it, by a couple of centimetres. Do not trim or clip artwork to the garment
silhouette. The mesh's UV island does the clipping at geometry precision, so a
pre-trimmed file can only be worse — see [decisions.md](decisions.md) §3. Note
this compounds with (4): trimming *by clipping mask* both violates this and
reappears anyway.

**8. Raster elements only where unavoidable, and then at high resolution.** Logos
supplied by third parties are often raster and that is accepted. They must be
8-bit gray, RGB or CMYK — more exotic encodings are skipped rather than guessed
at. Ask for **≥300 dpi at final printed size** (≈12 px/mm), which is 4× the
densest texture baked here (3 px/mm on the front). This event's SCARPA lockup
arrived at 8214 × 984 for a 105 mm placement, which is far more than needed and
exactly the right problem to have.

### Requirements that make registration cheap rather than possible

These are not blocking, but each one removes guesswork:

- **State the size the flat is drawn to**, and one real dimension to check it
  against — half-chest laid flat is the natural one. This model is a size L: the
  front pattern piece is 511.63 mm across, so a flat drawn to it should measure
  about that from side seam to side seam. Without a stated scale, the
  artwork→pattern fit is inferred from the silhouette and cannot be verified.
- **One page, both flats**, front and back side by side, plus any sleeve or
  pocket art laid out separately and labelled.
- **Group and name each design element** — stripes, wordmark, sponsor lockups.
  The extraction reports paths by index, and the per-event work is saying which
  index ranges are which element. Named groups turn that from archaeology into
  reading.
- **Give the palette as values**, hex or CMYK, in the delivery note. The pipeline
  can sample it, but a stated palette is checkable and survives a re-export.
- **Keep the original editable file** (`.ai`, `.svg`) available. Not needed by
  the pipeline, but it is what a correction is made from.

### Accepting a delivery

Run the extractor before telling the designer the file is good:

```
python3 tools/pdf_to_svg.py
```

Then check, in order — each maps to a requirement above:

| check | reading | fails |
|---|---|---|
| path count in `official-artwork.json` | ~100+ | (1) not vector |
| page size, reported in mm | plausible garment size | scale unstated |
| open `official-artwork.png` | all lettering present | (2) live text |
| …and compare to the designer's own preview | nothing extra, nothing missing | (4) clipping masks |
| distinct fill colours | a handful of flat values | (3) gradients |
| `pdf-images/` | only the logos you expect | art rasterised |
| artwork extends past the silhouette | yes | (7) trimmed to shape |

The last check is the scale-agreement test, and it is the one worth doing before
committing to a layout: fit the torso silhouette's bounding box to the front
panel and compare the x and y scale factors. They agreed to 2.6% on the front and
0.35% on the back here, which is what confirmed the flat was drawn at pattern
proportions. **If they disagree badly, that is the real work of the event** — the
artwork is projected rather than flat, and needs redrawing or warping before any
of this applies.

---

## 3. A layout manifest — *proposed*

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
artwork: pipeline-design/artwork/official-artwork.svg

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

## 4. A panel-name contract

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

## 5. What the runtime needs

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

## 6. Adding a new event today

Without any of the above built, the honest current procedure:

1. Get the print artwork as **vector PDF**, briefed and accepted against §2.
   Run `pdf_to_svg.py` and read the path report to find which indices are which
   design element.
2. Run the scale-agreement test from §2. It made registration a scale and a
   translate here; if it fails, that is the real work of the event.
3. Edit the design spec in `build_print_textures.py`.
4. Rebuild, render, compare against the reference, confirm in a browser.

Steps 1, 2 and 4 generalise. Step 3 is what the manifest is for.

---

## 7. Suggested order of work

1. **Extract `PANEL_GROUPS` into a model file.** Smallest change, removes the
   most duplication, and is a precondition for everything else.
2. **Move the design spec into a layout manifest**, with the current event as the
   first one — proving the format against a real design rather than a guess.
3. **Emit the runtime `PANELS` table from `panels.json`** instead of pasting it,
   closing the last hand-copied step.
4. **Add a second garment** and find out what actually breaks. Do not design for
   the tank top before you have one; the panel-name contract will be wrong in
   ways this document cannot predict.
