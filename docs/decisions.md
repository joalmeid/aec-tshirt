# Decisions

Why the pipeline is built the way it is. Several of these were got wrong first,
and those are recorded with the mistake intact — the wrong answer is usually more
useful than the right one, because it is what someone will reach for again.

---

## 1. Texture through the pattern UVs, not with decals

**The model's UVs are the garment's real 2D sewing pattern, measured in
millimetres.** `assets/tshirt.glb` came out of Marvelous Designer / CLO3D, which
exports UVs as the flat pattern pieces. Positions are in metres, so
`sqrt(uvArea / 3dArea)` comes out at a constant ≈1000 — that constant *is* the
mm-per-metre conversion, and its constancy is the proof.

| panel | pattern piece | texel density p95/p5 |
|---|---|---|
| front | 511.63 × 703.22 mm | 1.023 |
| back | 511.54 × 729.04 mm | 1.017 |
| sleeve (each) | 397.13 × 204.03 mm | 1.033 / 1.038 |
| collar ribbing | 187.30 × 17.00, 272.32 × 17.00 mm | 1.098 |

Under 4% stretch anywhere. Chest = 2 × 511.6 mm ≈ 102 cm, a size L.

So a point at (120 mm, 215 mm) in the front texture lands on exactly that spot of
the physical panel, and **the UV island boundary is the neckline, armhole,
shoulder and hem**.

The scene previously used `MeshBuilder.CreateDecal`, which is planar box
projection. On a curved, seamed garment that cannot be made exact: it smears
where the surface turns away from the projection axis, it cannot stop at a seam,
and it needs per-panel fudge factors that never converge. The history shows the
sleeves being swapped three separate times chasing it.

Babylon's own asset docs make the analogy without knowing it applies literally
here: *"the UVs for a mesh are very similar to a sewing pattern for making an
article of clothing."*

## 2. Artwork comes from the print-ready PDF, not the PSD

`t-shirt-AEC26-final.psd` looks like the obvious source and is a trap. It is a
**2D mockup**, not a 3D model:

- `Parts Merged.png` is a flat colour-ID mask drawn in one fixed 3/4 camera view.
- `Shirt Front Part FV11.png` is the artwork already perspective-warped for that
  camera.
- `Diffuse` / `Highlights` / `Shadow` / `Stitches Shirt` are view-space
  compositing layers.

None of it carries UV information, and no amount of re-exporting at higher
resolution changes that.

The PSD is **not in this repo** and is git-ignored. It is 91.5 MB, nothing in the
pipeline reads it, and it was carried in the history until it was stripped out —
see §13. Keep it alongside the repo if you need it; its per-layer PNG exports in
`design/all-psd-exports/` are what the investigation actually used.

`design/T-shirt Alimenta esta corrida oficial 2026.pdf` is the file the garment
supplier works from: a single 750 × 1230.17 pt page — 264.6 ×
434.0 mm — holding front and back technical flats as **121 real vector paths**.
From it, measured rather than guessed:

- palette `#c0d174` · `#98a64f` · `#6e7a33` · `#222221`
- stripes at **10.44°** from vertical, **3.70 mm** pitch, **2.19 mm** wide
- both logos as high-resolution stencils (SCARPA at 8214 × 984)

**The key unlock:** that technical flat is drawn at *flat-pattern* proportions,
not projected ones. A t-shirt laid flat measures half its chest circumference
across, which is exactly what the front pattern piece measures. So artwork →
pattern is only a scale and a translate, and the two axes agree independently:
6.534 vs 6.370 on the front, 6.533 vs 6.556 on the back.

## 3. Artwork is drawn full-bleed; the mesh does the clipping

Nothing is clipped to the panel outline in the texture. Artwork runs past the
panel edge on purpose, and the **UV island clips it**. Two consequences:

- the print terminates on the seam at *geometry* precision, not texture precision
- there is no island border for mip-mapping to bleed against

Clipping in the texture would be strictly worse on both counts.

## 4. `uScale` is POSITIVE — and the story of why it briefly wasn't

This is the most expensive mistake in the project's history and the one most
likely to recur.

Texture space is **the panel seen from OUTSIDE, left to right** — the same
convention the technical flat uses, which is why artwork x maps straight through.
That is also raw pattern-`u` order, so the whole mapping is
`texture_x_mm = pattern_u_mm` and every `uScale` is positive. Checked per panel
against the model rather than assumed — does `u` increase toward the right when
that panel is viewed from outside?

| panel | correlation | viewed from | u increases toward |
|---|---|---|---|
| front | `corr(u,X) = +0.99` | +Z | viewer's right ✓ |
| back | `corr(u,X) = −0.99` | −Z | viewer's right ✓ |
| `Sleeves_Node_6` | `corr(u,Z) = −0.77` | +X | viewer's right ✓ |
| `Sleeves_Node_7` | `corr(u,Z) = +0.77` | −X | viewer's right ✓ |

All four agree, so there is no per-panel special case.

