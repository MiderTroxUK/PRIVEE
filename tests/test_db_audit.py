"""Tests du Lot 3.2 : migrations d'audit (registre v4, client v3) et lectures temporelles.

Couvre : migration d'une base client v2 existante vers v3 (table ``audit_log``
et ses index, index ``idx_kpi_snap_node_ts``, colonne ``replaces_id``, données
préservées, idempotence), migration du registre v3 vers v4, lecture temporelle
``kpis_at``, exclusion des évaluations remplacées (``replaces_id``) et
exposition publique ``conn``/``lock`` pour un AuditTrail externe.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import threading
from pathlib import Path

import pytest

from supplyscore.data.db import ClientDatabase, RegistryDatabase
from supplyscore.data.migrations import (
    _client_v1,
    _client_v2,
    _registry_v1,
    _registry_v2,
    _registry_v3,
    apply_migrations,
)
from supplyscore.domain.models import AHPAssessment, KPIBundle

# --- Helpers --------------------------------------------------------------------

_AUDIT_COLUMNS = {
    "id",
    "entity_type",
    "entity_id",
    "field",
    "old_value",
    "new_value",
    "source",
    "operator_id",
    "iso_week",
    "timestamp",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row[0] for row in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    assert table in {"audit_log", "assessments"}  # tables connues uniquement (pas d'injection)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _build_v2_client(path: Path) -> None:
    """Construit une base client v2 réelle (telle que créée par le code actuel)."""
    conn = sqlite3.connect(str(path))
    _client_v1(conn)
    _client_v2(conn)
    conn.execute(
        """
        INSERT INTO assessments (node_id, project_id, operator_id, comparisons_json,
                                 criteria_scores_json, weights_json, consistency_ratio,
                                 is_consistent, ud, notes, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("n1", "p1", "op-7", '{"0-1": 3.0}', "[4.0, 6.5]", "[0.6, 0.4]", 0.03, 1, 0.4, "", 100.0),
    )
    conn.execute(
        "INSERT INTO kpi_snapshots (node_id, kpis_json, timestamp) VALUES (?, ?, ?)",
        ("n1", "{}", 42.0),
    )
    conn.commit()
    conn.close()


def _build_v3_registry(path: Path) -> None:
    """Construit une base registre v3 réelle (telle que créée par le code actuel)."""
    conn = sqlite3.connect(str(path))
    _registry_v1(conn)
    _registry_v2(conn)
    _registry_v3(conn)
    conn.execute(
        "INSERT INTO projects (id, name, owner_node_id, description, created_at, t0_ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("p1", "Projet", "n1", "desc", 1000.0, 900.0),
    )
    conn.execute(
        "INSERT INTO nodes (id, name, label, kind, rank, project_id, location, latitude, "
        "longitude, status, kpis_json, onboarding_state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("n1", "Client", "Client", "node", 0, "p1", "Lyon", 45.7, 4.8, "active", "{}", "complete"),
    )
    conn.commit()
    conn.close()


def _assessment(node_id: str = "n1", ts: float = 1000.0, ud: float = 0.4) -> AHPAssessment:
    return AHPAssessment(
        node_id=node_id,
        project_id="p1",
        operator_id="op-7",
        comparisons={(0, 1): 3.0, (0, 2): 5.0, (1, 2): 2.0},
        criteria_scores=[4.0, 6.5, 2.0],
        weights=[0.6, 0.25, 0.15],
        consistency_ratio=0.03,
        is_consistent=True,
        ud=ud,
        notes="hebdo",
        timestamp=ts,
    )


def _bundle(lead_time_h: float, demand: float) -> KPIBundle:
    """KPIBundle discriminable champ à champ (time.lead_time_h, network.demand)."""
    kpis = KPIBundle()
    kpis.time.lead_time_h = lead_time_h
    kpis.network.demand = demand
    return kpis


# --- Migration client v2 -> v3 ------------------------------------------------------


