"""FBWM - Fuzzy Best-Worst Method (Guo & Zhao 2017) : ponderation de criteres.

Methode de ponderation multicritere a nombres flous triangulaires (NFT)
exigeant seulement 2n-3 comparaisons (contre n(n-1)/2 pour l'AHP) : le
decideur designe le Meilleur critere B et le Pire critere W, puis juge
" B contre chaque autre " (vecteur Best-to-Others a_Bj) et " chaque autre
contre W " (vecteur Others-to-Worst a_jW) sur une echelle linguistique.

Modele d'optimisation (variables (l_j, m_j, u_j) pour chaque critere, plus xi) :

    min xi
    s.c.  |w_B / w_j - a_Bj| <= (xi, xi, xi)   pour j != B   (composantes l, m, u)
          |w_j / w_W - a_jW| <= (xi, xi, xi)   pour j != W
          Sigma_j R(w_j) = 1                    (defuzzification GMIR)
          0 < eps <= l_j <= m_j <= u_j

avec la division floue approchee (l1, m1, u1) / (l2, m2, u2) =
(l1/u2, m1/m2, u1/l2) et la defuzzification GMIR (Graded Mean Integration
Representation) R(l, m, u) = (l + 4m + u) / 6.

Resolution par ``scipy.optimize.minimize(method="SLSQP")`` en multi-departs
seedes (5 points initiaux tires de ``numpy.random.default_rng(graine)``) :
reproductible a graine egale. Si AUCUN depart ne fournit de solution faisable,
repli silencieux sur des poids uniformes (jamais d'exception pour cause
numerique).

Perimetre SupplyScore : ponderer les blocs KPI d'Ur (l'AHP reste sur le
questionnaire Ud a 4 criteres - cf. PLAN.md, E12).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import optimize  # type: ignore[import-untyped]  # scipy ne fournit pas de stubs

#: Nombre flou triangulaire (l, m, u), avec l <= m <= u.
NFT = tuple[float, float, float]

#: Echelle linguistique de Guo & Zhao (2017) : jugement -> NFT (l, m, u).
ECHELLE_LINGUISTIQUE: dict[str, tuple[float, float, float]] = {
    "egalement_important": (1, 1, 1),
    "faiblement_plus_important": (2 / 3, 1, 3 / 2),
    "assez_plus_important": (3 / 2, 2, 5 / 2),
    "tres_plus_important": (5 / 2, 3, 7 / 2),
    "absolument_plus_important": (7 / 2, 4, 9 / 2),
}

#: Indice de coherence (CI) par jugement a_BW (Guo & Zhao 2017).
TABLE_CI: dict[str, float] = {
    "egalement_important": 3.00,
    "faiblement_plus_important": 3.80,
    "assez_plus_important": 5.29,
    "tres_plus_important": 6.69,
    "absolument_plus_important": 8.04,
}

#: Seuil d'acceptation du ratio de coherence : CR < 0.10 => jugements exploitables.
SEUIL_CR: float = 0.10

#: Borne inferieure stricte des composantes floues (0 < eps <= l_j <= m_j <= u_j).
_EPS: float = 1e-4

#: Borne superieure des composantes : R(w_j) <= 1 et GMIR => u_j <= 6.
_BORNE_SUP: float = 6.0

#: Nombre de points initiaux du multi-departs SLSQP.
_NB_DEPARTS: int = 5

#: Tolerance de faisabilite a posteriori sur les contraintes du modele.
_TOL_FAISABILITE: float = 1e-6


@dataclass(frozen=True)
class ResultatFBWM:
    """Resultat complet d'une resolution FBWM.

    Attributes:
        poids: poids defuzzifies GMIR ``R(w) = (l + 4m + u) / 6`` puis
            renormalises (somme = 1), par critere.
        poids_flous: poids flous triangulaires ``(l, m, u)`` par critere.
        xi_star: consistance optimale xi* (inf si aucun depart n'a converge).
        cr: ratio de coherence xi*/CI, ou CI est l'indice du jugement
            linguistique LE PLUS FORT utilise (cf. :func:`resoudre_fbwm`).
        coherent: True si ``cr < SEUIL_CR``.
        converge: True si SLSQP a converge sur au moins un depart ;
            False => ``poids`` est le repli uniforme 1/n.
    """

    poids: dict[str, float]
    poids_flous: dict[str, tuple[float, float, float]]
    xi_star: float
    cr: float
    coherent: bool
    converge: bool


def _gmir(nft: tuple[float, float, float]) -> float:
    """Defuzzification GMIR d'un NFT : R(l, m, u) = (l + 4m + u) / 6."""
    bas, modal, haut = nft
    return (bas + 4.0 * modal + haut) / 6.0


def _point_initial(rng: np.random.Generator, n: int) -> np.ndarray:
    """Point de depart aleatoire : poids modaux normalises, etalement borne.

    Args:
        rng: generateur seede (reproductibilite du multi-departs).
        n: nombre de criteres.

    Returns:
        Vecteur ``[l_0, m_0, u_0, ..., l_{n-1}, m_{n-1}, u_{n-1}, xi]``.
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
    """Repli defensif : poids uniformes 1/n (flous degeneres crisp).

    Utilise quand aucun depart SLSQP ne fournit de solution faisable - la
    ponderation reste exploitable par l'appelant, jamais d'exception.
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
    """Resout le programme FBWM sur des jugements DEJA exprimes en NFT.

    Surcharge interne testable avec des NFT arbitraires (notamment crisp,
    l = m = u, pour retrouver les solutions analytiques du BWM classique).
    Aucune validation linguistique n'est faite ici - c'est le role de
    :func:`resoudre_fbwm`.

    Les auto-comparaisons eventuelles (``a_b[best]``, ``a_w[worst]``,
    necessairement (1, 1, 1)) sont ignorees ; le jugement a_BW peut figurer
    dans les deux vecteurs (contrainte dupliquee, sans effet sur l'optimum).

    Args:
        criteres: noms des criteres (l'ordre fixe la position des variables).
        best: critere Meilleur B.
        worst: critere Pire W.
        a_b: NFT Best-to-Others ``a_Bj`` par critere j (j != best).
        a_w: NFT Others-to-Worst ``a_jW`` par critere j (j != worst).
        graine: graine du multi-departs (reproductible a graine egale).
        ci: indice de coherence utilise pour ``cr = xi*/ci`` ; None => le CI
            le plus permissif de :data:`TABLE_CI` (les appels publics passent
            toujours le CI du jugement saisi le plus fort).

    Returns:
        :class:`ResultatFBWM` ; repli uniforme (``converge=False``) si aucun
        depart SLSQP n'aboutit - jamais d'exception pour cause numerique.
    """
    n = len(criteres)
    idx = {c: k for k, c in enumerate(criteres)}
    i_best = idx[best]
    i_worst = idx[worst]
    if ci is None:
        ci = max(TABLE_CI.values())

    # Paires de contraintes (i, j, nft) : ratio flou w_i / w_j compare au NFT. Iteration dans l'ordre de `criteres` (et non des dicts) : la geometrie du probleme ne depend que des positions => renommer les criteres ne change pas un seul bit du calcul.
    paires: list[tuple[int, int, NFT]] = []
    for c in criteres:
        if c in a_b and c != best:
            paires.append((i_best, idx[c], a_b[c]))
    for c in criteres:
        if c in a_w and c != worst:
            paires.append((idx[c], i_worst, a_w[c]))

    def _objectif(x: np.ndarray) -> float:
        """Objectif : la consistance xi (derniere variable)."""
        return float(x[-1])

    def _residus_ineg(x: np.ndarray) -> np.ndarray:
        """Residus des inegalites (>= 0 attendu) : ecarts aux NFT et ordre l <= m <= u."""
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
        """Residu de l'egalite GMIR : Sigma_j R(w_j) - 1 (= 0 attendu)."""
        somme = sum((x[3 * k] + 4.0 * x[3 * k + 1] + x[3 * k + 2]) / 6.0 for k in range(n))
        return float(somme - 1.0)

    def _faisable(x: np.ndarray) -> bool:
        """Verifie a posteriori la faisabilite de la solution candidate."""
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
            # Protection numerique : un depart qui explose est simplement ignore.
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
    """Resout le FBWM a partir de jugements linguistiques (Guo & Zhao 2017).

    Conventions documentees :

    * **Jugement a_BW** (Meilleur contre Pire) : il peut etre fourni dans
      ``best_vers_autres[worst]``, dans ``autres_vers_worst[best]``, ou dans
      les deux (auquel cas ils doivent etre identiques). L'absence des deux
      cotes est une erreur - c'est le seul jugement dont l'absence d'UN cote
      est toleree, car les deux entrees decrivent la meme comparaison.
    * **Ratio de coherence** : ``cr = xi*/CI`` ou CI est l'indice de
      :data:`TABLE_CI` du jugement LE PLUS FORT parmi tous les a_Bj et a_jW
      saisis. Pour des entrees coherentes ce jugement est a_BW lui-meme
      (a_BW majore les autres) ; prendre le maximum garde un CR defini et
      prudent meme quand la saisie viole cette dominance.
    * **Echec numerique** : si aucun des 5 departs SLSQP ne converge, le
      resultat porte ``converge=False``, des poids uniformes 1/n,
      ``xi_star=inf``, ``cr=inf``, ``coherent=False`` - jamais d'exception
      pour cause numerique. Meme graine => meme resultat, bit a bit.

    Args:
        criteres: noms des criteres (n >= 2, uniques).
        best: critere Meilleur B (doit appartenir a ``criteres``).
        worst: critere Pire W (doit appartenir a ``criteres``, != best).
        best_vers_autres: jugement linguistique ``a_Bj`` pour chaque j != best
            (cles de :data:`ECHELLE_LINGUISTIQUE`).
        autres_vers_worst: jugement linguistique ``a_jW`` pour chaque
            j != worst (cles de :data:`ECHELLE_LINGUISTIQUE`).
        graine: graine du multi-departs SLSQP (reproductibilite).

    Returns:
        :class:`ResultatFBWM` complet (poids defuzzifies a somme 1).

    Raises:
        ValueError: si n < 2, criteres en double, best/worst hors liste ou
            identiques, cle inattendue, jugement linguistique inconnu,
            couverture incomplete, ou jugements a_BW contradictoires.
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

    # Jugement a_BW : meme comparaison vue des deux cotes - un seul cote suffit.
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
    assert a_bw is not None  # garanti par les deux controles ci-dessus

    for j in criteres:
        if j not in (best, worst) and j not in best_vers_autres:
            raise ValueError(f"Jugement Meilleur → « {j} » manquant dans best_vers_autres.")
        if j not in (best, worst) and j not in autres_vers_worst:
            raise ValueError(f"Jugement « {j} » → Pire manquant dans autres_vers_worst.")

    a_b: dict[str, NFT] = {j: ECHELLE_LINGUISTIQUE[v] for j, v in best_vers_autres.items()}
    a_b[worst] = ECHELLE_LINGUISTIQUE[a_bw]
    a_w: dict[str, NFT] = {j: ECHELLE_LINGUISTIQUE[v] for j, v in autres_vers_worst.items()}
    a_w[best] = ECHELLE_LINGUISTIQUE[a_bw]

    # CI du jugement le plus fort saisi (= a_BW pour une saisie coherente).
    jugements_saisis = {*best_vers_autres.values(), *autres_vers_worst.values(), a_bw}
    ci = max(TABLE_CI[j] for j in jugements_saisis)

    return _resoudre(criteres, best, worst, a_b, a_w, graine=graine, ci=ci)
