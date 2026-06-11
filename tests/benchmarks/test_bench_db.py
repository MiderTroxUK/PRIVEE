"""Bancs de performance — persistance SQLite sur le DAG de stress (Lot 14.1).

Budgets du PLAN (@ 1 000 nœuds) : ``evaluate_all(persist=True)`` < 2.5 s,
``load_graph_from_registry`` < 1.5 s. Assertions à marge ×3 (machines de CI
lentes). Les bases vivent sous %TEMP% via la fixture session (faiblesse #21).

``min_rounds`` est abaissé sur ces bancs : chaque round persiste 1 000 états
dans 1 001 bases SQLite (faiblesse #14, optimisation au Lot 14.2) — les
rounds par défaut rendraient le banc interminable sans précision en plus.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.benchmark_suite

#: Budgets PLAN ×3 (secondes).
BUDGET_EVALUATE_ALL_PERSIST_S = 2.5 * 3
BUDGET_LOAD_GRAPH_S = 1.5 * 3


@pytest.mark.benchmark(min_rounds=3)
def test_bench_evaluate_all_persist(benchmark, stress_service):
    """Pipeline complet persisté : Ur_local -> propagation -> adéquation -> SQLite."""
    states = benchmark(stress_service.evaluate_all, persist=True)
    assert len(states) == 1_000
    assert benchmark.stats.stats.mean < BUDGET_EVALUATE_ALL_PERSIST_S


@pytest.mark.benchmark(min_rounds=3)
def test_bench_load_graph_from_registry(benchmark, stress_service):
    """Rechargement complet du graphe en mémoire depuis la base registre."""
    benchmark(stress_service.load_graph_from_registry)
    assert len(stress_service.repo.nodes()) == 1_000
    assert benchmark.stats.stats.mean < BUDGET_LOAD_GRAPH_S
