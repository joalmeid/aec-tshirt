# The ideal pipeline

[reusable-pipeline.md](reusable-pipeline.md) asks how to generalise *what exists*.
This asks a different question: **knowing what we now know, what would we build?**
It is a design study, not a description of code. Nothing here is implemented.

It is written under a hard constraint: this is a non-profit. **Every
recommendation has to be free or near-free**, both for us and for the designers,
who are likely to be volunteers. Where a paid tool is the industry norm, the free
route is named and its cost stated honestly.

---

## The short answer

Stop shipping a print PDF and reverse-engineering it.

**Generate a template pack from the garment model — one file per panel, real
outline, real millimetres — and take back the same files, filled in.**

Registration disappears. Not because it gets easier, but because artwork is
authored in the coordinate system the pipeline already consumes. The designer
draws *on the panel* instead of drawing a picture of a shirt that we then have to
work out how to lay onto panels.

Everything below is the argument for that, and what it costs.

---

## 1. What the PDF actually costs us

The source is a **technical flat**: the assembled garment seen head-on. The
pipeline needs **pattern pieces**: the flat panels as cut. Those are different
things that happen to look similar, and almost all the per-event work lives in
the gap between them.

What exists only because of that gap:

| work | why |
|---|---|
| artwork → pattern registration | the flat is not the pattern |
| the scale-agreement test | to find out whether the gap is even bridgeable |
| path-index archaeology | the PDF has no names, only 121 anonymous paths |
| extracting embedded rasters | logos arrive buried in the file |
| a 461-line PDF interpreter | no dependency-free way to read a content stream |
| the whole silent-failure class | live text, clipping masks, gradients — see [reusable-pipeline.md](reusable-pipeline.md) §2 |

That is the majority of what a new event costs today, and **all of it is
avoidable**. It is worth being clear that this was not a mistake: the PDF was the
only file that existed, and it was the right thing to build against. But it is
not what we would ask for next time.

What stays regardless of source format, because it comes from the mesh or the
fabric rather than from the artwork: seam derivation and stitching, the knit
normal map, the PBR setup, the whole runtime. Roughly half the tooling is already
source-agnostic.

---

## 2. Is there a better source format?

Yes: **SVG, one file per panel, in millimetres.**

| format | verdict |
|---|---|
| **SVG per panel** | ✅ **recommended.** Real units, named groups, XML, free tooling |
| **PNG per panel at stated px/mm** | ✅ **accepted fallback.** What the print-on-demand industry actually uses |
| print PDF (today) | ⚠️ workable, and what we have. Keep support; do not request it |
| `.ai`, `.psd` | ❌ proprietary, needs paid software to open reliably |
| USD / glTF | ❌ 3D interchange. The artwork is not 3D |
| ASTM/AAMA DXF | ❌ for *patterns*, not artwork — but see §6 |

### Why SVG beats PDF, specifically

Four properties, each of which removes a whole class of work:

1. **Real units are declared, not inferred.** `width="511.63mm"` plus a matching
   `viewBox` states the scale in the file. Today the scale is *deduced* by fitting
   a silhouette and hoping the axes agree. That entire test becomes unnecessary.
2. **Elements have names.** `id="stripes-front"`, `id="logo-chest"`. Today the
   per-event work is largely working out which of 121 path indices is which
   design element. Names make that free, and survive a re-export.
3. **It is XML.** It diffs in git, reviews in a pull request, and a revision is
   readable as a change rather than as a new opaque blob.
4. **It parses with the standard library.** `xml.etree` plus a path-data parser,
   against 461 lines of hand-written PDF content-stream interpreter. The silent
   failures in §2 of the other document are mostly *artefacts of that
   interpreter's limits*, and most of them stop existing.

### Why it is also the cheapest option

**Inkscape is free, open-source, and SVG is its native format** — no export step,
no fidelity loss, nothing to go wrong in conversion. Illustrator, Affinity and
Figma all export SVG competently too, so this constrains no one, but it means a
volunteer designer needs **zero paid software**. A brief that says "Illustrator:
*Type → Create Outlines*" quietly assumes a subscription; one that also says
"Inkscape: *Path → Object to Path*" does not.

Honest caveats: SVG export can rasterise effects that PDF would have kept as
vectors; text still needs converting to outlines; and some exporters embed
base64 PNGs into the SVG, which looks like vector until you open it. So the
acceptance checks in [reusable-pipeline.md](reusable-pipeline.md) §2 still apply —
they get cheaper, not obsolete.

### Do not throw the PDF away

The print supplier needs one. Ask for **both exports of the same artwork**, which
costs the designer one extra menu action. And this event's artwork exists *only*
as PDF, so `pdf_to_svg.py` stays as a supported path regardless.

---

## 3. Should there be several source files, one per component?

**Yes.** And this is not a novel idea — two mature industries already do exactly
this, arriving from opposite directions.

