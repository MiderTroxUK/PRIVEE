"""Construit le pack de donnees AIRB : degradation endogene, verite derivee.

AIRB n'est alimente par aucune serie publique — c'est une chaine construite, dont
les KPI sont poses. Ce script produit donc directement le pack que le harnais
consomme, sans passer par ``prepare_data.py`` (qui, lui, rebase des series INSEE
et WSTS sur les noeuds d'HELIOS et n'a pas de sens ici).

Ce qui est ecrit, par tour :

- ``tour_NN.csv``       : les KPI des QUINZE noeuds. Les trois fournisseurs de
                          ``DERIVE_ENDOGENE`` s'enlisent ; les douze autres
                          restent sains, mais leur cout est rafraichi a chaque
                          tour au lieu de rester fige (cf. plus bas) ;
- ``events_NN.json``    : vide. Aucun choc exogene, jamais ;
- ``milestones_NN.json``: pose a zero, puis RECALCULE par ``verite_derivee.py``,
                          qui fait decouler l'avancement de la trajectoire des KPI.

La degradation touche quatre grandeurs a la fois, parce qu'un fournisseur qui
s'enlise ne voit pas seulement son cycle s'allonger : sa disponibilite baisse,
la volatilite de ses couts monte, son cout operationnel s'ecarte du nominal et
sa probabilite de defaillance croit. Ne bouger que le lead time produirait un
signal plus facile a lire que la realite.

## Ce que la premiere version laissait mort, et pourquoi

Deux defauts, tous deux trouves en mesurant la campagne temoin plutot qu'en
relisant le code :

1. le seul signal de cout ecrit etait ``risk.cost_volatility``, qu'AUCUN bloc
   d'urgence ne consomme — ``u_cost`` lit ``cost.op_cost`` contre
   ``cost.nominal_op_cost``. Mesure : ``u_cost`` = 0,004 sur les quinze noeuds,
   a tous les tours, y compris ceux dont la volatilite atteignait 0,31 ;
2. les douze noeuds sains n'etaient jamais rafraichis, donc leur cout
   operationnel valait exactement le cout nominal du debut a la fin. Douze
   series plates sur quinze : la couche de prevision n'avait rien a lire.

La correction n'ecrit QUE dans les blocs cout et risque. Ni le lead time ni
l'OEE des noeuds sains ne bougent — ce sont les seules grandeurs qui entrent
dans la sante de ``verite_derivee.py``, donc la verite jalon reste identique et
les resultats deja mesures restent comparables sur cet axe.

Usage :
    python build_pack.py [--out <dossier>]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
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

#: Derive du cout operationnel au terme de l'enlisement, en part du cout
#: nominal. Un fournisseur qui s'enlise paie des heures supplementaires, du
#: transport express et des depannages : son cout operationnel s'ecarte du
#: nominal, et c'est CE couple que lit le bloc ``u_cost``.
#:
#: ``risk.cost_volatility`` etait jusqu'ici le seul signal de cout ecrit par ce
#: pack. Or aucun bloc d'urgence ne le consomme : ``u_cost`` lit
#: ``cost.op_cost`` contre ``cost.nominal_op_cost``. Resultat mesure sur la
#: campagne temoin : u_cost = 0,004 sur les QUINZE noeuds, a tous les tours,
#: y compris ceux dont la volatilite atteignait 0,31. Un tiers de la
#: degradation injectee n'arrivait nulle part.
DERIVE_COUT_MAX: float = 0.35

#: Montee de la probabilite de defaillance au terme de l'enlisement, en part
#: additive. Alimente ``u_risk``, qui lit ``risk.failure_probability``.
DERIVE_DEFAILLANCE_MAX: float = 0.06

#: Amplitude du bruit de cout des noeuds SAINS, en part du cout nominal.
#:
#: Sans lui, ``cost.op_cost`` reste egal au nominal a chaque tour et pour chaque
#: noeud : la serie est plate, la couche de prevision n'a aucune variation a
#: lire, et le bloc de cout est mort pour toute la chaine. Un atelier sain ne
#: facture pas au centime pres le meme montant tous les mois.
#:
#: Le bruit ne porte QUE sur les blocs cout et risque. Il ne touche ni le lead
#: time ni l'OEE, seules grandeurs qui entrent dans la sante de
#: ``verite_derivee.py`` : la verite jalon reste donc identique au bit pres, et
#: les douze noeuds sains continuent de tenir leurs dix-sept jalons au tour
#: pres. Enrichir les entrees ne doit pas deplacer la reference.
BRUIT_COUT_SAIN: float = 0.03

#: Graine du bruit des noeuds sains. Fixee : un pack doit etre reproductible.
GRAINE_BRUIT: int = 20260820


def _lignes_noeuds_sains(tour: int, derivants: set[str]) -> list[dict[str, str]]:
    """KPI du tour pour les noeuds qui ne derivent pas.

    Ces noeuds gardaient jusqu'ici leur socle d'initialisation sans jamais etre
    rafraichis : leur cout operationnel valait exactement le cout nominal a tous
    les tours, donc ``u_cost`` valait la meme constante pour toute la chaine et
    la couche de prevision n'avait aucune variation a lire sur douze noeuds sur
    quinze.

    Le bruit reste volontairement borne et ne porte que sur le cout : une usine
    saine facture un peu plus ou un peu moins d'un mois sur l'autre, sans que
    cela dise quoi que ce soit de sa capacite a tenir un jalon.

    Args:
        tour: tour courant.
        derivants: noeuds traites par ailleurs (a ne pas doubler ici).

    Returns:
        Les lignes CSV des noeuds sains pour ce tour.
    """
    lignes: list[dict[str, str]] = []
    for spec in scenario.NODES:
        node = spec["id"]
        if node in derivants:
            continue
        socle = scenario.BASELINE_KPIS[node]
        nominal = socle["cost.nominal_op_cost"]
        # Graine derivee du couple (noeud, tour) : reproductible, et deux noeuds
        # ne partagent pas la meme suite.
        alea = random.Random(f"{GRAINE_BRUIT}:{node}:{tour}")
        ecart = alea.uniform(-BRUIT_COUT_SAIN, BRUIT_COUT_SAIN)
        lignes.append({"node_id": node, "kpi_path": "cost.op_cost",
                       "valeur": f"{nominal * (1.0 + ecart):.2f}"})
    return lignes


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
            nominal = socle["cost.nominal_op_cost"]
            lignes.extend([
                {"node_id": node, "kpi_path": "time.lead_time_h", "valeur": f"{lead:.1f}"},
                {"node_id": node, "kpi_path": "oee.availability", "valeur": f"{dispo:.4f}"},
                {"node_id": node, "kpi_path": "risk.cost_volatility",
                 "valeur": f"{VOLATILITE_MAX * part:.4f}"},
                # Le couple que u_cost lit reellement. Sans lui, la derive de
                # cout n'existait que dans un KPI qu'aucun bloc ne consomme.
                {"node_id": node, "kpi_path": "cost.op_cost",
                 "valeur": f"{nominal * (1.0 + DERIVE_COUT_MAX * part):.2f}"},
                {"node_id": node, "kpi_path": "risk.failure_probability",
                 "valeur": f"{socle['risk.failure_probability'] + DERIVE_DEFAILLANCE_MAX * part:.4f}"},
            ])
        lignes.extend(_lignes_noeuds_sains(tour, set(derive)))
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
