"""PROMETHEE II - classement multicritere complet (Brans & Vincke) - phase E12, Lot 12.1.

Le classement repose sur des comparaisons par paires : pour chaque couple
d'alternatives (a, b) et chaque critere j, l'ecart oriente " max "
``d_j(a, b)`` est transforme en preference ``P_j(d)  dans  [0, 1]`` par l'une des
six fonctions de preference de Brans-Vincke. L'indice de preference agrege
``pi(a, b) = Sigma_j w_j - P_j(d_j(a, b))`` alimente les flux :

    phi^+(a) = 1/(n-1) - Sigma_{b!=a} pi(a, b)      (flux sortant - force de a)
    phi^-(a) = 1/(n-1) - Sigma_{b!=a} pi(b, a)      (flux entrant - faiblesse de a)
    phi(a)  = phi^+(a) - phi^-(a)                  (flux net, classement complet)

Regle des valeurs manquantes (mot pour mot, PLAN.md E12) : pour chaque paire
(a, b) et critere j ou l'une des deux valeurs est ``None``, ``P_j = 0`` dans
les deux sens et les poids sont renormalises sur les criteres presents pour
CETTE paire (si aucun critere present : ``pi(a, b) = pi(b, a) = 0``).

Limite connue (documentee) : PROMETHEE II n'est pas independant des
alternatives non concernees - ajouter une alternative PEUT inverser le rang
de deux alternatives existantes (renversement de rang). Voir
``docs/modele_mathematique.md`` et le test descriptif de
``tests/property/test_prop_promethee.py``.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "Critere",
    "FonctionPreference",
    "Gaussienne",
    "LineaireIndifference",
    "Palier",
    "PrometheeII",
    "ResultatPromethee",
    "UShape",
    "Usuelle",
    "VShape",
]


# Fonctions de preference (les six types de Brans-Vincke)


class FonctionPreference(ABC):
    """Fonction de preference ``P(d)  dans  [0, 1]`` sur l'ecart oriente " max ".

    L'ecart ``d = g(a) - g(b)`` est suppose deja oriente " max " : un ``d``
    positif signifie que l'alternative a est meilleure que b sur le critere.
    Toutes les implementations sont croissantes (au sens large) en ``d`` et
    valent 0 pour ``d <= 0``.
    """

    @abstractmethod
    def __call__(self, d: float) -> float:
        """Renvoie la preference ``P(d)  dans  [0, 1]`` pour l'ecart oriente ``d``."""


class Usuelle(FonctionPreference):
    """Type I - critere usuel : ``P(d) = 1`` si ``d > 0``, sinon 0."""

    def __call__(self, d: float) -> float:
        """Preference stricte des le moindre ecart positif."""
        return 1.0 if d > 0.0 else 0.0


class UShape(FonctionPreference):
    """Type II - quasi-critere (seuil d'indifference q) : ``P = 1`` si ``d > q``, sinon 0."""

    def __init__(self, q: float) -> None:
        """Initialise le quasi-critere.

        Args:
            q: seuil d'indifference (>= 0) : aucun ecart ``d <= q`` ne compte.

        Raises:
            ValueError: si ``q < 0``.
        """
        if q < 0.0:
            raise ValueError(f"UShape : seuil d'indifférence q >= 0 exigé (reçu q={q}).")
        self.q = q

    def __call__(self, d: float) -> float:
        """Preference binaire au-dela du seuil d'indifference q."""
        return 1.0 if d > self.q else 0.0


class VShape(FonctionPreference):
    """Type III - preference lineaire : ``P = min(d/p, 1)`` si ``d > 0``, sinon 0."""

    def __init__(self, p: float) -> None:
        """Initialise la preference lineaire.

        Args:
            p: seuil de preference stricte (> 0) : ``P = 1`` des ``d >= p``.

        Raises:
            ValueError: si ``p <= 0``.
        """
        if p <= 0.0:
            raise ValueError(f"VShape : seuil de préférence p > 0 exigé (reçu p={p}).")
        self.p = p

    def __call__(self, d: float) -> float:
        """Preference proportionnelle a l'ecart, saturee a 1 en ``d = p``."""
        if d <= 0.0:
            return 0.0
        return min(d / self.p, 1.0)