class TestClientV3Migration:
    def test_v2_to_v3_adds_audit_index_and_replaces_id(self, tmp_path):
        db_file = tmp_path / "client.sqlite"
        _build_v2_client(db_file)

        conn = sqlite3.connect(str(db_file))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert apply_migrations(conn, "client") == 6

        # Table d'audit et index présents.
        assert "audit_log" in _table_names(conn)
        assert _column_names(conn, "audit_log") == _AUDIT_COLUMNS
        assert {"idx_audit_entity", "idx_audit_week", "idx_kpi_snap_node_ts"} <= _index_names(conn)

        # Colonne replaces_id ajoutée, NULL pour les lignes existantes.
        assert "replaces_id" in _column_names(conn, "assessments")
        assert conn.execute("SELECT replaces_id FROM assessments").fetchone()[0] is None

        # Données préservées.
        row = conn.execute("SELECT node_id, operator_id, ud, timestamp FROM assessments").fetchone()
        assert row == ("n1", "op-7", 0.4, 100.0)
        assert conn.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT timestamp FROM kpi_snapshots").fetchone()[0] == 42.0
        conn.close()

    def test_v3_is_idempotent(self, tmp_path):
        db_file = tmp_path / "client.sqlite"
        _build_v2_client(db_file)
        conn = sqlite3.connect(str(db_file))

        assert apply_migrations(conn, "client") == 6
        # Re-application : no-op, données intactes.
        assert apply_migrations(conn, "client") == 6
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()[0] == 1
        conn.close()

    def test_fresh_client_reaches_v3(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "client.sqlite"))
        assert apply_migrations(conn, "client") == 6
        assert "audit_log" in _table_names(conn)
        assert "replaces_id" in _column_names(conn, "assessments")
        conn.close()


# --- Migration registre v3 -> v4 ------------------------------------------------------


class TestRegistryV4Migration:
    def test_v3_to_v4_adds_audit_log(self, tmp_path):
        db_file = tmp_path / "registry.sqlite"
        _build_v3_registry(db_file)

        conn = sqlite3.connect(str(db_file))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert apply_migrations(conn, "registry") == 5

        # Table d'audit et index présents.
        assert "audit_log" in _table_names(conn)
        assert _column_names(conn, "audit_log") == _AUDIT_COLUMNS
        assert {"idx_audit_entity", "idx_audit_week"} <= _index_names(conn)

        # Données préservées.
        row = conn.execute("SELECT name, created_at, t0_ts FROM projects").fetchone()
        assert row == ("Projet", 1000.0, 900.0)
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()

    def test_v4_is_idempotent(self, tmp_path):
        db_file = tmp_path / "registry.sqlite"
        _build_v3_registry(db_file)
        conn = sqlite3.connect(str(db_file))

        assert apply_migrations(conn, "registry") == 5
        # Re-application : no-op, données intactes.
        assert apply_migrations(conn, "registry") == 5
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        conn.close()

    def test_fresh_registry_reaches_v4(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "registry.sqlite"))
        assert apply_migrations(conn, "registry") == 5
        assert "audit_log" in _table_names(conn)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()


# --- Lecture temporelle : kpis_at -------------------------------------------------------


