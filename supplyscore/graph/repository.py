"""Interface abstraite du dépôt de graphe supply chain.

Convention d'orientation (cf. supplyscore.domain.models.SupplyArc) :
- une arête source -> target relie un FOURNISSEUR (rang r+1) à son CLIENT (rang r) ;
- rank 0 = client final (puits du graphe).
"""

from __future__ import annotations

import abc

from supplyscore.domain.models import SupplyArc, SupplyNode


class GraphRepository(abc.ABC):
    """Contrat commun aux implémentations mémoire (networkx) et Neo4j."""

    # --- Nœuds ----------------------------------------------------------

    @abc.abstractmethod
    def add_node(self, node: SupplyNode) -> None:
        """Ajoute un nœud. Lève ValueError si l'id existe déjà."""

    @abc.abstractmethod
    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le nœud ou None s'il est inconnu."""

    @abc.abstractmethod
    def update_node(self, node: SupplyNode) -> None:
        """Remplace le nœud existant. Lève KeyError si l'id est inconnu."""

    @abc.abstractmethod
    def remove_node(self, node_id: str) -> None:
        """Supprime le nœud et ses arcs incidents. Lève KeyError si inconnu."""

    # --- Arcs -----------------------------------------------------------

    @abc.abstractmethod
    def add_arc(self, arc: SupplyArc) -> None:
        """Ajoute un arc fournisseur -> client.

        Lève ValueError si un des deux nœuds est inconnu, si l'arc existe
        déjà, ou si l'ajout créerait un cycle.
        """

    @abc.abstractmethod
    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc source -> target ou None."""

    @abc.abstractmethod
    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Supprime l'arc. Lève KeyError s'il est inconnu."""

    # --- Parcours ---------------------------------------------------------

    @abc.abstractmethod
    def nodes(self) -> list[SupplyNode]:
        """Tous les nœuds du graphe."""

    @abc.abstractmethod
    def arcs(self) -> list[SupplyArc]:
        """Tous les arcs du graphe."""

    @abc.abstractmethod
    def predecessors(self, node_id: str) -> list[SupplyNode]:
        """Fournisseurs directs : sources des arcs entrants sur node_id."""

    @abc.abstractmethod
    def successors(self, node_id: str) -> list[SupplyNode]:
        """Clients directs : cibles des arcs sortants de node_id."""

    @abc.abstractmethod
    def nodes_by_project(self, project_id: str) -> list[SupplyNode]:
        """Nœuds rattachés au projet donné."""

    @abc.abstractmethod
    def topological_order(self) -> list[str]:
        """Ids triés des fournisseurs profonds (rang N) vers le rang 0."""

    @abc.abstractmethod
    def clear(self) -> None:
        """Vide entièrement le graphe."""
