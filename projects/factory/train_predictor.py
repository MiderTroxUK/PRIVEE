"""Post-traitement EMOS + entrainement + export d'artefact de risque HELIOS v7 (U10).

Consomme le dataset personne-periode (contrat 4, produit par ``build_dataset.py``,
unite soeur U8) et produit l'artefact numpy-only de scoring (contrat 5, consomme par
``PredictionService`` de l'unite soeur U11) : ``OUT/models/v1/artifact.json`` +
``model_card.md`` + ``model.joblib`` + des courbes de fiabilite PNG par axe
d'evaluation.

Modele PRIMAIRE - EMOS (" Ensemble Model Output Statistics ", plan D8) : quand
``p_rollout`` (issu du rollout Monte Carlo de U9) est present dans le jeu de
donnees, on ajuste::

    logit(p) = a-logit(clip(p_rollout)) + b-spread + c-x_keys + d

ou ``x_keys`` (<=10 features) sont selectionnees par regression logistique L1 sur
le pli d'entrainement, suivi d'une calibration isotonique (repli sigmoide si
n_train < 5000). Quand ``p_rollout`` est absent, EMOS DEGENERE vers le modele
pur-ML (regression logistique L2 sur toutes les features, puis calibration) -
annonce explicitement a l'ecran.

Challengers (jamais exportes, seulement compares dans le tableau du model card) :
rollout brut (aucun apprentissage), regression logistique L2 complete, et
HistGradientBoostingClassifier - tous NON calibres (seul EMOS l'est, par
definition).

Trois axes d'evaluation, hyperparametres regles UNIQUEMENT a l'interieur du pli
d'entrainement de chacun (plan D10) :
    (i)   GroupKFold(5) par ``chain_id`` (" chaines tenues ")
    (ii)  hold-out par groupe ``dgp_params_id`` (" regime DGP tenu ")
    (iii) coupure temporelle : train ``t<=12`` / test ``t>=13``

Decision de conception (contrat 4 gele n'expose PAS de colonne de tour/temps
brute - ``build_dataset.py`` la retire avant ecriture) : l'axe temporel utilise
``beta_n`` (nombre de tours reellement observes pour le noeud jusqu'a t inclus,
donc STRICTEMENT croissant avec t, egal a t+1 en l'absence de trou) comme proxy
de l'ordinal temporel. Documente ici, rappele dans le model card.

Regle de decision (plan D8, codee) : si le rollout brut bat EMOS en Brier sur
l'axe " chaines tenues ", l'artefact EXPORTE degenere en calibration isotonique
SEULE sur p_rollout (representee dans le meme format que le contrat 5 :
feature_names=["logit_p_rollout"], coef=[1.0], intercept=0.0, scaler identite -
de sorte que sigmoid(z) = p_rollout exactement, seule la calibration agit).

Reproductibilite numpy (frozen contract 5) : le score est
``z = coef-(x-mean)/std + intercept`` puis ``p = interp(calibrateur, sigmoid(z))``
- EXACTEMENT la formule utilisee par ``PredictionService`` (U11). Une assertion
en fin de script compare cette reproduction numpy a la sortie native sklearn sur
100 lignes (tolerance 1e-8) : voir :func:`assert_numpy_matches_sklearn` et la
note de conception sur la construction de ``calibrator_x``/``calibrator_y``
(grille = valeurs distinctes du score brut sur les donnees d'entrainement -
meme principe que les seuils natifs d'``IsotonicRegression``, qui garantit une
interpolation EXACTE par ``np.interp`` a ces points, y compris pour le repli
sigmoide ou la courbe est re-echantillonnee a cette meme grille).

Manquants (contrat 4 : cellule CSV vide = manquant, jamais 0 silencieux) :
imputation par MEDIANE (calculee sur le pli d'entrainement uniquement, jamais
sur le pli de test) + colonne indicatrice ``<feature>_missing`` ajoutee pour
toute feature ayant au moins une valeur manquante dans le jeu charge - voir
:class:`Imputer`.

Usage::

    python train_predictor.py --dataset dataset.csv --out OUT [--fast]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import GroupKFold, cross_val_predict

SCHEMA_VERSION = 1
EPS = 1e-4
RNG_SEED = 20260724

# Contrat 4 (gele, produit par build_dataset.py - U8)

GROUP_COLS = ("chain_id", "node_id", "dgp_params_id")
LABEL_Y1 = "y1"
LABEL_Y4 = "y4"

FEATURE_LOCAL = ["ud", "ur", "ud_local", "ur_local", "hidden_risk", "false_urgency", "adequation"]
FEATURE_U_BLOCS = ["u_time", "u_cap", "u_perf", "u_risk", "u_cost", "u_co2"]
FEATURE_DYNAMICS = [
    "d1_ur_local",
    "d2_ur_local",
    "d3_ur_local",
    "d4_ur_local",
    "d1_H",
    "d2_H",
    "d3_H",
    "d4_H",
    "ema_ur_local",
    "event_recent",
    "weeks_since_event",
]
FEATURE_BAYES = ["beta_mean", "beta_var", "beta_n"]
FEATURE_MC = [
    "p_retard_jalon",
    "p_impact_final",
    "delta_ell_final",
    "delta_ell_max",
    "p_rollout",
    "spread",
]
FEATURE_STRUCTURAL = ["depth_frac", "in_deg", "out_deg", "log_n_nodes", "impact_frac"]
FEATURE_NEIGHBORHOOD = ["mean_ur_pred", "max_ur_pred", "frac_pred_satures", "mean_beta_in"]

FEATURE_COLS = (
    FEATURE_LOCAL
    + FEATURE_U_BLOCS
    + FEATURE_DYNAMICS
    + FEATURE_BAYES
    + FEATURE_MC
    + FEATURE_STRUCTURAL
    + FEATURE_NEIGHBORHOOD
)
P_ROLLOUT_COL = "p_rollout"
SPREAD_COL = "spread"

MODEL_NAMES = ("emos", "rollout_brut", "ml_pur_l2", "hgb")
MODEL_LABELS_FR = {
    "emos": "EMOS",
    "rollout_brut": "Rollout brut",
    "ml_pur_l2": "ML pur (L2)",
    "hgb": "HistGradientBoosting",
}
AXIS_LABELS_FR = {
    "chaines": "Chaînes tenues (GroupKFold(5) par chain_id)",
    "dgp": "Régime DGP tenu (hold-out par dgp_params_id)",
    "temporel": "Coupure temporelle (train t<=12 / test t>=13, proxy beta_n)",
}

ECHELLE_PREUVE_T1_T4 = """\
- **T1 — fonctionnement** (synthétique) : le pipeline tourne, se calibre et
  reproduit ses propres prédictions en numpy — niveau atteint par CE run (fixture
  synthétique).
- **T2 — généralisation** : tenue sur des chaînes et des régimes DGP inédits
  (axes « chaînes tenues » et « régime DGP tenu » ci-dessous).
- **T3 — rejeu historique** : campagne HÉLIOS (crise des semi-conducteurs) ou
  extension énergie 2022 — nécessite le dataset réel produit par U8 sur les runs
  de la campagne, pas cette fixture.
