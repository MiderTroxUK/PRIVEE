"""Tests de la page " Edition des KPIs " (Lot 10.3) - sans serveur Dash.

Les callbacks sont des fonctions nommees au niveau module : ils sont appeles
directement, sur un service seede a horloge figee partage via ``set_service``
(libere en teardown). Couvre la construction du tableau (colonnes du bloc avec
unites, row ids stables, filtre par tags), le diff de cellule par ROW ID
(jamais par index - y compris lignes reordonnees), la coercition ``float()``,
l'effacement (None), le rejet hors bornes (table rechargee, AUCUN audit) et
les branches d'erreur (noeud inconnu, valeur non numerique, data_previous
absent).
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import dash
import pytest
from dash import dcc, html, no_update

from supplyscore.core.clock import FixedClock
from supplyscore.data.audit import AuditTrail
from supplyscore.domain.models import Project, SupplyNode
from supplyscore.domain.tags import Tag
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import editor

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()


@pytest.fixture
def service(tmp_path: Path):
    """Service a horloge figee, seede avec un projet " p1 " a 3 noeuds tagues."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    _seed(svc)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


def _seed(service: SupplyScoreService) -> None:
    """Projet p1 : n-a (tag eu), n-b (tag asia), n-c (sans tag) + KPIs initiaux."""
    project = Project(id="p1", name="Projet édition", owner_node_id="n-a", t0_ts=_NOW)
    service.registry.save_project(project)
    service.registry.save_tag(Tag(id="t-eu", project_id="p1", name="Europe"))
    service.registry.save_tag(Tag(id="t-asia", project_id="p1", name="Asie"))
    nodes = [
        SupplyNode(id="n-a", name="Atelier A", project_id="p1", rank=0, tags=["t-eu"]),
        SupplyNode(id="n-b", name="Broyeur B", project_id="p1", rank=1, tags=["t-asia"]),
        SupplyNode(id="n-c", name="Carrière C", project_id="p1", rank=2),
    ]
    nodes[0].kpis.time.lead_time_h = 24.0
    nodes[0].kpis.risk.failure_probability = 0.2
    service.create_project(project, nodes, [])


def _rows(block: str = "Temps", tags: list | None = None) -> list[dict]:
    """Lignes courantes du tableau pour " p1 " (relues depuis la base)."""
    _columns, rows = editor.refresh_table_callback("p1", block, tags or [])
    return rows


def _trail(service: SupplyScoreService, node_id: str) -> AuditTrail:
    """Journal d'audit de la base CLIENT du noeud."""
    db = service.client_db(node_id)
    return AuditTrail(db.conn, service.clock, lock=db.lock)


# refresh_table_callback


def test_colonnes_du_bloc_temps_avec_unites(service):
    columns, rows = editor.refresh_table_callback("p1", "Temps", [])

    assert columns[0] == {"name": "Nœud", "id": "Nœud", "editable": False}
    by_id = {c["id"]: c for c in columns[1:]}
    assert set(by_id) == {"time.lead_time_h", "time.lead_time_std_h", "time.deadline_h"}
    for column in by_id.values():
        assert column["type"] == "numeric"
        assert column["editable"] is True
        assert "(h)" in column["name"]  # unite presente dans le libelle
    # Lignes triees par rang/nom, chacune portant son row id stable == node_id.
    assert [r["id"] for r in rows] == ["n-a", "n-b", "n-c"]
    assert rows[0]["Nœud"] == "Atelier A"
    assert rows[0]["time.lead_time_h"] == 24.0
    assert rows[1]["time.lead_time_h"] is None


def test_colonne_sans_parenthese_suffixee_par_kpi_unit(service):
    columns, _rows = editor.refresh_table_callback("p1", "Coût", [])

    names = {c["id"]: c["name"] for c in columns}
    assert names["cost.nominal_op_cost"] == "Coût opérationnel nominal (€)"
    # Libelle deja parenthese : pas de double unite.
    assert names["cost.tariff"] == "Tarif (multiplicateur)"


def test_filtre_par_tags_reduit_les_lignes(service):
    _columns, rows = editor.refresh_table_callback("p1", "Temps", ["t-eu"])

    assert [r["id"] for r in rows] == ["n-a"]

    _columns, rows = editor.refresh_table_callback("p1", "Temps", ["t-eu", "t-asia"])
    assert [r["id"] for r in rows] == ["n-a", "n-b"]


def test_sans_projet_aucune_ligne(service):
    columns, rows = editor.refresh_table_callback(None, "Temps", [])

    assert rows == []
    assert columns[0]["id"] == "Nœud"  # les colonnes du bloc restent construites


def test_bloc_inconnu_retombe_sur_temps(service):
    columns, _rows = editor.refresh_table_callback("p1", None, [])

    assert "time.lead_time_h" in [c["id"] for c in columns]


# tags_options_callback


def test_options_tags_du_projet_et_valeur_reinitialisee(service):
    options, value = editor.tags_options_callback("p1")

    assert {o["value"]: o["label"] for o in options} == {"t-eu": "Europe", "t-asia": "Asie"}
    assert value == []


def test_options_tags_sans_projet_vides(service):
    assert editor.tags_options_callback(None) == ([], [])


# edit_cell_callback : succes


def test_edition_valide_persiste_audite_et_ne_reecrit_pas_la_table(service):
    previous = _rows()
    data = copy.deepcopy(previous)
    data[0]["time.lead_time_h"] = 48.0

    table, msg = editor.edit_cell_callback(1, data, previous, {"name": "alice"}, "p1", "Temps", [])

    assert table is no_update  # anti-scintillement : data non reecrite sur succes
    assert "KPI mis à jour — 1 entrée(s) d'audit" in str(msg)
    node = service.registry.get_node("n-a")
    assert node.kpis.time.lead_time_h == 48.0
    journal = _trail(service, "n-a").history("node_kpis", "n-a", field="time.lead_time_h")
    assert len(journal) == 1
    assert journal[0].source == "edit"
    assert journal[0].operator_id == "alice"
    assert journal[0].old_value == 24.0
    assert journal[0].new_value == 48.0


