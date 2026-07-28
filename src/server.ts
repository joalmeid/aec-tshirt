import { join, sep } from "node:path";
import index from "./index.html";

// Matches Babylon's own convention (see doc.babylonjs.com/guidedLearning/usingVite,
// which uses a "public/" folder the same way): only the runtime-fetched asset
// folder is served, not the whole project root — so pipeline-design/ (PSDs,
// reference images) and .git stay unreachable even locally.
const assetsRoot = join(import.meta.dir, "..", "assets");

const server = Bun.serve({
  routes: {
    "/": index,
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
