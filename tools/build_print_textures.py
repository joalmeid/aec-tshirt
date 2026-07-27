#!/usr/bin/env python3
"""Compose one base-colour texture per pattern panel, in pattern millimetres.

The whole point of this file is that it never guesses at pixels. Every design
element is positioned by an affine that maps the official artwork's own
millimetre coordinates onto the panel's flat-pattern millimetre coordinates, so
a change here is a change in real garment measurements.

Why this works at all: the print artwork PDF is a technical flat drawn at
*flat-pattern* proportions, not at projected-garment proportions -- a t-shirt
laid flat measures half its chest circumference across, which is exactly what
the front pattern piece measures. Fitting the artwork's torso silhouette onto
the pattern piece therefore needs only a scale and a translate, and the two axes
independently agree to within 3% (front 6.534 vs 6.370, back 6.533 vs 6.556).

Nothing is clipped to the panel outline on purpose. Artwork is drawn full-bleed
past the panel edge and the mesh's own UV island does the clipping, so the print
terminates exactly on the neckline, armhole, shoulder and hem at geometry
precision rather than texture precision -- and there is no island border for
mip-mapping to bleed against.

Run:  python3 tools/build_print_textures.py
"""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

import vectorart

# ------------------------------------------------------------------ convention
# A panel texture is authored as "the panel seen from OUTSIDE, laid flat" --
# x runs left-to-right exactly as you'd see it looking at that panel from
# outside the garment, which is the same convention the technical flat uses.
# That is why artwork x maps straight through with no flip.
#
# This is also raw pattern-u order, so the whole mapping is simply
#
#   texture_x_mm = pattern_u_mm
#
# and Babylon needs a POSITIVE uScale. Checked against the model rather than
# assumed: for each panel, does u increase toward the right when that panel is
# viewed from outside?
#
#   front               corr(u, X) = +0.99   seen from +Z   yes
#   back                corr(u, X) = -0.99   seen from -Z   yes
#   Sleeves_Node_6      corr(u, Z) = -0.77   seen from +X   yes
#   Sleeves_Node_7      corr(u, Z) = +0.77   seen from -X   yes
#
# All four agree, so there is no per-panel special case.
#
# An earlier version had this backwards and compensated with a negative uScale.
# The cause was tools/preview_render.py building its camera basis with the wrong
# handedness, which mirrored every render used to "verify" the convention. If
# something here ever looks mirrored again, suspect that tool before this file.
#
# Placement on a sleeve, which is the tube unrolled: the outer face of BOTH
# sleeves is at texture x ~198mm. The front of the sleeve is x~100 on
# Sleeves_Node_6 (wearer's left) and x~300 on Node_7 (wearer's right).

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "source" / "pattern"
OUT = ROOT / "assets" / "textures"

BODY_WHITE = (252, 252, 252)

# ---------------------------------------------------------------- design spec
# Artwork-space landmarks, straight out of source/artwork/official-artwork.json.
ART_FRONT_TORSO = (34.9, 45.0, 113.2, 155.4)  # path 0, the front body silhouette
ART_BACK_TORSO = (151.4, 44.2, 229.7, 155.4)  # path 69, the back body silhouette

# Which artwork paths belong to which design element.
BODY_STRIPES_FRONT = list(range(1, 7)) + list(range(27, 33)) + [46, 47, 48]
SHOULDER_STRIPES_FRONT = list(range(88, 97))
LOCKUP = list(range(97, 121))
BODY_STRIPES_BACK = list(range(57, 63)) + list(range(70, 76))

# The two logos are raster stencils inside the PDF (white = ink), recovered by
# tools/pdf_to_svg.py along with the exact placement rectangle each one is drawn
# into. The association mark sits on the chest and can therefore ride the same
# torso fit as everything else; SCARPA sits on a sleeve and has to be placed in
# sleeve-pattern millimetres instead.
STENCILS = ROOT / "source" / "artwork" / "pdf-images"
MARK_STENCIL = STENCILS / "img25_371x305.png"
SCARPA_STENCIL = STENCILS / "img44_8214x984.png"
INK = (34, 34, 33)  # #222221, the artwork's own black

ART_MARK_BOX = (71.25, 65.61, 76.56, 69.98)  # obj 25 placement, artwork mm

# SCARPA's placement on the sleeve, as fractions of the sleeve pattern piece so
# the intent survives a change of panel size.
#
# u: 0.5 is the outer face of the tube -- the outermost point of BOTH sleeves
#    sits at half the unrolled width -- so the badge faces squarely out to the
#    wearer's left and reads in full from a side view.
#
# v: 0 is the sleeve cap (shoulder), 1.0 the cuff. Note that pattern v is NOT
#    linear with how far down the sleeve the badge LOOKS: the top of the pattern
#    is the cap curving up into the armhole, so it compresses on screen.
#    Measured on the outward-facing half of the tube:
#
#      pattern v    17%  34%  49%  59%  69%  75%  83%  93%
#      looks like   13%  24%  34%  42%  59%  66%  72%  79%
#
#    The brief is "a quarter of the way up from the cuff", judged by eye off a
#    render, so it is a fraction of the VISIBLE sleeve -- 75% down it. That is
#    pattern v 0.877, not 0.75. Placing it at 0.75 lands at 66% and still reads
#    as too high.
SCARPA_ACROSS = 0.5
SCARPA_ALONG = 0.877
SCARPA_W_MM = 105.0
SCARPA_H_MM = 12.6

