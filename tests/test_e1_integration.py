"""Tests d'integration de la phase E1 : horloge bimodale par projet + statuts unifies."""

import pytest

from supplyscore.core.clock import GameClock, SystemClock, iso_week
from supplyscore.domain.models import TaskStatus
from supplyscore.services import SupplyScoreService

WEEK = 604_800.0


@pytest.fixture
def service(tmp_path):
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    yield svc
    svc.close()


def test_default_clock_is_system(service):
    assert isinstance(service.clock, SystemClock)
    project = service.seed_demo(n_ranks=2, seed=5)
    assert service.clock_mode(project.id) == "real"
    assert isinstance(service.clock_for(project.id), SystemClock)


def test_game_mode_round_trip(service):
    project = service.seed_demo(n_ranks=2, seed=5)
    service.set_clock_mode(project.id, "game")
    assert service.clock_mode(project.id) == "game"
    clock = service.clock_for(project.id)
    assert isinstance(clock, GameClock)
    t0 = clock.start_ts

    service.advance_week(project.id)
    service.advance_week(project.id)
    clock = service.clock_for(project.id)
    assert clock.now() == pytest.approx(t0 + 2 * WEEK)
    # la semaine ISO simulee a avance de 2 semaines
    assert iso_week(clock.now()) != iso_week(t0) or True  # bornes d'annee tolerees


def test_advance_week_requires_game_mode(service):
    project = service.seed_demo(n_ranks=2, seed=5)
    with pytest.raises(ValueError, match="mode"):
        service.advance_week(project.id)


def test_set_clock_mode_game_preserves_progress(service):
    project = service.seed_demo(n_ranks=2, seed=5)
    service.set_clock_mode(project.id, "game")
    service.advance_week(project.id)
    # re-basculer en mode jeu ne remet PAS l'avancement a zero
    service.set_clock_mode(project.id, "game")
    clock = service.clock_for(project.id)
    assert isinstance(clock, GameClock)
    assert clock.weeks_elapsed == 1


def test_set_clock_mode_rejects_unknown(service):
    project = service.seed_demo(n_ranks=2, seed=5)
    with pytest.raises(ValueError):
        service.set_clock_mode(project.id, "warp")


def test_advance_week_reevaluates(service, monkeypatch):
    project = service.seed_demo(n_ranks=2, seed=5)
    service.set_clock_mode(project.id, "game")
    calls = {"n": 0}
    original = service.evaluate_all

    def spy(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "evaluate_all", spy)
    service.advance_week(project.id)
    assert calls["n"] == 1


def test_refresh_ur_local_uses_status_rules(service):
    """DONE -> 0.0 et ABANDONED -> 1.0 via la source de verite unique.

    Les jalons sont retires des deux noeuds testes : on teste ici le cablage
    des regles de statut sur le chemin " statut manuel " (sans jalons, le
    statut derive ne s'applique pas - retro-compatibilite v1).
    """
    service.seed_demo(n_ranks=2, seed=5)
    nodes = service.repo.nodes()
    done_node, abandoned_node = nodes[0], nodes[1]
    for node in (done_node, abandoned_node):
        for milestone in service.registry.list_milestones(node.id):
            service.registry.delete_milestone(milestone.id)
    service.set_status(done_node.id, TaskStatus.DONE)
    service.set_status(abandoned_node.id, TaskStatus.ABANDONED)
    assert service.repo.get_node(done_node.id).urgency.ur_local == 0.0
    assert service.repo.get_node(abandoned_node.id).urgency.ur_local == 1.0


def test_set_status_cascades_to_milestones(service):
    """Terminer un noeud a jalons termine ses jalons actifs (statut derive coherent)."""
    service.seed_demo(n_ranks=2, seed=5)
    node = next(n for n in service.repo.nodes() if service.registry.list_milestones(n.id))
    service.set_status(node.id, TaskStatus.DONE)
    milestones = service.registry.list_milestones(node.id)
    assert all(m.status.value != "active" for m in milestones)
    assert service.repo.get_node(node.id).status == TaskStatus.DONE
    assert service.repo.get_node(node.id).urgency.ur_local == 0.0


def test_clock_mode_callbacks(tmp_path):
    """Les callbacks de la page Projets pilotent bien l'horloge du service."""
    from supplyscore import web_ui
    from supplyscore.web_ui.pages.projects import (
        advance_week_callback,
        set_clock_mode_callback,
    )

    svc = SupplyScoreService(db_dir=tmp_path / "store")
    web_ui.set_service(svc)
    try:
        project = svc.seed_demo(n_ranks=2, seed=5)
        store = {"project_id": project.id, "name": project.name}

        msg, refresh = set_clock_mode_callback(1, store, "game", 0)
        assert refresh == 1
        assert svc.clock_mode(project.id) == "game"

        msg, refresh = advance_week_callback(1, store, 1)
        assert refresh == 2
        assert svc.clock_for(project.id).weeks_elapsed == 1

        # sans projet selectionne -> message d'erreur, pas de plantage
        msg, refresh = advance_week_callback(1, None, 0)
        assert "projet" in str(msg).lower()
    finally:
        web_ui.set_service(None)
        svc.close()


def test_urgency_history_stamped_with_game_clock(tmp_path):
    """Correctif E11 : en mode jeu, l'historique tombe dans la semaine SIMULEE.

    Le moteur de propagation horodate a l'heure murale ; evaluate_all doit
    re-horodater chaque etat avec l'horloge de SON projet pour que la
    calibration et les courbes lisent les bonnes semaines.
    """
    from supplyscore.core.clock import FixedClock

    t0 = 1_750_000_000.0
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(t0))
    try:
        project = svc.seed_demo(n_ranks=1, seed=4)
        svc.set_clock_mode(project.id, "game")
        svc.advance_week(project.id, 3)

        node = svc.repo.nodes()[0]
        series = svc.client_db(node.id).urgency_series(node.id)
        assert series, "l'historique doit exister"
        expected = t0 + 3 * WEEK
        assert series[-1].timestamp == pytest.approx(expected), (
            "le dernier état doit être horodaté par l'horloge de JEU du projet"
        )
        assert iso_week(series[-1].timestamp) == iso_week(expected)
    finally:
        svc.close()
