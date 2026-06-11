"""Tests du service « données brutes » (RawTableService) — Lot 10.5.

Couvre : liste des bases et des tables (FORBIDDEN jamais éditables), lecture
paginée avec ``rowid``, édition auditée d'une cellule, refus typés (table
interdite, borne violée, JSON invalide, fenêtre de jalon) SANS écriture, et
les ValueError de clé/colonne.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.data.audit import AuditTrail
from supplyscore.services import SupplyScoreService
from supplyscore.services.raw_admin import (
    CellResult,
    ForbiddenTableError,
    RawTableService,
    TableInfo,
)

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()


@pytest.fixture
def service(tmp_path):
    """Service seedé avec une petite démo reproductible (horloge figée)."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    svc.seed_demo(n_ranks=2, seed=1)
    yield svc
    svc.close()


@pytest.fixture
def raw(service):
    """Vue brute sur le service seedé."""
    return RawTableService(service)


def _first_node_id(service) -> str:
    """Id du premier nœud du registre (sa base client existe : démo seedée)."""
    return service.registry.list_nodes()[0].id


# --- list_databases ---------------------------------------------------------------------


def test_list_databases_registry_first_then_node_ids(service, raw):
    databases = raw.list_databases()

    assert databases[0] == "registry"
    assert databases[1:] == [node.id for node in service.registry.list_nodes()]
    assert len(databases) > 1


# --- list_tables ------------------------------------------------------------------------


def test_list_tables_registry_editable_whitelist_only(raw):
    infos = {info.name: info for info in raw.list_tables("registry")}

    for name in ("nodes", "arcs", "milestones", "tags", "tag_categories", "projects"):
        assert infos[name].editable, name
    # Hors liste blanche : jamais éditables.
    for name in ("node_urgency", "project_settings", "node_tags", "onboarding_progress"):
        assert not infos[name].editable, name
    # FORBIDDEN : toujours editable=False.
    assert not infos["audit_log"].editable
    assert all(isinstance(info, TableInfo) for info in infos.values())


def test_list_tables_client_forbidden_never_editable(service, raw):
    node_id = _first_node_id(service)
    infos = {info.name: info for info in raw.list_tables(node_id)}

    for name in ("assessments", "spec_sheet", "events"):
        assert infos[name].editable, name
    for name in ("audit_log", "urgency_history", "kpi_snapshots", "weekly_reviews", "decisions"):
        assert not infos[name].editable, name
    # La démo seedée a au moins une évaluation et un historique d'urgence.
    assert infos["assessments"].row_count >= 1
    assert infos["urgency_history"].row_count >= 1


def test_list_tables_row_count_matches_registry(service, raw):
    infos = {info.name: info for info in raw.list_tables("registry")}
    assert infos["nodes"].row_count == len(service.registry.list_nodes())
    assert infos["arcs"].row_count == len(service.registry.list_arcs())


def test_list_tables_unknown_db_raises(raw):
    with pytest.raises(ValueError, match="Base inconnue"):
        raw.list_tables("base-fantome")


# --- fetch ------------------------------------------------------------------------------


def test_fetch_includes_rowid_and_paginates(raw):
    rows, columns = raw.fetch("registry", "nodes", limit=2)

    assert columns[0] == "rowid"
    assert "id" in columns
    assert len(rows) == 2
    assert all("rowid" in row for row in rows)

    # offset=1 retombe sur la deuxième ligne de la première page.
    page2, _ = raw.fetch("registry", "nodes", limit=1, offset=1)
    assert page2[0]["rowid"] == rows[1]["rowid"]


def test_fetch_unknown_table_raises(raw):
    with pytest.raises(ValueError, match="Table inconnue"):
        raw.fetch("registry", "table_fantome")


def test_fetch_unknown_db_raises(raw):
    with pytest.raises(ValueError, match="Base inconnue"):
        raw.fetch("base-fantome", "nodes")


# --- update_cell : succès audité ----------------------------------------------------------


