#!/usr/bin/env python3
"""Bake the runtime's per-panel texturing into a single self-contained .glb.

assets/tshirt.glb is geometry only: no images, no textures, six primitives'
worth of UVs in raw pattern millimetres, and two placeholder materials. Every
visual property lives in src/index.html — the per-panel uScale/uOffset that maps
mm UVs into 0..1, the knit normal tiled at 1/15mm, CLAMP vs WRAP, invertY=false,
and the PBR + sheen values. Anything that loads the model without running that
file gets an untextured shirt.

This produces assets/tshirt-prod.glb, where all of that is *in the file*:

  TEXCOORD_0   rewritten to uv*scale + offset, so it lands in 0..1 already.
               No texture transform at runtime, and no KHR_texture_transform
               either — baking into the attribute needs no extension at all,
               so the result renders the same in Babylon, three.js,
               <model-viewer>, Blender and the Khronos validator.
  TEXCOORD_1   the same UVs divided by TILE_MM, which is what the knit normal
               map needs. Baking TEXCOORD_0 destroys the millimetre UVs the
               weave tiling was reading, so it gets its own set. Core glTF,
               no extension.
  TANGENT      generated. The .glb ships none, so Babylon derives a tangent
               frame per-pixel from screen-space derivatives — fine in Babylon,
               but the Khronos validator flags it as non-portable, and "renders
               the same everywhere" is the entire point of this file. Cheap to
               do properly here: the unwrap is a real flat pattern with under
               4% stretch, so the pattern-space tangent IS the surface tangent.
  images       the six print PNGs plus knit-normal.png, embedded.
  samplers     CLAMP_TO_EDGE for the prints (the 0.5mm rim meshes overshoot
               0..1 a hair and must take the edge colour, not wrap around),
               REPEAT for the knit.
  materials    one per panel, metallic/roughness plus KHR_materials_sheen.

Two things deliberately do NOT go in, because glTF has nowhere to put them:
the IBL environment and the tone mapping. See docs/production-delivery.md.

Compression is a separate step and not done here — this tool stays
dependency-free like the rest of tools/, and KTX2/Draco need external binaries.
The command to run next is printed at the end.

Run:  python3 tools/build_production_glb.py
      python3 tools/build_production_glb.py --textures calib   # the check build
"""

import argparse
import json
import struct
from pathlib import Path

import numpy as np

from extract_pattern import PANEL_GROUPS
from make_weave_normal import TILE_MM

ROOT = Path(__file__).resolve().parent.parent
GLB_IN = ROOT / "assets" / "tshirt.glb"
PANELS_JSON = ROOT / "pipeline-design" / "pattern" / "panels.json"
TEXTURES = ROOT / "assets" / "textures"

# Mirrors makePanelMaterial() in src/index.html. If a value changes there it
# must change here, and the browser is the arbiter — preview_render.py is a
# Lambert rasteriser and cannot judge any of this.
ROUGHNESS = 0.82  # matte technical jersey
METALLIC = 0.0
NORMAL_SCALE = 0.45  # index.html's bumpTexture.level
SHEEN_INTENSITY = 0.4
SHEEN_ROUGHNESS = 0.3

# glTF enums, spelled out because the numbers are unreadable.
CLAMP_TO_EDGE, REPEAT = 33071, 10497
LINEAR, LINEAR_MIPMAP_LINEAR = 9729, 9987
ARRAY_BUFFER = 34962
FLOAT, VEC2 = 5126, "VEC2"


def read_glb(path):
    data = path.read_bytes()
    total = struct.unpack("<III", data[:12])[2]
    offset, chunks = 12, []
    while offset < total:
        clen, ctype = struct.unpack("<II", data[offset : offset + 8])
        chunks.append((ctype, offset + 8, clen))
        offset += 8 + clen
    gltf = json.loads(data[chunks[0][1] : chunks[0][1] + chunks[0][2]].decode("utf-8"))
    return gltf, data[chunks[1][1] : chunks[1][1] + chunks[1][2]]


