"""Tests du PropagationEngine : Ud descendant, Ur montant, statuts, chocs.

Couvre aussi (HÉLIOS v7, U3) : ``simulate_shock_detailed`` (ΔUr + Δl
log-survie du jumeau ε-régularisé), ``compute_ur_batch`` /
``compute_ell_batch`` (S tirages vectorisés, équivalence S=1 avec les passes
scalaires sur graphes aléatoires).
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from supplyscore.data.generator import RandomSupplyChainGenerator
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


# --- Choc détaillé Δl (dé-saturation, U3) --------------------------------------------


def make_saturated_chain() -> InMemoryGraphRepository:
    """Chaîne TOTALEMENT saturée : β=1 partout et C à ur_local=1.0 ⇒ Ur=1.0 partout."""
    return _make_custom_chain(
        ur_local={"A": 0.1, "B": 0.3, "C": 1.0},
        beta={("C", "B"): 1.0, ("B", "A"): 1.0},
    )


def _make_custom_chain(
    ur_local: dict[str, float], beta: dict[tuple[str, str], float]
) -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()
    for node_id in ("A", "B", "C"):
        repo.add_node(
            SupplyNode(
                id=node_id,
                name=f"Node {node_id}",
                urgency=UrgencyState(ud_local=0.2, ur_local=ur_local[node_id]),
            )
        )
    for source_id, target_id in (("C", "B"), ("B", "A")):
        repo.add_arc(
            SupplyArc(
                source_id=source_id,
                target_id=target_id,
                gamma=0.5,
                beta=beta[(source_id, target_id)],
            )
        )
    repo.assign_ranks()
    return repo


def test_simulate_shock_detailed_delta_ur_matches_simulate_shock() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    detail = engine.simulate_shock_detailed("C", 1.0)
    assert detail.delta_ur == engine.simulate_shock("C", 1.0)  # même pipeline, bit à bit


def test_simulate_shock_detailed_delta_ell_analytic_on_chain() -> None:
    # Hors saturation, Δl_i = ln((1 − Ur_i)/(1 − Ur'_i)) du pipeline standard.
    repo = make_chain()
    engine = PropagationEngine(repo)
    baseline = engine._compute_ur()
    shocked = engine._compute_ur(overrides={"C": 1.0})

    detail = engine.simulate_shock_detailed("C", 1.0)

    for node_id in ("A", "B"):  # C choqué à 1.0 : régularisé, testé à part
        expected = math.log((1.0 - baseline[node_id]) / (1.0 - shocked[node_id]))
        assert detail.delta_ell[node_id] == pytest.approx(expected, abs=1e-6)
    # Le Δl du nœud choqué lui-même est fini et strictement positif (ε-clip).
    assert detail.delta_ell["C"] > 0.0
    assert math.isfinite(detail.delta_ell["C"])


def test_simulate_shock_detailed_saturated_chain_ranks_by_delta_ell() -> None:
    # Réseau saturé : tous les ΔUr sont nuls, mais Δl classe encore les nœuds.
    repo = make_saturated_chain()
    engine = PropagationEngine(repo)
    states = engine.propagate_all()
    assert all(state.ur == 1.0 for state in states.values())  # saturation totale

    details = {nid: engine.simulate_shock_detailed(nid, 1.0) for nid in ("A", "B", "C")}
    for detail in details.values():
        assert all(abs(delta) < APPROX for delta in detail.delta_ur.values())
    # Au client final A : Δl discrimine — le choc le plus proche du rang 0 pèse le plus,
    # et C (déjà à ur_local=1.0) donne un choc à vide même en Δl.
    ell_finals = {nid: details[nid].delta_ell["A"] for nid in ("A", "B", "C")}
    assert ell_finals["A"] > ell_finals["B"] > ell_finals["C"]
    assert ell_finals["C"] == pytest.approx(0.0, abs=APPROX)


def test_simulate_shock_detailed_no_change_gives_zero_deltas() -> None:
    repo = make_chain()
    detail = PropagationEngine(repo).simulate_shock_detailed("C", UR_LOCAL["C"])
    assert all(abs(d) < APPROX for d in detail.delta_ur.values())
    assert all(abs(d) < APPROX for d in detail.delta_ell.values())


def test_simulate_shock_detailed_does_not_persist() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()
    before = {node.id: copy.deepcopy(node.urgency) for node in repo.nodes()}

    engine.simulate_shock_detailed("C", 1.0)

    after = {node.id: node.urgency for node in repo.nodes()}
    assert after == before


def test_simulate_shock_detailed_unknown_node_raises() -> None:
    repo = make_chain()
    with pytest.raises(KeyError):
        PropagationEngine(repo).simulate_shock_detailed("fantome", 1.0)


# --- Propagation par lots (compute_ur_batch / compute_ell_batch) ----------------------


def _random_repo(seed: int) -> InMemoryGraphRepository:
    """DAG aléatoire du générateur, ur_local/β re-tirés dans [0, 1] (seedé)."""
    rng = np.random.default_rng(seed)
    _project, nodes, arcs = RandomSupplyChainGenerator(seed=seed).generate(
        n_ranks=int(rng.integers(1, 4)), breadth=(1, 3)
    )
    repo = InMemoryGraphRepository()
    for node in nodes:
        node.urgency = UrgencyState(ud_local=float(rng.uniform()), ur_local=float(rng.uniform()))
        repo.add_node(node)
    for arc in arcs:
        arc.beta = float(rng.uniform())
        repo.add_arc(arc)
    repo.assign_ranks()
    return repo


def test_compute_ur_batch_s1_matches_compute_ur_on_random_graphs() -> None:
    for seed in range(10):
        engine = PropagationEngine(_random_repo(seed))
        scalar = engine._compute_ur()
        batch = engine.compute_ur_batch()
        assert set(batch) == set(scalar)
        for node_id, value in scalar.items():
            assert batch[node_id].shape == (1,)
            assert batch[node_id][0] == pytest.approx(value, abs=1e-12)


def test_compute_ell_batch_s1_matches_compute_ell_on_random_graphs() -> None:
    for seed in range(10):
        engine = PropagationEngine(_random_repo(seed))
        scalar = engine._compute_ell()
        batch = engine.compute_ell_batch()
        assert set(batch) == set(scalar)
        for node_id, value in scalar.items():
            assert batch[node_id][0] == pytest.approx(value, abs=1e-12)


def test_compute_ur_batch_overrides_match_scalar_per_draw() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    draws_c = np.array([0.0, 0.4, 0.8, 1.0])
    draws_b = np.array([0.1, 0.9, 0.3, 0.7])

    batch = engine.compute_ur_batch({"C": draws_c, "B": draws_b})

    for s in range(4):
        scalar = engine._compute_ur(overrides={"C": float(draws_c[s]), "B": float(draws_b[s])})
        for node_id, value in scalar.items():
            assert batch[node_id][s] == pytest.approx(value, abs=1e-12)


def test_compute_ell_batch_overrides_match_scalar_per_draw() -> None:
    repo = make_saturated_chain()  # cas exigeant : β=1 et fournisseur saturé
    engine = PropagationEngine(repo)
    draws_b = np.array([0.3, 0.6, 1.0])

    batch = engine.compute_ell_batch({"B": draws_b})

    for s in range(3):
        scalar = engine._compute_ell(overrides={"B": float(draws_b[s])})
        for node_id, value in scalar.items():
            assert batch[node_id][s] == pytest.approx(value, abs=1e-12)


def test_compute_ur_batch_regularized_clip_bounds_values() -> None:
    hi = 1.0 - 1e-9
    engine = PropagationEngine(make_saturated_chain())
    batch = engine.compute_ur_batch(clip=(0.0, hi))
    for values in batch.values():
        assert np.all(values <= hi)
        assert np.all(values >= 0.0)


def test_compute_ur_scalar_regularized_clip_bounds_values() -> None:
    # Le paramètre clip privé de _compute_ur : hi < 1 clippe aussi la valeur
    # locale effective (jumeau régularisé), le défaut reste bit à bit standard.
    hi = 1.0 - 1e-9
    engine = PropagationEngine(make_saturated_chain())
    regularized = engine._compute_ur(clip=(0.0, hi))
    assert all(0.0 <= value <= hi for value in regularized.values())
    assert regularized["C"] == hi  # local 1.0 clipé à 1−ε (aucun fournisseur)
    assert engine._compute_ur() == engine._compute_ur(clip=(0.0, 1.0))  # défaut inchangé


def test_compute_ur_batch_is_pure() -> None:
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()
    before = {node.id: copy.deepcopy(node.urgency) for node in repo.nodes()}

    engine.compute_ur_batch({"C": np.array([0.2, 1.0])})
    engine.compute_ell_batch({"C": np.array([0.2, 1.0])})

    assert {node.id: node.urgency for node in repo.nodes()} == before


def test_compute_ur_batch_rejects_inconsistent_or_unknown_overrides() -> None:
    engine = PropagationEngine(make_chain())
    with pytest.raises(ValueError, match="formes incohérentes"):
        engine.compute_ur_batch({"C": np.array([0.1, 0.2]), "B": np.array([0.1])})
    with pytest.raises(ValueError, match="formes incohérentes"):
        engine.compute_ur_batch({"C": np.array([[0.1], [0.2]])})
    with pytest.raises(ValueError, match="inconnu"):
        engine.compute_ur_batch({"fantome": np.array([0.1])})
    with pytest.raises(ValueError, match="inconnu"):
        engine.compute_ell_batch({"fantome": np.array([0.1])})
