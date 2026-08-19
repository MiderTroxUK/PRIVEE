"""Configuration des bancs de performance E14 (Lot 14.1).

Les bancs sont EXCLUS du run rapide par defaut : ils ne s'executent que si la
variable d'environnement ``SUPPLYSCORE_BENCH`` vaut ``"1"`` (posee par
``scripts/ci.ps1 -Benchmarks``). Le marqueur ``benchmark_suite`` est enregistre
ICI (conftest local) - aucun reglage pytest global n'est necessaire, la suite
rapide saute simplement ces fichiers a la collecte.

Les bases SQLite des bancs vivent sous ``tmp_path_factory`` (%TEMP%), JAMAIS
dans le dossier du projet potentiellement synchronise cloud (faiblesse #21).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.models import Project, SupplyArc, SupplyNode
from supplyscore.services import SupplyScoreService

#: Instant fige des bancs (epoch s) - reproductibilite totale des mesures.
BENCH_NOW = 1_780_000_000.0

#: Taille du DAG de stress - les budgets du PLAN sont exprimes @ 1 000 noeuds.
N_NODES_STRESS = 1_000

#: Seed figee du DAG de stress (memes donnees a chaque execution des bancs).
SEED_STRESS = 1414


def pytest_configure(config: pytest.Config) -> None:
    """Enregistre le marqueur local des bancs (porte par TOUS les tests du dossier)."""
    config.addinivalue_line(
        "markers",
        "benchmark_suite: banc de performance E14 — exécuté seulement si SUPPLYSCORE_BENCH=1",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """SKIP tous les bancs si SUPPLYSCORE_BENCH != '1' (run rapide par defaut)."""
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
    """DAG de stress 1 000 noeuds reproductible - KPIs complets, sans jalons/tags."""
    return RandomSupplyChainGenerator(seed=SEED_STRESS).generate_stress(n_nodes=N_NODES_STRESS)


@pytest.fixture(scope="session")
def stress_service(
    tmp_path_factory: pytest.TempPathFactory,
    stress_chain: tuple[Project, list[SupplyNode], list[SupplyArc]],
) -> Iterator[SupplyScoreService]:
    """Service charge avec le DAG de stress, stockage sous %TEMP% (faiblesse #21).

    SANS assessments : un questionnaire AHP simule par noeud rendrait la
    fixture prohibitive (1 000 sauvegardes + lissages) ; ``ud_local`` reste
    None, ce qui est accepte par la propagation et suffit pour mesurer.
    """
    project, nodes, arcs = stress_chain
    db_dir = tmp_path_factory.mktemp("supplyscore_bench_store")
    # client_cache_size dimensionne au graphe : sur 1 000 noeuds, le LRU par defaut (64) provoque ~1 000 open/close SQLite par evaluate_all(persist) - c'est le bouton de deploiement documente pour les tres grands graphes.
    svc = SupplyScoreService(db_dir=db_dir, clock=FixedClock(BENCH_NOW), client_cache_size=1_100)
    project.t0_ts = BENCH_NOW
    svc.create_project(project, nodes, arcs)
    yield svc
    svc.close()
