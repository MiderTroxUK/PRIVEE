"""Score d'adequation A  dans  [0, 100] entre urgence declaree Ud et reelle Ur.

L'adequation mesure l'alignement entre la perception humaine (Ud) et la
realite operationnelle (Ur). Deux pathologies sont distinguees :

- **Fausse urgence** F = [Ud - Ur]+ : panique injustifiee (sur-declaration) ;
- **Risque cache** H = [Ur - Ud]+ : danger invisible (sous-declaration).

Regle de gouvernance : ``lambda_under > lambda_over`` - le danger invisible
est pire que la panique. Une equipe qui sur-reagit gaspille des ressources ;
une equipe qui sous-estime decouvre la rupture quand il est trop tard.
Le defaut 2.25 vs 1.0 reprend le coefficient d'aversion a la perte mesure
par Kahneman & Tversky (Prospect Theory, 1992).
"""

from __future__ import annotations

import math

from supplyscore.domain.models import UrgencyState


def _clip(x: float, lo: float, hi: float) -> float:
    """Borne une valeur sur [lo, hi]."""
    return min(max(x, lo), hi)


class AdequationEngine:
    """Moteur de calcul du score d'adequation Ud/Ur.

    Attributes:
        lambda_under: penalite de sous-estimation (Ur > Ud), > 0.
            Doit rester > ``lambda_over`` (le danger invisible est pire
            que la panique).
        lambda_over: penalite de surestimation (Ud > Ur), > 0.
        alpha: courbure psychophysique de la fonction de valeur
            (Prospect Theory), dans (0, 1].
    """

    def __init__(
        self,
        lambda_under: float = 2.25,
        lambda_over: float = 1.0,
        alpha: float = 0.88,
    ) -> None:
        """Initialise le moteur avec les parametres de penalite asymetrique.

        Raises:
            ValueError: si un lambda est <= 0 ou si alpha sort de (0, 1].
        """
        self._validate(lambda_under, lambda_over, alpha)
        self.lambda_under = lambda_under
        self.lambda_over = lambda_over
        self.alpha = alpha

    @staticmethod
    def _validate(lambda_under: float, lambda_over: float, alpha: float) -> None:
        """Valide les parametres de la penalite asymetrique.

        Raises:
            ValueError: si un lambda est <= 0 ou si alpha sort de (0, 1].
        """
        if lambda_under <= 0:
            raise ValueError(f"lambda_under doit être > 0, reçu {lambda_under}")
        if lambda_over <= 0:
            raise ValueError(f"lambda_over doit être > 0, reçu {lambda_over}")
        if not 0.0 < alpha <= 1.0:
            raise ValueError(f"alpha doit être dans (0, 1], reçu {alpha}")

    # Mesures elementaires

    @staticmethod
    def adequation_simple(ud: float, ur: float) -> float:
        """Adequation naive : 1 - |Ud - Ur|, bornee sur [0, 1].

        Ur peut depasser 1 pour une tache en retard : l'ecart est alors
        borne a 1 avant soustraction.

        Args:
            ud: urgence declaree  dans  [0, 1].
            ur: urgence reelle (>= 0, peut depasser 1 si retard).

        Returns:
            Adequation dans [0, 1] (1 = alignement parfait).
        """
        gap = min(abs(ud - ur), 1.0)
        return _clip(1.0 - gap, 0.0, 1.0)

    @staticmethod
    def false_urgency(ud: float, ur: float) -> float:
        """Fausse urgence F = [Ud - Ur]+ : panique injustifiee.

        Args:
            ud: urgence declaree.
            ur: urgence reelle.

        Returns:
            Excedent de declaration, >= 0.
        """
        return max(ud - ur, 0.0)

    @staticmethod
    def hidden_risk(ud: float, ur: float) -> float:
        """Risque cache H = [Ur - Ud]+ : danger invisible.

        Args:
            ud: urgence declaree.
            ur: urgence reelle.

        Returns:
            Excedent de realite, >= 0.
        """
        return max(ur - ud, 0.0)

    # Score asymetrique

    def adequation_asym(
        self,
        ud: float,
        ur: float,
        lambda_under: float | None = None,
        lambda_over: float | None = None,
        alpha: float | None = None,
    ) -> float:
        """Score d'adequation asymetrique sur [0, 100] (Prospect Theory).

        La penalite pondere differemment les deux pathologies :

            e_under = [Ur - Ud]+ ; e_over = [Ud - Ur]+
            penalty = lambda_under-e_under^alpha + lambda_over-e_over^alpha
            A = 100-(exp(-penalty) - exp(-max_penalty)) / (1 - exp(-max_penalty))

        avec max_penalty = max(lambda_under, lambda_over) (penalite d'un ecart maximal
        de 1 dans la direction la plus penalisee). Le score est borne sur
        [0, 100] et vaut 0.0 des que exp(-penalty) <= exp(-max_penalty)
        (notamment quand Ur > 1 + Ud, tache tres en retard).

        Regle de gouvernance : ``lambda_under > lambda_over`` - la
        sous-estimation (risque cache) doit couter plus cher que la
        surestimation (fausse urgence) : le danger invisible est pire que
        la panique.

        Args:
            ud: urgence declaree  dans  [0, 1].
            ur: urgence reelle (>= 0, peut depasser 1 si retard).
            lambda_under: surcharge ponctuelle de la penalite de
                sous-estimation (defaut : valeur du moteur).
            lambda_over: surcharge ponctuelle de la penalite de
                surestimation (defaut : valeur du moteur).
            alpha: surcharge ponctuelle de la courbure (defaut : moteur).

        Returns:
            Score d'adequation dans [0, 100] (100 = alignement parfait).

        Raises:
            ValueError: si un lambda surcharge est <= 0 ou si alpha
                surcharge sort de (0, 1].
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

    # Evaluation complete

    def evaluate(self, ud: float, ur: float) -> UrgencyState:
        """Evalue un couple (Ud, Ur) et renvoie un etat d'urgence partiel.

        Remplit ``ud``, ``ur``, ``adequation`` (score asymetrique),
        ``false_urgency`` et ``hidden_risk`` ; les champs locaux/propages
        restants sont laisses a None (responsabilite du module graphe).

        Args:
            ud: urgence declaree  dans  [0, 1].
            ur: urgence reelle (>= 0, peut depasser 1 si retard).

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
