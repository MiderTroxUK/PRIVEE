"""Test d'intégration bout-en-bout : génération aléatoire -> pipeline complet -> persistance."""

import pytest

from supplyscore.domain.models import TaskStatus
from supplyscore.services import SupplyScoreService


@pytest.fixture
def service(tmp_path):
    # Horloge figée : les comparaisons entre deux evaluate_all successifs
    # doivent être déterministes (pas de dérive du temps réel entre les appels).
    from supplyscore.core.clock import FixedClock

    return SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(1_750_000_000.0))


def test_full_pipeline(service):
    project = service.seed_demo(n_ranks=3, seed=7)

    nodes = service.repo.nodes()
    assert len(nodes) >= 4  # client final + au moins 3 rangs

    states = service.evaluate_all(persist=True)
    for _node_id, state in states.items():
        assert state.ud is not None and 0.0 <= state.ud <= 1.0
        assert state.ur is not None and 0.0 <= state.ur <= 1.0
        assert state.adequation is not None and 0.0 <= state.adequation <= 100.0
        # F et H sont exclusifs
        assert state.false_urgency == 0.0 or state.hidden_risk == 0.0

    # historique persisté dans la base de chaque client
    for node in nodes:
        series = service.client_db(node.id).urgency_series(node.id)
        assert len(series) >= 1

    # le registre connaît le projet
    assert service.registry.get_project(project.id) is not None


def test_abandoned_task_raises_downstream_ur(service):
    service.seed_demo(n_ranks=3, seed=11)
    # nœud le plus profond (rang max)
    deepest = max(service.repo.nodes(), key=lambda n: n.rank)
    root = next(n for n in service.repo.nodes() if n.rank == 0)

    before = service.evaluate_all()[root.id].ur
    service.set_status(deepest.id, TaskStatus.ABANDONED)
    after = service.evaluate_all()[root.id].ur
    assert after >= before


def test_shock_simulation_is_pure(service):
    service.seed_demo(n_ranks=2, seed=3)
    states_before = service.evaluate_all()
    deepest = max(service.repo.nodes(), key=lambda n: n.rank)

    deltas = service.simulate_shock(deepest.id, 1.0)
    assert deltas[deepest.id] >= 0.0

    states_after = service.evaluate_all()
    for nid in states_before:
        assert states_before[nid].ur == pytest.approx(states_after[nid].ur, abs=1e-9)


def test_graph_reload_from_registry(service, tmp_path):
    project = service.seed_demo(n_ranks=2, seed=5)
    n_before = len(service.repo.nodes())

    reloaded = SupplyScoreService(db_dir=service.db_dir)
    reloaded.load_graph_from_registry()
    assert len(reloaded.repo.nodes()) == n_before
    assert reloaded.registry.get_project(project.id) is not None
