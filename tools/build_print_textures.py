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
PATTERN = ROOT / "pipeline-design" / "pattern"
OUT = ROOT / "assets" / "textures"

BODY_WHITE = (252, 252, 252)

# ---------------------------------------------------------------- design spec
# Artwork-space landmarks, straight out of pipeline-design/artwork/official-artwork.json.
ART_FRONT_TORSO = (34.9, 45.0, 113.2, 155.4)  # path 0, the front body silhouette
ART_BACK_TORSO = (151.4, 44.2, 229.7, 155.4)  # path 67, the back body silhouette

# Which artwork paths belong to which design element.
#
# These indices are the per-event work: the PDF has no names, only 120 anonymous
# paths, so which index is which element has to be re-derived every time the
# artwork changes. Derive them, do not shift them by hand -- select on fill
# colour, bbox height and which half of the page the path sits in, then read the
# result. The final-artwork revision deleted two paths near the start and
# inserted one in the middle, so a uniform offset would have been wrong in both
# directions at once.
#
# Groups below, as derived from official-artwork.json:
#   front body   full-height (h>100mm) greens with x < 130mm
#   back body    the same with x >= 130mm
#   accent       front greens of middle height (30 < h <= 100mm)
#   shoulder     front greens of h <= 30mm, up at the shoulder (y 45..63)
#   lockup       the chest wordmark, ink + light-green letters, y 74..91
BODY_STRIPES_FRONT = list(range(1, 5)) + list(range(25, 31)) + [44, 45, 46]
SHOULDER_STRIPES_FRONT = list(range(87, 96))
LOCKUP = list(range(96, 120))
BODY_STRIPES_BACK = list(range(55, 61)) + list(range(68, 75))

# NOT drawn, deliberately: the artwork's eight #383838 charcoal shapes. They are
# the presentation flat's drop SHADOWS -- the side/underarm shading that makes
# the mockup read as a photographed garment -- not printed panels. Confirmed
# with the organisers. They have never been in the texture and must not be
# added; the shirt is white with green stripes. Left recorded here because
# "the artwork has eight paths we never draw" otherwise reads as an oversight.

# The two logos are raster stencils inside the PDF (white = ink), recovered by
# tools/pdf_to_svg.py along with the exact placement rectangle each one is drawn
# into. The association mark sits on the chest and can therefore ride the same
# torso fit as everything else; SCARPA sits on a sleeve and has to be placed in
# sleeve-pattern millimetres instead.
STENCILS = ROOT / "pipeline-design" / "artwork" / "pdf-images"
MARK_STENCIL = STENCILS / "img25_371x305.png"
SCARPA_STENCIL = STENCILS / "img44_8214x984.png"
INK = (34, 34, 33)  # #222221, the artwork's own black

ART_MARK_BOX = (71.96, 67.03, 77.26, 71.39)  # obj 25 placement, artwork mm

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

# Compressport, on the upper back below the neck. A 2026 sponsor requirement
# that is NOT in the print artwork -- the PDF predates it -- so unlike every
# other element here it has no artwork-space coordinates to be fitted from. It
# is placed directly in back-panel millimetres, the same way SCARPA is.
#
# The stencil is rendered from the supplied vector lockup by
# tools/make_logo_stencil.py. Only the width is given: the height follows from
# the stencil's own aspect ratio, so the logo can never come out stretched, and
# re-rendering the stencil cannot silently change its proportions on the shirt.
#
# Both numbers are read off the supplier's mockup and should be treated as a
# starting point rather than a specification:
#
#   Width came from the mockup by scaling against the ALIMENTA lockup, whose
#   real printed width the pipeline already knows (247mm). The logo measured
#   41px against the wordmark's 83px, giving ~122mm. Rounded to 120.
#
#   Vertical position did NOT come from the mockup, and deliberately. That image
#   is a 3/4 view of a worn garment, so it is foreshortened AND draped: solving
#   the wordmark's scale from its top position gives 12.6 mm/px while solving it
#   from its height gives 3.2 mm/px, a 4x disagreement. Any millimetre read off
#   it vertically is fiction. This is instead set from the pattern: the
#   centre-back neck seam sits at y ~= 45mm (where panels.json's back row
#   profile closes its neck gap), and the logo centre is placed a hand's width
#   below it.
COMPRESSPORT_STENCIL = ROOT / "pipeline-design" / "artwork" / "logo-compressport.png"
COMPRESSPORT_ACROSS = 0.5  # centred on the back
COMPRESSPORT_BELOW_TOP_MM = 95.0  # centre, from the panel's top edge (~50mm below the neck seam)
COMPRESSPORT_W_MM = 120.0

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
        ops=[
            dict(kind="paths", paths=BODY_STRIPES_BACK, extend=STRIPE_EXTEND_MM),
            dict(
                kind="stencil",
                stencil=COMPRESSPORT_STENCIL,
                across_frac=COMPRESSPORT_ACROSS,
                below_top_mm=COMPRESSPORT_BELOW_TOP_MM,
                width_mm=COMPRESSPORT_W_MM,
                colour=INK,
            ),
        ],
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

