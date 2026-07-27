#!/usr/bin/env python3
"""Generate a tileable knit-jersey normal map for the shirt's fabric.

The shirt is a technical polyester jersey, so the surface structure is columns
of interlocking loops -- wales running along the fabric, courses across it. A
jersey face is rows of Vs, and that is built here from the shape directly: two
legs per loop cell, spread apart at the top and converging toward the bottom
where the next course pulls through, plus the arc of the loop head.

An earlier version swayed a sine wave sideways once per course instead. That
drifts rather than oscillating symmetrically, and the result read as a diagonal
twill, not a knit.

Everything is built from functions periodic over the tile, so the result tiles
seamlessly by construction, with no edge blending to go wrong. The noise layer
is made periodic by filtering in the frequency domain, which is periodic for the
same reason.

The tile represents a REAL patch of fabric, TILE_MM across. That matters because
the model's UVs are in millimetres: setting the texture's uScale/vScale to
1/TILE_MM makes the weave repeat every TILE_MM of actual garment, at the same
density on every panel, with no per-panel tuning.

Run:  python3 tools/make_weave_normal.py
"""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "textures"

# 256 rather than 512: a loop is 0.83mm on a panel half a metre across, so at
# any realistic camera distance this detail is sub-pixel and mip-mapping averages
# it away regardless. 256 still gives 14 pixels per loop and costs 133KB instead
# of 475KB -- normal maps compress badly, and the fine fibre noise is the worst
# of it.
SIZE = 256
TILE_MM = 15.0  # the patch of real fabric this tile represents
WALES = 18  # loop columns across the tile  -> ~12 per cm
COURSES = 22  # loop rows down the tile      -> ~15 per cm
LEG_SPREAD = 0.30  # how far the two legs of each V sit from the wale centre
LEG_WIDTH = 0.17  # yarn thickness, as a fraction of a wale
HEIGHT_MM = 0.16  # peak-to-trough relief of the knit
FIBRE = 0.14  # weight of the fine fibre noise, relative to the loops


def periodic_noise(size, cutoff, seed=7):
    """Band-limited noise that tiles: filtering in frequency space is periodic."""
    rng = np.random.default_rng(seed)
    spec = np.fft.fft2(rng.normal(size=(size, size)))
    fy = np.fft.fftfreq(size) * size
    fx = np.fft.fftfreq(size) * size
    r = np.hypot(*np.meshgrid(fx, fy, indexing="ij"))
    spec *= np.exp(-((r / cutoff) ** 2))
    out = np.real(np.fft.ifft2(spec))
    return (out - out.mean()) / (out.std() + 1e-9)


def _wrap_dist(a, b):
    """Distance between two positions in a cell, wrapping at the cell edge."""
    d = np.abs(a - b)
    return np.minimum(d, 1.0 - d)


def height_field():
    t = (np.arange(SIZE) + 0.5) / SIZE
    x, y = np.meshgrid(t, t, indexing="xy")

    # Position within one loop cell. Working in cell coordinates is what keeps
    # the result tileable: WALES and COURSES are integers, so the cells divide
    # the tile exactly.
    cx = (x * WALES) % 1.0
    cy = (y * COURSES) % 1.0

    # A jersey face is rows of Vs: two legs that sit apart at the top of the
    # cell and converge toward the bottom, where the next course pulls through.
    # An earlier version swayed a sine continuously instead, which drifts and
    # reads as a diagonal twill rather than a knit.
    spread = LEG_SPREAD * (0.35 + 0.65 * (1.0 - cy))
    left = _wrap_dist(cx, 0.5 - spread)
    right = _wrap_dist(cx, 0.5 + spread)
    legs = np.maximum(
        np.exp(-((left / LEG_WIDTH) ** 2)),
        np.exp(-((right / LEG_WIDTH) ** 2)),
    )

    # The head of the loop, the arc crossing the top of the cell where the yarn
    # passes over the course above.
    head = np.exp(-((_wrap_dist(cy, 0.0) / 0.20) ** 2)) * np.exp(
        -((_wrap_dist(cx, 0.5) / 0.34) ** 2)
    )

    loops = np.maximum(legs, head * 0.85)

    h = loops + FIBRE * periodic_noise(SIZE, cutoff=SIZE / 6.0) * 0.25
    h -= h.min()
    h /= h.max()
    return h


def to_normal_map(h, height_mm, tile_mm):
    """Height field -> tangent-space normal map, with real-world slope."""
    mm_per_px = tile_mm / h.shape[0]
    # np.gradient with wrap-around keeps the map tileable at its edges
    dy, dx = np.gradient(np.pad(h, 1, mode="wrap") * height_mm, mm_per_px)
    dx, dy = dx[1:-1, 1:-1], dy[1:-1, 1:-1]

    n = np.stack([-dx, -dy, np.ones_like(dx)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    # OpenGL / glTF convention: +Y up. Babylon's bump shader expects this.
    return ((n * 0.5 + 0.5) * 255).astype(np.uint8)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    h = height_field()
    rgb = to_normal_map(h, HEIGHT_MM, TILE_MM)
    path = OUT / "knit-normal.png"
    Image.fromarray(rgb, "RGB").save(path, optimize=True)

    tiled = np.tile(rgb, (2, 2, 1))
    Image.fromarray(tiled, "RGB").save(OUT.parent.parent / "source" / "preview" / "knit-normal-tiled.png")

    slope = np.degrees(np.arctan(np.abs(np.gradient(h * HEIGHT_MM, TILE_MM / SIZE)[0])).max())
    print(f"{path.name}: {SIZE}x{SIZE} for a {TILE_MM:.0f}mm patch, {path.stat().st_size/1024:.0f}KB")
    print(f"  {WALES} wales x {COURSES} courses  =  {WALES/TILE_MM*10:.0f}/cm x {COURSES/TILE_MM*10:.0f}/cm")
    print(f"  relief {HEIGHT_MM}mm, max slope {slope:.0f} deg")
    print(f"  -> set the texture's uScale = vScale = 1/{TILE_MM:.0f} = {1/TILE_MM:.6f} and wrap mode WRAP")


if __name__ == "__main__":
    main()