- **T4 — utilité** : observation puis intervention contrôlée (terrain, hors code).
"""


# Chargement du dataset (contrat 4)


@dataclass
class Dataset:
    """Jeu de donnees personne-periode charge depuis le CSV (contrat 4)."""

    chain_id: np.ndarray
    node_id: np.ndarray
    dgp_params_id: np.ndarray
    y1: np.ndarray
    y4: np.ndarray
    x: np.ndarray
    feature_names: list[str]


def _parse_float_cell(raw: str) -> float:
    """Convertit une cellule CSV en float ; chaine vide -> NaN (manquant)."""
    if raw == "":
        return math.nan
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"valeur non finie inattendue dans le CSV : {raw!r}")
    return value


def load_dataset(path: Path) -> Dataset:
    """Charge et valide le schema du dataset (contrat 4) depuis un CSV.

    Args:
        path: chemin du CSV produit par ``build_dataset.py`` (ou une fixture
            compatible - voir ``fixtures/make_predictor_fixture.py``).

    Returns:
        Le dataset charge (colonnes de groupe, labels, matrice de features).

    Raises:
        ValueError: colonnes du contrat 4 manquantes, ou fichier vide.
    """
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        required = [*GROUP_COLS, LABEL_Y1, LABEL_Y4, *FEATURE_COLS]
        missing_cols = [c for c in required if c not in fieldnames]
        if missing_cols:
            raise ValueError(
                "Dataset non conforme au contrat 4 — colonnes manquantes : "
                + ", ".join(missing_cols)
            )
        rows = list(reader)
    if not rows:
        raise ValueError(f"Dataset vide : {path}")

    n = len(rows)
    x = np.empty((n, len(FEATURE_COLS)), dtype=np.float64)
    for j, col in enumerate(FEATURE_COLS):
        x[:, j] = [_parse_float_cell(r[col]) for r in rows]

    return Dataset(
        chain_id=np.array([r["chain_id"] for r in rows], dtype=object),
        node_id=np.array([r["node_id"] for r in rows], dtype=object),
        dgp_params_id=np.array([r["dgp_params_id"] for r in rows], dtype=object),
        y1=np.array([_parse_float_cell(r[LABEL_Y1]) for r in rows]),
        y4=np.array([_parse_float_cell(r[LABEL_Y4]) for r in rows]),
        x=x,
        feature_names=list(FEATURE_COLS),
    )


# Imputation mediane + indicatrices de manquance


@dataclass
class Imputer:
    """Imputation par mediane (apprise sur train) + colonnes indicatrices de manquance.

    ``indicator_mask`` est une propriete STRUCTURELLE du dataset charge (quelles
    colonnes ont au moins une valeur manquante QUELQUE PART dans le jeu complet),
    fixee une fois pour toutes avant tout decoupage en plis - ce n'est pas une
    fuite d'information de label, seulement une decision de forme des colonnes
    (coherente entre tous les plis). Les VALEURS de mediane, elles, sont
    re-apprises a chaque pli sur son propre train, jamais sur le test.
    """

    feature_names: list[str]
    medians: np.ndarray
    indicator_mask: np.ndarray

    @classmethod
    def fit(cls, x: np.ndarray, feature_names: list[str], indicator_mask: np.ndarray) -> Imputer:
        """Apprend les medianes par colonne sur ``x`` (a appeler sur un train fold).

        Une colonne entierement manquante dans ``x`` (ex. ``p_retard_jalon``,
        reservee et toujours vide au schema v1) fait emettre a numpy un
        ``RuntimeWarning`` "All-NaN slice encountered" bien que le repli a 0.0
        juste apres soit correct et attendu - silencie explicitement ici pour ne
        pas polluer la sortie d'un cas normal et documente.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            medians = np.nanmedian(x, axis=0)
        medians = np.where(np.isfinite(medians), medians, 0.0)
        return cls(list(feature_names), medians, indicator_mask)

    def transform(self, x: np.ndarray) -> tuple[np.ndarray, list[str]]:
        """Impute les manquants et ajoute les colonnes indicatrices."""
        miss = ~np.isfinite(x)
        x_filled = np.where(miss, self.medians[np.newaxis, :], x)
        ind_idx = np.flatnonzero(self.indicator_mask)
        indicators = miss[:, ind_idx].astype(np.float64)
        out_names = [*self.feature_names, *(f"{self.feature_names[i]}_missing" for i in ind_idx)]
        return np.hstack([x_filled, indicators]), out_names


def compute_indicator_mask(x: np.ndarray) -> np.ndarray:
    """Colonnes ayant au moins une valeur manquante n'importe ou dans ``x``."""
    return ~np.isfinite(x).all(axis=0)


# Petits utilitaires numeriques


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def _logit(p: np.ndarray) -> np.ndarray:
    return np.log(p / (1.0 - p))


def _clip_prob(p: np.ndarray, eps: float = EPS) -> np.ndarray:
    return np.clip(p, eps, 1.0 - eps)