def write_glb(path, gltf, binary):
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)  # JSON chunk pads with spaces, BIN with zeros
    binary += b"\x00" * (-len(binary) % 4)
    header = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary))
    path.write_bytes(
        header
        + struct.pack("<II", len(js), 0x4E4F534A)
        + js
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def read_accessor(gltf, binary, index):
    """Non-sparse, non-interleaved accessor -> (count, n) float64/int64 array."""
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    fmt = {5125: np.uint32, 5126: np.float32}[acc["componentType"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or np.dtype(fmt).itemsize * n
    if stride != np.dtype(fmt).itemsize * n:
        raise SystemExit(f"accessor {index} is interleaved; this tool assumes tight packing")
    return np.frombuffer(binary, dtype=fmt, count=acc["count"] * n, offset=start).reshape(acc["count"], n)


def tangents(pos, nrm, uv, tri):
    """Per-vertex glTF TANGENT (vec4, w = bitangent sign) for one primitive.

    The textbook per-triangle tangent, area-weighted by accumulation and then
    Gram-Schmidt'd against the vertex normal. On a general model this is the
    approximation MikkTSpace exists to improve on; here it is very close to
    exact, because the UVs are the flat sewing pattern and sqrt(uvArea/3dArea)
    varies by under 4% across every panel — a near-isometric unwrap has a
    genuine tangent frame to find, not a least-bad compromise.

    Computed from the MILLIMETRE UVs, which is the set the knit normal map
    samples through (TEXCOORD_1 is just those over TILE_MM, a uniform scale, so
    the direction is identical). Deliberately not from the baked TEXCOORD_0:
    that one has a different u and v scale per panel, which would skew the
    frame relative to the map actually being sampled.
    """
    e1, e2 = pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]]
    d1, d2 = uv[tri[:, 1]] - uv[tri[:, 0]], uv[tri[:, 2]] - uv[tri[:, 0]]
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    # Degenerate UV triangles contribute nothing rather than infinity.
    r = np.where(np.abs(det) > 1e-20, 1.0 / np.where(det == 0, 1, det), 0.0)[:, None]
    t_face = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    b_face = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r

    acc_t = np.zeros_like(pos)
    acc_b = np.zeros_like(pos)
    for c in range(3):
        np.add.at(acc_t, tri[:, c], t_face)
        np.add.at(acc_b, tri[:, c], b_face)

    # Orthogonalise against the normal, then recover the handedness the shader
    # needs to rebuild the bitangent as w * cross(N, T).
    t = acc_t - nrm * np.sum(nrm * acc_t, axis=1, keepdims=True)
    norm = np.linalg.norm(t, axis=1, keepdims=True)
    fallback = np.abs(nrm[:, 0:1]) < 0.9
    alt = np.where(fallback, np.array([[0.0, 0.0, 1.0]]), np.array([[1.0, 0.0, 0.0]]))
    t = np.where(norm > 1e-12, t / np.maximum(norm, 1e-12), np.cross(nrm, alt))
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)

    w = np.where(np.sum(np.cross(nrm, t) * acc_b, axis=1) < 0.0, -1.0, 1.0)
    return np.hstack([t, w[:, None]]).astype(np.float32)


