#!/usr/bin/env python3
"""Generate calibration textures, one per pattern panel.

Reasoning alone can't settle which way a panel's texture ends up facing: it
depends on the sign of the pattern's u<->world-X relationship, on whether the
glTF loader flips V, and on Babylon's left-handed camera. All three interact.
The Babylon asset-pipeline docs recommend exactly this instead -- "Using UV grid
textures for the early stages of asset creation can help determine texel density
and consistency".

Each texture carries enough asymmetric information to read off, in one render,
every fact we need:

  * a 10mm / 50mm millimetre grid, so texel density is directly measurable
  * coloured edges  -- TOP red, BOTTOM blue, LEFT green, RIGHT yellow
  * a large "F", which looks wrong under either a mirror or a 180 rotation
  * corner tags with their pattern coordinates in millimetres
  * an arrow pointing at the neckline end of the panel

Run:  python3 tools/make_calibration.py
Then load the scene and compare against what you see.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "source" / "pattern"
OUT = ROOT / "assets" / "textures"

PX_PER_MM = 2.0

EDGE_TOP = (220, 40, 40)
EDGE_BOTTOM = (40, 90, 230)
EDGE_LEFT = (40, 190, 90)
EDGE_RIGHT = (240, 200, 40)


def font(size):
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def build(panel, width_mm, height_mm):
    w = int(round(width_mm * PX_PER_MM))
    h = int(round(height_mm * PX_PER_MM))
    img = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(img)

    def X(mm):
        return mm * PX_PER_MM

    # grid
    mm = 0
    while mm <= width_mm:
        major = mm % 50 == 0
        d.line([(X(mm), 0), (X(mm), h)], fill=(120, 150, 200) if major else (215, 222, 232), width=2 if major else 1)
        mm += 10
    mm = 0
    while mm <= height_mm:
        major = mm % 50 == 0
        d.line([(0, X(mm)), (w, X(mm))], fill=(120, 150, 200) if major else (215, 222, 232), width=2 if major else 1)
        mm += 10

    # a big F, drawn from the panel's own proportions so it fills the space
    fw, fh = width_mm * 0.42, height_mm * 0.42
    ox, oy = width_mm * 0.29, height_mm * 0.30
    bar = min(fw, fh) * 0.20
    d.rectangle([X(ox), X(oy), X(ox + bar), X(oy + fh)], fill=(30, 30, 30))
    d.rectangle([X(ox), X(oy), X(ox + fw), X(oy + bar)], fill=(30, 30, 30))
    d.rectangle([X(ox), X(oy + fh * 0.45), X(ox + fw * 0.72), X(oy + fh * 0.45 + bar)], fill=(30, 30, 30))

    # edge bands
    band = max(4.0, min(width_mm, height_mm) * 0.02)
    d.rectangle([0, 0, w, X(band)], fill=EDGE_TOP)
    d.rectangle([0, h - X(band), w, h], fill=EDGE_BOTTOM)
    d.rectangle([0, 0, X(band), h], fill=EDGE_LEFT)
    d.rectangle([w - X(band), 0, w, h], fill=EDGE_RIGHT)

    # arrow toward v=0, i.e. the neckline / sleeve-cap end
    cx = width_mm * 0.5
    ay = band + height_mm * 0.03
    tip = band + height_mm * 0.008
    d.polygon(
        [(X(cx), X(tip)), (X(cx - width_mm * 0.05), X(ay)), (X(cx + width_mm * 0.05), X(ay))],
        fill=(200, 0, 160),
    )

    fs = max(12, int(min(w, h) * 0.035))
    f = font(fs)
    fsmall = font(max(10, int(fs * 0.62)))
    d.text((X(band) + 6, X(band) + 6), f"TL 0,0", fill=(180, 0, 0), font=fsmall)
    d.text((w - X(band) - 6, X(band) + 6), f"TR {width_mm:.0f},0", fill=(150, 120, 0), font=fsmall, anchor="ra")
    d.text((X(band) + 6, h - X(band) - 6), f"BL 0,{height_mm:.0f}", fill=(0, 110, 40), font=fsmall, anchor="ls")
    d.text(
        (w - X(band) - 6, h - X(band) - 6),
        f"BR {width_mm:.0f},{height_mm:.0f}",
        fill=(0, 40, 170),
        font=fsmall,
        anchor="rs",
    )
    label = f"{panel}  {width_mm:.1f} x {height_mm:.1f} mm"
    d.text((w * 0.5, h * 0.80), label, fill=(20, 20, 20), font=f, anchor="mm")
    d.text((w * 0.5, h * 0.80 + fs * 1.4), "TOP=red BOT=blue L=green R=yellow", fill=(90, 90, 90), font=fsmall, anchor="mm")
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads((PATTERN / "panels.json").read_text())
    for panel, info in data["panels"].items():
        pm = info["pattern_mm"]
        img = build(panel, pm["width"], pm["height"])
        path = OUT / f"calib-{panel}.png"
        img.save(path)
        print(f"{panel:9s} {img.size[0]:5d} x {img.size[1]:5d} px  ({PX_PER_MM} px/mm)  -> {path.name}")


if __name__ == "__main__":
    main()
