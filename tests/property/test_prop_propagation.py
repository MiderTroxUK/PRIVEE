"""Propriétés Hypothesis de la propagation Ud/Ur sur DAG — PLAN.md, Lot 9.3 (E9).

Invariants vérifiés sur des DAG aléatoires (``RandomSupplyChainGenerator`` seedé
par Hypothesis, puis ``ud_local``/``ur_local``/γ/β re-tirés dans [0, 1]) :

1.  bornes : Ud, Ur ∈ [0, 1] pour tous les nœuds ;
2.  idempotence : deux ``propagate_all()`` sans changement ⇒ valeurs identiques (==) ;
3.  monotonie : augmenter ``ur_local`` (resp. ``ud_local``, γ) ne diminue aucun Ur
    (resp. aucun Ud) ;
4.  localité : modifier ``ur_local(i)`` ne touche Ur(k) que si k est atteignable
    depuis i via les arcs nominaux (fournisseur → client) — sinon delta exactement 0 ;
5.  stabilité : même graphe, ordres d'insertion mélangés ⇒ résultats à 1e-15 ;
6.  ``simulate_shock(i, valeur courante de i)`` ⇒ tous les deltas == 0 ;
7.  cas dégénérés : γ=0 partout ⇒ Ud == ud_local effectif ; β=1 et fournisseur
    saturé (ur_local=1) ⇒ son client a Ur == 1 exactement ;
8.  pureté : ``simulate_shock`` ne modifie aucune ``UrgencyState`` du dépôt ;
9.  sémantique DONE (décision de modélisation n°1) : un nœud DONE transmet
    l'urgence amont — test DESCRIPTIF, cf. docs/modele_mathematique.md ;
10. arcs backup : inertes pour Ud comme pour Ur, même avec une source saturée.
"""

from __future__ import annotations

import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core.status_rules import effective_ud_local
from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.models import ArcKind, SupplyArc, SupplyNode, TaskStatus, UrgencyState
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine

# Urgences et coefficients tirés dans [0, 1], sans NaN ni infinis (cf. PLAN.md, risques E9).
_UNIT = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


# --- Stratégies et aides -------------------------------------------------------------


@st.composite
def dag_cases(draw: st.DrawFn) -> tuple[list[SupplyNode], list[SupplyArc]]:
    """DAG par rangs via le générateur seedé ; ud_local/ur_local/γ/β re-tirés dans [0, 1]."""
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    n_ranks = draw(st.integers(min_value=1, max_value=3))
    _project, nodes, arcs = RandomSupplyChainGenerator(seed=seed).generate(
        n_ranks=n_ranks, breadth=(1, 2)
    )
    for node in nodes:
        node.urgency = UrgencyState(ud_local=draw(_UNIT), ur_local=draw(_UNIT), timestamp=0.0)
    for arc in arcs:
        arc.gamma = draw(_UNIT)
        arc.beta = draw(_UNIT)
    return nodes, arcs


def _build_repo(nodes: list[SupplyNode], arcs: list[SupplyArc]) -> InMemoryGraphRepository:
    """Charge nœuds puis arcs dans un dépôt mémoire et recalcule les rangs."""
    repo = InMemoryGraphRepository()
    for node in nodes:
        repo.add_node(node)
    for arc in arcs:
        repo.add_arc(arc)
    repo.assign_ranks()
    return repo


def _snapshot(repo: InMemoryGraphRepository) -> tuple[dict[str, float], dict[str, float]]:
    """Copie {id: ud} et {id: ur} en floats nus (les UrgencyState sont mutées en place)."""
    ud: dict[str, float] = {}
    ur: dict[str, float] = {}
    for node in repo.nodes():
        assert node.urgency.ud is not None
        assert node.urgency.ur is not None
        ud[node.id] = node.urgency.ud
        ur[node.id] = node.urgency.ur
    return ud, ur


def _reachable_via_nominal(repo: InMemoryGraphRepository, start_id: str) -> set[str]:
    """Ids atteignables depuis ``start_id`` (inclus) en suivant les arcs nominaux."""
    seen = {start_id}
    stack = [start_id]
    while stack:
        for succ in repo.successors(stack.pop()):
            if succ.id not in seen:
                seen.add(succ.id)
                stack.append(succ.id)
    return seen


