# Production delivery

[pipeline.md](pipeline.md) ends at `src/index.html`: a page that loads a bare
geometry `.glb` and builds every material in JavaScript. That is the right shape
for developing the design — the panel table is readable, a value can be changed
and reloaded, and the Playground twin makes it shareable.

It is the wrong shape for shipping. This document is what changes, why, and what
the limits are. Unlike [reusable-pipeline.md](reusable-pipeline.md) and
[ideal-reusable-pipeline.md](ideal-reusable-pipeline.md), which are design
studies, **this one is implemented**: `tools/build_production_glb.py`,
`src/index-prod.html` and `src/index-model-validation.html`.

Those two pages are not variants of each other and the split matters:

| | |
|---|---|
| `src/index-prod.html` → `/prod` | **The embed.** Babylon Viewer v2 from npm, §6. What a site should copy — and what the association's website runs. |
| `src/index-model-validation.html` → `/model-validation` | **The acceptance test.** Hand-builds an Engine and a Scene so it can read the loaded materials back and assert the bake, §7. |

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
loader (which turns off "specular over alpha").

This is the clearest illustration of why §6 recommends the viewer.
`index-model-validation.html` sets both by hand, because it builds its own
Engine. `index-prod.html` sets neither: Viewer v2 is 3D Commerce Certified by
default, so both come for free and there is nothing to keep in sync.

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

**Measure before choosing a method.** The instinct is to compress the textures,
and on this model that is close to pointless: of 10.54 MB, the seven images are
**0.81 MB** and the geometry is **9.72 MB** — float32 positions, normals,
tangents and UVs, with uint32 indices for primitives that never exceed 24,268
vertices. KTX2 would chase the smallest tenth of the file.

This is the command that produced `assets/tshirt-prod-min.glb`, **10.54 MB →
6.77 MB**, and every flag after the first is load-bearing:

```bash
npx @gltf-transform/cli optimize assets/tshirt-prod.glb assets/tshirt-prod-min.glb \
    --compress quantize --texture-compress false --simplify false \
    --palette false --join false --flatten false --instance false \
    --prune-solid-textures false
```

| attribute | before | after |
|---|---|---|
| INDICES | 2.86 MB `u32` | 1.43 MB `u16` |
| TANGENT | 1.96 MB `f32` | 0.98 MB `i16` |
| NORMAL | 1.47 MB `f32` | 0.74 MB `i16` |
| POSITION | 1.47 MB `f32` | 0.74 MB `i16` |
| TEXCOORD_0 | 0.98 MB `f32` | 0.59 MB, mostly `u16` |
| TEXCOORD_1 | 0.98 MB `f32` | unchanged |

`KHR_mesh_quantization` is the only extension this adds, and Babylon reads it
natively — **no decoder wasm is fetched**, which is the reason to prefer it over
Draco or meshopt here. Tangents are kept, at half the bytes, so §3's portability
argument survives compression rather than being traded away.

`TEXCOORD_1` is skipped by design: the knit UV is in millimetres and tiles far
beyond [0,1], so quantizing it would require a texture transform — the exact
convention hazard the bake exists to remove.

### The passes that must stay off

`optimize` runs everything by default, and four of its passes break this model's
contract:

- **`--prune-solid-textures`** turned `print-collar_a` and `print-collar_b` into
  material factors, taking `images` from 7 to 5. Visually near-identical, and it
  breaks the "six textured materials" assertion in §7 — caught only because that
  assertion exists.
- **`--palette`** merges materials; there must be exactly six.
- **`--join` / `--flatten`** restructure meshes and nodes.
- **`--simplify`** decimates geometry. Not obviously wrong, but it is a visual
  change and must not ride along with a lossless one.

Verify a compressed build at `/model-validation?min`, which renders it with the
same camera, environment and tone mapping as the original *and* asserts the
contract, then run the validator over it.

### If more is needed

The inner shells are the next 3.72 MB — see §8 — and they are a visual decision,
not a free one. `EXT_meshopt_compression` roughly halves geometry again but
fetches a decoder wasm from `cdn.babylonjs.com` by default, which is a CSP and
GDPR problem and must be self-hosted.

