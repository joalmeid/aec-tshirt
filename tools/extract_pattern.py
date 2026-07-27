#!/usr/bin/env python3
"""Extract the flat sewing-pattern UV layout from assets/tshirt.glb.

This model comes out of Marvelous Designer / CLO3D, which writes UVs as the
garment's real 2D pattern pieces measured in MILLIMETRES (positions are in
metres, so the ratio uvArea/3dArea comes out at a constant ~1000). That makes
UV space directly usable as a print-layout coordinate system: a point at
(120mm, 215mm) in the front panel's texture lands on exactly that spot of the
physical panel, and the panel's own UV island boundary is the neckline /
armhole / shoulder / hem.

Outputs to source/pattern/:
  panels.json          per-panel mm extents + the Babylon uScale/uOffset needed
                       to map those mm UVs into 0..1 texture space
  <panel>-mask.png     island coverage at PX_PER_MM, for eyeballing placement
  <panel>-guide.png    the same with a 10/50mm grid and landmark annotations

Run:  python3 tools/extract_pattern.py
"""

import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
GLB = ROOT / "assets" / "tshirt.glb"
OUT = ROOT / "source" / "pattern"

PX_PER_MM = 4  # only for the human-facing guide images, not the final textures

# Which glTF node parent groups make up each logical panel. Discovered by
# reading the .glb's own node names -- do NOT infer these from vertex counts or
# camera-relative position, both of which have silently picked the wrong mesh
# here before (the back panel has more vertices than the front).
PANEL_GROUPS = {
    "front": "Body_Front_Node_4",
    "back": "Body_Back_Node_5",
    "sleeve_r": "Sleeves_Node_6",  # world x > 0
    "sleeve_l": "Sleeves_Node_7",  # world x < 0
    "collar_a": "Ribbing_Node_2",
    "collar_b": "Ribbing_Node_3",
}

COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
NPDTYPE = {"f": np.float32, "H": np.uint16, "I": np.uint32, "B": np.uint8, "h": np.int16, "b": np.int8}


def load_glb(path):
    data = path.read_bytes()
    total = struct.unpack("<III", data[:12])[2]
    offset, chunks = 12, []
    while offset < total:
        clen, ctype = struct.unpack("<II", data[offset : offset + 8])
        chunks.append((ctype, offset + 8, clen))
        offset += 8 + clen
    gltf = json.loads(data[chunks[0][1] : chunks[0][1] + chunks[0][2]].decode("utf-8"))
    binary = data[chunks[1][1] : chunks[1][1] + chunks[1][2]]
    return gltf, binary