def primitives_by_parent(gltf):
    """parent-node name -> [(mesh index, primitive index), ...].

    Same rule as extract_pattern.py and the runtime: identify panels by their
    glTF PARENT node name and nothing else. Vertex count and world-X sign have
    both silently picked the wrong mesh in this project before.
    """
    parent_of = {}
    for i, node in enumerate(gltf["nodes"]):
        for c in node.get("children", []):
            parent_of[c] = i
    groups = {}
    for i, node in enumerate(gltf["nodes"]):
        if node.get("mesh") is None:
            continue
        pi = parent_of.get(i)
        name = gltf["nodes"][pi].get("name") if pi is not None else None
        for pj in range(len(gltf["meshes"][node["mesh"]]["primitives"])):
            groups.setdefault(name, []).append((node["mesh"], pj))
    return groups


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--textures",
        choices=("print", "calib"),
        default="print",
        help="print = the real design; calib = the millimetre-grid orientation "
        "textures, which is how you verify the bake did not flip or rescale "
        "anything (see docs/production-delivery.md)",
    )
    ap.add_argument(
        "--no-tangents",
        action="store_true",
        help="skip TANGENT generation. Saves ~2MB and Babylon will derive the "
        "frame itself, but the Khronos validator warns that a derived frame is "
        "not portable across viewers",
    )
    args = ap.parse_args()

    suffix = "" if args.textures == "print" else "-calib"
    out_path = ROOT / "assets" / f"tshirt-prod{suffix}.glb"

    gltf, old_bin = read_glb(GLB_IN)
    panels = json.loads(PANELS_JSON.read_text())["panels"]
    groups = primitives_by_parent(gltf)

    if len(gltf["bufferViews"]) != 3:
        raise SystemExit(
            f"expected the 3 bufferViews of the original export, found "
            f"{len(gltf['bufferViews'])}. This tool rewrites views by position; "
            "re-read it before running against a different model."
        )
    idx_view, uv_view, pos_view = gltf["bufferViews"]
    if uv_view.get("byteStride") != 8:
        raise SystemExit("the TEXCOORD_0 view is not tightly packed vec2; bake would corrupt it")

    # --- bake the UVs -------------------------------------------------------
    #
    # All ten primitives' TEXCOORD_0 accessors index into one shared view, so
    # the whole thing is read once, transformed per panel in place, and written
    # back at identical offsets. That is what lets every accessor keep its
    # byteOffset untouched, and lets TEXCOORD_1 be a byte-for-byte-shaped twin
    # of the view whose accessors differ only in which view they point at.
    n_uv = uv_view["byteLength"] // 8
    uv_mm = np.frombuffer(old_bin, np.float32, count=n_uv * 2, offset=uv_view.get("byteOffset", 0))
    uv_mm = uv_mm.reshape(n_uv, 2).astype(np.float64)
    uv_baked = np.zeros_like(uv_mm)
    covered = np.zeros(n_uv, bool)

    texcoord1_accessor = {}  # TEXCOORD_0 accessor index -> new TEXCOORD_1 accessor index
    material_of = {}  # (mesh, prim) -> material index
    tangent_parts = []  # (mesh, prim, float32 (n,4) array), concatenated into one view
    report = []

    for slot, (panel, parent_node) in enumerate(PANEL_GROUPS.items()):
        members = groups.get(parent_node)
        if not members:
            raise SystemExit(f"no primitives under {parent_node} for panel {panel}")
        if panel not in panels:
            raise SystemExit(f"{PANELS_JSON} has no entry for panel {panel}; rerun extract_pattern.py")
        b = panels[panel]["babylon"]

        for mesh_i, prim_j in members:
            prim = gltf["meshes"][mesh_i]["primitives"][prim_j]
            acc_i = prim["attributes"]["TEXCOORD_0"]
            acc = gltf["accessors"][acc_i]
            if acc["type"] != VEC2 or acc["componentType"] != FLOAT:
                raise SystemExit(f"accessor {acc_i} is not float vec2")
            start = acc.get("byteOffset", 0) // 8
            span = slice(start, start + acc["count"])
            if covered[span].any():
                raise SystemExit(f"vertices {span} claimed by two panels; node grouping is wrong")
            covered[span] = True

            # Exactly what Babylon's Texture does at runtime: uv' = uv*scale +
            # offset. panels.json is the single source of these numbers, so the
            # bake cannot drift from what extract_pattern.py measured.
            uv_baked[span, 0] = uv_mm[span, 0] * b["uScale"] + b["uOffset"]
            uv_baked[span, 1] = uv_mm[span, 1] * b["vScale"] + b["vOffset"]

            if not args.no_tangents:
                tangent_parts.append(
                    (
                        mesh_i,
                        prim_j,
                        tangents(
                            read_accessor(gltf, old_bin, prim["attributes"]["POSITION"]).astype(np.float64),
                            read_accessor(gltf, old_bin, prim["attributes"]["NORMAL"]).astype(np.float64),
                            uv_mm[span],
                            read_accessor(gltf, old_bin, prim["indices"]).astype(np.int64).reshape(-1, 3),
                        ),
                    )
                )

            material_of[(mesh_i, prim_j)] = slot
            texcoord1_accessor[acc_i] = None  # filled in once the new view exists

        report.append((panel, parent_node, len(members), b))

    if not covered.all():
        raise SystemExit(
            f"{(~covered).sum()} of {n_uv} vertices are in no panel group. Every "
            "primitive must be baked — an unbaked one keeps millimetre UVs and "
            "would sample a single texel of its print."
        )

    uv_knit = uv_mm / TILE_MM  # what index.html's knit.uScale = 1/TILE_MM did

    # --- assemble the new binary chunk --------------------------------------
    blocks, new_views = [], []
    cursor = 0

    def add_view(payload, **extra):
        nonlocal cursor
        pad = -cursor % 4
        if pad:
            blocks.append(b"\x00" * pad)
            cursor += pad
        blocks.append(payload)
        new_views.append(dict(buffer=0, byteOffset=cursor, byteLength=len(payload), **extra))
        cursor += len(payload)
        return len(new_views) - 1

    def slice_old(view):
        off = view.get("byteOffset", 0)
        return old_bin[off : off + view["byteLength"]]

    v_idx = add_view(slice_old(idx_view), target=idx_view["target"])
    v_uv0 = add_view(uv_baked.astype(np.float32).tobytes(), byteStride=8, target=ARRAY_BUFFER)
    v_pos = add_view(slice_old(pos_view), byteStride=pos_view["byteStride"], target=pos_view["target"])
    v_uv1 = add_view(uv_knit.astype(np.float32).tobytes(), byteStride=8, target=ARRAY_BUFFER)

    remap = {0: v_idx, 1: v_uv0, 2: v_pos}
    for acc in gltf["accessors"]:
        acc["bufferView"] = remap[acc["bufferView"]]

    # TEXCOORD_1 accessors: the knit view has the same layout as the print
    # view, so each is its TEXCOORD_0 twin with the view swapped.
    for acc_i in list(texcoord1_accessor):
        twin = dict(gltf["accessors"][acc_i])
        twin["bufferView"] = v_uv1
        gltf["accessors"].append(twin)
        texcoord1_accessor[acc_i] = len(gltf["accessors"]) - 1

    # TANGENT gets one view holding every primitive's block back to back, since
    # unlike the UVs there is no existing layout to mirror.
    tangent_accessor = {}
    if tangent_parts:
        v_tan = add_view(
            b"".join(t.tobytes() for _, _, t in tangent_parts), byteStride=16, target=ARRAY_BUFFER
        )
        at = 0
        for mesh_i, prim_j, t in tangent_parts:
            gltf["accessors"].append(
                dict(bufferView=v_tan, byteOffset=at, componentType=FLOAT, count=len(t), type="VEC4")
            )
            tangent_accessor[(mesh_i, prim_j)] = len(gltf["accessors"]) - 1
            at += t.nbytes

    # --- images, samplers, textures, materials ------------------------------
    gltf["samplers"] = [
        dict(magFilter=LINEAR, minFilter=LINEAR_MIPMAP_LINEAR, wrapS=CLAMP_TO_EDGE, wrapT=CLAMP_TO_EDGE),
        dict(magFilter=LINEAR, minFilter=LINEAR_MIPMAP_LINEAR, wrapS=REPEAT, wrapT=REPEAT),
    ]
    gltf["images"], gltf["textures"], gltf["materials"] = [], [], []

    def add_image(png_path, sampler):
        if not png_path.exists():
            raise SystemExit(f"missing {png_path} — run tools/build_print_textures.py first")
        view = add_view(png_path.read_bytes())
        gltf["images"].append(dict(name=png_path.stem, bufferView=view, mimeType="image/png"))
        gltf["textures"].append(dict(sampler=sampler, source=len(gltf["images"]) - 1))
        return len(gltf["textures"]) - 1, png_path.stat().st_size

    knit_tex, knit_bytes = add_image(TEXTURES / "knit-normal.png", sampler=1)
    png_bytes = knit_bytes

    for panel, parent_node, n_prims, b in report:
        tex, size = add_image(TEXTURES / f"{args.textures}-{panel}.png", sampler=0)
        png_bytes += size
        gltf["materials"].append(
            {
                "name": panel,
                "pbrMetallicRoughness": {
                    # baseColorTexture is sRGB and normalTexture is linear by
                    # spec, so the loader picks the right colour space itself.
                    # index.html had to say knit.gammaSpace = false by hand.
                    "baseColorTexture": {"index": tex, "texCoord": 0},
                    "metallicFactor": METALLIC,
                    "roughnessFactor": ROUGHNESS,
                },
                "normalTexture": {"index": knit_tex, "texCoord": 1, "scale": NORMAL_SCALE},
                "extensions": {
                    "KHR_materials_sheen": {
                        # Babylon splits this into sheen.color * sheen.intensity;
                        # glTF carries the product. White at 0.4 either way.
                        "sheenColorFactor": [SHEEN_INTENSITY] * 3,
                        "sheenRoughnessFactor": SHEEN_ROUGHNESS,
                    }
                },
            }
        )

    # extensionsUsed, not extensionsRequired: a viewer with no sheen support
    # should still render the shirt, just without the cloth lobe.
    gltf["extensionsUsed"] = sorted(set(gltf.get("extensionsUsed", [])) | {"KHR_materials_sheen"})

    for (mesh_i, prim_j), slot in material_of.items():
        prim = gltf["meshes"][mesh_i]["primitives"][prim_j]
        prim["material"] = slot
        prim["attributes"]["TEXCOORD_1"] = texcoord1_accessor[prim["attributes"]["TEXCOORD_0"]]
        if (mesh_i, prim_j) in tangent_accessor:
            prim["attributes"]["TANGENT"] = tangent_accessor[(mesh_i, prim_j)]

    gltf["bufferViews"] = new_views
    gltf["buffers"] = [dict(byteLength=cursor)]
    gltf["asset"] = dict(
        version="2.0",
        generator="aec tools/build_production_glb.py (from " + gltf["asset"].get("generator", "?") + ")",
    )

    binary = b"".join(blocks)
    write_glb(out_path, gltf, binary)

    # --- verify by reading back what was written ----------------------------
    #
    # Not a formality. The whole bake is one affine per panel, and getting it
    # wrong produces a shirt that still renders — just mirrored, or sampling
    # one texel. Reading the file back and checking the range is the cheapest
    # instrument that catches that without a browser.
    check_gltf, check_bin = read_glb(out_path)

    def read_uv(prim, attr):
        acc = check_gltf["accessors"][prim["attributes"][attr]]
        view = check_gltf["bufferViews"][acc["bufferView"]]
        off = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        return np.frombuffer(check_bin, np.float32, count=acc["count"] * 2, offset=off).reshape(-1, 2)

    bad = []
    for panel, parent_node, n_prims, _ in report:
        uv0 = np.vstack(
            [read_uv(check_gltf["meshes"][m]["primitives"][p], "TEXCOORD_0") for m, p in groups[parent_node]]
        )
        uv1 = np.vstack(
            [read_uv(check_gltf["meshes"][m]["primitives"][p], "TEXCOORD_1") for m, p in groups[parent_node]]
        )
        # 0.02 of tolerance is the 0.5mm rim band, which genuinely sits a hair
        # outside the pattern box — that is what CLAMP_TO_EDGE is there for.
        if uv0.min() < -0.02 or uv0.max() > 1.02:
            bad.append(f"{panel} TEXCOORD_0 outside 0..1: {uv0.min():.4f}..{uv0.max():.4f}")
        print(
            f"{panel:9s} {parent_node:20s} {n_prims} prim(s)  "
            f"u {uv0[:,0].min():.4f}..{uv0[:,0].max():.4f}  "
            f"v {uv0[:,1].min():.4f}..{uv0[:,1].max():.4f}  "
            f"knit {uv1.max() - uv1.min():.1f} tiles across"
        )

    if bad:
        raise SystemExit("BAKE FAILED:\n  " + "\n  ".join(bad))

    geom_mb = (idx_view["byteLength"] + pos_view["byteLength"]) / 1e6
    uv_mb = 2 * uv_view["byteLength"] / 1e6  # baked TEXCOORD_0 + the new TEXCOORD_1
    tan_mb = sum(t.nbytes for _, _, t in tangent_parts) / 1e6
    print(
        f"\nwrote {out_path.relative_to(ROOT)}  {out_path.stat().st_size/1e6:.2f} MB"
        f"  =  {geom_mb:.2f} geometry + {uv_mb:.2f} UVs (two sets)"
        f" + {tan_mb:.2f} tangents + {png_bytes/1e6:.2f} textures\n"
        f"  {len(gltf['materials'])} materials, {len(gltf['images'])} images, "
        f"knit tiled every {TILE_MM:.0f}mm via TEXCOORD_1\n"
        f"  extensionsUsed: {gltf['extensionsUsed']}\n"
        f"\nverify:  bun run dev  then open /prod"
        f"{'?calib' if args.textures == 'calib' else ''}\n"
        f"compress (optional, needs node):\n"
        f"  npx @gltf-transform/cli optimize {out_path.relative_to(ROOT)} "
        f"assets/tshirt-prod-min.glb --texture-compress ktx2 --compress meshopt\n"
        f"  and then SELF-HOST the decoders — see docs/production-delivery.md"
    )


if __name__ == "__main__":
    main()
