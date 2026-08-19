"""Le probleme restant est-il un probleme de NIVEAU, reparable apres coup ?

Le banc montre une dissociation nette : l'aire sous la courbe ROC est bonne et
monte avec l'horizon (0,73 a 0,85), tandis que le skill de Brier reste negatif.
C'est la signature decrite par Murphy : le modele ORDONNE correctement et
ANNONCE le mauvais niveau. Ce defaut-la se corrige apres coup, sans toucher au
modele.

Ce script le teste honnetement. Une regression isotone est ajustee sur les
previsions, puis appliquee, en validation croisee LAISSANT UN NOEUD DEHORS :
le recalage n'a jamais vu le noeud sur lequel il est score. Un recalage ajuste
et score sur les memes points remonterait mecaniquement, et ne prouverait rien.

Usage :
    python recalage.py <journal.jsonl> [--cible jalon] [--horizons 4 6 8]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(r"C:\PRIVEE\AZURE")
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "experiment" / "calibration"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import banc  # noqa: E402
from banc import auc, brier, charger, evenements_graves, jalons_rates  # noqa: E402


def points_avec_noeuds(lignes: list[dict], horizon: int, cible: str):
    """``(probas, verites, noeuds)`` scorables — censures exclus."""
    dernier = max(ligne["tour"] for ligne in lignes)
    rates = jalons_rates(dernier) if cible in ("contrat", "jalon") else {}
    graves = evenements_graves(banc._PACK) if cible in ("contrat", "evenement") else {}
    p, y, n = [], [], []
    for ligne in lignes:
        tour, node = ligne["tour"], ligne["node_id"]
        proba = ligne.get(f"p_issue_h{horizon}")
        if proba is None:
            continue
        issue = (any(tour < d <= tour + horizon for d in rates.get(node, set()))
                 or any(tour < e <= tour + horizon for e in graves.get(node, set())))
        if not issue and tour + horizon > dernier:
            continue
        p.append(float(proba))
        y.append(1.0 if issue else 0.0)
        n.append(node)
    return np.asarray(p), np.asarray(y), np.asarray(n)


def isotone(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Regression isotone par « pool adjacent violators », sans dependance.

    Args:
        x: scores bruts d'entrainement.
        y: verites 0/1 associees.

    Returns:
        ``(seuils, valeurs)`` : fonction en escalier croissante, evaluable par
        ``np.interp``-like via :func:`appliquer`.
    """
    ordre = np.argsort(x, kind="stable")
    xs, ys = x[ordre], y[ordre]
    valeurs = ys.astype(float).copy()
    poids = np.ones_like(valeurs)
    i = 0
    while i < len(valeurs) - 1:
        if valeurs[i] <= valeurs[i + 1]:
            i += 1
            continue
        total = poids[i] + poids[i + 1]
        moyenne = (valeurs[i] * poids[i] + valeurs[i + 1] * poids[i + 1]) / total
        valeurs[i] = moyenne
        poids[i] = total
        valeurs = np.delete(valeurs, i + 1)
        poids = np.delete(poids, i + 1)
        xs = np.delete(xs, i + 1)
        i = max(i - 1, 0)
    return xs, valeurs


def appliquer(seuils: np.ndarray, valeurs: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Evalue la fonction en escalier isotone en ``x`` (constante par morceaux)."""
    idx = np.searchsorted(seuils, x, side="right") - 1
    idx = np.clip(idx, 0, len(valeurs) - 1)
    return valeurs[idx]


def valider(lignes: list[dict], cible: str, horizon: int) -> dict | None:
    """Skill avant/apres recalage, en validation laissant un noeud dehors."""
    p, y, n = points_avec_noeuds(lignes, horizon, cible)
    if p.size == 0 or y.sum() == 0 or y.sum() == y.size:
        return None
    recale = np.empty_like(p)
    for noeud in np.unique(n):
        test = n == noeud
        entrainement = ~test
        if y[entrainement].sum() in (0, y[entrainement].size):
            recale[test] = p[test]  # pas de signal a apprendre : on ne touche pas
            continue
        seuils, valeurs = isotone(p[entrainement], y[entrainement])
        recale[test] = appliquer(seuils, valeurs, p[test])
    b0, s0 = brier(p, y)
    b1, s1 = brier(recale, y)
    return {"h": horizon, "n": int(p.size), "pos": int(y.sum()), "base": float(y.mean()),
            "brier_brut": float(b0), "skill_brut": float(s0), "auc_brut": auc(p, y),
            "brier_recale": float(b1), "skill_recale": float(s1), "auc_recale": auc(recale, y)}


def main() -> None:
    """Compare skill brut et skill recale, horizon par horizon."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("journal", type=Path)
    ap.add_argument("--cible", default="jalon", choices=("contrat", "jalon", "evenement"))
    ap.add_argument("--horizons", type=int, nargs="+", default=None)
    ap.add_argument("--pack", type=Path, default=None,
                    help="Pack dont la verite fait foi (VERITE.json + events_NN.json)")
    args = ap.parse_args()

    if args.pack is not None:
        banc._PACK = args.pack
        verite = args.pack / "VERITE.json"
        if verite.is_file():
            banc.charger_verite(verite)

    lignes = charger(args.journal)
    horizons = args.horizons or sorted(
        int(c.removeprefix("p_issue_h")) for c in lignes[0] if c.startswith("p_issue_h"))

    print(f"\n{args.journal.parent.parent.name} — cible « {args.cible} »")
    print("validation croisee en laissant UN NOEUD dehors ; le recalage ne voit")
    print("jamais le noeud sur lequel il est score.\n")
    entete = (f"{'h':>2} | {'n':>4} {'pos':>4} {'base':>6} | {'skill brut':>10} "
              f"{'AUC brut':>9} | {'skill recale':>12} {'AUC recale':>10}")
    print(entete)
    print("-" * len(entete))
    for h in horizons:
        r = valider(lignes, args.cible, h)
        if r is None:
            print(f"{h:>2} | non scorable")
            continue
        fa = lambda v: "     n/a" if v is None else f"{v:>8.3f}"
        print(f"{r['h']:>2} | {r['n']:>4} {r['pos']:>4} {r['base']:>6.3f} "
              f"| {r['skill_brut']:>+10.3f} {fa(r['auc_brut']):>9} "
              f"| {r['skill_recale']:>+12.3f} {fa(r['auc_recale']):>10}")


if __name__ == "__main__":
    main()
