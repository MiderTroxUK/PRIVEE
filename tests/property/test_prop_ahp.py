"""Proprietes mathematiques du module AHP - phase E9, Lot 9.4.

Cas analytiques exacts et invariants Hypothesis pour ``priority_vector``,
``consistency_ratio``, ``run_ahp``, ``compute_ud``, ``bipolar_to_saaty``,
``score_6_to_9`` et ``ud_smoothed``.

Note d'approximation (cf. ``docs/modele_mathematique.md``, Lot 9.1) :
``priority_vector`` implemente la methode " moyenne des colonnes normalisees "
(chaque colonne est divisee par sa somme, puis chaque ligne est moyennee), et
NON la methode exacte du vecteur propre principal de Saaty. Pour une matrice
PARFAITEMENT coherente (a_ij = w_i/w_j), les deux methodes coincident : chaque
colonne normalisee vaut exactement w, la moyenne des lignes est donc w lui-meme
(aux arrondis flottants pres, de l'ordre de 1e-16). Pour une matrice
INCOHERENTE, les deux methodes divergent legerement ; cet ecart est accepte et
documente - les proprietes ci-dessous n'exigent donc l'exactitude des poids que
sur des matrices coherentes.
"""

import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from supplyscore.core.ahp import (
    bipolar_to_saaty,
    compute_ud,
    consistency_ratio,
    priority_vector,
    run_ahp,
    score_6_to_9,
    ud_smoothed,
)

# Strategies

#: Jugements de Saaty classiques : 1..9 et leurs reciproques.
_SAATY_DISCRETE: list[float] = sorted(
    {float(k) for k in range(1, 10)} | {1.0 / k for k in range(1, 10)}
)

#: Jugement de Saaty valide dans [1/9, 9] : valeur classique ou intermediaire.
_saaty_judgement = st.one_of(
    st.sampled_from(_SAATY_DISCRETE),
    st.floats(min_value=1.0 / 9.0, max_value=9.0),
)


@st.composite
def _comparison_sets(draw, min_n: int = 2, max_n: int = 5):
    """Jeu complet de comparaisons (i < j) pour n criteres, valeurs Saaty valides."""
    n = draw(st.integers(min_value=min_n, max_value=max_n))
    comps = {(i, j): draw(_saaty_judgement) for i in range(n) for j in range(i + 1, n)}
    return n, comps


@st.composite
def _comparison_sets_with_permutation(draw):
    """Comparaisons + permutation aleatoire des indices de criteres."""
    n, comps = draw(_comparison_sets())
    perm = draw(st.permutations(range(n)))
    return n, comps, list(perm)


@st.composite
def _weight_vectors(draw, min_n: int = 2, max_n: int = 6, low: float = 0.05, high: float = 1.0):
    """Vecteur de poids strictement positifs (non necessairement normalise)."""
    n = draw(st.integers(min_value=min_n, max_value=max_n))
    w = draw(st.lists(st.floats(min_value=low, max_value=high), min_size=n, max_size=n))
    return np.asarray(w, dtype=float)


@st.composite
def _weights_and_scores(draw):
    """Couple (poids > 0, notes dans [1, 9]) de meme longueur."""
    n = draw(st.integers(min_value=2, max_value=6))
    w = draw(st.lists(st.floats(min_value=0.05, max_value=1.0), min_size=n, max_size=n))
    s = draw(st.lists(st.floats(min_value=1.0, max_value=9.0), min_size=n, max_size=n))
    return np.asarray(w, dtype=float), np.asarray(s, dtype=float)


@st.composite
def _ud_monotonie_cases(draw):
    """(poids, notes, indice a augmenter, increment >= 0)."""
    w, s = draw(_weights_and_scores())
    k = draw(st.integers(min_value=0, max_value=len(s) - 1))
    delta = draw(st.floats(min_value=0.0, max_value=8.0))
    return w, s, k, delta


# Cas analytiques exacts


