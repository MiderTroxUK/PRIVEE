"""Draw the four candidate models the literature review compares.

The review's table listed a formula and a one-line "key property" for each.
The property is the whole argument, and it is a shape: how urgency grows in
time, and what an aggregate does when one block saturates while the others
stay calm. Both are plotted from the formulas the table gives.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_aggregation_figure.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SORTIE = Path(__file__).resolve().parents[1].parent / "Images" / "aggregation_families.png"

MARINE, AZUR, OCRE, GRIS = "#043962", "#008BD2", "#D9960A", "#B8C4CE"

plt.rcParams.update({
    "font.size": 10.5,
    "axes.edgecolor": MARINE, "axes.labelcolor": MARINE, "text.color": MARINE,
    "xtick.color": MARINE, "ytick.color": MARINE,
    "axes.spines.top": False, "axes.spines.right": False,
    "savefig.bbox": "tight",
})

#: Cinq blocs calmes pendant qu'un sixieme monte ; poids egaux, de somme 1.
CALMES, POIDS = 0.2, 1 / 6


def tracer() -> None:
    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(11.2, 3.9))
    figure.patch.set_facecolor("white")

    # ── a. comment l'urgence croit dans le temps ──────────────────────────
    t = np.linspace(0, 10, 400)
    lineaire = np.clip(0.20 + 0.06 * t, 0, 1)
    hyperbolique = np.clip(1.20 / (11.0 - t) - 1.20 / 11.0 + 0.20, 0, 1)

    gauche.plot(t, lineaire, color=AZUR, lw=2.2, label="linear:  $U_0 + \\lambda t$")
    gauche.plot(t, hyperbolique, color=OCRE, lw=2.2,
                label="hyperbolic:  $K/(t_c - t)$, bounded")
    gauche.axvline(11.0, color=GRIS, lw=1.0, ls=":")
    gauche.set_xlim(0, 10)
    gauche.set_ylim(0, 1.05)
    gauche.set_xlabel("time towards the deadline")
    gauche.set_ylabel("urgency")
    gauche.set_title("a.  how urgency grows in time", fontsize=10.5, loc="left")
    gauche.grid(alpha=0.18)
    gauche.legend(fontsize=9.5, loc="upper left", frameon=False)

    # ── b. ce que fait un agregat quand un seul bloc sature ───────────────
    x = np.linspace(0, 1, 500)
    moyenne = (5 * CALMES + x) / 6
    noisy = 1 - (1 - CALMES) ** (5 * POIDS) * (1 - x) ** POIDS

    droite.plot(x, moyenne, color=AZUR, lw=2.2,
                label="weighted average:  $\\sum_m \\omega_m u_m$")
    droite.plot(x, noisy, color=OCRE, lw=2.2,
                label="noisy-OR:  $1-\\prod_m (1-u_m)^{\\omega_m}$")

    droite.plot([CALMES], [CALMES], "o", color=MARINE, ms=6, zorder=5)
    droite.annotate("all six blocks equal:\nthe two agree", xy=(CALMES, CALMES),
                    xytext=(0.34, 0.07), color=MARINE, fontsize=9.5,
                    arrowprops={"arrowstyle": "->", "color": MARINE, "lw": 1.0})
    droite.annotate("one block saturated:\nthe noisy-OR reaches $1.00$,\n"
                    "the average stops at $0.33$", xy=(0.985, 0.72),
                    xytext=(0.22, 0.62), color=MARINE, fontsize=9.5,
                    arrowprops={"arrowstyle": "->", "color": MARINE, "lw": 1.0})

    droite.set_xlim(0, 1)
    droite.set_ylim(0, 1.05)
    droite.set_xlabel("worst block  $u_m$, the other five held at $0.2$")
    droite.set_ylabel("aggregate  $U_{r,\\mathrm{local}}$")
    droite.set_title("b.  what the aggregate hides", fontsize=10.5, loc="left")
    droite.grid(alpha=0.18)
    droite.legend(fontsize=9.5, loc="upper left", frameon=False)

    figure.tight_layout()
    figure.savefig(SORTIE, dpi=200, facecolor="white")
    print(f"-> {SORTIE}")
    print(f"   un bloc a 1,00 : moyenne {(5*CALMES+1)/6:.3f}, noisy-OR 1,000")


if __name__ == "__main__":
    tracer()
