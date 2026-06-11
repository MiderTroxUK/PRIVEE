"""Implémentation en mémoire du GraphRepository, adossée à networkx.DiGraph.

L'arête networkx source -> target suit la convention du domaine :
fournisseur (rang r+1) -> client (rang r).

Seuls les arcs NOMINAUX sont portés par le ``DiGraph`` : ainsi les algorithmes
networkx (tri topologique, acyclicité, voisinage) ignorent naturellement les
arcs de secours (backup), purement documentaires, qui sont conservés à part
dans un dictionnaire ``{(source_id, target_id): SupplyArc}``.
"""

from __future__ import annotations

import networkx as nx

from supplyscore.domain.models import ArcKind, SupplyArc, SupplyNode
from supplyscore.graph.repository import GraphRepository

_NODE_KEY = "node"
_ARC_KEY = "arc"


class InMemoryGraphRepository(GraphRepository):
    """Dépôt volatil — sert de référence et de doublure de test pour Neo4j."""

    def __init__(self) -> None:
        """Crée un dépôt vide adossé à un ``networkx.DiGraph``.

        Le ``DiGraph`` ne porte que les arcs nominaux ; les arcs de secours
        (backup), inertes, sont stockés dans ``self._backup_arcs``.

        L'ordre topologique est mis en cache (``self._topo_cache``) : calculé
        une seule fois, il est invalidé par TOUTE mutation de structure
        (add_node/remove_node/add_arc/remove_arc/clear — ``update_node`` ne
        change pas la structure). Chaque invalidation incrémente aussi
        ``structure_version``, compteur monotone qui permet aux consommateurs
        (moteur de propagation incrémentale, E14.4) de détecter une mutation
        de structure survenue hors de leur contrôle.
        """
        self._graph = nx.DiGraph()
        self._backup_arcs: dict[tuple[str, str], SupplyArc] = {}
        self._topo_cache: list[str] | None = None
        self._structure_version = 0

    @property
    def structure_version(self) -> int:
        """Version de structure, incrémentée à chaque mutation de nœud ou d'arc."""
        return self._structure_version

    def _invalidate_structure(self) -> None:
        """Invalide le cache topologique et incrémente la version de structure."""
        self._topo_cache = None
        self._structure_version += 1

    # --- Nœuds ----------------------------------------------------------

    def add_node(self, node: SupplyNode) -> None:
        """Ajoute un nœud. Lève ValueError si l'id existe déjà."""
        if self._graph.has_node(node.id):
            raise ValueError(f"Nœud déjà présent : {node.id!r}")
        self._graph.add_node(node.id, **{_NODE_KEY: node})
        self._invalidate_structure()

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
        """Supprime le nœud et ses arcs incidents (backup inclus). Lève KeyError si inconnu."""
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        self._graph.remove_node(node_id)  # supprime aussi les arcs nominaux incidents
        self._backup_arcs = {
            key: arc for key, arc in self._backup_arcs.items() if node_id not in key
        }
        self._invalidate_structure()

    # --- Arcs -----------------------------------------------------------

    def add_arc(self, arc: SupplyArc) -> None:
        """Ajoute un arc fournisseur -> client. Lève ValueError si invalide ou cyclique.

        Le refus de cycle ne s'applique qu'aux arcs NOMINAUX. Un arc de
        secours (backup), inerte dans tous les calculs, peut fermer un cycle
        apparent ; il reste néanmoins interdit en boucle sur lui-même.
        """
        for node_id in (arc.source_id, arc.target_id):
            if not self._graph.has_node(node_id):
                raise ValueError(f"Nœud inconnu : {node_id!r}")
        if self.get_arc(arc.source_id, arc.target_id) is not None:
            raise ValueError(f"Arc déjà présent : {arc.id!r}")
        if arc.kind_arc == ArcKind.BACKUP:
            if arc.source_id == arc.target_id:
                raise ValueError(f"Arc de secours en boucle sur lui-même : {arc.id!r}")
            self._backup_arcs[(arc.source_id, arc.target_id)] = arc  # hors DiGraph : inerte
            self._invalidate_structure()
            return
        self._graph.add_edge(arc.source_id, arc.target_id, **{_ARC_KEY: arc})
        if not nx.is_directed_acyclic_graph(self._graph):
            self._graph.remove_edge(arc.source_id, arc.target_id)  # rollback
            raise ValueError(f"L'arc {arc.id!r} créerait un cycle")
        self._invalidate_structure()

    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc source -> target (nominal ou backup) ou None."""
        if self._graph.has_edge(source_id, target_id):
            return self._graph.edges[source_id, target_id][_ARC_KEY]
        return self._backup_arcs.get((source_id, target_id))

    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Supprime l'arc (nominal ou backup). Lève KeyError s'il est inconnu."""
        if self._graph.has_edge(source_id, target_id):
            self._graph.remove_edge(source_id, target_id)
        elif (source_id, target_id) in self._backup_arcs:
            del self._backup_arcs[(source_id, target_id)]
        else:
            raise KeyError(f"Arc inconnu : {source_id!r} -> {target_id!r}")
        self._invalidate_structure()

    # --- Parcours ---------------------------------------------------------

    def nodes(self) -> list[SupplyNode]:
        """Tous les nœuds du graphe."""
        return [data[_NODE_KEY] for _, data in self._graph.nodes(data=True)]

    def arcs(self, kinds: tuple[str, ...] | None = None) -> list[SupplyArc]:
        """Arcs du graphe (nominaux + backup) ; ``kinds`` filtre par nature, None = tous."""
        all_arcs = [data[_ARC_KEY] for _, _, data in self._graph.edges(data=True)]
        all_arcs.extend(self._backup_arcs.values())
        if kinds is None:
            return all_arcs
        return [arc for arc in all_arcs if arc.kind_arc in kinds]

    def predecessors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Fournisseurs directs du nœud (arcs nominaux seuls par défaut).

        Lève KeyError si l'id est inconnu.
        """
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        ids: list[str] = []
        if ArcKind.NOMINAL in kinds:
            ids.extend(self._graph.predecessors(node_id))
        if ArcKind.BACKUP in kinds:
            ids.extend(source for source, target in self._backup_arcs if target == node_id)
        return [self._graph.nodes[p][_NODE_KEY] for p in ids]

    def successors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Clients directs du nœud (arcs nominaux seuls par défaut).

        Lève KeyError si l'id est inconnu.
        """
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        ids: list[str] = []
        if ArcKind.NOMINAL in kinds:
            ids.extend(self._graph.successors(node_id))
        if ArcKind.BACKUP in kinds:
            ids.extend(target for source, target in self._backup_arcs if source == node_id)
        return [self._graph.nodes[s][_NODE_KEY] for s in ids]

    def nodes_by_project(self, project_id: str) -> list[SupplyNode]:
        """Nœuds rattachés au projet donné."""
        return [n for n in self.nodes() if n.project_id == project_id]

    def topological_order(self) -> list[str]:
        """Ids triés des fournisseurs profonds (rang N) vers le rang 0.

        Le ``DiGraph`` ne portant que les arcs nominaux, les arcs de secours
        (backup) ne créent aucune dépendance d'ordre.

        L'ordre est mis en CACHE : calculé une seule fois, invalidé par toute
        mutation de structure. Une COPIE est retournée — l'appelant peut la
        muter sans corrompre le cache.
        """
        if self._topo_cache is None:
            # Sources = fournisseurs profonds en premier, puits (rang 0) en dernier.
            self._topo_cache = list(nx.topological_sort(self._graph))
        return list(self._topo_cache)

    def descendants(self, node_id: str) -> set[str]:
        """Ids de TOUS les descendants de ``node_id`` (cône aval, arcs nominaux).

        Le ``DiGraph`` ne contenant que les arcs nominaux, les arcs de secours
        (backup) ne créent aucune descendance. Le nœud lui-même est EXCLU.

        Raises:
            KeyError: si ``node_id`` est inconnu (message en français).
        """
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        return set(nx.descendants(self._graph, node_id))

    def ancestors(self, node_id: str) -> set[str]:
        """Ids de TOUS les ancêtres de ``node_id`` (cône amont, arcs nominaux).

        Le ``DiGraph`` ne contenant que les arcs nominaux, les arcs de secours
        (backup) ne créent aucune ascendance. Le nœud lui-même est EXCLU.

        Raises:
            KeyError: si ``node_id`` est inconnu (message en français).
        """
        if not self._graph.has_node(node_id):
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        return set(nx.ancestors(self._graph, node_id))

    def clear(self) -> None:
        """Vide entièrement le graphe (arcs de secours inclus)."""
        self._graph.clear()
        self._backup_arcs.clear()
        self._invalidate_structure()

    # --- Rangs ------------------------------------------------------------

    def assign_ranks(self) -> dict[str, int]:
        """Recalcule node.rank pour chaque nœud et retourne {id: rank}.

        rank(i) = 0 si i n'a pas de successeur (client final),
        sinon 1 + max(rank(succ)) : plus longue distance vers un puits.
        Seuls les arcs nominaux comptent : un arc de secours (backup) ne crée
        pas de dépendance de rang.
        """
        ranks: dict[str, int] = {}
        for node_id in reversed(self.topological_order()):
            succ_ids = list(self._graph.successors(node_id))
            ranks[node_id] = 1 + max(ranks[s] for s in succ_ids) if succ_ids else 0
            self._graph.nodes[node_id][_NODE_KEY].rank = ranks[node_id]
        return ranks