On texture mode, if it ever does become worthwhile, Babylon's KTX2 documentation
is specific: **ETC1S for the prints** (true-colour data), **UASTC for
`knit-normal.png`** — ETC1S is explicitly called out as poor for anything that
is not colour data, and a normal map is direction data.

### Then self-host the decoders

The Babylon loader docs are blunt about this, and it bites the moment you
compress: Draco, meshopt and KTX2 all fetch their decoder wasm from
`cdn.babylonjs.com` at load time by default, which the docs name as a GDPR and
CSP problem. Two documented fixes — configure a base URL per decoder, or inject
the modules directly.

The same page carries the more general warning, twice:

> The CDN should not be used in production environments.

**`index-prod.html` no longer does.** It imports `@babylonjs/viewer` from npm
and Bun bundles it, which is why this repo now has a `node_modules` at all. The
`<script>` tags remain in `index.html` and `index-model-validation.html`, and
that is fine — both are development pages that only ever run on a developer's
machine. The distinction is the whole reason the two were split.

Separately: `playground.js` fetches assets from `raw.githubusercontent.com`,
which is a Playground convenience, not a CDN — no cache headers you control, and
rate-limited. Neither is the production origin.

### Bundle for production, with splitting

Worth knowing before this is built for deployment rather than served by
`bun run dev`: bundling the embed **without** code splitting collapses the
viewer's dynamic imports into one file — 4.5 MB, 1.11 MB gzipped — which throws
away the main reason to use it. With splitting, the entry is ~80 KB gzipped and
the glTF loader and each extension arrive as separate chunks.

```bash
bun build ./src/index-prod.html --outdir dist --minify --splitting
```

Bundlers that split `import()` automatically, Next.js among them, get this for
free.

---

## 6. Embedding — `src/index-prod.html`

Babylon Viewer v2, and this is no longer a recommendation to weigh up: it is
what `/prod` and the association's website both run.

```html
<babylon-viewer
  source="/assets/tshirt-prod.glb"
  environment-lighting="/assets/env/studio.env"
  environment-intensity="1"
  tone-mapping="neutral"
  camera-auto-orbit
></babylon-viewer>
```

Note `environment-lighting`, not `environment` — the attribute name in 9.x.
`viewerconfig.babylonjs.com` generates the rest.

What the viewer supplies, all of which the validation page writes by hand:

| | |
|---|---|
| 3D Commerce certified by default | `transparencyAsCoverage` and KHR PBR Neutral — the two settings from §4 |
| dynamic extension imports | `KHR_materials_sheen` is fetched; Draco, KTX2 and FBX are not |
| `autoSuspendRendering` | rendering stops when scrolled out of view or in a background tab |
| camera framing | computed from the model |
| WebGL / WebGPU | chosen per device |

**What it cannot know**, and what therefore stays in `src/prod.js`:

- **Exposure 1.15.** The viewer defaults to 1.0, and §4 explains why that is
  correct-but-different.
- **The key light.** The viewer lights from the environment alone. Added through
  `viewerDetails.scene`, with `specular` black so the shine stays with the
  material's sheen lobe. A scene changed from outside the viewer must call
  `viewerDetails.markSceneMutated()`, since it renders on demand rather than
  every frame.

### Four things that bite

Every one of these failed *silently* — no exception, no error event, and in two
cases no network request at all. Between them they cost an afternoon on the
website embed, so they are written down in the order they were hit.

**Version skew.** The viewer declares `peerDependencies: { "@babylonjs/core":
"^9.0.0" }`, which is far looser than reality. Viewer 9.20 against core 9.17
installs without a warning, creates its engine, logs the *core* version to the
console — and then never loads the model, with no error thrown and no event
fired. Keep `@babylonjs/core`, `@babylonjs/loaders` and `@babylonjs/viewer` on
the same version. The console banner naming a version you did not expect is the
tell.

