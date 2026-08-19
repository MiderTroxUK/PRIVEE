"""Interface abstraite du depot de graphe supply chain.

Convention d'orientation (cf. supplyscore.domain.models.SupplyArc) :
- une arete source -> target relie un FOURNISSEUR (rang r+1) a son CLIENT (rang r) ;
- rank 0 = client final (puits du graphe).

Nature des arcs (cf. supplyscore.domain.models.ArcKind) : par defaut, seuls
les arcs NOMINAUX comptent comme liens de flux (propagation, voisinage, tri
topologique, rangs). Les arcs de secours (BACKUP) sont purement documentaires
et inertes dans tous les calculs.
"""

from __future__ import annotations

import abc

from supplyscore.domain.models import SupplyArc, SupplyNode


class GraphRepository(abc.ABC):
    """Contrat commun aux implementations memoire (networkx) et Neo4j."""

    # Noeuds

    @abc.abstractmethod
    def add_node(self, node: SupplyNode) -> None:
        """Ajoute un noeud. Leve ValueError si l'id existe deja."""

    @abc.abstractmethod
    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le noeud ou None s'il est inconnu."""

    @abc.abstractmethod
    def update_node(self, node: SupplyNode) -> None:
        """Remplace le noeud existant. Leve KeyError si l'id est inconnu."""

    @abc.abstractmethod
    def remove_node(self, node_id: str) -> None:
        """Supprime le noeud et ses arcs incidents. Leve KeyError si inconnu."""

    # Arcs

    @abc.abstractmethod
    def add_arc(self, arc: SupplyArc) -> None:
        """Ajoute un arc fournisseur -> client.

        Leve ValueError si un des deux noeuds est inconnu, si l'arc existe
        deja, ou si l'ajout creerait un cycle. Le refus de cycle ne concerne
        que les arcs NOMINAUX : un arc de secours (backup), inerte, peut
        fermer un cycle apparent, mais reste interdit en boucle sur lui-meme.
        """

    @abc.abstractmethod
    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc source -> target ou None."""

    @abc.abstractmethod
    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Supprime l'arc. Leve KeyError s'il est inconnu."""

    # Parcours

    @abc.abstractmethod
    def nodes(self) -> list[SupplyNode]:
        """Tous les noeuds du graphe."""

    @abc.abstractmethod
    def arcs(self, kinds: tuple[str, ...] | None = None) -> list[SupplyArc]:
        """Arcs du graphe, filtres par nature.

        Args:
            kinds: natures d'arcs retenues (valeurs d'ArcKind, ex. "nominal",
                "backup") ; None retourne TOUS les arcs.
        """

    @abc.abstractmethod
    def predecessors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Fournisseurs directs : sources des arcs entrants sur node_id.

        Par defaut, seuls les arcs nominaux comptent comme liens de flux ;
        les arcs de secours (backup) sont documentaires et ignores. Passer
        ``kinds=("nominal", "backup")`` pour les inclure.
        """

    @abc.abstractmethod
    def successors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Clients directs : cibles des arcs sortants de node_id.

        Par defaut, seuls les arcs nominaux comptent comme liens de flux ;
        les arcs de secours (backup) sont documentaires et ignores. Passer
        ``kinds=("nominal", "backup")`` pour les inclure.
        """

    @abc.abstractmethod
    def nodes_by_project(self, project_id: str) -> list[SupplyNode]:
        """Noeuds rattaches au projet donne."""

    @abc.abstractmethod
    def topological_order(self) -> list[str]:
        """Ids tries des fournisseurs profonds (rang N) vers le rang 0.

        Seuls les arcs nominaux creent une dependance d'ordre : les arcs de
        secours (backup) sont ignores.
        """

    @abc.abstractmethod
    def clear(self) -> None:
        """Vide entierement le graphe."""
