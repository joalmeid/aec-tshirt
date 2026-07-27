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

import numpy as np
from PIL import Image, ImageDraw

import seams
import vectorart
from glb import Glb

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
# Across the tube: 0.5 is the outer face -- the outermost point of BOTH sleeves
# sits at half the unrolled width -- so the badge faces squarely out to the
# wearer's left and reads in full from a side view.
#
# Along the sleeve: given as a real distance up from the cuff hem rather than a
# fraction, because fractions are treacherous here. Pattern v is NOT linear with
# how far down the sleeve the badge LOOKS: the top of the pattern is the cap
# curving up into the armhole, so it compresses on screen. Measured on the
# outward-facing half of the tube:
#
#   pattern v    17%  34%  49%  59%  69%  75%  83%  93%
#   looks like   13%  24%  34%  42%  59%  66%  72%  79%
#
# Since pattern space IS real millimetres of fabric, measuring up from the hem
# is unambiguous and survives any change of panel size.
SCARPA_ACROSS = 0.5
SCARPA_ABOVE_CUFF_MM = 50.0
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
                across_frac=SCARPA_ACROSS,
                above_bottom_mm=SCARPA_ABOVE_CUFF_MM,
                size_mm=(SCARPA_W_MM, SCARPA_H_MM),
                colour=INK,
            ),
        ],
    ),
    "collar_a": dict(px_per_mm=4.0, fit=None, ops=[]),
    "collar_b": dict(px_per_mm=4.0, fit=None, ops=[]),
}

SS = 3  # supersample factor; PIL polygons have no antialiasing of their own

# ------------------------------------------------------------------- stitching
# Style measured off the PSD's own "Stitches Shirt" layer: solid #515253, dashed,
# about 0.8mm wide with a 3mm dash and 1.5mm gap. That is ordinary topstitch
# spacing, so it is used as-is rather than invented. The layer is opaque, but it
# composites subtly in the mockup, so it is drawn here at partial alpha.
STITCH_RGB = (81, 82, 83)
STITCH_ALPHA = 140  # of 255
STITCH_WIDTH_MM = 0.8
STITCH_DASH_MM = 3.0
STITCH_GAP_MM = 1.5

# How far in from the cut edge the stitch sits. A seam is topstitched close to
# the edge; a hem or cuff is folded under first and stitched above the fold, so
# it sits much further in. Panels are keyed by how deep their bottom edge folds.
SEAM_INSET_MM = 6.0
HEM_INSET_MM = 20.0
HEM_BAND_MM = 45.0  # how far up from the bottom edge the hem rule ramps in

# The neckline is stitched much closer in than an ordinary seam, so the dashes
# hug the collar band the way the reference shows. Without this the row sits a
# full 6mm below the band and reads as a separate line floating on the chest.
NECK_INSET_MM = 2.5
NECK_NEAR_COLLAR_MM = 12.0  # 3D distance from the ribbing that counts as neckline

# The hem is double-needle stitched: two parallel rows. Measured off the PSD's
# stitch layer, where a vertical slice through the centre front crosses two
# lines 9px apart edge to edge -- about 5mm centre to centre at that mockup's
# scale, which is standard for a double-needle hem. Only the hem: the same test
# crosses exactly one line at the neckline and one at each cuff.
DOUBLE_ROW_MM = 5.0

# Sleeves are unprinted below the cuff stitch, leaving a plain white band to the
# edge. 20mm is not a free choice -- it is HEM_INSET_MM, so the print stops
# exactly where the cuff row is stitched, which is what the reference shows.
# Body panels get none of this: their stripes run through the hem stitching all
# the way to the bottom edge.
CUFF_UNPRINTED_MM = HEM_INSET_MM