def _chain_repo(
    ur_local: dict[str, float], beta: dict[tuple[str, str], float]
) -> InMemoryGraphRepository:
    """Chaîne historique C (rang 2) → B (rang 1) → A (rang 0, client final)."""
    repo = InMemoryGraphRepository()
    for node_id in ("A", "B", "C"):
        repo.add_node(
            SupplyNode(
                id=node_id,
                name=f"Node {node_id}",
                urgency=UrgencyState(ud_local=0.0, ur_local=ur_local[node_id], timestamp=0.0),
            )
        )
    for source_id, target_id in (("C", "B"), ("B", "A")):
        repo.add_arc(
            SupplyArc(source_id=source_id, target_id=target_id, beta=beta[(source_id, target_id)])
        )
    repo.assign_ranks()
    return repo


# --- 1. Bornes ------------------------------------------------------------------------


@given(case=dag_cases())
def test_propagated_values_stay_in_unit_interval(
    case: tuple[list[SupplyNode], list[SupplyArc]],
) -> None:
    """Avec ud_local/ur_local ∈ [0,1] en entrée, Ud et Ur restent dans [0,1] partout."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    states = PropagationEngine(repo).propagate_all()
    for state in states.values():
        assert state.ud is not None
        assert state.ur is not None
        assert 0.0 <= state.ud <= 1.0
        assert 0.0 <= state.ur <= 1.0


# --- 2. Idempotence ---------------------------------------------------------------------


@given(case=dag_cases())
def test_propagate_all_is_idempotent_bitwise(
    case: tuple[list[SupplyNode], list[SupplyArc]],
) -> None:
    """Deux propagate_all() sans changement ⇒ Ud/Ur strictement identiques (==)."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)
    engine.propagate_all()
    ud_first, ur_first = _snapshot(repo)
    engine.propagate_all()
    ud_second, ur_second = _snapshot(repo)
    assert ud_second == ud_first
    assert ur_second == ur_first


# --- 3. Monotonie ------------------------------------------------------------------------


