# Production delivery

[pipeline.md](pipeline.md) ends at `src/index.html`: a page that loads a bare
geometry `.glb` and builds every material in JavaScript. That is the right shape
for developing the design — the panel table is readable, a value can be changed
and reloaded, and the Playground twin makes it shareable.

It is the wrong shape for shipping. This document is what changes, why, and what
the limits are. Unlike [reusable-pipeline.md](reusable-pipeline.md) and
[ideal-reusable-pipeline.md](ideal-reusable-pipeline.md), which are design
studies, **this one is implemented**: `tools/build_production_glb.py` and
`src/index-prod.html`.

---

## 1. What the development runtime leaves undone

`assets/tshirt.glb` is geometry only — no images, no textures, six panels' worth
of UVs in raw pattern millimetres, and two placeholder materials from the
original Sketchfab conversion. Everything visual lives in the page:

- a `PANELS` table of per-panel `uScale/uOffset/vScale/vOffset`
- six texture loads with `invertY: false` and `CLAMP_ADDRESSMODE`
- the knit normal at `uScale = 1/15`, `WRAP`, `gammaSpace = false`
- `metallic`, `roughness`, and the four `sheen.*` values

About 130 lines. Anything that loads the model *without* running that file gets
an untextured shirt: a partner's site, a `<model-viewer>` embed, the Khronos
sandbox, Blender, a supplier checking the artwork. The knowledge is in the repo,
not in the asset.

---

## 2. The rule

> **Bake everything glTF can hold. Configure the rest, and say so out loud.**

The split is not negotiable and it is not about effort. glTF describes an
*object*: geometry, UVs, materials, textures. It deliberately does not describe
the *room* the object is in. So:

| | where it goes |
|---|---|
| UV mapping, textures, PBR values, sheen, tangents | **in the file** |
| environment / IBL, tone mapping, exposure, camera | **alongside the file**, set by every viewer |

Any promise of "drop this on a website and it just works" that does not
acknowledge the second row is wrong. A shirt rendered with no environment does
not merely look flatter — the sheen lobe is a reflection of the surroundings, so
with nothing to reflect the fabric stops reading as fabric.

---

## 3. The bake — `tools/build_production_glb.py`

```bash
python3 tools/build_production_glb.py                    # -> assets/tshirt-prod.glb
python3 tools/build_production_glb.py --textures calib   # -> assets/tshirt-prod-calib.glb
```

Reads `assets/tshirt.glb`, `pipeline-design/pattern/panels.json` and
`assets/textures/*.png`; writes one self-contained `.glb`.

| runtime property | becomes |
|---|---|
| `uScale/uOffset/vScale/vOffset` | `TEXCOORD_0` rewritten to `uv·scale + offset` |
| `knit.uScale = 1/15` | `TEXCOORD_1` = the mm UVs over `TILE_MM` |
| `invertY = false` | nothing — glTF *defines* the UV origin, the loader handles it |
| `gammaSpace = false` | nothing — base colour is sRGB and normal is linear by spec |
| `CLAMP_ADDRESSMODE` / `WRAP` | two samplers: `CLAMP_TO_EDGE` for prints, `REPEAT` for knit |
| `metallic` / `roughness` | `pbrMetallicRoughness` |
| `bumpTexture.level = 0.45` | `normalTexture.scale` |
| `sheen.*` | `KHR_materials_sheen` |
| *(nothing — derived per-pixel)* | `TANGENT`, generated |

The numbers come from `panels.json`, and the node grouping from
`extract_pattern.py`'s `PANEL_GROUPS` — imported, not copied, so the bake cannot
drift from what was measured. It is the first piece of the de-duplication
[reusable-pipeline.md](reusable-pipeline.md) §7 asks for.

`KHR_materials_sheen` goes in `extensionsUsed`, **not** `extensionsRequired`: a
viewer without sheen support should still render the shirt, just without the
cloth lobe.

### Why baked UVs rather than `KHR_texture_transform`

