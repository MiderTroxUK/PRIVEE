"""Zone sweep plates for the poster: one wide overview plus three zoomed cases.

Reuses the tested pipeline in VOLUME_ENTREPOT (geo, analyse, zone) and only adds the
rendering, in the ALTEN palette so the plates match the rest of the poster.

  ./.venv/Scripts/python.exe <this file> --lat 43.71317 --lon 1.40566 --rayon 2000 --min 3000

Writes into --out (default: the poster scratch folder). Nothing is written into either
repository except the shared image cache that geo.py maintains anyway.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point, box

VE = r"C:\PRIVEE\GIT\SMART_GREEN_SUPPLY_CHAIN\VOLUME_ENTREPOT"
sys.path.insert(0, VE)

import analyse  # noqa: E402
import geo  # noqa: E402
import zone  # noqa: E402

# ALTEN Brand Book 2025 (EN), main colours p.27 and charter shades p.28
OCHRE = (255, 186, 0)  # BD TOPO footprint
AZURE = (0, 139, 210)  # apron drawn by the model
NAVY = (4, 57, 98)
WHITE = (255, 255, 255)
GREY = (160, 164, 178)


def batiments_tuiles(bbox, pas=4000.0):
    """geo.batiments over a grid of small boxes instead of one huge one.

    A single 30 x 30 km BBOX filter makes the WFS crawl: a 15 km sweep sat in that one
    request for twenty minutes without returning. The same area cut into 4 km tiles comes
    back in seconds per tile. Duplicates across tile borders are dropped on centroid.
    """
    seen, out = set(), []
    x0, y0, x1, y1 = bbox
    nx = max(1, int(np.ceil((x1 - x0) / pas)))
    ny = max(1, int(np.ceil((y1 - y0) / pas)))
    for i in range(nx):
        for j in range(ny):
            tb = (x0 + i * pas, y0 + j * pas,
                  min(x1, x0 + (i + 1) * pas), min(y1, y0 + (j + 1) * pas))
            for p, pr in geo.batiments(tb):
                k = (round(p.centroid.x, 1), round(p.centroid.y, 1))
                if k not in seen:
                    seen.add(k)
                    out.append((p, pr))
        print(f"  tiles {(i + 1) * ny}/{nx * ny}   {len(out)} buildings", flush=True)
    return out


def font(px):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def overview(bbox, bats, par_bat, res, path, title, sub):
    """One wide plate: every footprint, every apron, a label per productive building."""
    w_m, h_m = bbox[2] - bbox[0], bbox[3] - bbox[1]
    gsd = max(0.20, max(w_m, h_m) / 4600)  # stay under the 5010 px server cap
    img, meta = geo.ortho(bbox, gsd=gsd)
    im = Image.fromarray(img).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    g, minx, maxy = meta["gsd"], meta["bbox"][0], meta["bbox"][3]
    px = lambda p: ((p[0] - minx) / g, (maxy - p[1]) / g)

    lw = max(2, int(im.width / 900))
    for poly, _ in bats:
        d.line([px(p) for p in poly.exterior.coords], fill=OCHRE + (255,), width=lw)
    for i, zs in par_bat.items():
        for z in zs:
            d.polygon([px(p) for p in z.exterior.coords], fill=AZURE + (110,),
                      outline=AZURE + (255,), width=lw + 1)

    # Label only the productive sites, biggest first, nudging each box clear of the ones already placed. A cluttered overview is worse than an unlabelled one.
    f = font(max(14, int(im.width / 100)))
    placed = []
    inside = lambda r: bbox[0] < r["x"] < bbox[2] and bbox[1] < r["y"] < bbox[3]
    ranked = sorted((i for i, r in enumerate(res) if r["capacite_quais"] and inside(r)),
                    key=lambda i: -res[i]["capacite_quais"])[:12]
    for i in ranked:
        r = res[i]
        cx, cy = px((r["x"], r["y"]))
        label = f"W{i + 1}  {r['surface_m2']:,} m2  {r['capacite_quais']} docks".replace(",", " ")
        tb = d.textbbox((0, 0), label, font=f)
        wt, ht = tb[2] - tb[0], tb[3] - tb[1]
        for _ in range(40):
            bx = [cx - wt / 2 - 6, cy - ht / 2 - 5, cx + wt / 2 + 6, cy + ht / 2 + 6]
            if not any(bx[0] < q[2] and q[0] < bx[2] and bx[1] < q[3] and q[1] < bx[3]
                       for q in placed):
                break
            cy += ht * 1.7
        placed.append(bx)
        d.rectangle(bx, fill=NAVY + (230,))
        d.text((bx[0] + 6, bx[1] + 4), label, fill=WHITE, font=f)

    # info panel, same idea as the earlier SAM3 plate but carrying the new model's KPIs
    ph = int(im.height * 0.10)
    panel = Image.new("RGB", (im.width, im.height + ph), NAVY)
    panel.paste(im, (0, 0))
    d2 = ImageDraw.Draw(panel)
    ft, fs = font(int(ph * 0.26)), font(int(ph * 0.185))
    pad = int(ph * 0.22)
    d2.text((pad, im.height + int(ph * 0.13)), title, fill=WHITE, font=ft)
    d2.text((pad, im.height + int(ph * 0.52)), sub, fill=(178, 224, 245), font=fs)
    for k, (c, lab) in enumerate(((OCHRE, "BD TOPO footprint"), (AZURE, "dock apron, model"))):
        tw = d2.textbbox((0, 0), lab, font=fs)[2]
        lx = im.width - pad - tw - int(ph * 0.34)
        yy = im.height + int(ph * (0.16 + 0.40 * k))
        d2.rectangle([lx, yy, lx + ph * 0.20, yy + ph * 0.20], fill=c)
        d2.text((lx + ph * 0.32, yy - ph * 0.01), lab, fill=WHITE, font=fs)
    panel.save(path, quality=90)
    print(f"  {os.path.basename(path):<28} {panel.size}")


def slots(z, pas=analyse.PAS_QUAI):
    """The 1D reading of an apron: tick positions every `pas` along its long axis.

    Capacity is length / 3.8 m, so this draws the very thing that is counted, rather
    than a number printed next to a blob.
    """
    c = np.array(z.minimum_rotated_rectangle.exterior.coords)[:-1]
    edges = np.roll(c, -1, 0) - c
    lens = np.hypot(edges[:, 0], edges[:, 1])
    k = int(np.argmax(lens[:2]))  # long side of the rectangle
    u = edges[k] / lens[k]  # along the apron
    n = np.array([-u[1], u[0]])  # across it
    half = lens[1 - k] / 2
    o = c[k] + edges[1 - k] / 2  # mid-point of the long side
    L = lens[k]
    return [(o + u * t - n * half, o + u * t + n * half)
            for t in np.arange(pas / 2, L, pas)]


def zoomed(poly, mien, autres, path, caption):
    """A single site, its own aprons filled, the neighbours' outlined only."""
    img, meta = zone.chip(poly)
    if img is None:
        return False
    im = Image.fromarray(img).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    g, minx, maxy = meta["gsd"], meta["bbox"][0], meta["bbox"][3]
    px = lambda p: ((p[0] - minx) / g, (maxy - p[1]) / g)
    for z in autres:
        d.line([px(p) for p in z.exterior.coords], fill=AZURE + (140,), width=2)
    d.line([px(p) for p in poly.exterior.coords], fill=OCHRE + (255,), width=4)
    for z in mien:
        d.polygon([px(p) for p in z.exterior.coords], fill=AZURE + (100,),
                  outline=AZURE + (255,), width=4)
        for p0, p1 in slots(z):
            d.line([px(p0), px(p1)], fill=OCHRE + (235,), width=2)
    bh = max(26, int(im.height * 0.052))
    out = Image.new("RGB", (im.width, im.height + bh), NAVY)
    out.paste(im, (0, 0))
    ImageDraw.Draw(out).text((8, im.height + bh * 0.22), caption, fill=WHITE,
                             font=font(int(bh * 0.55)))
    out.thumbnail((900, 1400), Image.LANCZOS)
    out.save(path, quality=90)
    print(f"  {os.path.basename(path):<28} {out.size}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=43.71317)
    ap.add_argument("--lon", type=float, default=1.40566)
    ap.add_argument("--rayon", type=float, default=2000.0)
    ap.add_argument("--min", type=float, default=3000.0, dest="mini")
    # The overview is rendered on its own, tighter extent: past about 1.5 km across, a dock apron is a couple of pixels and the plate stops carrying information.
    ap.add_argument("--apercu", type=float, default=None,
                    help="half-width in m of the overview plate, default = rayon")
    ap.add_argument("--poids", default=os.path.join(VE, "runs/quai3/weights/best.pt"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "sweep"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    from pyproj import Transformer
    x, y = Transformer.from_crs("EPSG:4326", geo.CRS,
                                always_xy=True).transform(a.lon, a.lat)
    R = a.rayon
    c = Point(x, y)
    fetch = batiments_tuiles if R > 3000 else geo.batiments
    bats = [(p, pr) for p, pr in fetch((x - R, y - R, x + R, y + R))
            if p.area >= a.mini and p.centroid.distance(c) < R]
    bats.sort(key=lambda t: -t[0].area)
    print(f"{len(bats)} buildings >= {a.mini:.0f} m2 within {R:.0f} m\n")

    toutes = []
    for i, (poly, _) in enumerate(bats, 1):
        zs = zone.zones_quai(poly, a.poids)
        toutes += zs
        print(f"[{i}/{len(bats)}] {len(zs)} raw zone(s)", flush=True)
    par_bat, orphelines = zone.affecter(toutes, bats)

    res = [zone.resultat(p, pr, par_bat[i]) for i, (p, pr) in enumerate(bats)]
    cols = sorted({k for r in res for k in r})
    with open(os.path.join(a.out, "resultats.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(res)

    tot = dict(
        n=len(res), vol=sum(r["volume_m3"] for r in res),
        pal=sum(r["palettes"] for r in res), dock=sum(r["capacite_quais"] for r in res),
        length=sum(r["longueur_quai_m"] for r in res),
        withq=sum(1 for r in res if r["zones"]),
        alert=sum(1 for r in res if r["alerte"]),
        surf=sum(r["surface_m2"] for r in res),
        bdtopo=sum(1 for r in res if r["hauteur_source"] == "bdtopo"))
    json.dump(tot, open(os.path.join(a.out, "totaux.json"), "w"), indent=1)
    print("\n" + json.dumps(tot, indent=1))

    # Landscape extent: the poster column is wide and short, and a square plate would have to be scaled down until the aprons disappeared.
    Ov = a.apercu or R
    ovb = (x - Ov, y - Ov * 0.52, x + Ov, y + Ov * 0.52)
    keep = [k for k, (p, _) in enumerate(bats) if p.intersects(box(*ovb))]
    overview(ovb, [bats[k] for k in keep], {k: par_bat[k] for k in keep}, res,
             os.path.join(a.out, "sweep_overview.jpg"),
             f"Zone sweep, {2 * R / 1000:.0f} km across, centred {a.lat:.5f} N {a.lon:.5f} E",
             f"{tot['n']} buildings >= {a.mini:.0f} m2 | {tot['vol']:,} m3 storable | "
             f"{tot['pal']:,} pallet slots | {tot['length']} m of apron -> {tot['dock']} docks"
             .replace(",", " "))

    # three cases, picked by the pipeline's own quality gate rather than by eye
    clean = [i for i, r in enumerate(res) if r["zones"] and not r["alerte"]]
    flagged = [i for i, r in enumerate(res) if r["alerte"]]
    best = max(clean, key=lambda i: res[i]["capacite_quais"], default=None)
    mid = min((i for i in clean if i != best),
              key=lambda i: abs(res[i]["capacite_quais"] - 10), default=None)
    flop = max(flagged, key=lambda i: res[i]["capacite_quais"], default=None)

    # Nothing self-flags on a clean run, so the loudest ratios are rendered too and the failure case is chosen by looking at them rather than by trusting the gate.
    loud = sorted((i for i, r in enumerate(res) if r["zones"]),
                  key=lambda i: -res[i]["quais_par_ha"])[:8]
    picks = [(f"cand{k:02d}", i) for k, i in enumerate(loud)]

    for tag, i in [("best", best), ("mid", mid), ("flop", flop)] + picks:
        if i is None:
            print(f"  no candidate for {tag}")
            continue
        r = res[i]
        cadre = box(*geo.ortho(tuple(np.array(bats[i][0].buffer(60).bounds)))[1]["bbox"])
        autres = [z for j, zl in par_bat.items() if j != i for z in zl] + orphelines
        cap = (f"{r['surface_m2']} m2  {r['volume_m3']} m3  {r['zones']} apron(s)  "
               f"{r['longueur_quai_m']} m -> {r['capacite_quais']} docks"
               + (f"   FLAG: {r['alerte']}" if r["alerte"] else ""))
        zoomed(bats[i][0], par_bat[i], [z for z in autres if z.intersects(cadre)],
               os.path.join(a.out, f"sweep_{tag}.jpg"), cap)

    print(f"\n-> {a.out}")


if __name__ == "__main__":
    main()
