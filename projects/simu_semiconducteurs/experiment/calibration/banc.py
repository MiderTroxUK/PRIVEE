"""Banc d'essai de la couche de prevision : scoring, decoupes, diagnostic.

Un seul outil pour toutes les questions qu'on pose a un journal de previsions,
de facon que deux journaux soient toujours compares avec la meme regle.

Cibles disponibles (``--cible``) :
  ``contrat``   jalon rate a son echeance d'ORIGINE, ou evenement grave ;
  ``jalon``     jalon rate seulement — la part ENDOGENE, previsible en principe ;
  ``evenement`` evenement grave seulement — la part EXOGENE, imprevisible par
                construction puisque scriptee sans precurseur dans les KPI.

La decoupe jalon/evenement est LA mesure qui dit ou le modele echoue : un
modele qui score bien sur ``jalon`` et mal sur ``evenement`` n'est pas un
mauvais modele, c'est un modele a qui l'on demande de deviner un tremblement
de terre.

Usage :
    python banc.py <journal.jsonl> [<journal.jsonl> ...] [--cible X] [--par-tour]
    python banc.py <journal.jsonl> --toutes-cibles
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(r"C:\PRIVEE\AZURE")


def _dossier_scenario() -> Path:
    """Dossier ``scenario/`` du projet a traiter.

    ``SUPPLYSCORE_PROJET_DIR`` designe le projet ; sans lui, HELIOS. Sans cette
    resolution, l'outil chargeait toujours le scenario d'HELIOS et derivait donc
    la verite d'un projet a partir des jalons d'un autre — silencieusement.
    """
    brut = os.environ.get("SUPPLYSCORE_PROJET_DIR")
    if not brut:
        return REPO / "projects" / "simu_semiconducteurs" / "scenario"
    dossier = Path(brut)
    if not dossier.is_absolute():
        dossier = REPO / dossier
    return dossier / "scenario"


sys.path.insert(0, str(_dossier_scenario()))
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "experiment"
                     / "mesures_avant_reparation" / "outils"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scenario  # noqa: E402
from score_predictions import auc, brier, pr_auc  # noqa: E402

GRAVITES = frozenset({"critique", "defaut"})
CIBLES = ("contrat", "jalon", "evenement")

#: Pack dont la verite fait foi, si ``--pack`` est passe.
_PACK: Path | None = None


#: Verite jalon derivee d'un pack (``VERITE.json``), si une a ete chargee.
#: Quand elle est posee, elle REMPLACE ``scenario.MILESTONE_DONE`` : scorer une
#: campagne jouee sur un pack derive contre les jalons d'un autre scenario est
#: exactement l'erreur qui fait paraitre un pack sain « moins bon ».
_VERITE_PACK: dict | None = None


def charger_verite(chemin: Path) -> None:
    """Charge un ``VERITE.json`` produit par ``verite_derivee.py``."""
    global _VERITE_PACK
    _VERITE_PACK = json.loads(chemin.read_text(encoding="utf-8"))
    n = sum(1 for j in _VERITE_PACK["jalons"].values() if j["observable"] and j["rate"])
    total = sum(1 for j in _VERITE_PACK["jalons"].values() if j["observable"])
    print(f"verite derivee chargee : {n} jalons rates sur {total} observables")


def jalons_rates(dernier: int) -> dict[str, set[int]]:
    """``{node: {tours ou une echeance d'origine n'a pas ete tenue}}``.

    Lit la verite derivee du pack si une a ete chargee, sinon la verite
    scriptee du scenario. Les deux repondent a la meme question — le jalon
    a-t-il tenu son ENGAGEMENT INITIAL — et se lisent donc pareil.
    """
    if _VERITE_PACK is not None:
        rates: dict[str, set[int]] = {}
        for jalon in _VERITE_PACK["jalons"].values():
            if not jalon["observable"] or jalon["echeance_origine"] > dernier:
                continue
            if jalon["rate"]:
                rates.setdefault(jalon["node_id"], set()).add(jalon["echeance_origine"])
        return rates
    rates = {}
    for node, nom, _kind, _debut, echeance in scenario.MILESTONES:
        if echeance > dernier:
            continue  # echeance hors campagne : jamais observable
        livre = scenario.MILESTONE_DONE.get((node, nom))
        if livre is None or livre > echeance:
            rates.setdefault(node, set()).add(echeance)
    return rates


def evenements_graves(pack: Path | None = None) -> dict[str, set[int]]:
    """``{node: {tours d'evenement critique ou defaut}}``.

    Lit les ``events_NN.json`` du pack si un pack est fourni — un pack sans
    choc doit rendre un dictionnaire VIDE, sinon on compte des evenements qui
    ne se sont jamais produits.
    """
    graves: dict[str, set[int]] = {}
    if pack is not None:
        for chemin in sorted(pack.glob("events_*.json")):
            tour = int(chemin.stem.removeprefix("events_"))
            for ev in json.loads(chemin.read_text(encoding="utf-8")):
                if ev.get("params", {}).get("gravite") in GRAVITES:
                    graves.setdefault(ev["node"], set()).add(tour)
        return graves
    for tour, evs in scenario.EVENTS.items():
        for ev in evs:
            if ev.get("params", {}).get("gravite") in GRAVITES:
                graves.setdefault(ev["node"], set()).add(tour)
    return graves


def points(lignes: list[dict], horizon: int, dernier: int, cible: str):
    """``(probas, verites, tours)`` scorables ; points censures exclus."""
    rates = jalons_rates(dernier) if cible in ("contrat", "jalon") else {}
    graves = evenements_graves(_PACK) if cible in ("contrat", "evenement") else {}
    probas, verites, tours = [], [], []
    for ligne in lignes:
        tour, node = ligne["tour"], ligne["node_id"]
        proba = ligne.get(f"p_issue_h{horizon}")
        if proba is None:
            continue
        issue = (any(tour < d <= tour + horizon for d in rates.get(node, set()))
                 or any(tour < e <= tour + horizon for e in graves.get(node, set())))
        if not issue and tour + horizon > dernier:
            continue  # fenetre incomplete sans issue observee : censure
        probas.append(float(proba))
        verites.append(1 if issue else 0)
        tours.append(tour)
    return np.asarray(probas), np.asarray(verites, dtype=float), np.asarray(tours)


def horizons_du_journal(lignes: list[dict]) -> tuple[int, ...]:
    """Horizons effectivement presents dans le journal, tries."""
    trouves = set()
    for ligne in lignes:
        for cle in ligne:
            if cle.startswith("p_issue_h"):
                trouves.add(int(cle.removeprefix("p_issue_h")))
    return tuple(sorted(trouves))


def scorer(lignes: list[dict], cible: str, horizons: tuple[int, ...]) -> list[dict]:
    """Une ligne de resultats par horizon."""
    dernier = max(ligne["tour"] for ligne in lignes)
    sortie = []
    for h in horizons:
        p, y, _ = points(lignes, h, dernier, cible)
        if p.size == 0 or y.sum() == 0:
            sortie.append({"h": h, "n": int(p.size), "pos": int(y.sum()),
                           "base": None, "brier": None, "skill": None,
                           "auc": None, "pr_auc": None})
            continue
        b, skill = brier(p, y)
        sortie.append({"h": h, "n": int(p.size), "pos": int(y.sum()),
                       "base": float(y.mean()), "brier": float(b),
                       "skill": float(skill), "auc": auc(p, y), "pr_auc": pr_auc(p, y)})
    return sortie


def afficher(titre: str, resultats: list[dict]) -> None:
    """Tableau lisible d'un scoring."""
    print(f"\n  {titre}")
    print(f"  {'h':>2} | {'n':>4} {'pos':>4} {'base':>6} | {'Brier':>7} "
          f"{'skill':>7} | {'AUC':>6} {'PR-AUC':>7}")
    print("  " + "-" * 62)
    for r in resultats:
        if r["base"] is None:
            print(f"  {r['h']:>2} | {r['n']:>4} {r['pos']:>4}   ---  | aucun positif")
            continue
        fa = "   n/a" if r["auc"] is None else f"{r['auc']:>6.3f}"
        fp = "    n/a" if r["pr_auc"] is None else f"{r['pr_auc']:>7.3f}"
        print(f"  {r['h']:>2} | {r['n']:>4} {r['pos']:>4} {r['base']:>6.3f} "
              f"| {r['brier']:>7.4f} {r['skill']:>+7.3f} | {fa} {fp}")


def par_tour(lignes: list[dict], cible: str, horizon: int) -> None:
    """Erreur de Brier moyenne par tour : l'historique s'allonge-t-il utilement ?"""
    dernier = max(ligne["tour"] for ligne in lignes)
    p, y, t = points(lignes, horizon, dernier, cible)
    if p.size == 0:
        print("  aucun point scorable")
        return
    print(f"\n  erreur quadratique moyenne par tour (h={horizon}, cible {cible})")
    print(f"  {'tour':>4} {'n':>4} {'pos':>4} {'Brier':>8}")
    for tour in sorted(set(t.tolist())):
        masque = t == tour
        print(f"  {int(tour):>4} {int(masque.sum()):>4} {int(y[masque].sum()):>4} "
              f"{float(((p[masque] - y[masque]) ** 2).mean()):>8.4f}")


def charger(chemin: Path) -> list[dict]:
    """Lignes JSON d'un journal de previsions."""
    return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> None:
    """Score chaque journal demande, sur une cible ou sur les trois."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("journaux", nargs="+", type=Path)
    ap.add_argument("--cible", choices=CIBLES, default="contrat")
    ap.add_argument("--toutes-cibles", action="store_true")
    ap.add_argument("--par-tour", type=int, metavar="H", default=None)
    ap.add_argument("--json", type=Path, default=None, help="Ecrit les scores en JSON")
    ap.add_argument("--pack", type=Path, default=None,
                    help="Pack dont la verite fait foi (VERITE.json + events_NN.json)")
    args = ap.parse_args()

    if args.pack is not None:
        global _PACK
        _PACK = args.pack
        verite = args.pack / "VERITE.json"
        if verite.is_file():
            charger_verite(verite)
        else:
            print(f"ATTENTION : {verite} absent, verite scriptee du scenario conservee")

    tout: dict[str, dict] = {}
    for chemin in args.journaux:
        lignes = charger(chemin)
        horizons = horizons_du_journal(lignes)
        nom = chemin.parent.parent.name or chemin.stem
        print(f"\n{'=' * 66}\n{nom}  ({len(lignes)} previsions, horizons {list(horizons)})\n{'=' * 66}")
        cibles = CIBLES if args.toutes_cibles else (args.cible,)
        tout[nom] = {}
        for cible in cibles:
            resultats = scorer(lignes, cible, horizons)
            afficher(f"cible « {cible} »", resultats)
            tout[nom][cible] = resultats
        if args.par_tour is not None:
            par_tour(lignes, args.cible, args.par_tour)

    if args.json:
        args.json.write_text(json.dumps(tout, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\n-> {args.json}")


if __name__ == "__main__":
    main()
