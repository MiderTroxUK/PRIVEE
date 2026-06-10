"""Tests du domaine v2 : migrations registre v3 / client v2 et CRUD associés (Lot 2.4).

Couvre : migration d'une base v2 existante vers v3 (backfill t0_ts, idempotence,
intégrité référentielle), round-trips des nouveaux champs (t0_ts, tags,
onboarding_state, kind_arc), CRUD jalons/tags/onboarding/spec_sheet/events et
cascades explicites de delete_node.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from supplyscore.data.db import ClientDatabase, RegistryDatabase
from supplyscore.data.migrations import (
    _client_v1,
    _registry_v1,
    _registry_v2,
    apply_migrations,
)
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import ArcKind, Project, SupplyArc, SupplyNode
from supplyscore.domain.tags import Tag, TagCategory

# --- Helpers --------------------------------------------------------------------


def _build_v2_registry(path: Path) -> None:
    """Construit une base registre v2 réelle (telle que créée par le code actuel)."""
    conn = sqlite3.connect(str(path))
    _registry_v1(conn)
    _registry_v2(conn)
    conn.execute(
        "INSERT INTO projects (id, name, owner_node_id, description, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("p1", "Projet", "n1", "desc", 1000.0),
    )
    conn.executemany(
        "INSERT INTO nodes (id, name, label, kind, rank, project_id, location, "
        "latitude, longitude, status, kpis_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("n1", "Client", "Client", "node", 0, "p1", "Lyon", 45.7, 4.8, "active", "{}"),
            ("n2", "Usine", "Factory", "node", 1, "p1", None, None, None, "active", "{}"),
        ],
    )
    conn.execute(
        "INSERT INTO arcs (source_id, target_id, label, gamma, beta, delta, kpis_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("n2", "n1", "Truck", 0.4, 0.6, 1.0, "{}"),
    )
    conn.commit()
    conn.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row[0] for row in rows}


def _milestone(mid: str, node_id: str = "n1", position: int = 0, **kwargs: Any) -> Milestone:
    """Jalon valide par défaut (deadline > start, progress dans [0, 1])."""
    defaults: dict[str, Any] = {"start_ts": 1000.0, "deadline_ts": 2000.0}
    defaults.update(kwargs)
    return Milestone(id=mid, node_id=node_id, name=mid, position=position, **defaults)


# --- Migration registre v2 -> v3 ---------------------------------------------------


class TestRegistryV3Migration:
    def test_v2_to_v3_preserves_data_and_backfills_t0(self, tmp_path):
        db_file = tmp_path / "registry.sqlite"
        _build_v2_registry(db_file)

        conn = sqlite3.connect(str(db_file))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert apply_migrations(conn, "registry") == 3

        # Données préservées.
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM arcs").fetchone()[0] == 1

        # Backfill : t0_ts == created_at.
        row = conn.execute("SELECT created_at, t0_ts FROM projects WHERE id = 'p1'").fetchone()
        assert row == (1000.0, 1000.0)

        # Défauts des colonnes ajoutées.
        states = {r[0] for r in conn.execute("SELECT onboarding_state FROM nodes").fetchall()}
        assert states == {"complete"}
        assert conn.execute("SELECT arc_kind FROM arcs").fetchone()[0] == "nominal"

        # Nouvelles tables et index.
        assert {
            "milestones",
            "tag_categories",
            "tags",
            "node_tags",
            "onboarding_progress",
        } <= _table_names(conn)
        assert {"idx_milestones_node", "idx_node_tags_tag"} <= _index_names(conn)

        # Intégrité référentielle intacte.
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()

    def test_v3_is_idempotent(self, tmp_path):
        db_file = tmp_path / "registry.sqlite"
        _build_v2_registry(db_file)
        conn = sqlite3.connect(str(db_file))

        assert apply_migrations(conn, "registry") == 3
        # Re-application : no-op, données intactes.
        assert apply_migrations(conn, "registry") == 3
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 2
        assert conn.execute("SELECT t0_ts FROM projects WHERE id = 'p1'").fetchone()[0] == 1000.0
        conn.close()

    def test_fresh_registry_reaches_v3(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "registry.sqlite"))
        assert apply_migrations(conn, "registry") == 3
        assert {"milestones", "tags", "tag_categories", "node_tags"} <= _table_names(conn)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()

    def test_foreign_key_check_empty_with_v3_data(self, tmp_path):
        """Une base v3 peuplée via les CRUD reste référentiellement saine."""
        with RegistryDatabase(tmp_path) as db:
            db.save_project(Project(id="p1", name="P", owner_node_id="n1", created_at=10.0))
            db.save_tag(Tag(id="t1", project_id="p1", name="acier"))
            db.save_node(SupplyNode(id="n1", name="N", project_id="p1", tags=["t1"]))
            db.save_milestone(_milestone("m1", node_id="n1"))
            db.save_onboarding("n1", {"identity": True}, {"name": "N"}, 2)

        conn = sqlite3.connect(str(tmp_path / "registry.sqlite"))
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()


# --- Migration client v1 -> v2 ------------------------------------------------------


class TestClientV2Migration:
    def test_fresh_client_reaches_v2(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "client.sqlite"))
        assert apply_migrations(conn, "client") == 2
        assert {"spec_sheet", "events"} <= _table_names(conn)
        assert "idx_events_node_week" in _index_names(conn)
        conn.close()

    def test_v1_to_v2_preserves_data_and_is_idempotent(self, tmp_path):
        db_file = tmp_path / "client.sqlite"
        conn = sqlite3.connect(str(db_file))
        _client_v1(conn)
        conn.execute(
            "INSERT INTO kpi_snapshots (node_id, kpis_json, timestamp) VALUES (?, ?, ?)",
            ("n1", "{}", 42.0),
        )
        conn.commit()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

        assert apply_migrations(conn, "client") == 2
        assert apply_migrations(conn, "client") == 2  # idempotent
        assert conn.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()[0] == 1
        assert {"spec_sheet", "events"} <= _table_names(conn)
        conn.close()


# --- Round-trips des nouveaux champs --------------------------------------------------


class TestNewFieldsRoundTrip:
    def test_project_t0_ts_round_trip(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            explicit = Project(id="p1", name="A", owner_node_id="n1", created_at=100.0, t0_ts=50.0)
            implicit = Project(id="p2", name="B", owner_node_id="n2", created_at=200.0)
            db.save_project(explicit)
            db.save_project(implicit)

            got = db.get_project("p1")
            assert got is not None
            assert got == explicit
            assert got.t0_ts == 50.0
            assert got.origin_ts == 50.0

            got2 = db.get_project("p2")
            assert got2 is not None
            assert got2.t0_ts is None
            assert got2.origin_ts == 200.0  # repli sur created_at
            assert db.list_projects() == [explicit, got2]

    def test_node_tags_and_onboarding_state_round_trip(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_tag_category(
                TagCategory(id="c1", project_id="p1", name="Procédé", color="#f00")
            )
            db.save_tag(Tag(id="t1", project_id="p1", name="forge", category_id="c1"))
            db.save_tag(Tag(id="t2", project_id="p1", name="usinage"))

            node = SupplyNode(
                id="n1",
                name="Atelier",
                project_id="p1",
                tags=["t1", "t2"],
                onboarding_state="draft",
            )
            db.save_node(node)

            got = db.get_node("n1")
            assert got is not None
            assert got.tags == ["t1", "t2"]
            assert got.onboarding_state == "draft"

            # tags_of_node retourne les objets Tag, dans l'ordre d'association.
            tags = db.tags_of_node("n1")
            assert [t.id for t in tags] == ["t1", "t2"]
            assert tags[0].category_id == "c1"
            assert tags[1].category_id is None

            # Catalogues par projet.
            assert [c.name for c in db.list_tag_categories("p1")] == ["Procédé"]
            assert db.list_tag_categories("p1")[0].color == "#f00"
            assert [t.name for t in db.list_tags("p1")] == ["forge", "usinage"]
            assert db.list_tags("autre") == []

            # Re-save : les liens sont resynchronisés (pas accumulés).
            node.tags = ["t2"]
            db.save_node(node)
            resaved = db.get_node("n1")
            assert resaved is not None and resaved.tags == ["t2"]

            # set_node_tags remplace explicitement.
            db.set_node_tags("n1", ["t1"])
            assert [t.id for t in db.tags_of_node("n1")] == ["t1"]

    def test_arc_kind_round_trip(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            backup = SupplyArc(source_id="s", target_id="t", kind_arc=ArcKind.BACKUP)
            nominal = SupplyArc(source_id="s", target_id="u")
            db.save_arc(backup)
            db.save_arc(nominal)

            got_backup = db.get_arc("s", "t")
            got_nominal = db.get_arc("s", "u")
            assert got_backup == backup
            assert got_backup is not None and got_backup.kind_arc is ArcKind.BACKUP
            assert got_nominal is not None and got_nominal.kind_arc is ArcKind.NOMINAL
            assert db.list_arcs() == [backup, nominal]


# --- Jalons ---------------------------------------------------------------------------


class TestMilestones:
    def test_round_trip_and_sorted_by_position(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            serie = _milestone("m-serie", position=1, kind="serie", progress=0.5)
            proto = _milestone("m-proto", position=0, kind="proto", deadline_ts=1500.0)
            livraison = _milestone(
                "m-livr",
                position=2,
                start_ts=2000.0,
                deadline_ts=3000.0,
                status=MilestoneStatus.DONE,
                progress=1.0,
            )
            # Insertion volontairement dans le désordre.
            for m in (serie, livraison, proto):
                db.save_milestone(m)

            assert db.get_milestone("m-serie") == serie
            assert db.get_milestone("absent") is None
            listed = db.list_milestones("n1")
            assert listed == [proto, serie, livraison]
            assert [m.position for m in listed] == [0, 1, 2]
            assert listed[2].status is MilestoneStatus.DONE
            assert db.list_milestones("autre") == []

    def test_upsert_updates_and_preserves_created_at(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_milestone(_milestone("m1", progress=0.2))
            created = db._conn.execute(
                "SELECT created_at FROM milestones WHERE id = 'm1'"
            ).fetchone()[0]

            db.save_milestone(_milestone("m1", progress=0.7))
            row = db._conn.execute(
                "SELECT created_at, updated_at, progress FROM milestones WHERE id = 'm1'"
            ).fetchone()
            assert row[0] == created  # created_at préservé
            assert row[1] >= created  # updated_at rafraîchi
            assert row[2] == pytest.approx(0.7)
            assert len(db.list_milestones("n1")) == 1

    def test_delete_milestone(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            db.save_milestone(_milestone("m1"))
            db.delete_milestone("m1")
            assert db.get_milestone("m1") is None
            db.delete_milestone("m1")  # silencieux si absent

    def test_progress_out_of_bounds_rejected(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            with pytest.raises(sqlite3.IntegrityError):
                db.save_milestone(_milestone("bad", progress=1.5))
            with pytest.raises(sqlite3.IntegrityError):
                db.save_milestone(_milestone("bad", progress=-0.1))
            assert db.list_milestones("n1") == []

    def test_deadline_not_after_start_rejected(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            with pytest.raises(sqlite3.IntegrityError):
                db.save_milestone(_milestone("bad", start_ts=2000.0, deadline_ts=1000.0))
            with pytest.raises(sqlite3.IntegrityError):
                db.save_milestone(_milestone("bad", start_ts=1000.0, deadline_ts=1000.0))
            assert db.list_milestones("n1") == []


# --- Onboarding -----------------------------------------------------------------------


class TestOnboarding:
    def test_round_trip_update_and_delete(self, tmp_path):
        with RegistryDatabase(tmp_path) as db:
            assert db.get_onboarding("n1") is None

            db.save_onboarding("n1", {"identity": True, "kpis": False}, {"name": "Forge"}, 2)
            got = db.get_onboarding("n1")
            assert got is not None
            assert got["sections_done"] == {"identity": True, "kpis": False}
            assert got["draft"] == {"name": "Forge"}
            assert got["current_step"] == 2
            assert got["updated_at"] > 0

            # Upsert : remplace la progression existante.
            db.save_onboarding("n1", {"identity": True, "kpis": True}, {}, 3)
            got = db.get_onboarding("n1")
            assert got is not None
            assert got["sections_done"] == {"identity": True, "kpis": True}
            assert got["draft"] == {}
            assert got["current_step"] == 3

            db.delete_onboarding("n1")
            assert db.get_onboarding("n1") is None
            db.delete_onboarding("n1")  # silencieux si absent


# --- Cascades de delete_node ------------------------------------------------------------


def test_delete_node_cascades_tags_milestones_and_onboarding(tmp_path):
    with RegistryDatabase(tmp_path) as db:
        db.save_tag(Tag(id="t1", project_id="p1", name="acier"))
        db.save_node(SupplyNode(id="n1", name="A", tags=["t1"]))
        db.save_node(SupplyNode(id="n2", name="B", tags=["t1"]))
        db.save_milestone(_milestone("m1", node_id="n1"))
        db.save_milestone(_milestone("m2", node_id="n2"))
        db.save_onboarding("n1", {}, {}, 1)

        db.delete_node("n1")

        assert db.get_node("n1") is None
        assert db.tags_of_node("n1") == []
        assert db.list_milestones("n1") == []
        assert db.get_onboarding("n1") is None
        # Le nœud voisin et le catalogue de tags sont intacts.
        neighbour = db.get_node("n2")
        assert neighbour is not None and neighbour.tags == ["t1"]
        assert [m.id for m in db.list_milestones("n2")] == ["m2"]
        assert [t.id for t in db.list_tags("p1")] == ["t1"]
        # Aucune ligne orpheline en base.
        assert (
            db._conn.execute("SELECT COUNT(*) FROM node_tags WHERE node_id = 'n1'").fetchone()[0]
            == 0
        )
        assert db._conn.execute("PRAGMA foreign_key_check").fetchall() == []


# --- ClientDatabase : spec_sheet -----------------------------------------------------------


class TestSpecSheet:
    def test_versions_increment_and_latest(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            assert db.latest_spec_sheet("n1") is None
            assert db.spec_sheet_versions("n1") == []

            assert db.save_spec_sheet("n1", '{"qty": 1}', "wizard") == 1
            assert db.save_spec_sheet("n1", '{"qty": 2}', "manual") == 2
            assert db.save_spec_sheet("n1", '{"qty": 3}', "manual") == 3

            assert db.spec_sheet_versions("n1") == [1, 2, 3]
            assert db.latest_spec_sheet("n1") == (3, '{"qty": 3}')

    def test_versions_are_per_node(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_spec_sheet("n1", "{}", "wizard")
            db.save_spec_sheet("n1", "{}", "wizard")
            assert db.save_spec_sheet("n2", '{"a": 1}', "wizard") == 1
            assert db.spec_sheet_versions("n2") == [1]
            assert db.latest_spec_sheet("n2") == (1, '{"a": 1}')


# --- ClientDatabase : events ---------------------------------------------------------------


class TestEvents:
    def test_save_list_filter_and_revert(self, tmp_path):
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_event(
                "e2",
                "n1",
                "panne_majeure",
                "2026-W24",
                2000.0,
                '{"k": 2, "n": 2}',
                '{"failure_probability": 0.09}',
                "op-7",
                notes="ligne 3 à l'arrêt",
            )
            db.save_event(
                "e1",
                "n1",
                "hausse_tarif",
                "2026-W23",
                1000.0,
                '{"pct": 12}',
                '{"tariff": 1.176}',
                "op-7",
            )
            db.save_event(
                "e3",
                "n2",
                "panne_mineure",
                "2026-W23",
                1500.0,
                "{}",
                "{}",
                "op-8",
            )

            # Liste complète du nœud, ordonnée par occurred_at.
            events = db.list_events("n1")
            assert [e["id"] for e in events] == ["e1", "e2"]
            first = events[0]
            assert first["event_type"] == "hausse_tarif"
            assert first["iso_week"] == "2026-W23"
            assert first["params_json"] == '{"pct": 12}'
            assert first["impacts_json"] == '{"tariff": 1.176}'
            assert first["operator_id"] == "op-7"
            assert first["notes"] == ""
            assert first["reverted_at"] is None
            assert events[1]["notes"] == "ligne 3 à l'arrêt"

            # Filtre par semaine ISO (isolation par nœud comprise).
            assert [e["id"] for e in db.list_events("n1", iso_week="2026-W23")] == ["e1"]
            assert [e["id"] for e in db.list_events("n1", iso_week="2026-W24")] == ["e2"]
            assert db.list_events("n1", iso_week="2026-W25") == []
            assert [e["id"] for e in db.list_events("n2")] == ["e3"]

            # Annulation : reverted_at posé, l'événement reste journalisé.
            db.mark_reverted("e2", 2500.0)
            events = db.list_events("n1")
            assert events[1]["reverted_at"] == 2500.0
            assert events[0]["reverted_at"] is None


# --- Persistance après réouverture -----------------------------------------------------------


def test_v3_fields_persist_across_reopen(tmp_path):
    with RegistryDatabase(tmp_path) as db:
        db.save_project(Project(id="p1", name="P", owner_node_id="n1", created_at=10.0, t0_ts=5.0))
        db.save_tag(Tag(id="t1", project_id="p1", name="acier"))
        db.save_node(SupplyNode(id="n1", name="N", tags=["t1"], onboarding_state="draft"))
        db.save_arc(SupplyArc(source_id="n2", target_id="n1", kind_arc=ArcKind.BACKUP))
        db.save_milestone(_milestone("m1", node_id="n1"))

    with RegistryDatabase(tmp_path) as db:
        assert db.schema_version == 3
        project = db.get_project("p1")
        assert project is not None and project.t0_ts == 5.0
        node = db.get_node("n1")
        assert node is not None
        assert node.tags == ["t1"] and node.onboarding_state == "draft"
        arc = db.get_arc("n2", "n1")
        assert arc is not None and arc.kind_arc is ArcKind.BACKUP
        assert [m.id for m in db.list_milestones("n1")] == ["m1"]
