#!/usr/bin/env python3
"""Software-render the textured shirt, so texture mapping can be checked here.

The point of this tool is a tight feedback loop: bake a pattern-space texture,
render it onto the real mesh, look at the result -- without a browser, a
screenshot, or a round trip through the user. It is not trying to look like the
Babylon scene, only to be *geometrically* faithful, so that what it says about
orientation, mirroring and panel coverage is trustworthy.

It deliberately reproduces two Babylon conventions so its answers transfer:

  * a left-handed basis, where screen-right is cross(forward, up). With an
    ArcRotateCamera at alpha=pi/2 that puts world +X on the viewer's RIGHT,
    which is the WEARER'S LEFT.
  * millimetre pattern UVs normalised per panel exactly the way panels.json
    says Babylon should do it via uScale/uOffset.

Trust it only so far. It had the handedness backwards once, which mirrored
every render and led to a negative uScale being written into the scene to
correct a mirror that was not there. Confirm anything load-bearing in a browser.

Usage:
  python3 tools/preview_render.py --textures calib      # calib-<panel>.png
  python3 tools/preview_render.py --textures print --view three-quarter
  python3 tools/preview_render.py --textures calib --view front --flip-v
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from glb import Glb

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "pipeline-design" / "pattern"
TEXDIR = ROOT / "assets" / "textures"

def outer_node_map(panels):
    """node name -> panel name, for the one shell per panel that gets a print.

    Read from panels.json rather than hardcoded. It used to be a second copy of
    the mapping here, which silently went stale the moment the sleeve nodes were
    swapped at their real source in tools/extract_pattern.py -- the textures were
    corrected but this tool kept rendering the old pairing.

    Only the outer shell is drawn. A body panel is three meshes (outer shell,
    inner shell 0.5mm behind with flipped normals, and the rim joining them);
    drawing the inner one would just z-fight, and the real garment's inside face
    is blank anyway.
    """
    return {info["outer_node"]: name for name, info in panels.items()}

# Named from the WEARER's point of view, like every other name in this project.
# "left" is the wearer's left sleeve, which is world +X and renders on the
# viewer's right.
VIEWS = {
    "front": (0.0, 0.0, 1.0),
    "back": (0.0, 0.0, -1.0),
    "left": (1.0, 0.0, 0.0),
    "right": (-1.0, 0.0, 0.0),
    "three-quarter": (0.62, 0.10, 0.78),
    # Down onto the shoulders, tilted forward. Not straight down: a camera
    # directly overhead has its forward parallel to up and the basis degenerates.
    "top": (0.05, 1.0, 0.42),
    # Approximates assets/reference-3d-mockup.png: mostly front-on with a slight
    # turn, shot on a long lens so the silhouette stays close to orthographic.
    "reference": (0.30, 0.05, 0.95),
}

# (distance in bounding-sphere radii, vertical FOV in degrees) per view
FRAMING = {"reference": (7.0, 12.0)}
DEFAULT_FRAMING = (3.0, 28.0)


def look_at_lh(eye, target, up=(0.0, 1.0, 0.0)):
    """Babylon's left-handed camera basis.

    screen-right = forward x up. With a camera on +Z looking back at the origin
    that gives (+1,0,0), i.e. world +X lands on the VIEWER'S RIGHT.

    This was cross(up, forward) — the other handedness — and every conclusion
    drawn from this tool came out mirrored as a result. The calibration pass
    read the mirror, concluded the front panel needed flipping, and a negative
    uScale went into the scene to correct a mirror that did not exist. Verified
    now against a real Babylon screenshot rather than re-derived, because
    deriving it is exactly what went wrong.
    """
    f = np.array(target, dtype=float) - np.array(eye, dtype=float)
    f /= np.linalg.norm(f)
    up = np.array(up, dtype=float)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return r, u, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--textures", default="calib", help="texture prefix in assets/textures, e.g. 'calib' or 'print'")
    ap.add_argument("--view", default="front", choices=list(VIEWS))
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--flip-v", action="store_true", help="sample the texture with V inverted")
    ap.add_argument("--mirror-u", action="store_true", help="sample the texture with U mirrored")
    ap.add_argument(
        "--cull",
        default="ccw",
        choices=["cw", "ccw", "none"],
        # The screen-space signed area changes sign with the corrected camera
        # basis, so this default flipped back too. Needing to override it is a
        # signal that the basis is wrong again, not that the model changed.
        help="which screen-space winding to treat as front-facing",
    )
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    panels = json.loads((PATTERN / "panels.json").read_text())["panels"]
    node_to_panel = outer_node_map(panels)
    glb = Glb(ROOT / "assets" / "tshirt.glb")
    meshes = [m for m in glb.meshes() if m["node"] in node_to_panel]

    textures = {}
    for node, panel in node_to_panel.items():
        p = TEXDIR / f"{args.textures}-{panel}.png"
        if p.exists():
            textures[panel] = np.asarray(Image.open(p).convert("RGB"), dtype=np.float64) / 255.0
    if not textures:
        raise SystemExit(f"no textures matching {args.textures}-*.png in {TEXDIR}")

    allpos = np.vstack([m["pos"] for m in meshes])
    centre = (allpos.min(0) + allpos.max(0)) / 2
    radius = np.linalg.norm(allpos.max(0) - allpos.min(0)) / 2

    dist_r, fov_deg = FRAMING.get(args.view, DEFAULT_FRAMING)
    d = np.array(VIEWS[args.view], dtype=float)
    d /= np.linalg.norm(d)
    eye = centre + d * radius * dist_r
    right, up, fwd = look_at_lh(eye, centre)

    W = H = args.size
    fov = np.deg2rad(fov_deg)
    focal = (H / 2) / np.tan(fov / 2)

    colour = np.zeros((H, W, 3))
    colour[:] = (0.09, 0.09, 0.10)
    zbuf = np.full((H, W), np.inf)

    # two soft keys plus ambient; enough shaping to read form, flat enough that
    # the texture itself stays legible
    lights = [(np.array([-0.6, 0.7, 0.8]), 0.55), (np.array([0.7, 0.4, -0.5]), 0.30)]
    lights = [(v / np.linalg.norm(v), i) for v, i in lights]
    ambient = 0.42

    for m in meshes:
        panel = node_to_panel[m["node"]]
        tex = textures.get(panel)
        if tex is None:
            continue
        pm = panels[panel]["pattern_mm"]

        rel = m["pos"] - eye
        cx = rel @ right
        cy = rel @ up
        cz = rel @ fwd
        sx = W / 2 + focal * cx / np.maximum(cz, 1e-6)
        sy = H / 2 - focal * cy / np.maximum(cz, 1e-6)

        uvn = np.empty_like(m["uv"])
        uvn[:, 0] = (m["uv"][:, 0] - pm["u0"]) / pm["width"]
        uvn[:, 1] = (m["uv"][:, 1] - pm["v0"]) / pm["height"]
        if args.mirror_u:
            uvn[:, 0] = 1.0 - uvn[:, 0]
        if args.flip_v:
            uvn[:, 1] = 1.0 - uvn[:, 1]

        th, tw = tex.shape[0], tex.shape[1]
        shade = ambient + sum(i * np.clip(m["nrm"] @ v, 0, None) for v, i in lights)
        shade = np.clip(shade, 0, 1.25)

        tri = m["idx"]
        ax, ay, az = sx[tri[:, 0]], sy[tri[:, 0]], cz[tri[:, 0]]
        bx, by, bz = sx[tri[:, 1]], sy[tri[:, 1]], cz[tri[:, 1]]
        gx, gy, gz = sx[tri[:, 2]], sy[tri[:, 2]], cz[tri[:, 2]]
        area = (bx - ax) * (gy - ay) - (by - ay) * (gx - ax)

        visible = (az > 0) & (bz > 0) & (gz > 0)
        if args.cull == "cw":
            keep = (area > 1e-9) & visible
        elif args.cull == "ccw":
            keep = (area < -1e-9) & visible
        else:
            keep = (np.abs(area) > 1e-9) & visible
        idx = np.nonzero(keep)[0]

        for t in idx:
            x0 = max(int(np.floor(min(ax[t], bx[t], gx[t]))), 0)
            x1 = min(int(np.ceil(max(ax[t], bx[t], gx[t]))) + 1, W)
            y0 = max(int(np.floor(min(ay[t], by[t], gy[t]))), 0)
            y1 = min(int(np.ceil(max(ay[t], by[t], gy[t]))) + 1, H)
            if x0 >= x1 or y0 >= y1:
                continue
            px, py = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
            inv = 1.0 / area[t]
            w0 = ((bx[t] - px) * (gy[t] - py) - (by[t] - py) * (gx[t] - px)) * inv
            w1 = ((gx[t] - px) * (ay[t] - py) - (gy[t] - py) * (ax[t] - px)) * inv
            w2 = 1.0 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            i0, i1, i2 = tri[t]
            z = w0 * az[t] + w1 * bz[t] + w2 * gz[t]
            sub = zbuf[y0:y1, x0:x1]
            better = inside & (z < sub)
            if not better.any():
                continue
            u = w0 * uvn[i0, 0] + w1 * uvn[i1, 0] + w2 * uvn[i2, 0]
            v = w0 * uvn[i0, 1] + w1 * uvn[i1, 1] + w2 * uvn[i2, 1]
            tx = np.clip((u * (tw - 1)).astype(np.int32), 0, tw - 1)
            ty = np.clip((v * (th - 1)).astype(np.int32), 0, th - 1)
            sh = w0 * shade[i0] + w1 * shade[i1] + w2 * shade[i2]
            rgb = tex[ty, tx] * sh[..., None]
            dst = colour[y0:y1, x0:x1]
            dst[better] = np.clip(rgb[better], 0, 1)
            sub[better] = z[better]

    out = args.out or str(ROOT / "pipeline-design" / "preview" / f"{args.textures}-{args.view}.png")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((colour * 255).astype(np.uint8)).save(out)
    print(f"wrote {out}   view={args.view} flip_v={args.flip_v} mirror_u={args.mirror_u}")


if __name__ == "__main__":
    main()
