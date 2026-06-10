"""Tests du PropagationEngine : Ud descendant, Ur montant, statuts, chocs."""

from __future__ import annotations

import pytest

from supplyscore.domain.models import SupplyArc, SupplyNode, TaskStatus, UrgencyState
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine

APPROX = 1e-12

# Chaîne C (rang 2, fournisseur profond) -> B (rang 1) -> A (rang 0, client final)
UD_LOCAL = {"A": 0.5, "B": 0.2, "C": 0.1}
UR_LOCAL = {"A": 0.1, "B": 0.3, "C": 0.6}
GAMMA = {("C", "B"): 0.8, ("B", "A"): 0.6}
BETA = {("C", "B"): 0.5, ("B", "A"): 0.7}


def make_chain(
    gamma: dict[tuple[str, str], float] = GAMMA,
    beta: dict[tuple[str, str], float] = BETA,
) -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()
    for node_id in ("A", "B", "C"):
        repo.add_node(
            SupplyNode(
                id=node_id,
                name=f"Node {node_id}",
                urgency=UrgencyState(ud_local=UD_LOCAL[node_id], ur_local=UR_LOCAL[node_id]),
            )
        )
    for source_id, target_id in (("C", "B"), ("B", "A")):
        repo.add_arc(
            SupplyArc(
                source_id=source_id,
                target_id=target_id,
                gamma=gamma[(source_id, target_id)],
                beta=beta[(source_id, target_id)],
            )
        )
    repo.assign_ranks()
    return repo


# --- Calcul analytique sur la chaîne ------------------------------------------------


def test_ud_descending_chain_analytic() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()

    # Rang 0 : pas de client, Ud = Ud_local.
    ud_a = UD_LOCAL["A"]
    # Ud_B = 1 - (1 - 0.2) * (1 - 0.6 * 0.5) = 0.44
    ud_b = 1 - (1 - UD_LOCAL["B"]) * (1 - GAMMA[("B", "A")] * ud_a)
    # Ud_C = 1 - (1 - 0.1) * (1 - 0.8 * 0.44) = 0.4168
    ud_c = 1 - (1 - UD_LOCAL["C"]) * (1 - GAMMA[("C", "B")] * ud_b)

    assert repo.get_node("A").urgency.ud == pytest.approx(0.5, abs=APPROX)
    assert repo.get_node("B").urgency.ud == pytest.approx(0.44, abs=APPROX)
    assert repo.get_node("C").urgency.ud == pytest.approx(0.4168, abs=APPROX)
    assert repo.get_node("B").urgency.ud == pytest.approx(ud_b, abs=APPROX)
    assert repo.get_node("C").urgency.ud == pytest.approx(ud_c, abs=APPROX)


def test_ur_ascending_chain_analytic() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()

    # Rang 2 : pas de fournisseur, Ur = Ur_local.
    ur_c = UR_LOCAL["C"]
    # Ur_B = 1 - (1 - 0.3) * (1 - 0.5 * 0.6) = 0.51
    ur_b = 1 - (1 - UR_LOCAL["B"]) * (1 - BETA[("C", "B")] * ur_c)
    # Ur_A = 1 - (1 - 0.1) * (1 - 0.7 * 0.51) = 0.4213
    ur_a = 1 - (1 - UR_LOCAL["A"]) * (1 - BETA[("B", "A")] * ur_b)

    assert repo.get_node("C").urgency.ur == pytest.approx(0.6, abs=APPROX)
    assert repo.get_node("B").urgency.ur == pytest.approx(0.51, abs=APPROX)
    assert repo.get_node("A").urgency.ur == pytest.approx(0.4213, abs=APPROX)
    assert repo.get_node("A").urgency.ur == pytest.approx(ur_a, abs=APPROX)
    assert repo.get_node("B").urgency.ur == pytest.approx(ur_b, abs=APPROX)