class TestCasAnalytiques:
    """Cas de reference chiffres (tracabilite croisee avec docs/modele_mathematique.md)."""

    def test_matrice_coherente_4_criteres_poids_exacts(self):
        """a_ij = w_i/w_j avec w = (0.4, 0.3, 0.2, 0.1) : w exact, lambdamax = 4, CR = 0.

        Pour une matrice parfaitement coherente, chaque colonne normalisee vaut
        exactement w (a_ij / Sigma_k a_kj = w_i / Sigma_k w_k = w_i) : la moyenne des
        colonnes normalisees EST le vecteur de poids vrai, sans approximation.
        """
        w_true = np.array([0.4, 0.3, 0.2, 0.1])
        a = w_true[:, None] / w_true[None, :]
        w = priority_vector(a)
        np.testing.assert_allclose(w, w_true, rtol=0.0, atol=1e-12)
        lambda_max, ci, cr = consistency_ratio(a, w)
        assert lambda_max == pytest.approx(4.0, abs=1e-9)
        assert ci == pytest.approx(0.0, abs=1e-12)
        assert cr == pytest.approx(0.0, abs=1e-12)

    def test_matrice_2x2_poids_exacts(self):
        """[[1, 3], [1/3, 1]] donne w = (0.75, 0.25), exactement en flottant."""
        a = np.array([[1.0, 3.0], [1.0 / 3.0, 1.0]])
        w = priority_vector(a)
        assert w[0] == 0.75
        assert w[1] == 0.25


# Proprietes du vecteur de priorites


class TestProprietesPriorites:
    @given(case=_comparison_sets())
    def test_somme_unite_et_positivite(self, case):
        """Sigmaw = 1 (1e-9), w_i > 0, lambdamax >= n et CR >= 0 pour tout jeu valide."""
        n, comps = case
        result = run_ahp(comps, n=n)
        assert result.weights.shape == (n,)
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-9)
        assert np.all(result.weights > 0.0)
        # Pour toute matrice reciproque positive et tout w > 0 : mean((A @ w) / w) >= n (chaque paire (i, j) contribue t + 1/t >= 2), donc lambdamax >= n et CR >= 0, aux arrondis flottants pres.
        assert result.lambda_max >= n - 1e-9
        assert result.consistency_ratio >= -1e-12

    @given(case=_comparison_sets_with_permutation())
    def test_invariance_par_permutation(self, case):
        """Permuter les indices des comparaisons permute les poids a l'identique."""
        n, comps, perm = case
        w = run_ahp(comps, n=n).weights
        comps_perm = {(perm[i], perm[j]): v for (i, j), v in comps.items()}
        w_perm = run_ahp(comps_perm, n=n).weights
        # Le critere i devient le critere perm[i] : son poids doit le suivre.
        np.testing.assert_allclose(w_perm[np.asarray(perm)], w, rtol=0.0, atol=1e-12)


class TestMatriceCoherenteAleatoire:
    @given(w_true=_weight_vectors(min_n=3, max_n=6, low=0.1, high=10.0))
    def test_cr_quasi_nul_et_poids_retrouves(self, w_true):
        """Matrice a_ij = w_i/w_j parfaitement coherente : CR < 1e-9, coherente."""
        n = len(w_true)
        comps = {(i, j): float(w_true[i] / w_true[j]) for i in range(n) for j in range(i + 1, n)}
        result = run_ahp(comps, n=n)
        assert abs(result.consistency_ratio) < 1e-9
        assert result.is_consistent
        np.testing.assert_allclose(result.weights, w_true / w_true.sum(), rtol=0.0, atol=1e-9)


# Echelles UI


class TestBipolarToSaaty:
    @given(v=st.integers(min_value=-8, max_value=8))
    def test_image_dans_echelle_saaty(self, v):
        """bipolar_to_saaty(v) est dans [1/9, 9] pour tout v dans [-8, 8]."""
        s = bipolar_to_saaty(v)
        assert 1.0 / 9.0 <= s <= 9.0

    @given(v=st.integers(min_value=-8, max_value=8))
    def test_antisymetrie(self, v):
        """bipolar_to_saaty(-v) == 1 / bipolar_to_saaty(v) (1e-12)."""
        assert bipolar_to_saaty(-v) == pytest.approx(1.0 / bipolar_to_saaty(v), abs=1e-12)

    def test_neutre(self):
        """v = 0 : importance egale, jugement de Saaty 1.0."""
        assert bipolar_to_saaty(0) == 1.0


