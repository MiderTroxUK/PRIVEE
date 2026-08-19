"""Tests du depot de graphe : CRUD, voisinage, cycles, tri topo, rangs, Neo4j."""

from __future__ import annotations

import importlib
import importlib.util

import pytest

from supplyscore.domain.models import SupplyArc, SupplyNode
from supplyscore.graph import InMemoryGraphRepository


def make_node(node_id: str, project_id: str | None = None) -> SupplyNode:
    return SupplyNode(id=node_id, name=f"Node {node_id}", project_id=project_id)


@pytest.fixture
def repo() -> InMemoryGraphRepository:
    return InMemoryGraphRepository()


@pytest.fixture
def chain_repo() -> InMemoryGraphRepository:
    """Chaine A <- B <- C : C (fournisseur profond) -> B -> A (client final)."""
    repo = InMemoryGraphRepository()
    for node_id in ("A", "B", "C"):
        repo.add_node(make_node(node_id))
    repo.add_arc(SupplyArc(source_id="C", target_id="B"))
    repo.add_arc(SupplyArc(source_id="B", target_id="A"))
    return repo


# CRUD noeuds


def test_add_and_get_node(repo: InMemoryGraphRepository) -> None:
    node = make_node("A")
    repo.add_node(node)
    assert repo.get_node("A") is node
    assert repo.get_node("inconnu") is None


def test_add_duplicate_node_raises(repo: InMemoryGraphRepository) -> None:
    repo.add_node(make_node("A"))
    with pytest.raises(ValueError):
        repo.add_node(make_node("A"))


def test_update_node(repo: InMemoryGraphRepository) -> None:
    repo.add_node(make_node("A"))
    updated = SupplyNode(id="A", name="Renommé", rank=3)
    repo.update_node(updated)
    stored = repo.get_node("A")
    assert stored.name == "Renommé"
    assert stored.rank == 3


def test_update_unknown_node_raises(repo: InMemoryGraphRepository) -> None:
    with pytest.raises(KeyError):
        repo.update_node(make_node("fantome"))


def test_remove_node_also_removes_incident_arcs(chain_repo: InMemoryGraphRepository) -> None:
    chain_repo.remove_node("B")
    assert chain_repo.get_node("B") is None
    assert chain_repo.get_arc("C", "B") is None
    assert chain_repo.get_arc("B", "A") is None
    assert chain_repo.arcs() == []


def test_remove_unknown_node_raises(repo: InMemoryGraphRepository) -> None:
    with pytest.raises(KeyError):
        repo.remove_node("fantome")


# CRUD arcs


def test_add_and_get_arc(repo: InMemoryGraphRepository) -> None:
    repo.add_node(make_node("S"))
    repo.add_node(make_node("T"))
    arc = SupplyArc(source_id="S", target_id="T", gamma=0.3, beta=0.7)
    repo.add_arc(arc)
    assert repo.get_arc("S", "T") is arc
    assert repo.get_arc("T", "S") is None  # oriente


def test_add_arc_unknown_node_raises(repo: InMemoryGraphRepository) -> None:
    repo.add_node(make_node("S"))
    with pytest.raises(ValueError):
        repo.add_arc(SupplyArc(source_id="S", target_id="inconnu"))


def test_add_duplicate_arc_raises(chain_repo: InMemoryGraphRepository) -> None:
    with pytest.raises(ValueError):
        chain_repo.add_arc(SupplyArc(source_id="B", target_id="A"))


def test_remove_arc(chain_repo: InMemoryGraphRepository) -> None:
    chain_repo.remove_arc("B", "A")
    assert chain_repo.get_arc("B", "A") is None
    with pytest.raises(KeyError):
        chain_repo.remove_arc("B", "A")


def test_nodes_and_arcs_listing(chain_repo: InMemoryGraphRepository) -> None:
    assert {n.id for n in chain_repo.nodes()} == {"A", "B", "C"}
    assert {a.id for a in chain_repo.arcs()} == {"C->B", "B->A"}


# Voisinage


def test_predecessors_are_suppliers(chain_repo: InMemoryGraphRepository) -> None:
    assert [n.id for n in chain_repo.predecessors("B")] == ["C"]
    assert [n.id for n in chain_repo.predecessors("A")] == ["B"]
    assert chain_repo.predecessors("C") == []


