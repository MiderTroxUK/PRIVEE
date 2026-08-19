"""Tests des arcs de secours (backup) : purement visuels, inertes dans tous les calculs."""

from __future__ import annotations

import pytest

from supplyscore.domain.models import ArcKind, SupplyArc, SupplyNode, UrgencyState
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine
from supplyscore.web_ui.components.figures import dag_figure

UR_LOCAL = {"A": 0.2, "B": 0.5, "C": 1.0}
UD_LOCAL = {"A": 0.3, "B": 0.1, "C": 0.4}


def make_node(node_id: str, *, rank: int = 0) -> SupplyNode:
    return SupplyNode(
        id=node_id,
        name=f"Node {node_id}",
        rank=rank,
        urgency=UrgencyState(ud_local=UD_LOCAL.get(node_id), ur_local=UR_LOCAL.get(node_id)),
    )


def build_repo(*, with_backup: bool) -> InMemoryGraphRepository:
    """A <- B nominal (B fournisseur de A) ; C -> A en backup si demande.

    ur_local C = 1.0 et beta = 0.9 partout : si l'arc backup comptait,
    Ur_A serait fortement tire vers le haut.
    """
    repo = InMemoryGraphRepository()
    for node_id in ("A", "B", "C"):
        repo.add_node(make_node(node_id))
    repo.add_arc(SupplyArc(source_id="B", target_id="A", gamma=0.7, beta=0.9))
    if with_backup:
        repo.add_arc(
            SupplyArc(source_id="C", target_id="A", gamma=0.7, beta=0.9, kind_arc=ArcKind.BACKUP)
        )
    return repo


# Propagation : le backup est inerte


def test_propagate_all_ur_identical_with_or_without_backup() -> None:
    repo_with = build_repo(with_backup=True)
    repo_without = build_repo(with_backup=False)

    states_with = PropagationEngine(repo_with).propagate_all()
    states_without = PropagationEngine(repo_without).propagate_all()

    # Identite bit a bit (==), pas une simple approximation.
    assert states_with["A"].ur == states_without["A"].ur
    assert states_with["B"].ur == states_without["B"].ur
    assert states_with["A"].ud == states_without["A"].ud
    assert states_with["B"].ud == states_without["B"].ud


def test_simulate_shock_on_backup_source_has_zero_delta_on_target() -> None:
    repo = InMemoryGraphRepository()
    for node_id in ("A", "B", "C"):
        repo.add_node(make_node(node_id))
    repo.add_arc(SupplyArc(source_id="B", target_id="A", beta=0.9))
    repo.add_arc(SupplyArc(source_id="C", target_id="A", beta=0.9, kind_arc=ArcKind.BACKUP))
    node_c = repo.get_node("C")
    assert node_c is not None
    node_c.urgency.ur_local = 0.1  # baseline basse pour un choc visible sur C

    deltas = PropagationEngine(repo).simulate_shock("C", 1.0)

    assert deltas["C"] > 0.0  # le choc existe bien sur la source
    assert deltas["A"] == 0.0  # ... mais ne traverse PAS l'arc backup
    assert deltas["B"] == 0.0


# Tri topologique et rangs


def test_topological_order_and_ranks_unchanged_by_backup() -> None:
    repo_with = build_repo(with_backup=True)
    repo_without = build_repo(with_backup=False)

    assert repo_with.topological_order() == repo_without.topological_order()
    assert repo_with.assign_ranks() == repo_without.assign_ranks()
    # Le backup C -> A ne cree pas de dependance de rang : C reste un puits.
    node_c = repo_with.get_node("C")
    assert node_c is not None
    assert node_c.rank == 0


def test_backup_arc_may_close_apparent_cycle() -> None:
    repo = InMemoryGraphRepository()
    repo.add_node(make_node("A"))
    repo.add_node(make_node("B"))
    repo.add_arc(SupplyArc(source_id="A", target_id="B"))
    # B -> A en backup : cycle apparent accepte car l'arc est inerte.
    repo.add_arc(SupplyArc(source_id="B", target_id="A", kind_arc=ArcKind.BACKUP))

    assert repo.get_arc("B", "A") is not None
    assert repo.topological_order() == ["A", "B"]  # le backup n'ordonne rien