def test_update_cell_nodes_label_writes_and_audits(service, raw):
    rows, _ = raw.fetch("registry", "nodes", limit=1)
    rowid, node_id, old_label = rows[0]["rowid"], rows[0]["id"], rows[0]["label"]
    pk = {"rowid": rowid}

    result = raw.update_cell(
        "registry", "nodes", pk, "label", "Étiquette brute", operator_id="op-admin"
    )

    assert isinstance(result, CellResult) and result.ok
    assert "→" in result.message_fr
    assert service.registry.get_node(node_id).label == "Étiquette brute"

    trail = AuditTrail(service.registry.conn, service.clock, lock=service.registry.lock)
    entries = trail.history("raw:nodes", str(pk))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.field == "label"
    assert entry.old_value == old_label
    assert entry.new_value == "Étiquette brute"
    assert entry.source == "edit"
    assert entry.operator_id == "op-admin"


def test_update_cell_client_events_notes(service, raw):
    node_id = _first_node_id(service)
    client = service.client_db(node_id)
    client.save_event("ev-1", node_id, "panne_machine", "2026-S24", _NOW, "{}", "{}", "op-1")
    rows, _ = raw.fetch(node_id, "events", limit=1)
    pk = {"rowid": rows[0]["rowid"]}

    result = raw.update_cell(node_id, "events", pk, "notes", "note brute", operator_id="op-2")

    assert result.ok
    assert client.list_events(node_id)[0]["notes"] == "note brute"
    trail = AuditTrail(client.conn, service.clock, lock=client.lock)
    assert trail.history("raw:events", str(pk))[0].new_value == "note brute"


def test_update_cell_assessment_ud_bounded(service, raw):
    node_id = _first_node_id(service)
    rows, _ = raw.fetch(node_id, "assessments", limit=1)
    pk = {"rowid": rows[0]["rowid"]}

    refused = raw.update_cell(node_id, "assessments", pk, "ud", 1.5)
    assert not refused.ok

    accepted = raw.update_cell(node_id, "assessments", pk, "ud", "0.5")
    assert accepted.ok
    after, _ = raw.fetch(node_id, "assessments", limit=1)
    assert after[0]["ud"] == 0.5


def test_update_cell_milestone_deadline_window(service, raw):
    rows, _ = raw.fetch("registry", "milestones", limit=1)
    row = rows[0]
    pk = {"rowid": row["rowid"]}

    refused = raw.update_cell("registry", "milestones", pk, "deadline_ts", row["start_ts"] - 10)
    assert not refused.ok
    assert "start_ts" in refused.message_fr

    accepted = raw.update_cell("registry", "milestones", pk, "deadline_ts", row["start_ts"] + 3600)
    assert accepted.ok

    # start_ts doit rester strictement antérieure à deadline_ts.
    refused2 = raw.update_cell("registry", "milestones", pk, "start_ts", row["start_ts"] + 7200)
    assert not refused2.ok

    # ... et une avancée valide de start_ts est acceptée.
    accepted2 = raw.update_cell("registry", "milestones", pk, "start_ts", row["start_ts"] - 3600)
    assert accepted2.ok


def test_update_cell_milestone_window_non_numeric_refused(raw):
    rows, _ = raw.fetch("registry", "milestones", limit=1)
    pk = {"rowid": rows[0]["rowid"]}

    assert not raw.update_cell("registry", "milestones", pk, "deadline_ts", "abc").ok
    assert not raw.update_cell("registry", "milestones", pk, "start_ts", "abc").ok


# --- update_cell : refus sans écriture -----------------------------------------------------


def test_update_cell_forbidden_table_raises(service, raw):
    with pytest.raises(ForbiddenTableError, match="append-only"):
        raw.update_cell("registry", "audit_log", {"rowid": 1}, "field", "x")

    node_id = _first_node_id(service)
    with pytest.raises(ForbiddenTableError):
        raw.update_cell(node_id, "urgency_history", {"rowid": 1}, "ud", 0.5)


def test_update_cell_table_outside_whitelist_raises(service, raw):
    with pytest.raises(ForbiddenTableError, match="liste blanche"):
        raw.update_cell("registry", "node_urgency", {"rowid": 1}, "ud", 0.5)
    # Une table whitelistée côté client n'est pas éditable côté registre.
    with pytest.raises(ForbiddenTableError):
        raw.update_cell("registry", "assessments", {"rowid": 1}, "notes", "x")


