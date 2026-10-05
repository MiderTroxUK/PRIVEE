"""Draw the mission schedule for the MFE report.

Phase boundaries come from the artefact record rather than from commit
timestamps: the repository stores batched pushes, so a burst of seventeen
commits on 11 June closes work that ran over the preceding fortnight. April and
May come from the project workbook, June onward from the milestone artefacts,
and the last three phases from the agreed plan for the remainder of the
placement.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_gantt.py
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

OUT = Path(__file__).resolve().parents[1].parent / "Images" / "gantt.png"

NAVY = "#043962"
AZURE = "#008BD2"
AZURE_LIGHT = "#7DCAED"
OCHRE = "#FFBA00"
OCHRE_PALE = "#FFEF86"
GREY_LINE = "#CDCEDA"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Carlito", "Calibri", "DejaVu Sans"],
    "font.size": 11.5,
    "text.color": NAVY,
    "axes.labelcolor": NAVY,
    "axes.edgecolor": NAVY,
    "xtick.color": NAVY,
    "ytick.color": NAVY,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
})

D = dt.date

#: Date the report is submitted. Everything after it is planned, not achieved.
TODAY = D(2026, 8, 24)

#: (label, start, end, colour). Four bands: explore, build, validate, planned.
PHASES = [
    ("Framing: literature, knowledge transfer, state of the art",
     D(2026, 4, 13), D(2026, 4, 30), AZURE_LIGHT),
    ("First urgency model and end-to-end pipeline",
     D(2026, 4, 20), D(2026, 5, 29), AZURE_LIGHT),
    ("Capacity from satellite imagery (parallel workstream)",
     D(2026, 4, 30), D(2026, 6, 26), AZURE_LIGHT),
    ("SupplyScore: redesign, build, documentation",
     D(2026, 6, 1), D(2026, 6, 12), AZURE),
    ("Experimental design: scenario, protocol, freeze",
     D(2026, 6, 15), D(2026, 7, 6), AZURE),
    ("First campaign, forecast layer and diagnosis",
     D(2026, 7, 6), D(2026, 7, 27), NAVY),
    ("Independent validation: repair, second chain, baseline",
     D(2026, 7, 28), D(2026, 8, 21), NAVY),
    ("Serious games: new chains to calibrate the model",
     D(2026, 8, 25), D(2026, 9, 19), OCHRE_PALE),
    ("Vision model: sharper facade segmentation",
     D(2026, 9, 7), D(2026, 9, 26), OCHRE_PALE),
    ("Scientific report and defence",
     D(2026, 9, 28), D(2026, 10, 16), OCHRE_PALE),
]

#: (date, label, alignment). Solid diamond once reached, hollow while planned.
#: Two labels would otherwise collide, one with the submission line and one with
#: the right edge, so each carries the side it hangs from.
MILESTONES = [
    (D(2026, 4, 30), "State of the art delivered", "left"),
    (D(2026, 5, 29), "First pipeline running", "left"),
    (D(2026, 6, 12), "SupplyScore v2.0.0", "left"),
    (D(2026, 6, 26), "Capacity from imagery", "left"),
    (D(2026, 7, 6),  "Protocol frozen", "left"),
    (D(2026, 7, 27), "First campaign scored", "left"),
    (D(2026, 8, 21), "Validation closed", "right"),
    (D(2026, 9, 19), "Calibration campaigns", "left"),
    (D(2026, 10, 16), "Scientific report", "right"),
]

fig, ax = plt.subplots(figsize=(10.0, 6.6))

# labels live in a left gutter, so a short bar never truncates its own text
for i, (label, start, end, colour) in enumerate(PHASES):
    y = len(PHASES) - 1 - i
    planifie = start > TODAY
    ax.barh(y, (end - start).days, left=start, height=0.5,
            color=colour, edgecolor=NAVY, linewidth=0.8, zorder=3,
            hatch="///" if planifie else None)
    ax.text(start + dt.timedelta(days=2), y - 0.36,
            start.strftime("%d/%m") + " to " + end.strftime("%d/%m"),
            va="top", ha="left", fontsize=8.5, color=NAVY, zorder=4)

ax.set_yticks(range(len(PHASES)))
ax.set_yticklabels([lbl for lbl, *_ in PHASES][::-1], fontsize=10.5)
ax.tick_params(axis="y", length=0, pad=6)

for rang, (when, label, cote) in enumerate(MILESTONES, start=1):
    atteint = when <= TODAY
    ax.axvline(when, color=OCHRE, lw=1.3, ls="--", zorder=2,
               alpha=1.0 if atteint else 0.4)
    ax.plot([when], [len(PHASES) - 0.25], marker="D",
            color=OCHRE if atteint else "white", markersize=14,
            markeredgecolor=NAVY, markeredgewidth=0.9, zorder=5)
    ax.annotate(str(rang), xy=(when, len(PHASES) - 0.25), ha="center", va="center",
                fontsize=10, color=NAVY, zorder=6,
                alpha=1.0 if atteint else 0.55)

ax.annotate("milestones 1 to 9 are named in the table below",
            xy=(0.5, 1.02), xycoords="axes fraction", ha="center",
            fontsize=9.5, color=NAVY, style="italic")

# the submission date, so the reader sees what is done and what is planned
ax.axvline(TODAY, color=NAVY, lw=2.0, zorder=6)
ax.annotate("report submitted", xy=(TODAY, -0.74), xytext=(-5, 0),
            textcoords="offset points", ha="right", va="center",
            fontsize=10, color=NAVY, fontweight="bold")

ax.set_ylim(-0.95, len(PHASES) + 0.4)
ax.set_xlim(D(2026, 4, 6), D(2026, 10, 25))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.grid(axis="x", color=GREY_LINE, lw=0.6, alpha=0.7, zorder=0)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)

ax.annotate("placement: 13 April to 16 October 2026, 35 h per week",
            xy=(0.5, -0.12), xycoords="axes fraction", ha="center",
            fontsize=10, color=NAVY)

ax.legend(handles=[
    Patch(facecolor=AZURE_LIGHT, edgecolor=NAVY, label="exploration"),
    Patch(facecolor=AZURE, edgecolor=NAVY, label="construction"),
    Patch(facecolor=NAVY, edgecolor=NAVY, label="validation"),
    Patch(facecolor=OCHRE_PALE, edgecolor=NAVY, hatch="///", label="planned"),
], frameon=False, ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.21),
    fontsize=10)

OUT.parent.mkdir(parents=True, exist_ok=True)
#% Le PDF est ce que pdflatex inclut : le trait reste net a n'importe quel zoom.
#% Le SVG suit pour la reprise en soutenance, le PNG pour les previsualisations.
for suffixe in (".pdf", ".svg", ".png"):
    chemin = OUT.with_suffix(suffixe)
    fig.savefig(chemin, facecolor="white")
    print(f"wrote {chemin}")
