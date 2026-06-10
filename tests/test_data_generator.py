"""Tests du générateur de données de TEST (supplyscore.data.generator)."""

from __future__ import annotations

import networkx as nx
import pytest

from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.models import Project, SupplyArc, SupplyNode


@pytest.fixture()
def chain():
    return RandomSupplyChainGenerator(seed=42).generate(n_ranks=3, breadth=(1, 3))


class TestGenerateTopology:
    def test_returns_project_nodes_arcs(self, chain):
        project, nodes, arcs = chain
        assert isinstance(project, Project)
        assert all(isinstance(n, SupplyNode) for n in nodes)
        assert all(isinstance(a, SupplyArc) for a in arcs)

    def test_single_rank0_client_owns_project(self, chain):
        project, nodes, _ = chain
        rank0 = [n for n in nodes if n.rank == 0]
        assert len(rank0) == 1
        client = rank0[0]
        assert client.label == "Client"
        assert project.owner_node_id == client.id
        assert all(n.project_id == project.id for n in nodes)

    def test_dag_no_cycle_networkx(self, chain):
        _, nodes, arcs = chain
        g = nx.DiGraph()
        g.add_nodes_from(n.id for n in nodes)
        g.add_edges_from((a.source_id, a.target_id) for a in arcs)
        assert nx.is_directed_acyclic_graph(g)

    def test_arcs_go_from_rank_r_to_rank_r_minus_1(self, chain):
        _, nodes, arcs = chain
        rank_of = {n.id: n.rank for n in nodes}
        for arc in arcs:
            assert rank_of[arc.source_id] == rank_of[arc.target_id] + 1

    def test_ranks_correct_and_node_counts_coherent(self):
        gen = RandomSupplyChainGenerator(seed=7)
        project, nodes, arcs = gen.generate(n_ranks=4, breadth=(2, 3))

        by_rank: dict[int, int] = {}
        for n in nodes:
            by_rank[n.rank] = by_rank.get(n.rank, 0) + 1

        assert set(by_rank) == {0, 1, 2, 3, 4}
        assert by_rank[0] == 1
        # Chaque nœud du rang r-1 reçoit entre 2 et 3 fournisseurs dédiés.
        for r in range(1, 5):
            assert 2 * by_rank[r - 1] <= by_rank[r] <= 3 * by_rank[r - 1]
        assert len(nodes) == sum(by_rank.values())
        # Au moins un arc dédié par fournisseur, arcs croisés en plus possibles.
        assert len(arcs) >= len(nodes) - 1

    def test_every_consumer_has_a_supplier(self, chain):
        _, nodes, arcs = chain
        max_rank = max(n.rank for n in nodes)
        targets = {a.target_id for a in arcs}
        for n in nodes:
            if n.rank < max_rank:
                assert n.id in targets

    def test_no_duplicate_arcs(self, chain):
        _, _, arcs = chain
        pairs = [(a.source_id, a.target_id) for a in arcs]
        assert len(pairs) == len(set(pairs))


class TestGenerateKPIs:
    def test_node_kpis_within_bounds(self, chain):
        _, nodes, _ = chain
        for n in nodes:
            k = n.kpis
            assert 24.0 <= k.time.lead_time_h <= 720.0
            assert k.time.deadline_h > k.time.lead_time_h
            for comp in (k.oee.availability, k.oee.performance, k.oee.quality):
                assert 0.7 <= comp <= 0.99
            assert 0.001 <= k.risk.failure_probability <= 0.1
            assert 0.1 <= k.risk.severity <= 0.9
            assert 0.0 <= k.risk.env_exposure <= 0.3
            assert 0.0 <= k.risk.political_risk <= 0.3
            # Coûts cohérents : op_cost = nominal * (1 + volatilité).
            expected = k.cost.nominal_op_cost * (1.0 + k.risk.cost_volatility)
            assert k.cost.op_cost == pytest.approx(expected)
            # CO2 : target < total < max.
            assert k.co2.co2_target_g_h < k.co2.total_g_h < k.co2.co2_max_g_h
            # Inventaire : current <= max.
            assert k.inventory.current_volume_m3 <= k.inventory.max_volume_m3
            assert k.inventory.current_weight_kg <= k.inventory.max_weight_kg
            # Flow rate proche de la demande (±15 %).
            assert k.inventory.flow_rate == pytest.approx(
                k.network.demand, rel=0.15)

    def test_arc_kpis_and_coefficients(self, chain):
        _, _, arcs = chain
        for a in arcs:
            assert 0.3 <= a.gamma <= 0.9
            assert 0.3 <= a.beta <= 0.9
            assert 0.5 <= a.delta <= 1.5
            assert a.kpis.time.speed_kmh is not None and a.kpis.time.speed_kmh > 0
            assert a.kpis.network.distance_km is not None
            assert a.kpis.network.distance_km > 0


