#!/usr/bin/env python3
"""Load and rasterise the vector artwork produced by tools/pdf_to_svg.py.

Paths keep the PDF's own millimetre coordinate system throughout. Callers hand
in an affine that maps artwork millimetres to destination pixels, so a design
element's position stays traceable back to a measurement on the source artwork
instead of becoming an unexplained pixel constant.
"""

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "source" / "artwork"

PT_TO_MM = 25.4 / 72.0


def load():
    """Return [{index, d, fill, stroke, stroke_width}] in artwork millimetres."""
    svg = (ART / "official-artwork.svg").read_text()
    meta = {p["index"]: p for p in json.loads((ART / "official-artwork.json").read_text())["paths"]}
    out = []
    for i, m in enumerate(re.finditer(r"<path ([^>]*)d=\"([^\"]*)\"", svg)):
        attrs, d = m.group(1), m.group(2)
        fill = re.search(r'fill="(#[0-9a-f]{6})"', attrs)
        stroke = re.search(r'stroke="(#[0-9a-f]{6})"', attrs)
        sw = re.search(r'stroke-width="([\d\.]+)"', attrs)
        out.append(
            dict(
                index=i,
                d=d,
                fill=fill.group(1) if fill else None,
                stroke=stroke.group(1) if stroke else None,
                stroke_width=float(sw.group(1)) * PT_TO_MM if sw else 0.0,
                bbox_mm=meta[i]["bbox_mm"] if i in meta else None,
            )
        )
    return out


def subpaths(d, steps=28):
    """Flatten an SVG path string (M/L/C/Z only) to polylines, in PDF points."""
    toks = re.findall(r"[MLCZ]|-?[\d\.]+", d)
    subs, cur, last, i = [], [], (0.0, 0.0), 0
    while i < len(toks):
        t = toks[i]
        if t == "M":
            if len(cur) > 1:
                subs.append(cur)
            last = (float(toks[i + 1]), float(toks[i + 2]))
            cur = [last]
            i += 3
        elif t == "L":
            last = (float(toks[i + 1]), float(toks[i + 2]))
            cur.append(last)
            i += 3
        elif t == "C":
            p1 = (float(toks[i + 1]), float(toks[i + 2]))
            p2 = (float(toks[i + 3]), float(toks[i + 4]))
            p3 = (float(toks[i + 5]), float(toks[i + 6]))
            for s in range(1, steps + 1):
                u = s / steps
                v = 1 - u
                cur.append(
                    (
                        v**3 * last[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u**3 * p3[0],
                        v**3 * last[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u**3 * p3[1],
                    )
                )
            last = p3
            i += 7
        elif t == "Z":
            if cur:
                cur.append(cur[0])
            i += 1
        else:
            i += 1
    if len(cur) > 1:
        subs.append(cur)
    return subs


def draw_paths(draw: ImageDraw.ImageDraw, paths, xf, only=None, fill_override=None):
    """Fill `paths` into `draw`. `xf` maps artwork mm -> destination pixels.

    Every path in this artwork is a closed filled shape (the PDF strokes only
    the technical-flat's seam lines, which we never want on a texture), so
    filling each subpath independently is enough -- there are no holes that need
    even-odd handling in the elements we place.
    """
    for p in paths:
        if only is not None and p["index"] not in only:
            continue
        colour = fill_override or p["fill"]
        if not colour:
            continue
        for sub in subpaths(p["d"]):
            pts = [xf(x * PT_TO_MM, y * PT_TO_MM) for x, y in sub]
            if len(pts) > 2:
                draw.polygon(pts, fill=colour)