# Palette read straight off the vector artwork.
STRIPE_LIGHT = "#c0d174"
STRIPE_MID = "#98a64f"
STRIPE_DARK = "#6e7a33"
STRIPE_CYCLE = [STRIPE_LIGHT, STRIPE_MID, STRIPE_DARK]

# Stripe geometry measured on the artwork (perpendicular width 2.19mm,
# horizontal pitch 3.70mm, 10.44 deg from vertical) scaled by the torso fit
# factor of ~6.45 into real garment millimetres.
GARMENT_STRIPE_PITCH_MM = 3.70 * 6.45
GARMENT_STRIPE_WIDTH_MM = 2.23 * 6.45
GARMENT_STRIPE_ANGLE_DEG = 10.44

# Stripes are extended along their own long axis before drawing, so they bleed
# past the panel rather than stopping where the technical flat's silhouette
# happened to crop them.
STRIPE_EXTEND_MM = 260.0

PANELS = {
    "front": dict(
        px_per_mm=3.0,
        fit=ART_FRONT_TORSO,
        ops=[
            dict(kind="paths", paths=BODY_STRIPES_FRONT, extend=STRIPE_EXTEND_MM),
            # The shoulder block is deliberately NOT extended: unlike the body
            # stripes it is a closed wedge whose slanted top edge follows the
            # shoulder seam and whose bottom edge is the design's own cut-off.
            # Lengthening it along its axis turns it into full-height diagonals.
            dict(kind="paths", paths=SHOULDER_STRIPES_FRONT, extend=0.0),
            dict(kind="paths", paths=LOCKUP, extend=0.0),
            dict(kind="stencil", stencil=MARK_STENCIL, art_box=ART_MARK_BOX, colour=INK),
        ],
    ),
    "back": dict(
        px_per_mm=2.0,
        fit=ART_BACK_TORSO,
        ops=[dict(kind="paths", paths=BODY_STRIPES_BACK, extend=STRIPE_EXTEND_MM)],
    ),
    # Sleeves are not fitted from the technical flat: a sleeve pattern piece is
    # the tube unrolled (397mm around x 204mm long) while the flat draws the
    # sleeve from one side only, so no bbox fit relates the two. Everything on a
    # sleeve is therefore placed directly in sleeve-panel millimetres.
    #
    # sleeve_r is the wearer's RIGHT sleeve (Sleeves_Node_7, world x<0, which
    # renders on the viewer's left) and is the striped one in the reference.
    # sleeve_l is the wearer's LEFT (Node_6, x>0) and carries SCARPA only.
    "sleeve_r": dict(
        px_per_mm=3.0,
        fit=None,
        ops=[
            dict(
                kind="stripes",
                x_start=-20.0,
                count=20,
                pitch=GARMENT_STRIPE_PITCH_MM,
                width=GARMENT_STRIPE_WIDTH_MM,
                angle=GARMENT_STRIPE_ANGLE_DEG,
                cycle=STRIPE_CYCLE,
            )
        ],
    ),
    "sleeve_l": dict(
        px_per_mm=3.0,
        fit=None,
        ops=[
            dict(
                kind="stencil",
                stencil=SCARPA_STENCIL,
                centre_frac=(SCARPA_ACROSS, SCARPA_ALONG),
                size_mm=(SCARPA_W_MM, SCARPA_H_MM),
                colour=INK,
            ),
        ],
    ),
    "collar_a": dict(px_per_mm=4.0, fit=None, ops=[]),
    "collar_b": dict(px_per_mm=4.0, fit=None, ops=[]),
}

SS = 3  # supersample factor; PIL polygons have no antialiasing of their own


def fit_transform(art_bbox, panel_w, panel_h):
    """Affine mapping artwork mm -> pattern mm, fitting one bbox onto the panel.

    Kept as independent x/y scales rather than forced uniform: the two differ by
    under 3% and that difference is real (the technical flat's hem and shoulder
    are drawn slightly inside the pattern piece's extremes).
    """
    ax0, ay0, ax1, ay1 = art_bbox
    sx = panel_w / (ax1 - ax0)
    sy = panel_h / (ay1 - ay0)
    return lambda x, y: ((x - ax0) * sx, (y - ay0) * sy)


def extend_polygon(pts, amount):
    """Lengthen a stripe along its own long axis, for full bleed."""
    if amount <= 0 or len(pts) < 3:
        return pts
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    best, axis = 0.0, (0.0, 1.0)
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d > best:
            best, axis = d, ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
    mid = cx * axis[0] + cy * axis[1]
    out = []
    for x, y in pts:
        s = amount if (x * axis[0] + y * axis[1]) > mid else -amount
        out.append((x + axis[0] * s, y + axis[1] * s))
    return out


