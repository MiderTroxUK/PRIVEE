"""Construit le pack de donnees AIRB : degradation endogene, verite derivee.

AIRB n'est alimente par aucune serie publique — c'est une chaine construite, dont
les KPI sont poses. Ce script produit donc directement le pack que le harnais
consomme, sans passer par ``prepare_data.py`` (qui, lui, rebase des series INSEE
et WSTS sur les noeuds d'HELIOS et n'a pas de sens ici).

Ce qui est ecrit, par tour :

- ``tour_NN.csv``       : les KPI qui BOUGENT. Seuls les trois fournisseurs de
                          ``DERIVE_ENDOGENE`` bougent ; les douze autres restent
                          a leur socle, ce qui est le point du scenario ;
- ``events_NN.json``    : vide. Aucun choc exogene, jamais ;
- ``milestones_NN.json``: pose a zero, puis RECALCULE par ``verite_derivee.py``,
                          qui fait decouler l'avancement de la trajectoire des KPI.

La degradation touche trois grandeurs a la fois, parce qu'un fournisseur qui
s'enlise ne voit pas seulement son cycle s'allonger : sa disponibilite baisse et
la volatilite de ses couts monte. Ne bouger que le lead time produirait un signal
plus facile a lire que la realite.

Usage :
    python build_pack.py [--out <dossier>]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scenario"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scenario  # noqa: E402

#: Baisse de disponibilite par tour de derive, en points d'OEE. Bornee par
#: DISPO_PLANCHER : une usine qui derive ralentit, elle ne s'arrete pas.
BAISSE_DISPO: float = 0.008
DISPO_PLANCHER: float = 0.72

#: Volatilite de cout atteinte au terme de la derive. Un fournisseur en
#: difficulte facture ses depannages.
VOLATILITE_MAX: float = 0.40


def construire(sortie: Path, tours: int) -> None:
    """Ecrit le pack complet dans ``sortie``."""
    sortie.mkdir(parents=True, exist_ok=True)
    derive = scenario.DERIVE_ENDOGENE

    for tour in range(tours + 1):
        lignes: list[dict[str, str]] = []
        for node, (pente, depart) in sorted(derive.items()):
            avance = max(tour - depart, 0)
            socle = scenario.BASELINE_KPIS[node]
            lead = socle["time.lead_time_h"] + pente * avance
            dispo = max(socle["oee.availability"] - BAISSE_DISPO * avance, DISPO_PLANCHER)
            part = min(avance / max(tours, 1), 1.0)
            lignes.extend([
                {"node_id": node, "kpi_path": "time.lead_time_h", "valeur": f"{lead:.1f}"},
                {"node_id": node, "kpi_path": "oee.availability", "valeur": f"{dispo:.4f}"},
                {"node_id": node, "kpi_path": "risk.cost_volatility",
                 "valeur": f"{VOLATILITE_MAX * part:.4f}"},
            ])
        chemin = sortie / f"tour_{tour:02d}.csv"
        with chemin.open("w", encoding="utf-8", newline="") as flux:
            plume = csv.DictWriter(flux, fieldnames=["node_id", "kpi_path", "valeur"])
            plume.writeheader()
            plume.writerows(lignes)

        (sortie / f"events_{tour:02d}.json").write_text("[]\n", encoding="utf-8")
        # Avancement pose a zero : ``verite_derivee.py`` le recalcule depuis les
        # KPI ci-dessus. Ecrire ici une valeur plausible serait revenir a une
        # verite scriptee, c'est-a-dire au defaut que ce scenario existe pour eviter.
        (sortie / f"milestones_{tour:02d}.json").write_text(
            json.dumps([{"node": n, "name": nom, "progress": 0.0}
                        for n, nom, _k, _d, _e in scenario.MILESTONES],
                       ensure_ascii=False, indent=2),
            encoding="utf-8")

    (sortie / "PROVENANCE.md").write_text(
        "# Pack AIRB\n\n"
        "Construit par `scripts/build_pack.py` depuis `scenario/scenario.py`.\n"
        "Aucune serie externe : les ordres de grandeur sont poses, les entites fictives.\n\n"
        f"- {tours + 1} tours, {len(scenario.NODES)} noeuds, {len(scenario.ARCS)} arcs.\n"
        "- Aucun evenement exogene : tous les `events_NN.json` sont vides.\n"
        f"- Degradation endogene sur {', '.join(sorted(derive))} "
        "(lead time, disponibilite, volatilite de cout).\n"
        "- `milestones_NN.json` doit ensuite etre recalcule par `verite_derivee.py` :\n"
        "  la verite jalon DECOULE des KPI, elle n'est pas ecrite ici.\n",
        encoding="utf-8")

    print(f"pack AIRB ecrit : {tours + 1} tours dans {sortie}")
    print(f"derive endogene sur : {', '.join(sorted(derive))}")
    print("ETAPE SUIVANTE OBLIGATOIRE : verite_derivee.py sur ce dossier.")


def main() -> None:
    """Point d'entree CLI."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=_HERE.parent / "data" / "prepared")
    ap.add_argument("--tours", type=int, default=scenario.N_TOURS)
    args = ap.parse_args()
    construire(args.out, args.tours)


if __name__ == "__main__":
    main()
