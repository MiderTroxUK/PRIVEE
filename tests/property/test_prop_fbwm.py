"""Propriétés du solveur FBWM — phase E12, Lot 12.2.

Profil Hypothesis LIGHT : le solveur SLSQP multi-départs est coûteux,
chaque propriété est plafonnée à 25 exemples et sans deadline.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from supplyscore.mcda.fbwm import ECHELLE_LINGUISTIQUE, resoudre_fbwm

#: Jugements linguistiques valides, ordre stable pour la reproductibilité.
_JUGEMENTS: list[str] = sorted(ECHELLE_LINGUISTIQUE)

_LIGHT = settings(max_examples=25, deadline=None)


@st.composite
def _configs_valides(draw):
    """Configuration FBWM aléatoire valide : 3..5 critères, best != worst."""
    n = draw(st.integers(min_value=3, max_value=5))
    criteres = [f"c{k}" for k in range(n)]
    i_best = draw(st.integers(min_value=0, max_value=n - 1))
    decalage = draw(st.integers(min_value=1, max_value=n - 1))
    best = criteres[i_best]
    worst = criteres[(i_best + decalage) % n]
    a_bw = draw(st.sampled_from(_JUGEMENTS))
    bva = {j: draw(st.sampled_from(_JUGEMENTS)) for j in criteres if j != best and j != worst}
    bva[worst] = a_bw
    avw = {j: draw(st.sampled_from(_JUGEMENTS)) for j in criteres if j != worst and j != best}
    avw[best] = a_bw
    return criteres, best, worst, bva, avw


@st.composite
def _configs_avec_renommage(draw):
    """Configuration valide + permutation des noms des critères « autres »."""
    criteres, best, worst, bva, avw = draw(_configs_valides())
    autres = [c for c in criteres if c not in (best, worst)]
    permutes = draw(st.permutations(autres))
    return criteres, best, worst, bva, avw, dict(zip(autres, permutes, strict=True))


class TestProprietesPoids:
    @_LIGHT
    @given(config=_configs_valides())
    def test_somme_unite_et_positivite(self, config):
        """Σ poids = 1 (1e-6) et poids strictement positifs, repli compris."""
        criteres, best, worst, bva, avw = config
        res = resoudre_fbwm(criteres, best, worst, bva, avw, graine=0)
        assert sum(res.poids.values()) == pytest.approx(1.0, abs=1e-6)
        assert all(p > 0.0 for p in res.poids.values())
        assert set(res.poids) == set(criteres)


class TestInvarianceRenommage:
    @_LIGHT
    @given(config=_configs_avec_renommage())
    def test_renommer_les_autres_fait_suivre_les_poids(self, config):
        """Permuter les noms des critères « autres » permute les poids bit à bit."""
        criteres, best, worst, bva, avw, renom = config
        complet = {**renom, best: best, worst: worst}
        criteres_2 = [complet[c] for c in criteres]
        bva_2 = {complet[j]: v for j, v in bva.items()}
        avw_2 = {complet[j]: v for j, v in avw.items()}
        r1 = resoudre_fbwm(criteres, best, worst, bva, avw, graine=7)
        r2 = resoudre_fbwm(criteres_2, best, worst, bva_2, avw_2, graine=7)
        assert r2.xi_star == r1.xi_star
        assert r2.converge == r1.converge
        for j in criteres:
            assert r2.poids[complet[j]] == r1.poids[j]
            assert r2.poids_flous[complet[j]] == r1.poids_flous[j]


class TestCasCoherents:
    @_LIGHT
    @given(
        n=st.integers(min_value=3, max_value=5),
        jugement=st.sampled_from(_JUGEMENTS),
        cote_best=st.booleans(),
    )
    def test_jugements_transitifs_donnent_xi_petit(self, n, jugement, cote_best):
        """Jugements construits transitifs (a_Bj · a_jW = a_BW exact) : ξ* < 0.1.

        Deux familles exactement cohérentes :
        - côté Best : a_Bj = J pour tout j, a_jW = également important
          (tous les « autres » valent le Pire, le Meilleur les domine de J) ;
        - côté Worst : a_Bj = également important, a_jW = J pour tout j
          (tous les « autres » valent le Meilleur, qui domine le Pire de J).
        """
        criteres = [f"c{k}" for k in range(n)]
        best, worst = criteres[0], criteres[-1]
        milieu = criteres[1:-1]
        if cote_best:
            bva = {j: jugement for j in criteres[1:]}
            avw = {j: "egalement_important" for j in milieu}
            avw[best] = jugement
        else:
            bva = {j: "egalement_important" for j in milieu}
            bva[worst] = jugement
            avw = {j: jugement for j in criteres[:-1]}
        res = resoudre_fbwm(criteres, best, worst, bva, avw, graine=3)
        assert res.converge
        assert res.xi_star < 0.1
        assert res.coherent