def _standardize_fit(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Moyenne/ecart-type par colonne ; ecart-type plancher pour eviter une division par 0."""
    mean = x.mean(axis=0)
    std = x.std(axis=0, ddof=0)
    std_safe = np.where(std < 1e-12, 1.0, std)
    return mean, std_safe


def _standardize_apply(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return (x - mean[np.newaxis, :]) / std[np.newaxis, :]


def _inner_group_kfold(n_splits: int, groups: np.ndarray) -> GroupKFold | None:
    """GroupKFold interne, repli a moins de plis si trop peu de groupes distincts."""
    n_unique = len(np.unique(groups))
    k = min(n_splits, n_unique)
    if k < 2:
        return None
    return GroupKFold(n_splits=k)


# Calibration (isotonique / sigmoide), export en grille reproductible


@dataclass
class Calibrator:
    """Courbe de calibration exportable (np.interp) + modele natif (pour l'assertion)."""

    method: str  # "isotonic" | "sigmoid"
    x: np.ndarray
    y: np.ndarray
    model_obj: IsotonicRegression | LogisticRegression

    def apply(self, raw_p: np.ndarray) -> np.ndarray:
        """Reproduction numpy-only (celle exportee dans artifact.json)."""
        return np.interp(raw_p, self.x, self.y)

    def apply_native(self, raw_p: np.ndarray) -> np.ndarray:
        """Prediction sklearn native (reference pour l'assertion de reproductibilite)."""
        if self.method == "isotonic":
            return self.model_obj.predict(raw_p)
        return self.model_obj.predict_proba(raw_p.reshape(-1, 1))[:, 1]


def fit_calibrator(
    raw_fit: np.ndarray,
    y_fit: np.ndarray,
    raw_grid_source: np.ndarray,
    n_train: int,
) -> Calibrator:
    """Ajuste la calibration (isotonique si n_train>=5000, sinon sigmoide/Platt).

    ``raw_fit``/``y_fit`` = paires (score brut, label) sur lesquelles la fonction
    de calibration est apprise (idealement des predictions HORS-PLI - jamais
    exportees telles quelles : ces scores proviennent de modeles internes a la CV,
    jamais reproductibles par le modele final exporte). La grille EXPORTEE est
    evaluee a chaque valeur DISTINCTE de ``raw_grid_source`` uniquement - comme les
    seuils natifs d'``IsotonicRegression`` - pour garantir une reproduction EXACTE
    (precision flottante) par ``np.interp`` de toute ligne dont le score brut est
    calcule par le modele final exporte (utilise avec son score sur la totalite du
    jeu d'entrainement, pour que l'assertion numpy-vs-sklearn en fin de script -
    qui echantillonne parmi ces memes lignes - soit exacte).
    """
    method = "isotonic" if n_train >= 5000 else "sigmoid"
    grid = np.unique(raw_grid_source)
    if method == "isotonic":
        model: IsotonicRegression | LogisticRegression = IsotonicRegression(
            y_min=0.0, y_max=1.0, out_of_bounds="clip"
        )
        model.fit(raw_fit, y_fit)
        grid_y = model.predict(grid)
    else:
        model = LogisticRegression(max_iter=2000)
        model.fit(raw_fit.reshape(-1, 1), y_fit)
        grid_y = model.predict_proba(grid.reshape(-1, 1))[:, 1]
    return Calibrator(method=method, x=grid, y=grid_y, model_obj=model)


# Modele lineaire standardise + calibre (format exportable, contrat 5)


@dataclass
class LinearCalibratedModel:
    """Un modele logistique standardise + calibre - representation directe du contrat 5."""

    design_feature_names: list[str]
    scaler_mean: np.ndarray
    scaler_std: np.ndarray
    coef: np.ndarray
    intercept: float
    calibrator: Calibrator
    base_estimator: LogisticRegression | None
    n_train: int

    def raw_proba(self, x_design: np.ndarray) -> np.ndarray:
        """Probabilite AVANT calibration (sigmoide du score standardise)."""
        z = _standardize_apply(x_design, self.scaler_mean, self.scaler_std) @ self.coef
        z = z + self.intercept
        return _sigmoid(z)

    def predict_proba(self, x_design: np.ndarray) -> np.ndarray:
        """Probabilite calibree finale - meme formule que le scoring numpy de U11."""
        return self.calibrator.apply(self.raw_proba(x_design))


def fit_linear_calibrated(
    x_design_train: np.ndarray,
    y_train: np.ndarray,
    chain_train: np.ndarray,
    design_feature_names: list[str],
    *,
    calib_source_design: np.ndarray | None = None,
) -> LinearCalibratedModel:
    """Regression logistique L2 (C=1.0) + calibration hors-pli (GroupKFold(3) par chaine).

    Reimplementation A LA MAIN de ce que fait ``CalibratedClassifierCV(ensemble=False)``
    (calibrateur UNIQUE appris sur des predictions hors-pli, estimateur de base
    re-ajuste sur tout le train) plutot qu'un appel direct a cette classe : le
    contrat 5 exige un (coef, intercept, courbe de calibration) UNIQUES, alors que
    ``CalibratedClassifierCV`` expose ses resultats via des attributs internes non
    garantis stables entre versions de sklearn - cette implementation manuelle
    donne un controle total et verifiable sur ce qui est exporte.

    Args:
        x_design_train: matrice de features du pli d'entrainement (deja imputee).
        y_train: labels y1 (0/1) du pli d'entrainement.
        chain_train: ``chain_id`` de chaque ligne (groupes de la CV interne).
        design_feature_names: noms des colonnes de ``x_design_train``.
        calib_source_design: lignes supplementaires (meme colonnes) dont le score
            brut doit etre couvert EXACTEMENT par la grille de calibration
            exportee (typiquement le pli de test, ou l'ensemble du jeu pour le
            modele final - voir :func:`fit_calibrator`).
    """
    mean, std = _standardize_fit(x_design_train)
    x_std = _standardize_apply(x_design_train, mean, std)
    n_train = len(y_train)

    inner_cv = _inner_group_kfold(3, chain_train)
    raw_oof = None
    if inner_cv is not None:
        try:
            raw_oof = cross_val_predict(
                LogisticRegression(C=1.0, max_iter=2000),
                x_std,
                y_train,
                groups=chain_train,
                cv=inner_cv,
                method="predict_proba",
            )[:, 1]
        except ValueError:
            raw_oof = None

    base = LogisticRegression(C=1.0, max_iter=2000).fit(x_std, y_train)
    raw_train = _sigmoid(x_std @ base.coef_[0] + base.intercept_[0])
    if raw_oof is None:
        # Repli : trop peu de chaines distinctes pour une CV groupee interne - calibration apprise directement sur le train (legerement optimiste, signale dans le model card via n_train/nb de chaines).
        raw_oof = raw_train

    raw_grid_source = raw_train
    if calib_source_design is not None:
        extra_std = _standardize_apply(calib_source_design, mean, std)
        raw_extra = _sigmoid(extra_std @ base.coef_[0] + base.intercept_[0])
        raw_grid_source = np.concatenate([raw_train, raw_extra])

    calibrator = fit_calibrator(raw_oof, y_train, raw_grid_source, n_train)

    return LinearCalibratedModel(
        design_feature_names=list(design_feature_names),
        scaler_mean=mean,
        scaler_std=std,
        coef=base.coef_[0].copy(),
        intercept=float(base.intercept_[0]),
        calibrator=calibrator,
        base_estimator=base,
        n_train=n_train,
    )


# Selection L1 (x_keys d'EMOS)

L1_C_SHRINK_GRID = (1.0, 0.3, 0.1, 0.03, 0.01, 0.003, 0.001)


def select_l1_features(
    x_std: np.ndarray, y: np.ndarray, feature_names: list[str], *, max_features: int = 10
) -> list[str]:
    """Selectionne au plus ``max_features`` par regression logistique L1 (liblinear).

    Recherche decroissante de C (retrecissement, cf. ``L1_C_SHRINK_GRID``) jusqu'a
    obtenir au plus ``max_features`` coefficients non nuls ; si le C minimal de la
    grille laisse encore plus de survivants, on garde les ``max_features`` de plus
    grande valeur absolue.

    Note API : ``penalty=`` est deprecie depuis sklearn 1.8 au profit de
    ``l1_ratio`` (``l1_ratio=1.0`` <=> L1) - utilise ici pour rester sans
    avertissement sur la fourchette de version epinglee (scikit-learn>=1.5,<2).
    """
    coefs = np.zeros(x_std.shape[1])
    for c in L1_C_SHRINK_GRID:
        model = LogisticRegression(solver="liblinear", l1_ratio=1.0, C=c, max_iter=2000)
        model.fit(x_std, y)
        coefs = model.coef_[0]
        if np.count_nonzero(coefs) <= max_features:
            break

    nnz = np.flatnonzero(coefs)
    if len(nnz) > max_features:
        order = np.argsort(-np.abs(coefs[nnz]))
        nnz = nnz[order[:max_features]]
    return [feature_names[i] for i in sorted(nnz)]


def build_emos_design(
    x_imputed: np.ndarray, p_rollout_idx: int, spread_idx: int, x_key_indices: list[int]
) -> np.ndarray:
    """Construit [logit(clip(p_rollout)), spread, x_keys...] pour n'importe quel jeu de lignes."""
    logit_rollout = _logit(_clip_prob(x_imputed[:, p_rollout_idx]))
    spread_col = x_imputed[:, spread_idx]
    extra = (
        x_imputed[:, x_key_indices]
        if x_key_indices
        else np.empty((x_imputed.shape[0], 0))
    )
    return np.column_stack([logit_rollout, spread_col, extra])


def fit_emos(
    x_imputed_train: np.ndarray,
    y_train: np.ndarray,
    chain_train: np.ndarray,
    feature_names: list[str],
    p_rollout_idx: int,
    spread_idx: int,
    *,
    extra_grid_source: np.ndarray | None = None,
) -> tuple[LinearCalibratedModel, list[int]]:
    """Ajuste EMOS (plan D8) : logit(p) = a-logit(p_rollout) + b-spread + c-x_keys + d.

    ``x_keys`` sont selectionnees par L1 sur le pool de candidats = toutes les
    features SAUF les colonnes brutes p_rollout/spread elles-memes (deja des
    termes dedies a/b) - leurs indicatrices de manquance restent candidates
    (signal distinct : " le rollout MC etait-il disponible " n'est pas sa valeur).
    """
    candidate_mask = np.ones(x_imputed_train.shape[1], dtype=bool)
    candidate_mask[p_rollout_idx] = False
    candidate_mask[spread_idx] = False
    candidate_indices = np.flatnonzero(candidate_mask)
    candidate_names = [feature_names[i] for i in candidate_indices]

    cand_mean, cand_std = _standardize_fit(x_imputed_train[:, candidate_indices])
    cand_x_std = _standardize_apply(x_imputed_train[:, candidate_indices], cand_mean, cand_std)
    selected_names = select_l1_features(cand_x_std, y_train, candidate_names, max_features=10)
    x_key_indices = [feature_names.index(nm) for nm in selected_names]

    x_design_train = build_emos_design(x_imputed_train, p_rollout_idx, spread_idx, x_key_indices)
    design_names = ["logit_p_rollout", "spread", *selected_names]

    extra_design = None
    if extra_grid_source is not None:
        extra_design = build_emos_design(
            extra_grid_source, p_rollout_idx, spread_idx, x_key_indices
        )

    model = fit_linear_calibrated(
        x_design_train, y_train, chain_train, design_names, calib_source_design=extra_design
    )
    return model, x_key_indices


# Challengers (jamais exportes, comparaison seulement)


def fit_pure_lr_l2(
    x_full_train: np.ndarray, y_train: np.ndarray, chain_train: np.ndarray, *, fast: bool
) -> tuple[LogisticRegression, np.ndarray, np.ndarray, float]:
    """LogisticRegression(l2) sur TOUTES les features, C choisi par CV interne (D10).

    Retourne (modele re-ajuste sur tout le train avec le meilleur C, mean, std,
    best_C). Le C n'est jamais choisi en regardant le pli externe.
    """
    mean, std = _standardize_fit(x_full_train)
    x_std = _standardize_apply(x_full_train, mean, std)
    c_grid = np.logspace(-2, 1, 3 if fast else 7)
    inner_cv = _inner_group_kfold(3, chain_train)

    best_c = float(c_grid[len(c_grid) // 2])
    best_brier = math.inf
    if inner_cv is not None:
        for c in c_grid:
            try:
                oof = cross_val_predict(
                    LogisticRegression(C=c, max_iter=2000),
                    x_std,
                    y_train,
                    groups=chain_train,
                    cv=inner_cv,
                    method="predict_proba",
                )[:, 1]
            except ValueError:
                continue
            brier = float(np.mean((oof - y_train) ** 2))
            if brier < best_brier:
                best_brier, best_c = brier, float(c)

    model = LogisticRegression(C=best_c, max_iter=2000).fit(x_std, y_train)
    return model, mean, std, best_c


def fit_hgb(
    x_full_train: np.ndarray, y_train: np.ndarray, *, fast: bool
) -> HistGradientBoostingClassifier:
    """HistGradientBoostingClassifier a hyperparametres FIXES (pas de recherche)."""
    return HistGradientBoostingClassifier(
        max_leaf_nodes=15,
        learning_rate=0.1,
        max_iter=50 if fast else 200,
        random_state=0,
    ).fit(x_full_train, y_train)


# Metriques d'evaluation


@dataclass
class FoldMetrics:
    """Metriques agregees (pool hors-pli) d'un modele sur un axe d'evaluation."""

    n: int
    brier: float
    brier_skill: float
    roc_auc: float | None
    pr_auc: float | None
    reliability_mean_pred: list[float]
    reliability_frac_pos: list[float]
    youden_threshold: float | None
    ha4_precision: float | None
    ha4_recall: float | None
    ha4_n: int


def evaluate_predictions(
    y_test: np.ndarray,
    p_pred: np.ndarray,
    baseline_pred: np.ndarray,
    y4_test: np.ndarray | None,
) -> FoldMetrics:
    """Brier+skill, ROC-AUC, PR-AUC, fiabilite, et comparabilite HA4 (precision/rappel).

    ``baseline_pred`` = prediction de climatologie (taux de base du pli
    d'ENTRAINEMENT, jamais du test) pour chaque ligne - un tableau, pas un
    scalaire, car les lignes poolees peuvent provenir de plis differents.
    """
    n = len(y_test)
    brier = float(np.mean((p_pred - y_test) ** 2))
    brier_clim = float(np.mean((baseline_pred - y_test) ** 2))
    skill = 1.0 - brier / brier_clim if brier_clim > 0 else float("nan")

    roc_auc = pr_auc = youden = None
    if len(np.unique(y_test)) >= 2:
        roc_auc = float(roc_auc_score(y_test, p_pred))
        pr_auc = float(average_precision_score(y_test, p_pred))
        fpr, tpr, thr = roc_curve(y_test, p_pred)
        youden = float(thr[int(np.argmax(tpr - fpr))])

    n_bins = int(np.clip(n // 30, 3, 10))
    reliability_mean_pred: list[float] = []
    reliability_frac_pos: list[float] = []
    if n_bins >= 2:
        try:
            frac_pos, mean_pred = calibration_curve(
                y_test, p_pred, n_bins=n_bins, strategy="quantile"
            )
            reliability_mean_pred, reliability_frac_pos = mean_pred.tolist(), frac_pos.tolist()
        except ValueError:
            pass

    ha4_precision = ha4_recall = None
    ha4_n = 0
    if y4_test is not None and youden is not None:
        mask = np.isfinite(y4_test)
        ha4_n = int(mask.sum())
        if ha4_n > 0:
            pred_label = (p_pred[mask] >= youden).astype(int)
            ha4_precision = float(precision_score(y4_test[mask], pred_label, zero_division=0))
            ha4_recall = float(recall_score(y4_test[mask], pred_label, zero_division=0))

    return FoldMetrics(
        n=n,
        brier=brier,
        brier_skill=skill,
        roc_auc=roc_auc,
        pr_auc=pr_auc,
        reliability_mean_pred=reliability_mean_pred,
        reliability_frac_pos=reliability_frac_pos,
        youden_threshold=youden,
        ha4_precision=ha4_precision,
        ha4_recall=ha4_recall,
        ha4_n=ha4_n,
    )


# Axes d'evaluation


def build_axis_folds(
    chain: np.ndarray, dgp: np.ndarray, beta_n: np.ndarray, *, fast: bool
) -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
    """Construit les decoupages des 3 axes geles (plan D10)."""
    n = len(chain)
    idx_all = np.arange(n)
    folds: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}

    k_chain = min(3 if fast else 5, len(np.unique(chain)))
    folds["chaines"] = (
        list(GroupKFold(n_splits=k_chain).split(idx_all, groups=chain)) if k_chain >= 2 else []
    )

    k_dgp = min(3 if fast else 5, len(np.unique(dgp)))
    folds["dgp"] = list(GroupKFold(n_splits=k_dgp).split(idx_all, groups=dgp)) if k_dgp >= 2 else []

    train_mask = beta_n <= 12
    test_mask = beta_n >= 13
    folds["temporel"] = (
        [(idx_all[train_mask], idx_all[test_mask])]
        if train_mask.any() and test_mask.any()
        else []
    )
    return folds


def run_fold(
    x_train: np.ndarray,
    x_test: np.ndarray,
    y_train: np.ndarray,
    chain_train: np.ndarray,
    feature_names: list[str],
    p_rollout_idx: int,
    spread_idx: int,
    has_rollout: bool,
    fast: bool,
) -> tuple[dict[str, np.ndarray], HistGradientBoostingClassifier]:
    """Ajuste les 4 modeles sur ``(x_train, y_train)``, retourne leurs predictions sur ``x_test``.

    ``x_train``/``x_test`` doivent deja etre imputes par un :class:`Imputer` ajuste
    UNIQUEMENT sur les lignes de ce pli (jamais sur ``x_test``) - voir l'appelant
    :func:`run_axis`, qui les construit pli par pli pour qu'aucune mediane ne soit
    jamais partagee entre plis (ce qui ferait fuiter, via la valeur de la mediane,
    de l'information du test d'un pli vers son propre train par un detour via un
    AUTRE pli ou ces memes lignes de test seraient des lignes de train).
    """
    base_rate_train = float(y_train.mean())
    preds: dict[str, np.ndarray] = {}

    if has_rollout:
        preds["rollout_brut"] = _clip_prob(x_test[:, p_rollout_idx])
    else:
        preds["rollout_brut"] = np.full(x_test.shape[0], base_rate_train)

    lr_model, lr_mean, lr_std, _best_c = fit_pure_lr_l2(x_train, y_train, chain_train, fast=fast)
    x_test_std = _standardize_apply(x_test, lr_mean, lr_std)
    preds["ml_pur_l2"] = _sigmoid(x_test_std @ lr_model.coef_[0] + lr_model.intercept_[0])

    hgb_model = fit_hgb(x_train, y_train, fast=fast)
    preds["hgb"] = hgb_model.predict_proba(x_test)[:, 1]

    if has_rollout:
        emos_model, x_key_idx = fit_emos(
            x_train,
            y_train,
            chain_train,
            feature_names,
            p_rollout_idx,
            spread_idx,
            extra_grid_source=x_test,
        )
        x_design_test = build_emos_design(x_test, p_rollout_idx, spread_idx, x_key_idx)
    else:
        emos_model = fit_linear_calibrated(
            x_train,
            y_train,
            chain_train,
            feature_names,
            calib_source_design=x_test,
        )
        x_design_test = x_test
    preds["emos"] = emos_model.predict_proba(x_design_test)

    return preds, hgb_model


@dataclass
class AxisResult:
    """Resultat poole (hors-pli) d'un axe d'evaluation pour les 4 modeles.

    ``hgb_test_x_fold0``/``hgb_test_y_fold0`` materialisent le pli 0 tel
    qu'EFFECTIVEMENT vu par ``hgb_model_fold0`` (meme matrice imputee que celle
    utilisee pour l'entrainer) - captures ici plutot que re-indexes plus tard
    depuis une matrice imputee potentiellement differente (ex. celle du modele
    final, dont les medianes d'imputation ne sont pas celles de ce pli).
    """

    metrics: dict[str, FoldMetrics]
    hgb_model_fold0: HistGradientBoostingClassifier | None
    hgb_test_x_fold0: np.ndarray | None
    hgb_test_y_fold0: np.ndarray | None
    n_folds: int


def run_axis(
    folds: list[tuple[np.ndarray, np.ndarray]],
    x_raw: np.ndarray,
    raw_feature_names: list[str],
    imputed_feature_names: list[str],
    indicator_mask: np.ndarray,
    y1: np.ndarray,
    y4: np.ndarray,
    chain: np.ndarray,
    p_rollout_idx: int,
    spread_idx: int,
    has_rollout: bool,
    fast: bool,
) -> AxisResult | None:
    """Boucle un axe (K plis), poole les predictions hors-pli, calcule les metriques.

    L'imputation (mediane) est re-ajustee INDEPENDAMMENT a chaque pli, sur son
    propre ``train_idx`` uniquement (jamais partagee entre plis via une matrice
    commune : un pli B ou une ligne du TEST du pli A est un TRAIN ferait sinon
    fuiter la valeur de cette ligne dans la mediane qui sert ensuite, par
    ecrasement, a l'imputer - ``x_raw`` est donc toujours la matrice BRUTE
    (non imputee, ``raw_feature_names`` = ses 42 noms de colonnes), tranchee et
    imputee ici, pli par pli. ``imputed_feature_names`` (42 + indicatrices) est
    la liste FIXE (``indicator_mask`` est global) des colonnes apres imputation,
    utilisee pour indexer/selectionner dans les matrices deja imputees.
    """
    if not folds:
        return None
    n = len(y1)
    pooled_preds = {m: np.full(n, np.nan) for m in MODEL_NAMES}
    pooled_baseline = np.full(n, np.nan)
    covered = np.zeros(n, dtype=bool)
    hgb_fold0 = None
    hgb_test_x_fold0 = None
    hgb_test_y_fold0 = None

    for i, (train_idx, test_idx) in enumerate(folds):
        fold_imputer = Imputer.fit(x_raw[train_idx], raw_feature_names, indicator_mask)
        x_train, _names = fold_imputer.transform(x_raw[train_idx])
        x_test, _names = fold_imputer.transform(x_raw[test_idx])
        y_train = y1[train_idx]
        chain_train = chain[train_idx]

        preds, hgb_model = run_fold(
            x_train,
            x_test,
            y_train,
            chain_train,
            imputed_feature_names,
            p_rollout_idx,
            spread_idx,
            has_rollout,
            fast,
        )
        for m in MODEL_NAMES:
            pooled_preds[m][test_idx] = preds[m]
        pooled_baseline[test_idx] = float(y_train.mean())
        covered[test_idx] = True
        if i == 0:
            # Materialise ICI (meme matrice imputee que celle vue par hgb_model pendant son entrainement) - jamais re-indexe depuis une matrice imputee differemment plus tard.
            hgb_fold0 = hgb_model
            hgb_test_x_fold0 = x_test.copy()
            hgb_test_y_fold0 = y1[test_idx].copy()

    metrics = {
        m: evaluate_predictions(
            y1[covered], pooled_preds[m][covered], pooled_baseline[covered], y4[covered]
        )
        for m in MODEL_NAMES
    }
    return AxisResult(
        metrics=metrics,
        hgb_model_fold0=hgb_fold0,
        hgb_test_x_fold0=hgb_test_x_fold0,
        hgb_test_y_fold0=hgb_test_y_fold0,
        n_folds=len(folds),
    )


# Regle de decision + ajustement final (contrat 5)


@dataclass
class FinalArtifactResult:
    """Le modele exporte (EMOS, EMOS degrade, ou degenere) + tracabilite de la decision."""

    model: LinearCalibratedModel
    x_key_indices: list[int] | None
    degenerate: bool
    decision_reason: str


def decide_and_fit_final(
    x_imputed_full: np.ndarray,
    feature_names: list[str],
    y1_full: np.ndarray,
    chain_full: np.ndarray,
    p_rollout_idx: int,
    spread_idx: int,
    has_rollout: bool,
    axis_chaines: AxisResult | None,
) -> FinalArtifactResult:
    """Regle de decision (plan D8, gelee) + ajustement final sur TOUTES les donnees usables."""
    if not has_rollout:
        model = fit_linear_calibrated(x_imputed_full, y1_full, chain_full, feature_names)
        reason = (
            "p_rollout absent du jeu de données (colonne entièrement manquante) : "
            "EMOS dégrade vers le modèle pur-ML (L2 complet, calibré)."
        )
        return FinalArtifactResult(
            model=model, x_key_indices=None, degenerate=False, decision_reason=reason
        )

    degrade = False
    reason = "p_rollout présent : EMOS ajusté normalement."
    if axis_chaines is not None:
        b_emos = axis_chaines.metrics["emos"].brier
        b_roll = axis_chaines.metrics["rollout_brut"].brier
        if b_roll < b_emos:
            degrade = True
            reason = (
                f"Règle de décision : le rollout brut (Brier={b_roll:.4f}) bat EMOS "
                f"(Brier={b_emos:.4f}) sur l'axe « chaînes tenues » -> l'artefact exporté "
                "dégénère en calibration isotonique SEULE sur p_rollout."
            )
        else:
            reason = (
                f"Règle de décision : EMOS (Brier={b_emos:.4f}) conserve l'avantage sur le "
                f"rollout brut (Brier={b_roll:.4f}) sur l'axe « chaînes tenues » -> EMOS exporté."
            )
    else:
        reason = (
            "Règle de décision non évaluable (axe « chaînes tenues » indisponible sur ce "
            "jeu de données) : EMOS exporté par défaut."
        )

    if degrade:
        p_rollout_full = _clip_prob(x_imputed_full[:, p_rollout_idx])
        raw_full = p_rollout_full  # sigmoid(logit(p_rollout)) == p_rollout, coef=[1.0] intercept=0
        # p_rollout est EXOGENE (produit par U9, jamais ajuste sur y1 de ce dataset) : pas de biais optimiste a corriger par une CV interne, la calibration peut etre apprise directement sur (p_rollout, y1) - voir docstring du module.
        calibrator = fit_calibrator(raw_full, y1_full, raw_full, len(y1_full))
        model = LinearCalibratedModel(
            design_feature_names=["logit_p_rollout"],
            scaler_mean=np.array([0.0]),
            scaler_std=np.array([1.0]),
            coef=np.array([1.0]),
            intercept=0.0,
            calibrator=calibrator,
            base_estimator=None,
            n_train=len(y1_full),
        )
        return FinalArtifactResult(
            model=model, x_key_indices=None, degenerate=True, decision_reason=reason
        )

    model, x_key_idx = fit_emos(
        x_imputed_full, y1_full, chain_full, feature_names, p_rollout_idx, spread_idx
    )
    return FinalArtifactResult(
        model=model, x_key_indices=x_key_idx, degenerate=False, decision_reason=reason
    )


def final_design_matrix(
    result: FinalArtifactResult, x_imputed: np.ndarray, p_rollout_idx: int, spread_idx: int
) -> np.ndarray:
    """Reconstruit la matrice de design du modele final pour un jeu de lignes quelconque."""
    if result.degenerate:
        return _logit(_clip_prob(x_imputed[:, p_rollout_idx])).reshape(-1, 1)
    if result.x_key_indices is not None:
        return build_emos_design(x_imputed, p_rollout_idx, spread_idx, result.x_key_indices)
    return x_imputed


# Incertitude : bootstrap de chaines (K refits)


def bootstrap_coef(
    final: FinalArtifactResult,
    x_design_full: np.ndarray,
    y1_full: np.ndarray,
    chain_full: np.ndarray,
    *,
    k: int,
    seed: int,
) -> np.ndarray:
    """K re-ajustements par re-echantillonnage des CHAINES avec remise.

    Le preprocessing du modele final (medianes deja appliquees en amont,
    scaler_mean/std figes) est REUTILISE tel quel : seule l'estimation des
    coefficients varie d'une replique a l'autre, pour isoler la variance
    d'echantillonnage des coefficients eux-memes (l'intercept re-ajuste a chaque
    replique n'est pas exporte - le contrat 5 ne prevoit qu'un intercept
    ponctuel).
    """
    if final.degenerate:
        # Branche degeneree : coef=[1.0] est DEFINITIONNEL (pas estime) -> le bootstrap est trivialement constant, documente dans le model card.
        return np.tile(final.model.coef, (k, 1))

    rng = np.random.default_rng(seed)
    unique_chains = np.unique(chain_full)
    chain_to_rows = {c: np.flatnonzero(chain_full == c) for c in unique_chains}
    n_features = len(final.model.coef)
    coef_boot = np.zeros((k, n_features))

    for b in range(k):
        boot_idx = None
        for _attempt in range(20):
            sampled_chains = rng.choice(unique_chains, size=len(unique_chains), replace=True)
            candidate_idx = np.concatenate([chain_to_rows[c] for c in sampled_chains])
            if len(np.unique(y1_full[candidate_idx])) >= 2:
                boot_idx = candidate_idx
                break
        if boot_idx is None:
            continue  # ligne reste a 0.0, cas extremement improbable, documente
        x_boot_std = _standardize_apply(
            x_design_full[boot_idx], final.model.scaler_mean, final.model.scaler_std
        )
        try:
            m = LogisticRegression(C=1.0, max_iter=2000).fit(x_boot_std, y1_full[boot_idx])
            coef_boot[b] = m.coef_[0]
        except ValueError:
            continue
    return coef_boot


# Assertion de reproductibilite numpy-vs-sklearn (contrat 5)


def assert_numpy_matches_sklearn(
    final: FinalArtifactResult,
    x_design_full: np.ndarray,
    *,
    n_check: int = 100,
    seed: int = 0,
    tol: float = 1e-8,
) -> None:
    """Verifie que le scoring numpy (contrat 5) reproduit la sortie sklearn native.

    Formule numpy exportee (doit correspondre EXACTEMENT a celle de U11) ::

        z = coef-(x-mean)/std + intercept
        p = interp(calibrateur, sigmoid(z))

    Raises:
        AssertionError: ecart > ``tol`` entre les deux voies de calcul.
    """
    model = final.model
    rng = np.random.default_rng(seed)
    n = x_design_full.shape[0]
    idx = rng.choice(n, size=min(n_check, n), replace=False)
    x_check = x_design_full[idx]

    z = _standardize_apply(x_check, model.scaler_mean, model.scaler_std) @ model.coef
    z = z + model.intercept
    raw_numpy = _sigmoid(z)
    p_numpy = np.interp(raw_numpy, model.calibrator.x, model.calibrator.y)

    if model.base_estimator is not None:
        x_std = _standardize_apply(x_check, model.scaler_mean, model.scaler_std)
        raw_sklearn = model.base_estimator.predict_proba(x_std)[:, 1]
    else:
        # Branche degeneree : pas d'estimateur sklearn, p_brut = p_rollout par definition.
        raw_sklearn = raw_numpy

    if not np.allclose(raw_sklearn, raw_numpy, atol=tol, rtol=0.0):
        diff = float(np.max(np.abs(raw_sklearn - raw_numpy)))
        raise AssertionError(f"Score brut numpy != sklearn (écart max {diff:.3e} > tol {tol:g}).")

    p_sklearn = model.calibrator.apply_native(raw_sklearn)
    if not np.allclose(p_sklearn, p_numpy, atol=tol, rtol=0.0):
        diff = float(np.max(np.abs(p_sklearn - p_numpy)))
        msg = f"Score calibré numpy != sklearn (écart max {diff:.3e} > tol {tol:g})."
        raise AssertionError(msg)

    print(f"  Assertion numpy vs sklearn : OK sur {len(idx)} lignes (tolérance {tol:g}).")


# Assemblage et validation de l'artefact (contrat 5)


def build_artifact(model: LinearCalibratedModel, coef_boot: np.ndarray) -> dict[str, Any]:
    """Assemble le dict JSON du contrat 5."""
    return {
        "schema_version": SCHEMA_VERSION,
        "feature_names": list(model.design_feature_names),
        "scaler_mean": [float(v) for v in model.scaler_mean],
        "scaler_std": [float(v) for v in model.scaler_std],
        "coef": [float(v) for v in model.coef],
        "intercept": float(model.intercept),
        "calibrator_x": [float(v) for v in model.calibrator.x],
        "calibrator_y": [float(v) for v in model.calibrator.y],
        "coef_boot": [[float(v) for v in row] for row in coef_boot],
    }


def validate_contract5(artifact: dict[str, Any]) -> None:
    """Auto-verification du schema exporte - echoue fort en cas d'anomalie."""
    required = {
        "schema_version",
        "feature_names",
        "scaler_mean",
        "scaler_std",
        "coef",
        "intercept",
        "calibrator_x",
        "calibrator_y",
        "coef_boot",
    }
    missing = required - artifact.keys()
    if missing:
        raise AssertionError(f"artifact.json : champs manquants {sorted(missing)}")

    n_feat = len(artifact["feature_names"])
    for key in ("scaler_mean", "scaler_std", "coef"):
        if len(artifact[key]) != n_feat:
            raise AssertionError(
                f"artifact.json : {key} de longueur {len(artifact[key])} != {n_feat} features"
            )
    if len(artifact["calibrator_x"]) != len(artifact["calibrator_y"]):
        raise AssertionError("artifact.json : calibrator_x/calibrator_y de longueurs différentes")
    if not artifact["calibrator_x"]:
        raise AssertionError("artifact.json : calibrateur vide")
    for row in artifact["coef_boot"]:
        if len(row) != n_feat:
            raise AssertionError("artifact.json : une ligne de coef_boot sans n_features colonnes")
    if any(not math.isfinite(v) for v in artifact["scaler_std"]):
        raise AssertionError("artifact.json : scaler_std contient des valeurs non finies")
    if any(v == 0 for v in artifact["scaler_std"]):
        raise AssertionError("artifact.json : scaler_std contient un zéro (division par zéro)")
    if not math.isfinite(artifact["intercept"]):
        raise AssertionError("artifact.json : intercept non fini")
    n_boot = len(artifact["coef_boot"])
    print(f"  Contrat 5 validé : {n_feat} feature(s), {n_boot} réplique(s) bootstrap.")


# Figures de fiabilite


def plot_reliability(axis_name: str, axis_result: AxisResult, out_path: Path) -> None:
    """Courbe de fiabilite (calibration_curve) des 4 modeles superposes, pour un axe."""
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Parfaitement calibré")
    for m in MODEL_NAMES:
        fm = axis_result.metrics[m]
        if fm.reliability_mean_pred:
            ax.plot(
                fm.reliability_mean_pred,
                fm.reliability_frac_pos,
                marker="o",
                label=MODEL_LABELS_FR[m],
            )
    ax.set_xlabel("Probabilité prédite moyenne (par bin)")
    ax.set_ylabel("Fraction observée de positifs")
    ax.set_title(f"Fiabilité — axe {AXIS_LABELS_FR.get(axis_name, axis_name)}")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


# Model card (Francais)


def _fmt(v: float | None, spec: str = ".4f") -> str:
    return format(v, spec) if v is not None else "n/d"


def _artifact_kind_fr(final: FinalArtifactResult) -> str:
    if final.degenerate:
        return "branche dégénérée (isotonique seule sur p_rollout)"
    return "EMOS"


def _metrics_table(results: dict[str, AxisResult]) -> str:
    lines = [
        "| Axe | Modèle | n | Brier | Skill vs climatologie | ROC-AUC | PR-AUC | "
        "Précision HA4 | Rappel HA4 (n) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for axis_name, axis_result in results.items():
        axis_label = AXIS_LABELS_FR.get(axis_name, axis_name)
        if axis_result is None:
            lines.append(f"| {axis_label} | — | axe indisponible | | | | | | |")
            continue
        for m in MODEL_NAMES:
            fm = axis_result.metrics[m]
            lines.append(
                f"| {axis_label} | {MODEL_LABELS_FR[m]} | {fm.n} | "
                f"{_fmt(fm.brier)} | {_fmt(fm.brier_skill, '.1%')} | {_fmt(fm.roc_auc, '.3f')} | "
                f"{_fmt(fm.pr_auc, '.3f')} | {_fmt(fm.ha4_precision, '.3f')} | "
                f"{_fmt(fm.ha4_recall, '.3f')} ({fm.ha4_n}) |"
            )
    return "\n".join(lines)


def _odds_ratio_table(final: FinalArtifactResult, coef_boot: np.ndarray) -> str:
    if final.degenerate:
        return (
            "Non applicable : l'artefact exporté est la branche dégénérée "
            "(calibration isotonique seule sur p_rollout, coef=[1.0] DÉFINITIONNEL, pas estimé)."
        )
    lines = ["| Feature (unité standardisée) | Odds-ratio / ET | IC80 |", "|---|---|---|"]
    lo, hi = np.percentile(coef_boot, [10, 90], axis=0)
    for j, name in enumerate(final.model.design_feature_names):
        orr = math.exp(final.model.coef[j])
        lines.append(f"| {name} | {orr:.3f} | [{math.exp(lo[j]):.3f}, {math.exp(hi[j]):.3f}] |")
    return "\n".join(lines)


def _permutation_importance_table(axis_chaines: AxisResult | None, feature_names: list[str]) -> str:
    if axis_chaines is None or axis_chaines.hgb_model_fold0 is None:
        return "Non calculée (axe « chaînes tenues » indisponible)."
    x_test = axis_chaines.hgb_test_x_fold0
    y_test = axis_chaines.hgb_test_y_fold0
    assert x_test is not None
    assert y_test is not None
    result = permutation_importance(
        axis_chaines.hgb_model_fold0,
        x_test,
        y_test,
        n_repeats=5,
        random_state=0,
        scoring="neg_brier_score",
    )
    order = np.argsort(-result.importances_mean)[:15]
    lines = [
        "| Feature | Importance (perte de Brier, moyenne ± ET) |",
        "|---|---|",
    ]
    for i in order:
        mean_i, std_i = result.importances_mean[i], result.importances_std[i]
        lines.append(f"| {feature_names[i]} | {mean_i:.4f} ± {std_i:.4f} |")
    lines.append("")
    lines.append(
        "(Calculée sur le pli 0 de l'axe « chaînes tenues », hors-échantillon "
        "d'entraînement du HGB — `scoring='neg_brier_score'`, 5 répétitions.)"
    )
    return "\n".join(lines)


def render_model_card(
    *,
    dataset_path: Path,
    n_rows: int,
    n_usable: int,
    n_chains: int,
    n_dgp: int,
    has_rollout: bool,
    indicator_cols: list[str],
    axis_results: dict[str, AxisResult | None],
    final: FinalArtifactResult,
    coef_boot: np.ndarray,
    feature_names: list[str],
    fast: bool,
    elapsed_s: float,
) -> str:
    """Assemble le model_card.md complet (Francais)."""
    rollout_note = (
        "présent (au moins une valeur non manquante)"
        if has_rollout
        else "ABSENT (colonne entièrement manquante) — EMOS dégradé vers le modèle pur-ML"
    )
    parts = [
        "# Model card — Prédicteur de risque HÉLIOS v7 (U10, EMOS)\n",
        f"Généré le {time.strftime('%Y-%m-%d %H:%M:%S')} à partir de `{dataset_path}` "
        f"({'mode --fast' if fast else 'mode complet'}, {elapsed_s:.1f} s).\n",
        "## 1. Définition des labels\n",
        "- **y1** : 1 si un événement vérité (gravité critique|défaut) touche le nœud "
        "exactement à t+1, 0 sinon, VIDE si t+1 dépasse le dernier tour observé de la "
        "chaîne (censure explicite, jamais 0 silencieux).\n"
        "- **y4** : 1 si un événement vérité touche le nœud dans (t, t+4], 0 si la "
        "fenêtre est entièrement observée sans événement, VIDE si la fenêtre dépasse "
        "le dernier tour observé sans qu'aucun événement n'y ait été trouvé.\n"
        "- L'entraînement et les 3 axes d'évaluation utilisent **y1** (lignes censurées "
        "retirées) ; **y4** sert uniquement à la comparabilité HA4 (précision/rappel au "
        "seuil de Youden appris sur y1 du même pli).\n",
        f"Dataset : {n_rows} lignes chargées, {n_usable} utilisables (y1 non censuré), "
        f"{n_chains} chaînes, {n_dgp} régimes `dgp_params_id`. Colonnes manquantes-quelque-part "
        f"(indicatrice ajoutée) : {', '.join(indicator_cols) if indicator_cols else 'aucune'}. "
        f"`p_rollout` {rollout_note}.\n",
        "## 2. Les trois axes d'évaluation\n",
        "- **Chaînes tenues** : GroupKFold par `chain_id` — généralisation à des chaînes "
        "inédites.\n"
        "- **Régime DGP tenu** : hold-out par `dgp_params_id` — généralisation à un régime de "
        "paramètres inédit (jamais vu, ni dans le train du pli, ni dans le prior).\n"
        "- **Coupure temporelle** : train `t<=12` / test `t>=13`. **Décision de conception** : "
        "le contrat 4 gelé (`build_dataset.py`) ne conserve PAS de colonne de tour brute — elle "
        "est supprimée avant écriture. Cet axe utilise donc `beta_n` (nombre de tours réellement "
        "observés pour le nœud jusqu'à t inclus) comme proxy de l'ordinal temporel : `beta_n` "
        "est strictement croissant avec t et vaut t+1 en l'absence de trou d'historique. "
        "Hypothèse documentée, à vérifier si le dataset réel présente des trous d'historique "
        "fréquents (auquel cas `beta_n` sous-estime légèrement t).\n",
        "Hyperparamètres (grille de C du ML pur, sélection L1 d'EMOS, C de calibration) réglés "
        "UNIQUEMENT sur le pli d'entraînement de chaque axe (jamais sur le pli de test).\n",
        "## 3. Comparaison des modèles (3 axes × 4 modèles)\n",
        _metrics_table(axis_results),
        "\n(Skill = 1 − Brier(modèle)/Brier(climatologie du train du pli). "
        "Seul EMOS est calibré ; les 3 challengers utilisent leur `predict_proba` natif.)\n",
        "## 4. Règle de décision (exportée)\n",
        f"{final.decision_reason}\n",
        f"**Artefact exporté** : {_artifact_kind_fr(final)} "
        f"— {len(final.model.design_feature_names)} feature(s) de design : "
        f"`{', '.join(final.model.design_feature_names)}`.\n",
        "## 5. Échelle de preuve (définition gelée, plan v7)\n",
        ECHELLE_PREUVE_T1_T4,
        "## 6. Avertissement sim2real\n",
        "Ce model card a été généré sur une **fixture synthétique** "
        "(`fixtures/make_predictor_fixture.py`) à DGP logistique connu, utilisée pour valider le "
        "pipeline (T1). Les coefficients, odds-ratios et métriques ci-dessus NE reflètent PAS la "
        "réalité opérationnelle — ils décrivent le comportement du simulateur. Avant tout usage "
        "en production, ré-entraîner sur le dataset réel produit par `build_dataset.py` (U8) sur "
        "les runs de la campagne HÉLIOS (T2/T3), et ne jamais présenter ces chiffres comme une "
        "mesure de risque réelle.\n",
        "## 7. Odds-ratios par écart-type (modèle exporté)\n",
        _odds_ratio_table(final, coef_boot),
        "\n(IC80 = 10ᵉ-90ᵉ centile de `coef_boot`, K réplicats bootstrap par ré-échantillonnage "
        "des chaînes avec remise — convention IC80 du plan v7.)\n",
        "## 8. Importance par permutation (HistGradientBoostingClassifier, challenger)\n",
        _permutation_importance_table(axis_results.get("chaines"), feature_names),
    ]
    return "\n".join(parts)


# Orchestration CLI


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset", required=True, help="CSV du dataset (contrat 4)")
    parser.add_argument("--out", required=True, help="Répertoire de sortie (sous OUT/models/v1/)")
    parser.add_argument("--fast", action="store_true", help="Grilles/plis réduits (< 1 min)")
    parser.add_argument("--seed", type=int, default=RNG_SEED, help="Graine (bootstrap, assertion)")
    args = parser.parse_args(argv)

    t0 = time.time()
    dataset_path = Path(args.dataset)
    out_dir = Path(args.out) / "models" / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Chargement du dataset : {dataset_path}")
    ds = load_dataset(dataset_path)
    n_rows = len(ds.y1)

    usable = np.isfinite(ds.y1)
    n_usable = int(usable.sum())
    n_censored = n_rows - n_usable
    print(f"  {n_rows} lignes, {n_usable} utilisables (y1 non censuré), {n_censored} retirées.")
    if n_usable < 20:
        raise SystemExit("Dataset utilisable trop petit (< 20 lignes non censurées) — abandon.")

    chain = ds.chain_id[usable]
    dgp = ds.dgp_params_id[usable]
    y1 = ds.y1[usable]
    y4 = ds.y4[usable]
    x_raw = ds.x[usable]

    indicator_mask = compute_indicator_mask(x_raw)
    indicator_cols = [ds.feature_names[i] for i in np.flatnonzero(indicator_mask)]
    print(f"  Colonnes avec valeurs manquantes (indicatrice ajoutée) : {len(indicator_cols)}.")

    p_rollout_idx = ds.feature_names.index(P_ROLLOUT_COL)
    has_rollout = bool(np.isfinite(x_raw[:, p_rollout_idx]).any())
    if not has_rollout:
        print("  p_rollout ABSENT : EMOS se dégrade vers le modèle pur-ML (L2, calibré).")
    beta_n = x_raw[:, ds.feature_names.index("beta_n")]

    # Imputation "structurelle" (indicatrices) fixee une fois pour toutes ; les MEDIANES du modele final sont apprises sur tout l'usable (le train de l'export final), celles de chaque pli d'axe sur le train de CE pli.
    final_imputer = Imputer.fit(x_raw, ds.feature_names, indicator_mask)
    x_imputed_full, feature_names_imputed = final_imputer.transform(x_raw)
    p_rollout_idx_imp = feature_names_imputed.index(P_ROLLOUT_COL)
    spread_idx_imp = feature_names_imputed.index(SPREAD_COL)

    # Evaluation des 3 axes (imputation re-apprise pli par pli dans run_axis)
    axis_folds = build_axis_folds(chain, dgp, beta_n, fast=args.fast)
    axis_results: dict[str, AxisResult | None] = {}
    for axis_name in ("chaines", "dgp", "temporel"):
        folds = axis_folds[axis_name]
        if not folds:
            print(f"Axe « {axis_name} » : indisponible (pas assez de groupes distincts).")
            axis_results[axis_name] = None
            continue
        print(f"Axe « {AXIS_LABELS_FR[axis_name]} » : {len(folds)} pli(s)...")
        axis_results[axis_name] = run_axis(
            folds,
            x_raw,
            ds.feature_names,
            feature_names_imputed,
            indicator_mask,
            y1,
            y4,
            chain,
            p_rollout_idx_imp,
            spread_idx_imp,
            has_rollout,
            args.fast,
        )
        res = axis_results[axis_name]
        if res is not None:
            for m in MODEL_NAMES:
                fm = res.metrics[m]
                skill = _fmt(fm.brier_skill, ".1%")
                print(
                    f"    {MODEL_LABELS_FR[m]:22s} Brier={fm.brier:.4f} skill={skill} "
                    f"AUC={_fmt(fm.roc_auc, '.3f')} PR-AUC={_fmt(fm.pr_auc, '.3f')}"
                )

    # Decision + ajustement final sur toutes les donnees usables
    print("Ajustement du modèle final (toutes les données usables)...")
    final = decide_and_fit_final(
        x_imputed_full,
        feature_names_imputed,
        y1,
        chain,
        p_rollout_idx_imp,
        spread_idx_imp,
        has_rollout,
        axis_results.get("chaines"),
    )
    print(f"  {final.decision_reason}")

    x_design_full = final_design_matrix(final, x_imputed_full, p_rollout_idx_imp, spread_idx_imp)

    k_boot = 10 if args.fast else 50
    print(f"Bootstrap (K={k_boot} réplicats, ré-échantillonnage des chaînes)...")
    coef_boot = bootstrap_coef(final, x_design_full, y1, chain, k=k_boot, seed=args.seed)

    print("Assertion de reproductibilité numpy vs sklearn...")
    assert_numpy_matches_sklearn(final, x_design_full, seed=args.seed)

    artifact = build_artifact(final.model, coef_boot)
    validate_contract5(artifact)

    artifact_path = out_dir / "artifact.json"
    artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Artefact écrit : {artifact_path}")

    joblib.dump(
        {
            "base_estimator": final.model.base_estimator,
            "calibrator_method": final.model.calibrator.method,
            "calibrator_model": final.model.calibrator.model_obj,
            "design_feature_names": final.model.design_feature_names,
            "imputer_feature_names": final_imputer.feature_names,
            "imputer_medians": final_imputer.medians,
            "imputer_indicator_mask": final_imputer.indicator_mask,
            "x_key_indices": final.x_key_indices,
            "decision_reason": final.decision_reason,
        },
        out_dir / "model.joblib",
    )
    print(f"model.joblib écrit : {out_dir / 'model.joblib'}")

    for axis_name, axis_result in axis_results.items():
        if axis_result is None:
            continue
        png_path = out_dir / f"reliability_{axis_name}.png"
        plot_reliability(axis_name, axis_result, png_path)
        print(f"Figure de fiabilité écrite : {png_path}")

    n_chains = len(np.unique(chain))
    n_dgp = len(np.unique(dgp))
    card = render_model_card(
        dataset_path=dataset_path,
        n_rows=n_rows,
        n_usable=n_usable,
        n_chains=n_chains,
        n_dgp=n_dgp,
        has_rollout=has_rollout,
        indicator_cols=indicator_cols,
        axis_results=axis_results,
        final=final,
        coef_boot=coef_boot,
        feature_names=feature_names_imputed,
        fast=args.fast,
        elapsed_s=time.time() - t0,
    )
    card_path = out_dir / "model_card.md"
    card_path.write_text(card, encoding="utf-8")
    print(f"Model card écrit : {card_path}")

    print(f"Terminé en {time.time() - t0:.1f} s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
