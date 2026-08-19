"""Proprietes mathematiques de PROMETHEE II - phase E12, Lot 12.1.

Invariants Hypothesis sur des instances aleatoires (avec valeurs manquantes) :
Sigmaphi = 0, phi  dans  [-1, 1], monotonie en amelioration sur un critere " max ",
invariance par translation d'un critere, coherence du classement. Plus un
test DESCRIPTIF (non-invariant) du renversement de rang.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.mcda import (
    Critere,
    Gaussienne,
    LineaireIndifference,
    Palier,
    PrometheeII,
    UShape,
    Usuelle,
    VShape,
)

# Strategies

#: Noms de criteres disponibles (jusqu'a 4 par instance).
_NOMS: list[str] = ["u_time", "u_cap", "u_risk", "u_cost"]

#: Une instance de chaque type de fonction de preference (toutes sans etat).
_FONCTIONS = st.sampled_from(
    [
        Usuelle(),
        UShape(q=0.1),
        VShape(p=0.4),
        Palier(q=0.05, p=0.25),
        LineaireIndifference(),
        Gaussienne(s=0.2),
    ]
)

#: Valeur de critere : manquante (None) ou dans [0, 1].
_VALEUR = st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0))

#: Grille exacte en binaire (multiples de 2^-^6) pour le test de translation.
_GRILLE = st.one_of(st.none(), st.sampled_from([k / 64.0 for k in range(65)]))


@st.composite
def _instances(draw, valeur=_VALEUR):
    """(criteres, poids, valeurs) aleatoires : 1-4 criteres, 2-6 alternatives."""
    noms = _NOMS[: draw(st.integers(min_value=1, max_value=4))]
    criteres = [
        Critere(nom, draw(st.sampled_from(("max", "min"))), draw(_FONCTIONS)) for nom in noms
    ]
    poids = {nom: draw(st.floats(min_value=0.1, max_value=10.0)) for nom in noms}
    ids = [f"n{i}" for i in range(draw(st.integers(min_value=2, max_value=6)))]
    valeurs = {alt: {nom: draw(valeur) for nom in noms} for alt in ids}
    return criteres, poids, valeurs


@st.composite
def _instances_amelioration(draw):
    """Instance + (alternative cible, critere " max " renseigne, delta >= 0)."""
    criteres, poids, valeurs = draw(_instances())
    # Le premier critere est force en " max " : c'est lui qu'on ameliore.
    criteres[0] = Critere(criteres[0].nom, "max", criteres[0].fonction)
    cible = draw(st.sampled_from(sorted(valeurs)))
    if valeurs[cible][criteres[0].nom] is None:
        valeurs[cible][criteres[0].nom] = draw(st.floats(min_value=0.0, max_value=1.0))
    delta = draw(st.floats(min_value=0.0, max_value=1.0))
    return criteres, poids, valeurs, cible, criteres[0].nom, delta


@st.composite
def _instances_translation(draw):
    """Instance sur grille exacte + (critere a translater, t multiple de 2^-^6)."""
    criteres, poids, valeurs = draw(_instances(valeur=_GRILLE))
    nom = draw(st.sampled_from([c.nom for c in criteres]))
    t = draw(st.integers(min_value=-640, max_value=640)) / 64.0
    return criteres, poids, valeurs, nom, t


# Invariants


class TestInvariantsFlux:
    @given(case=_instances())
    def test_somme_des_phi_nulle(self, case):
        """Sigma_a phi(a) == 0 (1e-9) TOUJOURS, y compris avec des valeurs manquantes.

        Chaque pi(a, b) contribue symetriquement a phi^+(a) et a phi^-(b) : la somme
        des flux nets est structurellement nulle, aux arrondis flottants pres.
        """
        criteres, poids, valeurs = case
        res = PrometheeII(criteres, poids).classer(valeurs)
        assert sum(res.phi.values()) == pytest.approx(0.0, abs=1e-9)

    @given(case=_instances())
    def test_phi_borne_entre_moins_un_et_un(self, case):
        """phi  dans  [-1, 1] : phi^+ et phi^- sont des moyennes de pi  dans  [0, 1]."""
        criteres, poids, valeurs = case
        res = PrometheeII(criteres, poids).classer(valeurs)
        for alt, phi in res.phi.items():
            assert -1.0 - 1e-12 <= phi <= 1.0 + 1e-12
            assert -1e-12 <= res.phi_plus[alt] <= 1.0 + 1e-12
            assert -1e-12 <= res.phi_moins[alt] <= 1.0 + 1e-12

    @given(case=_instances())
    def test_classement_coherent_avec_phi(self, case):
        """Le classement est une permutation des ids triee par (-phi, id)."""
        criteres, poids, valeurs = case
        res = PrometheeII(criteres, poids).classer(valeurs)
        assert sorted(res.classement) == sorted(valeurs)
        cles = [(-res.phi[alt], alt) for alt in res.classement]
        assert cles == sorted(cles)


class TestMonotonie:
    @given(case=_instances_amelioration())
    def test_ameliorer_un_critere_max_ne_diminue_jamais_phi(self, case):
        """Augmenter g_j(a) de delta >= 0 sur un critere " max " n'abaisse jamais phi(a).

        Toutes les fonctions de preference sont croissantes (au sens large) en
        l'ecart d : chaque pi(a, -) ne peut que croitre et chaque pi(-, a) que
        decroitre. Marge 1e-12 : sommes flottantes evaluees independamment.
        """
        criteres, poids, valeurs, cible, nom, delta = case
        moteur = PrometheeII(criteres, poids)
        avant = moteur.classer(valeurs).phi[cible]
        ameliorees = {alt: dict(v) for alt, v in valeurs.items()}
        base = ameliorees[cible][nom]
        assert base is not None  # garanti par la strategie
        ameliorees[cible][nom] = base + delta
        apres = moteur.classer(ameliorees).phi[cible]
        assert apres >= avant - 1e-12


class TestInvarianceTranslation:
    @given(case=_instances_translation())
    def test_translation_simultanee_d_un_critere(self, case):
        """Translater toutes les valeurs d'un critere de t laisse les flux inchanges.

        Les fonctions de preference ne dependent que des ecarts
        d = g(a) - g(b) : translater simultanement toutes les valeurs d'un
        critere ne change aucun ecart. Les valeurs et t sont tires sur une
        grille de multiples de 2^-^6 (exactement representables en binaire),
        de sorte que (x + t) - (y + t) == x - y EXACTEMENT - sans quoi un
        arrondi de 1 ulp pres d'un seuil (d > 0, d > q...) pourrait faire
        basculer une fonction discontinue et fausser le test.
        """
        criteres, poids, valeurs, nom, t = case
        moteur = PrometheeII(criteres, poids)
        avant = moteur.classer(valeurs)
        translatees = {
            alt: {n: (v + t if n == nom and v is not None else v) for n, v in vals.items()}
            for alt, vals in valeurs.items()
        }
        apres = moteur.classer(translatees)
        for alt in valeurs:
            assert apres.phi[alt] == pytest.approx(avant.phi[alt], abs=1e-12)
            assert apres.phi_plus[alt] == pytest.approx(avant.phi_plus[alt], abs=1e-12)
            assert apres.phi_moins[alt] == pytest.approx(avant.phi_moins[alt], abs=1e-12)
        assert apres.classement == avant.classement


# Renversement de rang - test DESCRIPTIF (non-invariant)


class TestRenversementDeRang:
    def test_ajouter_une_alternative_peut_inverser_deux_rangs(self):
        """DESCRIPTIF : ajouter une alternative PEUT inverser deux rangs existants.

        PROMETHEE II n'est PAS independant des alternatives non concernees :
        le flux net phi agrege les comparaisons avec TOUTES les alternatives, si
        bien qu'une nouvelle venue D, sans rapport avec le duel A/B, peut
        redistribuer les flux et inverser leur ordre. C'est une limite connue
        de la methode (Brans & Vincke ; cf. ``docs/modele_mathematique.md``),
        documentee ici par un exemple concret - ce test montre que le
        phenomene EXISTE, ce n'est pas un invariant a preserver.

        Exemple (2 criteres " max ", Usuelle, poids 0.6/0.4) :
        - Sans D : phi(A) = +0.2 > phi(B) = 0.0  ->  A devant B.
        - D (g1=0.0, g2=0.25) perd g1 contre tous, mais bat A (et seulement A)
          sur g2 : pi(A,D) = 0.6, pi(D,A) = 0.4 alors que pi(B,D) = 1.0,
          pi(D,B) = 0. Avec D : phi(A) = 0.2 < phi(B) = (-0.2 + 0.2 + 1.0)/3 = 1/3
          ->  B passe devant A : renversement de rang.
        """
        criteres = [Critere("g1", "max", Usuelle()), Critere("g2", "max", Usuelle())]
        moteur = PrometheeII(criteres, poids={"g1": 0.6, "g2": 0.4})
        sans_d: dict[str, dict[str, float | None]] = {
            "A": {"g1": 0.8, "g2": 0.1},
            "B": {"g1": 0.5, "g2": 0.4},
            "C": {"g1": 0.2, "g2": 0.7},
        }
        avant = moteur.classer(sans_d)
        assert avant.classement.index("A") < avant.classement.index("B")
        assert avant.phi["A"] == pytest.approx(0.2, abs=1e-12)
        assert avant.phi["B"] == pytest.approx(0.0, abs=1e-12)

        avec_d = dict(sans_d)
        avec_d["D"] = {"g1": 0.0, "g2": 0.25}
        apres = moteur.classer(avec_d)
        assert apres.phi["A"] == pytest.approx(0.2, abs=1e-12)
        assert apres.phi["B"] == pytest.approx(1.0 / 3.0, abs=1e-12)
        # Renversement : B passe devant A alors qu'aucune valeur de A ni de B n'a change.
        assert apres.classement.index("B") < apres.classement.index("A")
