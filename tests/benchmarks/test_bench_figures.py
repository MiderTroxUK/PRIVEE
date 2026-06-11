"""Banc de performance — construction de la figure DAG du dashboard (Lot 14.1).

Budget du PLAN (@ 1 000 nœuds / ~1 250 arcs) : ``dashboard_dag_figure``
< 300 ms. Assertion à marge ×3 (machines de CI lentes). Le rendu historique
posait une annotation Plotly PAR arc (faiblesse #13, traitée au Lot 14.3) —
ce banc mesure la version courante de ``figures.py``.
"""

from __future__ import annotations

import pytest

from supplyscore.web_ui.components.figures import dashboard_dag_figure

pytestmark = pytest.mark.benchmark_suite

#: Budget PLAN ×3 (secondes).
BUDGET_DASHBOARD_DAG_S = 0.300 * 3


def test_bench_dashboard_dag_figure(benchmark, stress_chain):
    """Figure DAG dashboard (couleur = adéquation, taille = Ur) @ 1 000 nœuds."""
    _project, nodes, arcs = stress_chain
    fig = benchmark(dashboard_dag_figure, nodes, arcs)
    assert fig.data  # la figure contient bien des traces
    assert benchmark.stats.stats.mean < BUDGET_DASHBOARD_DAG_S
