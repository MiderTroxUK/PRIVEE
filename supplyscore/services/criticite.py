"""Service de criticité systématique des nœuds (phase E15, Lot 15.2).

:class:`ServiceCriticite` répond à « quel nœud ferait le plus mal s'il
tombait ? » : pour CHAQUE nœud actif d'un projet, il simule le pire choc
local (``ur_local -> 1.0``) via
:meth:`~supplyscore.graph.propagation.PropagationEngine.simulate_shock`
(calcul PUR — aucune écriture), mesure le ΔUr propagé jusqu'au(x) client(s)
final(aux) (rang 0) et classe les nœuds du plus critique au moins critique.

Le service est PUR EN LECTURE : ``simulate_shock`` ne persiste ni le
``ur_local`` simulé ni les Ur recalculés — les :class:`~supplyscore.domain.models.UrgencyState`
du dépôt sont bit à bit identiques avant et après :meth:`ServiceCriticite.indice_criticite`.

CHOIX DOCUMENTÉ — nœuds déjà saturés : un nœud dont le ``ur_local`` effectif
vaut déjà >= 1.0 (retard avéré, valeur clipée à 1.0 dans la propagation)
donne un choc « à vide » : l'état choqué est identique à la référence, tous
ses deltas valent 0.0 et il tombe en queue de classement. C'est voulu — sa
défaillance est DÉJÀ dans le Ur de référence, l'aggraver n'apprend rien.

Complexité : une propagation de référence + une propagation choquée par nœud
actif (``simulate_shock`` recalcule la référence à chaque appel), soit
O(n_actifs × (N + E)) sur le dépôt entier — instantané sur les graphes du
serious game, < 2 s visés sur 1 000 nœuds (DoD E15).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from supplyscore.domain.models import SupplyNode, TaskStatus

if TYPE_CHECKING:  # import différé : évite tout cycle services.criticite <-> orchestrator
    from supplyscore.services.orchestrator import SupplyScoreService

#: Seuil en deçà duquel un ΔUr est réputé nul (nœud non impacté par le choc).
_EPS_DELTA: float = 1e-12


@dataclass(frozen=True)
class PointCriticite:
    """Criticité d'un nœud : effet du pire choc local (``ur_local -> 1.0``).

    Attributes:
        node_id: identifiant du nœud choqué.
        node_name: nom lisible du nœud choqué.
        rank: rang dans le classement de criticité (1 = le plus critique).
        delta_ur_final: ΔUr du/des client(s) final(aux) du projet (rang 0)
            si CE nœud passait à ``ur_local = 1.0`` — le plus grand ΔUr
            parmi les nœuds de rang 0 du projet, 0.0 si le choc ne les
            atteint pas.
        delta_ur_max: plus grand ΔUr observé sur TOUT le graphe (le nœud
            choqué lui-même compris).
        nb_impactes: nombre de nœuds dont ``|ΔUr| > 1e-12`` (le nœud choqué
            compris s'il bouge).
    """

    node_id: str
    node_name: str
    rank: int
    delta_ur_final: float
    delta_ur_max: float
    nb_impactes: int


class ServiceCriticite:
    """Analyse systématique de criticité — lecture seule au-dessus de la façade.

    Toutes les lectures passent par les composants du
    :class:`~supplyscore.services.orchestrator.SupplyScoreService` fourni
    (graphe en mémoire, registre, moteur de propagation) ; le service ne
    recalcule rien hors de ``simulate_shock`` et n'écrit jamais.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service de criticité sur la façade de l'application.

        Args:
            service: façade :class:`~supplyscore.services.orchestrator.SupplyScoreService`
                (graphe, registre, moteur de propagation).
        """
        self._service = service

    # --- API publique -------------------------------------------------------------------

    def indice_criticite(self, project_id: str) -> list[PointCriticite]:
        """Criticité de chaque nœud actif du projet, du plus au moins critique.

        Pour chaque nœud ACTIF du projet (statut
        :attr:`~supplyscore.domain.models.TaskStatus.ACTIVE`, onboarding
        terminé), simule le pire choc local ``ur_local -> 1.0`` via
        ``simulate_shock`` (PUR — rien n'est persisté) et mesure :

        - ``delta_ur_final`` : le plus grand ΔUr parmi les nœuds de rang 0
          du projet (0.0 si le choc ne les atteint pas) ;
        - ``delta_ur_max`` : le plus grand ΔUr sur tout le graphe ;
        - ``nb_impactes`` : le nombre de nœuds avec ``|ΔUr| > 1e-12``.

        Tri : ``delta_ur_final`` décroissant, départagé par ``delta_ur_max``
        décroissant puis par nom croissant ; le champ ``rank`` reflète la
        position finale (1 = le plus critique). Un nœud déjà à
        ``ur_local >= 1.0`` donne des deltas nuls (cf. choix documenté en
        tête de module) et tombe donc en queue de classement.

        Args:
            project_id: projet à analyser.

        Returns:
            Un :class:`PointCriticite` par nœud actif, triés.

        Raises:
            ValueError: si le projet est inconnu du registre ou ne compte
                aucun nœud actif (messages en français).
        """
        service = self._service
        if service.registry.get_project(project_id) is None:
            raise ValueError(f"Projet inconnu : {project_id!r}")
        project_nodes = service.repo.nodes_by_project(project_id)
        actifs = [
            node
            for node in project_nodes
            if node.status == TaskStatus.ACTIVE and node.onboarding_state != "draft"
        ]
        if not actifs:
            raise ValueError(
                f"Analyse de criticité impossible pour le projet {project_id!r} : "
                "aucun nœud actif (statut ACTIVE, onboarding terminé)."
            )
        finals = [node.id for node in project_nodes if node.rank == 0]

        mesures: list[tuple[SupplyNode, float, float, int]] = []
        for node in actifs:
            deltas = service.propagation.simulate_shock(node.id, 1.0)
            delta_final = max((deltas[final_id] for final_id in finals), default=0.0)
            delta_max = max(deltas.values(), default=0.0)
            nb_impactes = sum(1 for delta in deltas.values() if abs(delta) > _EPS_DELTA)
            mesures.append((node, delta_final, delta_max, nb_impactes))

        mesures.sort(key=lambda mesure: (-mesure[1], -mesure[2], mesure[0].name))
        return [
            PointCriticite(
                node_id=node.id,
                node_name=node.name,
                rank=position,
                delta_ur_final=delta_final,
                delta_ur_max=delta_max,
                nb_impactes=nb_impactes,
            )
            for position, (node, delta_final, delta_max, nb_impactes) in enumerate(mesures, start=1)
        ]

    def top(self, project_id: str, n: int = 15) -> list[PointCriticite]:
        """Les ``n`` nœuds les plus critiques du projet (tornado UI, Lot 15.4).

        Args:
            project_id: projet à analyser.
            n: nombre maximal de points retournés (``n <= 0`` rend ``[]``).

        Returns:
            Le préfixe de longueur <= ``n`` de :meth:`indice_criticite`.

        Raises:
            ValueError: si le projet est inconnu ou sans nœud actif
                (mêmes règles que :meth:`indice_criticite`).
        """
        return self.indice_criticite(project_id)[: max(0, n)]
