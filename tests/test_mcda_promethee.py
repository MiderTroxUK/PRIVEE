"""Tests unitaires PROMETHEE II — phase E12, Lot 12.1.

Cas analytique de référence calculé à la main (PLAN.md E12), sens « min »,
les six fonctions de préférence sur leurs valeurs clés, règle des valeurs
manquantes vérifiée à la main, renormalisation des poids et erreurs.
"""

import pytest

from supplyscore.mcda import (
    Critere,
    Gaussienne,
    LineaireIndifference,
    Palier,
    PrometheeII,
    ResultatPromethee,
    UShape,
    Usuelle,
    VShape,
)

# ---------------------------------------------------------------------------
# Cas analytique de référence (PLAN.md E12) — calcul complet à la main
# ---------------------------------------------------------------------------
#
# 3 alternatives A/B/C, 2 critères « max », fonction Usuelle :
#   g1 = (A: 0.8, B: 0.5, C: 0.2), poids 0.6
#   g2 = (A: 0.1, B: 0.4, C: 0.7), poids 0.4
#
# Indices de préférence π (Usuelle : le gagnant du critère empoche son poids) :
#   π(A,B) = 0.6 (A gagne g1)   π(B,A) = 0.4 (B gagne g2)
#   π(A,C) = 0.6 (A gagne g1)   π(C,A) = 0.4 (C gagne g2)
#   π(B,C) = 0.6 (B gagne g1)   π(C,B) = 0.4 (C gagne g2)
#
# Flux (n − 1 = 2) :
#   φ⁺(A) = (0.6 + 0.6)/2 = 0.6   φ⁻(A) = (0.4 + 0.4)/2 = 0.4   φ(A) = +0.2
#   φ⁺(B) = (0.4 + 0.6)/2 = 0.5   φ⁻(B) = (0.6 + 0.4)/2 = 0.5   φ(B) =  0.0
#   φ⁺(C) = (0.4 + 0.4)/2 = 0.4   φ⁻(C) = (0.6 + 0.6)/2 = 0.6   φ(C) = −0.2


class TestCasAnalytique:
    """Cas de référence chiffré du PLAN.md E12 (3 alternatives, 2 critères max)."""

    @pytest.fixture
    def resultat(self) -> ResultatPromethee:
        criteres = [
            Critere("g1", "max", Usuelle()),
            Critere("g2", "max", Usuelle()),
        ]
        moteur = PrometheeII(criteres, poids={"g1": 0.6, "g2": 0.4})
        valeurs: dict[str, dict[str, float | None]] = {
            "A": {"g1": 0.8, "g2": 0.1},
            "B": {"g1": 0.5, "g2": 0.4},
            "C": {"g1": 0.2, "g2": 0.7},
        }
        return moteur.classer(valeurs)

    def test_phi_net(self, resultat: ResultatPromethee):
        assert resultat.phi["A"] == pytest.approx(0.2, abs=1e-12)
        assert resultat.phi["B"] == pytest.approx(0.0, abs=1e-12)
        assert resultat.phi["C"] == pytest.approx(-0.2, abs=1e-12)

    def test_phi_plus(self, resultat: ResultatPromethee):
        assert resultat.phi_plus["A"] == pytest.approx(0.6, abs=1e-12)
        assert resultat.phi_plus["B"] == pytest.approx(0.5, abs=1e-12)
        assert resultat.phi_plus["C"] == pytest.approx(0.4, abs=1e-12)

    def test_phi_moins(self, resultat: ResultatPromethee):
        assert resultat.phi_moins["A"] == pytest.approx(0.4, abs=1e-12)
        assert resultat.phi_moins["B"] == pytest.approx(0.5, abs=1e-12)
        assert resultat.phi_moins["C"] == pytest.approx(0.6, abs=1e-12)

    def test_classement(self, resultat: ResultatPromethee):
        assert resultat.classement == ["A", "B", "C"]

    def test_poids_non_normalises_acceptes(self):
        """Poids {g1: 3, g2: 2} ≡ {g1: 0.6, g2: 0.4} après renormalisation."""
        criteres = [Critere("g1", "max", Usuelle()), Critere("g2", "max", Usuelle())]
        moteur = PrometheeII(criteres, poids={"g1": 3.0, "g2": 2.0})
        assert moteur.poids["g1"] == pytest.approx(0.6, abs=1e-12)
        assert moteur.poids["g2"] == pytest.approx(0.4, abs=1e-12)
        res = moteur.classer(
            {
                "A": {"g1": 0.8, "g2": 0.1},
                "B": {"g1": 0.5, "g2": 0.4},
                "C": {"g1": 0.2, "g2": 0.7},
            }
        )
        assert res.phi["A"] == pytest.approx(0.2, abs=1e-12)
        assert res.phi["C"] == pytest.approx(-0.2, abs=1e-12)
        assert res.classement == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Sens « min » : l'écart est inversé (d = g(b) − g(a))
