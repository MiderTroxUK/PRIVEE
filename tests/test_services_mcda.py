"""Tests d'intégration service — poids FBWM par projet et classement PROMETHEE II (Lot 12.3).

Couvre : persistance et round-trip de ``set_poids_criteres`` / ``poids_criteres``,
validation française (bloc inconnu, poids négatif, somme nulle), effet des poids
sur ``ur_local`` (cohérence avec ``UrModel(omega=...)`` recalculé à la main),
``classement_promethee`` (Σφ == 0, poids stockés utilisés, < 2 actifs → ValueError)
et le cache de ``_ur_model_for``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core import BLOCKS
from supplyscore.core.clock import FixedClock, iso_week, project_hours
from supplyscore.domain.models import Project, SupplyNode, TaskStatus
from supplyscore.mcda.promethee import ResultatPromethee
from supplyscore.services import SupplyScoreService

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

#: Poids très « time-lourds » vs très « co2-lourds » (mêmes clés, somme > 0).
_POIDS_TIME = {"time": 5.0, "cap": 0.1, "perf": 0.1, "risk": 0.1, "cost": 0.1, "co2": 0.1}
_POIDS_CO2 = {"time": 0.1, "cap": 0.1, "perf": 0.1, "risk": 0.1, "cost": 0.1, "co2": 5.0}


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
    urs: dict[str, float] = {}
    for node in service.repo.nodes_by_project(project_id):
        assert node.urgency.ur_local is not None
        urs[node.id] = node.urgency.ur_local
    return urs


# --- set_poids_criteres / poids_criteres ------------------------------------------


def test_set_poids_criteres_persiste_le_reglage(service: SupplyScoreService, demo: Project) -> None:
    service.set_poids_criteres(demo.id, _POIDS_TIME, methode="fbwm", xi_star=0.12)
    raw = service.registry.get_setting(demo.id, "omega_ur")
    assert raw == {
        "poids": _POIDS_TIME,
        "methode": "fbwm",
        "xi_star": 0.12,
        "iso_week": iso_week(_NOW),  # semaine du projet posée automatiquement
    }


def test_set_poids_criteres_iso_week_explicite(service: SupplyScoreService, demo: Project) -> None:
    service.set_poids_criteres(demo.id, _POIDS_TIME, iso_week_val="2026-S01")
    raw = service.registry.get_setting(demo.id, "omega_ur")
    assert raw is not None and raw["iso_week"] == "2026-S01"


def test_poids_criteres_round_trip(service: SupplyScoreService, demo: Project) -> None:
    assert service.poids_criteres(demo.id) is None  # rien de stocké au départ
    service.set_poids_criteres(demo.id, _POIDS_CO2)
    assert service.poids_criteres(demo.id) == _POIDS_CO2


def test_poids_criteres_reglage_corrompu_sans_poids(
    service: SupplyScoreService, demo: Project
) -> None:
    # Réglage présent mais sans clé « poids » exploitable : ignoré proprement.
    service.registry.set_setting(demo.id, "omega_ur", {"methode": "fbwm"})
    assert service.poids_criteres(demo.id) is None


@pytest.mark.parametrize(
    ("poids", "motif"),
    [
        ({"fantome": 1.0}, "inconnu"),
        ({"time": 1.0, "vitesse": 2.0}, "inconnu"),
        ({"time": -0.1, "risk": 1.0}, "négatif"),
        ({"time": 0.0, "risk": 0.0}, "strictement positive"),
        ({}, "strictement positive"),
    ],
)
def test_set_poids_criteres_invalides(
    service: SupplyScoreService, demo: Project, poids: dict[str, float], motif: str
) -> None:
    with pytest.raises(ValueError, match=motif):
        service.set_poids_criteres(demo.id, poids)
    assert service.poids_criteres(demo.id) is None  # rien n'a été persisté


# --- effet des poids sur ur_local (OU probabiliste pondéré) -------------------------


def test_changer_les_poids_change_ur_local(service: SupplyScoreService, demo: Project) -> None:
    service.set_poids_criteres(demo.id, _POIDS_TIME)
    service.evaluate_all()
    ur_time = _ur_locaux(service, demo.id)

    service.set_poids_criteres(demo.id, _POIDS_CO2)
    service.evaluate_all()
    ur_co2 = _ur_locaux(service, demo.id)

    assert ur_time.keys() == ur_co2.keys()
    diffs = [abs(ur_time[nid] - ur_co2[nid]) for nid in ur_time]
    assert any(d > 1e-9 for d in diffs), "des poids opposés doivent changer au moins un ur_local"


def test_ur_local_coherent_avec_ur_model_recalcule_a_la_main(
    service: SupplyScoreService, demo: Project
) -> None:
    service.set_poids_criteres(demo.id, _POIDS_CO2)
    service.evaluate_all()
    attendu_model = dataclasses.replace(
        service.ur_model, omega={**service.ur_model.omega, **_POIDS_CO2}
    )
    t0 = demo.origin_ts
    t_h = project_hours(_NOW, t0)
    nodes = service.repo.nodes_by_project(demo.id)
    assert nodes, "le projet de démo doit avoir des nœuds"
    for node in nodes:
        attendu = attendu_model.ur_local(
            t_h,
            node.kpis,
            status=node.status,
            milestones=service.registry.list_milestones(node.id),
            t0_ts=t0,
        )
        assert node.urgency.ur_local == pytest.approx(attendu, abs=1e-12)


# --- classement PROMETHEE II ------------------------------------------------------


def test_classement_promethee_couvre_tous_les_noeuds_actifs(
    service: SupplyScoreService, demo: Project
) -> None:
    resultat = service.classement_promethee(demo.id)
    assert isinstance(resultat, ResultatPromethee)
    actifs = {
        n.id
        for n in service.repo.nodes_by_project(demo.id)
        if n.status == TaskStatus.ACTIVE and n.onboarding_state != "draft"
    }
    assert set(resultat.classement) == actifs
    assert set(resultat.phi) == actifs
    assert abs(sum(resultat.phi.values())) < 1e-9  # Σφ == 0 (propriété PROMETHEE II)


def test_classement_promethee_utilise_les_poids_stockes(
    service: SupplyScoreService, demo: Project
) -> None:
    uniforme = service.classement_promethee(demo.id)  # aucun poids stocké : ω par défaut
    service.set_poids_criteres(demo.id, _POIDS_TIME)
    pondere = service.classement_promethee(demo.id)
    diffs = [abs(uniforme.phi[nid] - pondere.phi[nid]) for nid in uniforme.phi]
    assert any(d > 1e-12 for d in diffs), "les poids stockés doivent modifier les flux φ"
    assert abs(sum(pondere.phi.values())) < 1e-9


def test_classement_promethee_exclut_les_blocs_de_poids_nul(
    service: SupplyScoreService, demo: Project
) -> None:
    # Poids nuls autorisés à l'écriture (somme > 0) : les blocs à 0 sont
    # exclus du classement (PrometheeII exige des poids strictement positifs).
    service.set_poids_criteres(demo.id, {"time": 1.0, "co2": 0.0})
    resultat = service.classement_promethee(demo.id)
    assert abs(sum(resultat.phi.values())) < 1e-9


def test_classement_promethee_moins_de_deux_actifs(service: SupplyScoreService) -> None:
    project = Project(id="p-solo", name="Solo", owner_node_id="s-1", created_at=_NOW, t0_ts=_NOW)
    nodes = [
        SupplyNode(id="s-1", name="s-1", project_id="p-solo"),
        SupplyNode(id="s-2", name="s-2", project_id="p-solo", status=TaskStatus.DONE),
        SupplyNode(id="s-3", name="s-3", project_id="p-solo", onboarding_state="draft"),
    ]
    service.create_project(project, nodes, [])
    with pytest.raises(ValueError, match="2 nœuds actifs"):
        service.classement_promethee("p-solo")


def test_classement_promethee_projet_inconnu(service: SupplyScoreService) -> None:
    with pytest.raises(ValueError, match="2 nœuds actifs"):
        service.classement_promethee("projet-fantome")


# --- _ur_model_for : défaut, fusion, cache ----------------------------------------


def test_ur_model_for_sans_poids_retourne_le_modele_par_defaut(
    service: SupplyScoreService, demo: Project
) -> None:
    assert service._ur_model_for(demo.id) is service.ur_model
    assert service._ur_model_for(None) is service.ur_model


def test_ur_model_for_fusionne_les_poids_et_met_en_cache(
    service: SupplyScoreService, demo: Project
) -> None:
    service.set_poids_criteres(demo.id, {"time": 2.0})
    model = service._ur_model_for(demo.id)
    assert model is not service.ur_model
    assert model.omega["time"] == 2.0
    for bloc in BLOCKS:
        if bloc != "time":
            assert model.omega[bloc] == service.ur_model.omega[bloc]  # défauts conservés
    assert service._ur_model_for(demo.id) is model  # cache : même objet au second appel

    service.set_poids_criteres(demo.id, {"time": 3.0})  # invalide le cache
    assert service._ur_model_for(demo.id).omega["time"] == 3.0
