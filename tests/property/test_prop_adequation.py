"""Propriétés Hypothesis du score d'adéquation Ud/Ur (E9 — Lot 9.5).

Couvre :class:`supplyscore.core.adequation.AdequationEngine` :

- cas analytiques exacts (alignement parfait, écarts maximaux, asymétrie) ;
- identités F·H == 0 et F − H == Ud − Ur ;
- bornes A ∈ [0, 100] et monotonie directionnelle à Ud fixé ;
- cohérence de ``evaluate()`` avec les fonctions unitaires.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core.adequation import AdequationEngine

#: Moteur aux paramètres de gouvernance par défaut : λ_under=2.25, λ_over=1.0, α=0.88.
ENGINE = AdequationEngine()

#: Urgence dans le carré unité [0, 1].
UNIT = st.floats(min_value=0.0, max_value=1.0)

#: Ur étendue : peut dépasser 1 pour une tâche en retard (domaine documenté ur >= 0).
UR_ETENDUE = st.floats(min_value=0.0, max_value=3.0)


class TestCasAnalytiques:
    """Valeurs fermées calculées à la main depuis la formule documentée."""

    @pytest.mark.parametrize("x", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_alignement_parfait_vaut_100(self, x: float) -> None:
        # ud == ur -> pénalité nulle -> A == 100 (à 1e-9 près).
        assert ENGINE.adequation_asym(x, x) == pytest.approx(100.0, abs=1e-9)

    def test_fausse_urgence_maximale_29_34(self) -> None:
        # A(1, 0) : e_over=1 -> penalty=λ_over=1 ; normalisation par e^(−2.25).
        attendu = 100.0 * (math.exp(-1.0) - math.exp(-2.25)) / (1.0 - math.exp(-2.25))
        a = ENGINE.adequation_asym(1.0, 0.0)
        assert a == pytest.approx(attendu, abs=1e-9)
        assert a == pytest.approx(29.34, abs=0.01)

    def test_risque_cache_maximal_zero_exact(self) -> None:
        # A(0, 1) : penalty == max_penalty == λ_under -> plancher atteint -> 0.0 EXACT.
        assert ENGINE.adequation_asym(0.0, 1.0) == 0.0

    def test_asymetrie_sous_estimation_plus_penalisee(self) -> None:
        # Même écart |Ud − Ur| = 0.6 : le risque caché coûte plus cher que la panique.
        assert ENGINE.adequation_asym(0.2, 0.8) < ENGINE.adequation_asym(0.8, 0.2)


class TestProprietesFH:
    """Identités algébriques de la fausse urgence F et du risque caché H."""

    @given(ud=UNIT, ur=UNIT)
    def test_produit_nul_et_difference_signee(self, ud: float, ur: float) -> None:
        f = ENGINE.false_urgency(ud, ur)
        h = ENGINE.hidden_risk(ud, ur)
        # Au plus une pathologie à la fois : F·H == 0 exactement.
        assert f * h == 0.0
        # F − H == Ud − Ur (différence signée reconstituée).
        assert abs((f - h) - (ud - ur)) <= 1e-12

    @given(ud=UNIT, ur=UR_ETENDUE)
    def test_f_et_h_positifs(self, ud: float, ur: float) -> None:
        assert ENGINE.false_urgency(ud, ur) >= 0.0
        assert ENGINE.hidden_risk(ud, ur) >= 0.0


class TestProprietesScore:
    """Bornes et monotonie du score asymétrique."""

    @given(ud=UNIT, ur=UR_ETENDUE)
    def test_score_borne_0_100(self, ud: float, ur: float) -> None:
        a = ENGINE.adequation_asym(ud, ur)
        assert 0.0 <= a <= 100.0
        assert math.isfinite(a)

    @given(ud=UNIT, f_near=UNIT, f_far=UNIT, sign=st.sampled_from((1.0, -1.0)))
    def test_monotonie_directionnelle(
        self, ud: float, f_near: float, f_far: float, sign: float
    ) -> None:
        # À Ud fixé, un écart plus grand DANS LA MÊME DIRECTION ne peut
        # qu'empirer le score : |ud − ur_far| >= |ud − ur_near| => A_far <= A_near.
        m_lo, m_hi = sorted((f_near, f_far))
        room = (1.0 - ud) if sign > 0 else ud  # reste dans [0, 1] des deux côtés
        ur_near = ud + sign * m_lo * room
        ur_far = ud + sign * m_hi * room
        a_near = ENGINE.adequation_asym(ud, ur_near)
        a_far = ENGINE.adequation_asym(ud, ur_far)
        assert a_far <= a_near + 1e-9


class TestEvaluate:
    """``evaluate()`` doit rester cohérent avec les fonctions unitaires."""

    @given(ud=UNIT, ur=UR_ETENDUE)
    def test_evaluate_coherent_avec_fonctions_unitaires(self, ud: float, ur: float) -> None:
        state = ENGINE.evaluate(ud, ur)
        assert state.ud == ud
        assert state.ur == ur
        assert state.adequation == ENGINE.adequation_asym(ud, ur)
        assert state.false_urgency == ENGINE.false_urgency(ud, ur)
        assert state.hidden_risk == ENGINE.hidden_risk(ud, ur)
        # Invariants transverses sur l'état rempli.
        assert 0.0 <= state.adequation <= 100.0
        assert state.false_urgency * state.hidden_risk == 0.0
        assert abs((state.false_urgency - state.hidden_risk) - (ud - ur)) <= 1e-12
