"""Scoring prospectif des previsions journalisees contre la verite gelee.

Verite terrain : ``scenario.EVENTS`` (crise semi-conducteurs rejouee). On suit
la definition PRE-ENREGISTREE de HA4 (cf. analyse_campagne.ha4) : pour un point
(noeud n, tour t) et un horizon h, l'issue est VRAIE s'il existe un evenement
sur n dans (t, t+h]. Les points censures (t+h au-dela du dernier tour, sans
evenement observe) sont EXCLUS, jamais comptes 0.

Usage : python score_predictions.py <predictions_log.jsonl> [<autre.jsonl> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(r"C:\PRIVEE\AZURE")
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "scenario"))
import scenario  # noqa: E402

HORIZONS = (1, 2, 3, 4)


def evenements_par_noeud() -> dict[str, set[int]]:
    par_noeud: dict[str, set[int]] = {}
    for tour, evs in scenario.EVENTS.items():
        for ev in evs:
            par_noeud.setdefault(ev["node"], set()).add(tour)
    return par_noeud


def auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """ROC-AUC par la statistique de Mann-Whitney, ex aequo a 0.5."""
    pos, neg = labels == 1, labels == 0
    if not pos.any() or not neg.any():
        return None
    ordre = np.argsort(scores, kind="mergesort")
    tries = scores[ordre]
    rangs = np.empty(len(scores), dtype=float)
    i = 0
    while i < len(tries):
        j = i
        while j + 1 < len(tries) and tries[j + 1] == tries[i]:
            j += 1
        rangs[ordre[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    n_p, n_n = int(pos.sum()), int(neg.sum())
    return float((rangs[pos].sum() - n_p * (n_p + 1) / 2.0) / (n_p * n_n))


def pr_auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """Precision moyenne (average precision), definition par paliers."""
    if labels.sum() == 0:
        return None
    ordre = np.argsort(-scores, kind="mergesort")
    lab = labels[ordre]
    tp = np.cumsum(lab)
    precision = tp / np.arange(1, len(lab) + 1)
    return float((precision * lab).sum() / lab.sum())


def brier(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    """(score de Brier, skill score vs taux de base)."""
    b = float(np.mean((scores - labels) ** 2))
    base = float(labels.mean())
    b_clim = float(np.mean((base - labels) ** 2))
    skill = 1.0 - b / b_clim if b_clim > 0 else float("nan")
    return b, skill


def analyser(chemin: Path) -> None:
    lignes = [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not lignes:
        print(f"{chemin} : vide")
        return
    bras = lignes[0].get("arm", "?")
    tours = sorted({l["tour"] for l in lignes})
    dernier = max(tours)
    ev = evenements_par_noeud()

    print(f"\n{'=' * 90}")
    print(f"BRAS « {bras} » — {len(lignes)} previsions, tours {min(tours)}..{dernier}")
    print(f"{'=' * 90}")
    print(f"{'h':>2} | {'n':>4} {'pos':>4} {'base':>6} | {'Brier':>7} {'skill':>7} "
          f"| {'AUC':>6} {'IC95':>14} {'PR-AUC':>7}")
    print("-" * 90)

    for h in HORIZONS:
        s, y, noeuds = [], [], []
        for ligne in lignes:
            t, node = ligne["tour"], ligne["node_id"]
            proba = ligne.get(f"p_issue_h{h}")
            if proba is None:
                continue
            touche = any(t < et <= t + h for et in ev.get(node, set()))
            if not touche and t + h > dernier:
                continue  # censure : fenetre incomplete sans evenement observe
            s.append(float(proba))
            y.append(1 if touche else 0)
            noeuds.append(node)
        if not s:
            print(f"{h:>2} | aucun point exploitable")
            continue
        sc, la = np.array(s), np.array(y, dtype=float)
        nd = np.array(noeuds)
        b, skill = brier(sc, la)
        a, p = auc(sc, la), pr_auc(sc, la)
        # IC95 de l'AUC par bootstrap PAR GRAPPES (noeud) : les points d'un meme noeud sont fortement correles, un bootstrap i.i.d. mentirait.
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

    print("\nLecture : skill > 0 = mieux que predire toujours le taux de base ;")
    print("          AUC 0.5 = hasard, > 0.65 = signal exploitable.")
    if len(lignes) < 30:
        print("ATTENTION : echantillon < 30 points, aucune conclusion ferme.")


def main() -> None:
    for arg in sys.argv[1:]:
        analyser(Path(arg))


if __name__ == "__main__":
    main()