class TestReproducibility:
    def test_same_seed_same_output(self):
        out1 = RandomSupplyChainGenerator(seed=123).generate(n_ranks=3,
                                                             breadth=(1, 3))
        out2 = RandomSupplyChainGenerator(seed=123).generate(n_ranks=3,
                                                             breadth=(1, 3))
        p1, n1, a1 = out1
        p2, n2, a2 = out2
        assert p1 == p2
        assert n1 == n2
        assert a1 == a2

    def test_different_seed_different_output(self):
        _, n1, _ = RandomSupplyChainGenerator(seed=1).generate()
        _, n2, _ = RandomSupplyChainGenerator(seed=2).generate()
        assert [x.id for x in n1] != [x.id for x in n2]

    def test_same_seed_same_assessment(self):
        a1 = RandomSupplyChainGenerator(seed=9).generate_assessment("n", "p")
        a2 = RandomSupplyChainGenerator(seed=9).generate_assessment("n", "p")
        # timestamp = heure d'exécution, on compare le reste.
        assert a1.comparisons == a2.comparisons
        assert a1.weights == a2.weights
        assert a1.criteria_scores == a2.criteria_scores
        assert a1.ud == a2.ud


class TestGenerateAssessment:
    SAATY = {1 / k for k in range(1, 10)} | {float(k) for k in range(1, 10)}

    def test_consistent_cr_below_0_10(self):
        gen = RandomSupplyChainGenerator(seed=0)
        for _ in range(50):
            a = gen.generate_assessment("n1", "p1")
            assert a.consistency_ratio < 0.10
            assert a.is_consistent is True

    def test_ud_in_unit_interval(self):
        gen = RandomSupplyChainGenerator(seed=1)
        for bias in (0.0, 0.25, 0.5, 0.75, 1.0):
            for _ in range(20):
                a = gen.generate_assessment("n1", "p1", urgency_bias=bias)
                assert 0.0 <= a.ud <= 1.0

    def test_urgency_bias_shifts_ud(self):
        gen = RandomSupplyChainGenerator(seed=4)
        low = [gen.generate_assessment("n", "p", urgency_bias=0.1).ud
               for _ in range(30)]
        high = [gen.generate_assessment("n", "p", urgency_bias=0.9).ud
                for _ in range(30)]
        assert sum(low) / len(low) < sum(high) / len(high)

    def test_structure(self):
        a = RandomSupplyChainGenerator(seed=3).generate_assessment(
            "n1", "p1", operator_id="op-x")
        n = len(a.weights)
        assert n == len(a.criteria_scores)
        assert len(a.comparisons) == n * (n - 1) // 2
        assert a.node_id == "n1"
        assert a.project_id == "p1"
        assert a.operator_id == "op-x"
        # Comparaisons sur l'échelle de Saaty, triangle supérieur uniquement.
        for (i, j), value in a.comparisons.items():
            assert i < j
            assert any(abs(value - s) < 1e-9 for s in self.SAATY)
        # Poids normalisés, scores dans [1, 9].
        assert sum(a.weights) == pytest.approx(1.0)
        assert all(w > 0 for w in a.weights)
        assert all(1.0 <= s <= 9.0 for s in a.criteria_scores)
