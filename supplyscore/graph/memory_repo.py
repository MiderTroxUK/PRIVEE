"""Implémentation en mémoire du GraphRepository, adossée à networkx.DiGraph.

L'arête networkx source -> target suit la convention du domaine :
fournisseur (rang r+1) -> client (rang r).
"""

from __future__ import annotations

import networkx as nx

from supplyscore.domain.models import SupplyArc, SupplyNode
from supplyscore.graph.repository import GraphRepository

_NODE_KEY = "node"
_ARC_KEY = "arc"


class InMemoryGraphRepository(GraphRepository):
    """Dépôt volatil — sert de référence et de doublure de test pour Neo4j."""

    def __init__(self) -> None:
        """Crée un dépôt vide adossé à un ``networkx.DiGraph``."""
        self._graph = nx.DiGraph()

    # --- Nœuds ----------------------------------------------------------

    def add_node(self, node: SupplyNode) -> None:
        """Ajoute un nœud. Lève ValueError si l'id existe déjà."""
        if self._graph.has_node(node.id):
            raise ValueError(f"Nœud déjà présent : {node.id!r}")
        self._graph.add_node(node.id, **{_NODE_KEY: node})

    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le nœud ou None s'il est inconnu."""
        if not self._graph.has_node(node_id):
            return None
        return self._graph.nodes[node_id][_NODE_KEY]

    def update_node(self, node: SupplyNode) -> None:
        """Remplace le nœud existant. Lève KeyError si l'id est inconnu."""
        if not self._graph.has_node(node.id):
            raise KeyError(f"Nœud inconnu : {node.id!r}")
        self._graph.nodes[node.id][_NODE_KEY] = node

    def remove_node(self, node_id: str) -> None:
        """Supprime le nœud et ses arcs incidents. Lève KeyError si inconnu."""
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        self._graph.remove_node(node_id)  # supprime aussi les arcs incidents

    # --- Arcs -----------------------------------------------------------

    def add_arc(self, arc: SupplyArc) -> None:
        """Ajoute un arc fournisseur -> client. Lève ValueError si invalide ou cyclique."""
        for node_id in (arc.source_id, arc.target_id):
            if not self._graph.has_node(node_id):
                raise ValueError(f"Nœud inconnu : {node_id!r}")
        if self._graph.has_edge(arc.source_id, arc.target_id):
            raise ValueError(f"Arc déjà présent : {arc.id!r}")
        self._graph.add_edge(arc.source_id, arc.target_id, **{_ARC_KEY: arc})
        if not nx.is_directed_acyclic_graph(self._graph):
            self._graph.remove_edge(arc.source_id, arc.target_id)  # rollback
            raise ValueError(f"L'arc {arc.id!r} créerait un cycle")

    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc source -> target ou None."""
        if not self._graph.has_edge(source_id, target_id):
            return None
        return self._graph.edges[source_id, target_id][_ARC_KEY]

    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Supprime l'arc. Lève KeyError s'il est inconnu."""
        if not self._graph.has_edge(source_id, target_id):
            raise KeyError(f"Arc inconnu : {source_id!r} -> {target_id!r}")
        self._graph.remove_edge(source_id, target_id)

    # --- Parcours ---------------------------------------------------------

    def nodes(self) -> list[SupplyNode]:
        """Tous les nœuds du graphe."""
        return [data[_NODE_KEY] for _, data in self._graph.nodes(data=True)]

    def arcs(self) -> list[SupplyArc]:
        """Tous les arcs du graphe."""
        return [data[_ARC_KEY] for _, _, data in self._graph.edges(data=True)]

    def predecessors(self, node_id: str) -> list[SupplyNode]:
        """Fournisseurs directs du nœud. Lève KeyError si l'id est inconnu."""
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        return [self._graph.nodes[p][_NODE_KEY] for p in self._graph.predecessors(node_id)]

    def successors(self, node_id: str) -> list[SupplyNode]:
        """Clients directs du nœud. Lève KeyError si l'id est inconnu."""
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        return [self._graph.nodes[s][_NODE_KEY] for s in self._graph.successors(node_id)]

    def nodes_by_project(self, project_id: str) -> list[SupplyNode]:
        """Nœuds rattachés au projet donné."""
        return [n for n in self.nodes() if n.project_id == project_id]

    def topological_order(self) -> list[str]:
        """Ids triés des fournisseurs profonds (rang N) vers le rang 0."""
        # Sources = fournisseurs profonds en premier, puits (rang 0) en dernier.
        return list(nx.topological_sort(self._graph))

    def clear(self) -> None:
        """Vide entièrement le graphe."""
        self._graph.clear()

    # --- Rangs ------------------------------------------------------------

    def assign_ranks(self) -> dict[str, int]:
        """Recalcule node.rank pour chaque nœud et retourne {id: rank}.

        rank(i) = 0 si i n'a pas de successeur (client final),
        sinon 1 + max(rank(succ)) : plus longue distance vers un puits.
        """
        ranks: dict[str, int] = {}
        for node_id in reversed(self.topological_order()):
            succ_ids = list(self._graph.successors(node_id))
            ranks[node_id] = 1 + max(ranks[s] for s in succ_ids) if succ_ids else 0
            self._graph.nodes[node_id][_NODE_KEY].rank = ranks[node_id]
        return ranks
