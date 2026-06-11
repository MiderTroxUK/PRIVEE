"""Tests d'intégration service — mode Monte Carlo du lead time par projet (Lot 13.3).

Couvre : round-trip de ``set_lead_time_mode`` / ``lead_time_mode``, validation à
l'écriture (mode inconnu, n_tirages hors bornes — choix documenté), effet du mode
MC sur ``ur_local`` (différent de l'analytique, bornes [0, 1] respectées),
STABILITÉ bit à bit dans la même semaine (graine stable dérivée de
(project_id, semaine ISO)), changement de graine après ``advance_week``,
``last_mc_result`` et la rétro-compatibilité du mode ``t`` explicite (jamais de MC).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import Project
from supplyscore.services import SupplyScoreService

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

#: N minimal accepté par le simulateur : suffisant et rapide pour les tests.
_N = 2_000


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    yield svc
    svc.close()


@pytest.fixture
def demo(service: SupplyScoreService) -> Project:
    """Projet de démonstration reproductible (KPIs, jalons et questionnaires)."""
    return service.seed_demo(n_ranks=2, seed=7)


def _ur_locaux(service: SupplyScoreService, project_id: str) -> dict[str, float]:
    """ur_local courant de chaque nœud du projet."""
    nodes = service.repo.nodes_by_project(project_id)
    assert nodes, "le projet doit avoir des nœuds"
    urs: dict[str, float] = {}
    for node in nodes:
        assert node.urgency.ur_local is not None
        urs[node.id] = node.urgency.ur_local
    return urs


# --- set_lead_time_mode / lead_time_mode --------------------------------------------


def test_set_lead_time_mode_round_trip(service: SupplyScoreService, demo: Project) -> None:
    assert service.lead_time_mode(demo.id) == {"mode": "analytique"}  # défaut
    service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N, graine=123)
    assert service.lead_time_mode(demo.id) == {
        "mode": "monte_carlo",
        "n_tirages": _N,
        "graine": 123,
    }
    service.set_lead_time_mode(demo.id, "analytique")
    assert service.lead_time_mode(demo.id)["mode"] == "analytique"
    assert service.lead_time_mode("projet-inconnu") == {"mode": "analytique"}


def test_set_lead_time_mode_inconnu_leve_value_error(
    service: SupplyScoreService, demo: Project
) -> None:
    with pytest.raises(ValueError, match="inconnu"):
        service.set_lead_time_mode(demo.id, "quantique")


@pytest.mark.parametrize("n_tirages", [0, 100, 1_999, 50_001, 1_000_000])
def test_set_lead_time_mode_n_tirages_hors_bornes(
    service: SupplyScoreService, demo: Project, n_tirages: int
) -> None:
    # CHOIX DOCUMENTÉ (orchestrateur) : n_tirages est validé à l'ÉCRITURE,
    # contre les bornes du simulateur — l'erreur ne peut pas atteindre evaluate_all.
    with pytest.raises(ValueError, match="n_tirages"):
        service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=n_tirages)
    assert service.lead_time_mode(demo.id) == {"mode": "analytique"}  # rien persisté


# --- mode MC : effet sur ur_local et bornes -----------------------------------------


def test_mode_mc_change_ur_local_et_reste_dans_les_bornes(
    service: SupplyScoreService, demo: Project
) -> None:
    service.evaluate_all()
    analytique = _ur_locaux(service, demo.id)

    service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N)
    service.evaluate_all()
    monte_carlo = _ur_locaux(service, demo.id)

    assert analytique.keys() == monte_carlo.keys()
    assert all(0.0 <= v <= 1.0 for v in analytique.values())
    assert all(0.0 <= v <= 1.0 for v in monte_carlo.values())
    diffs = [abs(analytique[nid] - monte_carlo[nid]) for nid in analytique]
    assert any(d > 1e-9 for d in diffs), "le u_time simulé doit changer au moins un ur_local"


# --- stabilité : graine stable par (project_id, semaine ISO) ------------------------


def test_stabilite_bit_a_bit_dans_la_meme_semaine(
    service: SupplyScoreService, demo: Project
) -> None:
    service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N)
    service.evaluate_all()
    premier = _ur_locaux(service, demo.id)
    graine_1 = service.last_mc_result(demo.id)
    service.evaluate_all()
    second = _ur_locaux(service, demo.id)
    graine_2 = service.last_mc_result(demo.id)
    assert premier == second  # IDENTIQUES bit à bit : le dashboard ne « clignote » pas
    assert graine_1 is not None and graine_2 is not None
    assert graine_1.graine == graine_2.graine


def test_graine_stockee_prioritaire_sur_la_graine_derivee(
    service: SupplyScoreService, demo: Project
) -> None:
    service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N, graine=42)
    service.evaluate_all()
    resultat = service.last_mc_result(demo.id)
    assert resultat is not None
    assert resultat.graine == 42
    assert resultat.n_tirages == _N


def test_advance_week_change_la_graine_sans_lever(
    service: SupplyScoreService, demo: Project
) -> None:
    service.set_clock_mode(demo.id, "game")
    service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N)
    service.evaluate_all()
    avant = service.last_mc_result(demo.id)
    assert avant is not None

    service.advance_week(demo.id)  # ne lève pas, réévalue en mode MC

    apres = service.last_mc_result(demo.id)
    assert apres is not None
    assert apres.graine != avant.graine  # nouvelle semaine ISO → nouvelle graine stable
    assert all(0.0 <= v <= 1.0 for v in _ur_locaux(service, demo.id).values())


# --- last_mc_result -----------------------------------------------------------------


def test_last_mc_result_none_en_analytique_renseigne_en_mc(
    service: SupplyScoreService, demo: Project
) -> None:
    service.evaluate_all()  # mode analytique par défaut
    assert service.last_mc_result(demo.id) is None

    service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N)
    service.evaluate_all()
    resultat = service.last_mc_result(demo.id)
    assert resultat is not None
    assert resultat.n_tirages == _N
    node_ids = {n.id for n in service.repo.nodes_by_project(demo.id)}
    assert node_ids <= set(resultat.u_time)  # u_time et IC95 disponibles pour l'UI
    assert node_ids <= set(resultat.ic95)

    # Le retour en analytique purge le dernier résultat (pas d'IC95 périmé).
    service.set_lead_time_mode(demo.id, "analytique")
    assert service.last_mc_result(demo.id) is None


# --- mode t explicite : JAMAIS de Monte Carlo (rétro-compat v1) ---------------------


def test_mode_t_explicite_jamais_de_monte_carlo(service: SupplyScoreService, demo: Project) -> None:
    service.evaluate_all(t=0.0)
    reference_v1 = _ur_locaux(service, demo.id)

    service.set_lead_time_mode(demo.id, "monte_carlo", n_tirages=_N)
    service.evaluate_all(t=0.0)

    assert service.last_mc_result(demo.id) is None  # aucun simulateur exécuté
    assert _ur_locaux(service, demo.id) == reference_v1  # rétro-compat v1 stricte
