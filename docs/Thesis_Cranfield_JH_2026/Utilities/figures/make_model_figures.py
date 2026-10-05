"""Draw the two model behaviours that a paragraph explains worse than a curve.

Both are functions the thesis defines in closed form, so the figures are
computed from the equations rather than drawn by hand, and they will follow if
a parameter is ever recalibrated.

  adequacy_asymmetry  the score against the signed gap. A paragraph can assert
      that under-declaration is priced above over-declaration; only the curve
      shows by how much, and that the two branches meet at zero.

  completion_repair   the completion date against declared progress, under the
      repair that failed and the one that worked. The failure is that the
      shock is scaled by the work remaining, so it disappears exactly where a
      warning would be worth most. That is one line on the plot and four
      sentences in prose.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_model_figures.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

IMAGES = Path(__file__).resolve().parents[1].parent / "Images"

#: Charte ALTEN : bleu marine, azur, ocre, gris de trait. Aucun rouge.
MARINE, AZUR, OCRE, GRIS = "#043962", "#008BD2", "#D9960A", "#B8C4CE"

#: Parametres par defaut de l'equation d'adequation (cf. tableau des termes).
LAMBDA_UNDER, LAMBDA_OVER, ALPHA = 2.25, 1.0, 0.88

plt.rcParams.update({
    "font.size": 10.5,
    "axes.edgecolor": MARINE,
    "axes.labelcolor": MARINE,
    "text.color": MARINE,
    "xtick.color": MARINE,
    "ytick.color": MARINE,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.bbox": "tight",
})


def adequation(ecart: np.ndarray) -> np.ndarray:
    """Score d'adequation pour un ecart signe $U_d - U_r$."""
    fausse = np.clip(ecart, 0, None)
    cachee = np.clip(-ecart, 0, None)
    penalite = LAMBDA_UNDER * cachee ** ALPHA + LAMBDA_OVER * fausse ** ALPHA
    maximale = max(LAMBDA_UNDER, LAMBDA_OVER)
    return 100 * (np.exp(-penalite) - np.exp(-maximale)) / (1 - np.exp(-maximale))


def asymetrie() -> None:
    ecart = np.linspace(-1, 1, 801)
    score = adequation(ecart)

    figure, axe = plt.subplots(figsize=(7.4, 3.9))
    figure.patch.set_facecolor("white")

    axe.fill_between(ecart, 0, score, where=ecart <= 0, color=OCRE, alpha=0.16)
    axe.fill_between(ecart, 0, score, where=ecart >= 0, color=AZUR, alpha=0.16)
    axe.plot(ecart, score, color=MARINE, lw=2.2)

    for signe, couleur in ((-0.5, OCRE), (0.5, AZUR)):
        valeur = float(adequation(np.array([signe]))[0])
        axe.plot([signe], [valeur], "o", color=couleur, ms=7, zorder=5)
        axe.annotate(f"{valeur:.0f}", (signe, valeur), textcoords="offset points",
                     xytext=(0, 11), ha="center", color=MARINE, fontsize=11,
                     fontweight="bold")
        axe.plot([signe, signe], [0, valeur], color=couleur, lw=0.9, ls=":")

    axe.axvline(0, color=GRIS, lw=1.0)
    axe.set_xlim(-1, 1)
    axe.set_ylim(0, 108)
    axe.set_xlabel("signed gap  $U_d - U_r$")
    axe.set_ylabel("adequacy  $A$")
    axe.set_xticks([-1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1])
    axe.grid(alpha=0.18)

    axe.text(-0.97, 96, "hidden risk\nthe state is worse than declared",
             color=MARINE, fontsize=9.5, va="top")
    axe.text(0.97, 96, "false urgency\nmore urgency claimed than justified",
             color=MARINE, fontsize=9.5, va="top", ha="right")

    sortie = IMAGES / "adequacy_asymmetry.png"
    figure.savefig(sortie, dpi=200, facecolor="white")
    print(f"-> {sortie}")


def reparation() -> None:
    """Deux lectures du meme correctif : la date, puis ce qui reste du choc."""
    progres = np.linspace(0, 1, 400)
    lead, perdu, echeance = 8.0, 4.0, 6.0     # semaines

    nominal = (1 - progres) * lead
    multiplie = (1 - progres) * (lead + perdu)
    ajoute = (1 - progres) * lead + perdu

    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(11.2, 3.9))
    figure.patch.set_facecolor("white")

    gauche.plot(progres, nominal, color=GRIS, lw=1.8, ls="--", label="no shock")
    gauche.plot(progres, multiplie, color=OCRE, lw=2.2, label="multiplied into the lead time")
    gauche.plot(progres, ajoute, color=AZUR, lw=2.2, label="added to the completion date")
    gauche.axhline(echeance, color=MARINE, lw=1.1, ls=":")
    gauche.text(0.015, echeance + 0.25, "deadline", color=MARINE, fontsize=9.5)
    gauche.set_xlim(0, 1)
    gauche.set_ylim(0, 13)
    gauche.set_xlabel("declared progress  $p$")
    gauche.set_ylabel("weeks to completion")
    gauche.set_title("a.  where the completion date lands", fontsize=10.5, loc="left")
    gauche.grid(alpha=0.18)
    gauche.legend(fontsize=9, loc="upper right", frameon=False)

    droite.fill_between(progres, multiplie - nominal, perdu, color=OCRE, alpha=0.14)
    droite.plot(progres, ajoute - nominal, color=AZUR, lw=2.2,
                label="added: the shock keeps its size")
    droite.plot(progres, multiplie - nominal, color=OCRE, lw=2.2,
                label="multiplied: the shock is scaled away")
    droite.annotate("a four-week freeze is worth\n0.4 weeks at $p = 0.9$",
                    xy=(0.9, 0.4), xytext=(0.36, 1.55), color=MARINE, fontsize=9.5,
                    arrowprops={"arrowstyle": "->", "color": MARINE, "lw": 1.0})
    droite.set_xlim(0, 1)
    droite.set_ylim(0, 4.7)
    droite.set_xlabel("declared progress  $p$")
    droite.set_ylabel("weeks of shock surviving")
    droite.set_title("b.  how much of the shock reaches the date", fontsize=10.5, loc="left")
    droite.grid(alpha=0.18)
    droite.legend(fontsize=9, loc="lower left", frameon=False)

    figure.tight_layout()
    sortie = IMAGES / "completion_repair.png"
    figure.savefig(sortie, dpi=200, facecolor="white")
    print(f"-> {sortie}")

    for valeur in (0.1, 0.9):
        reste = (1 - valeur) * perdu
        print(f"   p={valeur:.1f} : le choc contribue {reste:.1f} semaine(s) sous le correctif"
              f" errone, {perdu:.1f} sous le correctif retenu")


if __name__ == "__main__":
    asymetrie()
    reparation()