**Print-on-demand: cut-and-sew templates.** All-over-print suppliers give
designers a per-panel template — front, back, sleeves, hood, pockets — and take
back the filled-in panels with a bleed margin so print covers the edges after
cutting. This matters practically: **it is a deliverable a designer can be asked
for by name and can price**, because the whole POD industry already briefs this
way. It is not a bespoke demand.

**Film and VFX: UDIM.** Texture per region, tiles numbered 1001, 1002, 1003 —
adopted because one texture cannot hold a whole asset at usable resolution. **Our
panels are UDIM tiles.** The parallel is exact, down to the reason: the front
panel is baked at 3 px/mm and the back at 2, which is per-tile resolution
budgeting under another name.

### The obvious objection, and the answer

*A stripe running from the shoulder across the sleeve has to line up across two
files.* Real problem. Three answers, in order of how much they matter:

1. **Author whole, deliver per-panel.** This is precisely what Mari does — it
   presents UDIM tiles as one continuous canvas to paint across, then writes them
   out per tile. A designer can compose the whole garment and export per panel;
   the template pack just has to be laid out so that is natural.
2. **Bleed absorbs the mismatch.** Artwork crossing a seam is drawn past it on
   both sides. That is required anyway ([decisions.md](decisions.md) §3), and it
   is what the POD bleed convention is for.
3. **Perfect alignment is not achievable in the real garment either.** The fabric
   is cut, sewn and eased; POD guidance is explicit that prints shift near seams
   and that logos and text should be kept away from them. Chasing exactness
   across a seam in the 3D preview would be chasing something the physical shirt
   does not have.

So: per-panel files are not a compromise forced by the pipeline. They are what
the seam actually is.

---

## 4. A common format across garments

This is the strongest of the three questions, and the answer has a specific
shape:

> **A garment publishes a template pack. A layout is a filled-in template pack.**

Same format for a hoodie, a tank top, a tote bag. Only the *panel list* and the
*outlines* differ, and both are generated from the model rather than authored.

```
garments/
  unisex-tee/      template pack, generated from assets/tshirt.glb
  hoodie/          template pack, generated from assets/hoodie.glb
layouts/
  aec-2026/        one SVG per panel + manifest    -> unisex-tee
  aec-2027/                                        -> unisex-tee + hoodie
```

### The shared panel vocabulary

Names follow the **wearer**, as they already do here:

| panel | tee | hoodie | tank |
|---|---|---|---|
| `front` `back` | ✅ | ✅ | ✅ |
| `sleeve_l` `sleeve_r` | ✅ | ✅ | ❌ |
| `collar_*` | ✅ | — | binding |
| `hood_*` `pocket` `cuff_*` `waistband` | — | ✅ | — |

A layout declares the panels it requires. Applying it to a garment that lacks one
**fails loudly** rather than silently dropping a sponsor logo. That failure mode
is the entire value of having a vocabulary.

### The template pack, concretely

Per panel, generated by `extract_pattern.py`:

- the **outline** as an SVG path in millimetres — already computed, this is
  `seams.boundary_loops`
- a **bleed ring** outside it, and a **safe area** inside, so "keep text off the
  seam" is visible rather than a sentence in a brief
- **seam labels** — neck, shoulder, armhole, side, hem, cuff — which are already
  classified for stitching
- a locked reference layer, and the up direction

Plus one assembled preview of the whole garment, for judging the design as a
garment rather than as six rectangles.

**This is nearly free to build.** `panels.json` already carries exact millimetre
extents; `seams.py` already computes the outlines; the `<panel>-guide.png` and
`<panel>-mask.png` images already exist at 4 px/mm. Emitting an SVG template
instead of a PNG guide is a small addition to a tool that already runs.

That is the single highest-value thing on this page: it makes the artwork
contract **self-enforcing**. A designer working inside a template cannot deliver
the wrong scale, cannot omit bleed, and cannot get panel identity wrong — the
three failures that cost the most.

---

## 5. Cost

The binding constraint, so stated plainly rather than assumed.

**Already free, and should stay that way:**

- The pipeline is Python with numpy and Pillow only. `pdf_to_svg.py` was written
  dependency-free specifically to avoid needing poppler or cairo — that was a
  complexity decision, but it is a cost decision too, and moving to SVG makes it
  easier still.
- Rendering is offline on a laptop. No cloud, no per-render cost.
- Hosting is GitHub plus the Babylon Playground. Free, and the Playground needs
  no build step or server.

**Free tooling for the people involved:**

| need | free option | paid norm |
|---|---|---|
| draw the artwork | **Inkscape** (SVG-native), Figma free tier | Illustrator |
| raster panels | **GIMP**, **Krita** | Photoshop |
| 3D / inspect a model | **Blender** | — |
| patternmaking, if ever needed | **Valentina / Seamly2D**, which exports DXF-AAMA | CLO3D, Gerber, Lectra |
| texture compression | **`toktx`** (KTX-Software) | — |

**Where money would actually go.** Not software — **garment models**. That is the
real constraint on offering more than one garment, exactly as
[reusable-pipeline.md](reusable-pipeline.md) §1 says. Two things make this
cheaper:

