#!/usr/bin/env python3
"""Convert the official print artwork PDF into SVG + a geometry report.

"T-shirt Alimenta esta corrida oficial 2026.pdf" is the print-ready artwork the
garment supplier works from: a single 750 x 1230.17 pt page holding front and
back technical flats, drawn as real vector paths (beziers, not a raster). That
makes it the authoritative source for the design's exact colours, stripe angles
and stripe widths -- everything in source/all-psd-exports/ is a composited
mockup layer that has already been perspective-warped onto one fixed camera and
is therefore useless for measurement.

Note this is the *technical flat*, i.e. the assembled garment seen head-on, not
a flat pattern piece. Geometry read out of here still has to be re-expressed in
the panel's own pattern-millimetre space before it can be used as a texture --
see tools/extract_pattern.py for that coordinate system.

Deliberately dependency-free: no poppler / cairo / resvg on this machine, so it
parses the content stream directly. Only the subset of PDF operators this file
actually uses is implemented.

Outputs to source/artwork/:
  official-artwork.svg    the vector artwork, y-flipped into SVG convention
  official-artwork.json   every path with its fill/stroke colour and bbox,
                          plus each raster image's placement rectangle
  official-artwork.png    a rasterisation, for looking at
  pdf-images/*.png        the embedded raster images -- the association mark
                          and the SCARPA lockup, both white-on-black stencils

Run:  python3 tools/pdf_to_svg.py
"""

import json
import math
import re
import zlib
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT.parent / "T-shirt Alimenta esta corrida oficial 2026.pdf"
OUT = ROOT / "source" / "artwork"

PT_TO_MM = 25.4 / 72.0


# ---------------------------------------------------------------- pdf plumbing
def load_objects(data):
    objs = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
        num = int(m.group(1))
        start = m.end()
        end = data.find(b"endobj", start)
        objs[num] = data[start : end if end > 0 else start + 4096]
    return objs


def stream_of(obj):
    st = obj.find(b"stream")
    if st < 0:
        return None
    st = obj.find(b"\n", st) + 1
    en = obj.find(b"endstream")
    raw = obj[st:en]
    if b"/FlateDecode" in obj[: obj.find(b"stream")]:
        try:
            return zlib.decompressobj().decompress(raw)
        except Exception:
            return None
    return raw


# ------------------------------------------------------------------- matrices
def mmul(a, b):
    return [
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    ]


def mapply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def cmyk_to_rgb(c, m, y, k):
    return (
        round(255 * (1 - min(1.0, c + k))),
        round(255 * (1 - min(1.0, m + k))),
        round(255 * (1 - min(1.0, y + k))),
    )


TOKEN = re.compile(rb"/[A-Za-z0-9#\.\-\+_]+|\[[^\]]*\]|\([^)]*\)|<[^>]*>|[-+0-9\.]+|[A-Za-z\*'\"]+")


