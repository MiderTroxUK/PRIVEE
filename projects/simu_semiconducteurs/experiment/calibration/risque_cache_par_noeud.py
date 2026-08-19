"""Le risque cache designe-t-il les NOEUDS qui rateront un jalon ?

Le scoring de la campagne evalue la prevision a la maille (noeud, semaine) sur
une fenetre de quatre semaines : « le noeud X subira-t-il une issue defavorable
entre t+1 et t+4 ? ». Ce n'est pas la question que se pose un coordinateur. La
sienne est : « lequel de mes fournisseurs dois-je regarder cette semaine ? »

Ce script mesure la seconde. A chaque tour, il classe les noeuds par risque
cache H = [Ur - Ud]+ et confronte l'ensemble des noeuds signales (H > seuil) a
l'ensemble des noeuds qui rateront un jalon a son echeance CONTRACTUELLE plus
tard dans la campagne.

Usage :
    python risque_cache_par_noeud.py <dossier_snapshots> [<dossier_snapshots> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(r"C:\PRIVEE\AZURE")
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "scenario"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scenario  # noqa: E402

#: Un noeud est « signale » au-dessus de ce risque cache.
SEUIL_H = 0.10

#: Dernier tour de campagne : une echeance au-dela n'est pas observable.
DERNIER_TOUR = 18


def noeuds_qui_ratent() -> set[str]:
    """Noeuds ayant rate au moins un jalon a son echeance d'origine."""
    rates: set[str] = set()
    for node, nom, _kind, _debut, echeance in scenario.MILESTONES:
        if echeance > DERNIER_TOUR:
            continue
        livre = scenario.MILESTONE_DONE.get((node, nom))
        if livre is None or livre > echeance:
            rates.add(node)
    return rates


def analyser(dossier: Path) -> None:
    """Precision et rappel du signalement par tour, sur l'ensemble des noeuds."""
    verite = noeuds_qui_ratent()
    print(f"\n=== {dossier}")
    print(f"    noeuds qui ratent un jalon : {sorted(verite)}")
    print(f"    seuil de signalement : H > {SEUIL_H}\n")
    print(f"    {'tour':>4}  {'signales':<34} {'VP':>2} {'FP':>2} {'FN':>2}  "
          f"{'prec.':>6} {'rappel':>6}   pire noeud (adequation)")

    for chemin in sorted(dossier.glob("tour_*.json")):
        snap = json.loads(chemin.read_text(encoding="utf-8"))
        noeuds = snap["nodes"]
        signales = {
            nid for nid, n in noeuds.items()
            if (n.get("hidden_risk") or 0.0) > SEUIL_H
        }
        vp = len(signales & verite)
        fp = len(signales - verite)
        fn = len(verite - signales)
        prec = vp / (vp + fp) if (vp + fp) else None
        rapp = vp / (vp + fn) if (vp + fn) else None
        notes = [
            (n.get("adequation"), nid) for nid, n in noeuds.items()
            if n.get("adequation") is not None
        ]
        pire = min(notes)[1] if notes else "?"
        note_pire = min(notes)[0] if notes else float("nan")
        marque = "*" if pire in verite else " "
        fmt = lambda v: "  n/a " if v is None else f"{v:6.2f}"
        print(f"    T{snap['tour']:<3}  {','.join(sorted(signales))[:34]:<34} "
              f"{vp:>2} {fp:>2} {fn:>2}  {fmt(prec)} {fmt(rapp)}   "
              f"{pire}{marque} ({note_pire:.1f})")

    print("\n    * = le noeud le plus mal note est bien un noeud qui ratera un jalon")


def main() -> None:
    """Analyse chaque dossier de snapshots passe en argument."""
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for argument in sys.argv[1:]:
        analyser(Path(argument))


if __name__ == "__main__":
    main()
