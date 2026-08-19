"""Scoring contre la vraie cible du modele : l'ISSUE DEFAVORABLE.

Le premier scoring confrontait les previsions a « un evenement quelconque sur
le noeud » — ce n'est PAS ce que le modele predit. ``ForecastService`` estime
l'issue defavorable au sens de ``CalibrationService`` : JALON RATE ou evenement
critique/defaut. On rescore ici contre cette cible.

Verite endogene, sans reference au modele :
  - jalon rate : un jalon dont l'echeance CONTRACTUELLE (celle de
    ``scenario.MILESTONES``, l'engagement initial) tombe dans la fenetre et
    qui n'etait pas livre a cette date (``scenario.MILESTONE_DONE``). Une
    replanification est elle-meme un constat de glissement : elle ne remet pas
    le compteur a zero.
  - evenement critique/defaut dans la fenetre.
Points censures (fenetre incomplete sans issue observee) : EXCLUS.

Usage : python score_endogene.py <predictions_log.jsonl> [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(r"C:\PRIVEE\AZURE")
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "scenario"))
import scenario  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_predictions import auc, brier, pr_auc  # noqa: E402

HORIZONS = (1, 2, 3, 4)
GRAVITES = {"critique", "defaut"}


def jalons_rates(dernier_tour: int) -> dict[str, set[int]]:
    """{node: {tours ou un jalon a rate son echeance contractuelle}}.

    Un jalon dont l'echeance tombe APRES la fin de campagne n'a jamais eu
    l'occasion d'etre rate : il est NON OBSERVE, pas manque. On l'exclut —
    le compter comme positif gonflerait artificiellement les scores en fin
    de campagne.
    """
    rates: dict[str, set[int]] = {}
    for node, nom, _kind, _debut, echeance in scenario.MILESTONES:
        if echeance > dernier_tour:
            continue  # echeance hors campagne : non observable
        livre = scenario.MILESTONE_DONE.get((node, nom))
        if livre is None or livre > echeance:
            rates.setdefault(node, set()).add(echeance)
    return rates


def evenements_graves() -> dict[str, set[int]]:
    """{node: {tours d'evenement critique/defaut}}."""
    graves: dict[str, set[int]] = {}
    for tour, evs in scenario.EVENTS.items():
        for ev in evs:
            if ev.get("params", {}).get("gravite") in GRAVITES:
                graves.setdefault(ev["node"], set()).add(tour)
    return graves


def analyser(chemin: Path) -> None:
    lignes = [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]
    bras = lignes[0].get("arm", "?")
    dernier = max(l["tour"] for l in lignes)
    rates, graves = jalons_rates(dernier), evenements_graves()

    detail = {n: sorted(t) for n, t in rates.items()}
    print(f"\nJalons rates (echeance contractuelle non tenue) : {detail}")
    print(f"Evenements critiques/defaut : {({n: sorted(t) for n, t in graves.items()})}")

    print(f"\n{'=' * 90}")
    print(f"BRAS « {bras} » — cible ENDOGENE (jalon rate OU evenement grave)")
    print(f"{'=' * 90}")
    print(f"{'h':>2} | {'n':>4} {'pos':>4} {'base':>6} | {'Brier':>7} {'skill':>7} "
          f"| {'AUC':>6} {'IC95':>14} {'PR-AUC':>7}")
    print("-" * 90)

    for h in HORIZONS:
        s, y, nds = [], [], []
        for ligne in lignes:
            t, node = ligne["tour"], ligne["node_id"]
            proba = ligne.get(f"p_issue_h{h}")
            if proba is None:
                continue
            issue = any(t < d <= t + h for d in rates.get(node, set())) or \
                any(t < e <= t + h for e in graves.get(node, set()))
            if not issue and t + h > dernier:
                continue
            s.append(float(proba))
            y.append(1 if issue else 0)
            nds.append(node)
        if not s:
            print(f"{h:>2} | aucun point exploitable")
            continue
        sc, la, nd = np.array(s), np.array(y, dtype=float), np.array(nds)
        b, skill = brier(sc, la)
        a, p = auc(sc, la), pr_auc(sc, la)
        uniques = np.unique(nd)
        rng = np.random.default_rng(0)
        tirages = []
        for _ in range(1000):
            choisis = rng.choice(uniques, size=len(uniques), replace=True)
            idx = np.concatenate([np.flatnonzero(nd == c) for c in choisis])
            val = auc(sc[idx], la[idx])
            if val is not None:
                tirages.append(val)
        ic = (float(np.percentile(tirages, 2.5)), float(np.percentile(tirages, 97.5))) \
            if len(tirages) >= 100 else None
        fa = f"{a:.3f}" if a is not None else "  n/a"
        fp = f"{p:.3f}" if p is not None else "   n/a"
        fic = f"[{ic[0]:.2f}, {ic[1]:.2f}]" if ic else "     n/a"
        print(f"{h:>2} | {len(sc):>4} {int(la.sum()):>4} {la.mean():>6.3f} "
              f"| {b:>7.4f} {skill:>+7.3f} | {fa:>6} {fic:>14} {fp:>7}")


def main() -> None:
    for arg in sys.argv[1:]:
        analyser(Path(arg))


if __name__ == "__main__":
    main()
