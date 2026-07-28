# 3D T-Shirt Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone HTML page in `~/JDA/AFH/AEC/aec-3d-tshirt/` that shows an
interactive, rotatable 3D preview of the official 2026 "Alimenta Esta Corrida" event
t-shirt, ready to be manually ported into `afh-website` later.

**Architecture:** Single `index.html` loads Babylon.js from CDN (no build step), sets up a
transparent-background scene with an orbit camera and studio-style lighting, loads a
CC-BY-licensed generic t-shirt `.glb` mesh, paints it plain white, then projects the
official front/back print artwork onto the chest/back via Babylon's decal system (so it
works regardless of the mesh's own UV layout).

**Tech Stack:** Babylon.js 7.x (CDN), plain HTML/CSS/JS, no npm/build tooling, no test
framework — verification is manual (open in browser, confirm visually).

## Global Constraints

- Everything lives under `~/JDA/AFH/AEC/aec-3d-tshirt/` — do not touch `afh-website` or any
  other project.
- No build step: Babylon.js and the glTF loader are loaded via `<script>` tags from
  `https://cdn.babylonjs.com/`.
- Must be served over a local static server (`python3 -m http.server`), not opened via
  `file://` — the `.glb`/texture fetches will be blocked by the browser otherwise.
- Canvas/scene background is transparent (`alpha: true` on the engine, `clearColor` with
  0 alpha) so it will drop into the website's black background later with no color
  matching needed. The standalone `index.html`'s `<body>` has a black background so it
  previews correctly now.
- `assets/front.png` and `assets/back.png` already exist (2559×2525px RGBA, transparent
  background, extracted from the official design PDF) — do not regenerate them.
