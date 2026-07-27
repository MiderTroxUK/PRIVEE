r"""Modèle de comportement (palier 1, U7) — ajuste et sérialise le modèle par dimension.

Pour chaque dimension de sortie d :

    y_d(p, t) = alpha_{p,d} + x(p, t)·w_d + phi_d · y_d(p, t-1) + eps

- ``alpha_{p,d}`` : intercept de persona, partiellement poolé (pénalité
  ``lambda_alpha``, retenu vers 0 — pas vers une moyenne de groupe séparée,
  ce qui revient au même dans ce montage : pas de colonne d'intercept
  global) ;
- ``w_d`` : pente sur les 29 features x(p, t) (9 KPI x [val, d1, d2] +
  event_flag + press_flag, cf. ``declarants.vectorize_features``) ;
- ``phi_d`` : autorégression sur LA MÊME dimension au tour précédent.

``w_d`` et ``phi_d`` sont pénalisés ensemble par ``lambda_w`` (les deux sont
des « pentes » au sens du plan U7 — seul ``alpha`` a sa propre pénalité).
Résolution par MOINDRES CARRÉS AUGMENTÉS : les pénalités sont ajoutées comme
des lignes supplémentaires ``sqrt(lambda)·I`` avec cible 0
(``scipy.linalg.lstsq``), jamais une formule fermée réinventée.

Sélection de (lambda_alpha, lambda_w) sur une grille 3x3 par validation
TEMPORELLE : fit sur les tours 1..12, validation sur 13..18 — JAMAIS de
découpage aléatoire (fuite temporelle : un jour de campagne « voit » les
suivants via une AR mal découpée sinon). Le couple retenu sert ensuite à
ré-ajuster le modèle FINAL (sérialisé) sur l'intégralité 1..18 — plus de
données pour le modèle déployé, tandis que le verdict de rétention reste
calculé sur le fit HONNÊTE (1..12 seul, jamais 13..18).

RETENTION : le modèle n'est retenu que s'il bat, sur les tours de
validation, la baseline « biais de profil seul » — reconstruction de
``inject_tour._submit_synthetic_ahp`` (comparaisons neutres, notes ancrées
sur ``1 + 8·ur_local``) — sur une MAJORITÉ des 10 dimensions (4 notes + 6
comparaisons). ``ur_local`` réel n'étant pas dans ``data/prepared/`` (calculé
par le moteur, pas stocké), la baseline utilise un PROXY documenté
(:func:`_ur_local_proxy`) — limitation assumée, jamais utilisée par le
modèle palier 1 lui-même (qui consomme x(p,t) brut, pas le proxy).

Entrées :
    - les 8 ``.../llm_pilot_run/sandbox_<node>/results.jsonl`` du DÉPÔT
      PRINCIPAL (non versionnés, absents de ce worktree — lecture SEULE à un
      chemin absolu fixe, jamais dérivé de ``__file__``) ;
    - ``data/prepared/`` de CE worktree (lecture seule, jamais modifié).

Sortie : ``analysis/behavior_params.json`` (consommé par
``factory.declarants.RidgeDeclarant``).

Usage :
    .venv\Scripts\python.exe projects/simu_semiconducteurs/analysis/behavior_model.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
from scipy.linalg import lstsq

_ANALYSIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _ANALYSIS_DIR.parent  # projects/simu_semiconducteurs
_REPO_ROOT = _PROJECT_DIR.parent.parent  # racine de CE worktree
_SCRIPTS_DIR = _PROJECT_DIR / "scripts"
_SCENARIO_DIR = _PROJECT_DIR / "scenario"
_FACTORY_DIR = _REPO_ROOT / "projects" / "factory"
_PREPARED = _PROJECT_DIR / "data" / "prepared"
_PARAMS_PATH = _ANALYSIS_DIR / "behavior_params.json"

#: Dépôt PRINCIPAL (JAMAIS ce worktree) : artefacts pilotes non versionnés.
#: Chemin ABSOLU fixe (pas dérivé de __file__, qui pointerait ce worktree) —
#: consigne explicite de la campagne U7 : lecture seule, jamais d'écriture.
_MAIN_REPO = Path(r"C:\PRIVEE\AZURE")
_PILOT_ROOT = _MAIN_REPO / "projects" / "simu_semiconducteurs" / "analysis" / "llm_pilot_run"

for _p in (str(_SCRIPTS_DIR), str(_SCENARIO_DIR), str(_FACTORY_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import make_briefings  # noqa: E402
import scenario  # noqa: E402
from declarants import (  # noqa: E402
    BIPOLAR_DIMS,
    DIMENSIONS,
    KPI_PATHS,
    N_FEATURES,
    SCORE_DIMS,
    carried_value,
    kpi_history,
    reconstruct_features,
    vectorize_features,
)

if tuple(make_briefings.FIELD_LABELS) != KPI_PATHS:
    raise AssertionError(
        "declarants.KPI_PATHS a dérivé de make_briefings.FIELD_LABELS — "
        "resynchronisez les deux constantes avant de ré-ajuster le modèle."
    )

NODE_IDS: list[str] = [n["id"] for n in scenario.NODES]
N_TOURS: int = scenario.N_TOURS
N_PERSONAS: int = len(NODE_IDS)
LAMBDA_GRID: tuple[float, ...] = (0.1, 1.0, 10.0)
TRAIN_TOURS: range = range(1, 13)  # 1..12
VAL_TOURS: range = range(13, 19)  # 13..18

# Colonnes du design par dimension : [persona (8, one-hot) | features (29) | phi (1, AR)]
_COL_PERSONA = slice(0, N_PERSONAS)
_COL_FEATURES = slice(N_PERSONAS, N_PERSONAS + N_FEATURES)
_COL_PHI = N_PERSONAS + N_FEATURES
N_COLS = N_PERSONAS + N_FEATURES + 1


# --- Chargement des traces pilotes (dépôt principal, lecture seule) ----------------


def _load_pilot_traces() -> dict[str, dict[int, dict]]:
    """Charge les 8 ``results.jsonl`` par (nœud, tour) ; ignore la ligne « debrief »."""
    traces: dict[str, dict[int, dict]] = {}
    for node_id in NODE_IDS:
        path = _PILOT_ROOT / f"sandbox_{node_id}" / "results.jsonl"
        if not path.exists():
            raise FileNotFoundError(
                f"Artefact pilote manquant pour « {node_id} » : {path}\n"
                "Attendu en LECTURE SEULE depuis le dépôt principal (donnée de "
                "campagne non versionnée dans ce worktree)."
            )
        by_tour: dict[int, dict] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("tour") == "debrief":
                continue
            by_tour[int(rec["tour"])] = rec
        traces[node_id] = by_tour
    return traces


def _y_vector(rec: dict) -> list[float]:
    """Vecteur cible (10,) : 4 notes UI puis 6 comparaisons bipolaires."""
    return [float(v) for v in rec["scores_ui"]] + [float(v) for v in rec["bipolar"]]


def _build_rows(
    traces: dict[str, dict[int, dict]], features_by_nt: dict[tuple[str, int], dict]
) -> list[dict]:
    """Une ligne exploitable par (nœud, tour) pour t=1..N_TOURS (t-1 requis pour l'AR)."""
    rows: list[dict] = []
    for node_id in NODE_IDS:
        by_tour = traces[node_id]
        for t in range(1, N_TOURS + 1):
            if t not in by_tour or (t - 1) not in by_tour:
                continue
            feat = features_by_nt.get((node_id, t))
            if feat is None:
                continue
            rows.append(
                {
                    "node_id": node_id,
                    "tour": t,
                    "x": vectorize_features(feat, KPI_PATHS),
                    "y": _y_vector(by_tour[t]),
                    "y_prev": _y_vector(by_tour[t - 1]),
                }
            )
    return rows


# --- Moindres carrés augmentés (ridge par groupes de colonnes) ---------------------


def _design_matrix(rows: list[dict], dim_index: int) -> tuple[np.ndarray, np.ndarray]:
    """Matrice de design (n, N_COLS) et cible (n,) pour la dimension ``dim_index``."""
    node_col = {nid: i for i, nid in enumerate(NODE_IDS)}
    n = len(rows)
    x = np.zeros((n, N_COLS))
    y = np.zeros(n)
    for r, row in enumerate(rows):
        x[r, node_col[row["node_id"]]] = 1.0
        x[r, _COL_FEATURES] = row["x"]
        x[r, _COL_PHI] = row["y_prev"][dim_index]
        y[r] = row["y"][dim_index]
    return x, y


def _fit_penalized(
    x: np.ndarray, y: np.ndarray, lambda_alpha: float, lambda_w: float
) -> np.ndarray:
    """Moindres carrés augmentés : lignes de pénalité ``sqrt(lambda)·I`` par groupe.

    Groupe « persona » (colonnes one-hot) pénalisé par ``lambda_alpha``,
    groupe « pentes » (features + phi AR) pénalisé par ``lambda_w`` — cf.
    docstring module. Toutes les colonnes sont pénalisées (pas d'intercept
    global séparé) : la matrice augmentée est donc de rang plein par
    construction (diag(pénalité) > 0 partout), jamais de système singulier.
    """
    penalty = np.zeros(N_COLS)
    penalty[_COL_PERSONA] = np.sqrt(lambda_alpha)
    penalty[_COL_FEATURES] = np.sqrt(lambda_w)
    penalty[_COL_PHI] = np.sqrt(lambda_w)
    x_aug = np.vstack([x, np.diag(penalty)])
    y_aug = np.concatenate([y, np.zeros(N_COLS)])
    beta, *_rest = lstsq(x_aug, y_aug)
    return beta


def _mae(x: np.ndarray, y: np.ndarray, beta: np.ndarray) -> float:
    return float(np.mean(np.abs(x @ beta - y)))


def _fit_all_dims(rows: list[dict], lambda_alpha: float, lambda_w: float) -> dict[str, np.ndarray]:
    """Ajuste beta_d pour les 10 dimensions sur ``rows`` au couple donné."""
    betas: dict[str, np.ndarray] = {}
    for d, dim in enumerate(DIMENSIONS):
        x, y = _design_matrix(rows, d)
        betas[dim] = _fit_penalized(x, y, lambda_alpha, lambda_w)
    return betas


def _select_lambdas(rows: list[dict]) -> tuple[float, float]:
    """Grille 3x3 ; critère = MAE de validation normalisée moyenne (10 dimensions).

    Normalisation par l'étendue de chaque dimension (5 pour les notes UI
    [1,6], 16 pour les comparaisons [-8,8]) pour qu'une seule dimension à
    forte amplitude ne domine pas la sélection.
    """
    train_rows = [r for r in rows if r["tour"] in TRAIN_TOURS]
    val_rows = [r for r in rows if r["tour"] in VAL_TOURS]
    if not train_rows or not val_rows:
        raise RuntimeError(
            "Jeu d'entraînement/validation temporel vide — données pilotes incomplètes ?"
        )
    ranges = [5.0] * len(SCORE_DIMS) + [16.0] * len(BIPOLAR_DIMS)

    print("\n=== Grille (lambda_alpha, lambda_w) — MAE de validation normalisée moyenne ===")
    best: tuple[float, float, float] | None = None
    for lambda_alpha in LAMBDA_GRID:
        for lambda_w in LAMBDA_GRID:
            normed = []
            for d in range(len(DIMENSIONS)):
                x_tr, y_tr = _design_matrix(train_rows, d)
                x_val, y_val = _design_matrix(val_rows, d)
                beta = _fit_penalized(x_tr, y_tr, lambda_alpha, lambda_w)
                normed.append(_mae(x_val, y_val, beta) / ranges[d])
            score = float(np.mean(normed))
            if best is None or score < best[2]:
                best = (lambda_alpha, lambda_w, score)
            print(f"  lambda_alpha={lambda_alpha:<5} lambda_w={lambda_w:<5} score={score:.4f}")
    assert best is not None
    print(f"  -> retenu : lambda_alpha={best[0]}, lambda_w={best[1]} (score={best[2]:.4f})")
    return best[0], best[1]


# --- Baseline « biais de profil seul » (inject_tour._submit_synthetic_ahp) ---------

#: KPI déjà sur une échelle bornée : écart absolu à un plafond documenté.
_PROXY_ABS_REF: dict[str, tuple[float, float]] = {
    "risk.failure_probability": (0.0, 0.05),
    "risk.cost_volatility": (0.0, 0.05),
    "oee.performance": (1.0, 1.0),
    "oee.availability": (1.0, 1.0),
}
#: KPI à échelle propre au nœud : écart RELATIF à la première valeur
#: observée (+1 : une hausse est une tension ; -1 : une baisse l'est).
_PROXY_REL_DIRECTION: dict[str, int] = {
    "network.demand": 1,
    "time.lead_time_h": 1,
    "cost.op_cost": 1,
    "inventory.current_volume_m3": 1,
    "inventory.flow_rate": -1,
}


def _ur_local_proxy(hist: dict, node_id: str, t: int) -> float:
    """PROXY documenté d'urgence locale.

    Le ``ur_local`` réel du moteur n'est pas dans ``data/prepared/`` : il
    est calculé en rejouant la simulation, hors périmètre de ce script en
    lecture seule. Moyenne de signaux de tension normalisés [0, 1], calculée UNIQUEMENT à
    partir des KPI EFFECTIVEMENT observés pour ce nœud (un chemin jamais
    observé est ignoré, jamais compté comme « 0 = aucune tension »). Sert
    SEULEMENT à instancier la baseline ci-dessous ; jamais consommé par le
    modèle palier 1 (qui utilise x(p,t) brut, cf. :func:`vectorize_features`).
    """
    signals: list[float] = []
    for path, (nominal, span) in _PROXY_ABS_REF.items():
        v = carried_value(hist, node_id, path, t)
        if v is not None:
            signals.append(float(np.clip(abs(v - nominal) / span, 0.0, 1.0)))
    for path, direction in _PROXY_REL_DIRECTION.items():
        v = carried_value(hist, node_id, path, t)
        v0 = carried_value(hist, node_id, path, 0)
        if v is None or not v0:
            continue
        signals.append(float(np.clip(direction * (v / v0 - 1.0), 0.0, 1.0)))
    return float(np.mean(signals)) if signals else 0.0


def _profile_bias_by_node() -> dict[str, float]:
    bias: dict[str, float] = {}
    for profile in scenario.SYNTHETIC_PROFILES.values():
        for node_id in profile["nodes"]:
            bias[node_id] = profile["bias"]
    return bias


def _baseline_prediction(
    node_id: str, t: int, hist: dict, bias_by_node: dict[str, float]
) -> list[float]:
    """Reconstruction de ``inject_tour._submit_synthetic_ahp``.

    4 notes UI [1,6] ancrées sur ``1 + 8·ur_local`` (ici : le proxy) + biais
    de profil + bruit déterministe (même graine ``f"{node}-{tour}"``),
    mappées de [1,9] vers [1,6] par l'inverse de ``score_6_to_9`` ; 6
    comparaisons TOUJOURS neutres (0) — la baseline synthétique ne fait
    jamais varier les comparaisons par paire, seulement les notes.
    """
    ur = _ur_local_proxy(hist, node_id, t)
    nominal9 = 1.0 + 8.0 * min(max(ur, 0.0), 1.0)
    bias = bias_by_node.get(node_id, 0.0)
    rng = random.Random(f"{node_id}-{t}")
    scores9 = [min(max(nominal9 + bias + rng.uniform(-0.5, 0.5), 1.0), 9.0) for _ in range(4)]
    scores_ui = [1.0 + (s - 1.0) * 5.0 / 8.0 for s in scores9]
    return scores_ui + [0.0] * 6


# --- Validation temporelle honnête + verdict de rétention --------------------------


def _validation_report(
    val_rows: list[dict],
    betas_holdout: dict[str, np.ndarray],
    hist: dict,
    bias_by_node: dict[str, float],
) -> dict:
    """MAE modèle (fit 1..12 SEUL) vs baseline sur les tours 13..18, par dimension."""
    report: dict[str, dict] = {}
    n_wins = 0
    print("\n=== Validation temporelle (fit tours 1..12, validation 13..18) ===")
    print(f"{'dimension':<16}{'MAE modele':>12}{'MAE baseline':>14}   verdict")
    for d, dim in enumerate(DIMENSIONS):
        x_val, y_val = _design_matrix(val_rows, d)
        mae_model = _mae(x_val, y_val, betas_holdout[dim])
        baseline_preds = np.array(
            [_baseline_prediction(r["node_id"], r["tour"], hist, bias_by_node)[d] for r in val_rows]
        )
        mae_baseline = float(np.mean(np.abs(baseline_preds - y_val)))
        win = mae_model < mae_baseline
        n_wins += int(win)
        report[dim] = {"mae_model": mae_model, "mae_baseline": mae_baseline, "model_wins": win}
        verdict = "modele" if win else "baseline"
        print(f"{dim:<16}{mae_model:>12.3f}{mae_baseline:>14.3f}   {verdict}")
    retained = n_wins > len(DIMENSIONS) / 2
    print(
        f"\nModele meilleur que la baseline sur {n_wins}/{len(DIMENSIONS)} dimensions "
        f"(seuil majorité > {len(DIMENSIONS) / 2:.1f}) -> RETENU = {retained}"
    )
    report["summary"] = {"n_wins": n_wins, "n_dims": len(DIMENSIONS), "retained": retained}
    return report


# --- Sérialisation -------------------------------------------------------------------


def _split_beta(betas: dict[str, np.ndarray]) -> tuple[dict, dict, dict]:
    """Éclate chaque beta_d en (alpha par persona + générique, poids, phi)."""
    alpha: dict[str, dict[str, float]] = {nid: {} for nid in NODE_IDS}
    alpha["__generic__"] = {}
    weights: dict[str, list[float]] = {}
    phi: dict[str, float] = {}
    for dim, beta in betas.items():
        for i, nid in enumerate(NODE_IDS):
            alpha[nid][dim] = float(beta[i])
        alpha["__generic__"][dim] = 0.0
        weights[dim] = [float(v) for v in beta[_COL_FEATURES]]
        phi[dim] = float(beta[_COL_PHI])
    return alpha, weights, phi


def _residual_pools(rows: list[dict], betas: dict[str, np.ndarray]) -> dict[str, list[float]]:
    """Résidus empiriques (y - prédiction) du modèle final, par dimension.

    Pour le tirage bootstrap de :class:`declarants.RidgeDeclarant`.
    """
    pools: dict[str, list[float]] = {}
    for d, dim in enumerate(DIMENSIONS):
        x_all, y_all = _design_matrix(rows, d)
        pred = x_all @ betas[dim]
        pools[dim] = [float(v) for v in (y_all - pred)]
    return pools


def main() -> int:
    """Point d'entrée : ajuste, valide, sérialise. Retourne 0 (jamais d'échec silencieux)."""
    print("[behavior_model] chargement des traces pilotes (dépôt principal, lecture seule)...")
    traces = _load_pilot_traces()
    print(f"[behavior_model] {sum(len(v) for v in traces.values())} déclarations pilotes chargées "
          f"({len(NODE_IDS)} nœuds).")

    print("[behavior_model] reconstruction des features depuis data/prepared/ (lecture seule)...")
    features_by_nt = reconstruct_features(_PREPARED, NODE_IDS, N_TOURS)
    rows = _build_rows(traces, features_by_nt)
    print(f"[behavior_model] {len(rows)} lignes (nœud, tour) exploitables (t=1..{N_TOURS}).")

    lambda_alpha, lambda_w = _select_lambdas(rows)

    # Vérité de validation HONNÊTE : entraîné UNIQUEMENT sur les tours 1..12
    # (jamais 13..18) — c'est CE fit qui détermine le verdict de rétention.
    train_rows = [r for r in rows if r["tour"] in TRAIN_TOURS]
    val_rows = [r for r in rows if r["tour"] in VAL_TOURS]
    betas_holdout = _fit_all_dims(train_rows, lambda_alpha, lambda_w)
    hist = kpi_history(_PREPARED, N_TOURS)
    bias_by_node = _profile_bias_by_node()
    validation = _validation_report(val_rows, betas_holdout, hist, bias_by_node)

    # Modèle DÉPLOYÉ : ré-ajusté sur l'intégralité 1..18 au MÊME couple de
    # pénalités (plus de données pour le modèle qui sert vraiment en production).
    betas_final = _fit_all_dims(rows, lambda_alpha, lambda_w)
    residuals = _residual_pools(rows, betas_final)
    alpha, weights, phi = _split_beta(betas_final)

    params = {
        "kpi_paths": list(KPI_PATHS),
        "dimensions": list(DIMENSIONS),
        "node_ids": list(NODE_IDS),
        "n_features": N_FEATURES,
        "lambda_alpha": lambda_alpha,
        "lambda_w": lambda_w,
        "alpha": alpha,
        "weights": weights,
        "phi": phi,
        "residuals": residuals,
        "validation": validation,
        "retained": validation["summary"]["retained"],
    }
    _PARAMS_PATH.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[behavior_model] paramètres écrits -> {_PARAMS_PATH}")
    print(
        "[behavior_model] NB : plusieurs personas (orbitalys notamment) n'ont "
        "quasiment aucun signal sur les 9 KPI du contrat gelé (leurs "
        "kpi_paths pertinents n'apparaissent jamais dans data/prepared/) — "
        "leur Ud pilote est en réalité piloté par les jalons/narratif, hors "
        "périmètre du contrat U7. Pour ces personas, alpha + phi (AR) portent "
        "l'essentiel du signal ; ce n'est pas un bug, c'est la frontière du "
        "contrat gelé."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
