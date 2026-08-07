// The production embed's entire runtime.
//
// `import "@babylonjs/viewer"` registers the <babylon-viewer> custom element.
// Bun bundles this module and the viewer's dependency graph into the page, so
// nothing is fetched from cdn.babylonjs.com -- which is what
// docs/production-delivery.md section 5 requires, quoting Babylon's own docs:
// "The CDN should not be used in production environments."
//
// The viewer imports its glTF loader and each glTF extension dynamically, so a
// visitor downloads the sheen extension this shirt uses and not the Draco,
// KTX2 or FBX code it does not.
import "@babylonjs/viewer";
import { DirectionalLight } from "@babylonjs/core/Lights/directionalLight.js";
import { Vector3 } from "@babylonjs/core/Maths/math.vector.js";
import { Color3 } from "@babylonjs/core/Maths/math.color.js";

const viewer = document.querySelector("babylon-viewer");
const statusEl = document.getElementById("status");

// --- What still has to be said in code ------------------------------------
//
// The element's attributes cover the environment, the tone mapper and the
// auto-orbit. Two things have no attribute and are set here instead, through
// the documented `viewerDetails` escape hatch. Both are row-two items from
// production-delivery.md section 2: scene configuration glTF cannot carry and
// every viewer has to supply for itself.
viewer.addEventListener("viewerready", () => {
  const details = viewer.viewerDetails;
  if (!details) return;

  // 1. Exposure. Not the certification's business -- KHR PBR Neutral is the
  //    certified tone mapper and the viewer already defaults to it -- but 1.15
  //    is this event's own grade, carried over from
  //    index-model-validation.html so both pages render the same shirt. A
  //    partner site at the default 1.0 gets a slightly darker one, section 4.
  viewer.exposure = 1.15;

  // 2. The key light. The viewer lights from the environment alone, so this
  //    adds the shaping light the validation page uses, with specular off so
  //    the shine keeps coming from the material's sheen lobe rather than from a
  //    second highlight.
  const { scene, camera } = details;
  const keyLight = new DirectionalLight("keyLight", new Vector3(-0.55, -1, 0.45), scene);
  keyLight.position = new Vector3(4, 6, 4);
  keyLight.intensity = 1.1;
  keyLight.specular = new Color3(0, 0, 0);

  // The viewer renders on demand rather than every frame (autoSuspendRendering,
  // on by default) so a scene change made from outside it has to say so.
  details.markSceneMutated();

  // Framing is the viewer's own job now -- the validation page's 1.8x
  // half-diagonal calculation is gone with it. Only the pole limits are kept:
  // straight-down and straight-up views of a garment are neither useful nor
  // flattering.
  camera.lowerBetaLimit = 0.3;
  camera.upperBetaLimit = Math.PI - 0.3;
});

viewer.addEventListener("modelchange", () => {
  statusEl.hidden = true;
});

viewer.addEventListener("modelerror", (event) => {
  console.error("Failed to load the shirt:", event);
  statusEl.textContent = "Erro ao carregar o modelo 3D.";
});

// The environment loads separately from the model and fails separately. Not
// fatal -- the shirt still renders, just with nothing for the sheen lobe to
// reflect, which reads as "the fabric went flat" rather than as an error.
viewer.addEventListener("environmenterror", (event) => {
  console.error("Failed to load studio.env:", event);
});
