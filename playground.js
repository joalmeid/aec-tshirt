// Select all of this file and paste it into playground.babylonjs.com, replacing
// what is there. Nothing to trim: the whole file is the Playground program.
//
// Playground supplies `canvas` and `engine` itself and calls the exported
// createScene(), awaiting it, so there is no HTML wrapper, CDN script tag or
// engine bootstrap here. `export` puts the Playground in module mode, which is
// what allows top-level declarations like ASSET_ROOT below.
//
// This is a mirror of index.html's createScene(). Everything from
// "Pattern-space texturing" down is kept character-identical to that file, so
// the two cannot drift; only this header, the asset root, and index.html's
// loading-element and debugLayer lines differ.
//
// Assets load over the network from the public aec-tshirt repo.
// raw.githubusercontent.com sends permissive CORS headers, so it is reachable
// from playground.babylonjs.com — see
// doc.babylonjs.com/toolsAndResources/thePlayground/externalPGAssets.
//
// NOTE: this URL pins the "main" branch. The pattern-space textures it needs
// (assets/textures/print-*.png) only resolve once they are pushed there —
// point this at another branch name to test before merging.
const ASSET_ROOT = "https://raw.githubusercontent.com/joalmeid/aec-tshirt/main/assets/";

export const createScene = async function () {
  const scene = new BABYLON.Scene(engine);
  scene.clearColor = new BABYLON.Color4(0, 0, 0, 0); // transparent

  // --- Camera ---
  const camera = new BABYLON.ArcRotateCamera(
    "camera",
    Math.PI / 2,    // alpha: face the shirt's front (Body_Front is the z>0 panel)
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
  camera.minZ = 0.01; // default (1) clips nearby geometry at this model's small scale

  // --- Lighting ---
  const fillLight = new BABYLON.HemisphericLight(
    "fillLight",
    new BABYLON.Vector3(0, 1, 0),
    scene
  );
  fillLight.intensity = 0.6;

  // Two key lights, mirrored front/back (z-component flipped), so
  // whichever panel the camera is orbited to face is lit — a single
  // one-sided key light left the opposite panel dim/gray whenever the
  // camera turned to view it (this model has separate front/back mesh
  // panels, not one continuous double-sided shell).
  const keyLight = new BABYLON.DirectionalLight(
    "keyLight",
    new BABYLON.Vector3(-1, -1.5, 1),
    scene
  );
  keyLight.position = new BABYLON.Vector3(4, 6, 4);
  keyLight.intensity = 0.9;
  // No true specular contribution from this light — the low-shine
  // fabric look is meant to come from the material, not a highlight.
  keyLight.specular = new BABYLON.Color3(0, 0, 0);

  // Reduced from the original 0.9 (matching keyLight): at full
  // intensity, this light's diffuse contribution stacks with
  // keyLight's on the sleeves' curved (cylindrical) surface — their
  // normals sweep through a band that faces both lights favorably at
  // once, and the summed diffuse energy clipped to a hard white
  // "shiny" streak there. The flatter torso panels don't show this
  // because their normals stay mostly uniform, so they never enter
  // that double-lit overlap band. Still enough fill to keep the back
  // panel from reading dim/gray, without blowing out the sleeves.
  const keyLightBack = new BABYLON.DirectionalLight(
    "keyLightBack",
    new BABYLON.Vector3(-1, -1.5, -1),
    scene
  );
  keyLightBack.position = new BABYLON.Vector3(4, 6, -4);
  keyLightBack.intensity = 0.45;
  keyLightBack.specular = new BABYLON.Color3(0, 0, 0);

  const rimLight = new BABYLON.DirectionalLight(
    "rimLight",
    new BABYLON.Vector3(1, 0.3, 1),
    scene
  );
  rimLight.diffuse = new BABYLON.Color3(0.55, 0.75, 0.35); // event brand green
  rimLight.intensity = 0.05;

  // Idle auto-rotate
  let userInteracting = false;
  canvas.addEventListener("pointerdown", () => { userInteracting = true; });
  scene.onBeforeRenderObservable.add(() => {
    if (!userInteracting) {
      camera.alpha += 0.0015;
    }
  });

  // --- Pattern-space texturing -------------------------------------
  //
  // This model is a Marvelous Designer / CLO3D garment, and MD writes UVs
  // as the real 2D SEWING PATTERN measured in MILLIMETRES (positions are
  // in metres, so uvArea/3dArea comes out at a constant ~1000). Measured
  // across every panel, sqrt(uvArea/3dArea) varies by under 4% from the
  // 5th to the 95th percentile — the unwrap is essentially distortion
  // free, because it is a real flat pattern rather than a projection.
  //
  // That is why this file no longer uses CreateDecal. A decal is a planar
  // box projection: on a curved, seamed garment it smears wherever the
  // surface turns away from the projection axis, it cannot stop at a
  // seam, and it needs per-panel fudge factors that never quite converge.
  // Texturing through the pattern UVs is exact by construction — the
  // print terminates on the neckline, armhole, shoulder and hem because
  // those ARE the UV island boundary, at geometry precision.
  //
  // Textures are authored in pattern millimetres and baked by
  // tools/build_print_textures.py. They are drawn FULL BLEED, past the
  // panel edge, on purpose: the mesh island does the clipping, so there
  // is no texture border for mip-mapping to bleed against.
  //
  // uScale/uOffset/vScale/vOffset below map those millimetre UVs into
  // 0..1. uScale is NEGATIVE because the texture is authored as the panel
  // seen from OUTSIDE (left-to-right as you look at the garment) while
  // pattern u runs the other way — u increases with world +X, which this
  // scene's left-handed camera puts on the viewer's LEFT. That mirror was
  // settled by rendering tools/make_calibration.py's grid textures rather
  // than reasoned from handedness: the glTF V convention, the pattern's
  // u/X sign and the camera all interact, and argument is unreliable
  // there. Regenerate these numbers with tools/extract_pattern.py if the
  // model is ever replaced.
  // Texture paths are relative to ASSET_ROOT (declared at the top of this
  // file, pointing at raw.githubusercontent.com) so this block stays
  // character-identical to the one in index.html.
  const PANELS = {
    front: {
      node: "Body_Front_Node_4",
      texture: "textures/print-front.png",
      // pattern piece 511.63 x 703.22 mm
      uScale: -0.00195454, uOffset: 0.49999156,
      vScale: 0.00142203, vOffset: 0.57734550,
    },
    back: {
      node: "Body_Back_Node_5",
      texture: "textures/print-back.png",
      // pattern piece 511.54 x 729.04 mm
      uScale: -0.00195488, uOffset: 0.50000785,
      vScale: 0.00137167, vOffset: 0.52828288,
    },
    // "left"/"right" follow the WEARER, matching both the glTF node names
    // and the PSD's layer names. Sleeves_Node_6 is world x>0, which this
    // scene renders on the VIEWER'S LEFT — it is the striped sleeve.
    sleeve_r: {
      node: "Sleeves_Node_6",
      texture: "textures/print-sleeve_r.png",
      // pattern piece 397.13 x 204.03 mm
      uScale: -0.00251807, uOffset: 0.50000008,
      vScale: 0.00490134, vOffset: 0.49992072,
    },
    sleeve_l: {
      node: "Sleeves_Node_7",
      texture: "textures/print-sleeve_l.png",
      // pattern piece 397.13 x 204.03 mm — carries the SCARPA badge
      uScale: -0.00251807, uOffset: 0.49999992,
      vScale: 0.00490134, vOffset: 0.49992072,
    },
    collar_a: {
      node: "Ribbing_Node_2",
      texture: "textures/print-collar_a.png",
      // pattern piece 187.30 x 17.00 mm
      uScale: -0.00533901, uOffset: 0.50000000,
      vScale: 0.05882353, vOffset: 0.50000000,
    },
    collar_b: {
      node: "Ribbing_Node_3",
      texture: "textures/print-collar_b.png",
      // pattern piece 272.32 x 17.00 mm
      uScale: -0.00367209, uOffset: 0.50000000,
      vScale: 0.05882353, vOffset: 0.50000000,
    },
  };

  function makePanelMaterial(name, panel) {
    const mat = new BABYLON.StandardMaterial(name + "Mat", scene);
    // invertY MUST be false here. glTF puts the UV origin at the image's
    // TOP-left, and Babylon's own glTF loader creates its textures with
    // invertY:false to match — but this constructor defaults to
    // invertY:true, which flips the upload and would render every print
    // upside down on UVs that came out of a .glb. The 4th argument is
    // invertY; the 3rd is noMipmap, left false so mip-mapping stays on.
    // onError matters more than it looks. A texture that fails to load is not
    // an obvious failure on screen: Babylon substitutes its built-in fallback,
    // a 256x256 red-and-black checkerboard, so the shirt renders "fine" in
    // bright red and nothing is logged about why. Naming the URL turns that
    // into a one-line diagnosis — usually the asset root pointing at a branch
    // or commit where assets/textures/ does not exist yet.
    const url = ASSET_ROOT + panel.texture;
    const tex = new BABYLON.Texture(url, scene, false, false, undefined, null, (message, exception) => {
      console.error(
        `[${name}] texture failed to load: ${url}\n` +
          "The shirt will render with Babylon's red/black fallback checkerboard.\n" +
          (message || exception || "")
      );
    });
    tex.uScale = panel.uScale;
    tex.uOffset = panel.uOffset;
    tex.vScale = panel.vScale;
    tex.vOffset = panel.vOffset;
    // The transformed UVs land exactly in 0..1, but the 0.5mm rim meshes
    // that join each panel's outer and inner shell extend a hair past it.
    // Clamping makes them take the edge colour instead of wrapping round
    // to the opposite side of the print.
    tex.wrapU = BABYLON.Texture.CLAMP_ADDRESSMODE;
    tex.wrapV = BABYLON.Texture.CLAMP_ADDRESSMODE;
    mat.diffuseTexture = tex;
    // White, so the texture alone decides colour.
    mat.diffuseColor = new BABYLON.Color3(1, 1, 1);
    mat.specularColor = new BABYLON.Color3(0.05, 0.05, 0.05);
    return mat;
  }

  try {
    const result = await BABYLON.SceneLoader.ImportMeshAsync("", ASSET_ROOT, "tshirt.glb", scene);

    console.log(
      "Loaded meshes:",
      result.meshes.map((m) => m.name)
    );

    // Group meshes by their glTF PARENT node name. That name is the only
    // reliable identifier here — an earlier version picked the front
    // panel by largest-vertex-count and silently got the back one, which
    // happens to have more vertices, and picking sleeves by world-X sign
    // got them swapped twice. Each group holds three meshes for the body
    // panels (outer shell, inner shell 0.5mm behind it with flipped
    // normals, and the rim band joining them) and one for each sleeve.
    const byNode = new Map();
    result.meshes.forEach((m) => {
    const parent = m.parent && m.parent.name;
    if (!parent) return;
    if (!byNode.has(parent)) byNode.set(parent, []);
    byNode.get(parent).push(m);
    });

    // Anything the model ships that we have no pattern data for stays
    // plain white rather than keeping its original material.
    const baseMat = new BABYLON.StandardMaterial("baseMat", scene);
    baseMat.diffuseColor = new BABYLON.Color3(0.95, 0.95, 0.95);
    baseMat.specularColor = new BABYLON.Color3(0.05, 0.05, 0.05);
    result.meshes.forEach((m) => {
    if (m.material) m.material = baseMat;
    });

    const sleeveMeshes = [];
    Object.entries(PANELS).forEach(([name, panel]) => {
    const group = byNode.get(panel.node);
    if (!group || !group.length) {
      console.warn("no meshes found under node", panel.node, "for panel", name);
      return;
    }
    const mat = makePanelMaterial(name, panel);
    // Every mesh in the group shares the panel's UV layout, so the
    // inner shell and rim take the same material and stay in register
    // with the outer shell's print.
    group.forEach((m) => { m.material = mat; });
    if (name === "sleeve_r" || name === "sleeve_l") sleeveMeshes.push(...group);
    });

    const frontGroup = byNode.get(PANELS.front.node) || [];
    const shirtBounds = (frontGroup[0] || result.meshes[0]).getBoundingInfo().boundingBox;

    // Re-frame the camera on the actual model size.
    const radius = shirtBounds.extendSizeWorld.length() * 2.2;
    camera.setTarget(shirtBounds.centerWorld);
    camera.radius = radius;
    camera.lowerRadiusLimit = radius * 0.5;
    camera.upperRadiusLimit = radius * 2;

    // keyLightBack's diffuse contribution overlaps keyLight's on the
    // sleeves' curved (cylindrical) surface — their normals sweep
    // through a band that faces both lights favorably at once, and
    // the summed diffuse energy clips to a hard white "shiny" streak
    // there (confirmed via screenshot; reducing keyLightBack's
    // intensity alone wasn't enough to fix it). The flat torso panels
    // don't have this problem, so only the sleeves are excluded —
    // they're still lit by keyLight + fillLight, just not double-lit.
    sleeveMeshes.forEach((m) => keyLightBack.excludedMeshes.push(m));
  } catch (err) {
    console.error("Failed to load tshirt.glb:", err);
  }

  return scene;
};
