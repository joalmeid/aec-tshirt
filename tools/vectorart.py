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

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "pipeline-design" / "artwork"

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


def fill_contours(img, contours, colour):
    """Fill one path's contours as a single shape, keeping its holes open.

    Contours are XOR-ed into a mask rather than filled one by one: a pixel is
    inside when an odd number of contours covers it, so a letter's counter
    punches a hole instead of painting over it.

    Filling each contour independently -- which this used to do -- silently
    solidified every glyph with a hole in it: both As, the O, both Rs, the D,
    and the 0 and 6 of 2026.

    This is the even-odd rule, which is what the PDF asks for on its `f*` paths.
    It also matches `f` (nonzero) for everything here, because font outlines
    wind inner contours opposite to outer ones. The two rules only disagree on
    self-overlapping paths, and this artwork has none.
    """
    polys = [c for c in contours if len(c) > 2]
    if not polys:
        return
    xs = [p[0] for c in polys for p in c]
    ys = [p[1] for c in polys for p in c]
    x0, y0 = max(int(min(xs)) - 1, 0), max(int(min(ys)) - 1, 0)
    x1 = min(int(max(xs)) + 2, img.width)
    y1 = min(int(max(ys)) + 2, img.height)
    if x1 <= x0 or y1 <= y0:
        return

    acc = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    for c in polys:
        cell = Image.new("1", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(cell).polygon([(x - x0, y - y0) for x, y in c], fill=1)
        acc ^= np.asarray(cell, dtype=bool)

    if acc.any():
        img.paste(colour, (x0, y0), Image.fromarray(acc))


def draw_paths(draw_or_img, paths, xf, only=None, fill_override=None):
    """Fill `paths` into an image. `xf` maps artwork mm -> destination pixels."""
    img = getattr(draw_or_img, "_image", draw_or_img)
    for p in paths:
        if only is not None and p["index"] not in only:
            continue
        colour = fill_override or p["fill"]
        if not colour:
            continue
        contours = [
            [xf(x * PT_TO_MM, y * PT_TO_MM) for x, y in sub] for sub in subpaths(p["d"])
        ]
        fill_contours(img, contours, colour)