# ---------------------------------------------------------------- seam rules
# Every seam is classified from the mesh, then stitched as its own run. What a
# stretch of boundary IS gets decided by what it is sewn to -- proximity in 3D to
# the collar, a sleeve, or the opposite body panel -- which needs no coordinate
# thresholds and survives a change of pattern.
#
# The previous version offset each panel's whole boundary as one curve, with an
# inset that varied by height. That produced every stitching defect at once: the
# deep hem inset also applied to points low on the SIDE seams, whose inward
# direction is horizontal, so those lines swung ~14mm sideways and read as a
# spurious rising diagonal; and one continuous curve made the stitch turn every
# corner, where an angle-bisector offset overshoots or self-intersects.
# 5mm is this design's double spacing throughout: it is the hem's double-needle
# row gap, and it is what the neckline produces across the shoulder seam, since
# front and back each topstitch their own side of it at 2.5mm.
#
# A seam joining two panels therefore shows a pair of rows 2 x inset apart. That
# is worth keeping in mind when reading the numbers below -- the shoulder sat at
# 6mm, which looks unremarkable in isolation but rendered as a 12mm gap, twice
# as wide as everything else on the garment and visibly wrong next to the tight
# pair the neckline makes a few centimetres away.
DOUBLE_GAP_MM = 5.0

SEAM_SPEC = {
    "neck": dict(inset=DOUBLE_GAP_MM / 2, rows=1),
    "shoulder": dict(inset=DOUBLE_GAP_MM / 2, rows=1),
    # Matched to the shoulder so the two MEET at the shoulder tip. They end at
    # the same boundary point, so any difference in inset shows up there as a
    # perpendicular step -- at 6mm against the shoulder's 2.5mm that was a 3.5mm
    # displacement, reading as a broken corner rather than a join.
    #
    # The knock-on is at the other end, where the armhole now meets the side
    # seam 3.5mm off instead of flush. That is accepted: it puts the junction a
    # little higher up the side, which is where a real armhole ends anyway.
    "armhole": dict(inset=DOUBLE_GAP_MM / 2, rows=1),
    # Matched to the armhole for the same reason the armhole was matched to the
    # shoulder: they end on a shared boundary point at the armpit, so unequal
    # insets show up there as a perpendicular step rather than a join.
    "side": dict(inset=DOUBLE_GAP_MM / 2, rows=1),
    # The only double-needle seam, measured off the PSD: two rows 5mm apart.
    # close_ring for the same reason as the cuff: the body's hem is a continuous
    # loop once the side seams are sewn, so both rows are carried out to the
    # panel's side edges. Without it the front and back hems stop short of each
    # other, and the side seam's stitch comes down past a hem line that is not
    # there to meet it.
    "hem": dict(inset=20.0, rows=2, row_gap=DOUBLE_GAP_MM, close_ring=True),
    # Trimmed harder than the rest: a sleeve's bottom corners are rounded, so
    # the cuff run curves up into the underarm over its last ~15mm and offsetting
    # that leaves a hook. Two hooks meeting once the tube is sewn read as a cross
    # under the cuff.
    "cuff": dict(inset=20.0, rows=1, trim=16.0, close_ring=True),
    # A sleeve's armhole is already drawn by the body panel it is sewn to, and
    # the underarm is an enclosed seam with no topstitching.
    "sleeve_armhole": None,
    "underarm": None,
}

# Default: runs are NOT trimmed, so a seam reaches the seam it meets.
#
# Trimming exists for one case -- a run whose own last points curve into a
# rounded corner, where offsetting faithfully follows that curve and leaves a
# hook. That is the cuff, which overrides this below.
#
# Applying it everywhere was a mistake worth remembering. Trim is taken off BOTH
# runs at a junction, so 5mm each became a 10mm gap; on the 107mm shoulder seam
# that removed 20mm and left it visibly floating, connected to neither the
# neckline nor the armhole. Runs already end square thanks to the one-sided
# normals in seams.offset_run, so there is nothing here for a trim to fix.
STITCH_TRIM_MM = 0.0

NEAR_COLLAR_MM = 12.0
NEAR_PIECE_MM = 8.0

# Sleeves carry no print below the cuff stitch, leaving a plain white band to the
# edge. Read from the spec rather than repeated, so the print always stops
# exactly where the cuff is stitched however that inset is retuned. Body panels
# get none of this: their stripes run through the hem stitching to the edge.
CUFF_UNPRINTED_MM = SEAM_SPEC["cuff"]["inset"]


