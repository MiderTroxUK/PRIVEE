"""SAM3 roof, then shape and area, then YOLO docks, on one shared frame.

  SAM3 ("warehouse roof")  ->  mask
        -> boundary traversal -> layout I / L / U
        -> pixel count        -> footprint area -> volume, pallet slots
  YOLO26-seg (runs/quai3)  ->  dock aprons -> length / 3.8 m -> docks

Both models run over the same IGN chip in Lambert-93, so their outputs share one world
frame and can be overlaid without any re-projection. SAM3 comes from VOLUME_ENTREPOT's
own sam.py (transformers backend, weights in models/SAM3); the dock model is the kept
fine-tune. Nothing here modifies either repository.

  ./.venv/Scripts/python.exe <this file> --out <dir>

CPU only: budget roughly a minute per site, plus two minutes to load SAM3 once.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point, Polygon

VE = r"C:\PRIVEE\GIT\SMART_GREEN_SUPPLY_CHAIN\VOLUME_ENTREPOT"
sys.path.insert(0, VE)

import analyse  # noqa: E402
import geo  # noqa: E402
import sam  # noqa: E402
import zone  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shape_skeleton  # noqa: E402

OCHRE = (255, 186, 0)      # BD TOPO footprint, the reference
AZURE = (0, 139, 210)      # YOLO dock apron
MAGENTA = (176, 92, 200)   # SAM3 roof
GREEN = (0, 230, 120)      # skeleton, the centre line the layout class is read from
NAVY = (4, 57, 98)
WHITE = (255, 255, 255)

SITES = [
    ("best", 43.722035, 1.398999),
    ("mid", 43.719510, 1.390983),
    ("flop", 43.696143, 1.401918),
]

GSD_SAM = 0.40      # SAM3 sees the site whole, at about the scale the old pipeline used
GSD_DRAW = 0.20     # the plate is rendered at full IGN resolution
HALF = 220.0        # half-width of the view, metres


def font(px):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def mask_to_polygon(mask, bbox, gsd, simplify_m=4.0):
    """Largest connected component of a SAM3 mask, as a world-coordinate polygon.

    The contour is simplified before the shape is read: a raw mask boundary is jagged
    at pixel scale and every wobble would count as a corner, so every building would
    come back "complexe".
    """
    import cv2
    m = (np.asarray(mask) > 0).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)[:, 0, :]
    if len(c) < 4:
        return None
    p = Polygon([(bbox[0] + col * gsd, bbox[3] - row * gsd) for col, row in c])
    if not p.is_valid:
        p = p.buffer(0)
        if p.geom_type == "MultiPolygon":
            p = max(p.geoms, key=lambda g: g.area)
    return p.simplify(simplify_m)


def plate(img, meta, roof, bdtopo, aprons, info, path, skel=()):
    im = Image.fromarray(img).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    g, minx, maxy = meta["gsd"], meta["bbox"][0], meta["bbox"][3]
    px = lambda p: ((p[0] - minx) / g, (maxy - p[1]) / g)

    if bdtopo is not None:
        d.line([px(p) for p in bdtopo.exterior.coords], fill=OCHRE + (255,), width=4)
    if roof is not None:
        d.polygon([px(p) for p in roof.exterior.coords], fill=MAGENTA + (70,),
                  outline=MAGENTA + (255,), width=5)
    for z in aprons:
        d.polygon([px(p) for p in z.exterior.coords], fill=AZURE + (105,),
                  outline=AZURE + (255,), width=4)
        for p0, p1 in slots(z):
            d.line([px(p0), px(p1)], fill=OCHRE + (235,), width=2)
    if len(skel) >= 2:                               # the centre line the class comes from
        d.line([px(p) for p in skel], fill=GREEN + (255,), width=6)
        for p in skel:
            cx, cy = px(p)
            d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=GREEN + (255,))

    ph = int(im.height * 0.155)
    out = Image.new("RGB", (im.width, im.height + ph), NAVY)
    out.paste(im, (0, 0))
    d2 = ImageDraw.Draw(out)
    ft, fs = font(int(ph * 0.155)), font(int(ph * 0.115))
    y = im.height + ph * 0.07
    d2.text((ph * 0.12, y), info[0], fill=WHITE, font=ft)
    for k, line in enumerate(info[1:]):
        d2.text((ph * 0.12, y + ph * (0.24 + 0.175 * k)), line,
                fill=(178, 224, 245), font=fs)
    for k, (c, lab) in enumerate(((MAGENTA, "SAM3 roof"), (AZURE, "YOLO dock apron"),
                                  (OCHRE, "BD TOPO footprint"))):
        tw = d2.textbbox((0, 0), lab, font=fs)[2]
        lx = im.width - ph * 0.12 - tw - ph * 0.22
        yy = im.height + ph * (0.10 + 0.28 * k)
        d2.rectangle([lx, yy, lx + ph * 0.14, yy + ph * 0.14], fill=c)
        d2.text((lx + ph * 0.22, yy - ph * 0.012), lab, fill=WHITE, font=fs)
    out.thumbnail((1000, 1600), Image.LANCZOS)
    out.save(path, quality=90)


def slots(z, pas=analyse.PAS_QUAI):
    c = np.array(z.minimum_rotated_rectangle.exterior.coords)[:-1]
    e = np.roll(c, -1, 0) - c
    L = np.hypot(e[:, 0], e[:, 1])
    k = int(np.argmax(L[:2]))
    u = e[k] / L[k]
    n = np.array([-u[1], u[0]])
    half = L[1 - k] / 2
    o = c[k] + e[1 - k] / 2
    return [(o + u * t - n * half, o + u * t + n * half)
            for t in np.arange(pas / 2, L[k], pas)]


def roof_at(x, y, prompt, half=HALF):
    """SAM3 roof at (x, y) -> (polygon, layout class, skeleton in world coords), or None.

    The class comes from the mask, not the polygon: skeletonising needs the filled shape.
    """
    bbox = (x - half, y - half, x + half, y + half)
    img, meta = geo.ortho(bbox, gsd=GSD_SAM)
    if not geo.is_covered(img):
        return None
    centre = Point(x, y)
    g, bx, by = meta["gsd"], meta["bbox"][0], meta["bbox"][3]
    best = None
    for m, _area in sam.toits(img, meta["gsd"], prompt=prompt, aire_min_m2=1200.0):
        p = mask_to_polygon(m, meta["bbox"], meta["gsd"])
        if p is None or p.is_empty:
            continue
        hit = p.contains(centre)
        if hit or (best is None and p.distance(centre) < 30):
            klass, skel = shape_skeleton.analyse_mask(m, g)
            best = (p, klass, [(bx + c * g, by - r * g) for c, r in skel])
            if hit:
                break
    return best


def overview(lat, lon, half, ratio, mini, poids, prompt, out):
    """The wide plate, with every roof segmented rather than taken from the database."""
    from pyproj import Transformer
    from shapely.geometry import box as sbox
    x, y = Transformer.from_crs("EPSG:4326", geo.CRS, always_xy=True).transform(lon, lat)
    ovb = (x - half, y - half * ratio, x + half, y + half * ratio)
    bats = [(p, pr) for p, pr in geo.batiments(ovb)
            if p.area >= mini and p.intersects(sbox(*ovb))]
    bats.sort(key=lambda t: -t[0].area)
    print(f"{len(bats)} buildings >= {mini:.0f} m2 in the overview extent\n", flush=True)

    roofs, kept, missed, skels, klasses = [], [], 0, [], []
    for i, (p, pr) in enumerate(bats, 1):
        c = p.centroid
        got = roof_at(c.x, c.y, prompt)
        if got is None or got[0].area < mini * 0.3:
            missed += 1
            r, klass, sk = p, "I", []               # fall back to the database polygon
        else:
            r, klass, sk = got
            kept.append(i - 1)
        roofs.append((r, pr))
        skels.append(sk)
        klasses.append(klass)
        print(f"  [{i}/{len(bats)}] roof {r.area:>7.0f} m2  {klass}", flush=True)

    zones = []
    for r, _ in roofs:
        zones += zone.zones_quai(r, poids)
    par_bat, _orph = zone.affecter(zones, roofs)

    gsd = max(0.20, max(ovb[2] - ovb[0], ovb[3] - ovb[1]) / 4600)
    img, meta = geo.ortho(ovb, gsd=gsd)
    im = Image.fromarray(img).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    g, minx, maxy = meta["gsd"], meta["bbox"][0], meta["bbox"][3]
    px = lambda p: ((p[0] - minx) / g, (maxy - p[1]) / g)
    lw = max(2, int(im.width / 900))

    for p, _ in bats:
        d.line([px(q) for q in p.exterior.coords], fill=OCHRE + (255,), width=lw)
    for i, (r, _) in enumerate(roofs):
        if i in kept:
            d.polygon([px(q) for q in r.exterior.coords], fill=MAGENTA + (85,),
                      outline=MAGENTA + (255,), width=lw + 1)
    for i, zs in par_bat.items():
        for z in zs:
            d.polygon([px(q) for q in z.exterior.coords], fill=AZURE + (115,),
                      outline=AZURE + (255,), width=lw + 1)
    for sk in skels:                                 # the centre line the class is read from
        if len(sk) >= 2:
            d.line([px(q) for q in sk], fill=GREEN + (255,), width=lw + 1)
            for q in sk:
                cx, cy = px(q)
                d.ellipse([cx - lw, cy - lw, cx + lw, cy + lw], fill=GREEN + (255,))

    f = font(max(14, int(im.width / 100)))
    placed, tot_d, tot_v = [], 0, 0
    ranked = []
    for i, (r, _) in enumerate(roofs):
        L = sum(zone.longueur(z) for z in par_bat[i])
        dk = int(round(L / analyse.PAS_QUAI))
        tot_d += dk
        tot_v += analyse.capacite(r.area, None)["volume_m3"]
        ranked.append((i, r, dk))
    for i, r, dk in sorted(ranked, key=lambda t: -t[2])[:12]:
        if not dk:
            continue
        cx, cy = px((r.centroid.x, r.centroid.y))
        lab = f"{klasses[i]}  {r.area:,.0f} m2  {dk} docks".replace(",", " ")
        tb = d.textbbox((0, 0), lab, font=f)
        wt, ht = tb[2] - tb[0], tb[3] - tb[1]
        for _ in range(40):
            bx = [cx - wt / 2 - 6, cy - ht / 2 - 5, cx + wt / 2 + 6, cy + ht / 2 + 6]
            if not any(bx[0] < q[2] and q[0] < bx[2] and bx[1] < q[3] and q[1] < bx[3]
                       for q in placed):
                break
            cy += ht * 1.7
        placed.append(bx)
        d.rectangle(bx, fill=NAVY + (230,))
        d.text((bx[0] + 6, bx[1] + 4), lab, fill=WHITE, font=f)

    ph = int(im.height * 0.11)
    panel = Image.new("RGB", (im.width, im.height + ph), NAVY)
    panel.paste(im, (0, 0))
    d2 = ImageDraw.Draw(panel)
    ft, fs = font(int(ph * 0.26)), font(int(ph * 0.185))
    pad = int(ph * 0.22)
    d2.text((pad, im.height + int(ph * 0.13)),
            f"{(ovb[2] - ovb[0]) / 1000:.1f} km of corridor, every roof segmented",
            fill=WHITE, font=ft)
    d2.text((pad, im.height + int(ph * 0.52)),
            f"{len(bats)} buildings >= {mini:.0f} m2  |  {len(kept)} roofs segmented, "
            f"{missed} fell back to the database  |  {tot_v:,} m3  |  {tot_d} docks"
            .replace(",", " "), fill=(178, 224, 245), font=fs)
    for k, (c, lab) in enumerate(((MAGENTA, "SAM3 roof"), (AZURE, "YOLO dock apron"),
                                  (OCHRE, "BD TOPO footprint"))):
        tw = d2.textbbox((0, 0), lab, font=fs)[2]
        lx = im.width - pad - tw - int(ph * 0.30)
        yy = im.height + int(ph * (0.10 + 0.29 * k))
        d2.rectangle([lx, yy, lx + ph * 0.18, yy + ph * 0.18], fill=c)
        d2.text((lx + ph * 0.28, yy - ph * 0.01), lab, fill=WHITE, font=fs)
    p_out = os.path.join(out, "samyolo_overview.jpg")
    panel.save(p_out, quality=90)
    print(f"\n  {os.path.basename(p_out)}  {panel.size}  "
          f"{len(kept)}/{len(bats)} roofs segmented, {tot_d} docks")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("sites", "overview"), default="sites")
    ap.add_argument("--lat", type=float, default=43.71317)
    ap.add_argument("--lon", type=float, default=1.40566)
    ap.add_argument("--half", type=float, default=900.0)
    ap.add_argument("--ratio", type=float, default=0.52)
    ap.add_argument("--min", type=float, default=1500.0, dest="mini")
    ap.add_argument("--poids", default=os.path.join(VE, "runs/quai3/weights/best.pt"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "samyolo"))
    ap.add_argument("--prompt", default=sam.PROMPT_MESURER)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    from pyproj import Transformer
    to93 = Transformer.from_crs("EPSG:4326", geo.CRS, always_xy=True)

    print("loading SAM3 (3.4 GB, CPU) ...", flush=True)
    t0 = time.time()
    sam.charger()
    print(f"  loaded in {time.time() - t0:.0f}s\n", flush=True)

    if a.mode == "overview":
        overview(a.lat, a.lon, a.half, a.ratio, a.mini, a.poids, a.prompt, a.out)
        return

    rows = []
    for tag, lat, lon in SITES:
        t0 = time.time()
        x, y = to93.transform(lon, lat)
        bbox = (x - HALF, y - HALF, x + HALF, y + HALF)

        # 1. SAM3 on the whole site
        img_s, meta_s = geo.ortho(bbox, gsd=GSD_SAM)
        toits = sam.toits(img_s, meta_s["gsd"], prompt=a.prompt, aire_min_m2=1200.0)
        centre = Point(x, y)
        roof, klass, skel = None, "I", []
        for m, area in toits:                      # prefer the roof under the site centre
            p = mask_to_polygon(m, meta_s["bbox"], meta_s["gsd"])
            if p is None or p.is_empty:
                continue
            hit = p.contains(centre)
            if hit or (roof is None and p.distance(centre) < 40):
                g0, bx0, by0 = meta_s["gsd"], meta_s["bbox"][0], meta_s["bbox"][3]
                klass, sk = shape_skeleton.analyse_mask(m, g0)
                roof = p
                skel = [(bx0 + c * g0, by0 - r * g0) for c, r in sk]
                if hit:
                    break
        if roof is None:
            print(f"[{tag}] SAM3 found no roof at the centre, skipped")
            continue

        # 2. layout, read off the simplified boundary   3. area
        forme = klass
        cap = analyse.capacite(roof.area, None)     # no height claimed from imagery

        # BD TOPO, for comparison only
        bd, h_bd = None, None
        for p, pr in geo.batiments(bbox):
            if p.contains(centre) or p.distance(centre) < 15:
                bd, h_bd = p, pr.get("hauteur")
                break
        if h_bd:
            cap = analyse.capacite(roof.area, float(h_bd))

        # 4. docks, from the kept fine-tune, on the SAM3 outline
        aprons = zone.zones_quai(roof, a.poids)
        aprons = [z for z in aprons if z.distance(roof) <= zone.PORTEE]
        L = sum(zone.longueur(z) for z in aprons)
        docks = int(round(L / analyse.PAS_QUAI))

        img_d, meta_d = geo.ortho(bbox, gsd=GSD_DRAW)
        info = [
            f"SAM3 roof {roof.area:,.0f} m2   shape {forme}   {docks} docks".replace(",", " "),
            f"volume {cap['volume_m3']:,} m3  ·  {cap['palettes']:,} pallet slots  ·  "
            f"height {cap['hauteur_m']} m ({cap['hauteur_source']})".replace(",", " "),
            (f"BD TOPO footprint {bd.area:,.0f} m2, SAM3 reads "
             f"{roof.area / bd.area - 1:+.0%}".replace(",", " ")) if bd else
            "no BD TOPO polygon at this point",
            f"{len(aprons)} apron(s), {L:.0f} m of equipped facade at 3.8 m pitch",
        ]
        plate(img_d, meta_d, roof, bd, aprons, info,
              os.path.join(a.out, f"samyolo_{tag}.jpg"), skel=skel)

        rows.append(dict(tag=tag, lat=lat, lon=lon, sam_area_m2=round(roof.area),
                         bdtopo_area_m2=round(bd.area) if bd else None, forme=forme,
                         volume_m3=cap["volume_m3"], palettes=cap["palettes"],
                         hauteur_m=cap["hauteur_m"], hauteur_source=cap["hauteur_source"],
                         aprons=len(aprons), longueur_quai_m=round(L), docks=docks,
                         secondes=round(time.time() - t0)))
        print(f"[{tag}] {rows[-1]}", flush=True)

    json.dump(rows, open(os.path.join(a.out, "samyolo.json"), "w"), indent=1)
    print(f"\n-> {a.out}")


if __name__ == "__main__":
    main()
