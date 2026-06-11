"""PROMETHEE II — classement multicritère complet (Brans & Vincke) — phase E12, Lot 12.1.

Le classement repose sur des comparaisons par paires : pour chaque couple
d'alternatives (a, b) et chaque critère j, l'écart orienté « max »
``d_j(a, b)`` est transformé en préférence ``P_j(d) ∈ [0, 1]`` par l'une des
six fonctions de préférence de Brans–Vincke. L'indice de préférence agrégé
``π(a, b) = Σ_j w_j · P_j(d_j(a, b))`` alimente les flux :

    φ⁺(a) = 1/(n−1) · Σ_{b≠a} π(a, b)      (flux sortant — force de a)
    φ⁻(a) = 1/(n−1) · Σ_{b≠a} π(b, a)      (flux entrant — faiblesse de a)
    φ(a)  = φ⁺(a) − φ⁻(a)                  (flux net, classement complet)

Règle des valeurs manquantes (mot pour mot, PLAN.md E12) : pour chaque paire
(a, b) et critère j où l'une des deux valeurs est ``None``, ``P_j = 0`` dans
les deux sens et les poids sont renormalisés sur les critères présents pour
CETTE paire (si aucun critère présent : ``π(a, b) = π(b, a) = 0``).

Limite connue (documentée) : PROMETHEE II n'est pas indépendant des
alternatives non concernées — ajouter une alternative PEUT inverser le rang
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


# ---------------------------------------------------------------------------
# Fonctions de préférence (les six types de Brans–Vincke)
# ---------------------------------------------------------------------------


class FonctionPreference(ABC):
    """Fonction de préférence ``P(d) ∈ [0, 1]`` sur l'écart orienté « max ».

    L'écart ``d = g(a) − g(b)`` est supposé déjà orienté « max » : un ``d``
    positif signifie que l'alternative a est meilleure que b sur le critère.
    Toutes les implémentations sont croissantes (au sens large) en ``d`` et
    valent 0 pour ``d <= 0``.
    """

    @abstractmethod
    def __call__(self, d: float) -> float:
        """Renvoie la préférence ``P(d) ∈ [0, 1]`` pour l'écart orienté ``d``."""


class Usuelle(FonctionPreference):
    """Type I — critère usuel : ``P(d) = 1`` si ``d > 0``, sinon 0."""

    def __call__(self, d: float) -> float:
        """Préférence stricte dès le moindre écart positif."""
        return 1.0 if d > 0.0 else 0.0


class UShape(FonctionPreference):
    """Type II — quasi-critère (seuil d'indifférence q) : ``P = 1`` si ``d > q``, sinon 0."""

    def __init__(self, q: float) -> None:
        """Initialise le quasi-critère.

        Args:
            q: seuil d'indifférence (>= 0) : aucun écart ``d <= q`` ne compte.

        Raises:
            ValueError: si ``q < 0``.
        """
        if q < 0.0:
            raise ValueError(f"UShape : seuil d'indifférence q >= 0 exigé (reçu q={q}).")
        self.q = q

    def __call__(self, d: float) -> float:
        """Préférence binaire au-delà du seuil d'indifférence q."""
        return 1.0 if d > self.q else 0.0


class VShape(FonctionPreference):
    """Type III — préférence linéaire : ``P = min(d/p, 1)`` si ``d > 0``, sinon 0."""

    def __init__(self, p: float) -> None:
        """Initialise la préférence linéaire.

        Args:
            p: seuil de préférence stricte (> 0) : ``P = 1`` dès ``d >= p``.

        Raises:
            ValueError: si ``p <= 0``.
        """
        if p <= 0.0:
            raise ValueError(f"VShape : seuil de préférence p > 0 exigé (reçu p={p}).")
        self.p = p

    def __call__(self, d: float) -> float:
        """Préférence proportionnelle à l'écart, saturée à 1 en ``d = p``."""
        if d <= 0.0:
            return 0.0
        return min(d / self.p, 1.0)


class Palier(FonctionPreference):
    """Type IV — critère à paliers : 0 si ``d <= q`` ; 0.5 si ``q < d <= p`` ; 1 si ``d > p``."""

    def __init__(self, q: float, p: float) -> None:
        """Initialise le critère à paliers.

        Args:
            q: seuil d'indifférence (>= 0).
            p: seuil de préférence stricte (``p > q`` exigé).

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
        """Préférence en trois paliers 0 / 0.5 / 1 selon q et p."""
        if d <= self.q:
            return 0.0
        if d <= self.p:
            return 0.5
        return 1.0


class LineaireIndifference(FonctionPreference):
    """Type V (DÉFAUT) — linéaire avec zone d'indifférence.

    ``P = 0`` si ``d <= q`` ; ``(d − q)/(p − q)`` si ``q < d <= p`` ; 1 si
    ``d > p``. Défauts ``q = 0.05`` et ``p = 0.30``, calibrés pour des
    critères à valeurs dans [0, 1].
    """

    def __init__(self, q: float = 0.05, p: float = 0.30) -> None:
        """Initialise la préférence linéaire avec indifférence.

        Args:
            q: seuil d'indifférence (>= 0).
            p: seuil de préférence stricte (``p > q`` exigé).

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
        """Préférence nulle jusqu'à q, linéaire de q à p, totale au-delà de p."""
        if d <= self.q:
            return 0.0
        if d <= self.p:
            return (d - self.q) / (self.p - self.q)
        return 1.0


