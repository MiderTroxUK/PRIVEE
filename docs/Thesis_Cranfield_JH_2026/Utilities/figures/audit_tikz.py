# -*- coding: utf-8 -*-
"""Measure every TikZ figure against the text block, and flag what does not fit.

A tikzpicture is laid out in absolute centimetres and does not shrink to the
line width, so a diagram wider than the text block silently runs into the
margin. This finds those, and also the ones so small they waste a float.
"""
import re
from pathlib import Path

import pymupdf

ROOT = Path(r"C:\PRIVEE\AZURE\docs\Thesis_Cranfield_JH_2026")
DOC = pymupdf.open(ROOT / "main.pdf")

# geometry: a4paper, left=2.7cm right=2.7cm -> text block 21 - 5.4 = 15.6 cm
CM = 72 / 2.54
TEXT_W = 15.6 * CM
LEFT = 2.7 * CM
RIGHT = LEFT + TEXT_W

# Collect the caption label of every figure, in document order, from the .lof
lof = (ROOT / "main.lof").read_text(encoding="utf-8", errors="replace")
titles = re.findall(r"numberline \{(\d+)\}\{\\ignorespaces ([^}]*)\}\}\{(\d+)\}", lof)

print(f"{len(titles)} figures listed\n")
print(f"{'#':>3} {'page':>5}  {'w cm':>6} {'h cm':>6}  margin  title")
print("-" * 92)

flagged = []
for num, title, printed_page in titles:
    # find the pdf page carrying this figure number's caption
    target = f"Figure {num}:"
    pdf_page = None
    for i in range(DOC.page_count):
        if target in DOC[i].get_text():
            pdf_page = i
            break
    if pdf_page is None:
        continue
    page = DOC[pdf_page]
    # bounding box of the vector drawings on the page
    xs0 = ys0 = 1e9
    xs1 = ys1 = -1e9
    for d in page.get_drawings():
        r = d["rect"]
        if r.width > 400 and r.height < 2:      # rules across the page: ignore
            continue
        xs0, ys0 = min(xs0, r.x0), min(ys0, r.y0)
        xs1, ys1 = max(xs1, r.x1), max(ys1, r.y1)
    if xs1 < xs0:
        continue
    w, h = (xs1 - xs0) / CM, (ys1 - ys0) / CM
    over_l = LEFT - xs0
    over_r = xs1 - RIGHT
    worst = max(over_l, over_r) / CM
    mark = ""
    if worst > 0.15:
        mark = f"OVER {worst:+.2f}cm"
        flagged.append((int(num), title, worst))
    print(f"{num:>3} {printed_page:>5}  {w:6.2f} {h:6.2f}  {mark:>12}  {title[:44]}")

print("\n" + "=" * 92)
print(f"{len(flagged)} figures run past the text block:")
for num, title, worst in sorted(flagged, key=lambda t: -t[2]):
    print(f"  fig {num:>2}  +{worst:.2f} cm  {title}")