@given(case=dag_cases(), data=st.data())
def test_increasing_ur_local_never_decreases_any_ur(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Augmenter le ur_local d'un nœud ⇒ aucun Ur ne diminue (tolérance 1e-12)."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)
    engine.propagate_all()
    _, ur_before = _snapshot(repo)

    node = nodes[data.draw(st.integers(0, len(nodes) - 1), label="indice du nœud")]
    old = node.urgency.ur_local
    assert old is not None
    bump = data.draw(_UNIT, label="fraction d'augmentation")
    node.urgency.ur_local = old + bump * (1.0 - old)  # reste dans [old, 1]

    engine.propagate_all()
    _, ur_after = _snapshot(repo)
    for node_id, before in ur_before.items():
        assert ur_after[node_id] >= before - 1e-12


@given(case=dag_cases(), data=st.data())
def test_increasing_ud_local_never_decreases_any_ud(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Augmenter le ud_local d'un nœud ⇒ aucun Ud ne diminue (tolérance 1e-12)."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)
    engine.propagate_all()
    ud_before, _ = _snapshot(repo)

    node = nodes[data.draw(st.integers(0, len(nodes) - 1), label="indice du nœud")]
    old = node.urgency.ud_local
    assert old is not None
    bump = data.draw(_UNIT, label="fraction d'augmentation")
    node.urgency.ud_local = old + bump * (1.0 - old)

    engine.propagate_all()
    ud_after, _ = _snapshot(repo)
    for node_id, before in ud_before.items():
        assert ud_after[node_id] >= before - 1e-12


@given(case=dag_cases(), data=st.data())
def test_increasing_gamma_never_decreases_any_ud(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Augmenter le γ d'un arc ⇒ aucun Ud ne diminue (tolérance 1e-12)."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)
    engine.propagate_all()
    ud_before, _ = _snapshot(repo)

    arc = arcs[data.draw(st.integers(0, len(arcs) - 1), label="indice de l'arc")]
    bump = data.draw(_UNIT, label="fraction d'augmentation")
    arc.gamma = arc.gamma + bump * (1.0 - arc.gamma)  # objet partagé avec le dépôt

    engine.propagate_all()
    ud_after, _ = _snapshot(repo)
    for node_id, before in ud_before.items():
        assert ud_after[node_id] >= before - 1e-12


# --- 4. Localité -----------------------------------------------------------------------


@given(case=dag_cases(), data=st.data())
def test_shock_only_touches_nodes_reachable_downstream(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """ΔUr(k) ≠ 0 seulement si k est atteignable depuis i (arcs nominaux) ; sinon delta == 0."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)

    origin = nodes[data.draw(st.integers(0, len(nodes) - 1), label="indice du nœud choqué")]
    new_value = data.draw(_UNIT, label="nouveau ur_local")
    deltas = engine.simulate_shock(origin.id, new_value)

    reachable = _reachable_via_nominal(repo, origin.id)
    for node_id, delta in deltas.items():
        if node_id not in reachable:
            # Hors du cône aval : mêmes entrées, mêmes opérations ⇒ delta EXACTEMENT 0.
            assert delta == 0.0


# --- 5. Stabilité vis-à-vis de l'ordre d'insertion ----------------------------------------


@given(case=dag_cases(), data=st.data())
def test_insertion_order_does_not_change_results(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Même graphe, add_node/add_arc permutés ⇒ Ud et Ur identiques à 1e-15."""
    nodes, arcs = case
    shuffled_nodes = data.draw(st.permutations(nodes), label="ordre des nœuds")
    shuffled_arcs = data.draw(st.permutations(arcs), label="ordre des arcs")

    # Deux dépôts construits sur des copies INDÉPENDANTES : la propagation mute les nœuds.
    repo_ref = _build_repo(copy.deepcopy(nodes), copy.deepcopy(arcs))
    repo_mix = _build_repo(copy.deepcopy(shuffled_nodes), copy.deepcopy(shuffled_arcs))
    PropagationEngine(repo_ref).propagate_all()
    PropagationEngine(repo_mix).propagate_all()

    ud_ref, ur_ref = _snapshot(repo_ref)
    ud_mix, ur_mix = _snapshot(repo_mix)
    assert set(ud_mix) == set(ud_ref)
    for node_id in ud_ref:
        assert abs(ud_mix[node_id] - ud_ref[node_id]) <= 1e-15
        assert abs(ur_mix[node_id] - ur_ref[node_id]) <= 1e-15


# --- 6. Choc neutre ----------------------------------------------------------------------


@given(case=dag_cases(), data=st.data())
def test_shock_at_current_value_yields_zero_deltas(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """simulate_shock(i, valeur courante de i) ⇒ tous les deltas == 0 exactement."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)

    node = nodes[data.draw(st.integers(0, len(nodes) - 1), label="indice du nœud")]
    assert node.urgency.ur_local is not None
    deltas = engine.simulate_shock(node.id, node.urgency.ur_local)
    assert all(delta == 0.0 for delta in deltas.values())


# --- 7. Cas dégénérés --------------------------------------------------------------------


@given(case=dag_cases())
def test_gamma_zero_everywhere_makes_ud_purely_local(
    case: tuple[list[SupplyNode], list[SupplyArc]],
) -> None:
    """γ=0 partout ⇒ Ud == ud_local effectif sur chaque nœud.

    Tolérance 1e-15 (et non ==) : l'identité passe par ``1 - (1 - x) * 1.0``,
    qui introduit au plus un demi-ulp de 1.0 (≈ 1.1e-16) de double arrondi —
    p. ex. ``1 - (1 - 0.1) == 0.09999999999999998``. Ce n'est pas un
    affaiblissement d'invariant : c'est la tolérance d'identité algébrique
    flottante prévue par PLAN.md (risques E9).
    """
    nodes, arcs = case
    for arc in arcs:
        arc.gamma = 0.0
    repo = _build_repo(nodes, arcs)
    PropagationEngine(repo).propagate_all()
    for node in repo.nodes():
        expected = effective_ud_local(node.status, node.urgency.ud_local)
        assert node.urgency.ud == pytest.approx(expected, abs=1e-15)


@given(case=dag_cases(), data=st.data())
def test_beta_one_with_saturated_supplier_saturates_client(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """β=1 et fournisseur à ur_local=1 ⇒ Ur du fournisseur ET du client == 1 exactement.

    Exactitude attendue : Ur_fournisseur = 1 - (1-1)·att = 1.0 ; côté client le
    facteur (1 - 1.0·1.0) annule le produit d'atténuation, d'où Ur = 1 - x·0 = 1.0.
    """
    nodes, arcs = case
    arc = arcs[data.draw(st.integers(0, len(arcs) - 1), label="indice de l'arc")]
    arc.beta = 1.0
    by_id = {node.id: node for node in nodes}
    by_id[arc.source_id].urgency.ur_local = 1.0

    repo = _build_repo(nodes, arcs)
    PropagationEngine(repo).propagate_all()
    supplier = repo.get_node(arc.source_id)
    client = repo.get_node(arc.target_id)
    assert supplier is not None and client is not None
    assert supplier.urgency.ur == 1.0
    assert client.urgency.ur == 1.0


# --- 8. Pureté de simulate_shock -----------------------------------------------------------


@given(case=dag_cases(), data=st.data())
def test_simulate_shock_leaves_repository_state_untouched(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """simulate_shock ne modifie aucune UrgencyState persistée (comparaison de copies)."""
    nodes, arcs = case
    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)
    engine.propagate_all()  # part d'un état propagé réaliste avant le what-if

    before = {node.id: copy.deepcopy(node.urgency) for node in repo.nodes()}
    origin = nodes[data.draw(st.integers(0, len(nodes) - 1), label="indice du nœud")]
    engine.simulate_shock(origin.id, data.draw(_UNIT, label="nouveau ur_local"))

    after = {node.id: node.urgency for node in repo.nodes()}
    assert after == before  # UrgencyState est un dataclass : égalité champ à champ


# --- 9. Sémantique DONE (descriptif) + cas chiffré de référence -----------------------------


def test_done_node_still_transmits_upstream_urgency() -> None:
    """DESCRIPTIF — décision de modélisation n°1 (docs/modele_mathematique.md).

    Un nœud DONE annule sa contribution PROPRE (ur_local effectif 0.0,
    cf. supplyscore.core.status_rules) mais TRANSMET l'urgence de ses
    fournisseurs : le risque amont traverse les tâches terminées (écart n°11
    du PLAN, tranché en E9). Chaîne C → B → A, B en DONE, C.ur_local = 1.0 :

        Ur_C = 1.0
        Ur_B = 1 - (1 - 0.0) · (1 - 0.5·1.0)  = 0.5    (propre contribution annulée)
        Ur_A = 1 - (1 - 0.1) · (1 - 0.7·0.5)  = 0.415  > Ur_loc(A) = 0.1
    """
    repo = _chain_repo(
        ur_local={"A": 0.1, "B": 0.3, "C": 1.0},
        beta={("C", "B"): 0.5, ("B", "A"): 0.7},
    )
    engine = PropagationEngine(repo)
    engine.apply_status("B", TaskStatus.DONE)
    engine.propagate_all()

    node_a = repo.get_node("A")
    node_b = repo.get_node("B")
    assert node_a is not None and node_b is not None
    assert node_b.urgency.ur == pytest.approx(0.5, abs=1e-12)
    assert node_a.urgency.ur is not None and node_a.urgency.ur > 0.1  # Ur(A) > Ur_loc(A)
    assert node_a.urgency.ur == pytest.approx(0.415, abs=1e-12)


def test_reference_chain_ur_a_equals_0_4213() -> None:
    """Cas chiffré historique : C → B → A, β=(0.5, 0.7), ur_loc=(0.1, 0.3, 0.6).

    Recalcul manuel :
        Ur_C = 0.6
        Ur_B = 1 - (1 - 0.3) · (1 - 0.5·0.6)  = 1 - 0.7·0.70  = 0.51
        Ur_A = 1 - (1 - 0.1) · (1 - 0.7·0.51) = 1 - 0.9·0.643 = 0.4213
    """
    repo = _chain_repo(
        ur_local={"A": 0.1, "B": 0.3, "C": 0.6},
        beta={("C", "B"): 0.5, ("B", "A"): 0.7},
    )
    PropagationEngine(repo).propagate_all()
    node_a = repo.get_node("A")
    assert node_a is not None
    assert node_a.urgency.ur == pytest.approx(0.4213, abs=1e-4)


# --- 10. Arcs backup inertes ----------------------------------------------------------------


@given(case=dag_cases(), data=st.data())
def test_backup_arc_with_saturated_source_changes_nothing(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Un arc backup (même β=1, source à ur_local=1) ne change ni Ud ni Ur (== strict)."""
    nodes, arcs = case
    arc = arcs[data.draw(st.integers(0, len(arcs) - 1), label="indice de l'arc nominal")]
    by_id = {node.id: node for node in nodes}
    by_id[arc.target_id].urgency.ur_local = 1.0  # future source du backup, saturée

    repo = _build_repo(nodes, arcs)
    engine = PropagationEngine(repo)
    engine.propagate_all()
    ud_before, ur_before = _snapshot(repo)

    # Backup target → source : jamais déjà présent (l'inverse nominal fermerait un
    # cycle, impossible dans un DAG) et source ≠ target. Il peut fermer un cycle
    # APPARENT : autorisé pour un backup, purement documentaire.
    repo.add_arc(
        SupplyArc(
            source_id=arc.target_id,
            target_id=arc.source_id,
            gamma=1.0,
            beta=1.0,
            kind_arc=ArcKind.BACKUP,
        )
    )
    engine.propagate_all()
    ud_after, ur_after = _snapshot(repo)
    assert ur_after == ur_before
    assert ud_after == ud_before
