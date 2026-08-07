import { join, sep } from "node:path";
import index from "./index.html";
import indexProd from "./index-prod.html";
import indexModelValidation from "./index-model-validation.html";

// Matches Babylon's own convention (see doc.babylonjs.com/guidedLearning/usingVite,
// which uses a "public/" folder the same way): only the runtime-fetched asset
// folder is served, not the whole project root — so pipeline-design/ (PSDs,
// reference images) and .git stay unreachable even locally.
const assetsRoot = join(import.meta.dir, "..", "assets");

const server = Bun.serve({
  routes: {
    "/": index,

    // The shipping arrangement: Babylon Viewer v2, imported from npm rather
    // than a CDN, pointed at the baked model. This is what a site embedding
    // the shirt should copy — see docs/production-delivery.md section 6.
    "/prod": indexProd,

    // The acceptance test for the bake, and the reason it hand-builds an
    // Engine and a Scene: it reads the loaded materials back to prove the .glb
    // carries its own appearance, which a viewer that just renders it cannot
    // tell you. ?calib swaps in the millimetre-grid model, ?debug shows the
    // badge on a passing build, ?inspect opens the Babylon inspector.
    "/model-validation": indexModelValidation,
  },

  // Re-bundles on each request and enables the injected HMR websocket;
  // saving index.html (or any file in its <script>/<link> graph) triggers
  // an automatic browser reload. Static assets fetched at runtime (glTF,
  // PNGs under assets/) aren't part of that graph — the fetch fallback
  // below serves them, but editing one only refreshes on your next
  // manual reload or the next HTML/script save.
  development: {
    hmr: true,
    console: true,
  },

  async fetch(req) {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/assets/")) {
      return new Response("Not Found", { status: 404 });
    }

    const filePath = join(assetsRoot, url.pathname.slice("/assets/".length));
    // join() already resolves ".." segments; this just confirms the result
    // didn't escape assetsRoot before reading from disk.
    if (!(filePath + sep).startsWith(assetsRoot + sep)) {
      return new Response("Forbidden", { status: 403 });
    }

    const file = Bun.file(filePath);
    if (await file.exists()) {
      return new Response(file);
    }
    return new Response("Not Found", { status: 404 });
  },
});

console.log(`AEC t-shirt 3D preview running at ${server.url}`);
