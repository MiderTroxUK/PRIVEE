"""Tests d'intégration de la phase E2 : domaine v2 câblé bout en bout.

Vérifie que la démo enrichie (jalons, tags, arcs backup) alimente le pipeline
et que l'horloge de jeu rend les échéances vivantes : avancer les semaines
fait monter l'urgence temporelle des nœuds dont les deadlines approchent.
"""

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import ArcKind
from supplyscore.services import SupplyScoreService


@pytest.fixture
def service(tmp_path):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(1_750_000_000.0))
    yield svc
    svc.close()


def test_seed_demo_is_enriched(service):
    project = service.seed_demo(n_ranks=3, seed=11)

    nodes = service.repo.nodes()
    assert nodes, "la démo doit créer des nœuds"

    # origine temporelle posée à maintenant (horloge du service)
    stored = service.registry.get_project(project.id)
    assert stored is not None and stored.t0_ts == pytest.approx(1_750_000_000.0)

    # chaque nœud a 2 à 4 jalons, triés par position
    for node in nodes:
        milestones = service.registry.list_milestones(node.id)
        assert 2 <= len(milestones) <= 4
        assert [m.position for m in milestones] == sorted(m.position for m in milestones)

    # taxonomie et tags présents, chaque nœud porte 1 à 3 tags existants
    tags = service.registry.list_tags(project.id)
    categories = service.registry.list_tag_categories(project.id)
    assert len(categories) == 2 and 4 <= len(tags) <= 6
    tag_ids = {t.id for t in tags}
    for node in nodes:
        assert 1 <= len(node.tags) <= 3
        assert set(node.tags) <= tag_ids

    # des arcs backup existent (~1/10) et sont inertes
    backups = service.repo.arcs(kinds=("backup",))
    nominals = service.repo.arcs(kinds=("nominal",))
    assert nominals, "il faut des arcs nominaux"
    assert all(a.kind_arc == ArcKind.BACKUP for a in backups)


def test_seed_demo_reproducible(service, tmp_path):
    p1 = service.seed_demo(n_ranks=2, seed=99)
    ms1 = {
        n.id: [
            (m.name, m.deadline_ts, str(m.status)) for m in service.registry.list_milestones(n.id)
        ]
        for n in service.repo.nodes()
    }

    other = SupplyScoreService(db_dir=tmp_path / "store2", clock=FixedClock(1_750_000_000.0))
    try:
        p2 = other.seed_demo(n_ranks=2, seed=99)
        ms2 = {
            n.id: [
                (m.name, m.deadline_ts, str(m.status)) for m in other.registry.list_milestones(n.id)
            ]
            for n in other.repo.nodes()
        }
        assert p1.id == p2.id
        assert ms1 == ms2
    finally:
        other.close()


def test_game_clock_drives_urgency_up(service):
    """Avancer le temps de jeu fait monter l'urgence réelle moyenne du réseau.

    Les jalons de la démo s'étalent sur ~1 à 8 semaines : après 30 semaines de
    jeu, la plupart des deadlines sont dépassées (u_time -> 1) — la moyenne des
    Ur doit strictement monter.
    """
    project = service.seed_demo(n_ranks=2, seed=7)
    service.set_clock_mode(project.id, "game")

    states_before = service.evaluate_all()
    mean_before = sum(s.ur for s in states_before.values()) / len(states_before)

    for _ in range(30):
        service.advance_week(project.id)

    states_after = service.evaluate_all()
    mean_after = sum(s.ur for s in states_after.values()) / len(states_after)

    assert mean_after > mean_before


def test_derived_status_persists_after_restart(service, tmp_path):
    """Le statut dérivé des jalons survit à un redémarrage (registre + node_urgency)."""
    service.seed_demo(n_ranks=2, seed=3)
    states = service.evaluate_all(persist=True)
    db_dir = service.db_dir
    nodes_before = {n.id: (n.status, n.tags, n.onboarding_state) for n in service.repo.nodes()}
    service.close()

    reopened = SupplyScoreService(db_dir=db_dir, clock=FixedClock(1_750_000_000.0))
    try:
        reopened.load_graph_from_registry()
        for node in reopened.repo.nodes():
            status, tags, onboarding = nodes_before[node.id]
            assert node.status == status
            assert sorted(node.tags) == sorted(tags)
            assert node.onboarding_state == onboarding
        assert set(states) == {n.id for n in reopened.repo.nodes()}
    finally:
        reopened.close()