**An earlier version had these negated.** The cause was `tools/preview_render.py`
building its camera basis as `cross(up, forward)`. Babylon is left-handed, so
screen-right is `cross(forward, up)` — with a camera on +Z looking back at the
origin that is `(+1,0,0)`, meaning **world +X is the viewer's RIGHT**. The tool
had it as the viewer's left, so every render it produced was mirrored. The
calibration pass was read *through* that mirror, concluded the front panel needed
flipping, and a negative `uScale` was hand-written into the scene to correct a
mirror that never existed. The same sign error is why the backface-cull test had
to be flipped to see the front panel at all — one root cause, two symptoms.

`design/pattern/panels.json` had the correct positive values the whole time.

**If the print ever looks mirrored again, suspect the preview tool before these
numbers.**

## 5. `invertY: false` on every texture

glTF puts the UV origin at the image's **top-left**, and Babylon's own glTF
loader creates its textures with `invertY: false` to match. But the `Texture`
constructor defaults to `true`, which flips the upload and renders every print
upside down on UVs that came out of a `.glb`.

```js
new BABYLON.Texture(url, scene, false, false)  // 3rd noMipmap, 4th invertY
```

Read out of the shipped Babylon source, not assumed.

## 6. Sleeve node mapping

Swapped four times before it was written down. With +X on the viewer's right:

| node | world | renders | is the wearer's | carries |
|---|---|---|---|---|
| `Sleeves_Node_6` | x > 0 | viewer's RIGHT | **LEFT** | SCARPA badge |
| `Sleeves_Node_7` | x < 0 | viewer's LEFT | **RIGHT** | stripes |

Panel names follow the **wearer**, matching the PSD's layer names and how the
design is described. `tools/extract_pattern.py`'s `PANEL_GROUPS` is the single
point of truth; `panels.json` and the scene's transforms both follow from it.

Do not identify panels by vertex count or world-X sign. Both have silently picked
the wrong mesh — the back panel has *more* vertices than the front. Use the glTF
parent node name.

## 7. Stitching is derived from the mesh

The PSD's stitch layer is unusable for the reason in §2 — 3000 × 3000 with 0.1%
coverage, warped onto one camera.

It is not needed, because **a UV island's boundary IS a seam** — exactly, since
the UVs are the sewing pattern, so the island edge is the line the panel was cut
and sewn along. A boundary edge is simply an edge used by exactly one triangle,
so the seams fall out of the mesh with no image processing:

```
front  504 boundary edges -> 1 closed loop, 2480 mm
back   492 boundary edges -> 1 closed loop, 2419 mm
```

Style measured off the PSD rather than invented: `#515253`, dashed, 0.8 mm wide,
3 mm dash / 1.5 mm gap — ordinary topstitch spacing, so it transfers.

### Seams are classified by what they are sewn to

What a stretch of boundary *is* gets decided by 3D proximity to the piece it
joins — no coordinate thresholds, and it survives a change of pattern.

| test | seam | inset | rows |
|---|---|---|---|
| within 12 mm of collar ribbing | `neck` | 2.5 mm | 1 |
| within 8 mm of a sleeve | `armhole` | 6 mm | 1 |
| within 8 mm of the other body panel, above the armhole | `shoulder` | 6 mm | 1 |
| within 8 mm of the other body panel, below the armhole | `side` | 6 mm | 1 |
| free edge | `hem` | 20 mm | **2**, +5 mm |
| sleeve free bottom edge | `cuff` | 20 mm | 1 |
| sleeve, else | `underarm` | — | none |

Only the hem is double-needle, measured off the PSD: a vertical slice through the
centre front crosses two lines 9 px apart, ≈5 mm centre to centre. The same test
crosses exactly **one** line at the neckline — the second line visible in the
reference is the collar band's own edge, which is geometry, not stitching.

Three things this design exists to avoid, each of which happened:

1. **Each seam is owned by one panel.** A seam joins two pieces and both their
   boundaries run along it, so stitching both drew the armhole twice and the
   neckline three times. Body panels own the neckline, shoulders, armholes, sides
   and their own hem; sleeves own only their cuff; collar bands own nothing.
2. **Inset is per seam, not per height.** An earlier version gave the deep hem
   inset to any point low on the panel, including points on the *side seams* —
   whose inward direction is horizontal, so those lines swung ~14 mm sideways and
   read as a spurious rising diagonal.
3. **Each run is offset and dashed independently**, with one-sided normals at its
   ends, and stops short of its corners (5 mm, 16 mm on the cuff). Offsetting a
   whole loop makes the stitch turn every corner, where an angle-bisector offset
   overshoots or self-intersects. Two of those meeting at a sleeve's underarm drew
   a cross under each cuff.

`offset_inward` also rejects any contour the offset turns inside out. The sleeve
mesh's boundary contains 22 mm-wide underarm slivers, and offsetting those by the
20 mm hem inset collapsed them through themselves — the inverted polygon
rasterised as a line straight across the sleeve, through the SCARPA badge.

## 8. PBR, and the tone-mapping reversal

**Sheen is the reason for the move.** It is Babylon's fabric-specific lobe — the
soft retroreflective bloom cloth shows at grazing angles — and no combination of
diffuse and specular reproduces it. It also needs an environment to reflect,
which is why the old light rig had to go rather than be retuned.