# Which panel owns which seam. Every seam joins two pieces and both their island
# boundaries run along it, so without this the armhole gets stitched twice and
# the neckline three times (front panel plus both collar bands).
#
#   body panels  own the neckline, shoulders, armholes, sides and their own hem
#   sleeves      own only their cuff -- the armhole is already drawn by the body
#   collars      own nothing; the body panel's neckline stitch is that seam
STITCH_ZONE = {
    "front": "all",
    "back": "all",
    "sleeve_r": "hem_only",
    "sleeve_l": "hem_only",
    "collar_a": None,
    "collar_b": None,
}
SLEEVE_HEM_BAND_MM = 70.0  # how far up from the cuff still counts as its hem


def stitch_where(panel, height_mm):
    """Predicate over boundary points: is this stretch of seam stitched here?"""
    zone = STITCH_ZONE.get(panel, "all")
    if zone is None:
        return lambda u, v: False
    if zone == "hem_only":
        return lambda u, v: (height_mm - v) < SLEEVE_HEM_BAND_MM
    return None


def neckline_uv(mesh, pattern_mm, collar_meshes):
    """Pattern-space points on this panel's boundary that form the NECKLINE.

    Found from geometry rather than guessed from position: the neckline is
    whichever part of the boundary runs along the collar, so it is the boundary
    vertices sitting within a few millimetres of the ribbing meshes in 3D. That
    holds regardless of how the neck is shaped, where a rule like "v below some
    threshold and u near the middle" would need retuning for every panel.
    """
    if not collar_meshes:
        return np.empty((0, 2))
    collar = np.vstack([m["pos"] for m in collar_meshes])
    uv = mesh["uv"] - np.array([pattern_mm["u0"], pattern_mm["v0"]])
    limit = (NECK_NEAR_COLLAR_MM / 1000.0) ** 2  # positions are in metres

    out = []
    for loop in seams.boundary_loops(mesh["idx"]):
        pts = mesh["pos"][loop]
        # squared distance from each boundary point to the nearest collar vertex
        for i, p in enumerate(pts):
            if np.min(np.sum((collar - p) ** 2, axis=1)) < limit:
                out.append(uv[loop[i]])
    return np.array(out) if out else np.empty((0, 2))


def inset_with_neckline(panel, height_mm, neck_pts):
    """inset_fn that tightens along the neckline and deepens toward the hem."""
    base = inset_for(panel, height_mm)
    if len(neck_pts) == 0:
        return base

    def fn(u, v):
        d2 = np.min((neck_pts[:, 0] - u) ** 2 + (neck_pts[:, 1] - v) ** 2)
        if d2 < 6.0**2:
            return NECK_INSET_MM
        return base(u, v)

    return fn


def hem_row_where(panel, height_mm):
    """Where the SECOND stitch row goes: along a body panel's hem only."""
    if panel not in ("front", "back"):
        return lambda u, v: False
    return lambda u, v: (height_mm - v) < HEM_BAND_MM


def inset_for(panel, height_mm):
    """Return inset_fn(u, v) -> millimetres, deeper near a folded hem.

    Ramped rather than switched, so a single continuous boundary loop does not
    jump between two offsets where the hem meets the side seam.
    """
    hem_panels = {"front", "back", "sleeve_r", "sleeve_l"}
    if panel not in hem_panels:
        return lambda u, v: SEAM_INSET_MM

    def fn(u, v):
        d = height_mm - v  # distance up from the bottom edge
        if d >= HEM_BAND_MM:
            return SEAM_INSET_MM
        t = max(0.0, min(1.0, 1.0 - d / HEM_BAND_MM))
        return SEAM_INSET_MM + (HEM_INSET_MM - SEAM_INSET_MM) * t

    return fn


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


