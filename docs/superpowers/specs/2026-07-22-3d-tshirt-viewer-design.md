# 3D T-Shirt Viewer — Alimenta Esta Corrida 2026

## Purpose

An interactive, rotatable 3D preview of the official 2026 "Alimenta Esta Corrida" event
t-shirt (design by Gabriela Nogueira — official source: `T-shirt Alimenta esta corrida
oficial 2026.pdf`; `tshirt-aec26.jpeg` was an earlier lower-res phone-screenshot version of
the same design), built as a standalone prototype in this folder. It will later be manually
ported into `afh-website`'s `/aec2026` page hero, which currently shows a static photo
(`src/app/[locale]/aec2026/page.tsx`) — that integration is **out of scope** for this spec;
this spec covers only the standalone prototype.

## Constraints

- Everything stays inside `~/JDA/AFH/AEC/` — no changes to the `afh-website` repo.
- No build step: plain HTML + Babylon.js loaded from CDN.
- The website this will eventually live on has a **black background**; the shirt itself is
  white. The viewer must look correct against black from the start.
- Final print artwork is now available: extracted directly from the official design PDF
  (`T-shirt Alimenta esta corrida oficial 2026.pdf`, by Gabriela Nogueira) at full vector
  resolution, front and back, transparent background — see "Texture / artwork" below.

## Architecture

Self-contained folder, no npm/build tooling:

```
aec-3d-tshirt/
  index.html          — HTML shell, canvas, Babylon.js CDN <script> tags, scene code
  assets/
    tshirt.glb         — sourced 3D model (manually downloaded, see below)
    front.png          — front print texture (final, extracted from official PDF)
    back.png           — back print texture (final, extracted from official PDF)
  source/
    reference-3d-mockup.png — designer's rendered mockup, visual reference only
  README.md            — CC-BY attribution + how to run locally
```

(This layout already exists under `~/JDA/AFH/AEC/aec-3d-tshirt/` — `assets/front.png` and
`assets/back.png` are in place; `assets/tshirt.glb` and `index.html` are the remaining work.)

Must be served over a local static server (e.g. `python3 -m http.server`) — opening
`index.html` directly via `file://` blocks the `.glb`/texture fetches in most browsers.

## 3D model

**Chosen:** ["T Shirt" by funlab117](https://sketchfab.com/3d-models/t-shirt-c1a3e5eb9b5445f4b7d4be82f1127eba)
— plain white basic tee, glTF format, CC-BY licensed, free.

- License requires attribution — credited in `README.md` and as an HTML comment in
  `index.html`.
- Sketchfab requires a free account login to click "Download" — this is a **manual step
  the user performs**, not something scriptable. The downloaded `.glb` goes in
  `assets/tshirt.glb`.
- Fallback option if this model proves too heavy/awkward to texture:
  [low-poly T-Shirt by JC4862](https://sketchfab.com/3d-models/t-shirt-low-poly-3e4b13a502884acfbd79cee0f9cd8876)
  (same CC-BY terms).

## Texture / artwork

Sourced from `T-shirt Alimenta esta corrida oficial 2026.pdf` (design by Gabriela Nogueira,
gabriela.dsnogueira@gmail.com — credited in `README.md`). The PDF's flat front/back
mockups are vector content (not a low-res raster embed), so they were rasterized directly
from the page at high resolution and autocropped to their alpha bounding box:

- `assets/front.png` — 2559×2525px, RGBA, transparent background. Front print: green/olive
  diagonal stripe down the left chest/sleeve, "ALIMENTA ESTA CORRIDA 2026" wordmark,
  Compressport logo (chest) and Scarpa logo (right sleeve).
- `assets/back.png` — 2559×2525px, RGBA, transparent background. Same stripe motif on the
  back-left, no text.
- `source/reference-3d-mockup.png` — the designer's own 3000×3000 rendered mockup (studio
  gray background), kept as a visual reference for how the final print should read on
  fabric (shading, drape) — not used directly as a texture.

These are real, final, print-accurate assets — the earlier placeholder-texture plan is no
longer needed. UV-mapping: apply `front.png` to the mesh's front-facing chest/sleeve region
and `back.png` to the back-facing region (exact UV layout depends on the sourced mesh's
existing UV unwrap — may need minor alignment/tweaking once the model is loaded).

## Scene, lighting, and background

- **Renderer:** `BABYLON.Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true })`
  created with an alpha-enabled context so the canvas background is transparent
  (`scene.clearColor = new BABYLON.Color4(0, 0, 0, 0)`). This means the viewer will show
  whatever is behind the canvas — no hardcoded color to keep in sync with the website's
  actual black. For this standalone prototype, `index.html`'s `<body>` gets a black
  background so it previews the same as it eventually will embedded in the site.
- **Camera:** `ArcRotateCamera` — drag to orbit, scroll to zoom, sensible
  `lowerRadiusLimit`/`upperRadiusLimit` so users can't zoom through/away from the shirt.
  Slow automatic idle rotation when the user isn't interacting.
- **Lighting:** a soft `HemisphericLight` fill (so no side is ever fully black) plus one
  `DirectionalLight` acting as a key light angled to catch the fabric folds and give the
  white material visible shading rather than a flat cutout look. A subtle green-tinted rim
  light (picking up the event's brand green from the shirt's stripe design) separates the
  shirt's silhouette from the black background without looking artificial.
- **Optional:** two simple HTML buttons ("Front" / "Back") that animate the camera's
  `alpha` to snap to those two viewing angles.

## Loading & error handling

- Use `BABYLON.SceneLoader.ImportMeshAsync` (async/await) to load `tshirt.glb`; show a
  simple "Loading…" text overlay until it resolves.
- If WebGL is unavailable, show a plain fallback message instead of a blank canvas.

## Out of scope

- Integrating into `afh-website` / Next.js (manual porting step, done later by the user).
- Physics, animation beyond camera movement, GUI beyond the optional front/back buttons.
- Automated tests — this is a small visual prototype; verification is manual (open in
  browser, confirm it loads, orbits, and reads correctly against black).

