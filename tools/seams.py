#!/usr/bin/env python3
"""Recover the garment's seams from the mesh, as polylines in pattern millimetres.

A UV island's boundary IS a seam. That is not an approximation here: this model
is a Marvelous Designer garment whose UVs are the real 2D sewing pattern, so the
edge of each island is exactly the cut line the panel was sewn along. Finding it
needs no image processing and no tracing -- a boundary edge is simply an edge
used by exactly one triangle.

This is why the stitching does not come from the PSD. source/all-psd-exports/
"Stitches Shirt.png" is 3000x3000 with 0.1% coverage, drawn in the mockup's
fixed camera projection: perspective-warped onto one viewpoint, with no way back
to the garment. The mesh already knows where its own seams are.

Measured off that PSD layer, real topstitching on this design is a dashed line
in #515253, roughly 0.8mm wide with a 3mm dash and 1.5mm gap -- which is
ordinary topstitch spacing, so it transfers.
"""

import math
from collections import defaultdict

import numpy as np


def boundary_loops(idx, min_points=8):
    """Ordered vertex loops along the mesh boundary.

    An edge shared by two triangles is interior; an edge used once is on the
    island boundary. Walking those gives closed loops -- one per panel for the
    body pieces, several for a sleeve (cap, cuff, underarm).
    """
    used = defaultdict(int)
    for tri in idx:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            used[(min(a, b), max(a, b))] += 1

    adj = defaultdict(list)
    for (a, b), n in used.items():
        if n == 1:
            adj[a].append(b)
            adj[b].append(a)

    loops, seen = [], set()
    for start in adj:
        if start in seen:
            continue
        loop, cur, prev = [start], start, None
        seen.add(start)
        while True:
            nxt = [v for v in adj[cur] if v != prev and v not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        if len(loop) >= min_points:
            loops.append(loop)
    return loops


def _signed_area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def offset_inward(poly, dist):
    """Move every vertex inward along its angle bisector.

    `dist` may be a scalar or one value per vertex, which is how the hem gets a
    deeper inset than the side seams without breaking the curve into pieces.

    Direction is settled by measuring rather than by reasoning about winding:
    offset once, and if the polygon grew instead of shrinking, go the other way.
    Cheap, and it cannot be got backwards.
    """
    dist = np.asarray(dist, dtype=float)
    if dist.ndim == 0:
        dist = np.full(len(poly), float(dist))

    nxt = np.roll(poly, -1, axis=0) - poly
    prv = poly - np.roll(poly, 1, axis=0)
    for e in (nxt, prv):
        n = np.linalg.norm(e, axis=1, keepdims=True)
        e /= np.maximum(n, 1e-9)

    # normal of a 2D edge (dx,dy) is (dy,-dx); averaging the two adjacent edge
    # normals approximates the bisector and behaves on smooth boundaries
    normal = np.stack([nxt[:, 1] + prv[:, 1], -(nxt[:, 0] + prv[:, 0])], axis=1)
    n = np.linalg.norm(normal, axis=1, keepdims=True)
    normal /= np.maximum(n, 1e-9)

    out = poly + normal * dist[:, None]
    if abs(_signed_area(out)) > abs(_signed_area(poly)):
        out = poly - normal * dist[:, None]
    return out


def resample(poly, step_mm):
    """Even arc-length resampling, so dashes come out a constant length."""
    seg = np.linalg.norm(np.diff(np.vstack([poly, poly[:1]]), axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = s[-1]
    if total <= 0:
        return poly, 0.0
    n = max(2, int(round(total / step_mm)))
    targets = np.linspace(0.0, total, n, endpoint=False)
    closed = np.vstack([poly, poly[:1]])
    x = np.interp(targets, s, closed[:, 0])
    y = np.interp(targets, s, closed[:, 1])
    return np.stack([x, y], axis=1), total


def dashes(poly, dash_mm, gap_mm, step_mm=0.35):
    """Split a closed polyline into dash segments of constant arc length.

    The dash pattern is stretched by up to half a step so a whole number of
    dashes fits the loop -- otherwise every seam ends in a stub where the
    pattern wraps past the start point.
    """
    pts, total = resample(poly, step_mm)
    if total <= 0 or len(pts) < 2:
        return []
    period = dash_mm + gap_mm
    reps = max(1, round(total / period))
    period = total / reps
    duty = dash_mm / (dash_mm + gap_mm)

    seg = np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
    on = (s % period) < period * duty

    out, run = [], []
    for i, flag in enumerate(on):
        if flag:
            run.append(tuple(pts[i]))
        elif run:
            if len(run) > 1:
                out.append(run)
            run = []
    if len(run) > 1:
        out.append(run)
    return out


def seam_polylines(mesh, pattern_mm, inset_fn, dash_mm=3.0, gap_mm=1.5, where_fn=None):
    """Every stitch dash for one panel, in pattern millimetres.

    `inset_fn(u, v)` returns how far in from the boundary the stitch sits, given
    a point on the boundary in panel millimetres -- letting a hem sit deeper than
    a shoulder seam on the same continuous loop.

    `where_fn(u, v)` decides whether that stretch of boundary is stitched at all.
    It matters because a seam joins TWO panels, and each one's island boundary
    runs along it: stitching both draws the armhole twice, a few millimetres
    apart, and the neckline three times once the collar bands join in. Real
    topstitching shows once, so each seam is claimed by exactly one panel.
    """
    uv = mesh["uv"] - np.array([pattern_mm["u0"], pattern_mm["v0"]])
    out = []
    for loop in boundary_loops(mesh["idx"]):
        poly = uv[loop]
        inset = np.array([inset_fn(p[0], p[1]) for p in poly])
        offset = offset_inward(poly, inset)
        if where_fn is None:
            out.extend(dashes(offset, dash_mm, gap_mm))
            continue
        # Split the loop into the runs that are stitched, then dash each run.
        keep = np.array([bool(where_fn(p[0], p[1])) for p in poly])
        if not keep.any():
            continue
        if keep.all():
            out.extend(dashes(offset, dash_mm, gap_mm))
            continue
        idx = np.nonzero(keep)[0]
        breaks = np.nonzero(np.diff(idx) != 1)[0]
        for run in np.split(idx, breaks + 1):
            if len(run) > 3:
                out.extend(dashes(offset[run], dash_mm, gap_mm))
    return out
