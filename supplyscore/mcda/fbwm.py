"""FBWM — Fuzzy Best-Worst Method (Guo & Zhao 2017) : pondération de critères.

Méthode de pondération multicritère à nombres flous triangulaires (NFT)
exigeant seulement 2n−3 comparaisons (contre n(n−1)/2 pour l'AHP) : le
décideur désigne le Meilleur critère B et le Pire critère W, puis juge
« B contre chaque autre » (vecteur Best-to-Others a_Bj) et « chaque autre
contre W » (vecteur Others-to-Worst a_jW) sur une échelle linguistique.

Modèle d'optimisation (variables (l_j, m_j, u_j) pour chaque critère, plus ξ) :

    min ξ
    s.c.  |w_B / w_j − a_Bj| ≤ (ξ, ξ, ξ)   pour j != B   (composantes l, m, u)
          |w_j / w_W − a_jW| ≤ (ξ, ξ, ξ)   pour j != W
          Σ_j R(w_j) = 1                    (défuzzification GMIR)
          0 < eps ≤ l_j ≤ m_j ≤ u_j

avec la division floue approchée (l1, m1, u1) / (l2, m2, u2) =
(l1/u2, m1/m2, u1/l2) et la défuzzification GMIR (Graded Mean Integration
Representation) R(l, m, u) = (l + 4m + u) / 6.

Résolution par ``scipy.optimize.minimize(method="SLSQP")`` en multi-départs
seedés (5 points initiaux tirés de ``numpy.random.default_rng(graine)``) :
reproductible à graine égale. Si AUCUN départ ne fournit de solution faisable,
repli silencieux sur des poids uniformes (jamais d'exception pour cause
numérique).

Périmètre SupplyScore : pondérer les blocs KPI d'Ur (l'AHP reste sur le
questionnaire Ud à 4 critères — cf. PLAN.md, E12).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import optimize  # type: ignore[import-untyped]  # scipy ne fournit pas de stubs

#: Nombre flou triangulaire (l, m, u), avec l ≤ m ≤ u.
NFT = tuple[float, float, float]

#: Échelle linguistique de Guo & Zhao (2017) : jugement → NFT (l, m, u).
ECHELLE_LINGUISTIQUE: dict[str, tuple[float, float, float]] = {
    "egalement_important": (1, 1, 1),
    "faiblement_plus_important": (2 / 3, 1, 3 / 2),
    "assez_plus_important": (3 / 2, 2, 5 / 2),
    "tres_plus_important": (5 / 2, 3, 7 / 2),
    "absolument_plus_important": (7 / 2, 4, 9 / 2),
}

#: Indice de cohérence (CI) par jugement a_BW (Guo & Zhao 2017).
TABLE_CI: dict[str, float] = {
    "egalement_important": 3.00,
    "faiblement_plus_important": 3.80,
    "assez_plus_important": 5.29,
    "tres_plus_important": 6.69,
    "absolument_plus_important": 8.04,
}

#: Seuil d'acceptation du ratio de cohérence : CR < 0.10 => jugements exploitables.
SEUIL_CR: float = 0.10

#: Borne inférieure stricte des composantes floues (0 < eps ≤ l_j ≤ m_j ≤ u_j).
_EPS: float = 1e-4

#: Borne supérieure des composantes : R(w_j) ≤ 1 et GMIR => u_j ≤ 6.
_BORNE_SUP: float = 6.0

#: Nombre de points initiaux du multi-départs SLSQP.
_NB_DEPARTS: int = 5

#: Tolérance de faisabilité a posteriori sur les contraintes du modèle.
_TOL_FAISABILITE: float = 1e-6


@dataclass(frozen=True)
class ResultatFBWM:
    """Résultat complet d'une résolution FBWM.

    Attributes:
        poids: poids défuzzifiés GMIR ``R(w) = (l + 4m + u) / 6`` puis
            renormalisés (somme = 1), par critère.
        poids_flous: poids flous triangulaires ``(l, m, u)`` par critère.
        xi_star: consistance optimale ξ* (inf si aucun départ n'a convergé).
        cr: ratio de cohérence ξ*/CI, où CI est l'indice du jugement
            linguistique LE PLUS FORT utilisé (cf. :func:`resoudre_fbwm`).
        coherent: True si ``cr < SEUIL_CR``.
        converge: True si SLSQP a convergé sur au moins un départ ;
            False => ``poids`` est le repli uniforme 1/n.
    """

    poids: dict[str, float]
    poids_flous: dict[str, tuple[float, float, float]]
    xi_star: float
    cr: float
    coherent: bool
    converge: bool


def _gmir(nft: tuple[float, float, float]) -> float:
    """Défuzzification GMIR d'un NFT : R(l, m, u) = (l + 4m + u) / 6."""
    bas, modal, haut = nft
    return (bas + 4.0 * modal + haut) / 6.0


def _point_initial(rng: np.random.Generator, n: int) -> np.ndarray:
    """Point de départ aléatoire : poids modaux normalisés, étalement borné.

    Args:
        rng: générateur seedé (reproductibilité du multi-départs).
        n: nombre de critères.

    Returns:
        Vecteur ``[l_0, m_0, u_0, ..., l_{n-1}, m_{n-1}, u_{n-1}, ξ]``.
    """
    modaux = rng.uniform(0.5, 1.5, size=n)
    modaux /= modaux.sum()
    etalement = float(rng.uniform(0.0, 0.25))
    x0 = np.empty(3 * n + 1)
    for k in range(n):
        x0[3 * k] = max(modaux[k] * (1.0 - etalement), _EPS)
        x0[3 * k + 1] = modaux[k]
        x0[3 * k + 2] = modaux[k] * (1.0 + etalement)
    x0[-1] = float(rng.uniform(0.2, 1.0))
    return x0


def _repli_uniforme(criteres: list[str]) -> ResultatFBWM:
    """Repli défensif : poids uniformes 1/n (flous dégénérés crisp).

    Utilisé quand aucun départ SLSQP ne fournit de solution faisable — la
    pondération reste exploitable par l'appelant, jamais d'exception.
    """
    unif = 1.0 / len(criteres)
    return ResultatFBWM(
        poids={c: unif for c in criteres},
        poids_flous={c: (unif, unif, unif) for c in criteres},
        xi_star=math.inf,
        cr=math.inf,
        coherent=False,
        converge=False,
    )


def _resoudre(
    criteres: list[str],
    best: str,
    worst: str,
    a_b: dict[str, NFT],
    a_w: dict[str, NFT],
    graine: int = 0,
    ci: float | None = None,
) -> ResultatFBWM:
    """Résout le programme FBWM sur des jugements DÉJÀ exprimés en NFT.

    Surcharge interne testable avec des NFT arbitraires (notamment crisp,
    l = m = u, pour retrouver les solutions analytiques du BWM classique).
    Aucune validation linguistique n'est faite ici — c'est le rôle de
    :func:`resoudre_fbwm`.

    Les auto-comparaisons éventuelles (``a_b[best]``, ``a_w[worst]``,
    nécessairement (1, 1, 1)) sont ignorées ; le jugement a_BW peut figurer
    dans les deux vecteurs (contrainte dupliquée, sans effet sur l'optimum).

    Args:
        criteres: noms des critères (l'ordre fixe la position des variables).
        best: critère Meilleur B.
        worst: critère Pire W.
        a_b: NFT Best-to-Others ``a_Bj`` par critère j (j != best).
        a_w: NFT Others-to-Worst ``a_jW`` par critère j (j != worst).
        graine: graine du multi-départs (reproductible à graine égale).
        ci: indice de cohérence utilisé pour ``cr = ξ*/ci`` ; None => le CI
            le plus permissif de :data:`TABLE_CI` (les appels publics passent
            toujours le CI du jugement saisi le plus fort).

    Returns:
        :class:`ResultatFBWM` ; repli uniforme (``converge=False``) si aucun
        départ SLSQP n'aboutit — jamais d'exception pour cause numérique.
    """
    n = len(criteres)
    idx = {c: k for k, c in enumerate(criteres)}
    i_best = idx[best]
    i_worst = idx[worst]
    if ci is None:
        ci = max(TABLE_CI.values())

    # Paires de contraintes (i, j, nft) : ratio flou w_i / w_j comparé au NFT.
    # Itération dans l'ordre de `criteres` (et non des dicts) : la géométrie du
    # problème ne dépend que des positions => renommer les critères ne change
    # pas un seul bit du calcul.
    paires: list[tuple[int, int, NFT]] = []
    for c in criteres:
        if c in a_b and c != best:
            paires.append((i_best, idx[c], a_b[c]))
    for c in criteres:
        if c in a_w and c != worst:
            paires.append((idx[c], i_worst, a_w[c]))

    def _objectif(x: np.ndarray) -> float:
        """Objectif : la consistance ξ (dernière variable)."""
        return float(x[-1])

    def _residus_ineg(x: np.ndarray) -> np.ndarray:
        """Résidus des inégalités (>= 0 attendu) : écarts aux NFT et ordre l ≤ m ≤ u."""
        xi = x[-1]
        residus: list[float] = []
        for i, j, (bas_a, mod_a, haut_a) in paires:
            li, mi, ui = x[3 * i], x[3 * i + 1], x[3 * i + 2]
            lj, mj, uj = x[3 * j], x[3 * j + 1], x[3 * j + 2]
            for ecart in (li / uj - bas_a, mi / mj - mod_a, ui / lj - haut_a):
                residus.append(xi - ecart)
                residus.append(xi + ecart)
        for k in range(n):
            residus.append(x[3 * k + 1] - x[3 * k])
            residus.append(x[3 * k + 2] - x[3 * k + 1])
        return np.asarray(residus)

    def _residu_eq(x: np.ndarray) -> float:
        """Résidu de l'égalité GMIR : Σ_j R(w_j) − 1 (= 0 attendu)."""
        somme = sum((x[3 * k] + 4.0 * x[3 * k + 1] + x[3 * k + 2]) / 6.0 for k in range(n))
        return float(somme - 1.0)

    def _faisable(x: np.ndarray) -> bool:
        """Vérifie a posteriori la faisabilité de la solution candidate."""
        return bool(np.all(_residus_ineg(x) >= -_TOL_FAISABILITE)) and (
            abs(_residu_eq(x)) <= _TOL_FAISABILITE
        )

    bornes: list[tuple[float, float | None]] = [(_EPS, _BORNE_SUP)] * (3 * n)
    bornes.append((0.0, None))
    contraintes = [
        {"type": "ineq", "fun": _residus_ineg},
        {"type": "eq", "fun": _residu_eq},
    ]

    rng = np.random.default_rng(graine)
    meilleur_x: np.ndarray | None = None
    for _ in range(_NB_DEPARTS):
        x0 = _point_initial(rng, n)
        try:
            res = optimize.minimize(
                _objectif,
                x0,
                method="SLSQP",
                bounds=bornes,
                constraints=contraintes,
                options={"maxiter": 400, "ftol": 1e-10},
            )
        except Exception:
            # Protection numérique : un départ qui explose est simplement ignoré.
            continue
        if not res.success:
            continue
        x_cand = np.asarray(res.x, dtype=float)
        if not _faisable(x_cand):
            continue
        if meilleur_x is None or x_cand[-1] < meilleur_x[-1]:
            meilleur_x = x_cand

    if meilleur_x is None:
        return _repli_uniforme(criteres)

    poids_flous: dict[str, tuple[float, float, float]] = {
        c: (
            float(meilleur_x[3 * k]),
            float(meilleur_x[3 * k + 1]),
            float(meilleur_x[3 * k + 2]),
        )
        for k, c in enumerate(criteres)
    }
    bruts = {c: _gmir(nft) for c, nft in poids_flous.items()}
    total = sum(bruts.values())
    poids = {c: v / total for c, v in bruts.items()}
    xi_star = float(meilleur_x[-1])
    cr = xi_star / ci
    return ResultatFBWM(
        poids=poids,
        poids_flous=poids_flous,
        xi_star=xi_star,
        cr=cr,
        coherent=cr < SEUIL_CR,
        converge=True,
    )


def resoudre_fbwm(
    criteres: list[str],
    best: str,
    worst: str,
    best_vers_autres: dict[str, str],
    autres_vers_worst: dict[str, str],
    graine: int = 0,
) -> ResultatFBWM:
    """Résout le FBWM à partir de jugements linguistiques (Guo & Zhao 2017).

    Conventions documentées :

    * **Jugement a_BW** (Meilleur contre Pire) : il peut être fourni dans
      ``best_vers_autres[worst]``, dans ``autres_vers_worst[best]``, ou dans
      les deux (auquel cas ils doivent être identiques). L'absence des deux
      côtés est une erreur — c'est le seul jugement dont l'absence d'UN côté
      est tolérée, car les deux entrées décrivent la même comparaison.
    * **Ratio de cohérence** : ``cr = ξ*/CI`` où CI est l'indice de
      :data:`TABLE_CI` du jugement LE PLUS FORT parmi tous les a_Bj et a_jW
      saisis. Pour des entrées cohérentes ce jugement est a_BW lui-même
      (a_BW majore les autres) ; prendre le maximum garde un CR défini et
      prudent même quand la saisie viole cette dominance.
    * **Échec numérique** : si aucun des 5 départs SLSQP ne converge, le
      résultat porte ``converge=False``, des poids uniformes 1/n,
      ``xi_star=inf``, ``cr=inf``, ``coherent=False`` — jamais d'exception
      pour cause numérique. Même graine => même résultat, bit à bit.

    Args:
        criteres: noms des critères (n >= 2, uniques).
        best: critère Meilleur B (doit appartenir à ``criteres``).
        worst: critère Pire W (doit appartenir à ``criteres``, != best).
        best_vers_autres: jugement linguistique ``a_Bj`` pour chaque j != best
            (clés de :data:`ECHELLE_LINGUISTIQUE`).
        autres_vers_worst: jugement linguistique ``a_jW`` pour chaque
            j != worst (clés de :data:`ECHELLE_LINGUISTIQUE`).
        graine: graine du multi-départs SLSQP (reproductibilité).

    Returns:
        :class:`ResultatFBWM` complet (poids défuzzifiés à somme 1).

    Raises:
        ValueError: si n < 2, critères en double, best/worst hors liste ou
            identiques, clé inattendue, jugement linguistique inconnu,
            couverture incomplète, ou jugements a_BW contradictoires.
    """
    n = len(criteres)
    if n < 2:
        raise ValueError(f"Au moins 2 critères sont requis pour le FBWM (reçu {n}).")
    if len(set(criteres)) != n:
        doublons = sorted({c for c in criteres if criteres.count(c) > 1})
        raise ValueError(f"Les critères doivent être uniques ; doublons : {doublons}.")
    if best not in criteres:
        raise ValueError(f"Le critère Meilleur « {best} » ne fait pas partie des critères.")
    if worst not in criteres:
        raise ValueError(f"Le critère Pire « {worst} » ne fait pas partie des critères.")
    if best == worst:
        raise ValueError(
            f"Le Meilleur et le Pire doivent être deux critères distincts (reçu « {best} »)."
        )

    ensemble = set(criteres)
    for j in best_vers_autres:
        if j not in ensemble or j == best:
            raise ValueError(
                f"Clé inattendue dans best_vers_autres : « {j} » "
                "(attendu : les critères autres que le Meilleur)."
            )
    for j in autres_vers_worst:
        if j not in ensemble or j == worst:
            raise ValueError(
                f"Clé inattendue dans autres_vers_worst : « {j} » "
                "(attendu : les critères autres que le Pire)."
            )
    for jugement in (*best_vers_autres.values(), *autres_vers_worst.values()):
        if jugement not in ECHELLE_LINGUISTIQUE:
            raise ValueError(
                f"Jugement linguistique inconnu : « {jugement} ». "
                f"Jugements valides : {sorted(ECHELLE_LINGUISTIQUE)}."
            )

    # Jugement a_BW : même comparaison vue des deux côtés — un seul côté suffit.
    j_bw_cote_best = best_vers_autres.get(worst)
    j_bw_cote_worst = autres_vers_worst.get(best)
    if j_bw_cote_best is None and j_bw_cote_worst is None:
        raise ValueError(
            "Le jugement a_BW (Meilleur contre Pire) doit être fourni dans "
            "best_vers_autres[worst] ou autres_vers_worst[best]."
        )
    if (
        j_bw_cote_best is not None
        and j_bw_cote_worst is not None
        and j_bw_cote_best != j_bw_cote_worst
    ):
        raise ValueError(
            f"Jugements a_BW contradictoires : best_vers_autres[« {worst} »] = "
            f"« {j_bw_cote_best} » mais autres_vers_worst[« {best} »] = "
            f"« {j_bw_cote_worst} »."
        )
    a_bw = j_bw_cote_best if j_bw_cote_best is not None else j_bw_cote_worst
    assert a_bw is not None  # garanti par les deux contrôles ci-dessus

    for j in criteres:
        if j not in (best, worst) and j not in best_vers_autres:
            raise ValueError(f"Jugement Meilleur → « {j} » manquant dans best_vers_autres.")
        if j not in (best, worst) and j not in autres_vers_worst:
            raise ValueError(f"Jugement « {j} » → Pire manquant dans autres_vers_worst.")

    a_b: dict[str, NFT] = {j: ECHELLE_LINGUISTIQUE[v] for j, v in best_vers_autres.items()}
    a_b[worst] = ECHELLE_LINGUISTIQUE[a_bw]
    a_w: dict[str, NFT] = {j: ECHELLE_LINGUISTIQUE[v] for j, v in autres_vers_worst.items()}
    a_w[best] = ECHELLE_LINGUISTIQUE[a_bw]

    # CI du jugement le plus fort saisi (= a_BW pour une saisie cohérente).
    jugements_saisis = {*best_vers_autres.values(), *autres_vers_worst.values(), a_bw}
    ci = max(TABLE_CI[j] for j in jugements_saisis)

    return _resoudre(criteres, best, worst, a_b, a_w, graine=graine, ci=ci)
