"""Draw the truth-against-prediction plates for the poster.

Run with the VOLUME_ENTREPOT venv, from that directory:
  ./.venv/Scripts/python.exe C:/PRIVEE/AZURE/docs/BST_DISCO_JH_2026/Poster/web/make_pairs.py

The ultralytics validation grids exist but bleed class labels from one cell into the
next, so the same four chips are re-rendered here: hand annotation in ochre, model
output in azure, no burnt-in text. Counts are printed so the poster captions can be
checked against what is actually drawn.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

VE = Path("C:/PRIVEE/GIT/SMART_GREEN_SUPPLY_CHAIN/VOLUME_ENTREPOT")
OUT = Path(__file__).resolve().parent / "img"

OCHRE = (255, 186, 0)  # ALTEN charter shade, hand annotation
AZURE = (0, 139, 210)  # ALTEN main azure, model output
CONF = 0.25  # same threshold evaluer.py and tester.py use

CHIPS = {
    "a": "cfea0b1a09e78615",  # match
    "b": "00f50c5cf03fea4a",  # partial
    "c": "5b1dc10c58cdc2d8",  # missed
    "d": "2c84a0419f0485da",  # true negative
}


def truth_polys(stem: str, w: int, h: int):
    """YOLO-seg label file to pixel polygons. Format: cls x1 y1 x2 y2 ... normalised."""
    p = VE / "yolo/labels/val" / f"{stem}.txt"
    out = []
    for line in p.read_text().splitlines():
        v = line.split()
        if len(v) < 7:
            continue
        c = [float(x) for x in v[1:]]
        out.append([(c[i] * w, c[i + 1] * h) for i in range(0, len(c) - 1, 2)])
    return out


def draw(img: Image.Image, polys, colour):
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im, "RGBA")
    for poly in polys:
        if len(poly) >= 3:
            d.polygon(poly, fill=colour + (85,), outline=colour + (255,), width=5)
    return im


def main():
    import sys
    sys.path.insert(0, str(VE))
    from ultralytics import YOLO

    import analyse
    model = YOLO(str(VE / "runs/quai3/weights/best.pt"))
    imgsz = analyse.imgsz_entraine(model)  # infer at the size it was trained at

    for tag, stem in CHIPS.items():
        src = VE / "yolo/images/val" / f"{stem}.png"
        img = Image.open(src)
        w, h = img.size

        gt = truth_polys(stem, w, h)
        r = model.predict(img, imgsz=imgsz, conf=CONF, verbose=False)[0]
        pr = [[(float(x), float(y)) for x, y in m] for m in (r.masks.xy if r.masks else [])]
        pr = [p for p in pr if len(p) >= 3]

        for suffix, polys, colour in (("gt", gt, OCHRE), ("pr", pr, AZURE)):
            out = draw(img, polys, colour)
            out.thumbnail((620, 620), Image.LANCZOS)
            out.save(OUT / f"ve_{suffix}_{tag}.jpg", quality=88, optimize=True)

        print(f"{tag}  {stem}   truth {len(gt):>2}   predicted {len(pr):>2}")


if __name__ == "__main__":
    main()