def test_update_cell_gamma_out_of_bounds_refused_without_write(service, raw):
    rows, _ = raw.fetch("registry", "arcs", limit=1)
    row = rows[0]
    pk = {"rowid": row["rowid"]}

    result = raw.update_cell("registry", "arcs", pk, "gamma", "1.7")

    assert not result.ok
    assert "hors [0, 1]" in result.message_fr
    after, _ = raw.fetch("registry", "arcs", limit=1)
    assert after[0]["gamma"] == row["gamma"]
    # Aucune ligne d'audit n'a été écrite.
    trail = AuditTrail(service.registry.conn, service.clock, lock=service.registry.lock)
    assert trail.history("raw:arcs", str(pk)) == []


def test_update_cell_non_numeric_for_bounded_column_refused(raw):
    rows, _ = raw.fetch("registry", "arcs", limit=1)
    result = raw.update_cell("registry", "arcs", {"rowid": rows[0]["rowid"]}, "beta", "abc")

    assert not result.ok
    assert "non numérique" in result.message_fr


def test_update_cell_non_finite_for_bounded_column_refused(raw):
    rows, _ = raw.fetch("registry", "arcs", limit=1)
    result = raw.update_cell("registry", "arcs", {"rowid": rows[0]["rowid"]}, "gamma", "nan")

    assert not result.ok
    assert "non finie" in result.message_fr


def test_update_cell_invalid_json_refused_without_write(service, raw):
    rows, _ = raw.fetch("registry", "nodes", limit=1)
    row = rows[0]
    pk = {"rowid": row["rowid"]}

    result = raw.update_cell("registry", "nodes", pk, "kpis_json", "{pas du json")

    assert not result.ok
    assert "JSON invalide" in result.message_fr
    after, _ = raw.fetch("registry", "nodes", limit=1)
    assert after[0]["kpis_json"] == row["kpis_json"]


def test_update_cell_json_column_requires_string(raw):
    rows, _ = raw.fetch("registry", "nodes", limit=1)
    result = raw.update_cell(
        "registry", "nodes", {"rowid": rows[0]["rowid"]}, "kpis_json", {"network": {}}
    )

    assert not result.ok
    assert "chaîne" in result.message_fr


def test_update_cell_valid_json_accepted(raw):
    rows, _ = raw.fetch("registry", "nodes", limit=1)
    result = raw.update_cell("registry", "nodes", {"rowid": rows[0]["rowid"]}, "kpis_json", "{}")

    assert result.ok
    after, _ = raw.fetch("registry", "nodes", limit=1)
    assert after[0]["kpis_json"] == "{}"


# --- update_cell : ValueError de clé/colonne ------------------------------------------------


def test_update_cell_unknown_pk_column_raises(raw):
    with pytest.raises(ValueError, match="Clé primaire inconnue"):
        raw.update_cell("registry", "nodes", {"plouf": 1}, "label", "x")


def test_update_cell_empty_pk_raises(raw):
    with pytest.raises(ValueError, match="Clé de ligne vide"):
        raw.update_cell("registry", "nodes", {}, "label", "x")


def test_update_cell_row_not_found_raises(raw):
    with pytest.raises(ValueError, match="introuvable"):
        raw.update_cell("registry", "nodes", {"rowid": 10**9}, "label", "x")


def test_update_cell_unknown_column_raises(raw):
    rows, _ = raw.fetch("registry", "nodes", limit=1)
    with pytest.raises(ValueError, match="Colonne inconnue"):
        raw.update_cell("registry", "nodes", {"rowid": rows[0]["rowid"]}, "fantome", "x")


def test_update_cell_pk_column_not_editable(raw):
    rows, _ = raw.fetch("registry", "nodes", limit=1)
    with pytest.raises(ValueError, match="clé primaire"):
        raw.update_cell("registry", "nodes", {"rowid": rows[0]["rowid"]}, "id", "nouveau-id")


def test_update_cell_unknown_db_raises(raw):
    with pytest.raises(ValueError, match="Base inconnue"):
        raw.update_cell("base-fantome", "nodes", {"rowid": 1}, "label", "x")
