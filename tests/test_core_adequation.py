"""Tests du moteur d'adequation Ud/Ur."""

from itertools import pairwise

import pytest

from supplyscore.core.adequation import AdequationEngine
from supplyscore.domain.models import UrgencyState


@pytest.fixture
def engine() -> AdequationEngine:
    return AdequationEngine()


class TestAdequationSimple:
    def test_alignement_parfait(self, engine):
        assert engine.adequation_simple(0.5, 0.5) == pytest.approx(1.0)
        assert engine.adequation_simple(0.0, 0.0) == pytest.approx(1.0)

    def test_ecart_maximal(self, engine):
        assert engine.adequation_simple(0.0, 1.0) == pytest.approx(0.0)
        assert engine.adequation_simple(1.0, 0.0) == pytest.approx(0.0)

    def test_ur_superieur_a_1_ecart_borne(self, engine):
        """Tache en retard (ur > 1) : l'ecart est borne a 1."""
        assert engine.adequation_simple(0.5, 3.0) == pytest.approx(0.0)
        assert engine.adequation_simple(1.0, 1.0) == pytest.approx(1.0)


class TestPathologies:
    def test_false_urgency(self, engine):
        assert engine.false_urgency(0.8, 0.3) == pytest.approx(0.5)
        assert engine.false_urgency(0.3, 0.8) == 0.0

    def test_hidden_risk(self, engine):
        assert engine.hidden_risk(0.3, 0.8) == pytest.approx(0.5)
        assert engine.hidden_risk(0.8, 0.3) == 0.0

    def test_f_et_h_exclusifs(self, engine):
        """F et H ne peuvent pas etre tous deux > 0 pour un meme couple."""
        for ud, ur in [(0.2, 0.9), (0.9, 0.2), (0.5, 0.5), (0.0, 1.0)]:
            f = engine.false_urgency(ud, ur)
            h = engine.hidden_risk(ud, ur)
            assert f * h == 0.0
            assert f >= 0.0 and h >= 0.0


class TestAdequationAsym:
    def test_alignement_parfait_100(self, engine):
        assert engine.adequation_asym(0.5, 0.5) == pytest.approx(100.0)
        assert engine.adequation_asym(0.0, 0.0) == pytest.approx(100.0)
        assert engine.adequation_asym(1.0, 1.0) == pytest.approx(100.0)

    def test_ecart_maximal_sous_estimation_0(self, engine):
        """|ecart| = 1 dans la direction la plus penalisee -> score 0."""
        assert engine.adequation_asym(0.0, 1.0) == pytest.approx(0.0)

    def test_asymetrie_sous_estimation_plus_penalisee(self, engine):
        """Risque cache (ur > ud) penalise plus fort que fausse urgence."""
        hidden = engine.adequation_asym(ud=0.2, ur=0.8)
        false = engine.adequation_asym(ud=0.8, ur=0.2)
        assert hidden < false

    def test_monotonie_en_ecart(self, engine):
        """Plus l'ecart grandit, plus le score baisse."""
        scores = [engine.adequation_asym(0.5, 0.5 + d) for d in (0.0, 0.1, 0.3, 0.5)]
        assert all(b < a for a, b in pairwise(scores))

    def test_ur_tres_en_retard_score_0(self, engine):
        assert engine.adequation_asym(0.0, 2.5) == 0.0

    def test_bornes(self, engine):
        for ud in (0.0, 0.3, 0.7, 1.0):
            for ur in (0.0, 0.4, 1.0, 1.8):
                assert 0.0 <= engine.adequation_asym(ud, ur) <= 100.0

    def test_lambdas_invalides(self, engine):
        with pytest.raises(ValueError):
            AdequationEngine(lambda_under=0.0)
        with pytest.raises(ValueError):
            AdequationEngine(lambda_over=-1.0)
        with pytest.raises(ValueError):
            engine.adequation_asym(0.5, 0.5, lambda_under=-2.0)

    def test_alpha_invalide(self):
        with pytest.raises(ValueError):
            AdequationEngine(alpha=0.0)
        with pytest.raises(ValueError):
            AdequationEngine(alpha=1.5)

    def test_symetrique_si_lambdas_egaux(self):
        eng = AdequationEngine(lambda_under=1.5, lambda_over=1.5)
        assert eng.adequation_asym(0.2, 0.8) == pytest.approx(eng.adequation_asym(0.8, 0.2))


class TestEvaluate:
    def test_etat_urgence_rempli(self, engine):
        state = engine.evaluate(ud=0.3, ur=0.7)
        assert isinstance(state, UrgencyState)
        assert state.ud == pytest.approx(0.3)
        assert state.ur == pytest.approx(0.7)
        assert state.adequation == pytest.approx(engine.adequation_asym(0.3, 0.7))
        assert state.false_urgency == 0.0
        assert state.hidden_risk == pytest.approx(0.4)

    def test_champs_locaux_laisses_none(self, engine):
        state = engine.evaluate(ud=0.5, ur=0.5)
        assert state.ud_local is None
        assert state.ur_local is None
