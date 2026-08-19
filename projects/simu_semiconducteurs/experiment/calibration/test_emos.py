"""La couche de calibration EMOS aide-t-elle sur la cible REELLE du produit ?

L'artefact U10 est entraine sur ``y1`` = « un evenement critique/defaut touche le
noeud exactement a t+1 ». Le produit, lui, affiche ``p_issue_h4`` = « jalon rate
OU evenement critique, cumule sur (t, t+4] ». Horizon different, cible
different : brancher l'artefact sans verifier reproduirait exactement le piege
deja identifie — evaluer un modele contre la mauvaise cible.

Ce script tranche empiriquement. Il rejoue le journal de previsions gele, applique
l'artefact, et score AVANT/APRES contre la cible endogene du produit. Si le skill
monte malgre le decalage, la couche est utilisable en l'etat ; s'il baisse, le
decalage est disqualifiant et il faut re-entrainer sur la bonne cible.

Usage : python test_emos.py <journal_previsions.jsonl> [artifact.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(r"C:\PRIVEE\AZURE")
OUTILS = REPO / "projects/simu_semiconducteurs/experiment/mesures_avant_reparation/outils"
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "scenario"))
sys.path.insert(0, str(OUTILS))
from score_endogene import evenements_graves, jalons_rates  # noqa: E402
from score_predictions import auc, brier  # noqa: E402

from supplyscore.services.prediction import (  # noqa: E402
    _charger_artifact,
    _construire_vecteur,
    _score,
    _standardiser,
)

HORIZONS = (1, 2, 3, 4)

#: Bornes de clip du logit, comme a l'entrainement (evite +/-inf sur 0 et 1).
_CLIP = 1e-6


def _logit(p: float) -> float:
    """Logit borne, identique au pretraitement d'entrainement."""
    q = min(max(p, _CLIP), 1.0 - _CLIP)
    return math.log(q / (1.0 - q))


def features_ligne(ligne: dict, horizon: int) -> dict[str, float]:
    """Features de l'artefact assemblees depuis une ligne du journal.

    Les features absentes du journal sont laissees hors du dict : le service
    les impute a ``scaler_mean`` et le signale, plutot que d'inventer un zero.
    """
    p_rollout = ligne.get(f"p_issue_h{horizon}")
    feats: dict[str, float] = {}
    if p_rollout is not None:
        feats["logit_p_rollout"] = _logit(float(p_rollout))
    if ligne.get("spread") is not None:
        feats["spread"] = float(ligne["spread"])
    if ligne.get("p_impact_client") is not None:
        feats["p_impact_final"] = float(ligne["p_impact_client"])
    if ligne.get("ur_local") is not None:
        feats["ur_local"] = float(ligne["ur_local"])
    if ligne.get("d1_ur_local") is not None:
        feats["d1_ur_local"] = float(ligne["d1_ur_local"])
    return feats


def points(
    lignes: list[dict], horizon: int, dernier: int
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """(scores bruts, verites, lignes) scorables — cible endogene, censures exclus."""
    rates, graves = jalons_rates(dernier), evenements_graves()
    bruts: list[float] = []
    verites: list[int] = []
    gardees: list[dict] = []
    for ligne in lignes:
        tour, node = ligne["tour"], ligne["node_id"]
        proba = ligne.get(f"p_issue_h{horizon}")
        if proba is None:
            continue
        issue = any(tour < d <= tour + horizon for d in rates.get(node, set())) or any(
            tour < e <= tour + horizon for e in graves.get(node, set())
        )
        if not issue and tour + horizon > dernier:
            continue
        bruts.append(float(proba))
        verites.append(1 if issue else 0)
        gardees.append(ligne)
    return np.asarray(bruts), np.asarray(verites), gardees


def main() -> None:
    """Score le journal AVANT et APRES calibration, horizon par horizon."""
    journal = Path(sys.argv[1])
    artefact_path = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "models/latest/artifact.json"
    artifact = _charger_artifact(artefact_path)
    print(f"artefact : {artefact_path}")
    print(f"features attendues : {list(artifact.feature_names)}\n")

    lignes = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines() if x.strip()]
    dernier = max(ligne["tour"] for ligne in lignes)

    entete = f"{'h':>2} | {'n':>4} {'base':>6} | {'Brier brut':>10} {'skill':>7} {'AUC':>6} "
    entete += f"| {'Brier cal.':>10} {'skill':>7} {'AUC':>6}"
    print(entete)
    print("-" * len(entete))

    imputes_signales: set[str] = set()
    for h in HORIZONS:
        bruts, verites, gardees = points(lignes, h, dernier)
        if bruts.size == 0:
            continue
        calibres = np.empty_like(bruts)
        for i, ligne in enumerate(gardees):
            x, imputees = _construire_vecteur(artifact, features_ligne(ligne, h))
            imputes_signales.update(imputees)
            calibres[i] = _score(artifact, _standardiser(artifact, x))[0]
        b_brut, s_brut = brier(bruts, verites)
        b_cal, s_cal = brier(calibres, verites)
        a_brut = auc(bruts, verites)
        a_cal = auc(calibres, verites)
        txt_brut = "  None" if a_brut is None else f"{a_brut:>6.3f}"
        txt_cal = "  None" if a_cal is None else f"{a_cal:>6.3f}"
        print(
            f"{h:>2} | {bruts.size:>4} {verites.mean():>6.3f} "
            f"| {b_brut:>10.4f} {s_brut:>+7.3f} {txt_brut} "
            f"| {b_cal:>10.4f} {s_cal:>+7.3f} {txt_cal}"
        )

    if imputes_signales:
        print(f"\nFeatures IMPUTEES (absentes du journal) : {sorted(imputes_signales)}")
        print("Elles sont remplacees par leur moyenne d'entrainement — la calibration")
        print("travaille donc sur une information partielle.")


if __name__ == "__main__":
    main()