def test_coercition_chaine_numerique(service):
    previous = _rows()
    data = copy.deepcopy(previous)
    data[0]["time.lead_time_h"] = "123.5"  # la DataTable renvoie parfois des chaines

    table, msg = editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", [])

    assert table is no_update
    assert "KPI mis à jour" in str(msg)
    assert service.registry.get_node("n-a").kpis.time.lead_time_h == 123.5


def test_effacement_remet_le_kpi_a_none(service):
    previous = _rows()
    data = copy.deepcopy(previous)
    data[0]["time.lead_time_h"] = None

    table, msg = editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", [])

    assert table is no_update
    assert "KPI mis à jour" in str(msg)
    assert service.registry.get_node("n-a").kpis.time.lead_time_h is None


def test_lignes_reordonnees_le_diff_par_id_trouve_la_bonne_cellule(service):
    previous = _rows()
    data = copy.deepcopy(previous)[::-1]  # memes row ids, ordre inverse
    target = next(r for r in data if r["id"] == "n-a")
    target["time.lead_time_h"] = 72.0

    table, msg = editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", [])

    assert table is no_update
    assert "KPI mis à jour" in str(msg)
    assert service.registry.get_node("n-a").kpis.time.lead_time_h == 72.0
    # Les autres noeuds n'ont pas bouge (le diff par index aurait ecrit n-c).
    assert service.registry.get_node("n-c").kpis.time.lead_time_h is None


# edit_cell_callback : rejets et no-ops


def test_hors_bornes_table_rechargee_ancienne_valeur_et_aucun_audit(service):
    previous = _rows("Risque")
    data = copy.deepcopy(previous)
    data[0]["risk.failure_probability"] = 1.7  # > maximum 1.0

    table, msg = editor.edit_cell_callback(1, data, previous, None, "p1", "Risque", [])

    assert table is not no_update  # rechargement depuis la base = restauration
    restored = next(r for r in table if r["id"] == "n-a")
    assert restored["risk.failure_probability"] == 0.2  # ancienne valeur
    assert "Modification refusée" in str(msg)
    assert service.registry.get_node("n-a").kpis.risk.failure_probability == 0.2
    journal = _trail(service, "n-a").history("node_kpis", "n-a", field="risk.failure_probability")
    assert journal == []  # AUCUN audit sur rejet


def test_valeur_non_numerique_table_rechargee(service):
    previous = _rows()
    data = copy.deepcopy(previous)
    data[0]["time.lead_time_h"] = "abc"

    table, msg = editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", [])

    assert table is not no_update
    assert next(r for r in table if r["id"] == "n-a")["time.lead_time_h"] == 24.0
    assert "non numérique" in str(msg)
    assert service.registry.get_node("n-a").kpis.time.lead_time_h == 24.0


def test_noeud_inconnu_table_rechargee_et_message(service):
    previous = [{"id": "ghost", "Nœud": "Fantôme", "time.lead_time_h": 1.0}]
    data = [{"id": "ghost", "Nœud": "Fantôme", "time.lead_time_h": 2.0}]

    table, msg = editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", [])

    assert table is not no_update
    assert [r["id"] for r in table] == ["n-a", "n-b", "n-c"]
    assert "Modification refusée" in str(msg)


def test_data_previous_none_no_update(service):
    assert editor.edit_cell_callback(1, [], None, None, "p1", "Temps", []) == (
        no_update,
        no_update,
    )


def test_aucun_ecart_no_update(service):
    previous = _rows()
    data = copy.deepcopy(previous)

    assert editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", []) == (
        no_update,
        no_update,
    )


def test_ligne_inconnue_de_data_previous_ignoree(service):
    previous = _rows()
    data = copy.deepcopy(previous)
    data.append({"id": "ghost", "Nœud": "Fantôme", "time.lead_time_h": 9.0})

    assert editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", []) == (
        no_update,
        no_update,
    )


def test_valeur_identique_a_la_base_aucune_ecriture(service):
    # data differe de data_previous mais vaut DEJA la valeur en base (cas du re-declenchement apres restauration) : update_kpis ne diffe rien.
    previous = _rows()
    previous[0]["time.lead_time_h"] = 99.0  # data_previous desynchronise simule
    data = _rows()  # valeurs de la base

    table, msg = editor.edit_cell_callback(1, data, previous, None, "p1", "Temps", [])

    assert table is no_update
    assert "aucune écriture" in str(msg)
    journal = _trail(service, "n-a").history("node_kpis", "n-a", field="time.lead_time_h")
    assert journal == []


# layout & register_callbacks


def test_layout_contient_filtres_table_et_bandeau(service):
    tree = str(editor.layout().to_plotly_json())

    for component_id in ("edit-project-dd", "edit-block-dd", "edit-tags-dd", "edit-msg"):
        assert component_id in tree
    assert "kpi-edit-table" in tree
    assert "Les modifications sont auditées et réévaluent les scores immédiatement." in tree
    assert "Projet édition" in tree  # options du dropdown projet depuis le registre


def test_register_callbacks_smoke(service):
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div(
        [
            dcc.Store(id="store-project"),
            dcc.Store(id="store-operator"),
            editor.layout(),
        ]
    )
    editor.register_callbacks(app)
    assert len(app.callback_map) == 3
