"""Implémentation Neo4j du GraphRepository.

Le driver ``neo4j`` est une dépendance OPTIONNELLE : ce module doit rester
importable sans lui. L'import du driver est donc fait paresseusement dans le
constructeur, avec un message d'installation explicite en cas d'absence.

Modèle de données :
- nœud  (:SupplyNode {id, name, label, kind, rank, project_id, location,
                      latitude, longitude, status, kpis, urgency})
- arc   (:SupplyNode)-[:SUPPLIES {label, gamma, beta, delta, kpis}]->(:SupplyNode)
  orienté fournisseur -> client ; les KPIs sont sérialisés en JSON.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from supplyscore.domain.models import (
    KPIBundle,
    NodeKind,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)
from supplyscore.graph.repository import GraphRepository

_INSTALL_HINT = (
    "Le driver Neo4j n'est pas installé. "
    "Installez la dépendance optionnelle avec : pip install supplyscore[neo4j]"
)


# --- (Dé)sérialisation -------------------------------------------------------


def _kpis_to_json(kpis: KPIBundle) -> str:
    return json.dumps(dataclasses.asdict(kpis))


def _kpis_from_json(raw: str | None) -> KPIBundle:
    if not raw:
        return KPIBundle()
    data = json.loads(raw)
    bundle = KPIBundle()
    for block_name, block_values in data.items():
        block = getattr(bundle, block_name, None)
        if block is None or not isinstance(block_values, dict):
            continue
        for key, value in block_values.items():
            if hasattr(block, key):
                setattr(block, key, value)
    return bundle


def _urgency_to_json(urgency: UrgencyState) -> str:
    return json.dumps(dataclasses.asdict(urgency))


def _urgency_from_json(raw: str | None) -> UrgencyState:
    if not raw:
        return UrgencyState()
    return UrgencyState(**json.loads(raw))


def _node_to_props(node: SupplyNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "label": node.label,
        "kind": str(node.kind),
        "rank": node.rank,
        "project_id": node.project_id,
        "location": node.location,
        "latitude": node.latitude,
        "longitude": node.longitude,
        "status": str(node.status),
        "kpis": _kpis_to_json(node.kpis),
        "urgency": _urgency_to_json(node.urgency),
    }


def _node_from_props(props: dict[str, Any]) -> SupplyNode:
    return SupplyNode(
        id=props["id"],
        name=props.get("name", props["id"]),
        label=props.get("label", "Workshop"),
        kind=NodeKind(props.get("kind", "node")),
        rank=int(props.get("rank", 0)),
        project_id=props.get("project_id"),
        location=props.get("location"),
        latitude=props.get("latitude"),
        longitude=props.get("longitude"),
        status=TaskStatus(props.get("status", "active")),
        kpis=_kpis_from_json(props.get("kpis")),
        urgency=_urgency_from_json(props.get("urgency")),
    )


def _arc_to_props(arc: SupplyArc) -> dict[str, Any]:
    return {
        "label": arc.label,
        "gamma": arc.gamma,
        "beta": arc.beta,
        "delta": arc.delta,
        "kpis": _kpis_to_json(arc.kpis),
    }


def _arc_from_record(source_id: str, target_id: str, props: dict[str, Any]) -> SupplyArc:
    return SupplyArc(
        source_id=source_id,
        target_id=target_id,
        label=props.get("label", "Truck"),
        gamma=float(props.get("gamma", 0.5)),
        beta=float(props.get("beta", 0.5)),
        delta=float(props.get("delta", 1.0)),
        kpis=_kpis_from_json(props.get("kpis")),
    )


# --- Dépôt --------------------------------------------------------------------


class Neo4jGraphRepository(GraphRepository):
    """Persiste le graphe supply chain dans une base Neo4j."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        """Ouvre le driver Neo4j (import paresseux : dépendance optionnelle)."""
        try:
            from neo4j import GraphDatabase  # import paresseux : dépendance optionnelle
        except ImportError as exc:
            raise ImportError(_INSTALL_HINT) from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    def close(self) -> None:
        """Ferme le driver Neo4j."""
        self._driver.close()

    def __enter__(self) -> Neo4jGraphRepository:
        """Entre dans le context manager (retourne le dépôt lui-même)."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Ferme le driver à la sortie du context manager."""
        self.close()

    def _run(self, query: str, **params: Any) -> list[Any]:
        with self._driver.session(database=self._database) as session:
            return list(session.run(query, **params))

    # --- Nœuds ----------------------------------------------------------

    def add_node(self, node: SupplyNode) -> None:
        """Ajoute un nœud. Lève ValueError si l'id existe déjà."""
        if self.get_node(node.id) is not None:
            raise ValueError(f"Nœud déjà présent : {node.id!r}")
        self._run(
            "MERGE (n:SupplyNode {id: $id}) SET n += $props",
            id=node.id,
            props=_node_to_props(node),
        )

    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le nœud ou None s'il est inconnu."""
        records = self._run("MATCH (n:SupplyNode {id: $id}) RETURN n", id=node_id)
        if not records:
            return None
        return _node_from_props(dict(records[0]["n"]))

    def update_node(self, node: SupplyNode) -> None:
        """Remplace le nœud existant. Lève KeyError si l'id est inconnu."""
        if self.get_node(node.id) is None:
            raise KeyError(f"Nœud inconnu : {node.id!r}")
        self._run(
            "MATCH (n:SupplyNode {id: $id}) SET n += $props",
            id=node.id,
            props=_node_to_props(node),
        )

    def remove_node(self, node_id: str) -> None:
        """Supprime le nœud et ses arcs incidents. Lève KeyError si inconnu."""
        if self.get_node(node_id) is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        self._run("MATCH (n:SupplyNode {id: $id}) DETACH DELETE n", id=node_id)

    # --- Arcs -----------------------------------------------------------

    def add_arc(self, arc: SupplyArc) -> None:
        """Ajoute un arc fournisseur -> client. Lève ValueError si invalide ou cyclique."""
        for node_id in (arc.source_id, arc.target_id):
            if self.get_node(node_id) is None:
                raise ValueError(f"Nœud inconnu : {node_id!r}")
        if self.get_arc(arc.source_id, arc.target_id) is not None:
            raise ValueError(f"Arc déjà présent : {arc.id!r}")
        if self._creates_cycle(arc.source_id, arc.target_id):
            raise ValueError(f"L'arc {arc.id!r} créerait un cycle")
        self._run(
            "MATCH (s:SupplyNode {id: $source_id}), (t:SupplyNode {id: $target_id}) "
            "MERGE (s)-[r:SUPPLIES]->(t) SET r += $props",
            source_id=arc.source_id,
            target_id=arc.target_id,
            props=_arc_to_props(arc),
        )

    def _creates_cycle(self, source_id: str, target_id: str) -> bool:
        # Cycle ssi un chemin target -> ... -> source existe déjà.
        records = self._run(
            "MATCH (t:SupplyNode {id: $target_id}), (s:SupplyNode {id: $source_id}) "
            "RETURN exists((t)-[:SUPPLIES*]->(s)) AS has_path",
            source_id=source_id,
            target_id=target_id,
        )
        return bool(records and records[0]["has_path"])

    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc source -> target ou None."""
        records = self._run(
            "MATCH (:SupplyNode {id: $source_id})-[r:SUPPLIES]->(:SupplyNode {id: $target_id}) "
            "RETURN r",
            source_id=source_id,
            target_id=target_id,
        )
        if not records:
            return None
        return _arc_from_record(source_id, target_id, dict(records[0]["r"]))

    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Supprime l'arc. Lève KeyError s'il est inconnu."""
        if self.get_arc(source_id, target_id) is None:
            raise KeyError(f"Arc inconnu : {source_id!r} -> {target_id!r}")
        self._run(
            "MATCH (:SupplyNode {id: $source_id})-[r:SUPPLIES]->(:SupplyNode {id: $target_id}) "
            "DELETE r",
            source_id=source_id,
            target_id=target_id,
        )

    # --- Parcours ---------------------------------------------------------

    def nodes(self) -> list[SupplyNode]:
        """Tous les nœuds du graphe."""
        records = self._run("MATCH (n:SupplyNode) RETURN n")
        return [_node_from_props(dict(rec["n"])) for rec in records]

    def arcs(self) -> list[SupplyArc]:
        """Tous les arcs du graphe."""
        records = self._run(
            "MATCH (s:SupplyNode)-[r:SUPPLIES]->(t:SupplyNode) "
            "RETURN s.id AS source_id, t.id AS target_id, r"
        )
        return [
            _arc_from_record(rec["source_id"], rec["target_id"], dict(rec["r"])) for rec in records
        ]

    def predecessors(self, node_id: str) -> list[SupplyNode]:
        """Fournisseurs directs : sources des arcs entrants sur node_id."""
        records = self._run(
            "MATCH (p:SupplyNode)-[:SUPPLIES]->(:SupplyNode {id: $id}) RETURN p",
            id=node_id,
        )
        return [_node_from_props(dict(rec["p"])) for rec in records]

    def successors(self, node_id: str) -> list[SupplyNode]:
        """Clients directs : cibles des arcs sortants de node_id."""
        records = self._run(
            "MATCH (:SupplyNode {id: $id})-[:SUPPLIES]->(s:SupplyNode) RETURN s",
            id=node_id,
        )
        return [_node_from_props(dict(rec["s"])) for rec in records]

    def nodes_by_project(self, project_id: str) -> list[SupplyNode]:
        """Nœuds rattachés au projet donné."""
        records = self._run(
            "MATCH (n:SupplyNode {project_id: $project_id}) RETURN n",
            project_id=project_id,
        )
        return [_node_from_props(dict(rec["n"])) for rec in records]

    def topological_order(self) -> list[str]:
        """Tri topologique (Kahn) calculé côté Python à partir des arcs."""
        node_ids = [n.id for n in self.nodes()]
        edges = [(a.source_id, a.target_id) for a in self.arcs()]
        out_edges: dict[str, list[str]] = {nid: [] for nid in node_ids}
        in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
        for source_id, target_id in edges:
            out_edges[source_id].append(target_id)
            in_degree[target_id] += 1
        queue = [nid for nid in node_ids if in_degree[nid] == 0]
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for nxt in out_edges[current]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(node_ids):
            raise ValueError("Le graphe persisté contient un cycle")
        return order

    def clear(self) -> None:
        """Vide entièrement le graphe."""
        self._run("MATCH (n:SupplyNode) DETACH DELETE n")