class TestScore6To9:
    @given(v1=st.floats(min_value=1.0, max_value=6.0), v2=st.floats(min_value=1.0, max_value=6.0))
    def test_monotone_croissante(self, v1, v2):
        """v1 <= v2 implique score_6_to_9(v1) <= score_6_to_9(v2)."""
        lo, hi = sorted((v1, v2))
        assert score_6_to_9(lo) <= score_6_to_9(hi)

    def test_points_extremes(self):
        """1 -> 1 et 6 -> 9, exactement."""
        assert score_6_to_9(1.0) == 1.0
        assert score_6_to_9(6.0) == 9.0

    @given(v=st.floats(min_value=1.0, max_value=6.0))
    def test_image_dans_1_9(self, v):
        """L'image de [1, 6] reste dans [1, 9]."""
        assert 1.0 <= score_6_to_9(v) <= 9.0


# Urgence declaree Ud


class TestComputeUd:
    @given(ws=_weights_and_scores())
    def test_borne_0_1(self, ws):
        """compute_ud reste dans [0, 1] pour tout couple (poids, notes) valide."""
        w, s = ws
        assert 0.0 <= compute_ud(w, s) <= 1.0

    @given(w=_weight_vectors())
    def test_toutes_notes_a_1_donne_zero(self, w):
        """Sens direct du " ssi " : toutes les notes a 1 donnent Ud = 0."""
        assert compute_ud(w, np.ones_like(w)) == pytest.approx(0.0, abs=1e-12)

    @given(w=_weight_vectors())
    def test_toutes_notes_a_9_donne_un(self, w):
        """Sens direct du " ssi " : toutes les notes a 9 donnent Ud = 1."""
        assert compute_ud(w, np.full_like(w, 9.0)) == pytest.approx(1.0, abs=1e-12)

    @given(ws=_weights_and_scores())
    def test_positif_des_qu_une_note_depasse_1(self, ws):
        """Reciproque du " ssi " : une note > 1 (poids > 0) implique Ud > 0."""
        w, s = ws
        assume(float(s.max()) >= 1.0 + 1e-3)
        assert compute_ud(w, s) > 0.0

    @given(ws=_weights_and_scores())
    def test_inferieur_a_un_des_qu_une_note_sous_9(self, ws):
        """Reciproque du " ssi " : une note < 9 (poids > 0) implique Ud < 1."""
        w, s = ws
        assume(float(s.min()) <= 9.0 - 1e-3)
        assert compute_ud(w, s) < 1.0

    @given(case=_ud_monotonie_cases())
    def test_monotone_en_chaque_note(self, case):
        """Augmenter une note (a poids fixes) n'abaisse jamais Ud."""
        w, s, k, delta = case
        s_up = s.copy()
        s_up[k] = min(9.0, float(s_up[k]) + delta)
        # Marge 1e-12 : deux produits scalaires flottants evalues independamment.
        assert compute_ud(w, s_up) >= compute_ud(w, s) - 1e-12


# Lissage exponentiel


class TestUdSmoothed:
    @given(
        prev=st.floats(min_value=0.0, max_value=1.0),
        cur=st.floats(min_value=0.0, max_value=1.0),
        rho=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_combinaison_convexe_entre_bornes(self, prev, cur, rho):
        """ud_smoothed(prev, cur, rho) reste dans [min(prev, cur), max(prev, cur)]."""
        out = ud_smoothed(prev, cur, rho)
        # Marge 1e-12 : la combinaison convexe flottante peut deborder d'un ulp.
        assert min(prev, cur) - 1e-12 <= out <= max(prev, cur) + 1e-12

    @given(
        cur=st.floats(min_value=0.0, max_value=1.0),
        rho=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_prev_none_renvoie_cur(self, cur, rho):
        """Premier questionnaire (prev None) : Ud courant renvoye tel quel."""
        assert ud_smoothed(None, cur, rho) == cur