class Palier(FonctionPreference):
    """Type IV - critere a paliers : 0 si ``d <= q`` ; 0.5 si ``q < d <= p`` ; 1 si ``d > p``."""

    def __init__(self, q: float, p: float) -> None:
        """Initialise le critere a paliers.

        Args:
            q: seuil d'indifference (>= 0).
            p: seuil de preference stricte (``p > q`` exige).

        Raises:
            ValueError: si ``q < 0`` ou ``p <= q``.
        """
        if q < 0.0:
            raise ValueError(f"Palier : seuil d'indifférence q >= 0 exigé (reçu q={q}).")
        if p <= q:
            raise ValueError(f"Palier : p > q exigé (reçu q={q}, p={p}).")
        self.q = q
        self.p = p

    def __call__(self, d: float) -> float:
        """Preference en trois paliers 0 / 0.5 / 1 selon q et p."""
        if d <= self.q:
            return 0.0
        if d <= self.p:
            return 0.5
        return 1.0


class LineaireIndifference(FonctionPreference):
    """Type V (DEFAUT) - lineaire avec zone d'indifference.

    ``P = 0`` si ``d <= q`` ; ``(d - q)/(p - q)`` si ``q < d <= p`` ; 1 si
    ``d > p``. Defauts ``q = 0.05`` et ``p = 0.30``, calibres pour des
    criteres a valeurs dans [0, 1].
    """

    def __init__(self, q: float = 0.05, p: float = 0.30) -> None:
        """Initialise la preference lineaire avec indifference.

        Args:
            q: seuil d'indifference (>= 0).
            p: seuil de preference stricte (``p > q`` exige).

        Raises:
            ValueError: si ``q < 0`` ou ``p <= q``.
        """
        if q < 0.0:
            raise ValueError(
                f"LineaireIndifference : seuil d'indifférence q >= 0 exigé (reçu q={q})."
            )
        if p <= q:
            raise ValueError(f"LineaireIndifference : p > q exigé (reçu q={q}, p={p}).")
        self.q = q
        self.p = p

    def __call__(self, d: float) -> float:
        """Preference nulle jusqu'a q, lineaire de q a p, totale au-dela de p."""
        if d <= self.q:
            return 0.0
        if d <= self.p:
            return (d - self.q) / (self.p - self.q)
        return 1.0


class Gaussienne(FonctionPreference):
    """Type VI - gaussienne : ``P = 1 - exp(-d^2/(2s^2))`` si ``d > 0``, sinon 0."""

    def __init__(self, s: float) -> None:
        """Initialise la preference gaussienne.

        Args:
            s: parametre d'echelle (> 0), point d'inflexion de la courbe.

        Raises:
            ValueError: si ``s <= 0``.
        """
        if s <= 0.0:
            raise ValueError(f"Gaussienne : paramètre d'échelle s > 0 exigé (reçu s={s}).")
        self.s = s

    def __call__(self, d: float) -> float:
        """Preference en S progressif, sans saturation exacte a 1."""
        if d <= 0.0:
            return 0.0
        return 1.0 - math.exp(-(d * d) / (2.0 * self.s * self.s))


# Critere, resultat et moteur PROMETHEE II


@dataclass(frozen=True)
class Critere:
    """Critere d'evaluation PROMETHEE.

    Attributes:
        nom: identifiant du critere (cle des poids et des valeurs).
        sens: ``"max"`` (plus grand = mieux) ou ``"min"`` (plus petit = mieux) ;
            en sens ``"min"``, l'ecart est inverse (``d = g(b) - g(a)``).
        fonction: fonction de preference appliquee a l'ecart oriente
            (defaut : :class:`LineaireIndifference` avec q=0.05, p=0.30).
    """

    nom: str
    sens: Literal["max", "min"]
    fonction: FonctionPreference = field(default_factory=LineaireIndifference)


@dataclass(frozen=True)
class ResultatPromethee:
    """Flux PROMETHEE II et classement complet des alternatives.

    Attributes:
        phi: flux net ``phi = phi^+ - phi^-`` par identifiant d'alternative.
        phi_plus: flux sortant ``phi^+`` par identifiant d'alternative.
        phi_moins: flux entrant ``phi^-`` par identifiant d'alternative.
        classement: identifiants tries par ``phi`` decroissant
            (departage : identifiant croissant).
    """

    phi: dict[str, float]
    phi_plus: dict[str, float]
    phi_moins: dict[str, float]
    classement: list[str]


