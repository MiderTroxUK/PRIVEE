"""Tests unitaires du solveur FBWM (Guo & Zhao 2017) - phase E12, Lot 12.2."""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from supplyscore.mcda import fbwm
from supplyscore.mcda.fbwm import (
    ECHELLE_LINGUISTIQUE,
    SEUIL_CR,
    TABLE_CI,
    ResultatFBWM,
    _resoudre,
    resoudre_fbwm,
)

# Configuration de reference (3 criteres, jugements plausibles)

CRITERES = ["cout", "delai", "qualite"]
BEST, WORST = "cout", "qualite"
BVA = {"delai": "assez_plus_important", "qualite": "tres_plus_important"}
AVW = {"cout": "tres_plus_important", "delai": "assez_plus_important"}


class TestConstantes:
    def test_echelle_et_table_ci_alignees(self):
        assert set(ECHELLE_LINGUISTIQUE) == set(TABLE_CI)
        assert SEUIL_CR == 0.10

    def test_echelle_nft_valides(self):
        for bas, modal, haut in ECHELLE_LINGUISTIQUE.values():
            assert 0 < bas <= modal <= haut


class TestCasAnalytiqueCrisp:
    """Cas crisp degenere (l = m = u) du PLAN : a_B = (1, 2, 4), a_W = (4, 2, 1).

    Coherent (a_13 = a_12 - a_23) : la solution BWM exacte est w = (4/7, 2/7, 1/7)
    avec xi* = 0 - le solveur flou doit la retrouver.
    """

    def test_poids_exacts_et_xi_quasi_nul(self):
        a_b = {"c1": (1.0, 1.0, 1.0), "c2": (2.0, 2.0, 2.0), "c3": (4.0, 4.0, 4.0)}
        a_w = {"c1": (4.0, 4.0, 4.0), "c2": (2.0, 2.0, 2.0), "c3": (1.0, 1.0, 1.0)}
        res = _resoudre(["c1", "c2", "c3"], "c1", "c3", a_b, a_w, graine=0)
        assert res.converge
        assert res.xi_star < 1e-4
        assert res.poids["c1"] == pytest.approx(4 / 7, abs=1e-3)
        assert res.poids["c2"] == pytest.approx(2 / 7, abs=1e-3)
        assert res.poids["c3"] == pytest.approx(1 / 7, abs=1e-3)
        assert sum(res.poids.values()) == pytest.approx(1.0, abs=1e-9)
        # A xi* = 0 la solution est necessairement crisp : etalement quasi nul.
        for bas, _modal, haut in res.poids_flous.values():
            assert haut - bas < 1e-2
        assert res.coherent
        assert res.cr == pytest.approx(res.xi_star / max(TABLE_CI.values()))


class TestAppelPublic:
    def test_poids_ordonnes_du_best_au_worst(self):
        res = resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW, graine=0)
        assert res.converge
        assert res.poids[BEST] > res.poids["delai"] > res.poids[WORST]
        assert sum(res.poids.values()) == pytest.approx(1.0, abs=1e-9)
        assert all(p > 0 for p in res.poids.values())

    def test_cr_utilise_le_jugement_le_plus_fort(self):
        res = resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW, graine=0)
        # Jugements saisis : assez (CI 5.29) et tres (CI 6.69) => CI = 6.69.
        assert res.cr == pytest.approx(res.xi_star / TABLE_CI["tres_plus_important"])
        assert res.coherent == (res.cr < SEUIL_CR)

    def test_poids_flous_ordonnes_et_positifs(self):
        res = resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW, graine=0)
        for bas, modal, haut in res.poids_flous.values():
            assert 0 < bas <= modal + 1e-9
            assert modal <= haut + 1e-9

    def test_deux_criteres_minimal(self):
        # n = 2 : 2n - 3 = 1 seule comparaison (a_BW), portee par le cote Best.
        res = resoudre_fbwm(["a", "b"], "a", "b", {"b": "assez_plus_important"}, {}, graine=0)
        assert res.converge
        assert res.poids["a"] == pytest.approx(2 / 3, abs=2e-2)
        assert res.poids["b"] == pytest.approx(1 / 3, abs=2e-2)


class TestConventionABW:
    def test_un_seul_cote_suffit_et_donne_le_meme_resultat(self):
        avw_sans_best = {"delai": "assez_plus_important"}
        bva_sans_worst = {"delai": "assez_plus_important"}
        complet = resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW, graine=0)
        cote_best = resoudre_fbwm(CRITERES, BEST, WORST, BVA, avw_sans_best, graine=0)
        cote_worst = resoudre_fbwm(
            CRITERES, BEST, WORST, bva_sans_worst, {**AVW, "cout": "tres_plus_important"}, graine=0
        )
        assert cote_best == complet
        assert cote_worst == complet

    def test_absent_des_deux_cotes_invalide(self):
        bva = {"delai": "assez_plus_important"}
        avw = {"delai": "assez_plus_important"}
        with pytest.raises(ValueError, match="a_BW"):
            resoudre_fbwm(CRITERES, BEST, WORST, bva, avw)

    def test_contradiction_entre_les_deux_cotes_invalide(self):
        avw = {**AVW, "cout": "absolument_plus_important"}
        with pytest.raises(ValueError, match="contradictoires"):
            resoudre_fbwm(CRITERES, BEST, WORST, BVA, avw)


