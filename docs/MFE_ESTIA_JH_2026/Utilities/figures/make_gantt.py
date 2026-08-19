"""Draw the mission schedule for the MFE report.

The workbook exported from the project tool only covers the first seven weeks,
so the schedule is redrawn here from the phases actually delivered, with the
milestones that closed each one. Dates come from the placement agreement
(13/04/2026 to 16/10/2026) and from the artefact record.

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
GREY_LINE = "#CDCEDA"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Carlito", "Calibri", "DejaVu Sans"],
    "font.size": 9.5,
    "text.color": NAVY,
    "axes.labelcolor": NAVY,
    "axes.edgecolor": NAVY,
    "xtick.color": NAVY,
    "ytick.color": NAVY,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
})

D = dt.date

# (label, start, end, colour band)
#   framing / build / validate / capitalise
PHASES = [
    ("Framing: literature, vocabulary, subject convergence", D(2026, 4, 13), D(2026, 5, 1), AZURE_LIGHT),
    ("First pipeline: initial model and modules",            D(2026, 4, 27), D(2026, 6, 1), AZURE_LIGHT),
    ("Redesign and build: SupplyScore application",          D(2026, 6, 1),  D(2026, 6, 20), AZURE),
    ("Experimental design: scenario, protocol, freeze",      D(2026, 6, 20), D(2026, 7, 10), AZURE),
    ("Campaign: execution of the two arms and analysis",     D(2026, 7, 10), D(2026, 8, 1), NAVY),
    ("Capitalisation: scientific report and reproducibility", D(2026, 8, 1), D(2026, 9, 5), NAVY),
    ("Reporting and defence preparation",                    D(2026, 9, 5),  D(2026, 10, 16), AZURE_LIGHT),
]

MILESTONES = [
    (D(2026, 5, 1),  "Framing complete"),
    (D(2026, 6, 1),  "Pipeline judged insufficient"),
    (D(2026, 6, 20), "Application delivered"),
    (D(2026, 7, 10), "Protocol frozen"),
    (D(2026, 8, 1),  "Campaign executed"),
    (D(2026, 9, 5),  "Research capitalised"),
]

fig, ax = plt.subplots(figsize=(11.0, 4.6))

# labels live in a left gutter, so a short bar never truncates its own text
for i, (label, start, end, colour) in enumerate(PHASES):
    y = len(PHASES) - 1 - i
    ax.barh(y, (end - start).days, left=start, height=0.5,
            color=colour, edgecolor=NAVY, linewidth=0.8, zorder=3)
    ax.text(start + dt.timedelta(days=3), y - 0.34,
            start.strftime("%d/%m") + " to " + end.strftime("%d/%m"),
            va="top", ha="left", fontsize=7.5, color=NAVY, zorder=4)

ax.set_yticks(range(len(PHASES)))
ax.set_yticklabels([lbl for lbl, *_ in PHASES][::-1], fontsize=9)
ax.tick_params(axis="y", length=0, pad=6)

for when, label in MILESTONES:
    ax.axvline(when, color=OCHRE, lw=1.4, ls="--", zorder=2)
    ax.plot([when], [len(PHASES) - 0.35], marker="D", color=OCHRE,
            markersize=7, markeredgecolor=NAVY, markeredgewidth=0.8, zorder=5)
    ax.annotate(label, xy=(when, len(PHASES) - 0.35),
                xytext=(0, 12), textcoords="offset points",
                rotation=32, ha="left", va="bottom", fontsize=8, color=NAVY)

ax.set_ylim(-0.8, len(PHASES) + 1.4)
ax.set_xlim(D(2026, 4, 6), D(2026, 10, 25))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.grid(axis="x", color=GREY_LINE, lw=0.6, alpha=0.7, zorder=0)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)

ax.annotate("placement: 13 April to 16 October 2026", xy=(0.5, -0.16),
            xycoords="axes fraction", ha="center", fontsize=8.5, color=NAVY)

ax.legend(handles=[
    Patch(facecolor=AZURE_LIGHT, edgecolor=NAVY, label="exploration"),
    Patch(facecolor=AZURE, edgecolor=NAVY, label="construction"),
    Patch(facecolor=NAVY, edgecolor=NAVY, label="validation and capitalisation"),
], frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.30),
    fontsize=8.5)

OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, facecolor="white")
print(f"wrote {OUT}")
