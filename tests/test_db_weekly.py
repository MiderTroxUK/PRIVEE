"""Tests de la revue hebdomadaire et du journal des décisions (migration client v5).

Couvre : migration v4 -> v5 sur base réelle peuplée (tables créées, données
préservées, idempotence), sémantique d'``upsert_weekly_review`` (fusion des
volets, ``started_at`` posé une seule fois, ``completed_at`` écrasable),
round-trip ``save_decision``/``list_decisions`` (tri DESC, filtre semaine,
isolation par nœud) et persistance après réouverture du fichier.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from supplyscore.data.db import ClientDatabase
from supplyscore.data.migrations import (
    _client_v1,
    _client_v2,
    _client_v3,
    _client_v4,
    apply_migrations,
)

_SCORES = {"ud": 0.6, "ur": 0.4, "a": 0.8, "f": 0.1, "h": 0.05}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row[0] for row in rows}


def _build_v4_client_with_data(db_file: Path) -> None:
    """Construit une vraie base client v4 peuplée (évaluation + événement)."""
    conn = sqlite3.connect(str(db_file))
    _client_v1(conn)
    _client_v2(conn)
    _client_v3(conn)
    _client_v4(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    conn.execute(
        """
        INSERT INTO assessments (node_id, project_id, operator_id, comparisons_json,
                                 criteria_scores_json, weights_json, consistency_ratio,
                                 is_consistent, ud, notes, timestamp, iso_week)
        VALUES ('n1', 'p1', 'op-7', '{}', '[]', '[]', 0.03, 1, 0.4, 'hebdo',
                1000.0, '2026-S24')
        """
    )
    conn.execute(
        """
        INSERT INTO events (id, node_id, event_type, iso_week, occurred_at,
                            params_json, impacts_json, reverted_at, operator_id, notes)
        VALUES ('e1', 'n1', 'panne', '2026-S24', 1500.0, '{}', '{}', NULL, 'op-7', '')
        """
    )
    conn.commit()
    conn.close()


# --- Migration client v4 -> v5 ------------------------------------------------------


class TestClientV5Migration:
    def test_v4_to_v5_creates_tables_and_preserves_data(self, tmp_path: Path) -> None:
        db_file = tmp_path / "client.sqlite"
        _build_v4_client_with_data(db_file)

        conn = sqlite3.connect(str(db_file))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert apply_migrations(conn, "client") == 6
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6

        # Nouvelles tables et index présents.
        assert {"weekly_reviews", "decisions"} <= _table_names(conn)
        assert "idx_decisions_node_week" in _index_names(conn)

        # Données préservées.
        row = conn.execute("SELECT node_id, operator_id, ud, iso_week FROM assessments").fetchone()
        assert row == ("n1", "op-7", 0.4, "2026-S24")
        assert conn.execute("SELECT id, event_type FROM events").fetchone() == ("e1", "panne")
        conn.close()

    def test_v5_is_idempotent(self, tmp_path: Path) -> None:
        db_file = tmp_path / "client.sqlite"
        _build_v4_client_with_data(db_file)
        conn = sqlite3.connect(str(db_file))

        assert apply_migrations(conn, "client") == 6
        # Re-application : no-op, données intactes.
        assert apply_migrations(conn, "client") == 6
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        conn.close()

    def test_fresh_client_reaches_v5(self, tmp_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_path / "client.sqlite"))
        assert apply_migrations(conn, "client") == 6
        assert {"weekly_reviews", "decisions"} <= _table_names(conn)
        assert "idx_decisions_node_week" in _index_names(conn)
        conn.close()


# --- Revue hebdomadaire (weekly_reviews) ---------------------------------------------


class TestWeeklyReview:
    def test_get_sur_semaine_vierge_retourne_none(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            assert db.get_weekly_review("n1", "2026-S24") is None

    def test_creation_minimale(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.upsert_weekly_review("n1", "2026-S24")
            review = db.get_weekly_review("n1", "2026-S24")
            assert review == {"volets": {}, "started_at": None, "completed_at": None}

    def test_volets_fusionnes_cle_a_cle(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.upsert_weekly_review("n1", "2026-S24", volets={"ahp": 1})
            db.upsert_weekly_review("n1", "2026-S24", volets={"kpis": 1})
            review = db.get_weekly_review("n1", "2026-S24")
            assert review is not None
            assert review["volets"] == {"ahp": 1, "kpis": 1}

            # Un volet déjà présent est écrasé par sa nouvelle valeur.
            db.upsert_weekly_review("n1", "2026-S24", volets={"ahp": 0})
            review = db.get_weekly_review("n1", "2026-S24")
            assert review is not None
            assert review["volets"] == {"ahp": 0, "kpis": 1}

    def test_started_at_pose_une_seule_fois(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.upsert_weekly_review("n1", "2026-S24", started_at=1000.0)
            db.upsert_weekly_review("n1", "2026-S24", started_at=2000.0)  # ignoré
            review = db.get_weekly_review("n1", "2026-S24")
            assert review is not None
            assert review["started_at"] == 1000.0

    def test_completed_at_ecrasable(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.upsert_weekly_review("n1", "2026-S24", completed_at=3000.0)
            db.upsert_weekly_review("n1", "2026-S24", completed_at=4000.0)
            review = db.get_weekly_review("n1", "2026-S24")
            assert review is not None
            assert review["completed_at"] == 4000.0

    def test_champs_non_fournis_intacts(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.upsert_weekly_review("n1", "2026-S24", volets={"ahp": 1}, started_at=1000.0)
            # Mise à jour partielle : ni volets ni started_at ne bougent.
            db.upsert_weekly_review("n1", "2026-S24", completed_at=2000.0)
            review = db.get_weekly_review("n1", "2026-S24")
            assert review == {
                "volets": {"ahp": 1},
                "started_at": 1000.0,
                "completed_at": 2000.0,
            }

    def test_semaines_et_noeuds_independants(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.upsert_weekly_review("n1", "2026-S24", volets={"ahp": 1})
            db.upsert_weekly_review("n1", "2026-S25", volets={"kpis": 1})
            db.upsert_weekly_review("n2", "2026-S24", volets={"jalons": 1})

            s24 = db.get_weekly_review("n1", "2026-S24")
            s25 = db.get_weekly_review("n1", "2026-S25")
            autre = db.get_weekly_review("n2", "2026-S24")
            assert s24 is not None and s24["volets"] == {"ahp": 1}
            assert s25 is not None and s25["volets"] == {"kpis": 1}
            assert autre is not None and autre["volets"] == {"jalons": 1}


# --- Journal des décisions (decisions) -----------------------------------------------


class TestDecisions:
    def test_round_trip_et_tri_desc(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_decision(
                "d1",
                "n1",
                "2026-S24",
                "op-7",
                "Relancer le fournisseur",
                json.dumps(_SCORES),
                1000.0,
            )
            db.save_decision(
                "d2",
                "n1",
                "2026-S24",
                "op-8",
                "Activer l'arc de backup",
                json.dumps({"ud": 0.9, "ur": 0.2, "a": 0.3, "f": 0.7, "h": 0.0}),
                2000.0,
            )

            decisions = db.list_decisions("n1")
            # Tri created_at DESC : la plus récente d'abord.
            assert [d["id"] for d in decisions] == ["d2", "d1"]

            premiere = decisions[1]
            assert premiere["node_id"] == "n1"
            assert premiere["iso_week"] == "2026-S24"
            assert premiere["operator_id"] == "op-7"
            assert premiere["description"] == "Relancer le fournisseur"
            assert premiere["scores"] == _SCORES  # snapshot désérialisé
            assert premiere["created_at"] == 1000.0

    def test_filtre_iso_week(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_decision("d1", "n1", "2026-S24", "op", "A", "{}", 1000.0)
            db.save_decision("d2", "n1", "2026-S25", "op", "B", "{}", 2000.0)

            assert [d["id"] for d in db.list_decisions("n1")] == ["d2", "d1"]
            assert [d["id"] for d in db.list_decisions("n1", "2026-S24")] == ["d1"]
            assert [d["id"] for d in db.list_decisions("n1", "2026-S25")] == ["d2"]
            assert db.list_decisions("n1", "2026-S26") == []

    def test_isolation_par_noeud(self, tmp_path: Path) -> None:
        with ClientDatabase(tmp_path, "client-1") as db:
            db.save_decision("d1", "n1", "2026-S24", "op", "A", "{}", 1000.0)
            db.save_decision("d2", "n2", "2026-S24", "op", "B", "{}", 2000.0)

            assert [d["id"] for d in db.list_decisions("n1")] == ["d1"]
            assert [d["id"] for d in db.list_decisions("n2")] == ["d2"]
            assert db.list_decisions("n3") == []


# --- Persistance après réouverture ----------------------------------------------------


def test_donnees_persistent_apres_reouverture(tmp_path: Path) -> None:
    with ClientDatabase(tmp_path, "client-1") as db:
        db.upsert_weekly_review(
            "n1", "2026-S24", volets={"ahp": 1, "evenements": 1}, started_at=1000.0
        )
        db.upsert_weekly_review("n1", "2026-S24", completed_at=2000.0)
        db.save_decision("d1", "n1", "2026-S24", "op-7", "Décision", json.dumps(_SCORES), 1500.0)

    with ClientDatabase(tmp_path, "client-1") as db:
        assert db.schema_version == 6
        review = db.get_weekly_review("n1", "2026-S24")
        assert review == {
            "volets": {"ahp": 1, "evenements": 1},
            "started_at": 1000.0,
            "completed_at": 2000.0,
        }
        decisions = db.list_decisions("n1", "2026-S24")
        assert len(decisions) == 1
        assert decisions[0]["id"] == "d1"
        assert decisions[0]["scores"] == _SCORES