- `assets/tshirt.glb` does **not** exist yet and cannot be fetched automatically — Sketchfab
  requires a logged-in browser session to download. The user downloads
  ["T Shirt" by funlab117](https://sketchfab.com/3d-models/t-shirt-c1a3e5eb9b5445f4b7d4be82f1127eba)
  (glTF/glb export, CC-BY licensed) and saves it to `assets/tshirt.glb` before Task 3.
- CC-BY attribution for the mesh, and a credit line for the print design (Gabriela
  Nogueira), must appear in `README.md`.
- No git repository exists in this folder — there are no commit steps in this plan. Each
  task ends with a manual browser-verification checkpoint instead.

---

### Task 1: HTML shell, engine/scene boilerplate, transparent background

**Files:**
- Create: `aec-3d-tshirt/index.html`

**Interfaces:**
- Produces: a running Babylon.js `engine` and `scene` in global scope, a `<canvas
  id="renderCanvas">`, and a `#loading` overlay `<div>` that later tasks show/hide.

- [ ] **Step 1: Write `index.html` with the engine/scene/render-loop boilerplate**

```html
<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8" />
  <title>Alimenta Esta Corrida 2026 — T-shirt 3D</title>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      background: #000; /* simulates the website's black background */
      overflow: hidden;
    }
    #renderCanvas {
      width: 100%;
      height: 100%;
      display: block;
      touch-action: none;
    }
    #loading, #fallback {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      color: #fff;
      font-family: sans-serif;
      font-size: 1.1rem;
      text-align: center;
    }
    #fallback { display: none; }
  </style>
</head>
<body>
  <canvas id="renderCanvas"></canvas>
  <div id="loading">A carregar…</div>
  <div id="fallback">O teu navegador não suporta WebGL, necessário para esta pré-visualização 3D.</div>

  <!-- Babylon.js core + glTF/glb loader, from CDN. No build step. -->
  <script src="https://cdn.babylonjs.com/babylon.js"></script>
  <script src="https://cdn.babylonjs.com/loaders/babylonjs.loaders.min.js"></script>

  <script>
    const canvas = document.getElementById("renderCanvas");
    const loadingEl = document.getElementById("loading");
    const fallbackEl = document.getElementById("fallback");

    if (!BABYLON.Engine.isSupported()) {
      canvas.style.display = "none";
      loadingEl.style.display = "none";
      fallbackEl.style.display = "block";
    } else {
      const engine = new BABYLON.Engine(canvas, true, {
        preserveDrawingBuffer: true,
        stencil: true,
        alpha: true,
      });

      const scene = new BABYLON.Scene(engine);
      scene.clearColor = new BABYLON.Color4(0, 0, 0, 0); // transparent

      engine.runRenderLoop(() => {
        scene.render();
      });

      window.addEventListener("resize", () => {
        engine.resize();
      });
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: Serve the folder locally**

Run: `cd ~/JDA/AFH/AEC/aec-3d-tshirt && python3 -m http.server 8000`

- [ ] **Step 3: Verify in browser**

Open `http://localhost:8000/` in a browser.

Expected: a solid black page with the text "A carregar…" centered on screen, no console
errors (open DevTools console — should be empty of red errors). The page does not go blank
or show the WebGL-unsupported fallback message.

---

### Task 2: Camera and lighting, verified against a temporary debug box

**Files:**
- Modify: `aec-3d-tshirt/index.html`

**Interfaces:**
- Consumes: `engine`, `scene`, `canvas` from Task 1.
- Produces: `camera` (module-level `const` inside the script block) that Task 5 reuses to
  add view-snap buttons.

- [ ] **Step 1: Add camera, lighting, and a temporary debug box to the script block**

Insert this immediately after `scene.clearColor = ...` and before `engine.runRenderLoop`:

```js
      // --- Camera ---
      const camera = new BABYLON.ArcRotateCamera(
        "camera",
        -Math.PI / 2,   // alpha: face the shirt head-on
        Math.PI / 2.3,  // beta: slightly above eye-level
        6,              // radius: starting distance
        BABYLON.Vector3.Zero(),
        scene
      );
      camera.attachControl(canvas, true);
      camera.lowerRadiusLimit = 3;
      camera.upperRadiusLimit = 12;
      camera.wheelPrecision = 50;
      camera.lowerBetaLimit = 0.3;
      camera.upperBetaLimit = Math.PI - 0.3;

      // --- Lighting ---
      const fillLight = new BABYLON.HemisphericLight(
        "fillLight",
        new BABYLON.Vector3(0, 1, 0),
        scene
      );
      fillLight.intensity = 0.6;

      const keyLight = new BABYLON.DirectionalLight(
        "keyLight",
        new BABYLON.Vector3(-1, -1.5, -1),
        scene
      );
      keyLight.position = new BABYLON.Vector3(4, 6, 4);
      keyLight.intensity = 0.9;

      const rimLight = new BABYLON.DirectionalLight(
        "rimLight",
        new BABYLON.Vector3(1, 0.3, 1),
        scene
      );
      rimLight.diffuse = new BABYLON.Color3(0.55, 0.75, 0.35); // event brand green
      rimLight.intensity = 0.35;

      // --- TEMPORARY debug box (removed in Task 3 once the real model loads) ---
      const debugBox = BABYLON.MeshBuilder.CreateBox("debugBox", { size: 2 }, scene);
      const debugMat = new BABYLON.StandardMaterial("debugMat", scene);
      debugMat.diffuseColor = new BABYLON.Color3(1, 1, 1);
      debugBox.material = debugMat;

      // Idle auto-rotate
      let userInteracting = false;
      canvas.addEventListener("pointerdown", () => { userInteracting = true; });
      scene.onBeforeRenderObservable.add(() => {
        if (!userInteracting) {
          camera.alpha += 0.0015;
        }
      });

      loadingEl.style.display = "none";
```

- [ ] **Step 2: Verify in browser**

Refresh `http://localhost:8000/`.

Expected: a lit white cube on a black background, slowly auto-rotating. Dragging with the
mouse orbits around it (and stops the auto-rotate); scrolling zooms in/out but cannot pass
through the cube or zoom out past a reasonable distance. The right side of the cube should
look faintly green-tinted (the rim light) compared to the left. No console errors.

---

### Task 3: Load the real t-shirt model, replacing the debug box

**Files:**
- Modify: `aec-3d-tshirt/index.html`

**Interfaces:**
- Consumes: `scene`, `debugBox`, `loadingEl` from Tasks 1–2; `assets/tshirt.glb` (manually
  downloaded by the user, see Global Constraints).
- Produces: `torso` (the main shirt mesh, module-level `let`, assigned once the model
  finishes loading) and `shirtBounds` (its world bounding-box info, same `let` pattern)
  that Task 4's decal placement relies on.

- [ ] **Step 1: Confirm the model file is in place**

Run: `ls -la ~/JDA/AFH/AEC/aec-3d-tshirt/assets/tshirt.glb`

Expected: the file exists and is a few hundred KB to a few MB. If it's missing, stop here
and download it manually from
https://sketchfab.com/3d-models/t-shirt-c1a3e5eb9b5445f4b7d4be82f1127eba (requires a free
Sketchfab login to click "Download", choose the glTF/glb format) before continuing.

- [ ] **Step 2: Replace the debug box with the real model**

In `index.html`, delete the "TEMPORARY debug box" block from Task 2 (the `debugBox` and
`debugMat` lines), and replace `loadingEl.style.display = "none";` with:

```js
      let torso = null;
      let shirtBounds = null;

      BABYLON.SceneLoader.ImportMeshAsync("", "assets/", "tshirt.glb", scene)
        .then((result) => {
          console.log(
            "Loaded meshes:",
            result.meshes.map((m) => m.name)
          );

          // Pick the largest mesh by vertex count as the main torso/body mesh
          // (some exports include separate meshes for buttons/seams/logos).
          torso = result.meshes
            .filter((m) => m.getTotalVertices() > 0)
            .sort((a, b) => b.getTotalVertices() - a.getTotalVertices())[0];

          // Plain white base material, regardless of whatever material the
          // downloaded model shipped with.
          const baseMat = new BABYLON.StandardMaterial("baseMat", scene);
          baseMat.diffuseColor = new BABYLON.Color3(0.95, 0.95, 0.95);
          baseMat.specularColor = new BABYLON.Color3(0.05, 0.05, 0.05);
          result.meshes.forEach((m) => {
            if (m.material) m.material = baseMat;
          });

          shirtBounds = torso.getBoundingInfo().boundingBox;
          console.log(
            "Torso bounds — center:", shirtBounds.centerWorld,
            "half-extents:", shirtBounds.extendSizeWorld
          );

          // Re-frame the camera on the actual model size.
          const radius = shirtBounds.extendSizeWorld.length() * 2.2;
          camera.setTarget(shirtBounds.centerWorld);
          camera.radius = radius;
          camera.lowerRadiusLimit = radius * 0.5;
          camera.upperRadiusLimit = radius * 2;

          loadingEl.style.display = "none";
        })
        .catch((err) => {
          console.error("Failed to load tshirt.glb:", err);
          loadingEl.textContent = "Erro ao carregar o modelo 3D.";
        });
```

- [ ] **Step 3: Verify in browser**

Refresh `http://localhost:8000/`. Open the DevTools console.

Expected: console prints `Loaded meshes: [...]` (a list of one or more mesh names) followed
by `Torso bounds — center: ... half-extents: ...`. The page shows a plain white t-shirt
model on the black background, correctly framed (not too close/far), orbitable and slowly
auto-rotating. No console errors. Note down the printed half-extents values — Task 4 uses
them as a sanity check.

---

### Task 4: Front/back print via decals

**Files:**
- Modify: `aec-3d-tshirt/index.html`

**Interfaces:**
- Consumes: `torso`, `shirtBounds`, `scene` from Task 3; `assets/front.png`,
  `assets/back.png` (already on disk).
- Produces: `frontDecal`, `backDecal` meshes (for reference only — no later task consumes
  them).

- [ ] **Step 1: Add a decal-creation helper and call it for front and back**

Add this function above the `BABYLON.SceneLoader.ImportMeshAsync(...)` call, and call it
inside the `.then((result) => { ... })` block right after the `shirtBounds = ...` /
camera-framing lines from Task 3:

```js
      function addPrintDecal(name, torsoMesh, bounds, texturePath, zSign) {
        const center = bounds.centerWorld;
        const half = bounds.extendSizeWorld;

        // Chest/back print sits slightly above vertical center, roughly
        // centered horizontally, projected from just outside the mesh surface.
        const position = new BABYLON.Vector3(
          center.x,
          center.y + half.y * 0.15,
          center.z + half.z * zSign
        );
        const normal = new BABYLON.Vector3(0, 0, zSign);
        // Decal size: most of the torso's width/height, shallow depth so the
        // projection only affects the front- or back-facing surface.
        const size = new BABYLON.Vector3(half.x * 1.3, half.y * 1.1, half.z * 0.8);

        const decal = BABYLON.MeshBuilder.CreateDecal(name, torsoMesh, {
          position,
          normal,
          size,
          angle: 0,
        });

        const decalMat = new BABYLON.StandardMaterial(name + "Mat", scene);
        decalMat.diffuseTexture = new BABYLON.Texture(texturePath, scene);
        decalMat.diffuseTexture.hasAlpha = true;
        decalMat.useAlphaFromDiffuseTexture = true;
        decalMat.specularColor = new BABYLON.Color3(0, 0, 0);
        decalMat.zOffset = -2; // render slightly in front to avoid z-fighting
        decal.material = decalMat;

        return decal;
      }
```

Then, inside the `.then((result) => { ... })` block, right after the camera-framing lines
(`camera.upperRadiusLimit = radius * 2;`) and before `loadingEl.style.display = "none";`,
add:

```js
          const frontDecal = addPrintDecal("frontDecal", torso, shirtBounds, "assets/front.png", 1);
          const backDecal = addPrintDecal("backDecal", torso, shirtBounds, "assets/back.png", -1);
```

- [ ] **Step 2: Verify in browser and calibrate**

Refresh `http://localhost:8000/`.