def test_backup_self_loop_refused() -> None:
    repo = InMemoryGraphRepository()
    repo.add_node(make_node("A"))
    with pytest.raises(ValueError):
        repo.add_arc(SupplyArc(source_id="A", target_id="A", kind_arc=ArcKind.BACKUP))


def test_duplicate_arc_refused_across_kinds() -> None:
    repo = InMemoryGraphRepository()
    repo.add_node(make_node("A"))
    repo.add_node(make_node("B"))
    repo.add_arc(SupplyArc(source_id="B", target_id="A"))
    with pytest.raises(ValueError):
        repo.add_arc(SupplyArc(source_id="B", target_id="A", kind_arc=ArcKind.BACKUP))


# Filtrage par nature : arcs, predecessors, successors


def test_arcs_filtering_by_kinds() -> None:
    repo = build_repo(with_backup=True)

    assert {a.id for a in repo.arcs()} == {"B->A", "C->A"}  # defaut None = tous
    assert {a.id for a in repo.arcs(kinds=None)} == {"B->A", "C->A"}
    assert {a.id for a in repo.arcs(kinds=("backup",))} == {"C->A"}
    assert {a.id for a in repo.arcs(kinds=("nominal",))} == {"B->A"}


def test_predecessors_default_ignores_backup() -> None:
    repo = build_repo(with_backup=True)

    assert {n.id for n in repo.predecessors("A")} == {"B"}
    assert {n.id for n in repo.predecessors("A", kinds=("nominal", "backup"))} == {"B", "C"}
    assert {n.id for n in repo.predecessors("A", kinds=("backup",))} == {"C"}


def test_successors_default_ignores_backup() -> None:
    repo = build_repo(with_backup=True)

    assert repo.successors("C") == []
    assert {n.id for n in repo.successors("C", kinds=("nominal", "backup"))} == {"A"}


def test_crud_covers_backup_arcs() -> None:
    repo = build_repo(with_backup=True)

    backup = repo.get_arc("C", "A")
    assert backup is not None
    assert backup.kind_arc is ArcKind.BACKUP

    repo.remove_arc("C", "A")
    assert repo.get_arc("C", "A") is None
    with pytest.raises(KeyError):
        repo.remove_arc("C", "A")


def test_remove_node_purges_incident_backup_arcs() -> None:
    repo = build_repo(with_backup=True)
    repo.remove_node("C")
    assert repo.get_arc("C", "A") is None
    assert repo.arcs(kinds=("backup",)) == []


def test_clear_purges_backup_arcs() -> None:
    repo = build_repo(with_backup=True)
    repo.clear()
    assert repo.arcs() == []


# Rendu : trace pointillee dediee


def test_dag_figure_renders_backup_as_dashed_trace() -> None:
    nodes = [make_node("A", rank=0), make_node("B", rank=1), make_node("C", rank=1)]
    arcs = [
        SupplyArc(source_id="B", target_id="A"),
        SupplyArc(source_id="C", target_id="A", kind_arc=ArcKind.BACKUP),
    ]
    fig = dag_figure(nodes, arcs)

    dashed = [t for t in fig.data if t.mode == "lines" and t.line.dash == "dash"]
    assert len(dashed) == 1
    assert dashed[0].hovertext == "Arc de secours (inactif)"
    # E14.3 : plus AUCUNE annotation de fleche par arc - la direction est portee par la trace de marqueurs " sens-arcs ", qui ignore les arcs backup.
    assert not any(a.showarrow for a in fig.layout.annotations)
    sens = next(t for t in fig.data if t.name == "sens-arcs")
    assert len(sens.x) == 2  # une paire (orientation, fleche) pour le SEUL arc nominal


def test_dag_figure_without_backup_has_no_dashed_trace() -> None:
    nodes = [make_node("A", rank=0), make_node("B", rank=1)]
    arcs = [SupplyArc(source_id="B", target_id="A")]
    fig = dag_figure(nodes, arcs)
    assert all(t.line.dash != "dash" for t in fig.data if t.mode == "lines")
