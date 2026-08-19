"""Banc de performance - Monte Carlo des dates d'achevement (Lot 14.1).

Budget du PLAN (@ 1 000 noeuds, N = 10 000 tirages) : ``executer`` < 2 s.
Assertion a marge x3 (machines de CI lentes).

Garde-fou memoire du simulateur : N x n_noeuds <= 5e7 - ici
10 000 x 1 000 = 1e7, largement sous le plafond (verifie explicitement).
"""

from __future__ import annotations

import pytest

from supplyscore.mc.lead_time import BUDGET_MEMOIRE_MAX, SimulateurLeadTime

pytestmark = pytest.mark.benchmark_suite

#: Budget PLAN x3 (secondes).
BUDGET_MC_S = 2.0 * 3

#: Nombre de tirages N du banc (valeur par defaut de l'app).
N_TIRAGES = 10_000


@pytest.mark.benchmark(min_rounds=3)
def test_bench_simulateur_lead_time(benchmark, stress_service):
    """Simulation MC complete N=10 000 sur le DAG de stress (sans jalons)."""
    n_nodes = len(stress_service.repo.nodes())
    assert N_TIRAGES * n_nodes <= BUDGET_MEMOIRE_MAX  # garde memoire documentee
    simulateur = SimulateurLeadTime(stress_service.repo, n_tirages=N_TIRAGES, graine=1414)
    resultat = benchmark(simulateur.executer, t=0.0)
    assert resultat.n_tirages == N_TIRAGES
    assert len(resultat.u_time) == n_nodes
    assert benchmark.stats.stats.mean < BUDGET_MC_S