Expected: the front print (green/olive stripes, "ALIMENTA ESTA CORRIDA 2026" text) appears
projected onto the chest, and rotating the model 180° shows the back print (stripes only)
on the back. No console errors.

If the print appears on the wrong side (front texture shows on the back of the mesh, or
vice versa): the model's front-facing axis is flipped from what was assumed — swap the
`zSign` arguments in the two `addPrintDecal(...)` calls (`1` ↔ `-1`).

If the print is misaligned (too high/low, too big/small, or wrapping oddly around the
sides): adjust the multipliers in the `position` and `size` calculations inside
`addPrintDecal` (e.g. change `half.y * 0.15` to `half.y * 0.05` to lower the print, or
`half.x * 1.3` to `half.x * 1.0` to shrink it horizontally) and refresh until it sits
centered on the chest/back, matching `source/reference-3d-mockup.png` as a visual guide.

---

### Task 5: Front/Back view-snap buttons

**Files:**
- Modify: `aec-3d-tshirt/index.html`

**Interfaces:**
- Consumes: `camera` from Task 2.

- [ ] **Step 1: Add the buttons to the HTML body**

Add this inside `<body>`, right after the `<canvas>` element:

```html
  <div id="viewButtons" style="position:absolute; bottom:24px; left:50%; transform:translateX(-50%); display:flex; gap:12px;">
    <button id="btnFront" style="padding:8px 20px; font-family:sans-serif; cursor:pointer;">Frente</button>
    <button id="btnBack" style="padding:8px 20px; font-family:sans-serif; cursor:pointer;">Trás</button>
  </div>
```

- [ ] **Step 2: Wire them up to the camera**

Add this at the end of the main script block (after the `onBeforeRenderObservable.add`
idle-rotate code from Task 2):

```js
      document.getElementById("btnFront").addEventListener("click", () => {
        userInteracting = true;
        camera.alpha = -Math.PI / 2;
      });
      document.getElementById("btnBack").addEventListener("click", () => {
        userInteracting = true;
        camera.alpha = Math.PI / 2;
      });
```

- [ ] **Step 3: Verify in browser**

Refresh `http://localhost:8000/`. Click "Frente", then "Trás".

Expected: clicking "Frente" snaps the camera to show the front print; clicking "Trás"
snaps it to show the back print. Auto-rotate stays stopped after clicking either button
(since `userInteracting` is now `true`). No console errors.

---

### Task 6: README with attribution and run instructions

**Files:**
- Create: `aec-3d-tshirt/README.md`

- [ ] **Step 1: Write the README**

```markdown
# Alimenta Esta Corrida 2026 — 3D T-Shirt Viewer

Standalone, interactive 3D preview of the official 2026 event t-shirt. No build step —
plain HTML + Babylon.js loaded from CDN.

## Running locally

This must be served over HTTP (not opened directly as a `file://` URL, which blocks the
model/texture fetches):

\`\`\`bash
cd aec-3d-tshirt
python3 -m http.server 8000
\`\`\`

Then open http://localhost:8000/ in a browser. Drag to orbit, scroll to zoom, or use the
"Frente"/"Trás" buttons to snap to the front/back view.

## Assets and attribution

- `assets/front.png`, `assets/back.png` — official print design for the 2026 t-shirt,
  extracted from `T-shirt Alimenta esta corrida oficial 2026.pdf`. Design by
  **Gabriela Nogueira** (gabriela.dsnogueira@gmail.com).
- `assets/tshirt.glb` — ["T Shirt" by funlab117](https://sketchfab.com/3d-models/t-shirt-c1a3e5eb9b5445f4b7d4be82f1127eba),
  licensed [CC-BY](https://creativecommons.org/licenses/by/4.0/). Attribution required if
  redistributed.
- `source/reference-3d-mockup.png` — designer's own rendered mockup, kept as a visual
  reference for how the print should read on fabric.

## Status / next steps

This is a standalone prototype. It is not yet integrated into `afh-website` — that's a
manual porting step, done separately (see
`docs/superpowers/specs/2026-07-22-3d-tshirt-viewer-design.md` in the parent `AEC` folder
for the full design).
```

- [ ] **Step 2: Full run-through checkpoint**

Run: `cd ~/JDA/AFH/AEC/aec-3d-tshirt && python3 -m http.server 8000`, open
`http://localhost:8000/` fresh (hard-reload to clear cache).

Expected end-to-end: black page loads → "A carregar…" briefly appears → white t-shirt
model appears with the green-striped front print facing the camera → it slowly auto-rotates
→ dragging orbits it and stops the auto-rotate → scrolling zooms within limits → clicking
"Frente"/"Trás" snaps to those views → no red errors in the DevTools console at any point.
