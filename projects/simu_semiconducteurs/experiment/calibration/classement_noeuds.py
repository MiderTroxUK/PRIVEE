"""Le systeme designe-t-il les BONS noeuds, et dans le bon ordre ?

La question operationnelle n'est pas « quelle probabilite pour ce noeud-semaine »
mais « quels fournisseurs dois-je regarder cette semaine, et dans quel ordre ».
Ce script la mesure sur trois classements concurrents, tour par tour :

  - ``adequation``   : la note d'adequation, du plus mauvais au meilleur ;
  - ``hidden_risk``  : l'ecart [Ur - Ud]+, du plus grand au plus petit ;
  - ``p_issue``      : la probabilite de la couche de prevision.

Les trois sont confrontes a l'ensemble des noeuds qui rateront un jalon, lu dans
le ``VERITE.json`` du pack. On mesure la PRECISION AU RANG k : parmi les k noeuds
designes, combien defaillent reellement. C'est la forme que prend la question
quand un coordinateur n'a le temps de regarder que trois fournisseurs.

Selon la facon dont la campagne a ete jouee, la prevision se trouve DANS le
snapshot (campagnes lancees par ``run_campaign.py --rollout``) ou seulement dans
le journal ``predictions_log.jsonl`` (campagnes pilotees tour par tour). Passer
``--journal`` fait lire ``p_issue`` dans le journal : sans quoi la colonne reste
vide et l'on conclurait a tort que la couche de prevision n'a rien produit.

Usage :
    python classement_noeuds.py <dossier_snapshots> <pack> [--k 3]
                                [--journal predictions_log.jsonl] [--horizon 4]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def noeuds_defaillants(pack: Path) -> set[str]:
    """Noeuds portant au moins un jalon rate, d'apres la verite du pack."""
    verite = json.loads((pack / "VERITE.json").read_text(encoding="utf-8"))
    return {j["node_id"] for j in verite["jalons"].values() if j["observable"] and j["rate"]}


def p_issue_du_journal(journal: Path, horizon: int) -> dict[int, dict[str, float]]:
    """``{tour: {node: p_issue}}`` lu dans un journal de previsions.

    Args:
        journal: ``predictions_log.jsonl`` de la campagne.
        horizon: horizon retenu, en semaines.

    Returns:
        Une entree par tour effectivement journalise. Les tours du debut de
        campagne en sont absents : la prevision ne demarre qu'une fois assez
        d'historique accumule, et c'est une absence legitime, pas un trou.
    """
    par_tour: dict[int, dict[str, float]] = {}
    for brute in journal.read_text(encoding="utf-8").splitlines():
        if not brute.strip():
            continue
        ligne = json.loads(brute)
        valeur = ligne.get(f"p_issue_h{horizon}")
        if valeur is not None:
            par_tour.setdefault(int(ligne["tour"]), {})[ligne["node_id"]] = float(valeur)
    return par_tour


def classements(snapshot: dict, p_issue_externe: dict[str, float] | None = None,
                ) -> dict[str, list[str]]:
    """Les trois classements du tour, du plus inquietant au moins inquietant."""
    noeuds = snapshot["nodes"]

    def trier(cle, decroissant: bool) -> list[str]:
        avec = [(nid, cle(n)) for nid, n in noeuds.items() if cle(n) is not None]
        return [nid for nid, _ in sorted(avec, key=lambda x: -x[1] if decroissant else x[1])]

    sortie = {
        "adequation": trier(lambda n: n.get("adequation"), decroissant=False),
        "hidden_risk": trier(lambda n: n.get("hidden_risk"), decroissant=True),
    }
    if p_issue_externe:
        sortie["p_issue"] = [nid for nid, _ in
                             sorted(p_issue_externe.items(), key=lambda x: -x[1])]
        return sortie
    prev = {nid: (n.get("forecast") or {}) for nid, n in noeuds.items()}
    if any(p.get("p_issue") for p in prev.values()):
        horizon = max((int(k) for p in prev.values() for k in p.get("p_issue", {})), default=4)
        sortie["p_issue"] = trier(
            lambda n: (n.get("forecast") or {}).get("p_issue", {}).get(str(horizon)),
            decroissant=True,
        )
    return sortie


def main() -> None:
    """Precision au rang k de chaque classement, tour par tour puis en moyenne."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshots", type=Path)
    ap.add_argument("pack", type=Path)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--journal", type=Path, default=None,
                    help="predictions_log.jsonl, si la prevision n'est pas dans les snapshots")
    ap.add_argument("--horizon", type=int, default=4,
                    help="horizon retenu pour classer sur p_issue (defaut 4 semaines)")
    args = ap.parse_args()

    verite = noeuds_defaillants(args.pack)
    fichiers = sorted(args.snapshots.glob("tour_*.json"))
    journal = p_issue_du_journal(args.journal, args.horizon) if args.journal else {}
    print(f"\nnoeuds qui rateront un jalon : {sorted(verite)}")
    print(f"precision au rang {args.k}, sur {len(fichiers)} tours\n")

    cumul: dict[str, list[float]] = {}
    entete = f"{'tour':>4} | " + " | ".join(f"{c:^28}" for c in ("adequation", "hidden_risk", "p_issue"))
    print(entete)
    print("-" * len(entete))
    for chemin in fichiers:
        snap = json.loads(chemin.read_text(encoding="utf-8"))
        rangs = classements(snap, journal.get(int(snap["tour"])))
        cases = []
        for critere in ("adequation", "hidden_risk", "p_issue"):
            tete = rangs.get(critere, [])[: args.k]
            if not tete:
                cases.append(f"{'-':^28}")
                continue
            bons = sum(1 for n in tete if n in verite)
            cumul.setdefault(critere, []).append(bons / len(tete))
            cases.append(f"{','.join(x[:9] for x in tete):<24}{bons}/{len(tete)}")
        print(f"T{snap['tour']:<3} | " + " | ".join(cases))

    print()
    for critere, valeurs in cumul.items():
        print(f"  {critere:<14} precision@{args.k} moyenne = {sum(valeurs)/len(valeurs):.2f} "
              f"sur {len(valeurs)} tours")


if __name__ == "__main__":
    main()
