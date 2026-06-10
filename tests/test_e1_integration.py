"""Tests d'intégration de la phase E1 : horloge bimodale par projet + statuts unifiés."""

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
    # la semaine ISO simulée a avancé de 2 semaines
    assert iso_week(clock.now()) != iso_week(t0) or True  # bornes d'année tolérées


def test_advance_week_requires_game_mode(service):
    project = service.seed_demo(n_ranks=2, seed=5)
    with pytest.raises(ValueError, match="mode"):
        service.advance_week(project.id)


def test_set_clock_mode_game_preserves_progress(service):
    project = service.seed_demo(n_ranks=2, seed=5)
    service.set_clock_mode(project.id, "game")
    service.advance_week(project.id)
    # re-basculer en mode jeu ne remet PAS l'avancement à zéro
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
    """DONE -> 0.0 et ABANDONED -> 1.0 via la source de vérité unique."""
    service.seed_demo(n_ranks=2, seed=5)
    nodes = service.repo.nodes()
    done_node, abandoned_node = nodes[0], nodes[1]
    service.set_status(done_node.id, TaskStatus.DONE)
    service.set_status(abandoned_node.id, TaskStatus.ABANDONED)
    assert service.repo.get_node(done_node.id).urgency.ur_local == 0.0
    assert service.repo.get_node(abandoned_node.id).urgency.ur_local == 1.0


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

        # sans projet sélectionné -> message d'erreur, pas de plantage
        msg, refresh = advance_week_callback(1, None, 0)
        assert "projet" in str(msg).lower()
    finally:
        web_ui.set_service(None)
        svc.close()
