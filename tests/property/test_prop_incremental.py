"""L'INVARIANT CENTRAL E14.4 (hypothesis) : incrémental == complet à 1e-12.

Pour TOUTE séquence aléatoire de modifications (``ud_local``, ``ur_local``,
statuts) sur un DAG aléatoire (``RandomSupplyChainGenerator`` seedé par
Hypothesis), ``propagate_incremental`` doit produire EXACTEMENT les mêmes
Ud/Ur que ``propagate_all`` sur tous les nœuds (tolérance 1e-12). La
comparaison oppose deux moteurs JUMEAUX construits sur des copies
indépendantes du même graphe : l'un ne propage que par l'incrémental
(``mark_dirty_*`` au fil des modifications), l'autre repasse au complet à
chaque étape.

Le piège classique du nœud « frontière » (un seul prédécesseur affecté, les
autres relus du cache) est couvert par construction : les DAG générés
contiennent des diamants et chaque étape compare TOUS les nœuds.

Les modifications passent ici directement par le moteur + ``mark_dirty_*``
(variante autorisée par PLAN.md E14.4 « via les chemins orchestrateur OU
directement moteur+mark_dirty ») : le câblage orchestrateur est couvert par
``tests/test_graph_incremental.py``.
"""

from __future__ import annotations

import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.models import SupplyArc, SupplyNode, TaskStatus, UrgencyState
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine

# Urgences tirées dans [0, 1], sans NaN ni infinis (cf. PLAN.md, risques E9).
_UNIT = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

#: Une modification = (champ, indice de nœud, nouvelle valeur).
_Modification = tuple[str, int, float | TaskStatus]


@st.composite
def incremental_cases(
    draw: st.DrawFn,
) -> tuple[list[SupplyNode], list[SupplyArc], list[_Modification]]:
    """DAG seedé + séquence de 1 à 6 modifications (ud_local, ur_local, statut)."""
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    n_ranks = draw(st.integers(min_value=1, max_value=3))
    _project, nodes, arcs = RandomSupplyChainGenerator(seed=seed).generate(
        n_ranks=n_ranks, breadth=(1, 2)
    )
    for node in nodes:
        node.urgency = UrgencyState(ud_local=draw(_UNIT), ur_local=draw(_UNIT), timestamp=0.0)
    modifications: list[_Modification] = []
    for _ in range(draw(st.integers(min_value=1, max_value=6))):
        kind = draw(st.sampled_from(["ud_local", "ur_local", "statut"]))
        index = draw(st.integers(min_value=0, max_value=len(nodes) - 1))
        value: float | TaskStatus = (
            draw(st.sampled_from(list(TaskStatus))) if kind == "statut" else draw(_UNIT)
        )
        modifications.append((kind, index, value))
    return nodes, arcs, modifications


def _build_repo(nodes: list[SupplyNode], arcs: list[SupplyArc]) -> InMemoryGraphRepository:
    """Charge nœuds puis arcs dans un dépôt mémoire et recalcule les rangs."""
    repo = InMemoryGraphRepository()
    for node in nodes:
        repo.add_node(node)
    for arc in arcs:
        repo.add_arc(arc)
    repo.assign_ranks()
    return repo


def _apply(
    repo: InMemoryGraphRepository,
    node_id: str,
    kind: str,
    value: float | TaskStatus,
) -> None:
    """Applique une modification sur le nœud du dépôt (sans propager)."""
    node = repo.get_node(node_id)
    assert node is not None
    if kind == "ud_local":
        assert isinstance(value, float)
        node.urgency.ud_local = value
    elif kind == "ur_local":
        assert isinstance(value, float)
        node.urgency.ur_local = value
    else:  # statut
        assert isinstance(value, TaskStatus)
        node.status = value
    repo.update_node(node)


