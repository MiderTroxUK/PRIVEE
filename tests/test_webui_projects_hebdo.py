"""Cablage hebdo de la page Projets (lot 4.3b) - aucun serveur lance.

Couvre : colonne " Hebdo " du tableau des noeuds (texte_hebdo + synthese()
appelee UNE fois), ``style_data_conditional`` pose sur la colonne, et bandeau
" Projet actif " enrichi de la semaine ISO courante du projet selon SON
horloge (temps reel ou temps de jeu apres advance_week).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.domain.models import AHPAssessment, Project, SupplyNode
from supplyscore.services import SupplyScoreService
from supplyscore.services.weekly import CycleHebdomadaire
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components.badges import style_hebdo_conditionnel
from supplyscore.web_ui.pages import projects

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0
_STORE = {"project_id": "p1", "name": "Chaîne Alpha"}


def _assessment(node_id: str, ts: float) -> AHPAssessment:
    """Evaluation AHP minimale valide (iso_week derivee du timestamp)."""
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
    )


def _setup_projet(service: SupplyScoreService, node_ids: tuple[str, ...]) -> Project:
    """Cree le projet " p1 " et ses noeuds actifs (aucun arc, aucun jalon)."""
    project = Project(
        id="p1",
        name="Chaîne Alpha",
        owner_node_id=node_ids[0],
        created_at=_NOW - 5 * _WEEK,
        t0_ts=_NOW - 5 * _WEEK,
    )
    nodes = [
        SupplyNode(id=node_id, name=node_id, project_id="p1", rank=i)
        for i, node_id in enumerate(node_ids)
    ]
    service.create_project(project, nodes, [])
    return project


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


# Tableau : colonne " Hebdo "


def test_tableau_colonne_hebdo(service: SupplyScoreService, fixed_clock: FixedClock) -> None:
    _setup_projet(service, ("n-a", "n-b", "n-c"))

    # n-a : evalue cette semaine -> " A jour ".
    service.submit_assessment(_assessment("n-a", _NOW))
    # n-b : evalue il y a 2 semaines (horloge reculee puis re-avancee) -> " En retard ".
    fixed_clock.set(_NOW - 2 * _WEEK)
    service.submit_assessment(_assessment("n-b", _NOW - 2 * _WEEK))
    fixed_clock.set(_NOW)
    # n-c : jamais evalue -> " Manquant ".

    _, _, _, rows, _ = projects.update_view_callback(_STORE, 0)

    assert [row["Nom"] for row in rows] == ["n-a", "n-b", "n-c"]
    assert [row["Hebdo"] for row in rows] == ["À jour", "En retard (2 sem.)", "Manquant"]
    # Les autres colonnes du tableau restent servies.
    assert rows[0]["Statut"] == "Active"
    assert rows[0]["Rang"] == 0


def test_synthese_appelee_une_seule_fois(service: SupplyScoreService, monkeypatch) -> None:
    _setup_projet(service, ("n-a", "n-b", "n-c"))
    appels: list[str] = []
    originale = CycleHebdomadaire.synthese

    def espion(self: CycleHebdomadaire, project_id: str):
        appels.append(project_id)
        return originale(self, project_id)

    monkeypatch.setattr(CycleHebdomadaire, "synthese", espion)
    projects.update_view_callback(_STORE, 0)
    assert appels == ["p1"]


def test_layout_table_style_conditionnel_hebdo(service: SupplyScoreService) -> None:
    assert {"name": "Hebdo", "id": "Hebdo"} in projects._TABLE_COLUMNS
    table = _find_component(projects.layout(), "proj-table")
    assert table is not None
    assert table.style_data_conditional == style_hebdo_conditionnel("Hebdo")
    assert {"name": "Hebdo", "id": "Hebdo"} in table.columns


def _find_component(component, component_id: str):
    """Descente recursive dans l'arbre Dash jusqu'au composant d'id donne."""
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, list | tuple):
        children = [children]
    for child in children:
        found = _find_component(child, component_id)
        if found is not None:
            return found
    return None


# Bandeau " Projet actif " : semaine ISO et mode d'horloge


def test_bandeau_semaine_courante_temps_reel(service: SupplyScoreService) -> None:
    _setup_projet(service, ("n-a", "n-b"))
    *_, active = projects.update_view_callback(_STORE, 0)

    bandeau = str(active)
    assert iso_week(_NOW) == "2026-S24"
    assert "Projet actif : « Chaîne Alpha » (2 nœud(s)) — semaine 2026-S24 [temps réel]." in bandeau


def test_bandeau_mode_jeu_affiche_semaine_simulee(service: SupplyScoreService) -> None:
    _setup_projet(service, ("n-a",))
    service.set_clock_mode("p1", "game")  # origine = _NOW (horloge reelle figee)
    service.advance_week("p1", 2)

    *_, active = projects.update_view_callback(_STORE, 0)
    bandeau = str(active)

    semaine_simulee = iso_week(_NOW + 2 * _WEEK)
    assert semaine_simulee == "2026-S26"
    assert semaine_simulee != iso_week(_NOW)  # on a avance assez pour changer de semaine
    assert f"semaine {semaine_simulee} [temps de jeu]." in bandeau
    assert iso_week(_NOW) not in bandeau  # la semaine reelle n'apparait plus


def test_bandeau_sans_projet(service: SupplyScoreService) -> None:
    _, _, _, rows, active = projects.update_view_callback(None, 0)
    assert rows == []
    assert "Aucun projet sélectionné" in str(active)
