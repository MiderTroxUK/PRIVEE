"""Tests de la couche d'audit generique append-only (supplyscore.data.audit).

La table ``audit_log`` sera creee par les migrations (autre lot) : ici les
tests la creent eux-memes en SQL brut, avec EXACTEMENT le schema cible.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.data.audit import AuditEntry, AuditTrail

# Schema cible de la table (verbatim PLAN.md E3 Lot 3.1).
AUDIT_SCHEMA = """
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, field TEXT NOT NULL,
  old_value TEXT, new_value TEXT,
  source TEXT NOT NULL, operator_id TEXT NOT NULL DEFAULT '',
  iso_week TEXT NOT NULL, timestamp REAL NOT NULL);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id, field, timestamp);
"""


def _count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(AUDIT_SCHEMA)
    yield connection
    connection.close()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(100.0)


@pytest.fixture
def trail(conn: sqlite3.Connection, clock: FixedClock) -> AuditTrail:
    return AuditTrail(conn, clock)


# record + history : entree complete, valeurs retypees


class TestRecordAndHistory:
    def test_record_returns_id_and_history_returns_full_entry(self, trail: AuditTrail):
        row_id = trail.record(
            "node",
            "n1",
            "risk.failure_probability",
            0.1,
            0.2,
            "edit",
            operator_id="op-7",
        )
        assert row_id == 1

        entries = trail.history("node", "n1")
        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, AuditEntry)
        assert entry.id == 1
        assert entry.entity_type == "node"
        assert entry.entity_id == "n1"
        assert entry.field == "risk.failure_probability"
        assert entry.old_value == 0.1
        assert entry.new_value == 0.2
        assert entry.source == "edit"
        assert entry.operator_id == "op-7"
        assert entry.timestamp == 100.0
        assert entry.iso_week == "1970-S01"  # epoch 100 s = 1er janvier 1970

    def test_operator_id_default_empty(self, trail: AuditTrail):
        trail.record("node", "n1", "f", None, 1, "system")
        assert trail.history("node", "n1")[0].operator_id == ""

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            (1, 2),
            (0.25, 0.5),
            ("avant", "après"),
            (None, None),
            ({"x": 1}, {"x": 2, "y": [1, 2.5, "z"]}),
            (True, False),
            ([1, 2], [3]),
        ],
    )
    def test_values_round_trip_typed(self, trail: AuditTrail, old: Any, new: Any):
        trail.record("node", "n1", "champ", old, new, "edit")
        entry = trail.history("node", "n1")[0]
        assert entry.old_value == old
        assert entry.new_value == new
        assert type(entry.old_value) is type(old)
        assert type(entry.new_value) is type(new)

    def test_float_never_comes_back_as_string(self, trail: AuditTrail):
        trail.record("node_kpis", "n1", "risk.severity", None, 0.5, "weekly")
        entry = trail.history("node_kpis", "n1")[0]
        assert entry.new_value == 0.5
        assert isinstance(entry.new_value, float)
        assert not isinstance(entry.new_value, str)
        assert entry.new_value != "0.5"
        assert trail.value_at("node_kpis", "n1", "risk.severity", 100.0) == 0.5

    def test_none_on_creation_round_trips(self, trail: AuditTrail):
        trail.record("arc", "a1", "", None, {"kind": "transport"}, "onboarding")
        entry = trail.history("arc", "a1")[0]
        assert entry.old_value is None
        assert entry.new_value == {"kind": "transport"}

    def test_append_only_no_update_delete_methods(self, trail: AuditTrail):
        public = [name for name in dir(trail) if not name.startswith("_")]
        assert not any("update" in name.lower() or "delete" in name.lower() for name in public)


# value_at


class TestValueAt:
    def test_value_at_picks_last_write_before_t(self, trail: AuditTrail, clock: FixedClock):
        for ts, value in [(100.0, "v100"), (200.0, "v200"), (300.0, "v300")]:
            clock.set(ts)
            trail.record("node", "n1", "statut", None, value, "weekly")

        assert trail.value_at("node", "n1", "statut", 250.0) == "v200"
        assert trail.value_at("node", "n1", "statut", 50.0) is None
        assert trail.value_at("node", "n1", "statut", 300.0) == "v300"

    def test_value_at_unknown_entity_or_field(self, trail: AuditTrail):
        trail.record("node", "n1", "statut", None, "x", "edit")
        assert trail.value_at("node", "n2", "statut", 1e12) is None
        assert trail.value_at("node", "n1", "autre_champ", 1e12) is None

    def test_value_at_same_timestamp_takes_highest_id(self, trail: AuditTrail):
        trail.record("node", "n1", "f", None, "premier", "edit")
        trail.record("node", "n1", "f", "premier", "second", "edit")
        # Meme timestamp (horloge figee) : departage par id decroissant.
        assert trail.value_at("node", "n1", "f", 100.0) == "second"


# record_many : lot atomique


class TestRecordMany:
    def test_fifty_entries_in_one_batch(self, trail: AuditTrail, conn: sqlite3.Connection):
        entries = [("node", f"n{i}", "f", None, i, "migration", "") for i in range(50)]
        trail.record_many(entries)
        assert _count(conn) == 50
        assert not conn.in_transaction  # le lot est commite

    def test_invalid_entry_mid_batch_writes_nothing(
        self, trail: AuditTrail, conn: sqlite3.Connection
    ):
        entries: list[tuple[str, str, str, Any, Any, str, str]] = [
            ("node", f"n{i}", "f", None, i, "edit", "") for i in range(10)
        ]
        entries[5] = ("node", "n5", "f", None, object(), "edit", "")  # non serialisable JSON
        with pytest.raises(TypeError):
            trail.record_many(entries)
        assert _count(conn) == 0
        assert not conn.in_transaction

    def test_sql_constraint_violation_mid_batch_writes_nothing(
        self, trail: AuditTrail, conn: sqlite3.Connection
    ):
        entries: list[tuple[str, str, str, Any, Any, str, str]] = [
            ("node", f"n{i}", "f", None, i, "edit", "") for i in range(10)
        ]
        # entity_type NULL : viole NOT NULL au milieu du lot.
        entries[5] = (None, "n5", "f", None, 5, "edit", "")  # type: ignore[assignment]
        with pytest.raises(sqlite3.IntegrityError):
            trail.record_many(entries)
        assert _count(conn) == 0
        assert not conn.in_transaction

    def test_empty_batch_is_a_no_op(self, trail: AuditTrail, conn: sqlite3.Connection):
        trail.record_many([])
        assert _count(conn) == 0


# history : filtres, limit, before, ordre


class TestHistoryFilters:
    @pytest.fixture
    def populated(self, trail: AuditTrail, clock: FixedClock) -> AuditTrail:
        for ts, field, value in [
            (100.0, "a", 1),
            (200.0, "b", 2),
            (300.0, "a", 3),
            (400.0, "a", 4),
        ]:
            clock.set(ts)
            trail.record("node", "n1", field, None, value, "edit")
        clock.set(500.0)
        trail.record("node", "AUTRE", "a", None, 99, "edit")
        return trail

    def test_order_desc_by_timestamp_then_id(self, populated: AuditTrail):
        entries = populated.history("node", "n1")
        assert [e.timestamp for e in entries] == [400.0, 300.0, 200.0, 100.0]
        assert [e.id for e in entries] == sorted([e.id for e in entries], reverse=True)

    def test_same_timestamp_orders_by_id_desc(self, trail: AuditTrail):
        first = trail.record("node", "n1", "f", None, 1, "edit")
        second = trail.record("node", "n1", "f", 1, 2, "edit")
        entries = trail.history("node", "n1")
        assert [e.id for e in entries] == [second, first]

    def test_filter_by_field(self, populated: AuditTrail):
        entries = populated.history("node", "n1", field="a")
        assert [e.new_value for e in entries] == [4, 3, 1]
        assert all(e.field == "a" for e in entries)

    def test_filter_by_entity(self, populated: AuditTrail):
        assert len(populated.history("node", "AUTRE")) == 1
        assert populated.history("arc", "n1") == []

    def test_limit(self, populated: AuditTrail):
        entries = populated.history("node", "n1", limit=2)
        assert [e.timestamp for e in entries] == [400.0, 300.0]

    def test_before_is_strict(self, populated: AuditTrail):
        entries = populated.history("node", "n1", before=300.0)
        assert [e.timestamp for e in entries] == [200.0, 100.0]

    def test_combined_field_before_limit(self, populated: AuditTrail):
        entries = populated.history("node", "n1", field="a", before=400.0, limit=1)
        assert [e.new_value for e in entries] == [3]


# iso_week


class TestIsoWeek:
    def test_known_date_gives_2026_s24(self, conn: sqlite3.Connection):
        # Midi local le mercredi 10 juin 2026 - semaine ISO 24 de 2026.
        clock = FixedClock(datetime(2026, 6, 10, 12, 0).timestamp())
        trail = AuditTrail(conn, clock)
        trail.record("node", "n1", "f", None, 1, "weekly")
        assert trail.history("node", "n1")[0].iso_week == "2026-S24"

    def test_iso_year_boundary(self, conn: sqlite3.Connection):
        # Le 1er janvier 2021 appartient a la semaine ISO 53 de... 2020.
        clock = FixedClock(datetime(2021, 1, 1, 12, 0).timestamp())
        trail = AuditTrail(conn, clock)
        trail.record("node", "n1", "f", None, 1, "weekly")
        assert trail.history("node", "n1")[0].iso_week == "2020-S53"

    def test_iso_week_follows_clock_set(self, conn: sqlite3.Connection):
        clock = FixedClock(datetime(2026, 6, 10, 12, 0).timestamp())
        trail = AuditTrail(conn, clock)
        trail.record("node", "n1", "f", None, 1, "weekly")
        clock.set(datetime(2026, 6, 17, 12, 0).timestamp())  # semaine suivante
        trail.record("node", "n1", "f", 1, 2, "weekly")
        weeks = [e.iso_week for e in trail.history("node", "n1")]
        assert weeks == ["2026-S25", "2026-S24"]


# Transactions : integration a la transaction de l'hote


class TestTransactions:
    def test_record_commits_when_no_transaction(self, trail: AuditTrail, conn: sqlite3.Connection):
        trail.record("node", "n1", "f", None, 1, "edit")
        assert not conn.in_transaction
        conn.rollback()  # sans effet : deja commite
        assert _count(conn) == 1

    def test_record_joins_host_transaction(self, trail: AuditTrail, conn: sqlite3.Connection):
        conn.execute("BEGIN")
        trail.record("node", "n1", "f", None, 1, "edit")
        assert conn.in_transaction  # pas de commit impose par l'audit
        conn.rollback()
        assert _count(conn) == 0  # l'hote a annule : l'audit suit

        conn.execute("BEGIN")
        trail.record("node", "n1", "f", None, 1, "edit")
        conn.commit()
        assert _count(conn) == 1

    def test_record_many_failure_preserves_host_transaction(
        self, trail: AuditTrail, conn: sqlite3.Connection
    ):
        conn.execute("BEGIN")
        trail.record("node", "avant", "f", None, 1, "edit")
        bad: list[tuple[str, str, str, Any, Any, str, str]] = [
            ("node", "n0", "f", None, 0, "edit", ""),
            (None, "n1", "f", None, 1, "edit", ""),  # type: ignore[list-item]
        ]
        with pytest.raises(sqlite3.IntegrityError):
            trail.record_many(bad)
        assert conn.in_transaction  # la transaction hote survit
        conn.commit()
        # Seule l'ecriture anterieure de l'hote est conservee, le lot est annule.
        entries = trail.history("node", "avant")
        assert len(entries) == 1
        assert _count(conn) == 1


# Concurrence


class TestConcurrency:
    def test_two_threads_fifty_records_each_under_shared_rlock(
        self, conn: sqlite3.Connection, clock: FixedClock
    ):
        lock = threading.RLock()
        trail = AuditTrail(conn, clock, lock=lock)
        errors: list[Exception] = []

        def worker(tag: str) -> None:
            try:
                for i in range(50):
                    trail.record("node", f"{tag}-{i}", "f", None, i, "edit", operator_id=tag)
            except Exception as exc:  # pragma: no cover - echec remonte a l'assert
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("t1", "t2")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert _count(conn) == 100
