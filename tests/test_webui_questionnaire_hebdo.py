"""Tests du cablage hebdo de la page Questionnaire (Lot 4.3c) - sans serveur.

Couvre : bandeau projet avec semaine ISO courante (" Semaine 2026-S24 "),
statuts hebdo dans les libelles du dropdown noeud (A jour / En retard (n sem.) /
Manquant) et message de confirmation mentionnant la semaine enregistree.
Les callbacks sont appeles directement (fonctions module), service seede
partage via ``set_service`` et libere en teardown.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import AHPAssessment, Project, SupplyNode
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import questionnaire

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0


@pytest.fixture
def service(tmp_path: Path):
    """Service a horloge figee (2026-S24), partage par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


def _assessment(node_id: str, iso_week: str = "", ts: float = _NOW) -> AHPAssessment:
    """Evaluation AHP minimale valide ; iso_week vide -> posee par le service."""
    return AHPAssessment(
        node_id=node_id,
        project_id="p1",
        operator_id="op",
        comparisons={(0, 1): 1.0},
        criteria_scores=[5.0, 5.0],
        weights=[0.5, 0.5],
        consistency_ratio=0.0,
        is_consistent=True,
        ud=0.5,
        timestamp=ts,
        iso_week=iso_week,
    )


def _setup_projet_trois_statuts(service: SupplyScoreService) -> Project:
    """Projet " p1 " : n-a evalue cette semaine, n-b il y a 2 semaines, n-c jamais."""
    project = Project(
        id="p1",
        name="Projet hebdo",
        owner_node_id="n-a",
        created_at=_NOW - 5 * _WEEK,
        t0_ts=_NOW - 5 * _WEEK,
    )
    nodes = [
        SupplyNode(id=node_id, name=node_id, project_id="p1", rank=i)
        for i, node_id in enumerate(("n-a", "n-b", "n-c"))
    ]
    service.create_project(project, nodes, [])
    service.submit_assessment(_assessment("n-a"))
    service.submit_assessment(_assessment("n-b", iso_week="2026-S22", ts=_NOW - 2 * _WEEK))
    return project


# Bandeau projet : semaine ISO courante


def test_bandeau_affiche_semaine_courante_du_projet(service):
    project = _setup_projet_trois_statuts(service)

    info, _ = questionnaire.project_info_callback({"project_id": project.id, "name": project.name})

    assert "Projet hebdo" in str(info)
    assert "Semaine 2026-S24" in str(info)


def test_bandeau_sans_projet_inchange(service):
    _setup_projet_trois_statuts(service)

    info, options = questionnaire.project_info_callback(None)

    assert "Aucun projet sélectionné" in str(info)
    assert "Semaine" not in str(info)
    # Sans projet, pas d'horloge de reference : libelles sans statut hebdo.
    assert all(option["label"].endswith(")") for option in options)


# Dropdown noeud : statut hebdo dans les libelles


def test_options_dropdown_portent_le_statut_hebdo(service):
    project = _setup_projet_trois_statuts(service)

    _, options = questionnaire.project_info_callback(
        {"project_id": project.id, "name": project.name}
    )

    labels = {option["value"]: option["label"] for option in options}
    assert labels["n-a"] == "n-a (rang 0 — Workshop) — À jour"
    assert labels["n-b"] == "n-b (rang 1 — Workshop) — En retard (2 sem.)"
    assert labels["n-c"] == "n-c (rang 2 — Workshop) — Manquant"


# Confirmation d'enregistrement : semaine mentionnee


def _pair_args():
    pair_ids = [{"type": "ahp-pair", "index": f"{i}-{j}"} for i, j in questionnaire.PAIRS]
    return [0] * len(pair_ids), pair_ids


def _score_args():
    score_ids = [{"type": "ahp-score", "index": str(k)} for k in range(4)]
    return [3] * 4, score_ids


def _kpi_args():
    kpi_ids = [
        {"type": "kpi-input", "index": key}
        for _, fields in questionnaire.KPI_FIELDS
        for key, _ in fields
    ]
    return [None] * len(kpi_ids), kpi_ids


def test_message_de_succes_mentionne_la_semaine_enregistree(service):
    project = service.seed_demo(n_ranks=2, seed=1)
    node = service.repo.nodes()[0]

    pair_values, pair_ids = _pair_args()
    score_values, score_ids = _score_args()
    kpi_values, kpi_ids = _kpi_args()

    message = questionnaire.save_assessment_callback(
        1,
        {"project_id": project.id, "name": project.name},
        node.id,
        "testeur",
        "",
        pair_values,
        pair_ids,
        score_values,
        score_ids,
        kpi_values,
        kpi_ids,
    )

    text = str(message)
    assert "Évaluation enregistrée" in text
    assert "semaine 2026-S24" in text
    # La semaine affichee est bien celle persistee avec l'evaluation.
    assert service.client_db(node.id).last_assessment_week(node.id) == "2026-S24"
