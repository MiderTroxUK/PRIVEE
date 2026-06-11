"""Configuration des bancs de performance E14 (Lot 14.1).

Les bancs sont EXCLUS du run rapide par défaut : ils ne s'exécutent que si la
variable d'environnement ``SUPPLYSCORE_BENCH`` vaut ``"1"`` (posée par
``scripts/ci.ps1 -Benchmarks``). Le marqueur ``benchmark_suite`` est enregistré
ICI (conftest local) — aucun réglage pytest global n'est nécessaire, la suite
rapide saute simplement ces fichiers à la collecte.

Les bases SQLite des bancs vivent sous ``tmp_path_factory`` (%TEMP%), JAMAIS
dans le dossier du projet potentiellement synchronisé cloud (faiblesse #21).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.models import Project, SupplyArc, SupplyNode
from supplyscore.services import SupplyScoreService

#: Instant figé des bancs (epoch s) — reproductibilité totale des mesures.
BENCH_NOW = 1_780_000_000.0

#: Taille du DAG de stress — les budgets du PLAN sont exprimés @ 1 000 nœuds.
N_NODES_STRESS = 1_000

#: Seed figée du DAG de stress (mêmes données à chaque exécution des bancs).
SEED_STRESS = 1414


def pytest_configure(config: pytest.Config) -> None:
    """Enregistre le marqueur local des bancs (porté par TOUS les tests du dossier)."""
    config.addinivalue_line(
        "markers",
        "benchmark_suite: banc de performance E14 — exécuté seulement si SUPPLYSCORE_BENCH=1",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """SKIP tous les bancs si SUPPLYSCORE_BENCH != '1' (run rapide par défaut)."""
    if os.environ.get("SUPPLYSCORE_BENCH") == "1":
        return
    skip_bench = pytest.mark.skip(
        reason="banc de performance : poser SUPPLYSCORE_BENCH=1 (ou scripts/ci.ps1 -Benchmarks)"
    )
    for item in items:
        if "benchmark_suite" in item.keywords:
            item.add_marker(skip_bench)


@pytest.fixture(scope="session")
def stress_chain() -> tuple[Project, list[SupplyNode], list[SupplyArc]]:
    """DAG de stress 1 000 nœuds reproductible — KPIs complets, sans jalons/tags."""
    return RandomSupplyChainGenerator(seed=SEED_STRESS).generate_stress(n_nodes=N_NODES_STRESS)


@pytest.fixture(scope="session")
def stress_service(
    tmp_path_factory: pytest.TempPathFactory,
    stress_chain: tuple[Project, list[SupplyNode], list[SupplyArc]],
) -> Iterator[SupplyScoreService]:
    """Service chargé avec le DAG de stress, stockage sous %TEMP% (faiblesse #21).

    SANS assessments : un questionnaire AHP simulé par nœud rendrait la
    fixture prohibitive (1 000 sauvegardes + lissages) ; ``ud_local`` reste
    None, ce qui est accepté par la propagation et suffit pour mesurer.
    """
    project, nodes, arcs = stress_chain
    db_dir = tmp_path_factory.mktemp("supplyscore_bench_store")
    # client_cache_size dimensionné au graphe : sur 1 000 nœuds, le LRU par
    # défaut (64) provoque ~1 000 open/close SQLite par evaluate_all(persist)
    # — c'est le bouton de déploiement documenté pour les très grands graphes.
    svc = SupplyScoreService(db_dir=db_dir, clock=FixedClock(BENCH_NOW), client_cache_size=1_100)
    project.t0_ts = BENCH_NOW
    svc.create_project(project, nodes, arcs)
    yield svc
    svc.close()