def classify_boundary(panel, loop_pos, loop_uv, height_mm, neighbours):
    """Label every point of a boundary loop with the seam it belongs to.

    `neighbours["bodies"]` must EXCLUDE the panel being classified. Including it
    makes every point zero millimetres from "a body panel", so the whole boundary
    classifies as shoulder or side and the hem disappears entirely.
    """
    if panel.startswith("collar"):
        # The collar bands own no seam. The neckline they sit on is stitched by
        # the body panel, and drawing it here too put three concentric rows
        # around the neck.
        return np.full(len(loop_pos), "collar_edge", dtype=object)

    d_collar = seams.nearest_mm(loop_pos, neighbours["collar"])
    d_sleeve = seams.nearest_mm(loop_pos, neighbours["sleeves"])
    d_body = seams.nearest_mm(loop_pos, neighbours["bodies"])

    if panel in ("sleeve_r", "sleeve_l"):
        labels = np.full(len(loop_pos), "underarm", dtype=object)
        labels[d_body < NEAR_PIECE_MM] = "sleeve_armhole"
        # The cuff is the free bottom edge: the end of the tube, nowhere near
        # another piece.
        labels[(d_body >= NEAR_PIECE_MM) & (loop_uv[:, 1] > height_mm - 12.0)] = "cuff"
        return labels

    labels = np.full(len(loop_pos), "hem", dtype=object)
    near_body = d_body < NEAR_PIECE_MM
    armhole = d_sleeve < NEAR_PIECE_MM

    # Shoulder above the armhole, side seam below it. Split on the armhole's own
    # v-extent rather than at mid-panel: mid-panel lets "shoulder" leak down over
    # the upper half of the side seam, which is a different seam entirely.
    if armhole.any():
        top, bottom = loop_uv[armhole, 1].min(), loop_uv[armhole, 1].max()
    else:
        top = bottom = height_mm * 0.5
    labels[near_body & (loop_uv[:, 1] <= top)] = "shoulder"
    labels[near_body & (loop_uv[:, 1] >= bottom)] = "side"
    labels[armhole] = "armhole"
    labels[d_collar < NEAR_COLLAR_MM] = "neck"
    return labels


def panel_stitches(panel, mesh, pattern_mm, neighbours):
    """Every stitch dash for one panel, in pattern millimetres.

    Only the largest boundary loop is used. A panel's other loops are the inner
    shell's outline and thin rim bands that duplicate stretches of the same
    seams -- stitching them would double every line, and the narrowest of them
    collapse when offset.
    """
    loops = seams.boundary_loops(mesh["idx"])
    if not loops:
        return []
    loop = max(loops, key=len)
    origin = np.array([pattern_mm["u0"], pattern_mm["v0"]])
    loop_uv = mesh["uv"][loop] - origin
    labels = classify_boundary(panel, mesh["pos"][loop], loop_uv, pattern_mm["height"], neighbours)
    return seams.stitch_runs(
        loop_uv,
        labels,
        SEAM_SPEC,
        STITCH_DASH_MM,
        STITCH_GAP_MM,
        trim_mm=STITCH_TRIM_MM,
        span=(0.0, pattern_mm["width"]),
    )


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
    def positions(names):
        out = [meshes[panels[n]["outer_node"]]["pos"] for n in names if n in panels]
        return np.vstack(out) if out else np.empty((0, 3))

    def neighbours_for(panel):
        """Neighbour point clouds for classifying one panel, EXCLUDING itself."""
        return dict(
            collar=positions([n for n in ("collar_a", "collar_b") if n != panel]),
            sleeves=positions([n for n in ("sleeve_r", "sleeve_l") if n != panel]),
            bodies=positions([n for n in ("front", "back") if n != panel]),
        )

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
                    # Across the panel as a fraction, along it as millimetres
                    # from one edge, sized in real millimetres -- so moving it
                    # can never resize it.
                    #
                    # Measured up from the bottom for a sleeve badge (the cuff
                    # is the landmark) and down from the top for a back-neck
                    # logo (the neckline is). Both are real distances to a real
                    # garment feature, which is the point: a fraction of panel
                    # height would move if the pattern were ever regraded.
                    cx = op["across_frac"] * w_mm
                    if "above_bottom_mm" in op:
                        cy = h_mm - op["above_bottom_mm"]
                    else:
                        cy = op["below_top_mm"]
                    if "size_mm" in op:
                        sw, sh = op["size_mm"]
                    else:
                        # Height from the stencil's own aspect, so the logo
                        # cannot be stretched by giving it a wrong pair.
                        sw = op["width_mm"]
                        with Image.open(op["stencil"]) as st:
                            sh = sw * st.height / st.width
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
            runs = panel_stitches(name, mesh, pm, neighbours_for(name))
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