What was removed: a three-light Blinn-Phong rig (hemisphere fill, two mirrored
directional keys, a green rim) that faked what IBL does properly. Its
`keyLightBack` additionally needed every sleeve mesh *excluded* from it, because
two directional lights summing on a curved surface clipped to a hard white
streak. That is a Blinn-Phong artifact with no PBR equivalent, so the workaround
went with the light that caused it.

Current values: `metallic 0`, `roughness 0.82`, `sheen.intensity 0.4`,
`sheen.roughness 0.3`, `sheen.albedoScaling true`, `bumpTexture.level 0.45`,
`environmentIntensity 1.0`, `exposure 1.15`.

**Tone mapping is ON, reversing an earlier decision** that is worth stating
because it was correct at the time: under `StandardMaterial` with no environment
the scene was effectively LDR, so a tone curve had no over-range headroom to
recover and merely darkened the mid-range. With an HDR environment driving a PBR
material there are genuine over-1.0 values to compress, and without a curve the
white fabric clips.

`TONEMAPPING_KHR_PBR_NEUTRAL` rather than ACES, deliberately: it leaves in-gamut
colour alone and compresses only highlights, so the brand greens stay on-brand.
ACES is filmic and shifts them.

**No tangents.** The `.glb` carries `POSITION`, `NORMAL`, `TEXCOORD_0` only, so
Babylon derives the tangent frame per-pixel from screen-space derivatives.
Normally a compromise, but a good one here: the unwrap is a true flat pattern
with under 4% stretch, so the derived frame is close to a real one. If the weave
ever looks smeared or swims while orbiting, that is the suspect.

## 9. The knit map tiles in real millimetres

`uScale = 1/TILE_MM` makes the weave repeat every **15 mm of actual garment**,
identically on every panel, with no repeat count to guess at. That only works
because the UVs are in millimetres — it is the same property that makes §1 work,
reused.

256 × 256 rather than 512: a loop is 0.83 mm on a panel half a metre across, so
it is sub-pixel at any realistic camera distance, and normal maps compress badly
enough that 512 cost 475 KB against 133 KB for no visible gain.

A first attempt swayed a sine sideways once per course. That *drifts* rather than
oscillating symmetrically and read as diagonal twill, not knit. It is now built
from the shape directly: two legs per loop cell converging toward the bottom,
plus the loop head.

## 10. Fill rule: contours are XOR-composited

Glyphs with counters — both **A**s, **O**, both **R**s, **D**, and **0**/**6** of
2026 — came out solid. The rasteriser was filling each of a path's contours
independently, so a letter's inner contour painted over its own hole.

Contours of one path are now XOR-composited into a mask: a pixel is inside when
an odd number of contours covers it. That is the even-odd rule, which is what the
PDF asks for on its `f*` paths, and it matches `f` (nonzero) for everything here
because font outlines wind inner contours opposite to outer ones. The two rules
differ only on self-overlapping paths, and this artwork has none.

The bug hid because there were **two copies** of the flawed loop. There is now
one implementation, `vectorart.fill_contours`.

## 11. The preview renderer is not ground truth

`tools/preview_render.py` is a fast loop, not a verdict. It is a Lambert
rasteriser: it can verify UV mapping, orientation, stitch placement and panel
coverage, but it **cannot judge sheen, IBL or tone mapping**.

It has been wrong once, expensively — see §4. Confirm anything load-bearing in a
browser.

## 12. The two scene files must not drift

`src/index.html` and `src/playground.js` are the same scene twice. A fix applied
to one and not the other produces a bug that only shows up in the copy nobody is
looking at — which happened, when the playground was left on decal projection for
a whole commit.

They used to be compared byte for byte. Since the playground was slimmed for
pasting, `tools/check_scene_sync.py` compares **code only**, with comments
stripped. Run it after touching either file.

## 13. The PSD was stripped from the history

The 91.5 MB layered PSD (`t-shirt-AEC26-final.psd`) was committed early, before
it was understood that it is a 2D mockup and not a usable source — see §2. It
then travelled through two renames (`source/` → `design/`, plus a stint in
`assets/`) and GitHub warned on every push that carried it.

It was removed from all refs with `git-filter-repo`, stripping all three of its
historical paths, and force-pushed. The commit that only added it was pruned as
empty; nothing else changed, verified by diffing the rewritten tree against a
bundle of the pre-rewrite history. Clone size went from ~120 MB to ~31 MB.

`*.psd` is git-ignored so it cannot return. Keep the file next to the repo if you
want it; the per-layer PNG exports in `design/all-psd-exports/` are what the
investigation actually read, and they are still tracked.

**GitHub still has the old objects.** A force-push makes commits unreachable, not
deleted: `refs/pull/1/head` is immutable and pins the pre-rewrite tip, and old
commit SHAs still resolve — the blob is downloadable by anyone who knows the old
SHA. Only GitHub Support can garbage-collect them. That is fine here, since the
file is a t-shirt mockup and the repo is public anyway. It would **not** be fine
for a leaked secret, which must be rotated rather than rewritten away.