class TestKpisAt:
    def test_returns_last_snapshot_before_t(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_kpi_snapshot("n1", _bundle(10.0, 100.0), timestamp=100.0)
            expected = _bundle(20.0, 200.0)
            db.save_kpi_snapshot("n1", expected, timestamp=200.0)
            db.save_kpi_snapshot("n1", _bundle(30.0, 300.0), timestamp=300.0)

            got = db.kpis_at("n1", 250.0)
            assert got is not None
            # Comparaison champ à champ : le snapshot t=200 exactement.
            assert dataclasses.asdict(got) == dataclasses.asdict(expected)
            assert got.time.lead_time_h == pytest.approx(20.0)
            assert got.network.demand == pytest.approx(200.0)

    def test_none_before_first_snapshot(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_kpi_snapshot("n1", _bundle(10.0, 100.0), timestamp=100.0)
            assert db.kpis_at("n1", 50.0) is None

    def test_boundary_is_inclusive(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_kpi_snapshot("n1", _bundle(10.0, 100.0), timestamp=100.0)
            db.save_kpi_snapshot("n1", _bundle(20.0, 200.0), timestamp=200.0)
            got = db.kpis_at("n1", 200.0)
            assert got is not None and got.time.lead_time_h == pytest.approx(20.0)

    def test_isolated_per_node(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_kpi_snapshot("n1", _bundle(10.0, 100.0), timestamp=100.0)
            assert db.kpis_at("autre", 250.0) is None


# --- Corrections d'évaluations : replaces_id ----------------------------------------------


class TestReplacesId:
    def test_correction_supersedes_original(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            id_a = db.save_assessment(_assessment(ts=100.0, ud=0.1))
            id_b = db.save_assessment(_assessment(ts=150.0, ud=0.2), replaces_id=id_a)

            # replaces_id persisté en base.
            row = db.conn.execute(
                "SELECT replaces_id FROM assessments WHERE id = ?", (id_b,)
            ).fetchone()
            assert row[0] == id_a

            # latest_assessment retourne la correction B.
            latest = db.latest_assessment("n1")
            assert latest is not None and latest.ud == pytest.approx(0.2)

            # Historique complet (défaut) : A ET B ; effectif : B seulement.
            full = db.list_assessments("n1", include_replaced=True)
            assert [a.ud for a in full] == [pytest.approx(0.1), pytest.approx(0.2)]
            assert db.list_assessments("n1") == full  # défaut = historique complet
            effective = db.list_assessments("n1", include_replaced=False)
            assert [a.ud for a in effective] == [pytest.approx(0.2)]

    def test_replaced_excluded_even_if_newer(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            id_a = db.save_assessment(_assessment(ts=200.0, ud=0.1))
            db.save_assessment(_assessment(ts=150.0, ud=0.2), replaces_id=id_a)

            # A est plus récente mais remplacée : la correction B l'emporte.
            latest = db.latest_assessment("n1")
            assert latest is not None and latest.ud == pytest.approx(0.2)

    def test_default_save_remains_original(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            rowid = db.save_assessment(_assessment(ts=100.0, ud=0.3))
            row = db.conn.execute(
                "SELECT replaces_id FROM assessments WHERE id = ?", (rowid,)
            ).fetchone()
            assert row[0] is None
            latest = db.latest_assessment("n1")
            assert latest is not None and latest.ud == pytest.approx(0.3)


# --- Accès partagés conn / lock --------------------------------------------------------


class TestSharedConnAndLock:
    def test_conn_and_lock_exposed(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            assert isinstance(db.conn, sqlite3.Connection)
            assert db.conn is db._conn
            assert db.lock is db._lock
            assert isinstance(db.lock, type(threading.RLock()))
        with RegistryDatabase(tmp_path) as registry:
            assert isinstance(registry.conn, sqlite3.Connection)
            assert registry.lock is registry._lock

    def test_lock_is_reentrant_and_usable(self, tmp_path):
        # db.lock pris DEUX fois : RLock réentrant, double acquisition OK.
        with ClientDatabase(tmp_path, "client-1") as db, db.lock, db.lock:
            assert db.conn.execute("SELECT 1").fetchone()[0] == 1

    def test_external_audit_writer_shares_connection(self, tmp_path):
        """Un AuditTrail externe peut écrire dans audit_log via conn + lock."""
        with ClientDatabase(tmp_path, "client-1") as db:
            with db.lock, db.conn:
                db.conn.execute(
                    """
                    INSERT INTO audit_log (entity_type, entity_id, field, old_value,
                                           new_value, source, operator_id, iso_week,
                                           timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("node", "n1", "status", "active", "done", "ui", "op-7", "2026-W24", 1000.0),
                )
            row = db.conn.execute(
                "SELECT entity_type, entity_id, field, new_value, operator_id FROM audit_log"
            ).fetchone()
            assert tuple(row) == ("node", "n1", "status", "done", "op-7")