def draw_element(img, paths, indices, art_to_pattern, px_per_mm, extend):
    """Draw one design element. Contours of a path are filled as ONE shape, so
    the counters in A, O, R, D, 0 and 6 stay open -- see vectorart.fill_contours.
    """
    wanted = set(indices)
    for p in paths:
        if p["index"] not in wanted or not p["fill"]:
            continue
        contours = []
        for sub in vectorart.subpaths(p["d"]):
            mm = [art_to_pattern(x * vectorart.PT_TO_MM, y * vectorart.PT_TO_MM) for x, y in sub]
            mm = extend_polygon(mm, extend)
            contours.append([(x * px_per_mm, y * px_per_mm) for x, y in mm])
        vectorart.fill_contours(img, contours, p["fill"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    panels = json.loads((PATTERN / "panels.json").read_text())["panels"]
    art = vectorart.load()

    # Seams are read off the mesh itself -- an island boundary is a real cut
    # line on this model, because the UVs are the actual sewing pattern.
    glb = Glb(ROOT / "assets" / "tshirt.glb")
    meshes = {m["node"]: m for m in glb.meshes()}
    collar_meshes = [
        meshes[panels[p]["outer_node"]] for p in ("collar_a", "collar_b") if p in panels
    ]

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
                draw_element(img, art, op["paths"], xf, ppmss, op["extend"])
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
                if box is None and "across_frac" in op:
                    # Across the panel as a fraction, along it as millimetres up
                    # from the bottom edge, sized in real millimetres -- so
                    # moving it can never resize it.
                    cx = op["across_frac"] * w_mm
                    cy = h_mm - op["above_bottom_mm"]
                    sw, sh = op["size_mm"]
                    box = (cx - sw / 2, cy - sh / 2, cx + sw / 2, cy + sh / 2)
                if box is None:
                    ax0, ay0, ax1, ay1 = op["art_box"]
                    p0, p1 = xf(ax0, ay0), xf(ax1, ay1)
                    box = (p0[0], p0[1], p1[0], p1[1])
                paste_stencil(img, op["stencil"], op["colour"], box, ppmss, op.get("rotate", 0.0))
                d = ImageDraw.Draw(img)

        # Sleeves carry no print below the cuff stitch. Painted over the ops
        # rather than clipped out of them, so it applies whatever the sleeve is
        # printed with -- stripes today, anything later.
        if name in ("sleeve_r", "sleeve_l") and CUFF_UNPRINTED_MM > 0:
            top = (h_mm - CUFF_UNPRINTED_MM) * ppmss
            ImageDraw.Draw(img).rectangle([0, top, img.width, img.height], fill=BODY_WHITE)

        # Stitching goes on last so it sits over the print, the way real
        # topstitching runs across whatever the panel is printed with.
        mesh = meshes.get(panels[name]["outer_node"])
        runs = []
        if mesh is not None:
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            width_px = max(1, int(round(STITCH_WIDTH_MM * ppmss)))
            neck_pts = neckline_uv(mesh, pm, collar_meshes)
            primary = inset_with_neckline(name, h_mm, neck_pts)
            runs = seams.seam_polylines(
                mesh, pm, primary, STITCH_DASH_MM, STITCH_GAP_MM,
                where_fn=stitch_where(name, h_mm),
            )
            # Second row of the double-needle hem, offset further in. Run as a
            # separate pass rather than threaded through inset_fn: the row count
            # varies along the boundary, and splitting the loop twice for that
            # is far more code than simply asking for the rows we want.
            runs += seams.seam_polylines(
                mesh,
                pm,
                lambda u, v: primary(u, v) + DOUBLE_ROW_MM,
                STITCH_DASH_MM,
                STITCH_GAP_MM,
                where_fn=hem_row_where(name, h_mm),
            )
            for run in runs:
                od.line(
                    [(x * ppmss, y * ppmss) for x, y in run],
                    fill=STITCH_RGB + (STITCH_ALPHA,),
                    width=width_px,
                    joint="curve",
                )
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

        img = img.resize((w, h), Image.LANCZOS)
        path = OUT / f"print-{name}.png"
        img.save(path)
        print(
            f"{name:9s} {w:5d} x {h:5d} px  ({ppm} px/mm)  {w_mm:.1f} x {h_mm:.1f} mm  "
            f"stitch-dashes={len(runs):5d}  -> {path.name}"
        )


if __name__ == "__main__":
    main()
