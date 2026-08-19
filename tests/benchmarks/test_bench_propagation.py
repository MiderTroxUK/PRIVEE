"""Bancs de performance - propagation des urgences sur le DAG de stress (Lot 14.1).

Budgets du PLAN (@ 1 000 noeuds) : ``propagate_all`` < 80 ms,
``simulate_shock`` < 30 ms, propagation incrementale (1 noeud change) < 5 ms
(Lot 14.4). Assertions a marge x3 (machines de CI lentes) : on echoue
seulement si la moyenne mesuree depasse budget x 3.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.benchmark_suite

#: Budgets PLAN x3 (secondes).
BUDGET_PROPAGATE_ALL_S = 0.080 * 3
BUDGET_SIMULATE_SHOCK_S = 0.030 * 3
BUDGET_PROPAGATE_INCREMENTAL_S = 0.005 * 3


def test_bench_propagate_all(benchmark, stress_service):
    """Propagation complete Ud (descendante) + Ur (montante) @ 1 000 noeuds."""
    n_nodes = len(stress_service.repo.nodes())
    states = benchmark(stress_service.propagation.propagate_all)
    assert len(states) == n_nodes == 1_000
    assert benchmark.stats.stats.mean < BUDGET_PROPAGATE_ALL_S


def test_bench_simulate_shock(benchmark, stress_service):
    """Choc what-if sur un fournisseur du rang le plus profond (impact maximal)."""
    deep_node = max(stress_service.repo.nodes(), key=lambda n: n.rank)
    deltas = benchmark(stress_service.simulate_shock, deep_node.id, 1.0)
    assert len(deltas) == 1_000
    assert benchmark.stats.stats.mean < BUDGET_SIMULATE_SHOCK_S


def test_bench_propagate_incremental(benchmark, stress_service):
    """Propagation incrementale : 1 noeud sale du rang le plus profond (Lot 14.4).

    Le graphe est d'abord ENTIEREMENT propage (cache Ud/Ur complet et version
    de structure synchronisee) ; chaque round marque UN noeud du rang le plus
    profond ``dirty_ur`` puis ne recalcule que son cone aval.
    """
    engine = stress_service.propagation
    engine.propagate_all()  # " deja propage " : cache complet, plus rien de sale
    deep_node = max(stress_service.repo.nodes(), key=lambda n: n.rank)

    def _one_dirty_node():
        engine.mark_dirty_ur(deep_node.id)
        return engine.propagate_incremental()

    states = benchmark(_one_dirty_node)
    assert len(states) == 1_000
    assert benchmark.stats.stats.mean < BUDGET_PROPAGATE_INCREMENTAL_S
