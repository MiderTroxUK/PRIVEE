"""Tests E16 (Lots 16.4–16.6) — polissage des pages secondaires, sans serveur.

Couvre, pour les neuf pages du lot B (projects, onboarding, node_detail,
explain, questionnaire, editor, graph_editor, admin_data, simulation) :

- les ``dcc.Loading`` (type "circle") autour des zones lentes — l'id reste
  posé sur le composant INTERNE (DataTable, Graph, Div), jamais sur le
  Loading lui-même ;
- les états vides : sans projet actif, layouts et callbacks ne lèvent pas et
  affichent une invitation française claire ;
- la chasse au texte anglais visible (DoD E16) : aucun mot de la liste
  pragmatique ``MOTS_ANGLAIS`` dans les layouts. La vérification est
  SENSIBLE à la casse — exclusion documentée : les ids techniques en
  minuscules (« q-save-btn », « arc-del-dd »…) et les valeurs de données
  (« nominal », « backup », labels métier stockés) ne sont pas des libellés
  et ne déclenchent donc pas de faux positifs ;
- le format français des messages (virgule décimale dans les PHRASES — pas
  dans les inputs ni les colonnes numériques de DataTable) ;
- la non-régression des ids critiques épinglés par les tests navigateur.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from dash import dcc

from supplyscore.core.clock import FixedClock
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import (
    admin_data,
    editor,
    explain,
    graph_editor,
    node_detail,
    onboarding,
    projects,
    questionnaire,
    simulation,
)

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

#: Liste pragmatique des mots anglais interdits dans les layouts (DoD E16).
MOTS_ANGLAIS = [
    "Submit",
    "Save",
    "Delete",
    "Loading...",
    "Choose",
    "Select a",
    "Unknown",
    "Error:",
]


@pytest.fixture
def service(tmp_path):
    """Service seedé avec une petite démo évaluée, partagé par les pages."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


def _demo_node(service):
    """Premier nœud de la démo évalué (assessment + adéquation propagée)."""
    for node in sorted(service.repo.nodes(), key=lambda n: (n.rank, n.name)):
        if (
            node.urgency.adequation is not None
            and service.client_db(node.id).latest_assessment(node.id) is not None
        ):
            return node
    pytest.fail("la démo doit contenir un nœud évalué")


# --- Aides de parcours de l'arbre de composants ---------------------------------------


def _subtree_contains_id(component, component_id: str) -> bool:
    """True si l'arbre de composants contient l'id (simple, pas pattern-matching)."""
    if getattr(component, "id", None) == component_id:
        return True
    children = getattr(component, "children", None)
    if children is None:
        return False
    if not isinstance(children, (list, tuple)):
        children = [children]
    return any(_subtree_contains_id(child, component_id) for child in children)


def _loading_de(component, component_id: str):
    """Premier ``dcc.Loading`` de l'arbre dont le sous-arbre porte l'id donné."""
    if isinstance(component, dcc.Loading) and _subtree_contains_id(component, component_id):
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        found = _loading_de(child, component_id)
        if found is not None:
            return found
    return None


def _assert_loading(tree, component_id: str, page: str) -> None:
    """Assertion commune : un Loading « circle » entoure le composant d'id donné."""
    loading = _loading_de(tree, component_id)
    assert loading is not None, f"dcc.Loading absent autour de « {component_id} » ({page})"
    assert loading.type == "circle", f"Loading de « {component_id} » ({page}) : type != circle"
    # L'id reste sur le composant INTERNE, jamais sur le Loading lui-même.
    assert getattr(loading, "id", None) != component_id


# --- 1) dcc.Loading autour des zones lentes -------------------------------------------


@pytest.mark.parametrize(
    ("nom", "ids"),
    [
        ("projects", ("proj-table",)),
        ("onboarding", ("onb-step-content",)),
        ("editor", ("kpi-edit-table",)),
        ("graph_editor", ("arc-edit-table",)),
        ("admin_data", ("admin-table",)),
        ("simulation", ("sim-dag-fig", "sim-scn-table", "sim-crit-fig")),
    ],
)
def test_loading_sur_les_zones_lentes(service, nom, ids):
    page = {
        "projects": projects,
        "onboarding": onboarding,
        "editor": editor,
        "graph_editor": graph_editor,
        "admin_data": admin_data,
        "simulation": simulation,
    }[nom]
    tree = page.layout()
    for component_id in ids:
        _assert_loading(tree, component_id, nom)


def test_loading_fiche_noeud(service):
    node = _demo_node(service)
    tree = node_detail.layout(node.id)
    # Cartes éditables (corps re-rendus par les callbacks), jalons et audit.
    for component_id in (
        "fiche-identity-body",
        "fiche-cdc-body",
        "fiche-kpis-body",
        "fiche-milestones-body",
        "history-table",
    ):
        _assert_loading(tree, component_id, "node_detail")


def test_loading_explication(service):
    node = _demo_node(service)
    tree = explain.layout(node.id)
    # Les deux graphes de propagation sont TOUJOURS rendus ; les graphes Ud/Ur
    # dépendent de l'état du nœud — s'ils sont montés, ils sont sous Loading.
    for component_id in ("explain-prop-ur-graph", "explain-prop-ud-graph"):
        _assert_loading(tree, component_id, "explain")
    for component_id in ("explain-ud-graph", "explain-ur-graph"):
        if _subtree_contains_id(tree, component_id):
            _assert_loading(tree, component_id, "explain")


# --- 2) états vides : sans projet actif, invitation claire et aucun plantage -----------


