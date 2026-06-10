"""Smoke tests de l'UI web Dash — aucun serveur lancé.

Les callbacks étant des fonctions nommées au niveau module (enregistrées via
``app.callback(...)(fn)`` dans ``register_callbacks``), ils sont appelés
directement ici, sans contexte de requête Dash.
"""

import pytest

from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.app import create_app
from supplyscore.web_ui.components.figures import (
    dashboard_dag_figure,
    urgency_history_figure,
)
from supplyscore.web_ui.pages import dashboard, projects, questionnaire, simulation


@pytest.fixture
def service(tmp_path):
    """Service seedé avec une petite démo, partagé par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)


# --- Application -----------------------------------------------------------------

def test_create_app_builds_layout(service):
    app = create_app(service=service)
    assert app.title == "SupplyScore"
    tree = str(app.layout)
    for component_id in ("url", "store-project", "page-content"):
        assert component_id in tree


# --- Layouts des 4 pages ------------------------------------------------------------

@pytest.mark.parametrize(
    ("page", "expected_id"),
    [
        (projects, "proj-table"),
        (questionnaire, "q-save-btn"),
        (dashboard, "dash-table"),
        (simulation, "sim-run-btn"),
    ],
    ids=["projects", "questionnaire", "dashboard", "simulation"],
)
def test_page_layout_builds(service, page, expected_id):
    tree = str(page.layout())
    assert expected_id in tree


# --- Figures du dashboard avec les données de la démo --------------------------------

def test_dashboard_figures_with_demo_data(service):
    nodes = service.repo.nodes()
    arcs = service.repo.arcs()
    assert nodes and arcs

    dag = dashboard_dag_figure(nodes, arcs)
    assert len(dag.data) >= 2  # trace des arêtes + trace des nœuds
    assert len(dag.data[1].x) == len(nodes)

    node = nodes[0]
    series = service.client_db(node.id).urgency_series(node.id)
    assert series, "seed_demo doit avoir persisté un historique d'urgence"
    hist = urgency_history_figure(series, node.name)
    assert len(hist.data) == 3  # Ud, Ur et A


# --- Logique de sauvegarde du questionnaire -----------------------------------------

def _pair_args():
    pair_ids = [{"type": "ahp-pair", "index": f"{i}-{j}"}
                for i, j in questionnaire.PAIRS]
    return [0] * len(pair_ids), pair_ids


def _score_args():
    score_ids = [{"type": "ahp-score", "index": str(k)} for k in range(4)]
    return [3] * 4, score_ids


def _kpi_args():
    kpi_ids = [{"type": "kpi-input", "index": key}
               for _, fields in questionnaire.KPI_FIELDS
               for key, _ in fields]
    return [None] * len(kpi_ids), kpi_ids


def test_save_assessment_callback_persists(service):
    node = service.repo.nodes()[0]
    before = len(service.client_db(node.id).list_assessments(node.id))

    pair_values, pair_ids = _pair_args()
    score_values, score_ids = _score_args()
    kpi_values, kpi_ids = _kpi_args()
    kpi_values[0] = 120.0  # premier champ : time.lead_time_h

    message = questionnaire.save_assessment_callback(
        1, {"project_id": node.project_id}, node.id, "test", "",
        pair_values, pair_ids, score_values, score_ids, kpi_values, kpi_ids,
    )

    after = service.client_db(node.id).list_assessments(node.id)
    assert len(after) == before + 1
    assert after[-1].operator_id == "test"
    # Notes à 3/6 -> Saaty 4.2, poids égaux -> Ud = (4.2 - 1) / 8 = 0.4
    assert after[-1].ud == pytest.approx(0.4)
    assert after[-1].is_consistent
    assert "enregistrée" in str(message)
    # Le KPI renseigné a bien été écrit sur le nœud et persisté.
    assert service.repo.get_node(node.id).kpis.time.lead_time_h == pytest.approx(120.0)
    assert service.registry.get_node(node.id).kpis.time.lead_time_h == pytest.approx(120.0)


def test_save_assessment_requires_operator(service):
    node = service.repo.nodes()[0]
    before = len(service.client_db(node.id).list_assessments(node.id))

    pair_values, pair_ids = _pair_args()
    score_values, score_ids = _score_args()
    kpi_values, kpi_ids = _kpi_args()

    message = questionnaire.save_assessment_callback(
        1, {"project_id": node.project_id}, node.id, "", "",
        pair_values, pair_ids, score_values, score_ids, kpi_values, kpi_ids,
    )

    assert len(service.client_db(node.id).list_assessments(node.id)) == before
    assert "opérateur" in str(message)
