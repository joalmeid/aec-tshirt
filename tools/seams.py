#!/usr/bin/env python3
"""Recover the garment's seams from the mesh, as polylines in pattern millimetres.

A UV island's boundary IS a seam. That is not an approximation here: this model
is a Marvelous Designer garment whose UVs are the real 2D sewing pattern, so the
edge of each island is exactly the cut line the panel was sewn along. Finding it
needs no image processing and no tracing -- a boundary edge is simply an edge
used by exactly one triangle.

This is why the stitching does not come from the PSD. pipeline-design/all-psd-exports/
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

    # Reject a contour that the offset turns inside out. Offsetting inward can
    # only shrink a shape; if the signed area flips sign or all but vanishes,
    # the contour was narrower than twice the inset and has collapsed through
    # itself, and what rasterises is a line cutting straight across the panel.
    #
    # This is not hypothetical -- the sleeve mesh's boundary includes 22mm-wide
    # underarm slivers, and offsetting those by the 20mm hem inset is exactly
    # what drew a diagonal across both sleeves and through the SCARPA badge.
    before, after = _signed_area(poly), _signed_area(out)
    if before == 0 or after / before < 0.05:
        return None
    return out


def resample(poly, step_mm, closed=True):
    """Even arc-length resampling, so dashes come out a constant length."""
    pts = np.vstack([poly, poly[:1]]) if closed else np.asarray(poly, dtype=float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = s[-1]
    if total <= 0:
        return poly, 0.0
    n = max(2, int(round(total / step_mm)))
    targets = np.linspace(0.0, total, n, endpoint=not closed)
    x = np.interp(targets, s, pts[:, 0])
    y = np.interp(targets, s, pts[:, 1])
    return np.stack([x, y], axis=1), total


def dashes(poly, dash_mm, gap_mm, step_mm=0.35, closed=True):
    """Split a polyline into dash segments of constant arc length.

    The dash pattern is stretched by up to half a step so a whole number of
    dashes fits the run -- otherwise a closed seam ends in a stub where the
    pattern wraps past the start point, and an open one ends in a half dash.
    """
    pts, total = resample(poly, step_mm, closed=closed)
    if total <= 0 or len(pts) < 2:
        return []
    period = dash_mm + gap_mm
    reps = max(1, round(total / period))
    period = total / reps
    duty = dash_mm / (dash_mm + gap_mm)

    ends = np.vstack([pts, pts[:1]]) if closed else pts
    seg = np.linalg.norm(np.diff(ends, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])[: len(pts)]
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


def nearest_mm(points, target):
    """Distance in MILLIMETRES from each point to the nearest target vertex.

    Positions in the glTF are metres, so the result is scaled. Used to work out
    which garment piece a stretch of boundary is sewn to, which is what says
    whether it is a neckline, an armhole, a side seam or a free hem.
    """
    if len(target) == 0:
        return np.full(len(points), np.inf)
    d2 = ((points[:, None, :] - target[None, :, :]) ** 2).sum(-1)
    return np.sqrt(d2.min(axis=1)) * 1000.0


def inward_sign(poly):
    """+1 or -1: which way the right-hand edge normal points INTO the shape.

    Settled by measuring, not by assuming a winding: offset the closed loop one
    way and see whether it shrank.
    """
    e = np.roll(poly, -1, axis=0) - poly
    e /= np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-9)
    n = np.stack([e[:, 1], -e[:, 0]], axis=1)
    step = max(1e-6, 0.001 * float(np.abs(poly).max()))
    return 1.0 if abs(_signed_area(poly + n * step)) < abs(_signed_area(poly)) else -1.0


def offset_run(run_pts, dist, sign):
    """Offset an OPEN polyline, using one-sided normals at its two ends.

    This is why runs are offset individually rather than sliced out of an
    offset of the whole loop. At a run's end the loop turns into the next seam,
    so a whole-loop offset has already begun rotating there -- and the slice
    inherits that rotation as a hook curling back on itself. Two of those
    meeting at the sleeve's underarm is what drew a cross under each cuff.

    An endpoint here takes the normal of its single adjacent edge, so the run
    ends square, exactly where its seam ends.
    """
    p = np.asarray(run_pts, dtype=float)
    if len(p) < 2:
        return p
    e = np.diff(p, axis=0)
    e /= np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-9)
    en = np.stack([e[:, 1], -e[:, 0]], axis=1)  # right-hand normal per edge

    nrm = np.empty_like(p)
    nrm[0] = en[0]
    nrm[-1] = en[-1]
    if len(p) > 2:
        nrm[1:-1] = en[:-1] + en[1:]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    return p + sign * nrm * dist


def trim_ends(pts, mm):
    """Drop `mm` of arc length from both ends of an open polyline.

    A pattern piece's corners are rounded, so the last stretch of a run is
    already curving into the next seam. Offsetting that follows the curve and
    leaves a small hook at each end. Stopping short is also what real
    topstitching does -- a seam is not sewn into its own corner.
    """
    p = np.asarray(pts, dtype=float)
    if len(p) < 3 or mm <= 0:
        return p
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] <= 2 * mm + 1e-6:
        return p
    keep = (s >= mm) & (s <= s[-1] - mm)
    return p[keep] if keep.sum() >= 2 else p


def extend_to_span(pts, x_min, x_max, sample=6):
    """Extrapolate an open run's ends until they reach x_min and x_max.

    For a piece that is sewn into a tube, the pattern's left and right edges are
    the SAME line on the finished garment. A hem run that stops short of them
    leaves a gap at the join -- on this sleeve, 40mm where the boundary curves up
    at the corners and is no longer classified as hem, plus the trim, came to 72mm
    of a 397mm ring.

    Extrapolating straight is not a shortcut, it is more correct than following
    the boundary: the corner curvature is seam-allowance shaping, while the
    finished hem is a closed circle parallel to the fold.

    Direction is averaged over `sample` points so a single noisy end segment
    cannot send the extension off at an angle.
    """
    p = np.asarray(pts, dtype=float)
    if len(p) < 2:
        return p

    def endpoint(tip, inward):
        d = tip - inward
        n = np.linalg.norm(d)
        if n < 1e-9 or abs(d[0]) < 1e-9:
            return None
        d = d / n
        target = x_min if d[0] < 0 else x_max
        t = (target - tip[0]) / d[0]
        return tip + d * t if t > 0 else None

    k = min(sample, len(p) - 1)
    head = endpoint(p[0], p[k])
    tail = endpoint(p[-1], p[-1 - k])

    out = p
    if head is not None:
        out = np.vstack([head, out])
    if tail is not None:
        out = np.vstack([out, tail])
    return out


def label_runs(labels):
    """Contiguous same-label stretches of a CLOSED loop, as index arrays.

    A run that wraps past index 0 is stitched back together, so a seam crossing
    the loop's arbitrary start point stays one run rather than two stubs.

    Runs do NOT overlap here. Whether a run should reach into its neighbour is a
    question about the two seams' insets, which only stitch_runs knows -- see
    `_join_to_next` there.
    """
    n = len(labels)
    if n == 0:
        return []
    bounds = [i for i in range(n) if labels[i] != labels[i - 1]]
    if not bounds:
        return [(labels[0], np.arange(n))]
    runs = []
    for k, start in enumerate(bounds):
        end = bounds[(k + 1) % len(bounds)]
        stop = end if end > start else end + n
        runs.append((labels[start], np.arange(start, stop) % n))
    return runs


def trim_kinks(pts, max_turn_deg=30.0, head=True, tail=True):
    """Drop points from either end while the polyline turns sharply there.

    A run is classified from the boundary, and a classifier working on distance
    to the neighbouring piece cannot land exactly on a corner: the first point or
    two that have already turned along the NEXT edge still come out labelled with
    this seam. Offsetting them faithfully reproduces the turn, so the stitch
    finishes with a little flick across the corner instead of running out
    straight -- which is what the side seams were doing as they reached the hem,
    their last segment turning 90 degrees.

    Self-orienting on purpose: it removes a kink wherever it is and leaves an end
    that is already straight alone, so a run whose other end meets its neighbour
    exactly does not get shortened for the sake of the far end. Smooth curves
    such as the armhole and neckline turn a few degrees per segment and are
    untouched.

    `head` and `tail` let the caller protect an end that takes part in a join.
    Those ends turn a corner legitimately -- that is what meeting the next seam
    looks like -- and trimming them reopens the junction. Left on, this quietly
    undid every join around the armhole.
    """
    p = np.asarray(pts, dtype=float)
    while len(p) > 3:
        d = np.diff(p, axis=0)
        n = np.linalg.norm(d, axis=1, keepdims=True)
        if np.any(n < 1e-9):
            break
        ang = np.degrees(np.arctan2(*(d / n).T[::-1]))
        turn = np.abs((np.diff(ang) + 180.0) % 360.0 - 180.0)
        if tail and turn[-1] > max_turn_deg:
            p = p[:-1]
        elif head and turn[0] > max_turn_deg:
            p = p[1:]
        else:
            break
    return p


def _join_to_next(runs, k, spec):
    """Should run `k` extend one point into the next run, to close the join?

    Yes when both seams are stitched at the SAME inset: their offset lines then
    land on top of each other and the shared segment completes the join. Without
    this a run ends on its last boundary point while the next begins on the
    following one, leaving the segment between them unstitched -- and since this
    boundary is sampled at roughly 4.9mm, that read as a visible break at every
    junction, most obviously where the shoulder meets the neckline.

    No when the insets differ. The two lines are parallel but separated then, so
    they never meet whatever we do, and reaching across only drags one segment of
    the neighbour's direction into this run's end. Where the seams are also
    perpendicular -- the side seam arriving at the hem -- that segment turns 90
    degrees and hooks the line into a corner just before it terminates.
    """
    a = spec.get(runs[k][0])
    b = spec.get(runs[(k + 1) % len(runs)][0])
    if not a or not b:
        return False
    return abs(a["inset"] - b["inset"]) < 1e-6


def stitch_runs(loop_uv, labels, spec, dash_mm=3.0, gap_mm=1.5, trim_mm=0.0, span=None):
    """Dashes for one boundary loop, one run per seam.

    `spec` maps a label to {"inset": mm, "rows": n, "row_gap": mm}, or to None
    for seams that are not topstitched.

    Each seam is offset and dashed INDEPENDENTLY, and that is the point. The
    previous version offset the whole loop as one curve, so the stitch travelled
    around every corner -- shoulder tip, armpit, hem-to-side junction -- where an
    angle-bisector offset overshoots or self-intersects. Real topstitching stops
    at those corners, and so does this.
    """
    sign = inward_sign(loop_uv)
    runs = label_runs(labels)
    whole = len(runs) == 1

    out = []
    for k, (label, idx) in enumerate(runs):
        rule = spec.get(label)
        if not rule or len(idx) < 4:
            continue
        for row in range(rule.get("rows", 1)):
            inset = rule["inset"] + row * rule.get("row_gap", 0.0)
            if whole:
                # A label covering the entire boundary really is a closed ring.
                offset = offset_inward(loop_uv, inset)
                if offset is None:
                    continue
                out.extend(dashes(offset, dash_mm, gap_mm, closed=True))
            else:
                # Order matters. trim_kinks first, on the run's OWN points, to
                # drop any stray point the classifier left across a corner. The
                # join point is added AFTER: it sits across a corner by
                # definition, so trimming kinks afterwards would remove exactly
                # the point that closes the join and silently undo it.
                joins_next = _join_to_next(runs, k, spec)
                joined_from_prev = _join_to_next(runs, (k - 1) % len(runs), spec)
                run = trim_kinks(loop_uv[idx], head=not joined_from_prev, tail=not joins_next)
                if joins_next:
                    run = np.vstack([run, loop_uv[runs[(k + 1) % len(runs)][1][0]]])
                run = trim_ends(run, rule.get("trim", trim_mm))
                run = offset_run(run, inset, sign)
                if rule.get("close_ring") and span is not None:
                    # The piece is sewn into a tube, so carry the run out to both
                    # pattern edges -- they are the same line once joined.
                    run = extend_to_span(run, span[0], span[1])
                out.extend(dashes(run, dash_mm, gap_mm, closed=False))
    return out