class PrometheeII:
    """Moteur de classement PROMETHEE II (flux nets complets).

    Les poids sont fournis par nom de critere, strictement positifs, et
    renormalises a somme 1 a la construction. La renormalisation par paire
    (valeurs manquantes) s'applique ensuite au moment du classement.
    """

    def __init__(self, criteres: list[Critere], poids: dict[str, float]) -> None:
        """Initialise le moteur avec ses criteres et leurs poids.

        Args:
            criteres: criteres d'evaluation (au moins un, noms uniques).
            poids: poids par nom de critere, strictement positifs ; ils sont
                renormalises a somme 1 (les poids non normalises sont acceptes).

        Raises:
            ValueError: si la liste de criteres est vide, si un nom de critere
                est duplique, si un critere n'a pas de poids, ou si un poids
                est <= 0.
        """
        if not criteres:
            raise ValueError("PrometheeII : au moins un critère est requis.")
        noms = [c.nom for c in criteres]
        if len(set(noms)) != len(noms):
            doublons = sorted({n for n in noms if noms.count(n) > 1})
            raise ValueError(f"PrometheeII : noms de critères dupliqués : {doublons}.")
        manquants = [n for n in noms if n not in poids]
        if manquants:
            raise ValueError(f"PrometheeII : critère(s) sans poids : {manquants}.")
        invalides = {n: poids[n] for n in noms if poids[n] <= 0.0}
        if invalides:
            raise ValueError(f"PrometheeII : poids strictement positifs exigés : {invalides}.")
        total = sum(poids[n] for n in noms)
        self._criteres: list[Critere] = list(criteres)
        #: Poids renormalises a somme 1, restreints aux criteres declares.
        self._poids: dict[str, float] = {n: poids[n] / total for n in noms}

    @property
    def poids(self) -> dict[str, float]:
        """Poids renormalises (somme 1) par nom de critere (copie defensive)."""
        return dict(self._poids)

    def _pi(
        self,
        valeurs_a: dict[str, float | None],
        valeurs_b: dict[str, float | None],
    ) -> float:
        """Indice de preference agrege ``pi(a, b)`` pour une paire ordonnee.

        Regle des valeurs manquantes : un critere dont l'une des deux valeurs
        est ``None`` (ou absente) est exclu, et les poids sont renormalises
        sur les criteres presents pour cette paire. Si aucun critere n'est
        present, ``pi = 0``.

        Args:
            valeurs_a: valeurs de l'alternative a par nom de critere.
            valeurs_b: valeurs de l'alternative b par nom de critere.

        Returns:
            ``pi(a, b)  dans  [0, 1]``.
        """
        contributions: list[tuple[float, float]] = []  # (poids, preference)
        for critere in self._criteres:
            g_a = valeurs_a.get(critere.nom)
            g_b = valeurs_b.get(critere.nom)
            if g_a is None or g_b is None:
                continue
            d = g_a - g_b if critere.sens == "max" else g_b - g_a
            contributions.append((self._poids[critere.nom], critere.fonction(d)))
        poids_present = sum(w for w, _ in contributions)
        if poids_present <= 0.0:
            return 0.0
        return sum(w * p for w, p in contributions) / poids_present

    def classer(self, valeurs: dict[str, dict[str, float | None]]) -> ResultatPromethee:
        """Classe les alternatives par flux net decroissant.

        Args:
            valeurs: ``valeurs[alt_id][critere_nom]`` ; ``None`` (ou cle
                absente) signifie " valeur manquante " pour ce critere.

        Returns:
            :class:`ResultatPromethee` avec ``phi``, ``phi^+``, ``phi^-`` et le
            classement (phi decroissant, departage par identifiant croissant).
            Cas degenere ``n == 1`` : ``phi = phi^+ = phi^- = 0``.

        Raises:
            ValueError: si ``valeurs`` est vide.
        """
        if not valeurs:
            raise ValueError("PrometheeII.classer : aucune alternative fournie.")
        ids = sorted(valeurs)
        n = len(ids)
        if n == 1:
            seul = ids[0]
            return ResultatPromethee(
                phi={seul: 0.0},
                phi_plus={seul: 0.0},
                phi_moins={seul: 0.0},
                classement=[seul],
            )
        phi_plus = dict.fromkeys(ids, 0.0)
        phi_moins = dict.fromkeys(ids, 0.0)
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                pi_ab = self._pi(valeurs[a], valeurs[b])
                pi_ba = self._pi(valeurs[b], valeurs[a])
                phi_plus[a] += pi_ab
                phi_moins[b] += pi_ab
                phi_plus[b] += pi_ba
                phi_moins[a] += pi_ba
        facteur = 1.0 / (n - 1)
        phi_plus = {alt: facteur * v for alt, v in phi_plus.items()}
        phi_moins = {alt: facteur * v for alt, v in phi_moins.items()}
        phi = {alt: phi_plus[alt] - phi_moins[alt] for alt in ids}
        classement = sorted(ids, key=lambda alt: (-phi[alt], alt))
        return ResultatPromethee(
            phi=phi,
            phi_plus=phi_plus,
            phi_moins=phi_moins,
            classement=classement,
        )
