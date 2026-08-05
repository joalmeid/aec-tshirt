#!/usr/bin/env python3
"""Turn a vector logo (SVG) into a white-on-black stencil PNG.

Sponsor logos arrive from outside the print artwork -- the garment's own PDF has
no idea Compressport is on the back this year -- so they need their own way in.
tools/build_print_textures.py already stamps logos through paste_stencil(), which
wants a raster mask where WHITE IS INK. This produces that from an SVG.

Why not just use the supplied PNG: the bitmap Compressport ships is the *boxed*
lockup (red tile, white swooshes, black bar) at 2000x284. The mono lockup wanted
here -- black mark plus black wordmark on nothing -- exists only as vector. And
vector means the stencil can be re-rendered at whatever px/mm a panel needs
instead of being resampled from a fixed bitmap.

Why not shell out to resvg / Inkscape / cairosvg: none of them are on this
machine, and the rest of tools/ is deliberately numpy + Pillow only (see
docs/tools.md). The subset of SVG a logo actually uses is small, so it is
implemented here, the same trade tools/pdf_to_svg.py already makes for PDF.

Supported: <path> with M L C S H V Z in both cases, <polygon>. Even-odd filling
keeps letter counters open, via the same vectorart.fill_contours() the artwork
paths use.

Fills are flattened to ink/not-ink rather than ignored. A stencil has no
colours, but it does have a background: the Compressport file ships a WHITE
bounding-box frame behind the lockup, and treating every shape as ink stamps
that frame onto the shirt as a solid black slab. So the effective fill is
resolved -- inline style first, then the class's CSS rule -- and near-white
shapes are dropped. Everything else becomes ink.

Run:  python3 tools/make_logo_stencil.py
"""

import html
import re
from pathlib import Path

import numpy as np
from PIL import Image

import vectorart

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pipeline-design" / "artwork"

# Each entry: source SVG -> stencil PNG. Rendered at RENDER_PX across the
# content, which is far above any panel's need (the back is baked at 2 px/mm,
# so a 120mm logo lands at ~240px) and leaves headroom for downsampling.
LOGOS = {
    "logo-compressport.png": ROOT / "assets" / "compressport-seeklogo-bw.svg",
}
RENDER_PX = 2400
SS = 4  # supersample, then box-downsample -- Pillow polygons are hard-edged

NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_path(d):
    """SVG path data -> list of contours [(x, y), ...] in user units."""
    tokens = re.findall(r"[MmLlCcSsHhVvZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    contours, cur = [], []
    x = y = 0.0
    start = (0.0, 0.0)
    prev_c2 = None  # second control point of the last cubic, for S/s
    cmd = None
    i = 0

    def flush():
        nonlocal cur
        if len(cur) > 2:
            contours.append(cur)
        cur = []

    def cubic(x1, y1, x2, y2, x3, y3, steps=24):
        nonlocal x, y, prev_c2
        for s in range(1, steps + 1):
            t = s / steps
            u = 1 - t
            cur.append(
                (
                    u**3 * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                    u**3 * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
                )
            )
        prev_c2 = (x2, y2)
        x, y = x3, y3

    while i < len(tokens):
        t = tokens[i]
        if re.match(r"[MmLlCcSsHhVvZz]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(cur[0])
                flush()
                x, y = start
                prev_c2 = None
                continue
        # An omitted command repeats the previous one; after M/m it becomes L/l.
        rel = cmd.islower()
        c = cmd.upper()

        def take(n):
            nonlocal i
            vals = [float(v) for v in tokens[i : i + n]]
            i += n
            return vals

        if c == "M":
            dx, dy = take(2)
            x, y = (x + dx, y + dy) if rel else (dx, dy)
            flush()
            cur = [(x, y)]
            start = (x, y)
            cmd = "l" if rel else "L"
            prev_c2 = None
        elif c == "L":
            dx, dy = take(2)
            x, y = (x + dx, y + dy) if rel else (dx, dy)
            cur.append((x, y))
            prev_c2 = None
        elif c == "H":
            (dx,) = take(1)
            x = x + dx if rel else dx
            cur.append((x, y))
            prev_c2 = None
        elif c == "V":
            (dy,) = take(1)
            y = y + dy if rel else dy
            cur.append((x, y))
            prev_c2 = None
        elif c == "C":
            a = take(6)
            if rel:
                cubic(x + a[0], y + a[1], x + a[2], y + a[3], x + a[4], y + a[5])
            else:
                cubic(*a)
        elif c == "S":
            a = take(4)
            # Reflect the previous cubic's second control point about the
            # current point; with no previous cubic the control point IS the
            # current point, per the SVG spec.
            rx, ry = (2 * x - prev_c2[0], 2 * y - prev_c2[1]) if prev_c2 else (x, y)
            if rel:
                cubic(rx, ry, x + a[0], y + a[1], x + a[2], y + a[3])
            else:
                cubic(rx, ry, a[0], a[1], a[2], a[3])
        else:
            i += 1
    flush()
    return contours


def css_fills(svg):
    """class name -> fill colour, from the document's <style> block."""
    out = {}
    for block in re.findall(r"<style[^>]*>(.*?)</style>", svg, re.S):
        for cls, body in re.findall(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", block):
            m = re.search(r"fill\s*:\s*([^;}\s]+)", body)
            if m:
                out[cls] = m.group(1).strip()
    return out


def is_ink(attrs, classes):
    """False for shapes that are the logo's background rather than its mark."""
    m = re.search(r'style="([^"]*)"', attrs)
    fill = None
    if m:
        f = re.search(r"fill\s*:\s*([^;]+)", m.group(1))
        if f:
            fill = f.group(1).strip()
    if fill is None:
        c = re.search(r'class="([^"]+)"', attrs)
        if c:
            fill = classes.get(c.group(1).split()[0])
    if fill is None:
        f = re.search(r'fill="([^"]+)"', attrs)
        fill = f.group(1).strip() if f else None
    if fill is None or fill == "none":
        return fill != "none"

    rgb = re.match(r"rgb\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", fill)
    if rgb:
        r, g, b = (int(v) for v in rgb.groups())
    elif fill.startswith("#"):
        h = fill[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) != 6:
            return True
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    else:
        return fill.lower() != "white"
    return min(r, g, b) < 235  # near-white is the backing plate, not the mark


def shapes_of(svg):
    """Every filled contour in the document, in user units.

    Attributes are XML-unescaped first. Illustrator wraps long coordinate lists
    with literal newlines and tabs written as character references, so a
    points="..." arrives holding &#10;&#9; between numbers. Those are whitespace
    separators, but read as raw text a number scanner sees the digits inside
    them: every wrap injected a spurious (10, 9) vertex and shifted the rest of
    the list by one coordinate. It does not throw -- it silently deforms the
    glyphs and stretches the bounding box, which is how it was caught (the
    lockup's aspect came out 1.74 instead of 12.6).
    """
    svg = html.unescape(svg)
    classes = css_fills(svg)
    out, skipped = [], 0
    # Match the WHOLE element, not the run up to d=. Illustrator writes
    # style= after d=, so capturing only what precedes the geometry loses the
    # inline fill -- and then every shape inherits its class's white and the
    # stencil comes out empty.
    for attrs in re.findall(r"<path\b([^>]*?)/?>", svg):
        d = re.search(r"\sd=\"([^\"]+)\"", attrs)
        if not d:
            continue
        if not is_ink(attrs, classes):
            skipped += 1
            continue
        out.extend(parse_path(d.group(1)))
    for attrs in re.findall(r"<polygon\b([^>]*?)/?>", svg):
        pts = re.search(r"\spoints=\"([^\"]+)\"", attrs)
        if not pts:
            continue
        if not is_ink(attrs, classes):
            skipped += 1
            continue
        nums = [float(v) for v in NUM.findall(pts.group(1))]
        pairs = list(zip(nums[0::2], nums[1::2]))
        if len(pairs) > 2:
            out.append(pairs + [pairs[0]])
    if skipped:
        print(f"  skipped {skipped} near-white shape(s) as background")
    return out


def render(svg_path, out_path):
    svg = svg_path.read_text()
    contours = shapes_of(svg)
    if not contours:
        raise SystemExit(f"no drawable shapes found in {svg_path}")

    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w_u, h_u = x1 - x0, y1 - y0

    # Crop to the ink, not the canvas. The Compressport lockup is 556x44 inside
    # a 652x652 square, so keeping the canvas would make the placement
    # millimetres in build_print_textures.py describe mostly empty space.
    scale = RENDER_PX / w_u
    W = max(1, int(round(w_u * scale))) * SS
    H = max(1, int(round(h_u * scale))) * SS

    img = Image.new("RGB", (W, H), (0, 0, 0))
    vectorart.fill_contours(
        img,
        [[((px - x0) * scale * SS, (py - y0) * scale * SS) for px, py in c] for c in contours],
        (255, 255, 255),
    )
    img = img.resize((W // SS, H // SS), Image.LANCZOS).convert("L")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    ink = float((np.asarray(img) > 127).mean())
    try:
        shown = out_path.relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(
        f"{svg_path.name}\n"
        f"  content {w_u:.1f} x {h_u:.1f} user units  (aspect {w_u/h_u:.2f})\n"
        f"  -> {shown}  {img.width} x {img.height}px, {100*ink:.1f}% ink\n"
        f"  white = ink, cropped to content"
    )
    return w_u / h_u


def main():
    for name, src in LOGOS.items():
        if not src.exists():
            raise SystemExit(f"missing {src}")
        render(src, OUT / name)


if __name__ == "__main__":
    main()