def test_propagate_all_returns_states_and_stamps_time() -> None:
    repo = make_chain()
    before = repo.get_node("A").urgency.timestamp
    result = PropagationEngine(repo).propagate_all()
    assert set(result) == {"A", "B", "C"}
    for state in result.values():
        assert isinstance(state, UrgencyState)
        assert 0.0 <= state.ud <= 1.0
        assert 0.0 <= state.ur <= 1.0
        assert state.timestamp >= before


def test_none_locals_treated_as_zero() -> None:
    repo = InMemoryGraphRepository()
    repo.add_node(SupplyNode(id="A", name="A"))  # urgency par défaut : tout None
    repo.add_node(SupplyNode(id="B", name="B"))
    repo.add_arc(SupplyArc(source_id="B", target_id="A", gamma=0.9, beta=0.9))
    states = PropagationEngine(repo).propagate_all()
    assert states["A"].ud == 0.0
    assert states["B"].ud == 0.0
    assert states["A"].ur == 0.0
    assert states["B"].ur == 0.0


# --- Coefficients nuls : pas de propagation ----------------------------------------


def test_gamma_zero_blocks_descending_propagation() -> None:
    repo = make_chain(gamma={("C", "B"): 0.0, ("B", "A"): 0.0})
    PropagationEngine(repo).propagate_all()
    for node_id in ("A", "B", "C"):
        assert repo.get_node(node_id).urgency.ud == pytest.approx(UD_LOCAL[node_id], abs=APPROX)


def test_beta_zero_blocks_ascending_propagation() -> None:
    repo = make_chain(beta={("C", "B"): 0.0, ("B", "A"): 0.0})
    PropagationEngine(repo).propagate_all()
    for node_id in ("A", "B", "C"):
        assert repo.get_node(node_id).urgency.ur == pytest.approx(UR_LOCAL[node_id], abs=APPROX)


# --- Règles de statut -----------------------------------------------------------


def test_abandoned_deep_supplier_raises_ur_down_to_rank0() -> None:
    repo = make_chain()
    baseline_a = PropagationEngine(repo)._compute_ur()["A"]

    repo.get_node("C").status = TaskStatus.ABANDONED
    PropagationEngine(repo).propagate_all()

    # Ur_C forcé à 1.0, et le rang 0 doit monter par rapport à la référence.
    assert repo.get_node("C").urgency.ur == pytest.approx(1.0, abs=APPROX)
    ur_b = 1 - (1 - UR_LOCAL["B"]) * (1 - BETA[("C", "B")] * 1.0)  # 0.65
    ur_a = 1 - (1 - UR_LOCAL["A"]) * (1 - BETA[("B", "A")] * ur_b)  # 0.5095
    assert repo.get_node("B").urgency.ur == pytest.approx(ur_b, abs=APPROX)
    assert repo.get_node("A").urgency.ur == pytest.approx(ur_a, abs=APPROX)
    assert repo.get_node("A").urgency.ur > baseline_a


def test_done_node_has_null_local_contribution() -> None:
    repo = make_chain()
    repo.get_node("B").status = TaskStatus.DONE
    PropagationEngine(repo).propagate_all()

    # Ur_loc_B forcé à 0 : seul l'amont (C) contribue à Ur_B.
    ur_b = 1 - (1 - 0.0) * (1 - BETA[("C", "B")] * UR_LOCAL["C"])  # 0.3
    ur_a = 1 - (1 - UR_LOCAL["A"]) * (1 - BETA[("B", "A")] * ur_b)  # 0.289
    assert repo.get_node("B").urgency.ur == pytest.approx(ur_b, abs=APPROX)
    assert repo.get_node("A").urgency.ur == pytest.approx(ur_a, abs=APPROX)
    # ur_local n'est pas écrasé par la règle de statut (valeur du core préservée).
    assert repo.get_node("B").urgency.ur_local == pytest.approx(UR_LOCAL["B"])


def test_apply_status_sets_status_without_propagating() -> None:
    # Nouveau contrat : apply_status pose le statut, la propagation est explicite.
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()
    ur_before = {nid: repo.get_node(nid).urgency.ur for nid in ("A", "B", "C")}

    engine.apply_status("C", TaskStatus.ABANDONED)

    assert repo.get_node("C").status is TaskStatus.ABANDONED
    # Aucune propagation tant que propagate_all n'est pas rappelé.
    for node_id, ur in ur_before.items():
        assert repo.get_node(node_id).urgency.ur == pytest.approx(ur, abs=APPROX)