def test_etat_vide_projects(service):
    *_, rows, active = projects.update_view_callback(None, 0)
    assert rows == []
    assert "Aucun projet sélectionné" in str(active)
    assert "choisissez ou créez un projet" in str(active)


def test_etat_vide_onboarding(service):
    drafts = onboarding.render_drafts_callback(None, 0, {"node_id": None, "step": 1})
    assert "Sélectionnez d'abord un projet actif" in str(drafts)
    step = onboarding.render_step_callback({"node_id": None, "step": 1}, 0)
    assert "Aucun onboarding en cours" in str(step)


def test_etat_vide_editor(service):
    _columns, rows = editor.refresh_table_callback(None, "Temps", [])
    assert rows == []
    # Invitation statique de la page (le nombre de callbacks est épinglé à 3).
    assert "Sélectionnez d'abord un projet" in str(editor.layout())


def test_etat_vide_graph_editor(service):
    *_, info = graph_editor.refresh_view_callback(None, 0)
    texte = str(info)
    assert "Aucun projet sélectionné" in texte
    assert "sélectionnez un projet" in texte


def test_etat_vide_admin(service):
    assert admin_data.tables_callback(None) == ([], None)
    assert admin_data.table_data_callback(None, 0, None) == ([], [], 1)
    assert "Choisissez d'abord une base puis une table" in str(admin_data.layout())


def test_etat_vide_simulation(service):
    figure = simulation.criticite_callback(1, None)
    assert "Sélectionnez d'abord un projet" in figure.layout.annotations[0].text


def test_etat_vide_questionnaire(service):
    info, options = questionnaire.project_info_callback(None)
    assert "Aucun projet sélectionné" in str(info)
    assert options  # tous les nœuds du graphe restent proposés


# --- 3) chasse au texte anglais visible (DoD E16) ---------------------------------------


def test_aucun_texte_anglais_visible(service):
    node = _demo_node(service)
    layouts = {
        "projects": projects.layout(),
        "onboarding": onboarding.layout(),
        "questionnaire": questionnaire.layout(),
        "editor": editor.layout(),
        "graph_editor": graph_editor.layout(),
        "admin_data": admin_data.layout(),
        "simulation": simulation.layout(),
        "node_detail": node_detail.layout(node.id),
        "explain": explain.layout(node.id),
    }
    for nom, tree in layouts.items():
        texte = str(tree)
        for mot in MOTS_ANGLAIS:
            assert mot not in texte, f"texte anglais « {mot} » visible sur la page {nom}"


def test_labels_metier_traduits_dans_les_dropdowns(service):
    options = projects.label_metier_options()
    assert {"label": "Usine (Factory)", "value": "Factory"} in options
    assert {"label": "Fournisseur (Supplier)", "value": "Supplier"} in options
    assert {"label": "Client", "value": "Client"} in options  # déjà français
    # Les deux pages affichent les libellés français, valeurs techniques intactes.
    assert "Entrepôt (Warehouse)" in str(projects.layout())
    assert "Atelier (Workshop)" in str(onboarding.layout())


# --- 4) format français des messages (virgule décimale dans les phrases) ----------------


def test_helpers_fr_virgule_decimale(service):
    assert node_detail._fr(0.1234) == "0,123"
    assert admin_data._fr(1.0) == "1,000"
    assert questionnaire._fr(0.1, 2) == "0,10"
    assert simulation._fr(0.5, signe=True) == "+0,500"
    assert simulation._fr(-0.25, 2, signe=True) == "-0,25"


def test_message_cr_du_questionnaire_en_francais(service):
    pair_ids = [{"type": "ahp-pair", "index": f"{i}-{j}"} for i, j in questionnaire.PAIRS]
    score_ids = [{"type": "ahp-score", "index": str(k)} for k in range(4)]
    _badge, cr_msg, _fig = questionnaire.preview_callback(
        [0] * len(pair_ids), [3] * 4, pair_ids, score_ids
    )
    texte = str(cr_msg)
    assert "CR = 0,000 < 0,10 : jugements cohérents." in texte


def test_message_simulation_en_francais(service):
    node = _demo_node(service)
    _dag, _bars, message = simulation.simulate_callback(1, node.id, 1.0, None)
    texte = str(message)
    assert "Le choc sur" in texte  # préfixe épinglé par les tests navigateur
    assert "Ur_local = 1,00" in texte


# --- 5) libellés d'aide ------------------------------------------------------------------


def test_libelles_d_aide_gamma_beta_et_cartes(service):
    texte = str(graph_editor.layout())
    assert "γ : force avec laquelle le besoin du client tire ce fournisseur" in texte
    assert "β : force avec laquelle le risque du fournisseur remonte" in texte

    assert "la colonne « Fiche » ouvre la fiche 360°" in str(projects.layout())
    # Le bandeau rouge d'avertissement de la zone admin reste en place.
    assert "Zone avancée : édition cellule par cellule, sous audit." in str(admin_data.layout())


# --- 6) non-régression des ids critiques -------------------------------------------------


def test_ids_critiques_inchanges(service):
    node = _demo_node(service)
    cas = {
        "sim-run-btn": simulation.layout(),
        "demo-btn": projects.layout(),
        "q-node-dd": questionnaire.layout(),
        "onb-start-btn": onboarding.layout(),
        "admin-unlock": admin_data.layout(),
        "kpi-edit-table": editor.layout(),
        "arc-edit-table": graph_editor.layout(),
        "store-fiche": node_detail.layout(node.id),
    }
    for component_id, tree in cas.items():
        assert component_id in str(tree), f"id critique manquant : {component_id}"
