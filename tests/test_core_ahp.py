"""Tests du module AHP (urgence déclarée Ud)."""

import numpy as np
import pytest

from supplyscore.core.ahp import (
    AHPResult,
    bipolar_to_saaty,
    build_matrix,
    compute_ud,
    consistency_ratio,
    priority_vector,
    run_ahp,
    score_6_to_9,
    ud_smoothed,
)


class TestBuildMatrix:
    def test_matrice_reciproque(self):
        A = build_matrix({(0, 1): 3.0, (0, 2): 5.0}, n=3)
        assert A[0, 1] == 3.0
        assert A[1, 0] == pytest.approx(1 / 3)
        assert A[0, 2] == 5.0
        assert A[2, 0] == pytest.approx(1 / 5)
        assert np.allclose(np.diag(A), 1.0)

    def test_valeur_non_positive_rejetee(self):
        with pytest.raises(ValueError):
            build_matrix({(0, 1): 0.0}, n=2)
        with pytest.raises(ValueError):
            build_matrix({(0, 1): -2.0}, n=2)

    def test_indice_hors_bornes_rejete(self):
        with pytest.raises(ValueError):
            build_matrix({(0, 5): 2.0}, n=4)


class TestPriorityAndConsistency:
    def test_matrice_identite_poids_egaux_cr_nul(self):
        """Matrice de jugements neutre (tout à 1) -> poids égaux, CR = 0."""
        A = np.ones((4, 4))
        w = priority_vector(A)
        assert np.allclose(w, 0.25)
        lambda_max, ci, cr = consistency_ratio(A, w)
        assert lambda_max == pytest.approx(4.0)
        assert ci == pytest.approx(0.0, abs=1e-12)
        assert cr == pytest.approx(0.0, abs=1e-12)

    def test_jugements_coherents_poids_attendus(self):
        """Matrice parfaitement cohérente w ∝ [8, 4, 2, 1] -> poids exacts."""
        comparisons = {
            (0, 1): 2.0, (0, 2): 4.0, (0, 3): 8.0,
            (1, 2): 2.0, (1, 3): 4.0, (2, 3): 2.0,
        }
        result = run_ahp(comparisons, n=4)
        expected = np.array([8, 4, 2, 1]) / 15.0
        assert np.allclose(result.weights, expected)
        assert result.consistency_ratio == pytest.approx(0.0, abs=1e-9)
        assert result.is_consistent

    def test_matrice_incoherente_cr_eleve(self):
        """Jugements cycliques contradictoires -> CR >= 0.10."""
        comparisons = {(0, 1): 9.0, (1, 2): 9.0, (0, 2): 1 / 9.0}
        result = run_ahp(comparisons, n=3)
        assert result.consistency_ratio >= 0.10
        assert not result.is_consistent

    def test_run_ahp_deduit_n(self):
        result = run_ahp({(0, 1): 2.0, (1, 2): 2.0, (0, 2): 4.0})
        assert isinstance(result, AHPResult)
        assert result.weights.shape == (3,)
        assert result.weights.sum() == pytest.approx(1.0)


class TestComputeUd:
    def test_bornes(self):
        w = np.full(4, 0.25)
        assert compute_ud(w, np.full(4, 1.0)) == pytest.approx(0.0)
        assert compute_ud(w, np.full(4, 9.0)) == pytest.approx(1.0)

    def test_valeur_intermediaire(self):
        w = np.full(4, 0.25)
        assert compute_ud(w, np.full(4, 5.0)) == pytest.approx(0.5)

    def test_score_hors_echelle_rejete(self):
        w = np.full(4, 0.25)
        with pytest.raises(ValueError):
            compute_ud(w, np.array([0.5, 5, 5, 5]))
        with pytest.raises(ValueError):
            compute_ud(w, np.array([5, 5, 5, 9.5]))


class TestEchellesUI:
    def test_bipolar_to_saaty(self):
        assert bipolar_to_saaty(0) == pytest.approx(1.0)
        assert bipolar_to_saaty(8) == pytest.approx(9.0)
        assert bipolar_to_saaty(-8) == pytest.approx(1 / 9)
        assert bipolar_to_saaty(3) == pytest.approx(4.0)
        assert bipolar_to_saaty(-3) == pytest.approx(1 / 4)

    def test_bipolar_hors_bornes(self):
        with pytest.raises(ValueError):
            bipolar_to_saaty(9)
        with pytest.raises(ValueError):
            bipolar_to_saaty(-9)

    def test_score_6_to_9(self):
        assert score_6_to_9(1) == pytest.approx(1.0)
        assert score_6_to_9(6) == pytest.approx(9.0)
        assert score_6_to_9(3.5) == pytest.approx(5.0)

    def test_score_6_to_9_hors_bornes(self):
        with pytest.raises(ValueError):
            score_6_to_9(0)
        with pytest.raises(ValueError):
            score_6_to_9(7)


class TestUdSmoothed:
    def test_premier_questionnaire(self):
        assert ud_smoothed(None, 0.7) == pytest.approx(0.7)

    def test_lissage(self):
        assert ud_smoothed(0.2, 0.8, rho=0.3) == pytest.approx(0.3 * 0.2 + 0.7 * 0.8)

    def test_rho_invalide(self):
        with pytest.raises(ValueError):
            ud_smoothed(0.5, 0.5, rho=1.5)
        with pytest.raises(ValueError):
            ud_smoothed(0.5, 0.5, rho=-0.1)