Babylon's glTF exporter supports `KHR_texture_transform`, and it would work: the
mm UVs stay intact and the affine moves into the material. Baking was chosen
anyway, for two reasons.

**It needs no extension at all.** A rewritten `TEXCOORD_0` is core glTF 2.0, so
the result renders identically in anything that reads glTF — including tools that
predate the extension or skip it.

**It removes a convention hazard rather than relocating one.** The transform's
scale and offset live in glTF's top-left-origin UV space, which is exactly the
mismatch `index.html`'s `invertY: false` comment already warns about, and which
[decisions.md](decisions.md) records this project getting wrong repeatedly. A
baked attribute has no convention to get wrong — the numbers are the UVs.

The cost is that the millimetre UVs are gone from the model. That is why the knit
gets `TEXCOORD_1`, and it is not a real loss: the millimetres live in
`panels.json`, which is where the pipeline reads them from anyway.

### Why generate tangents

The `.glb` ships no `TANGENT`, so Babylon derives a tangent frame per-pixel from
screen-space derivatives. `index.html` notes this and correctly calls it a good
compromise *for Babylon*. The Khronos validator disagrees for everyone else:

```
MESH_PRIMITIVE_GENERATED_TANGENT_SPACE
Material requires a tangent space but the mesh primitive does not provide it.
Runtime-generated tangent space may be non-portable across implementations.
```

"Renders the same everywhere" is the entire point of this file, so the frame is
computed and stored. This is cheap to do *well* here specifically: the unwrap is a
real flat sewing pattern with under 4% stretch anywhere, so a near-isometric
surface has a genuine tangent frame to find rather than a least-bad compromise —
which is what MikkTSpace exists to negotiate on ordinary models.

It is computed from the **millimetre** UVs, the set the normal map actually
samples through, not from the baked `TEXCOORD_0` — that one has a different `u`
and `v` scale per panel and would skew the frame relative to the map being read.

It costs ~2 MB. `--no-tangents` skips it if that matters more than portability.

---

## 4. What is deliberately *not* in the file

**The environment.** `studio.env`, 205 KB, ships next to the `.glb`. glTF has no
ratified environment or IBL extension; every viewer supplies its own.

**Tone mapping.** KHR PBR Neutral. Not in the file, but not really a loss either
— it is the Khronos 3D Commerce standard, so a certified viewer already applies
it. Babylon's certified configuration differs from the engine defaults in exactly
two ways: this tone mapper, and `transparencyAsCoverage = true` on the glTF
loader (which turns off "specular over alpha"). `index-prod.html` sets both.

**Exposure 1.15.** This event's own grade, carried over so the two pages can be
compared. It is *not* part of the certification, so a partner site rendering at
the default 1.0 gets a slightly darker shirt. Worth knowing before someone
reports it as a bug.

**Camera framing and auto-rotate.** Viewer configuration.

---

## 5. Compression

Not done by the bake, and deliberately: `tools/` is dependency-free beyond numpy
and Pillow, and KTX2 and Draco need external binaries. Babylon's own exporter
cannot do this part either — its documented support table lists
`KHR_texture_basisu` ❌, `EXT_meshopt_compression` ❌ and
`KHR_materials_variants` ❌ — so a post-step is required whichever route you take.

```bash
npx @gltf-transform/cli optimize assets/tshirt-prod.glb assets/tshirt-prod-min.glb \
    --texture-compress ktx2 --compress meshopt
```

On texture mode, Babylon's KTX2 documentation is specific and it matters here:
**ETC1S for the prints** (true-colour data), **UASTC for `knit-normal.png`** —
ETC1S is explicitly called out as poor for anything that is not colour data, and
a normal map is direction data.

### Then self-host the decoders

The Babylon loader docs are blunt about this, and it bites the moment you
compress: Draco, meshopt and KTX2 all fetch their decoder wasm from
`cdn.babylonjs.com` at load time by default, which the docs name as a GDPR and
CSP problem. Two documented fixes — configure a base URL per decoder, or inject
the modules directly.

The same page carries the more general warning, twice:

> The CDN should not be used in production environments.

That applies to the `<script>` tags in `index.html` and `index-prod.html`, and
separately: `playground.js` fetches assets from `raw.githubusercontent.com`,
which is a Playground convenience, not a CDN — no cache headers you control, and
rate-limited. Neither is the production origin.

---

## 6. Embedding

The least-code option is Babylon Viewer v2, which is **3D Commerce Certified by
default** — the two settings above come for free:

```html
<babylon-viewer source="shirt.glb" environment="studio.env"></babylon-viewer>
```

It imports loaders and glTF extensions dynamically (no Draco or KTX2 code
downloaded unless the model uses them), suspends rendering when scrolled out of
view, and picks WebGL or WebGPU itself. `viewerconfig.babylonjs.com` generates
the attributes.

`<model-viewer>` is the other candidate. Verify sheen renders there before
committing — the cloth lobe is the whole reason this scene is PBR.

---

## 7. Verifying a build — `src/index-prod.html`

```bash
bun run dev
```

| URL | what it shows |
|---|---|
| `/` | the development scene: geometry `.glb` + 130 lines of material code |
| `/prod` | `tshirt-prod.glb` and **no material code at all** |
| `/prod?calib` | the millimetre-grid build — the acceptance test |
| `/prod?inspect` | the same with the Babylon inspector |
| `/prod?debug` | show the self-containment badge on a passing build |

`index-prod.html` contains no panel table, no texture code and no material code —
it constructs neither a material nor a texture, and the only material properties
it touches are the ones it reads back to check the bake. Everything after the
loader is camera, environment and tone mapping: the row-two items from §2. **If
the shirt renders correctly at `/prod`, the model is genuinely self-contained.**

It also asserts the contract, because a shirt that renders "nearly right" is the
failure worth guarding against — a lost material, extension or UV set still
loads and still looks like a shirt. It checks six textured materials, a normal
map on UV set 1, sheen enabled, and that no albedo texture still carries a UV
transform. The result always goes to the console; the corner badge stays hidden
unless a check fails or you ask for it, since a debug overlay burned into the
page that stands in for a production embed is the sort of thing that ships by
accident.

Three checks, in order:

1. **`/prod?calib`.** Every panel upright and unmirrored, grid at the right
   scale. This is the one that catches a flipped or rescaled bake, and it is the
   reason `make_calibration.py` exists — see [decisions.md](decisions.md).
2. **`/prod` against `/`.** Same shirt. Differences are attributable, because
   the two pages share their camera, environment and tone mapping verbatim.
3. **The validator.** `npx @gltf-transform/cli validate assets/tshirt-prod.glb`
   should report no errors and no warnings.

### A known, deliberate non-issue

The validator reports `IMAGE_NPOT_DIMENSIONS` (severity: info) for the six print
textures. Leave them. Their pixel dimensions come from the panel's millimetre
size at a chosen px/mm, which is the relationship the entire pipeline rests on;
rounding them to powers of two would break it for no benefit. NPOT with mipmaps
is fine on WebGL2 and WebGPU under `CLAMP_TO_EDGE`, and the only texture that
tiles — the knit, which is the case that would actually matter — is already
256×256.

---

## 8. What this does not solve

- **Colourways.** A store selling the same garment in several designs wants
  `KHR_materials_variants`: one geometry, several material sets, switched at
  runtime. Babylon can load it but not write it, and neither does this tool.
  `gltf-transform` can.
- **One bake per event.** The tool reads panel geometry from `panels.json` but
  the textures still come from `build_print_textures.py`'s hardcoded design
  spec. That is the same gap [reusable-pipeline.md](reusable-pipeline.md) §3
  proposes a layout manifest for; the bake sits downstream of it and needs no
  change when it arrives.
- **The inner shells.** The model carries an inner shell and rim per body panel,
  roughly doubling the front and back triangle counts. Correct for a garment
  seen from any angle, and not obviously droppable, but it is where the weight
  is if download size becomes the binding constraint.