- **The acceptance check is free and takes a minute.** Run `extract_pattern.py`
  and read the texel-density ratio *before* paying for anything. A model that
  fails is worthless here at any price, and this is the only way to know.
- **Ask a supplier for their model.** A garment manufacturer producing these
  shirts may already have the CAD, and for a charity that is a plausible in-kind
  donation — the same ask as the food and the sponsorship. It costs an email.

**One practical consequence for the existing brief:** it currently gives
Illustrator menu paths only, which assumes a subscription a volunteer may not
have. Inkscape equivalents should be added. Cheap fix, removes a real barrier.

---

## 6. What the industry does

Grounding, so the above is not invention. Each row is something to take or
deliberately not take:

| practice | who | what we take |
|---|---|---|
| **cut-and-sew AOP templates** | print-on-demand | the template-pack model, and bleed conventions |
| **UDIM tiles** | film / VFX | per-panel textures, per-tile resolution budgeting |
| **tech pack** | apparel | the vocabulary designers already expect: flats, measurements, colourways, placements |
| **ASTM D6673 / AAMA DXF-292** | apparel CAD | the real pattern interchange standard, preserving grading and notches. Not needed while patterns come from the 3D model — relevant the day a manufacturer sends real pieces |
| **Khronos 3D Commerce Asset Creation Guidelines 2.0** | 3D retail | how to author glTF that renders consistently across viewers |
| **`KHR_materials_variants`** | 3D retail | colourways sharing one geometry in one file, switching at runtime — the right mechanism for a store |
| **300 dpi at final size, 2–5 mm bleed** | print | already in the brief |

Worth noting what does **not** exist: there is no standard for "artwork
authored in pattern space". POD templates are the closest thing, and they are
per-vendor. So a template pack is a house format by necessity — which is an
argument for keeping it boring and self-describing (SVG, millimetres, named
groups), not for avoiding it.

---

## 7. What I would build, in order

1. **The template pack generator.** Small, mostly-existing code, and it makes the
   artwork contract self-enforcing. Highest value per hour on this page.
2. **Accept per-panel SVG**, alongside the PDF path rather than replacing it.
   Prove it on a real delivery before committing.
3. **The layout manifest** ([reusable-pipeline.md](reusable-pipeline.md) §3), with
   this event as the first entry, so the format is tested against a real design.
4. **A second garment**, and find out what actually breaks. The panel vocabulary
   above will be wrong in ways this document cannot predict.

Steps 1 and 2 pay off at the *next event*. Steps 3 and 4 only pay off at the
second *garment*. Sequence accordingly, and do not build the hoodie abstraction
before there is a hoodie.

---

## 8. What gets worse

An honest accounting, because none of this is free of cost:

- **Per-panel is more abstract for a designer.** Composing on a whole-garment
  mockup is how people naturally work. If the template pack does not carry a good
  assembled preview, the *design* gets worse even as the pipeline gets easier.
  This is the main risk.
- **Two deliverables to keep in sync** — panel SVGs for us, print PDF for the
  supplier. Generating the print PDF *from* the panels would fix this and is
  more work than it sounds.
- **More files.** Six per layout for a tee, ten or more for a hoodie, against one
  PDF today.
- **A design that ignores panel structure gets harder, not easier.** One large
  photographic image across the whole front is *simpler* to place from a technical
  flat than from per-panel files.
- **It is a house format.** Nobody else's tools read it, and it needs documenting
  and maintaining — the cost the template generator has to earn back.

None of these outweigh removing the registration step, but the first one is close
enough to be worth designing against rather than dismissing.

---

## Sources

- [Printful — how to make custom all-over print shirts](https://www.printful.com/blog/how-to-make-custom-all-over-print-shirts)
- [Printify — how to make all-over print shirts](https://printify.com/blog/how-to-make-custom-all-over-print-shirts/)
- [Yoycol — all-over print clothing guide](https://www.yoycol.com/blog/all-over-print/)
- [Foundry — UDIM workflow](https://learn.foundry.com/modo/content/help/pages/uving/udim_workflow.html)
- [Adobe — painting across UV tiles (UDIMs) in Substance Painter](https://www.adobe.com/products/substance3d/magazine/paint-across-uv-tiles-udims-in-substance-painter.html)
- [Optitex — data exchange (DXF AAMA/ASTM)](https://help.optitex.com/1382687/Content/FAQ/Data_Exchange_Questions.htm)
- [File Wizards — apparel CAD pattern file formats](https://www.file-wizards.com/apparel-cad-pattern-file-formats-explained.html)
- [Khronos — Asset Creation Guidelines 2.0 for commerce-ready glTF](https://www.khronos.org/blog/introducing-asset-creation-guidelines-2.0-siggraph-2025)
- [Khronos — material variants in glTF](https://www.khronos.org/blog/streamlining-3d-commerce-with-material-variant-support-in-gltf-assets)
- [`KHR_materials_variants` specification](https://github.com/KhronosGroup/glTF/blob/main/extensions/2.0/Khronos/KHR_materials_variants/README.md)
