"""Generate the three diagram figures of the poster as SVG.

These three are diagrams, not illustrations: their whole value is exact text and
exact geometry. A diffusion model cannot guarantee either, which is where
"attolated", "dyn. dyn." and the mangled formula came from. Authored here instead,
so every string is literal and every arrow direction is provable.

    .venv\\Scripts\\python.exe docs/BST_DISCO_JH_2026/Poster/web/make_svg_figures.py

Writes into img/generated/ next to this file. Viewbox aspects match the poster
panes exactly, so object-fit:contain leaves no letterboxing.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "img" / "generated"

# ALTEN 2025 brand book. Ochre is a fill colour only, never text.
NAVY, AZURE, OCHRE = "#043962", "#008BD2", "#FFDA65"
ICE, GREY, RULE = "#B2E0F5", "#8C8C9A", "#CDCEDA"
AZ_MID, AZ_DARK = "#7DCAED", "#176F98"
BG = "#EBF3F9"
FONT = "Calibri, Carlito, Arial, Helvetica, sans-serif"


def tick(cx: float, cy: float, r: float, colour: str, w: float) -> str:
    """A checkmark sized to a disc of radius r."""
    return (f'<path d="M{cx - .43 * r:.1f} {cy + .03 * r:.1f} '
            f'L{cx - .13 * r:.1f} {cy + .36 * r:.1f} '
            f'L{cx + .46 * r:.1f} {cy - .36 * r:.1f}" fill="none" stroke="{colour}" '
            f'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>')


def crossed(cx: float, cy: float, r: float) -> str:
    """The 'does not do this' marker: same visual weight as a filled tick."""
    d = r * .64
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{RULE}" stroke-width="5"/>'
            f'<line x1="{cx - d:.1f}" y1="{cy + d:.1f}" x2="{cx + d:.1f}" y2="{cy - d:.1f}" '
            f'stroke="{RULE}" stroke-width="5" stroke-linecap="round"/>')


# 1. the empty column
def empty_column() -> str:
    W, H = 1600, 400  # 4:1, matches the 364 x 91 mm pane
    LBL_R = 258  # right edge of the row-label column
    BAND_X, BAND_W = 1012, 14  # ochre band isolating the answer column
    R = 30

    cols = [
        ("Ripple-effect", "models"),
        ("Markov and", "dyn. Bayesian"),
        ("Bayesian SC", "risk networks"),
        ("TTR / TTS", "stress tests"),
        ("Everstream,", "Resilinc, Interos"),
    ]
    step = (BAND_X - LBL_R) / len(cols)
    cx = [LBL_R + step * (i + .5) for i in range(len(cols))]
    ss_x = (BAND_X + BAND_W + W - 20) / 2  # SupplyScore column centre

    rows_y = [145, 243, 341]
    rules_y = [96, 194, 292, 390]

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="{FONT}">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<rect x="{BAND_X}" y="14" width="{BAND_W}" height="{H - 28}" fill="{OCHRE}"/>']

    # headers, horizontal, never rotated
    for (a, b), x in zip(cols, cx):
        s.append(f'<text x="{x:.1f}" y="46" font-size="20" fill="{NAVY}" '
                 f'text-anchor="middle">{a}</text>')
        s.append(f'<text x="{x:.1f}" y="72" font-size="20" fill="{NAVY}" '
                 f'text-anchor="middle">{b}</text>')
    s.append(f'<text x="{ss_x:.1f}" y="62" font-size="31" fill="{NAVY}" font-weight="700" '
             f'text-anchor="middle">SupplyScore</text>')

    for y in rules_y:
        s.append(f'<line x1="24" y1="{y}" x2="{W - 20}" y2="{y}" stroke="{RULE}" stroke-width="2"/>')
    s.append(f'<line x1="{LBL_R}" y1="96" x2="{LBL_R}" y2="390" stroke="{RULE}" stroke-width="2"/>')

    labels = [("Scores physical", "reality"), ("Scores human", "declaration"),
              ("Scores the gap", None)]
    for (a, b), y in zip(labels, rows_y):
        if b:
            s.append(f'<text x="24" y="{y - 9}" font-size="26" fill="{NAVY}">{a}</text>')
            s.append(f'<text x="24" y="{y + 23}" font-size="26" fill="{NAVY}">{b}</text>')
        else:
            s.append(f'<text x="24" y="{y + 9}" font-size="26" fill="{NAVY}">{a}</text>')

    # row 1: everyone scores physical reality
    for x in cx + [ss_x]:
        s.append(f'<circle cx="{x:.1f}" cy="{rows_y[0]}" r="{R}" fill="{AZURE}"/>')
        s.append(tick(x, rows_y[0], R, "#fff", 6))
    # rows 2 and 3: the empty band, and the one column that fills it
    for y in rows_y[1:]:
        for x in cx:
            s.append(crossed(x, y, R))
        s.append(f'<circle cx="{ss_x:.1f}" cy="{y}" r="{R}" fill="{OCHRE}"/>')
        s.append(tick(ss_x, y, R, NAVY, 6))

    s.append("</svg>")
    return "\n".join(s)


# 2. six detectors, one saturated
def noisy_or() -> str:
    W, H = 1200, 786  # 1.527, matches the 180 x 118 mm pane
    names = ["TIME", "CAPACITY", "PERFORMANCE", "RISK", "COST", "CO"]
    n = len(names)
    step = W / n
    cx = [step * (i + .5) for i in range(n)]
    cy, R = 138, 66
    LIT = 1  # CAPACITY is the saturated block

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="{FONT}">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>']

    for i, x in enumerate(cx):
        lit = i == LIT
        body, rim = (OCHRE, "#C99A00") if lit else (NAVY, AZ_DARK)
        if lit:  # alarm: bold solid crescents, not thin motion lines
            for k, rr in enumerate((R + 22, R + 42, R + 62)):
                s.append(f'<path d="M{x - rr * .72:.1f} {cy - rr * .70:.1f} '
                         f'A{rr} {rr} 0 0 1 {x + rr * .72:.1f} {cy - rr * .70:.1f}" '
                         f'fill="none" stroke="{OCHRE}" stroke-width="{9 - k * 2}" '
                         f'stroke-linecap="round"/>')
        # ceiling smoke detector: shallow disc, raised rim, vent slots, one LED
        s.append(f'<circle cx="{x:.1f}" cy="{cy}" r="{R}" fill="{body}"/>')
        s.append(f'<circle cx="{x:.1f}" cy="{cy}" r="{R - 11}" fill="none" '
                 f'stroke="{rim}" stroke-width="4"/>')
        for k in (-1, 0, 1):  # vent grille across the middle
            s.append(f'<rect x="{x - 26 + k * 0:.1f}" y="{cy - 8 + k * 15:.1f}" width="52" '
                     f'height="7" rx="3.5" fill="{"#8a6a00" if lit else AZ_DARK}"/>')
        s.append(f'<circle cx="{x:.1f}" cy="{cy + 40}" r="7" '
                 f'fill="{NAVY if lit else ICE}"/>')
        label = names[i]
        s.append(f'<text x="{x:.1f}" y="{cy + R + 46}" font-size="25" font-weight="700" '
                 f'fill="{NAVY}" text-anchor="middle">{label}'
                 + ('<tspan font-size="17" dy="6">2</tspan>' if label == "CO" else '')
                 + '</text>')

    # the two chips: a mean that was rejected, and the aggregation that replaced it
    cy2, ch = 330, 118
    s.append(f'<rect x="70" y="{cy2}" width="470" height="{ch}" rx="12" fill="{GREY}"/>')
    # the rejection mark goes UNDER the label and stays translucent: it must read as struck out, not as redacted. A solid X on top destroys the very number the figure is arguing about.
    s.append(f'<g stroke="{NAVY}" stroke-width="7" stroke-linecap="round" opacity="0.45">'
             f'<line x1="88" y1="{cy2 + 14}" x2="522" y2="{cy2 + ch - 14}"/>'
             f'<line x1="522" y1="{cy2 + 14}" x2="88" y2="{cy2 + ch - 14}"/></g>')
    s.append(f'<text x="305" y="{cy2 + 74}" font-size="46" fill="#fff" font-weight="700" '
             f'text-anchor="middle" letter-spacing="1">MEAN = 0.17</text>')

    s.append(f'<rect x="660" y="{cy2}" width="470" height="{ch}" rx="12" fill="{NAVY}"/>')
    s.append(f'<text x="895" y="{cy2 + 48}" font-size="38" fill="{OCHRE}" font-weight="700" '
             f'text-anchor="middle">PROBABILISTIC</text>')
    s.append(f'<text x="895" y="{cy2 + 95}" font-size="38" fill="{OCHRE}" font-weight="700" '
             f'text-anchor="middle">OR = 1.00</text>')

    # properly typeset mathematics: real subscripts, indexed product, no underscores
    fy = 600
    s.append(f'<g fill="{NAVY}" text-anchor="middle">')
    s.append(f'<text x="600" y="{fy}" font-size="62">'
             f'<tspan>U</tspan><tspan font-size="34" dy="14">r,local</tspan>'
             f'<tspan font-size="62" dy="-14">  =  1  −  </tspan>'
             f'</text>')
    s.append('</g>')
    # the product sign carries its index beneath it
    px = 764
    s.append(f'<text x="{px}" y="{fy}" font-size="78" fill="{NAVY}" text-anchor="middle">'
             f'∏</text>')
    s.append(f'<text x="{px}" y="{fy + 34}" font-size="28" fill="{NAVY}" '
             f'text-anchor="middle">m</text>')
    s.append(f'<text x="{px + 24}" y="{fy}" font-size="62" fill="{NAVY}" text-anchor="start">'
             f'<tspan>(1 − u</tspan><tspan font-size="34" dy="14">m</tspan>'
             f'<tspan font-size="62" dy="-14">)</tspan>'
             f'<tspan font-size="34" dy="-26">ω</tspan>'
             f'<tspan font-size="24" dy="10">m</tspan></text>')

    s.append(f'<text x="600" y="{fy + 128}" font-size="27" fill="{GREY}" '
             f'text-anchor="middle">One saturated block is enough. A mean would have '
             f'buried it.</text>')
    s.append("</svg>")
    return "\n".join(s)


# 3. two strictly opposite flows
def dag_propagation() -> str:
    W, H = 1200, 786
    NW, NH = 132, 62
    tiers = [
        [("wafers", 392)],
        [("foundry", 250), ("foundry 2", 534)],
        [("board EMS", 250), ("distributor", 534)],
        [("freight", 250), ("avionics", 534)],
        [("satellite", 392)],
    ]
    tx = [118, 350, 582, 814, 1046]
    fills = [ICE, AZ_MID, AZURE, AZ_DARK, NAVY]
    texts = [NAVY, NAVY, "#fff", "#fff", "#fff"]

    def box(i, j):
        name, y = tiers[i][j]
        return tx[i], y, name

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="{FONT}">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<defs>'
         f'<marker id="az" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" '
         f'markerHeight="7" orient="auto"><path d="M0 0 L12 6 L0 12 z" fill="{AZURE}"/></marker>'
         f'<marker id="oc" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" '
         f'markerHeight="7" orient="auto"><path d="M0 0 L12 6 L0 12 z" fill="{OCHRE}"/></marker>'
         f'</defs>']

    # structural edges of the DAG, drawn quietly so the two flows dominate
    edges = [((0, 0), (1, 0)), ((0, 0), (1, 1)),
             ((1, 0), (2, 0)), ((1, 1), (2, 1)), ((1, 0), (2, 1)),
             ((2, 0), (3, 0)), ((2, 1), (3, 1)),
             ((3, 0), (4, 0)), ((3, 1), (4, 0))]
    for a, b in edges:
        x1, y1, _ = box(*a)
        x2, y2, _ = box(*b)
        s.append(f'<line x1="{x1 + NW / 2}" y1="{y1}" x2="{x2 - NW / 2}" y2="{y2}" '
                 f'stroke="{RULE}" stroke-width="3"/>')

    # the one backup arc, between two named adjacent nodes, not across the figure
    x1, y1, _ = box(2, 1)
    x2, y2, _ = box(3, 0)
    s.append(f'<line x1="{x1 + NW / 2}" y1="{y1}" x2="{x2 - NW / 2}" y2="{y2}" '
             f'stroke="{RULE}" stroke-width="3" stroke-dasharray="10 8"/>')
    # clear of the dashed line itself, which passes through the midpoint
    s.append(f'<text x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 + 58:.0f}" font-size="20" '
             f'fill="{GREY}" text-anchor="middle">backup arc, deliberately inert</text>')

    for i, tier in enumerate(tiers):
        for j, _ in enumerate(tier):
            x, y, name = box(i, j)
            s.append(f'<rect x="{x - NW / 2}" y="{y - NH / 2}" width="{NW}" height="{NH}" '
                     f'rx="12" fill="{fills[i]}"/>')
            s.append(f'<text x="{x}" y="{y + 8}" font-size="22" fill="{texts[i]}" '
                     f'font-weight="700" text-anchor="middle">{name}</text>')

    # the whole point: one stream right to left, one stream left to right
    s.append(f'<path d="M1120 96 C 820 40, 380 40, 74 96" fill="none" stroke="{AZURE}" '
             f'stroke-width="11" marker-end="url(#az)" stroke-linecap="round"/>')
    s.append(f'<text x="600" y="34" font-size="26" fill="{NAVY}" text-anchor="middle">'
             f'declared need descends, attenuated by γ</text>')

    s.append(f'<path d="M74 690 C 380 748, 820 748, 1120 690" fill="none" stroke="{OCHRE}" '
             f'stroke-width="11" marker-end="url(#oc)" stroke-linecap="round"/>')
    s.append(f'<text x="600" y="772" font-size="26" fill="{NAVY}" text-anchor="middle">'
             f'physical risk climbs, scaled by β</text>')

    s.append(f'<text x="118" y="480" font-size="21" fill="{GREY}" text-anchor="middle">'
             f'deep supplier</text>')
    s.append(f'<text x="1046" y="480" font-size="21" fill="{GREY}" text-anchor="middle">'
             f'final customer</text>')
    s.append("</svg>")
    return "\n".join(s)


# 4. where each signal comes from, and what the gap between them is
def declared_and_gap() -> str:
    """Station 3, right slot. The bare propagation graph showed the two flows but
    not where either signal comes from, nor what the distance between them buys.
    This shows all three: origin, direction, and the gap that is the score."""
    W, H = 1200, 790
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="{FONT}">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<defs>'
         f'<marker id="al" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="6" '
         f'markerHeight="6" orient="auto"><path d="M0 0 L12 6 L0 12 z" fill="{AZURE}"/></marker>'
         f'<marker id="ol" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="6" '
         f'markerHeight="6" orient="auto"><path d="M0 0 L12 6 L0 12 z" fill="{OCHRE}"/></marker>'
         f'</defs>']

    # band 1: the declaration, and the end of the chain it enters from. Type is sized against the printed cell (180 mm wide), not against the viewBox, so it reads at the same weight as the poster body text.
    s.append(f'<text x="20" y="42" font-size="35" font-weight="700" fill="{NAVY}">'
             f'DECLARED  U<tspan font-size="23" dy="9">d</tspan></text>')
    s.append(f'<text x="20" y="82" font-size="28" fill="{GREY}">'
             f'four criteria, once a week</text>')
    s.append(f'<rect x="946" y="10" width="234" height="96" rx="9" fill="#fff" '
             f'stroke="{AZURE}" stroke-width="4"/>')
    for k in range(4):
        yy = 28 + k * 20
        s.append(f'<rect x="966" y="{yy}" width="15" height="15" rx="3" fill="{AZURE}"/>')
        s.append(f'<rect x="990" y="{yy + 4}" width="{166 - k * 22}" height="7" rx="3.5" '
                 f'fill="{RULE}"/>')
    s.append(f'<path d="M1150 138 C 720 184, 430 184, 34 144" fill="none" stroke="{AZURE}" '
             f'stroke-width="11" marker-end="url(#al)" stroke-linecap="round"/>')
    s.append(f'<text x="600" y="218" font-size="30" fill="{NAVY}" text-anchor="middle">'
             f'descends the chain, attenuated by γ</text>')

    # band 2: the chain
    names = ["wafers", "foundry", "board EMS", "freight", "satellite"]
    fills, cols = [ICE, AZ_MID, AZURE, AZ_DARK, NAVY], [NAVY, NAVY, "#fff", "#fff", "#fff"]
    nw, nh, y0 = 194, 66, 252
    for i, nm in enumerate(names):
        x = 36 + i * 230
        s.append(f'<rect x="{x}" y="{y0}" width="{nw}" height="{nh}" rx="12" fill="{fills[i]}"/>')
        s.append(f'<text x="{x + nw / 2}" y="{y0 + 43}" font-size="28" fill="{cols[i]}" '
                 f'font-weight="700" text-anchor="middle">{nm}</text>')
        if i < 4:
            s.append(f'<line x1="{x + nw}" y1="{y0 + nh / 2}" x2="{x + 230}" '
                     f'y2="{y0 + nh / 2}" stroke="{RULE}" stroke-width="3"/>')
    s.append(f'<text x="133" y="{y0 + nh + 32}" font-size="24" fill="{GREY}" '
             f'text-anchor="middle">deep supplier</text>')
    s.append(f'<text x="1053" y="{y0 + nh + 32}" font-size="24" fill="{GREY}" '
             f'text-anchor="middle">final customer</text>')

    # band 3: the measured signal, entering from the opposite end
    s.append(f'<path d="M34 400 C 430 446, 720 446, 1150 406" fill="none" stroke="{OCHRE}" '
             f'stroke-width="11" marker-end="url(#ol)" stroke-linecap="round"/>')
    s.append(f'<text x="600" y="482" font-size="30" fill="{NAVY}" text-anchor="middle">'
             f'climbs the chain, scaled by β</text>')
    s.append(f'<text x="20" y="542" font-size="35" font-weight="700" fill="{NAVY}">'
             f'MEASURED  U<tspan font-size="23" dy="9">r</tspan></text>')
    s.append(f'<text x="20" y="582" font-size="28" fill="{GREY}">'
             f'six families of indicators</text>')
    for k in range(6):
        s.append(f'<rect x="{946 + k * 40}" y="518" width="30" height="30" rx="6" '
                 f'fill="{OCHRE if k == 1 else NAVY}"/>')

    # band 4: the distance between the two IS the score
    gy = 656
    s.append(f'<line x1="20" y1="{gy - 46}" x2="1180" y2="{gy - 46}" stroke="{RULE}" '
             f'stroke-width="2"/>')
    s.append(f'<text x="20" y="{gy + 4}" font-size="28" fill="{NAVY}">declared</text>')
    s.append(f'<rect x="235" y="{gy - 24}" width="315" height="32" rx="6" fill="{AZURE}"/>')
    s.append(f'<text x="20" y="{gy + 76}" font-size="28" fill="{NAVY}">measured</text>')
    s.append(f'<rect x="235" y="{gy + 48}" width="605" height="32" rx="6" fill="{OCHRE}"/>')
    s.append(f'<path d="M550 {gy + 16} L550 {gy + 38} L840 {gy + 38} L840 {gy + 16}" '
             f'fill="none" stroke="{NAVY}" stroke-width="4"/>')
    s.append(f'<text x="600" y="{gy + 128}" font-size="33" font-weight="700" fill="{NAVY}" '
             f'text-anchor="middle">this distance is the score</text>')
    s.append("</svg>")
    return "\n".join(s)


# 5. the crisis the campaign replays, laid out on a timeline
def crisis_timeline() -> str:
    """Station 5. Eighteen rounds, five acts, and the dated real events each round
    is pinned to."""
    # the printed cell is only 144 x 57 mm, so type is large relative to the viewBox and the event list is deliberately short: four markers, not twelve
    W, H = 1200, 474
    x0, x1, ax = 80, 1130, 262
    step = (x1 - x0) / 17.0

    def X(t: float) -> float:
        return x0 + (t - 1) * step

    acts = [(1, 4, "BASELINE"), (5, 8, "TIPPING POINT"), (9, 12, "THE SQUEEZE"),
            (13, 16, "RUPTURE"), (17, 18, "RECOVERY")]
    events = [(6, "Texas freeze", True), (10, "Taiwan drought", False),
              (13, "order bullwhip", False), (16, "polysilicon ×3", False)]

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="{FONT}">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>']

    for i, (a, b, nm) in enumerate(acts):
        xa, xb = X(a) - step / 2, X(b) + step / 2
        s.append(f'<rect x="{xa:.1f}" y="{ax - 34}" width="{xb - xa:.1f}" height="68" '
                 f'fill="{BG if i % 2 == 0 else "#fff"}"/>')
        s.append(f'<text x="{(xa + xb) / 2:.1f}" y="{ax + 74}" font-size="24" '
                 f'font-weight="700" fill="{AZ_DARK}" text-anchor="middle">{nm}</text>')

    s.append(f'<line x1="{x0 - 30}" y1="{ax}" x2="{x1 + 30}" y2="{ax}" stroke="{NAVY}" '
             f'stroke-width="5"/>')
    for t in range(1, 19):
        s.append(f'<line x1="{X(t):.1f}" y1="{ax - 11}" x2="{X(t):.1f}" y2="{ax + 11}" '
                 f'stroke="{NAVY}" stroke-width="2.5"/>')

    # every marker sits ABOVE the axis, staggered at two heights, so nothing collides with the act names running underneath
    for k, (t, label, big) in enumerate(events):
        stem = 62 if k % 2 == 0 else 116
        ytip = ax - stem
        s.append(f'<line x1="{X(t):.1f}" y1="{ax}" x2="{X(t):.1f}" y2="{ytip}" '
                 f'stroke="{NAVY if big else RULE}" stroke-width="{5 if big else 3}"/>')
        s.append(f'<circle cx="{X(t):.1f}" cy="{ax}" r="{14 if big else 10}" '
                 f'fill="{OCHRE if big else AZURE}" stroke="#fff" stroke-width="3"/>')
        s.append(f'<text x="{X(t):.1f}" y="{ytip - 14}" font-size="{30 if big else 26}" '
                 f'font-weight="{700 if big else 400}" fill="{NAVY}" '
                 f'text-anchor="middle">{label}</text>')

    s.append(f'<text x="20" y="38" font-size="29" font-weight="700" fill="{NAVY}">'
             f'18 rounds, 5 acts, 12 calibrated events</text>')
    s.append("</svg>")
    return "\n".join(s)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, svg in (("empty_column", empty_column()),
                      ("noisy_or_detectors", noisy_or()),
                      ("dag_propagation", dag_propagation()),
                      ("declared_and_gap", declared_and_gap()),
                      ("crisis_timeline", crisis_timeline())):
        p = OUT / f"{name}.svg"
        p.write_text(svg, encoding="utf-8")
        print(f"wrote {p.relative_to(OUT.parents[2])}  ({len(svg):,} bytes)")
