"""Tests de la page " Donnees brutes " (" /admin ") - sans serveur Dash.

``layout()`` et les callbacks (fonctions nommees) sont appeles directement
sur un service seede (FixedClock, set_service/teardown). Couvre : bandeau
rouge et dropdowns, options de tables avec [verrou], chargement pagine avec
``rowid``, verrouillage (FORBIDDEN jamais editable meme deverrouille) et le
callback d'edition (succes -> message DeltaUr, refus -> table rechargee).
"""

from __future__ import annotations

import copy
from datetime import datetime

import dash
import pytest
from dash.exceptions import PreventUpdate

from supplyscore.core.clock import FixedClock
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import admin_data

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()


@pytest.fixture
def service(tmp_path):
    """Service seede avec une petite demo, partage par la page (teardown propre)."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


# layout


def test_layout_contains_red_banner_and_dropdowns(service):
    text = str(admin_data.layout())

    assert "Zone avancée : édition cellule par cellule, sous audit." in text
    assert "Les tables d'historique sont inéditables par construction." in text
    assert "admin-db-dd" in text
    assert "admin-table-dd" in text
    assert "admin-table" in text
    assert "Déverrouiller l'édition" in text
    assert "Vous éditez les données brutes sous audit. Continuer ?" in text


def test_layout_db_options_registre_and_node_names(service):
    text = str(admin_data.layout())

    assert "Registre" in text
    for node in service.registry.list_nodes():
        assert node.name in text


def test_layout_table_locked_by_default(service):
    text = str(admin_data.layout())
    assert "editable=False" in text


# tables_callback


def test_tables_callback_labels_rows_and_lock(service):
    options, value = admin_data.tables_callback("registry")

    assert value is None
    labels = {option["value"]: option["label"] for option in options}
    n_nodes = len(service.registry.list_nodes())
    assert labels["nodes"] == f"nodes ({n_nodes} lignes)"
    assert labels["audit_log"].endswith("🔒")
    assert "🔒" not in labels["arcs"]


def test_tables_callback_without_db(service):
    assert admin_data.tables_callback(None) == ([], None)


# table_data_callback


def test_table_data_callback_loads_rows_with_rowid(service):
    data, columns, page_count = admin_data.table_data_callback("nodes", 0, "registry")

    assert data and all("rowid" in row for row in data)
    by_id = {column["id"]: column for column in columns}
    assert by_id["rowid"]["editable"] is False
    # Les autres colonnes ne portent PAS d'editable par colonne (il contournerait le verrou global de la table).
    assert "editable" not in by_id["label"]
    assert page_count >= 1


def test_table_data_callback_without_selection(service):
    assert admin_data.table_data_callback(None, 0, None) == ([], [], 1)


def test_reset_page_callback(service):
    assert admin_data.reset_page_callback("nodes") == 0


# unlock_callback


def test_unlock_callback_locked_without_confirmation(service):
    assert admin_data.unlock_callback(None, "nodes", "registry") is False


def test_unlock_callback_unlocks_whitelisted_table(service):
    assert admin_data.unlock_callback(1, "nodes", "registry") is True


def test_unlock_callback_forbidden_table_never_editable(service):
    # Meme deverrouillee, une table d'historique reste en lecture seule.
    assert admin_data.unlock_callback(1, "audit_log", "registry") is False
    node_id = service.registry.list_nodes()[0].id
    assert admin_data.unlock_callback(1, "urgency_history", node_id) is False


def test_unlock_callback_table_outside_whitelist(service):
    assert admin_data.unlock_callback(1, "node_urgency", "registry") is False


# edit_callback


def _edited(data, row_index, column, value):
    """Copie de ``data`` avec UNE cellule modifiee (simule l'edition UI)."""
    edited = copy.deepcopy(data)
    edited[row_index][column] = value
    return edited


def test_edit_callback_valid_cell_revalidates_with_delta_ur(service):
    data, _, _ = admin_data.table_data_callback("nodes", 0, "registry")
    edited = _edited(data, 0, "label", "Étiquette brute")

    message, rows = admin_data.edit_callback(
        1234, edited, data, "registry", "nodes", 0, {"name": "op-ui"}
    )

    text = str(message)
    assert "1 cellule modifiée, revalidation OK" in text
    assert "ΔUr max =" in text
    assert "nœud(s)" in text
    # La valeur est persistee et la table rechargee la reflete.
    node_id = data[0]["id"]
    assert service.registry.get_node(node_id).label == "Étiquette brute"
    assert rows[0]["label"] == "Étiquette brute"


def test_edit_callback_refused_value_reloads_table(service):
    data, _, _ = admin_data.table_data_callback("arcs", 0, "registry")
    old_gamma = data[0]["gamma"]
    edited = _edited(data, 0, "gamma", "5")

    message, rows = admin_data.edit_callback(1234, edited, data, "registry", "arcs", 0, None)

    assert "aucune écriture" in str(message)
    assert rows[0]["gamma"] == old_gamma
    arc = service.registry.get_arc(data[0]["source_id"], data[0]["target_id"])
    assert arc.gamma == old_gamma


def test_edit_callback_forbidden_table_shows_refusal(service):
    node_id = service.registry.list_nodes()[0].id
    data, _, _ = admin_data.table_data_callback("urgency_history", 0, node_id)
    edited = _edited(data, 0, "ud", 0.99)

    message, rows = admin_data.edit_callback(
        1234, edited, data, node_id, "urgency_history", 0, None
    )

    assert "Édition refusée" in str(message)
    assert rows[0]["ud"] == data[0]["ud"]


def test_edit_callback_without_change_prevents_update(service):
    data, _, _ = admin_data.table_data_callback("nodes", 0, "registry")
    with pytest.raises(PreventUpdate):
        admin_data.edit_callback(1234, copy.deepcopy(data), data, "registry", "nodes", 0, None)


def test_edit_callback_without_previous_prevents_update(service):
    with pytest.raises(PreventUpdate):
        admin_data.edit_callback(1234, [], None, "registry", "nodes", 0, None)


# register_callbacks


def test_register_callbacks_registers_all(service):
    app = dash.Dash(__name__)
    admin_data.register_callbacks(app)
    assert len(app.callback_map) >= 5
