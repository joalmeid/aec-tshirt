#!/usr/bin/env python3
"""Minimal .glb reader for the offline tools in this directory.

Only covers what assets/tshirt.glb actually uses: a single binary chunk,
non-sparse accessors, triangle primitives, and a static node hierarchy. No
animation, no skinning, no Draco. Kept dependency-free on purpose -- these tools
run without a build step or a 3D package installed.
"""

import json
import struct
from pathlib import Path

import numpy as np

COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
NPDTYPE = {"f": np.float32, "H": np.uint16, "I": np.uint32, "B": np.uint8, "h": np.int16, "b": np.int8}


class Glb:
    def __init__(self, path):
        data = Path(path).read_bytes()
        total = struct.unpack("<III", data[:12])[2]
        offset, chunks = 12, []
        while offset < total:
            clen, ctype = struct.unpack("<II", data[offset : offset + 8])
            chunks.append((ctype, offset + 8, clen))
            offset += 8 + clen
        self.gltf = json.loads(data[chunks[0][1] : chunks[0][1] + chunks[0][2]].decode("utf-8"))
        self.bin = data[chunks[1][1] : chunks[1][1] + chunks[1][2]]

    def accessor(self, index):
        acc = self.gltf["accessors"][index]
        view = self.gltf["bufferViews"][acc["bufferView"]]
        fmt, size = COMPONENT[acc["componentType"]]
        n = NCOMP[acc["type"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or size * n
        if stride == size * n:
            return np.frombuffer(self.bin, dtype=NPDTYPE[fmt], count=acc["count"] * n, offset=start).reshape(
                acc["count"], n
            )
        out = np.zeros((acc["count"], n), dtype=NPDTYPE[fmt])
        for k in range(acc["count"]):
            out[k] = struct.unpack_from("<" + fmt * n, self.bin, start + k * stride)
        return out

    def node_matrix(self, node):
        if "matrix" in node:
            return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
        m = np.eye(4)
        if "scale" in node:
            m = np.diag(list(node["scale"]) + [1.0]) @ m
        if "rotation" in node:
            x, y, z, w = node["rotation"]
            r = np.array(
                [
                    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
                    [0, 0, 0, 1],
                ]
            )
            m = r @ m
        if "translation" in node:
            t = np.eye(4)
            t[:3, 3] = node["translation"]
            m = t @ m
        return m

    def meshes(self):
        """Flatten the scene graph into world-space mesh records."""
        nodes = self.gltf["nodes"]
        parent_of = {}
        for i, node in enumerate(nodes):
            for c in node.get("children", []):
                parent_of[c] = i

        out = []
        for i, node in enumerate(nodes):
            if node.get("mesh") is None:
                continue
            world = np.eye(4)
            chain, j = [], i
            while j is not None:
                chain.append(j)
                j = parent_of.get(j)
            for j in reversed(chain):
                world = world @ self.node_matrix(nodes[j])

            pi = parent_of.get(i)
            prim = self.gltf["meshes"][node["mesh"]]["primitives"][0]
            pos = self.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
            pos = (world[:3, :3] @ pos.T).T + world[:3, 3]
            nrm = self.accessor(prim["attributes"]["NORMAL"]).astype(np.float64)
            nrm = (world[:3, :3] @ nrm.T).T
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
            out.append(
                dict(
                    mesh=node["mesh"],
                    node=node.get("name", "?"),
                    parent=nodes[pi].get("name", "?") if pi is not None else "?",
                    material=prim.get("material"),
                    pos=pos,
                    nrm=nrm,
                    uv=self.accessor(prim["attributes"]["TEXCOORD_0"]).astype(np.float64),
                    idx=self.accessor(prim["indices"]).astype(np.int64).ravel().reshape(-1, 3),
                )
            )
        return out