def accessor(gltf, binary, index):
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    fmt, size = COMPONENT[acc["componentType"]]
    n = NCOMP[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or size * n
    if stride == size * n:
        return np.frombuffer(binary, dtype=NPDTYPE[fmt], count=acc["count"] * n, offset=start).reshape(acc["count"], n)
    out = np.zeros((acc["count"], n), dtype=NPDTYPE[fmt])
    for k in range(acc["count"]):
        out[k] = struct.unpack_from("<" + fmt * n, binary, start + k * stride)
    return out


def mesh_index_by_parent(gltf):
    """Map parent-node name -> [(mesh index, child node name), ...]."""
    parent_of = {}
    for i, node in enumerate(gltf["nodes"]):
        for c in node.get("children", []):
            parent_of[c] = i
    groups = {}
    for i, node in enumerate(gltf["nodes"]):
        if node.get("mesh") is None:
            continue
        pi = parent_of.get(i)
        pname = gltf["nodes"][pi].get("name", "?") if pi is not None else "?"
        groups.setdefault(pname, []).append((node["mesh"], node.get("name", "?")))
    return groups


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gltf, binary = load_glb(GLB)
    groups = mesh_index_by_parent(gltf)

    panels = {}
    for panel, parent_name in PANEL_GROUPS.items():
        members = groups.get(parent_name)
        if not members:
            print(f"!! no meshes under {parent_name}")
            continue

        parts = []
        for mesh_i, node_name in members:
            prim = gltf["meshes"][mesh_i]["primitives"][0]
            uv = accessor(gltf, binary, prim["attributes"]["TEXCOORD_0"]).astype(np.float64)
            pos = accessor(gltf, binary, prim["attributes"]["POSITION"]).astype(np.float64)
            nrm = accessor(gltf, binary, prim["attributes"]["NORMAL"]).astype(np.float64)
            idx = accessor(gltf, binary, prim["indices"]).astype(np.int64).ravel().reshape(-1, 3)
            parts.append(dict(mesh=mesh_i, node=node_name, uv=uv, pos=pos, nrm=nrm, idx=idx))

        # The outer shell is the largest part; MD exports cloth with thickness,
        # so a body panel is outer shell + inner shell (0.5mm behind, normals
        # flipped) + a thin rim band joining them. Size the pattern box from the
        # outer shell and reuse it for every part in the group, so the inner
        # shell and rim stay in register with the print instead of each getting
        # its own slightly different normalisation.
        outer = max(parts, key=lambda p: len(p["uv"]))
        u0, u1 = outer["uv"][:, 0].min(), outer["uv"][:, 0].max()
        v0, v1 = outer["uv"][:, 1].min(), outer["uv"][:, 1].max()
        w, h = u1 - u0, v1 - v0

        # Distortion / texel-density uniformity. sqrt(uvArea/3dArea) should be
        # near-constant if the unwrap is a true flat pattern; the ratio between
        # the 95th and 5th percentile is the practical "how much does a texture
        # stretch anywhere on this panel" number.
        t = outer["idx"]
        uv, pos = outer["uv"], outer["pos"]
        a2, b2 = uv[t[:, 1]] - uv[t[:, 0]], uv[t[:, 2]] - uv[t[:, 0]]
        area_uv = 0.5 * np.abs(a2[:, 0] * b2[:, 1] - a2[:, 1] * b2[:, 0])
        a3, b3 = pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]]
        area_3d = 0.5 * np.linalg.norm(np.cross(a3, b3), axis=1)
        ok = (area_3d > 1e-12) & (area_uv > 1e-14)
        density = np.sqrt(area_uv[ok] / area_3d[ok])
        p5, p50, p95 = np.percentile(density, [5, 50, 95])

        # Orientation: how pattern axes relate to world axes. Sign of the
        # u<->X correlation is what decides whether the texture reads mirrored
        # when the panel is viewed from outside -- recorded here so the runtime
        # can flip deliberately instead of by trial and error.
        corr = lambda a, b: float(np.corrcoef(a, b)[0, 1])
        orient = dict(
            u_vs_x=corr(uv[:, 0], pos[:, 0]),
            u_vs_z=corr(uv[:, 0], pos[:, 2]),
            v_vs_y=corr(uv[:, 1], pos[:, 1]),
        )

        panels[panel] = dict(
            parent_node=parent_name,
            meshes=[dict(mesh=p["mesh"], node=p["node"], vertices=len(p["uv"])) for p in parts],
            outer_node=outer["node"],
            pattern_mm=dict(u0=u0, v0=v0, u1=u1, v1=v1, width=w, height=h, aspect=w / h),
            # Babylon Texture applies uv' = uv * scale + offset. These map the
            # raw millimetre UVs onto 0..1 so an ordinary texture just works.
            babylon=dict(uScale=1.0 / w, uOffset=-u0 / w, vScale=1.0 / h, vOffset=-v0 / h),
            texel_density=dict(p5=p5, p50=p50, p95=p95, ratio=p95 / p5),
            orientation=orient,
        )

        # --- guide image -------------------------------------------------
        wpx, hpx = int(round(w * PX_PER_MM)), int(round(h * PX_PER_MM))
        mask = Image.new("L", (wpx, hpx), 0)
        md = ImageDraw.Draw(mask)
        for tri in outer["idx"]:
            md.polygon([((uv[i, 0] - u0) * PX_PER_MM, (uv[i, 1] - v0) * PX_PER_MM) for i in tri], fill=255)
        mask.save(OUT / f"{panel}-mask.png")

        guide = Image.new("RGB", (wpx, hpx), (24, 24, 28))
        arr = np.array(mask) > 0
        rgb = np.array(guide)
        rgb[arr] = (238, 238, 240)
        guide = Image.fromarray(rgb)
        gd = ImageDraw.Draw(guide)
        for mm in range(0, int(w) + 1, 10):
            x = mm * PX_PER_MM
            gd.line([(x, 0), (x, hpx)], fill=(150, 170, 200) if mm % 50 else (70, 130, 220), width=1)
        for mm in range(0, int(h) + 1, 10):
            y = mm * PX_PER_MM
            gd.line([(0, y), (wpx, y)], fill=(150, 170, 200) if mm % 50 else (70, 130, 220), width=1)
        for mm in range(0, int(w) + 1, 50):
            gd.text((mm * PX_PER_MM + 3, 3), str(mm), fill=(220, 60, 60))
        for mm in range(50, int(h) + 1, 50):
            gd.text((3, mm * PX_PER_MM + 3), str(mm), fill=(220, 60, 60))
        gd.text((6, hpx - 18), f"{panel}  {w:.1f} x {h:.1f} mm  (0,0 = top-left of pattern box)", fill=(255, 200, 0))
        guide.save(OUT / f"{panel}-guide.png")

        print(
            f"{panel:9s} {parent_name:20s} {w:7.2f} x {h:7.2f} mm  aspect {w/h:.4f}  "
            f"density p5/p50/p95 {p5:.0f}/{p50:.0f}/{p95:.0f} (ratio {p95/p5:.3f})  "
            f"parts {[p['node'] for p in parts]}"
        )

    # Row profile of the front panel: where the neckline, armholes and full-width
    # body actually start, in mm. This is the print-safe-area spec.
    prof = {}
    for panel in ("front", "back", "sleeve_r"):
        if panel not in panels:
            continue
        m = np.array(Image.open(OUT / f"{panel}-mask.png")) > 0
        rows = {}
        for ymm in range(0, int(panels[panel]["pattern_mm"]["height"]), 10):
            r = int(ymm * PX_PER_MM)
            if r >= m.shape[0]:
                break
            cols = np.where(m[r])[0]
            if len(cols) == 0:
                rows[ymm] = []
                continue
            runs, start, prev = [], cols[0], cols[0]
            for c in cols[1:]:
                if c != prev + 1:
                    runs.append([round(start / PX_PER_MM, 1), round(prev / PX_PER_MM, 1)])
                    start = c
                prev = c
            runs.append([round(start / PX_PER_MM, 1), round(prev / PX_PER_MM, 1)])
            rows[ymm] = runs
        prof[panel] = rows

    (OUT / "panels.json").write_text(json.dumps(dict(panels=panels, row_profile_mm=prof), indent=2))
    print(f"\nwrote {OUT/'panels.json'} and per-panel mask/guide PNGs")


if __name__ == "__main__":
    main()