def paste_stencil(img, stencil_path, colour, box_mm, px_per_mm, rotate_deg=0.0):
    """Stamp a white-on-black stencil into the panel as flat ink.

    box_mm is (x0, y0, x1, y1) in the destination panel's own millimetres, and
    describes the logo *before* rotation, so changing the angle never changes
    how big the logo is.
    """
    x0, y0, x1, y1 = box_mm
    w = max(1, int(round((x1 - x0) * px_per_mm)))
    h = max(1, int(round((y1 - y0) * px_per_mm)))
    mask = Image.open(stencil_path).convert("L").resize((w, h), Image.LANCZOS)
    ink = Image.new("RGB", (w, h), colour)
    if rotate_deg:
        mask = mask.rotate(rotate_deg, resample=Image.BICUBIC, expand=True)
        ink = ink.resize(mask.size)
    cx = (x0 + x1) / 2 * px_per_mm
    cy = (y0 + y1) / 2 * px_per_mm
    img.paste(ink, (int(round(cx - mask.width / 2)), int(round(cy - mask.height / 2))), mask)


def draw_stripe_band(draw, x_start_mm, count, pitch_mm, width_mm, angle_deg, height_mm, px_per_mm, cycle):
    """Draw a run of parallel diagonal stripes directly in panel millimetres.

    Used for the sleeves only. The torso takes its stripes from the artwork's own
    vector paths, but a sleeve pattern piece is the tube unrolled and no bbox fit
    relates it to the technical flat's side-on sleeve, so these are placed
    natively instead.

    angle_deg is measured from vertical, positive leaning right going down, to
    match how the artwork's stripes were measured.
    """
    t = math.tan(math.radians(angle_deg))
    over = height_mm * 1.5
    for i in range(count):
        x = x_start_mm + i * pitch_mm
        top, bot = -over, height_mm + over
        pts = [
            (x + t * top, top),
            (x + width_mm + t * top, top),
            (x + width_mm + t * bot, bot),
            (x + t * bot, bot),
        ]
        draw.polygon([(px * px_per_mm, py * px_per_mm) for px, py in pts], fill=cycle[i % len(cycle)])


def draw_element(draw, paths, indices, art_to_pattern, px_per_mm, extend):
    wanted = set(indices)
    for p in paths:
        if p["index"] not in wanted or not p["fill"]:
            continue
        for sub in vectorart.subpaths(p["d"]):
            mm = [art_to_pattern(x * vectorart.PT_TO_MM, y * vectorart.PT_TO_MM) for x, y in sub]
            mm = extend_polygon(mm, extend)
            pts = [(x * px_per_mm, y * px_per_mm) for x, y in mm]
            if len(pts) > 2:
                draw.polygon(pts, fill=p["fill"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    panels = json.loads((PATTERN / "panels.json").read_text())["panels"]
    art = vectorart.load()

    for name, spec in PANELS.items():
        pm = panels[name]["pattern_mm"]
        w_mm, h_mm = pm["width"], pm["height"]
        ppm = spec["px_per_mm"]
        w = int(round(w_mm * ppm))
        h = int(round(h_mm * ppm))

        img = Image.new("RGB", (w * SS, h * SS), BODY_WHITE)
        d = ImageDraw.Draw(img)
        ppmss = ppm * SS
        xf = fit_transform(spec["fit"], w_mm, h_mm) if spec["fit"] else None

        for op in spec["ops"]:
            if op["kind"] == "paths":
                draw_element(d, art, op["paths"], xf, ppmss, op["extend"])
            elif op["kind"] == "stripes":
                draw_stripe_band(
                    d,
                    op["x_start"],
                    op["count"],
                    op["pitch"],
                    op["width"],
                    op["angle"],
                    h_mm,
                    ppmss,
                    op["cycle"],
                )
            elif op["kind"] == "stencil":
                box = op.get("box")
                if box is None and "centre_frac" in op:
                    # Positioned as a fraction of the panel, sized in real
                    # millimetres -- moving it never resizes it.
                    cx = op["centre_frac"][0] * w_mm
                    cy = op["centre_frac"][1] * h_mm
                    sw, sh = op["size_mm"]
                    box = (cx - sw / 2, cy - sh / 2, cx + sw / 2, cy + sh / 2)
                if box is None:
                    ax0, ay0, ax1, ay1 = op["art_box"]
                    p0, p1 = xf(ax0, ay0), xf(ax1, ay1)
                    box = (p0[0], p0[1], p1[0], p1[1])
                paste_stencil(img, op["stencil"], op["colour"], box, ppmss, op.get("rotate", 0.0))
                d = ImageDraw.Draw(img)

        img = img.resize((w, h), Image.LANCZOS)
        path = OUT / f"print-{name}.png"
        img.save(path)
        print(f"{name:9s} {w:5d} x {h:5d} px  ({ppm} px/mm)  {w_mm:.1f} x {h_mm:.1f} mm  -> {path.name}")


if __name__ == "__main__":
    main()