class Interp:
    """Walks a PDF content stream and emits flattened SVG path elements."""

    def __init__(self, page_height, objects, resources_xobjects):
        self.H = page_height
        self.objects = objects
        self.xobjects = resources_xobjects
        self.paths = []
        self.images = []
        self.opcount = Counter()

    def run(self, content, ctm=None, depth=0):
        if depth > 6:
            return
        ctm = list(ctm or [1, 0, 0, 1, 0, 0])
        stack = []
        fill, stroke, lw = (0, 0, 0), (0, 0, 0), 1.0
        cur, subs = [], []
        start_pt = None
        last = (0.0, 0.0)
        operands = []

        toks = [t.decode("latin-1") for t in TOKEN.findall(content)]
        i = 0
        while i < len(toks):
            t = toks[i]
            i += 1
            try:
                operands.append(float(t))
                continue
            except ValueError:
                pass
            if t[0] in "/[(<":
                operands.append(t)
                continue

            op = t
            self.opcount[op] += 1
            nums = [v for v in operands if isinstance(v, float)]

            def n(k):
                return nums[-k:] if len(nums) >= k else [0.0] * k

            if op == "q":
                stack.append((ctm[:], fill, stroke, lw))
            elif op == "Q":
                if stack:
                    ctm, fill, stroke, lw = stack.pop()
                    ctm = ctm[:]
            elif op == "cm":
                ctm = mmul(n(6), ctm)
            elif op == "gs":
                pass
            elif op == "m":
                a = n(2)
                if len(cur) > 1:
                    subs.append(cur)
                last = mapply(ctm, a[0], a[1])
                start_pt = last
                cur = [f"M {last[0]:.3f} {self.H - last[1]:.3f}"]
            elif op == "l":
                a = n(2)
                last = mapply(ctm, a[0], a[1])
                cur.append(f"L {last[0]:.3f} {self.H - last[1]:.3f}")
            elif op == "c":
                a = n(6)
                p1, p2, p3 = mapply(ctm, a[0], a[1]), mapply(ctm, a[2], a[3]), mapply(ctm, a[4], a[5])
                cur.append(
                    f"C {p1[0]:.3f} {self.H-p1[1]:.3f} {p2[0]:.3f} {self.H-p2[1]:.3f} {p3[0]:.3f} {self.H-p3[1]:.3f}"
                )
                last = p3
            elif op == "v":  # current point doubles as first control point
                a = n(4)
                p2, p3 = mapply(ctm, a[0], a[1]), mapply(ctm, a[2], a[3])
                cur.append(
                    f"C {last[0]:.3f} {self.H-last[1]:.3f} {p2[0]:.3f} {self.H-p2[1]:.3f} {p3[0]:.3f} {self.H-p3[1]:.3f}"
                )
                last = p3
            elif op == "y":  # final point doubles as second control point
                a = n(4)
                p1, p3 = mapply(ctm, a[0], a[1]), mapply(ctm, a[2], a[3])
                cur.append(
                    f"C {p1[0]:.3f} {self.H-p1[1]:.3f} {p3[0]:.3f} {self.H-p3[1]:.3f} {p3[0]:.3f} {self.H-p3[1]:.3f}"
                )
                last = p3
            elif op == "h":
                cur.append("Z")
                if start_pt:
                    last = start_pt
            elif op == "re":
                a = n(4)
                pts = [
                    mapply(ctm, a[0], a[1]),
                    mapply(ctm, a[0] + a[2], a[1]),
                    mapply(ctm, a[0] + a[2], a[1] + a[3]),
                    mapply(ctm, a[0], a[1] + a[3]),
                ]
                if len(cur) > 1:
                    subs.append(cur)
                cur = [f"M {pts[0][0]:.3f} {self.H-pts[0][1]:.3f}"]
                cur += [f"L {p[0]:.3f} {self.H-p[1]:.3f}" for p in pts[1:]]
                cur.append("Z")
                last = pts[0]
            elif op in ("f", "f*", "F", "S", "s", "B", "B*", "b", "b*", "n"):
                if len(cur) > 1:
                    subs.append(cur)
                if op != "n" and subs:
                    scale = math.hypot(ctm[0], ctm[1]) or 1.0
                    self.paths.append(
                        dict(
                            d=" ".join(seg for sub in subs for seg in sub),
                            fill=fill if op in ("f", "f*", "F", "B", "B*", "b", "b*") else None,
                            even_odd=op.endswith("*"),
                            stroke=stroke if op in ("S", "s", "B", "B*", "b", "b*") else None,
                            stroke_width=lw * scale,
                        )
                    )
                cur, subs, start_pt = [], [], None
            elif op in ("W", "W*"):
                pass
            elif op == "rg":
                fill = tuple(round(255 * v) for v in n(3))
            elif op == "RG":
                stroke = tuple(round(255 * v) for v in n(3))
            elif op == "g":
                fill = tuple([round(255 * n(1)[0])] * 3)
            elif op == "G":
                stroke = tuple([round(255 * n(1)[0])] * 3)
            elif op == "k":
                fill = cmyk_to_rgb(*n(4))
            elif op == "K":
                stroke = cmyk_to_rgb(*n(4))
            elif op in ("sc", "scn"):
                if len(nums) >= 3:
                    fill = tuple(round(255 * v) for v in nums[-3:])
                elif len(nums) == 1:
                    fill = tuple([round(255 * nums[-1])] * 3)
            elif op in ("SC", "SCN"):
                if len(nums) >= 3:
                    stroke = tuple(round(255 * v) for v in nums[-3:])
            elif op == "w":
                lw = n(1)[0]
            elif op == "Do":
                names = [v for v in operands if isinstance(v, str) and v.startswith("/")]
                if names:
                    ref = self.xobjects.get(names[-1][1:])
                    if ref is not None:
                        body = self.objects.get(ref, b"")
                        if b"/Subtype" in body and b"/Image" in body:
                            # A PDF image always occupies the unit square in its
                            # own space, so the CTM at the Do *is* its placement
                            # rectangle. y is flipped into SVG convention here so
                            # it matches the path coordinates.
                            corners = [mapply(ctm, x, y) for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
                            xs = [c[0] for c in corners]
                            ys = [self.H - c[1] for c in corners]
                            self.images.append(
                                dict(
                                    name=names[-1][1:],
                                    obj=ref,
                                    ctm=[round(v, 4) for v in ctm],
                                    bbox_pt=[min(xs), min(ys), max(xs), max(ys)],
                                    bbox_mm=[round(v * PT_TO_MM, 2) for v in (min(xs), min(ys), max(xs), max(ys))],
                                )
                            )
                        elif b"/Subtype" in body and b"/Form" in body:
                            mtx = re.search(rb"/Matrix\s*\[([^\]]*)\]", body)
                            sub_ctm = ctm
                            if mtx:
                                vals = [float(x) for x in mtx.group(1).split()]
                                if len(vals) == 6:
                                    sub_ctm = mmul(vals, ctm)
                            inner = stream_of(body)
                            if inner:
                                self.run(inner, sub_ctm, depth + 1)
            operands = []


# ------------------------------------------------------------------ rendering
def flatten(d, steps=24):
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


def extract_images(objects, outdir):
    """Write every embedded raster image out as a PNG.

    The two that matter are stencils rather than pictures: the association's
    three-swoosh mark, and the SCARPA lockup (stored as an indexed image plus a
    separate soft-mask object -- the mask is the legible one, and is what gets
    used as ink). Anything more exotic than 8-bit gray/RGB/CMYK is skipped
    rather than guessed at; this artwork contains nothing else.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for num, body in objects.items():
        head = body[: body.find(b"stream")]
        if b"/Subtype" not in head or b"/Image" not in head:
            continue

        def num_key(key, default=None):
            m = re.search(rb"/" + key + rb"\s+(\d+)", head)
            return int(m.group(1)) if m else default

        w, h = num_key(b"Width"), num_key(b"Height")
        bpc = num_key(b"BitsPerComponent", 8)
        if not w or not h:
            continue
        raw = stream_of(body)
        if raw is None or b"FlateDecode" not in head or bpc != 8:
            continue
        mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(len(raw) // (w * h))
        if not mode:
            continue
        path = outdir / f"img{num}_{w}x{h}.png"
        Image.frombytes(mode, (w, h), raw[: w * h * len(mode)]).save(path)
        written.append((num, w, h, mode, path.name))
    return written


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = PDF.read_bytes()
    objects = load_objects(data)

    page_num, page_body = next((n, b) for n, b in objects.items() if re.search(rb"/Type\s*/Page[^s]", b))
    mb = re.search(rb"/MediaBox\s*\[([^\]]*)\]", page_body) or re.search(rb"/MediaBox\s*\[([^\]]*)\]", data)
    W, H = [float(x) for x in mb.group(1).split()][2:4]

    xobjects = {}
    for m in re.finditer(rb"/([A-Za-z0-9_\.\-]+)\s+(\d+)\s+\d+\s+R", page_body):
        xobjects[m.group(1).decode()] = int(m.group(2))
    for n, b in objects.items():
        if b"/XObject" in b:
            for m in re.finditer(rb"/([A-Za-z0-9_\.\-]+)\s+(\d+)\s+\d+\s+R", b):
                xobjects.setdefault(m.group(1).decode(), int(m.group(2)))

    cont = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page_body)
    content = stream_of(objects[int(cont.group(1))])

    interp = Interp(H, objects, xobjects)
    interp.run(content)
    paths = interp.paths

    # bboxes, for identifying which paths are which design element
    report = []
    for k, p in enumerate(paths):
        pts = [pt for sub in flatten(p["d"], steps=8) for pt in sub]
        if not pts:
            continue
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        report.append(
            dict(
                index=k,
                fill=("#%02x%02x%02x" % p["fill"]) if p["fill"] else None,
                stroke=("#%02x%02x%02x" % p["stroke"]) if p["stroke"] else None,
                stroke_width_pt=round(p["stroke_width"], 3),
                bbox_pt=[round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)],
                bbox_mm=[round(v * PT_TO_MM, 2) for v in (min(xs), min(ys), max(xs), max(ys))],
                points=len(pts),
            )
        )

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W*PT_TO_MM:.2f}mm" '
        f'height="{H*PT_TO_MM:.2f}mm" viewBox="0 0 {W:.2f} {H:.2f}">'
    ]
    for p in paths:
        style = ""
        if p["fill"]:
            style += 'fill="#%02x%02x%02x" ' % p["fill"]
            if p["even_odd"]:
                style += 'fill-rule="evenodd" '
        else:
            style += 'fill="none" '
        if p["stroke"]:
            style += 'stroke="#%02x%02x%02x" stroke-width="%.3f" ' % (*p["stroke"], p["stroke_width"])
        svg.append(f'  <path {style}d="{p["d"]}"/>')
    svg.append("</svg>")
    (OUT / "official-artwork.svg").write_text("\n".join(svg))

    (OUT / "official-artwork.json").write_text(
        json.dumps(
            dict(
                source=PDF.name,
                page_pt=[W, H],
                page_mm=[round(W * PT_TO_MM, 2), round(H * PT_TO_MM, 2)],
                pt_to_mm=PT_TO_MM,
                operators=dict(interp.opcount.most_common()),
                images=interp.images,
                paths=report,
            ),
            indent=2,
        )
    )

    ss = 2
    img = Image.new("RGB", (int(W * ss), int(H * ss)), (200, 200, 205))
    dr = ImageDraw.Draw(img)
    for p in paths:
        for sub in flatten(p["d"]):
            pts = [(x * ss, y * ss) for x, y in sub]
            if p["fill"] and len(pts) > 2:
                try:
                    dr.polygon(pts, fill=p["fill"])
                except Exception:
                    pass
            if p["stroke"] and len(pts) > 1:
                dr.line(pts, fill=p["stroke"], width=max(1, int(round(p["stroke_width"] * ss))))
    img.resize((int(W * ss / 2), int(H * ss / 2)), Image.LANCZOS).save(OUT / "official-artwork.png")

    print(f"page {W} x {H} pt  =  {W*PT_TO_MM:.1f} x {H*PT_TO_MM:.1f} mm")
    print(f"paths: {len(paths)}   ops: {dict(interp.opcount.most_common(12))}")
    fills = Counter(r["fill"] for r in report if r["fill"])
    print("fill colours by path count:")
    for c, n in fills.most_common():
        print(f"   {c}  x{n}")
    for num, iw, ih, mode, fname in extract_images(objects, OUT / "pdf-images"):
        print(f"image obj {num:>3}: {iw} x {ih} {mode:<5} -> pdf-images/{fname}")
    print(f"wrote {OUT/'official-artwork.svg'}, .json, .png, pdf-images/")


if __name__ == "__main__":
    main()
