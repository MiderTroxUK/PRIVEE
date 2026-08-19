"""Figure de la campagne ENDOGENE a verite derivee : brut contre recale.

Deux panneaux, sur une campagne ou aucun choc exogene n'existe et ou la verite
jalon DECOULE de la trajectoire des KPI (``verite_derivee.py``) :

  A. skill de Brier contre horizon, avant et apres recalage isotone valide en
     laissant un noeud dehors ;
  B. aire sous la courbe ROC, meme decoupage.

Ce que la figure doit montrer : le modele CLASSE tres bien a court horizon
(AUC 0,91 a une semaine) et annonce le mauvais NIVEAU ; un recalage monotone
corrige le niveau sans casser le classement, et le skill passe positif. Aux
horizons longs, tout se degrade — sur une chaine purement endogene, tous les
fournisseurs qui derivent finissent par echouer, l'issue devient quasi certaine
partout et il n'y a plus rien a ordonner.

Usage :
    python graphe_endogene.py <sortie.png> <journal.jsonl> <pack>
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(r"C:\PRIVEE\AZURE")
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "experiment" / "calibration"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import banc  # noqa: E402
import recalage  # noqa: E402

#: Charte ALTEN : bleu marine pour le brut, ocre pour le recale.
BRUT, RECALE = "#043962", "#FFBA00"


def tracer(sortie: Path, journal: Path, pack: Path) -> None:
    """Dessine les deux panneaux et ecrit le PNG."""
    banc._PACK = pack
    verite = pack / "VERITE.json"
    if verite.is_file():
        banc.charger_verite(verite)

    lignes = banc.charger(journal)
    horizons = [h for h in banc.horizons_du_journal(lignes) if h <= 8]
    resultats = [r for r in (recalage.valider(lignes, "contrat", h) for h in horizons)
                 if r is not None]

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.6))
    fig.patch.set_facecolor("white")

    hs = [r["h"] for r in resultats]

    ax = axes[0]
    ax.axhline(0.0, color="#666666", lw=1.1, ls="--")
    ax.plot(hs, [r["skill_brut"] for r in resultats], marker="o", ms=5, lw=2.0,
            color=BRUT, label="brut")
    ax.plot(hs, [r["skill_recale"] for r in resultats], marker="s", ms=5, lw=2.0,
            color=RECALE, label="recale (un noeud dehors)")
    ax.set_title("A. Calibration : skill de Brier", fontsize=11)
    ax.set_xlabel("horizon (semaines)")
    ax.set_ylabel("skill de Brier")
    ax.text(0.30, 0.94, "au-dessus de 0 : mieux que le taux de base",
            transform=ax.transAxes, ha="left", va="top", fontsize=8, color="#444444")
    ax.legend(fontsize=9, loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25)

    ax = axes[1]
    ax.axhline(0.5, color="#666666", lw=1.1, ls="--")
    ax.plot(hs, [r["auc_brut"] for r in resultats], marker="o", ms=5, lw=2.0,
            color=BRUT, label="brut")
    ax.plot(hs, [r["auc_recale"] for r in resultats], marker="s", ms=5, lw=2.0,
            color=RECALE, label="recale (un noeud dehors)")
    ax.set_title("B. Classement : aire sous la courbe ROC", fontsize=11)
    ax.set_xlabel("horizon (semaines)")
    ax.set_ylabel("AUC")
    ax.set_ylim(0.0, 1.0)
    ax.text(0.03, 0.06, "0,5 = hasard", transform=ax.transAxes, fontsize=8, color="#444444")
    ax.legend(fontsize=9, loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25)

    fig.suptitle("Campagne endogene, verite jalon derivee des KPI "
                 "(aucun choc exogene)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(sortie, dpi=170, facecolor="white")
    print(f"-> {sortie}")


def main() -> None:
    """Trace la figure demandee."""
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    tracer(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    main()
