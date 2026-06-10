"""Score d'adéquation A ∈ [0, 100] entre urgence déclarée Ud et réelle Ur.

L'adéquation mesure l'alignement entre la perception humaine (Ud) et la
réalité opérationnelle (Ur). Deux pathologies sont distinguées :

- **Fausse urgence** F = [Ud − Ur]+ : panique injustifiée (sur-déclaration) ;
- **Risque caché** H = [Ur − Ud]+ : danger invisible (sous-déclaration).

Règle de gouvernance : ``lambda_under > lambda_over`` — le danger invisible
est pire que la panique. Une équipe qui sur-réagit gaspille des ressources ;
une équipe qui sous-estime découvre la rupture quand il est trop tard.
Le défaut 2.25 vs 1.0 reprend le coefficient d'aversion à la perte mesuré
par Kahneman & Tversky (Prospect Theory, 1992).
"""

from __future__ import annotations

import math

from supplyscore.domain.models import UrgencyState


def _clip(x: float, lo: float, hi: float) -> float:
    """Borne une valeur sur [lo, hi]."""
    return min(max(x, lo), hi)


class AdequationEngine:
    """Moteur de calcul du score d'adéquation Ud/Ur.

    Attributes:
        lambda_under: pénalité de sous-estimation (Ur > Ud), > 0.
            Doit rester > ``lambda_over`` (le danger invisible est pire
            que la panique).
        lambda_over: pénalité de surestimation (Ud > Ur), > 0.
        alpha: courbure psychophysique de la fonction de valeur
            (Prospect Theory), dans (0, 1].
    """

    def __init__(
        self,
        lambda_under: float = 2.25,
        lambda_over: float = 1.0,
        alpha: float = 0.88,
    ) -> None:
        """Initialise le moteur avec les paramètres de pénalité asymétrique.

        Raises:
            ValueError: si un lambda est <= 0 ou si alpha sort de (0, 1].
        """
        self._validate(lambda_under, lambda_over, alpha)
        self.lambda_under = lambda_under
        self.lambda_over = lambda_over
        self.alpha = alpha

    @staticmethod
    def _validate(lambda_under: float, lambda_over: float, alpha: float) -> None:
        """Valide les paramètres de la pénalité asymétrique.

        Raises:
            ValueError: si un lambda est <= 0 ou si alpha sort de (0, 1].
        """
        if lambda_under <= 0:
            raise ValueError(f"lambda_under doit être > 0, reçu {lambda_under}")
        if lambda_over <= 0:
            raise ValueError(f"lambda_over doit être > 0, reçu {lambda_over}")
        if not 0.0 < alpha <= 1.0:
            raise ValueError(f"alpha doit être dans (0, 1], reçu {alpha}")

    # --- Mesures élémentaires ---------------------------------------------------

    @staticmethod
    def adequation_simple(ud: float, ur: float) -> float:
        """Adéquation naïve : 1 − |Ud − Ur|, bornée sur [0, 1].

        Ur peut dépasser 1 pour une tâche en retard : l'écart est alors
        borné à 1 avant soustraction.

        Args:
            ud: urgence déclarée ∈ [0, 1].
            ur: urgence réelle (>= 0, peut dépasser 1 si retard).

        Returns:
            Adéquation dans [0, 1] (1 = alignement parfait).
        """
        gap = min(abs(ud - ur), 1.0)
        return _clip(1.0 - gap, 0.0, 1.0)

    @staticmethod
    def false_urgency(ud: float, ur: float) -> float:
        """Fausse urgence F = [Ud − Ur]+ : panique injustifiée.

        Args:
            ud: urgence déclarée.
            ur: urgence réelle.

        Returns:
            Excédent de déclaration, >= 0.
        """
        return max(ud - ur, 0.0)

    @staticmethod
    def hidden_risk(ud: float, ur: float) -> float:
        """Risque caché H = [Ur − Ud]+ : danger invisible.

        Args:
            ud: urgence déclarée.
            ur: urgence réelle.

        Returns:
            Excédent de réalité, >= 0.
        """
        return max(ur - ud, 0.0)

    # --- Score asymétrique --------------------------------------------------------

    def adequation_asym(
        self,
        ud: float,
        ur: float,
        lambda_under: float | None = None,
        lambda_over: float | None = None,
        alpha: float | None = None,
    ) -> float:
        """Score d'adéquation asymétrique sur [0, 100] (Prospect Theory).

        La pénalité pondère différemment les deux pathologies :

            e_under = [Ur − Ud]+ ; e_over = [Ud − Ur]+
            penalty = λ_under·e_under^α + λ_over·e_over^α
            A = 100·(exp(−penalty) − exp(−max_penalty)) / (1 − exp(−max_penalty))

        avec max_penalty = max(λ_under, λ_over) (pénalité d'un écart maximal
        de 1 dans la direction la plus pénalisée). Le score est borné sur
        [0, 100] et vaut 0.0 dès que exp(−penalty) <= exp(−max_penalty)
        (notamment quand Ur > 1 + Ud, tâche très en retard).

        Règle de gouvernance : ``lambda_under > lambda_over`` — la
        sous-estimation (risque caché) doit coûter plus cher que la
        surestimation (fausse urgence) : le danger invisible est pire que
        la panique.

        Args:
            ud: urgence déclarée ∈ [0, 1].
            ur: urgence réelle (>= 0, peut dépasser 1 si retard).
            lambda_under: surcharge ponctuelle de la pénalité de
                sous-estimation (défaut : valeur du moteur).
            lambda_over: surcharge ponctuelle de la pénalité de
                surestimation (défaut : valeur du moteur).
            alpha: surcharge ponctuelle de la courbure (défaut : moteur).

        Returns:
            Score d'adéquation dans [0, 100] (100 = alignement parfait).

        Raises:
            ValueError: si un lambda surchargé est <= 0 ou si alpha
                surchargé sort de (0, 1].
        """
        lu = self.lambda_under if lambda_under is None else lambda_under
        lo = self.lambda_over if lambda_over is None else lambda_over
        a = self.alpha if alpha is None else alpha
        self._validate(lu, lo, a)

        e_under = max(ur - ud, 0.0)
        e_over = max(ud - ur, 0.0)
        penalty = lu * e_under**a + lo * e_over**a

        max_penalty = max(lu, lo)
        floor = math.exp(-max_penalty)
        value = math.exp(-penalty)
        if value <= floor:
            return 0.0
        score = 100.0 * (value - floor) / (1.0 - floor)
        return _clip(score, 0.0, 100.0)

    # --- Évaluation complète --------------------------------------------------------

    def evaluate(self, ud: float, ur: float) -> UrgencyState:
        """Évalue un couple (Ud, Ur) et renvoie un état d'urgence partiel.

        Remplit ``ud``, ``ur``, ``adequation`` (score asymétrique),
        ``false_urgency`` et ``hidden_risk`` ; les champs locaux/propagés
        restants sont laissés à None (responsabilité du module graphe).

        Args:
            ud: urgence déclarée ∈ [0, 1].
            ur: urgence réelle (>= 0, peut dépasser 1 si retard).

        Returns:
            :class:`supplyscore.domain.models.UrgencyState` partiellement rempli.
        """
        return UrgencyState(
            ud=ud,
            ur=ur,
            adequation=self.adequation_asym(ud, ur),
            false_urgency=self.false_urgency(ud, ur),
            hidden_risk=self.hidden_risk(ud, ur),
        )