class TestValidations:
    def test_best_egal_worst(self):
        with pytest.raises(ValueError, match="distincts"):
            resoudre_fbwm(CRITERES, "cout", "cout", BVA, AVW)

    def test_moins_de_deux_criteres(self):
        with pytest.raises(ValueError, match="Au moins 2 critères"):
            resoudre_fbwm(["seul"], "seul", "seul", {}, {})

    def test_criteres_en_double(self):
        with pytest.raises(ValueError, match="uniques"):
            resoudre_fbwm(["a", "a", "b"], "a", "b", {"b": "assez_plus_important"}, {})

    def test_best_hors_liste(self):
        with pytest.raises(ValueError, match="Meilleur"):
            resoudre_fbwm(CRITERES, "inconnu", WORST, BVA, AVW)

    def test_worst_hors_liste(self):
        with pytest.raises(ValueError, match="Pire"):
            resoudre_fbwm(CRITERES, BEST, "inconnu", BVA, AVW)

    def test_jugement_best_vers_autres_manquant(self):
        bva = {"qualite": "tres_plus_important"}  # " delai " manquant
        with pytest.raises(ValueError, match="manquant dans best_vers_autres"):
            resoudre_fbwm(CRITERES, BEST, WORST, bva, AVW)

    def test_jugement_autres_vers_worst_manquant(self):
        avw = {"cout": "tres_plus_important"}  # " delai " manquant
        with pytest.raises(ValueError, match="manquant dans autres_vers_worst"):
            resoudre_fbwm(CRITERES, BEST, WORST, BVA, avw)

    def test_jugement_linguistique_inconnu(self):
        bva = {**BVA, "delai": "hyper_important"}
        with pytest.raises(ValueError, match="Jugement linguistique inconnu"):
            resoudre_fbwm(CRITERES, BEST, WORST, bva, AVW)

    def test_cle_inattendue_dans_best_vers_autres(self):
        bva = {**BVA, "cout": "egalement_important"}  # le Meilleur lui-meme
        with pytest.raises(ValueError, match="Clé inattendue dans best_vers_autres"):
            resoudre_fbwm(CRITERES, BEST, WORST, bva, AVW)

    def test_cle_inattendue_dans_autres_vers_worst(self):
        avw = {**AVW, "fantome": "egalement_important"}
        with pytest.raises(ValueError, match="Clé inattendue dans autres_vers_worst"):
            resoudre_fbwm(CRITERES, BEST, WORST, BVA, avw)


class TestReproductibilite:
    def test_meme_graine_meme_resultat_bit_a_bit(self):
        r1 = resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW, graine=42)
        r2 = resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW, graine=42)
        assert r1 == r2  # dataclass gelee : egalite champ a champ, bit a bit
        assert r1.poids == r2.poids
        assert r1.poids_flous == r2.poids_flous
        assert r1.xi_star == r2.xi_star


class TestRepliUniforme:
    """Echec de convergence force : repli uniforme, jamais d'exception."""

    def _verifie_repli(self, res: ResultatFBWM) -> None:
        assert res.converge is False
        assert res.poids == {c: 1.0 / 3.0 for c in CRITERES}
        assert res.poids_flous == {c: (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0) for c in CRITERES}
        assert math.isinf(res.xi_star)
        assert math.isinf(res.cr)
        assert res.coherent is False

    def test_echec_total_renvoie_poids_uniformes(self, monkeypatch):
        def _refus(*_args, **_kwargs):
            return SimpleNamespace(success=False, x=np.full(10, np.nan), message="échec simulé")

        monkeypatch.setattr(fbwm.optimize, "minimize", _refus)
        self._verifie_repli(resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW))

    def test_exception_numerique_renvoie_poids_uniformes(self, monkeypatch):
        def _explose(*_args, **_kwargs):
            raise RuntimeError("instabilité numérique simulée")

        monkeypatch.setattr(fbwm.optimize, "minimize", _explose)
        self._verifie_repli(resoudre_fbwm(CRITERES, BEST, WORST, BVA, AVW))


class TestReexportsPaquet:
    def test_api_disponible_au_niveau_du_paquet(self):
        import supplyscore.mcda as mcda

        assert mcda.resoudre_fbwm is resoudre_fbwm
        assert mcda.ResultatFBWM is ResultatFBWM
        assert mcda.ECHELLE_LINGUISTIQUE is ECHELLE_LINGUISTIQUE
        assert mcda.TABLE_CI is TABLE_CI
        assert mcda.SEUIL_CR == SEUIL_CR
