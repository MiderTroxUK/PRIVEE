"""Graphe de banc d'essai : ou la couche de prevision marche, et ou elle casse.

Trois panneaux, tires des journaux de previsions passes en argument :

  A. skill de Brier contre horizon, cible JALON (la part endogene). La ligne
     zero est le previsionniste trivial qui annonce le taux de base : au-dessus,
     le modele apporte quelque chose.
  B. aire sous la courbe ROC contre horizon, meme cible. Mesure le CLASSEMENT,
     independamment du niveau annonce.
  C. decomposition par nature d'issue sur la campagne de reference : jalon
     (endogene) contre evenement (exogene). C'est le panneau qui explique
     pourquoi la cible mixte du produit donnait un mauvais chiffre.

Usage :
    python graphe_banc.py <sortie.png> <nom=journal.jsonl[::pack]> [...]

Le suffixe optionnel ``::pack`` designe le dossier dont la verite fait foi
pour ce journal — indispensable des que deux campagnes differentes figurent
sur la meme figure.
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
from banc import charger, horizons_du_journal, scorer  # noqa: E402

#: Charte ALTEN : bleu marine, azur, ocre. Aucun rouge, reserve aux alertes.
COULEURS = ("#043962", "#008BD2", "#FFBA00", "#7DCAED")


def serie(resultats: list[dict], champ: str):
    """``(horizons, valeurs)`` en ecartant les horizons non scorables."""
    xs = [r["h"] for r in resultats if r.get(champ) is not None]
    ys = [r[champ] for r in resultats if r.get(champ) is not None]
    return xs, ys


def tracer(sortie: Path, journaux: dict[str, tuple[Path, Path | None]]) -> None:
    """Dessine les trois panneaux et ecrit le PNG."""
    scores = {}
    for nom, (chemin, pack) in journaux.items():
        # La verite est propre a chaque campagne : scorer un journal AIRB contre
        # les jalons d'HELIOS ne mesurerait rien. Le pack est donc rearme avant
        # CHAQUE journal, et remis a zero quand le journal n'en a pas.
        banc._PACK = pack
        banc._VERITE_PACK = None
        if pack is not None and (pack / "VERITE.json").is_file():
            banc.charger_verite(pack / "VERITE.json")
        lignes = charger(chemin)
        horizons = horizons_du_journal(lignes)
        scores[nom] = {c: scorer(lignes, c, horizons) for c in ("jalon", "evenement", "contrat")}

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.9))
    fig.patch.set_facecolor("white")

    # --- A : skill contre horizon -------------------------------------------
    ax = axes[0]
    ax.axhline(0.0, color="#666666", lw=1.1, ls="--", zorder=1)
    for i, (nom, par_cible) in enumerate(scores.items()):
        xs, ys = serie(par_cible["jalon"], "skill")
        ax.plot(xs, ys, marker="o", ms=4.5, lw=2.0, color=COULEURS[i % len(COULEURS)], label=nom)
    ax.set_title("A. Calibration : skill de Brier\n(cible jalon)", fontsize=11)
    ax.set_xlabel("horizon (semaines)")
    ax.set_ylabel("skill de Brier")
    ax.text(0.03, 0.96, "au-dessus de 0 : mieux que le taux de base",
            transform=ax.transAxes, ha="left", va="top", fontsize=8, color="#444444")
    ax.legend(fontsize=8.5, loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25)

    # --- B : AUC contre horizon ---------------------------------------------
    ax = axes[1]
    ax.axhline(0.5, color="#666666", lw=1.1, ls="--", zorder=1)
    for i, (nom, par_cible) in enumerate(scores.items()):
        xs, ys = serie(par_cible["jalon"], "auc")
        ax.plot(xs, ys, marker="o", ms=4.5, lw=2.0, color=COULEURS[i % len(COULEURS)], label=nom)
    ax.set_title("B. Classement : aire sous la courbe ROC\n(cible jalon)", fontsize=11)
    ax.set_xlabel("horizon (semaines)")
    ax.set_ylabel("AUC")
    ax.set_ylim(0.0, 1.0)
    ax.text(0.98, 0.04, "0,5 = hasard", transform=ax.transAxes, ha="right",
            va="bottom", fontsize=8, color="#444444")
    ax.legend(fontsize=8.5, loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25)

    # --- C : endogene contre exogene ----------------------------------------
    ax = axes[2]
    reference = next(iter(scores))
    ax.axhline(0.5, color="#666666", lw=1.1, ls="--", zorder=1)
    for i, (cible, libelle) in enumerate(
        (("jalon", "jalon (endogene)"), ("contrat", "mixte (cible produit)"),
         ("evenement", "evenement (exogene)"))
    ):
        xs, ys = serie(scores[reference][cible], "auc")
        ax.plot(xs, ys, marker="s", ms=4.5, lw=2.0, color=COULEURS[i % len(COULEURS)],
                label=libelle)
    ax.set_title(f"C. La cible decide du verdict\n({reference})", fontsize=11)
    ax.set_xlabel("horizon (semaines)")
    ax.set_ylabel("AUC")
    ax.set_ylim(0.0, 1.0)
    ax.legend(fontsize=8.5, loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25)

    fig.tight_layout()
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(sortie, dpi=170, facecolor="white")
    print(f"-> {sortie}")


def main() -> None:
    """Lit ``nom=chemin`` en arguments et trace le banc."""
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    sortie = Path(sys.argv[1])
    journaux: dict[str, tuple[Path, Path | None]] = {}
    for brut in sys.argv[2:]:
        nom, _, reste = brut.partition("=")
        if not reste:
            raise SystemExit(f"argument attendu sous la forme nom=journal[::pack], recu {brut!r}")
        chemin, _, pack = reste.partition("::")
        journaux[nom] = (Path(chemin), Path(pack) if pack else None)
    tracer(sortie, journaux)


if __name__ == "__main__":
    main()
