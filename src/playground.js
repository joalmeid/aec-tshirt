// https://playground.babylonjs.com/#TI5ATU#4
// Select all and paste into playground.babylonjs.com. Mirrors src/index.html's
// createScene(); see docs/decisions.md for why anything here is the way it is.
// ASSET_ROOT pins the "main" branch — assets must be pushed there to resolve.
const ASSET_ROOT = "https://raw.githubusercontent.com/joalmeid/aec-tshirt/main/assets/";

export const createScene = async function () {
  const scene = new BABYLON.Scene(engine);
  scene.clearColor = new BABYLON.Color4(0, 0, 0, 0); // transparent

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
  camera.minZ = 0.01; // default (1) clips this model's small scale

  scene.environmentTexture = BABYLON.CubeTexture.CreateFromPrefilteredData(
    ASSET_ROOT + "env/studio.env",
    scene
  );
  scene.environmentIntensity = 1.0; // IBL does the lighting; sheen needs it

  const keyLight = new BABYLON.DirectionalLight(
    "keyLight",
    new BABYLON.Vector3(-0.55, -1, 0.45),
    scene
  );
  keyLight.position = new BABYLON.Vector3(4, 6, 4);
  keyLight.intensity = 1.1;
  keyLight.specular = new BABYLON.Color3(0, 0, 0); // shine comes from the material

  const imageProcessing = scene.imageProcessingConfiguration;
  imageProcessing.toneMappingEnabled = true;
  imageProcessing.toneMappingType =
    BABYLON.ImageProcessingConfiguration.TONEMAPPING_KHR_PBR_NEUTRAL; // not ACES: keeps greens in gamut
  imageProcessing.exposure = 1.15;

  // Idle auto-rotate
  let userInteracting = false;
  canvas.addEventListener("pointerdown", () => { userInteracting = true; });
  scene.onBeforeRenderObservable.add(() => {
    if (!userInteracting) {
      camera.alpha += 0.0015;
    }
  });

  // UVs are the garment's flat sewing pattern in MILLIMETRES; these map them
  // to 0..1. Regenerate with tools/extract_pattern.py. uScale is POSITIVE —
  // if the print ever looks mirrored, see docs/decisions.md before touching it.
  const PANELS = {
    front: {
      node: "Body_Front_Node_4",
      texture: "textures/print-front.png",
      // pattern piece 511.63 x 703.22 mm
      uScale: 0.00195454, uOffset: 0.50000844,
      vScale: 0.00142203, vOffset: 0.57734550,
    },
    back: {
      node: "Body_Back_Node_5",
      texture: "textures/print-back.png",
      // pattern piece 511.54 x 729.04 mm
      uScale: 0.00195488, uOffset: 0.49999215,
      vScale: 0.00137167, vOffset: 0.52828288,
    },
    sleeve_r: {
      node: "Sleeves_Node_7", // world x<0, renders viewer's LEFT = wearer's RIGHT
      texture: "textures/print-sleeve_r.png",
      // pattern piece 397.13 x 204.03 mm - the striped sleeve
      uScale: 0.00251807, uOffset: 0.50000008,
      vScale: 0.00490134, vOffset: 0.49992072,
    },
    sleeve_l: {
      node: "Sleeves_Node_6", // world x>0, renders viewer's RIGHT = wearer's LEFT
      texture: "textures/print-sleeve_l.png",
      // pattern piece 397.13 x 204.03 mm - carries the SCARPA badge
      uScale: 0.00251807, uOffset: 0.49999992,
      vScale: 0.00490134, vOffset: 0.49992072,
    },
    collar_a: {
      node: "Ribbing_Node_2",
      texture: "textures/print-collar_a.png",
      // pattern piece 187.30 x 17.00 mm
      uScale: 0.00533901, uOffset: 0.50000000,
      vScale: 0.05882353, vOffset: 0.50000000,
    },
    collar_b: {
      node: "Ribbing_Node_3",
      texture: "textures/print-collar_b.png",
      // pattern piece 272.32 x 17.00 mm
      uScale: 0.00367209, uOffset: 0.50000000,
      vScale: 0.05882353, vOffset: 0.50000000,
    },
  };

  const KNIT_TILE_MM = 15.0; // must match tools/make_weave_normal.py

  function makePanelMaterial(name, panel) {
    const mat = new BABYLON.PBRMaterial(name + "Mat", scene);

    const url = ASSET_ROOT + panel.texture;
    // 3rd arg noMipmap=false, 4th invertY=FALSE — glTF UVs need it; the
    // constructor defaults to true and would flip every print upside down.
    const albedo = new BABYLON.Texture(url, scene, false, false, undefined, null, (message, exception) => {
      // Without this a failed load is silent: Babylon substitutes a red/black
      // checkerboard and the shirt just renders bright red.
      console.error(
        `[${name}] texture failed to load: ${url}\n` +
          "The shirt will render with Babylon's red/black fallback checkerboard.\n" +
          (message || exception || "")
      );
    });
    albedo.uScale = panel.uScale;
    albedo.uOffset = panel.uOffset;
    albedo.vScale = panel.vScale;
    albedo.vOffset = panel.vOffset;
    albedo.wrapU = BABYLON.Texture.CLAMP_ADDRESSMODE; // rim meshes overshoot 0..1 slightly
    albedo.wrapV = BABYLON.Texture.CLAMP_ADDRESSMODE;
    mat.albedoTexture = albedo;

    const knit = new BABYLON.Texture(ASSET_ROOT + "textures/knit-normal.png", scene, false, false);
    knit.uScale = 1 / KNIT_TILE_MM; // UVs are mm, so this repeats every 15mm of real fabric
    knit.vScale = 1 / KNIT_TILE_MM;
    knit.wrapU = BABYLON.Texture.WRAP_ADDRESSMODE; // unlike the print, this tiles
    knit.wrapV = BABYLON.Texture.WRAP_ADDRESSMODE;
    knit.gammaSpace = false; // direction data, not colour
    mat.bumpTexture = knit;
    mat.bumpTexture.level = 0.45; // 0.16mm relief; grain, not visible bumps

    mat.metallic = 0.0;
    mat.roughness = 0.82; // matte technical jersey

    mat.sheen.isEnabled = true; // the fabric lobe — the reason for PBR
    mat.sheen.intensity = 0.4;
    mat.sheen.roughness = 0.3;
    mat.sheen.color = new BABYLON.Color3(1, 1, 1);
    mat.sheen.albedoScaling = true; // takes sheen energy out of the base layer

    return mat;
  }

  try {
    const result = await BABYLON.SceneLoader.ImportMeshAsync("", ASSET_ROOT, "tshirt.glb", scene);

    console.log(
      "Loaded meshes:",
      result.meshes.map((m) => m.name)
    );

    // Group by glTF PARENT node name — the only reliable identifier. Vertex
    // count and world-X sign have both picked the wrong mesh before.
    const byNode = new Map();
    result.meshes.forEach((m) => {
      const parent = m.parent && m.parent.name;
      if (!parent) return;
      if (!byNode.has(parent)) byNode.set(parent, []);
      byNode.get(parent).push(m);
    });

    // Fallback for anything with no pattern data. PBR so it sits under the
    // same environment light rather than reading as a flat grey patch.
    const baseMat = new BABYLON.PBRMaterial("baseMat", scene);
    baseMat.albedoColor = new BABYLON.Color3(0.95, 0.95, 0.95);
    baseMat.metallic = 0.0;
    baseMat.roughness = 0.82;
    result.meshes.forEach((m) => {
      if (m.material) m.material = baseMat;
    });

    Object.entries(PANELS).forEach(([name, panel]) => {
      const group = byNode.get(panel.node);
      if (!group || !group.length) {
        console.warn("no meshes found under node", panel.node, "for panel", name);
        return;
      }
      const mat = makePanelMaterial(name, panel);
      // Whole group shares the panel's UVs: outer shell, inner shell, rim.
      group.forEach((m) => { m.material = mat; });
    });

    const frontGroup = byNode.get(PANELS.front.node) || [];
    const shirtBounds = (frontGroup[0] || result.meshes[0]).getBoundingInfo().boundingBox;

    // Re-frame the camera on the actual model size.
    const radius = shirtBounds.extendSizeWorld.length() * 2.2;
    camera.setTarget(shirtBounds.centerWorld);
    camera.radius = radius;
    camera.lowerRadiusLimit = radius * 0.5;
    camera.upperRadiusLimit = radius * 2;
  } catch (err) {
    console.error("Failed to load tshirt.glb:", err);
  }

  return scene;
};