# ---------------------------------------------------------------------------


class TestSensMin:
    def test_min_inverse_le_classement_d_un_critere(self):
        """Sur un critère unique, passer de « max » à « min » inverse le classement."""
        valeurs: dict[str, dict[str, float | None]] = {
            "A": {"delai": 0.2},
            "B": {"delai": 0.8},
        }
        res_max = PrometheeII([Critere("delai", "max", Usuelle())], {"delai": 1.0}).classer(valeurs)
        res_min = PrometheeII([Critere("delai", "min", Usuelle())], {"delai": 1.0}).classer(valeurs)
        assert res_max.classement == ["B", "A"]
        assert res_min.classement == ["A", "B"]
        # n = 2 : φ(A) = π(A,B) − π(B,A) ; en « min », A (plus petit délai) domine.
        assert res_min.phi["A"] == pytest.approx(1.0, abs=1e-12)
        assert res_min.phi["B"] == pytest.approx(-1.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Fonctions de préférence — valeurs clés (q, p, bornes)
# ---------------------------------------------------------------------------


class TestFonctionsPreference:
    def test_usuelle(self):
        f = Usuelle()
        assert f(-0.5) == 0.0
        assert f(0.0) == 0.0  # d > 0 strict : l'égalité ne préfère pas
        assert f(1e-9) == 1.0
        assert f(0.7) == 1.0

    def test_u_shape(self):
        f = UShape(q=0.2)
        assert f(-0.1) == 0.0
        assert f(0.0) == 0.0
        assert f(0.2) == 0.0  # d <= q : indifférence (borne incluse)
        assert f(0.2000001) == 1.0
        assert f(0.9) == 1.0

    def test_v_shape(self):
        f = VShape(p=0.5)
        assert f(-0.2) == 0.0
        assert f(0.0) == 0.0
        assert f(0.25) == pytest.approx(0.5, abs=1e-12)  # d/p
        assert f(0.5) == pytest.approx(1.0, abs=1e-12)  # saturation exacte en d = p
        assert f(0.8) == 1.0  # min(d/p, 1) au-delà de p

    def test_palier(self):
        f = Palier(q=0.1, p=0.3)
        assert f(0.0) == 0.0
        assert f(0.1) == 0.0  # d <= q
        assert f(0.2) == 0.5  # q < d <= p
        assert f(0.3) == 0.5  # borne p incluse dans le palier 0.5
        assert f(0.30001) == 1.0  # d > p

    def test_lineaire_indifference_defauts(self):
        """Défauts q = 0.05 et p = 0.30 (critères dans [0, 1])."""
        f = LineaireIndifference()
        assert f.q == 0.05
        assert f.p == 0.30
        assert f(-0.1) == 0.0
        assert f(0.05) == 0.0  # d <= q
        assert f(0.175) == pytest.approx(0.5, abs=1e-12)  # (d − q)/(p − q) à mi-chemin
        assert f(0.30) == pytest.approx(1.0, abs=1e-12)  # borne p : préférence pleine
        assert f(0.9) == 1.0  # d > p

    def test_gaussienne(self):
        import math

        f = Gaussienne(s=0.2)
        assert f(-0.3) == 0.0
        assert f(0.0) == 0.0
        # En d = s : P = 1 − exp(−1/2).
        assert f(0.2) == pytest.approx(1.0 - math.exp(-0.5), abs=1e-12)
        assert f(10.0) == pytest.approx(1.0, abs=1e-9)  # asymptote vers 1

    def test_defaut_du_critere_est_lineaire_indifference(self):
        """Critere sans fonction explicite : LineaireIndifference(q=0.05, p=0.30)."""
        c = Critere("u_time", "max")
        assert isinstance(c.fonction, LineaireIndifference)
        assert c.fonction.q == 0.05
        assert c.fonction.p == 0.30


class TestValidationParametres:
    def test_lineaire_indifference_p_inferieur_ou_egal_q(self):
        with pytest.raises(ValueError, match="p > q"):
            LineaireIndifference(q=0.3, p=0.3)
        with pytest.raises(ValueError, match="p > q"):
            LineaireIndifference(q=0.3, p=0.1)

    def test_lineaire_indifference_q_negatif(self):
        with pytest.raises(ValueError, match="q >= 0"):
            LineaireIndifference(q=-0.1, p=0.3)

    def test_u_shape_q_negatif(self):
        with pytest.raises(ValueError, match="q >= 0"):
            UShape(q=-0.01)

    def test_v_shape_p_non_positif(self):
        with pytest.raises(ValueError, match="p > 0"):
            VShape(p=0.0)

    def test_palier_invalide(self):
        with pytest.raises(ValueError, match="q >= 0"):
            Palier(q=-0.2, p=0.1)
        with pytest.raises(ValueError, match="p > q"):
            Palier(q=0.2, p=0.2)

    def test_gaussienne_s_non_positif(self):
        with pytest.raises(ValueError, match="s > 0"):
            Gaussienne(s=0.0)


# ---------------------------------------------------------------------------
# Valeurs manquantes — renormalisation par paire vérifiée à la main
# ---------------------------------------------------------------------------
#
# Critères « max », Usuelle, poids 0.6 / 0.4. C n'a pas de valeur sur g2.
#   A : g1 = 0.8, g2 = 0.1   B : g1 = 0.5, g2 = 0.4   C : g1 = 0.2, g2 = None
#
# Paire (A,B) — les deux critères présents :        π(A,B) = 0.6, π(B,A) = 0.4
# Paire (A,C) — seul g1 présent, poids renormalisé 0.6/0.6 = 1 :
#   d1(A,C) = +0.6 > 0  ⇒  π(A,C) = 1.0, π(C,A) = 0.0
# Paire (B,C) — idem :  π(B,C) = 1.0, π(C,B) = 0.0
#
# Flux (n − 1 = 2) :
#   φ⁺(A) = (0.6 + 1.0)/2 = 0.8   φ⁻(A) = (0.4 + 0.0)/2 = 0.2   φ(A) = +0.6
#   φ⁺(B) = (0.4 + 1.0)/2 = 0.7   φ⁻(B) = (0.6 + 0.0)/2 = 0.3   φ(B) = +0.4
#   φ⁺(C) = (0.0 + 0.0)/2 = 0.0   φ⁻(C) = (1.0 + 1.0)/2 = 1.0   φ(C) = −1.0


class TestValeursManquantes:
    @pytest.fixture
    def moteur(self) -> PrometheeII:
        criteres = [Critere("g1", "max", Usuelle()), Critere("g2", "max", Usuelle())]
        return PrometheeII(criteres, poids={"g1": 0.6, "g2": 0.4})

    def test_renormalisation_par_paire(self, moteur: PrometheeII):
        """None sur g2 pour C : la paire (·, C) ne pèse que sur g1, renormalisé à 1."""
        res = moteur.classer(
            {
                "A": {"g1": 0.8, "g2": 0.1},
                "B": {"g1": 0.5, "g2": 0.4},
                "C": {"g1": 0.2, "g2": None},
            }
        )
        assert res.phi_plus["A"] == pytest.approx(0.8, abs=1e-12)
        assert res.phi_moins["A"] == pytest.approx(0.2, abs=1e-12)
        assert res.phi["A"] == pytest.approx(0.6, abs=1e-12)
        assert res.phi["B"] == pytest.approx(0.4, abs=1e-12)
        assert res.phi["C"] == pytest.approx(-1.0, abs=1e-12)
        # Σφ = 0 même avec des valeurs manquantes.
        assert sum(res.phi.values()) == pytest.approx(0.0, abs=1e-12)
        assert res.classement == ["A", "B", "C"]

    def test_cle_absente_equivaut_a_none(self, moteur: PrometheeII):
        """Une clé absente du dict de valeurs est traitée comme None."""
        avec_none = moteur.classer(
            {
                "A": {"g1": 0.8, "g2": 0.1},
                "B": {"g1": 0.5, "g2": 0.4},
                "C": {"g1": 0.2, "g2": None},
            }
        )
        sans_cle = moteur.classer(
            {
                "A": {"g1": 0.8, "g2": 0.1},
                "B": {"g1": 0.5, "g2": 0.4},
                "C": {"g1": 0.2},
            }
        )
        assert sans_cle.phi == avec_none.phi

    def test_aucun_critere_present_pi_nul(self, moteur: PrometheeII):
        """Paire sans aucun critère présent : π = 0 dans les deux sens, φ = 0."""
        res = moteur.classer(
            {
                "A": {"g1": None, "g2": None},
                "B": {"g1": 0.9, "g2": 0.9},
            }
        )
        assert res.phi == {"A": 0.0, "B": 0.0}
        assert res.phi_plus == {"A": 0.0, "B": 0.0}
        assert res.phi_moins == {"A": 0.0, "B": 0.0}
        # Départage à φ égal : identifiant croissant.
        assert res.classement == ["A", "B"]


# ---------------------------------------------------------------------------
# Cas dégénérés et erreurs
# ---------------------------------------------------------------------------


class TestCasDegeneresEtErreurs:
    def test_une_seule_alternative_flux_nuls(self):
        """n == 1 : φ = φ⁺ = φ⁻ = 0 (aucune paire à comparer)."""
        moteur = PrometheeII([Critere("g1", "max", Usuelle())], {"g1": 1.0})
        res = moteur.classer({"seul": {"g1": 0.5}})
        assert res.phi == {"seul": 0.0}
        assert res.phi_plus == {"seul": 0.0}
        assert res.phi_moins == {"seul": 0.0}
        assert res.classement == ["seul"]

    def test_valeurs_vides_value_error(self):
        moteur = PrometheeII([Critere("g1", "max", Usuelle())], {"g1": 1.0})
        with pytest.raises(ValueError, match="aucune alternative"):
            moteur.classer({})

    def test_critere_sans_poids_value_error(self):
        criteres = [Critere("g1", "max", Usuelle()), Critere("g2", "max", Usuelle())]
        with pytest.raises(ValueError, match="sans poids"):
            PrometheeII(criteres, poids={"g1": 1.0})

    def test_poids_non_positif_value_error(self):
        with pytest.raises(ValueError, match="strictement positifs"):
            PrometheeII([Critere("g1", "max", Usuelle())], poids={"g1": 0.0})
        with pytest.raises(ValueError, match="strictement positifs"):
            PrometheeII([Critere("g1", "max", Usuelle())], poids={"g1": -2.0})

    def test_liste_de_criteres_vide_value_error(self):
        with pytest.raises(ValueError, match="au moins un critère"):
            PrometheeII([], poids={})

    def test_noms_de_criteres_dupliques_value_error(self):
        criteres = [Critere("g1", "max", Usuelle()), Critere("g1", "min", Usuelle())]
        with pytest.raises(ValueError, match="dupliqués"):
            PrometheeII(criteres, poids={"g1": 1.0})

    def test_egalite_parfaite_departage_par_id(self):
        """Alternatives identiques : φ = 0 partout, classement par id croissant."""
        moteur = PrometheeII([Critere("g1", "max", Usuelle())], {"g1": 1.0})
        res = moteur.classer({"z": {"g1": 0.5}, "a": {"g1": 0.5}, "m": {"g1": 0.5}})
        assert res.classement == ["a", "m", "z"]
        assert all(v == 0.0 for v in res.phi.values())
