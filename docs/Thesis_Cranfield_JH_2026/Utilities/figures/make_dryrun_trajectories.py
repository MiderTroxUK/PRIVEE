"""Redraw the dry-run trajectories with English labels.

The shared figure in the BST image tree is labelled in French, because the BST
is written in French. Re-labelling it in place would break that document, so
this script writes an English twin into the thesis's own image tree from the
same CSV. Nothing else changes: same data, same eight panels, same act bands.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_dryrun_trajectories.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RACINE = Path(__file__).resolve().parents[3].parent
SOURCE = RACINE / "projects" / "simu_semiconducteurs" / "analysis" / "resultats.csv"
SORTIE = Path(__file__).resolve().parents[1].parent / "Images" / "helios_dryrun_trajectories_en.png"

#: Charte ALTEN : bleu azur, ocre. Aucun rouge.
AZUR, OCRE, BANDE = "#008BD2", "#D9960A", "#EBF3F9"

#: Les huit noeuds, dans l'ordre des rangs, avec leur intitule anglais.
NOEUDS = [
    ("orbitalys", "Orbitalys — satellite prime, rank 0"),
    ("aviosys", "AvioSys — avionics, rank 1"),
    ("electis", "Electis EMS — boards, rank 2"),
    ("compodis", "CompoDis — distribution, rank 3"),
    ("transglobal", "TransGlobal — freight, rank 3"),
    ("novafab", "NovaFab — foundry, rank 4"),
    ("meridian", "Meridian — second foundry, rank 4"),
    ("silpure", "SilPure — wafers, rank 5"),
]

#: Actes 1, 3 et 5 du scenario, ombres pour situer les tours sans les nommer.
ACTES = [(0.5, 4.5), (8.5, 12.5), (16.5, 18.5)]


def charger() -> dict[str, dict[str, list[float]]]:
    """Lit tour, ud et ur pour chaque noeud."""
    series = {cle: {"t": [], "ud": [], "ur": []} for cle, _ in NOEUDS}
    with SOURCE.open(encoding="utf-8") as fichier:
        for ligne in csv.DictReader(fichier):
            if ligne["node"] in series:
                serie = series[ligne["node"]]
                serie["t"].append(int(ligne["tour"]))
                serie["ud"].append(float(ligne["ud"]))
                serie["ur"].append(float(ligne["ur"]))
    return series


def tracer() -> None:
    series = charger()
    figure, grille = plt.subplots(4, 2, figsize=(13.0, 11.0), sharex=True, sharey=True)
    figure.patch.set_facecolor("white")

    for axe, (cle, titre) in zip(grille.flat, NOEUDS):
        serie = series[cle]
        for debut, fin in ACTES:
            axe.axvspan(debut, fin, color=BANDE, zorder=0)
        axe.plot(serie["t"], serie["ur"], color=AZUR, lw=2.0,
                 label="$U_r$  computed, from data")
        axe.plot(serie["t"], serie["ud"], color=OCRE, lw=2.0, ls="--",
                 label="$U_d$  declared, synthetic")
        axe.set_title(titre, fontsize=10.5)
        axe.set_ylim(0, 1.05)
        axe.set_xticks(range(0, 19, 3))
        axe.grid(alpha=0.18)

    poignees, etiquettes = grille.flat[0].get_legend_handles_labels()
    figure.legend(poignees, etiquettes, loc="upper center", ncol=2,
                  fontsize=11, frameon=False, bbox_to_anchor=(0.5, 0.995))
    figure.supxlabel(
        "Game turn  (T0 training, T1 to T18 = Sept. 2020 to Feb. 2022; "
        "shaded bands: acts 1, 3 and 5)", fontsize=10.5, y=0.012)
    figure.tight_layout(rect=(0, 0.022, 1, 0.962))
    figure.savefig(SORTIE, dpi=170, facecolor="white")
    print(f"-> {SORTIE}")


if __name__ == "__main__":
    tracer()