class Gaussienne(FonctionPreference):
    """Type VI — gaussienne : ``P = 1 − exp(−d²/(2s²))`` si ``d > 0``, sinon 0."""

    def __init__(self, s: float) -> None:
        """Initialise la préférence gaussienne.

        Args:
            s: paramètre d'échelle (> 0), point d'inflexion de la courbe.

        Raises:
            ValueError: si ``s <= 0``.
        """
        if s <= 0.0:
            raise ValueError(f"Gaussienne : paramètre d'échelle s > 0 exigé (reçu s={s}).")
        self.s = s

    def __call__(self, d: float) -> float:
        """Préférence en S progressif, sans saturation exacte à 1."""
        if d <= 0.0:
            return 0.0
        return 1.0 - math.exp(-(d * d) / (2.0 * self.s * self.s))


# ---------------------------------------------------------------------------
# Critère, résultat et moteur PROMETHEE II
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Critere:
    """Critère d'évaluation PROMETHEE.

    Attributes:
        nom: identifiant du critère (clé des poids et des valeurs).
        sens: ``"max"`` (plus grand = mieux) ou ``"min"`` (plus petit = mieux) ;
            en sens ``"min"``, l'écart est inversé (``d = g(b) − g(a)``).
        fonction: fonction de préférence appliquée à l'écart orienté
            (défaut : :class:`LineaireIndifference` avec q=0.05, p=0.30).
    """

    nom: str
    sens: Literal["max", "min"]
    fonction: FonctionPreference = field(default_factory=LineaireIndifference)


@dataclass(frozen=True)
class ResultatPromethee:
    """Flux PROMETHEE II et classement complet des alternatives.

    Attributes:
        phi: flux net ``φ = φ⁺ − φ⁻`` par identifiant d'alternative.
        phi_plus: flux sortant ``φ⁺`` par identifiant d'alternative.
        phi_moins: flux entrant ``φ⁻`` par identifiant d'alternative.
        classement: identifiants triés par ``φ`` décroissant
            (départage : identifiant croissant).
    """

    phi: dict[str, float]
    phi_plus: dict[str, float]
    phi_moins: dict[str, float]
    classement: list[str]


class PrometheeII:
    """Moteur de classement PROMETHEE II (flux nets complets).

    Les poids sont fournis par nom de critère, strictement positifs, et
    renormalisés à somme 1 à la construction. La renormalisation par paire
    (valeurs manquantes) s'applique ensuite au moment du classement.
    """

    def __init__(self, criteres: list[Critere], poids: dict[str, float]) -> None:
        """Initialise le moteur avec ses critères et leurs poids.

        Args:
            criteres: critères d'évaluation (au moins un, noms uniques).
            poids: poids par nom de critère, strictement positifs ; ils sont
                renormalisés à somme 1 (les poids non normalisés sont acceptés).

        Raises:
            ValueError: si la liste de critères est vide, si un nom de critère
                est dupliqué, si un critère n'a pas de poids, ou si un poids
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
        #: Poids renormalisés à somme 1, restreints aux critères déclarés.
        self._poids: dict[str, float] = {n: poids[n] / total for n in noms}

    @property
    def poids(self) -> dict[str, float]:
        """Poids renormalisés (somme 1) par nom de critère (copie défensive)."""
        return dict(self._poids)

    def _pi(
        self,
        valeurs_a: dict[str, float | None],
        valeurs_b: dict[str, float | None],
    ) -> float:
        """Indice de préférence agrégé ``π(a, b)`` pour une paire ordonnée.

        Règle des valeurs manquantes : un critère dont l'une des deux valeurs
        est ``None`` (ou absente) est exclu, et les poids sont renormalisés
        sur les critères présents pour cette paire. Si aucun critère n'est
        présent, ``π = 0``.

        Args:
            valeurs_a: valeurs de l'alternative a par nom de critère.
            valeurs_b: valeurs de l'alternative b par nom de critère.

        Returns:
            ``π(a, b) ∈ [0, 1]``.
        """
        contributions: list[tuple[float, float]] = []  # (poids, préférence)
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
        """Classe les alternatives par flux net décroissant.

        Args:
            valeurs: ``valeurs[alt_id][critere_nom]`` ; ``None`` (ou clé
                absente) signifie « valeur manquante » pour ce critère.

        Returns:
            :class:`ResultatPromethee` avec ``φ``, ``φ⁺``, ``φ⁻`` et le
            classement (φ décroissant, départage par identifiant croissant).
            Cas dégénéré ``n == 1`` : ``φ = φ⁺ = φ⁻ = 0``.

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
