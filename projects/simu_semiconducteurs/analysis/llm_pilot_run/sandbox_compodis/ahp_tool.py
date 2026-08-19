"""AHP (Analytic Hierarchy Process, Saaty) - urgence declaree Ud  dans  [0, 1].

Le questionnaire hebdomadaire compare 4 criteres deux a deux sur l'echelle
de Saaty (1..9 et reciproques), puis note chaque critere sur [1, 9].
L'urgence declaree est la moyenne ponderee des notes, ramenee sur [0, 1].

Criteres :
    C1 - Impact operationnel
    C2 - Fenetre temporelle
    C3 - Dependances aval
    C4 - Recuperabilite
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

#: Libelles des 4 criteres AHP, dans l'ordre des indices de la matrice.
CRITERIA: list[str] = [
    "Impact opérationnel",
    "Fenêtre temporelle",
    "Dépendances aval",
    "Récupérabilité",
]

#: Indices aleatoires de coherence (Random Index) de Saaty, par taille de matrice.
_RI: dict[int, float] = {
    1: 0.0,
    2: 0.0,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
}

#: Seuil de coherence de Saaty : CR < 0.10 => jugements exploitables.
CONSISTENCY_THRESHOLD: float = 0.10


class AHPResult(NamedTuple):
    """Resultat complet d'une analyse AHP.

    Attributes:
        weights: vecteur de priorites (somme = 1).
        lambda_max: valeur propre principale approchee de la matrice.
        consistency_index: CI = (lambdamax - n) / (n - 1).
        consistency_ratio: CR = CI / RI(n).
        is_consistent: True si CR < 0.10 (seuil de Saaty).
    """

    weights: np.ndarray
    lambda_max: float
    consistency_index: float
    consistency_ratio: float
    is_consistent: bool


def build_matrix(comparisons: dict[tuple[int, int], float], n: int) -> np.ndarray:
    """Construit la matrice de comparaison reciproque nxn.

    Args:
        comparisons: jugements de Saaty par paire ; ``{(i, j): v}`` signifie
            " le critere i est v fois plus important que le critere j ".
            La reciproque ``A[j, i] = 1/v`` est posee automatiquement.
        n: taille de la matrice.

    Returns:
        Matrice reciproque positive avec diagonale unitaire.

    Raises:
        ValueError: si une valeur est <= 0, si un indice sort de [0, n-1],
            si i == j avec v != 1, ou si deux jugements (i, j) / (j, i)
            sont contradictoires.
    """
    if n < 1:
        raise ValueError(f"Taille de matrice invalide : n={n}")
    A = np.ones((n, n), dtype=float)  # noqa: N806  # convention math : A = matrice
    seen: set[tuple[int, int]] = set()
    for (i, j), v in comparisons.items():
        if not (0 <= i < n and 0 <= j < n):
            raise ValueError(f"Indice hors bornes pour n={n} : ({i}, {j})")
        if v <= 0:
            raise ValueError(f"Jugement de Saaty non positif pour ({i}, {j}) : {v}")
        if i == j:
            if not np.isclose(v, 1.0):
                raise ValueError(f"La diagonale doit valoir 1, reçu A[{i},{i}]={v}")
            continue
        if (j, i) in seen and not np.isclose(A[i, j], v, rtol=1e-6):
            raise ValueError(
                f"Jugements contradictoires pour la paire ({i}, {j}) : {v} vs réciproque {A[i, j]}"
            )
        A[i, j] = v
        A[j, i] = 1.0 / v
        seen.add((i, j))
    return A


def priority_vector(A: np.ndarray) -> np.ndarray:  # noqa: N803  # convention math : A = matrice
    """Vecteur de priorites par normalisation des colonnes puis moyenne des lignes.

    Approximation classique du vecteur propre principal : chaque colonne est
    normalisee par sa somme, puis on prend la moyenne de chaque ligne.

    Args:
        A: matrice de comparaison reciproque positive.

    Returns:
        Vecteur de poids normalise (somme = 1).
    """
    A = np.asarray(A, dtype=float)  # noqa: N806  # convention math : A = matrice
    col_sums = A.sum(axis=0)
    normalized = A / col_sums
    w = normalized.mean(axis=1)
    return w / w.sum()


def consistency_ratio(
    A: np.ndarray,  # noqa: N803  # convention math : A = matrice
    w: np.ndarray,
) -> tuple[float, float, float]:
    """Calcule (lambdamax, CI, CR) pour une matrice et son vecteur de priorites.

    CI = (lambdamax - n) / (n - 1) ; CR = CI / RI(n). Pour n <= 2 la matrice
    reciproque est toujours coherente : CR = 0.

    Args:
        A: matrice de comparaison reciproque.
        w: vecteur de priorites associe.

    Returns:
        Tuple ``(lambda_max, consistency_index, consistency_ratio)``.
    """
    A = np.asarray(A, dtype=float)  # noqa: N806  # convention math : A = matrice
    w = np.asarray(w, dtype=float)
    n = A.shape[0]
    lambda_max = float(np.mean((A @ w) / w))
    if n <= 2:
        return lambda_max, 0.0, 0.0
    ci = (lambda_max - n) / (n - 1)
    ri = _RI.get(n, _RI[10])
    cr = ci / ri
    return lambda_max, ci, cr


def run_ahp(comparisons: dict[tuple[int, int], float], n: int | None = None) -> AHPResult:
    """Execute l'analyse AHP complete sur un jeu de jugements.

    Args:
        comparisons: jugements de Saaty par paire (cf. :func:`build_matrix`).
        n: taille de la matrice ; deduite des indices si None.

    Returns:
        :class:`AHPResult` avec ``is_consistent = CR < 0.10``.

    Raises:
        ValueError: si n est None et qu'aucun jugement ne permet de le deduire.
    """
    if n is None:
        if not comparisons:
            raise ValueError("Impossible de déduire n : aucun jugement fourni")
        n = max(max(i, j) for i, j in comparisons) + 1
    A = build_matrix(comparisons, n)  # noqa: N806  # convention math : A = matrice
    w = priority_vector(A)
    lambda_max, ci, cr = consistency_ratio(A, w)
    return AHPResult(
        weights=w,
        lambda_max=lambda_max,
        consistency_index=ci,
        consistency_ratio=cr,
        is_consistent=cr < CONSISTENCY_THRESHOLD,
    )


def compute_ud(weights: np.ndarray, scores: np.ndarray) -> float:
    """Urgence declaree Ud  dans  [0, 1] a partir des poids AHP et des notes [1, 9].

    Ud = (Sigma wj-sj - 1) / 8 : la moyenne ponderee des notes (qui vit dans
    [1, 9]) est ramenee lineairement sur [0, 1].

    Args:
        weights: poids AHP (renormalises defensivement a somme 1).
        scores: notes par critere sur l'echelle de Saaty [1, 9].

    Returns:
        Ud dans [0, 1].

    Raises:
        ValueError: si les longueurs different ou si une note sort de [1, 9].
    """
    w = np.asarray(weights, dtype=float)
    s = np.asarray(scores, dtype=float)
    if w.shape != s.shape:
        raise ValueError(f"Dimensions incompatibles : weights {w.shape} vs scores {s.shape}")
    if np.any(s < 1.0) or np.any(s > 9.0):
        raise ValueError(f"Les notes doivent être dans [1, 9], reçu {s.tolist()}")
    w = w / w.sum()
    ud = (float(w @ s) - 1.0) / 8.0
    return float(np.clip(ud, 0.0, 1.0))


def bipolar_to_saaty(v: int) -> float:
    """Convertit une valeur d'echelle bipolaire UI v  dans  {-8..+8} en jugement Saaty.

    - v = 0  -> 1.0 (importance egale) ;
    - v > 0  -> 1 + v (A plus important que B) ;
    - v < 0  -> 1 / (1 + |v|) (B plus important que A).

    Args:
        v: position du curseur bipolaire, entier dans [-8, +8].

    Returns:
        Jugement de Saaty dans [1/9, 9].

    Raises:
        ValueError: si v sort de [-8, +8].
    """
    if not -8 <= v <= 8:
        raise ValueError(f"Valeur bipolaire hors de [-8, +8] : {v}")
    if v >= 0:
        return 1.0 + v
    return 1.0 / (1.0 + abs(v))


def score_6_to_9(v: float) -> float:
    """Mappe une note UI sur [1, 6] vers l'echelle de Saaty [1, 9] lineairement.

    1 -> 1, 6 -> 9 : s = 1 + (v - 1) - 8/5.

    Args:
        v: note UI dans [1, 6].

    Returns:
        Note equivalente sur [1, 9].

    Raises:
        ValueError: si v sort de [1, 6].
    """
    if not 1.0 <= v <= 6.0:
        raise ValueError(f"Note UI hors de [1, 6] : {v}")
    return 1.0 + (v - 1.0) * 8.0 / 5.0


def ud_smoothed(prev: float | None, current: float, rho: float = 0.3) -> float:
    """Lissage exponentiel de Ud entre deux questionnaires successifs.

    Ud_t = rho-Ud_{t-1} + (1-rho)-Ud_courant. Amortit les variations brusques
    de perception d'une semaine sur l'autre.

    Args:
        prev: Ud precedent, ou None s'il s'agit du premier questionnaire.
        current: Ud calcule pour le questionnaire courant.
        rho: inertie du lissage, dans [0, 1] (0 = aucun lissage).

    Returns:
        Ud lisse ; ``current`` tel quel si ``prev`` est None.

    Raises:
        ValueError: si rho sort de [0, 1].
    """
    if not 0.0 <= rho <= 1.0:
        raise ValueError(f"rho doit être dans [0, 1], reçu {rho}")
    if prev is None:
        return current
    return rho * prev + (1.0 - rho) * current