**React sets `source` as a property, and the viewer ignores it.** React assigns
a prop to a custom element as a *property* when the name exists on the element,
and only falls back to an attribute otherwise. So `environment-lighting` and
`tone-mapping` — dash-cased, not property names — arrive as attributes and work,
while `source` is assigned as a property before the viewer instance exists, and
that assignment is dropped. The element then sits there fully initialised,
holding the correct URL in `.source`, having never requested anything. Set it as
an attribute instead:

```jsx
// NOT source={url} — that becomes a property and is lost
viewerRef.current.setAttribute("source", url);
```

The tell is `viewer.source` returning the right URL while
`viewer.getAttribute("source")` returns `null`. In plain HTML, as on this page,
the attribute is present from parse time and the problem does not exist.

**A CSP without `blob:` in `connect-src` breaks the textures.** Babylon extracts
the images embedded in a `.glb` into Blob URLs and fetches them back, so a
policy of `connect-src 'self'` blocks every one. The model downloads, then fails
per texture with `Error status: 0` — which reads like a corrupt asset rather
than a policy decision, and the browser's CSP violations are logged separately
from Babylon's error. `blob:` grants no new reach; a `blob:` URL can only be one
the page itself created. `/prod` never hits this because Bun serves no CSP —
which is exactly why an embed must be tested behind the real headers.

**The mousewheel.** The viewer wires the standard zoom, which is right for a
full-page viewer and wrong for one embedded mid-article: it captures the wheel
on hover and stalls anyone scrolling past. The website detaches
`camera.inputs.attached.mousewheel` until the visitor clicks the shirt. `/prod`
keeps it, being a full-page viewer.

`<model-viewer>` is the other candidate. Verify sheen renders there before
committing — the cloth lobe is the whole reason this scene is PBR.

---

## 7. Verifying a build — `src/index-model-validation.html`

```bash
bun run dev
```

| URL | what it shows |
|---|---|
| `/` | the development scene: geometry `.glb` + 130 lines of material code |
| `/prod` | the production embed, §6 — Viewer v2, no material code and no engine code either |
| `/model-validation` | `tshirt-prod.glb` on a hand-built Engine and **no material code at all** |
| `/model-validation?calib` | the millimetre-grid build — the acceptance test |
| `/model-validation?inspect` | the same with the Babylon inspector |
| `/model-validation?debug` | show the self-containment badge on a passing build |

`index-model-validation.html` contains no panel table, no texture code and no
material code — it constructs neither a material nor a texture, and the only
material properties it touches are the ones it reads back to check the bake.
Everything after the loader is camera, environment and tone mapping: the row-two
items from §2. **If the shirt renders correctly at `/model-validation`, the
model is genuinely self-contained.**

It hand-builds an Engine on purpose, and that is the one thing to preserve if
this page is ever revisited. The viewer at `/prod` renders the shirt but cannot
tell you *why* it looks right, and a shirt that renders "nearly right" is the
failure worth guarding against. Reading the materials back requires owning the
scene.

It also asserts the contract, because a shirt that renders "nearly right" is the
failure worth guarding against — a lost material, extension or UV set still
loads and still looks like a shirt. It checks six textured materials, a normal
map on UV set 1, sheen enabled, and that no albedo texture still carries a UV
transform. The result always goes to the console; the corner badge stays hidden
unless a check fails or you ask for it, since a debug overlay burned into the
page that stands in for a production embed is the sort of thing that ships by
accident.

Three checks, in order:

1. **`/model-validation?calib`.** Every panel upright and unmirrored, grid at
   the right scale. This is the one that catches a flipped or rescaled bake, and
   it is the reason `make_calibration.py` exists — see
   [decisions.md](decisions.md).
2. **`/model-validation` against `/`.** Same shirt. Differences are
   attributable, because the two pages share their camera, environment and tone
   mapping verbatim.
3. **`/prod` against `/model-validation`.** Also the same shirt, but the
   agreement means something different: the validation page sets the tone
   mapper, `transparencyAsCoverage` and the framing explicitly, and the viewer
   arrives at them by default. A divergence here is the viewer's configuration
   drifting from the certified one, not a bad bake.
4. **The validator.** `npx @gltf-transform/cli validate assets/tshirt-prod.glb`
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