def test_successors_are_clients(chain_repo: InMemoryGraphRepository) -> None:
    assert [n.id for n in chain_repo.successors("C")] == ["B"]
    assert [n.id for n in chain_repo.successors("B")] == ["A"]
    assert chain_repo.successors("A") == []


def test_nodes_by_project(repo: InMemoryGraphRepository) -> None:
    repo.add_node(make_node("A", project_id="p1"))
    repo.add_node(make_node("B", project_id="p1"))
    repo.add_node(make_node("C", project_id="p2"))
    assert {n.id for n in repo.nodes_by_project("p1")} == {"A", "B"}
    assert repo.nodes_by_project("p3") == []


# Cycles


def test_add_arc_refuses_cycle(chain_repo: InMemoryGraphRepository) -> None:
    with pytest.raises(ValueError):
        chain_repo.add_arc(SupplyArc(source_id="A", target_id="C"))
    # rollback : l'arc fautif n'a pas ete conserve
    assert chain_repo.get_arc("A", "C") is None
    assert len(chain_repo.arcs()) == 2


def test_add_arc_refuses_self_loop(repo: InMemoryGraphRepository) -> None:
    repo.add_node(make_node("A"))
    with pytest.raises(ValueError):
        repo.add_arc(SupplyArc(source_id="A", target_id="A"))


# Tri topologique


def test_topological_order_chain(chain_repo: InMemoryGraphRepository) -> None:
    # Des fournisseurs profonds vers le rang 0.
    assert chain_repo.topological_order() == ["C", "B", "A"]


def test_topological_order_is_valid_on_diamond(repo: InMemoryGraphRepository) -> None:
    # Diamant : D -> B -> A, D -> C -> A
    for node_id in ("A", "B", "C", "D"):
        repo.add_node(make_node(node_id))
    edges = [("D", "B"), ("D", "C"), ("B", "A"), ("C", "A")]
    for source_id, target_id in edges:
        repo.add_arc(SupplyArc(source_id=source_id, target_id=target_id))
    order = repo.topological_order()
    assert sorted(order) == ["A", "B", "C", "D"]
    position = {node_id: i for i, node_id in enumerate(order)}
    for source_id, target_id in edges:
        assert position[source_id] < position[target_id]


# Rangs


def test_assign_ranks_chain(chain_repo: InMemoryGraphRepository) -> None:
    ranks = chain_repo.assign_ranks()
    assert ranks == {"A": 0, "B": 1, "C": 2}
    assert chain_repo.get_node("A").rank == 0
    assert chain_repo.get_node("B").rank == 1
    assert chain_repo.get_node("C").rank == 2


def test_assign_ranks_diamond(repo: InMemoryGraphRepository) -> None:
    # Diamant asymetrique : D -> B -> A, D -> A (chemin le plus long : rang 2).
    for node_id in ("A", "B", "C", "D"):
        repo.add_node(make_node(node_id))
    repo.add_arc(SupplyArc(source_id="D", target_id="B"))
    repo.add_arc(SupplyArc(source_id="D", target_id="C"))
    repo.add_arc(SupplyArc(source_id="B", target_id="A"))
    repo.add_arc(SupplyArc(source_id="C", target_id="A"))
    # arc direct D -> A : le rang doit suivre le chemin le plus LONG
    repo.add_arc(SupplyArc(source_id="D", target_id="A"))
    ranks = repo.assign_ranks()
    assert ranks == {"A": 0, "B": 1, "C": 1, "D": 2}


def test_clear(chain_repo: InMemoryGraphRepository) -> None:
    chain_repo.clear()
    assert chain_repo.nodes() == []
    assert chain_repo.arcs() == []
    assert chain_repo.topological_order() == []


# Neo4j (sans serveur ni driver)

_NEO4J_INSTALLED = importlib.util.find_spec("neo4j") is not None


def test_neo4j_module_importable_without_driver() -> None:
    module = importlib.import_module("supplyscore.graph.neo4j_repo")
    assert hasattr(module, "Neo4jGraphRepository")


@pytest.mark.skipif(_NEO4J_INSTALLED, reason="le driver neo4j est installé")
def test_neo4j_instantiation_without_driver_raises_explicit_error() -> None:
    from supplyscore.graph import Neo4jGraphRepository

    with pytest.raises(ImportError, match=r"pip install supplyscore\[neo4j\]"):
        Neo4jGraphRepository("bolt://localhost:7687", "neo4j", "secret")