def test_apply_status_then_propagate_all_repropagates() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()
    ur_a_before = repo.get_node("A").urgency.ur

    engine.apply_status("C", TaskStatus.ABANDONED)
    states = engine.propagate_all()

    # Résultat final identique à l'ancienne sémantique (apply_status propagateur).
    assert repo.get_node("C").status is TaskStatus.ABANDONED
    assert states["C"].ur == pytest.approx(1.0, abs=APPROX)
    assert repo.get_node("A").urgency.ur > ur_a_before


def test_apply_status_unknown_node_raises() -> None:
    repo = make_chain()
    with pytest.raises(KeyError):
        PropagationEngine(repo).apply_status("fantome", TaskStatus.DONE)


# --- Choc what-if ------------------------------------------------------------------


def test_simulate_shock_does_not_persist() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()
    snapshot = {
        node_id: (
            repo.get_node(node_id).urgency.ur_local,
            repo.get_node(node_id).urgency.ur,
            repo.get_node(node_id).status,
        )
        for node_id in ("A", "B", "C")
    }

    engine.simulate_shock("C", 1.0)

    for node_id, (ur_local, ur, status) in snapshot.items():
        node = repo.get_node(node_id)
        assert node.urgency.ur_local == ur_local
        assert node.urgency.ur == ur
        assert node.status is status


def test_simulate_shock_deltas_are_consistent() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    deltas = engine.simulate_shock("C", 1.0)

    # Référence et état choqué calculés à la main.
    ur_c0, ur_c1 = UR_LOCAL["C"], 1.0
    ur_b0 = 1 - (1 - UR_LOCAL["B"]) * (1 - BETA[("C", "B")] * ur_c0)
    ur_b1 = 1 - (1 - UR_LOCAL["B"]) * (1 - BETA[("C", "B")] * ur_c1)
    ur_a0 = 1 - (1 - UR_LOCAL["A"]) * (1 - BETA[("B", "A")] * ur_b0)
    ur_a1 = 1 - (1 - UR_LOCAL["A"]) * (1 - BETA[("B", "A")] * ur_b1)

    assert deltas["C"] == pytest.approx(ur_c1 - ur_c0, abs=APPROX)
    assert deltas["B"] == pytest.approx(ur_b1 - ur_b0, abs=APPROX)
    assert deltas["A"] == pytest.approx(ur_a1 - ur_a0, abs=APPROX)
    # Le choc s'atténue en descendant vers le rang 0 mais reste positif.
    assert deltas["C"] > deltas["B"] > deltas["A"] > 0.0


def test_simulate_shock_no_change_gives_zero_deltas() -> None:
    repo = make_chain()
    deltas = PropagationEngine(repo).simulate_shock("C", UR_LOCAL["C"])
    assert all(abs(d) < APPROX for d in deltas.values())


def test_simulate_shock_unknown_node_raises() -> None:
    repo = make_chain()
    with pytest.raises(KeyError):
        PropagationEngine(repo).simulate_shock("fantome", 1.0)


# --- Clip [0, 1] ------------------------------------------------------------------


def test_propagated_values_are_clipped() -> None:
    repo = InMemoryGraphRepository()
    # ur_local > 1 autorisé localement (tâche en retard), mais Ur propagé clipé.
    repo.add_node(SupplyNode(id="A", name="A", urgency=UrgencyState(ud_local=1.5, ur_local=2.0)))
    repo.add_node(SupplyNode(id="B", name="B", urgency=UrgencyState(ud_local=0.5, ur_local=0.5)))
    repo.add_arc(SupplyArc(source_id="B", target_id="A", gamma=1.0, beta=1.0))
    states = PropagationEngine(repo).propagate_all()
    for state in states.values():
        assert 0.0 <= state.ud <= 1.0
        assert 0.0 <= state.ur <= 1.0
    assert states["A"].ur == 1.0