def _assert_states_equal(
    states_inc: dict[str, UrgencyState], states_full: dict[str, UrgencyState]
) -> None:
    """Ud et Ur identiques à 1e-12 sur TOUS les nœuds, mêmes ensembles d'ids."""
    assert set(states_inc) == set(states_full)
    for node_id, full in states_full.items():
        inc = states_inc[node_id]
        assert inc.ud == pytest.approx(full.ud, abs=1e-12)
        assert inc.ur == pytest.approx(full.ur, abs=1e-12)


@given(case=incremental_cases())
def test_incremental_equals_full_for_any_modification_sequence(
    case: tuple[list[SupplyNode], list[SupplyArc], list[_Modification]],
) -> None:
    """Après CHAQUE modification, propagate_incremental == propagate_all à 1e-12.

    Le statut ne modifie que le Ur effectif (décision de modélisation n°1 :
    ``effective_ud_local`` ignore le statut), d'où ``mark_dirty_ur`` seul sur
    un changement de statut.
    """
    nodes, arcs, modifications = case
    repo_inc = _build_repo(copy.deepcopy(nodes), copy.deepcopy(arcs))
    repo_full = _build_repo(copy.deepcopy(nodes), copy.deepcopy(arcs))
    engine_inc = PropagationEngine(repo_inc)
    engine_full = PropagationEngine(repo_full)
    # Base commune : les deux jumeaux partent du même état entièrement propagé.
    _assert_states_equal(engine_inc.propagate_all(), engine_full.propagate_all())

    ids = [node.id for node in nodes]
    for kind, index, value in modifications:
        node_id = ids[index]
        _apply(repo_inc, node_id, kind, value)
        _apply(repo_full, node_id, kind, value)
        if kind == "ud_local":
            engine_inc.mark_dirty_ud(node_id)
        else:  # ur_local comme statut n'affectent que le Ur effectif
            engine_inc.mark_dirty_ur(node_id)
        _assert_states_equal(engine_inc.propagate_incremental(), engine_full.propagate_all())


@given(case=incremental_cases())
def test_incremental_without_dirty_is_idempotent_bitwise(
    case: tuple[list[SupplyNode], list[SupplyArc], list[_Modification]],
) -> None:
    """Sans nœud sale, propagate_incremental ne change RIEN (identité bit à bit)."""
    nodes, arcs, modifications = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)
    engine.propagate_all()
    for kind, index, value in modifications:
        _apply(repo, nodes[index].id, kind, value)
        if kind == "ud_local":
            engine.mark_dirty_ud(nodes[index].id)
        else:
            engine.mark_dirty_ur(nodes[index].id)
    engine.propagate_incremental()  # absorbe les modifications, vide les sales

    before = {node.id: (node.urgency.ud, node.urgency.ur) for node in repo.nodes()}
    engine.propagate_incremental()  # plus rien de sale
    after = {node.id: (node.urgency.ud, node.urgency.ur) for node in repo.nodes()}
    assert after == before


@given(case=incremental_cases())
def test_invalidate_then_incremental_equals_full(
    case: tuple[list[SupplyNode], list[SupplyArc], list[_Modification]],
) -> None:
    """invalidate() (tout sale) : l'incrémental délègue et égale le complet."""
    nodes, arcs, modifications = case
    repo_inc = _build_repo(copy.deepcopy(nodes), copy.deepcopy(arcs))
    repo_full = _build_repo(copy.deepcopy(nodes), copy.deepcopy(arcs))
    engine_inc = PropagationEngine(repo_inc)
    engine_full = PropagationEngine(repo_full)
    engine_inc.propagate_all()
    engine_full.propagate_all()

    ids = [node.id for node in nodes]
    for kind, index, value in modifications:
        _apply(repo_inc, ids[index], kind, value)
        _apply(repo_full, ids[index], kind, value)
    engine_inc.invalidate()  # AUCUN mark_dirty_* : tout doit être repassé
    _assert_states_equal(engine_inc.propagate_incremental(), engine_full.propagate_all())
