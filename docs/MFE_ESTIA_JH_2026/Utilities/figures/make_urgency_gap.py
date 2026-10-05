"""Draw the two urgency signals and the two mismatch pathologies.

The figure this replaces used red, which is outside the ALTEN palette, and drew
the step function by hand. Here the declared series is a step held between
weekly reviews, the computed series is continuous, and the two shaded regions
are the exact areas between them, so the picture and the definition agree.

Hidden risk carries the attention colour because it is the dangerous direction:
it raises no alert. False urgency is shaded lightly because it is visible and
merely expensive.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_urgency_gap.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

#: L'arbre d'images du BST est partage par les trois documents. La version
#: anglaise vit a cote de la francaise, sous un nom distinct, pour que le
#: document francais garde la sienne.
OUT = (Path(__file__).resolve().parents[3] / "BST_DISCO_JH_2026" / "Images"
       / "2.Problem" / "urgency_gap_en.png")

NAVY = "#043962"
AZURE = "#008BD2"
AZURE_LIGHT = "#7DCAED"
OCHRE = "#FFBA00"
OCHRE_PALE = "#FFEF86"
GREY_LINE = "#CDCEDA"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Carlito", "Calibri", "DejaVu Sans"],
    "font.size": 10.5,
    "text.color": NAVY,
    "axes.labelcolor": NAVY,
    "axes.edgecolor": NAVY,
    "xtick.color": NAVY,
    "ytick.color": NAVY,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
})

#: Urgence calculee : une derive lente, un pic de crise, une retombee partielle.
SEMAINES = np.linspace(0, 10, 601)
CALCULEE = np.clip(
    0.30
    + 0.030 * SEMAINES
    + 0.26 * np.exp(-((SEMAINES - 3.4) ** 2) / 0.9)
    + 0.34 * np.exp(-((SEMAINES - 8.1) ** 2) / 1.4),
    0.0, 1.0)

#: Urgence declaree : constante entre deux revues hebdomadaires. Le declarant
#: sur-reagit tot, puis rate la montee reelle avant de la rattraper.
DECLAREE = np.array([0.30, 0.52, 0.74, 0.74, 0.74, 0.44, 0.40, 0.40, 0.62, 0.86])

fig, ax = plt.subplots(figsize=(9.4, 4.9))

palier = np.array([DECLAREE[min(int(s), len(DECLAREE) - 1)] for s in SEMAINES])

ax.fill_between(SEMAINES, CALCULEE, palier, where=palier >= CALCULEE,
                color=AZURE_LIGHT, alpha=0.55, linewidth=0, zorder=2)
ax.fill_between(SEMAINES, CALCULEE, palier, where=CALCULEE > palier,
                color=OCHRE, alpha=0.75, linewidth=0, zorder=2)

ax.step(np.arange(len(DECLAREE) + 1),
        np.append(DECLAREE, DECLAREE[-1]), where="post",
        color=NAVY, lw=2.4, zorder=4)
ax.plot(SEMAINES, CALCULEE, color=AZURE, lw=2.6, zorder=5)

ax.annotate("declared urgency $U_d$\nmoves only at a weekly review",
            xy=(2.5, 0.74), xytext=(0.35, 0.955), fontsize=10, color=NAVY,
            arrowprops=dict(arrowstyle="-", color=NAVY, lw=1.0))
ax.annotate("computed urgency $U_r$\nmoves continuously",
            xy=(4.4, 0.50), xytext=(4.05, 0.19), fontsize=10, color=AZURE,
            arrowprops=dict(arrowstyle="-", color=AZURE, lw=1.0))
ax.annotate("hidden risk: no alert is raised",
            xy=(8.1, 0.60), xytext=(6.15, 0.90), fontsize=10, color=NAVY,
            arrowprops=dict(arrowstyle="-", color=OCHRE, lw=1.4))
ax.annotate("false urgency: capacity taken\nfrom another flow",
            xy=(2.3, 0.62), xytext=(1.35, 0.05), fontsize=10, color=NAVY,
            arrowprops=dict(arrowstyle="-", color=AZURE_LIGHT, lw=1.4))

ax.set_xlabel("project weeks")
ax.set_ylabel("urgency")
ax.set_xlim(0, 10)
ax.set_ylim(0, 1.08)
ax.set_xticks(range(0, 11))
ax.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0])
ax.grid(color=GREY_LINE, lw=0.6, alpha=0.6, zorder=0)
ax.set_axisbelow(True)
for cote in ("top", "right"):
    ax.spines[cote].set_visible(False)

ax.legend(handles=[
    Line2D([], [], color=NAVY, lw=2.4, label="$U_d$ declared"),
    Line2D([], [], color=AZURE, lw=2.6, label="$U_r$ computed"),
    Patch(facecolor=OCHRE, alpha=0.75, label="hidden risk $[U_r-U_d]^+$"),
    Patch(facecolor=AZURE_LIGHT, alpha=0.55, label="false urgency $[U_d-U_r]^+$"),
], frameon=False, ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.29),
    fontsize=9.5)

OUT.parent.mkdir(parents=True, exist_ok=True)
#% Le PDF est ce que pdflatex inclut : le trait reste net a n'importe quel zoom.
#% Le SVG suit pour la reprise en soutenance, le PNG pour les previsualisations.
for suffixe in (".pdf", ".svg", ".png"):
    chemin = OUT.with_suffix(suffixe)
    fig.savefig(chemin, facecolor="white")
    print(f"wrote {chemin}")
