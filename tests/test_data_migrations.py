"""Tests des migrations de schéma (supplyscore.data.migrations) et du cycle de vie.

Couvre : migrations sur base neuve et sur base v1 héritée, redémarrage complet
du service (restauration des UrgencyState), accès concurrents, fermeture
propre (WAL) et réglages par projet.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import threading

import pytest

from supplyscore.data import migrations
from supplyscore.data.db import ClientDatabase, RegistryDatabase, kpis_from_json
from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.data.migrations import apply_migrations
from supplyscore.domain.models import TaskStatus, UrgencyState
from supplyscore.graph import PropagationEngine
from supplyscore.services import SupplyScoreService

# --- Helpers --------------------------------------------------------------------

# Schéma v1 historique BRUT (tel que créé par l'ancien code, user_version = 0).
_LEGACY_REGISTRY_SCHEMA = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_node_id TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    rank INTEGER NOT NULL,
    project_id TEXT,
    location TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL,
    kpis_json TEXT NOT NULL
);
CREATE TABLE arcs (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    label TEXT NOT NULL,
    gamma REAL NOT NULL,
    beta REAL NOT NULL,
    delta REAL NOT NULL,
    kpis_json TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id)
);
"""

_URGENCY_FIELDS = (
    "ud_local",
    "ur_local",
    "ud",
    "ur",
    "adequation",
    "false_urgency",
    "hidden_risk",
)


def _build_legacy_registry(path) -> None:
    """Construit une base registre v1 réelle avec données (et incohérences)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_LEGACY_REGISTRY_SCHEMA)
    conn.execute(
        "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
        ("p1", "Projet", "n1", "desc", 1000.0),
    )
    nodes = [
        ("n1", "Client", "Client", "node", 0, "p1", "Lyon", 45.7, 4.8, "active", "{}"),
        ("n2", "Usine", "Factory", "node", 1, "p1", None, None, None, "active", "{}"),
        # project_id pendant (projet jamais créé) : doit être remis à NULL.
        ("n3", "Errant", "Workshop", "node", 1, "ghost-project", None, None, None, "done", "{}"),
    ]
    conn.executemany(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        nodes,
    )
    conn.executemany(
        "INSERT INTO arcs VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("n2", "n1", "Truck", 0.4, 0.6, 1.0, "{}"),
            # arc orphelin (source jamais créée) : doit être purgé.
            ("ghost-node", "n1", "Ship", 0.5, 0.5, 1.0, "{}"),
        ],
    )
    conn.commit()
    conn.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row[0] for row in rows}


# --- Migrations : base neuve -------------------------------------------------------


class TestFreshDatabase:
    def test_registry_migrations_from_scratch(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "registry.sqlite"))
        version = apply_migrations(conn, "registry")

        assert version == 5
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        tables = _table_names(conn)
        assert {"projects", "nodes", "arcs", "node_urgency", "project_settings"} <= tables
        assert "idx_nodes_project" in _index_names(conn)
        conn.close()

    def test_client_migrations_from_scratch(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "client.sqlite"))
        version = apply_migrations(conn, "client")

        assert version == 7
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        assert {"assessments", "kpi_snapshots", "urgency_history", "interventions"} <= _table_names(
            conn
        )
        assert "idx_interventions_node_date" in _index_names(conn)
        conn.close()


# --- Migrations : base v1 héritée ----------------------------------------------------


class TestLegacyV1Database:
    def test_migration_preserves_data_and_cleans_orphans(self, tmp_path):
        db_file = tmp_path / "registry.sqlite"
        _build_legacy_registry(db_file)

        conn = sqlite3.connect(str(db_file))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        version = apply_migrations(conn, "registry")
        assert version == 5

        # Données préservées.
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        node_ids = {r[0] for r in conn.execute("SELECT id FROM nodes").fetchall()}
        assert node_ids == {"n1", "n2", "n3"}
        row = conn.execute(
            "SELECT name, rank, project_id, status FROM nodes WHERE id = 'n1'"
        ).fetchone()
        assert row == ("Client", 0, "p1", "active")

        # Arc orphelin purgé, arc valide conservé.
        arcs = conn.execute("SELECT source_id, target_id FROM arcs").fetchall()
        assert arcs == [("n2", "n1")]

        # project_id pendant remis à NULL (FK ON DELETE SET NULL posée).
        assert conn.execute("SELECT project_id FROM nodes WHERE id = 'n3'").fetchone()[0] is None

        # FK actives : aucune violation référentielle.
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # Les nouvelles tables et l'index existent.
        assert {"node_urgency", "project_settings"} <= _table_names(conn)
        assert "idx_nodes_project" in _index_names(conn)
        conn.close()

    def test_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "registry.sqlite"
        _build_legacy_registry(db_file)
        conn = sqlite3.connect(str(db_file))

        assert apply_migrations(conn, "registry") == 5
        # Re-application : no-op, données intactes.
        assert apply_migrations(conn, "registry") == 5
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM arcs").fetchone()[0] == 1
        conn.close()

    def test_registry_database_opens_legacy_file(self, tmp_path):
        _build_legacy_registry(tmp_path / "registry.sqlite")

        with RegistryDatabase(tmp_path) as db:
            assert db.schema_version == 5
            node = db.get_node("n1")
            assert node is not None and node.name == "Client"
            # Pas de ligne node_urgency : UrgencyState vierge.
            for field in _URGENCY_FIELDS:
                assert getattr(node.urgency, field) is None


# --- Migrations : base client v6 existante (U16 — journal des interventions) --------


class TestClientV6ToV7:
    def test_migration_v6_to_v7_ajoute_interventions_sans_perte(self, tmp_path):
        """Une base client réellement en v6 migre proprement vers v7 (open -> migrate -> reopen)."""
        db_file = tmp_path / "client.sqlite"

        # Construit une base v6 réelle en rejouant UNIQUEMENT les vraies
        # migrations v1..v6 du module (pas une copie à la main du schéma).
        conn = sqlite3.connect(str(db_file))
        with pytest.MonkeyPatch.context() as mp:
            # ``apply_migrations`` lit ``_MIGRATIONS_BY_KIND["client"]`` (pas
            # ``_CLIENT_MIGRATIONS`` directement) : c'est CETTE entrée qu'il
            # faut patcher pour que la troncature soit effective.
            sliced = [t for t in migrations._CLIENT_MIGRATIONS if t[0] <= 6]
            mp.setitem(migrations._MIGRATIONS_BY_KIND, "client", sliced)
            version = apply_migrations(conn, "client")
        assert version == 6
        assert "interventions" not in _table_names(conn)

        # Données antérieures, pour vérifier qu'elles survivent à la migration v7.
        conn.execute(
            """
            INSERT INTO events (id, node_id, event_type, iso_week, occurred_at,
                                params_json, impacts_json, reverted_at, operator_id, notes)
            VALUES ('ev1', 'n1', 'panne_machine', '2026-S24', 1000.0, '{}', '[]', NULL, 'op', '')
            """
        )
        conn.commit()
        conn.close()

        # Réouverture : migration réelle jusqu'à v7 (liste NON monkeypatchée).
        conn2 = sqlite3.connect(str(db_file))
        version2 = apply_migrations(conn2, "client")
        assert version2 == 7
        assert conn2.execute("PRAGMA user_version").fetchone()[0] == 7
        assert "interventions" in _table_names(conn2)
        assert "idx_interventions_node_date" in _index_names(conn2)
        assert conn2.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        conn2.close()

        # Rejouable : re-application = no-op.
        conn3 = sqlite3.connect(str(db_file))
        assert apply_migrations(conn3, "client") == 7
        assert conn3.execute("PRAGMA user_version").fetchone()[0] == 7
        conn3.close()

        # Le chemin normal (ClientDatabase) migre aussi proprement et la table
        # interventions est immédiatement utilisable (round-trip minimal).
        with ClientDatabase(tmp_path, "client") as db:
            assert db.schema_version == 7
            row_id = db.insert_intervention(
                {
                    "id": "iv-1",
                    "node_id": "n1",
                    "date_ts": 1000.0,
                    "etat_avant_json": "{}",
                    "action_id": "a1",
                    "acteur": "op",
                    "objectif_operationnel": "tester la migration",
                    "decidee_ts": 1000.0,
                    "executee": None,
                    "executee_ts": None,
                    "date_effet_ts": None,
                    "resultat": "en_cours",
                    "etat_apres_json": None,
                    "etat_risque_avant_json": "{}",
                    "etat_risque_apres_json": None,
                    "succes": None,
                    "effets_voisins_json": "[]",
                    "notes": "",
                }
            )
            assert row_id == "iv-1"
            assert [row["id"] for row in db.list_interventions("n1")] == ["iv-1"]


# --- Redémarrage du service (test pivot) ---------------------------------------------


def test_restart_restores_identical_urgency_states(tmp_path):
    store = tmp_path / "store"
    with SupplyScoreService(db_dir=store) as service:
        service.seed_demo(n_ranks=2, seed=3)
        states = service.evaluate_all(persist=True)
        captured = {nid: dataclasses.replace(state) for nid, state in states.items()}
    assert captured  # le seed a bien produit des nœuds

    with SupplyScoreService(db_dir=store) as reloaded:
        reloaded.load_graph_from_registry()
        nodes = reloaded.repo.nodes()
        assert {n.id for n in nodes} == set(captured)
        for node in nodes:
            expected = captured[node.id]
            for field in _URGENCY_FIELDS:
                assert getattr(node.urgency, field) == getattr(expected, field), (
                    node.id,
                    field,
                )


# --- Accès concurrents -----------------------------------------------------------------


def test_threaded_access_keeps_databases_intact(tmp_path):
    store = tmp_path / "store"
    n_threads, n_iterations = 8, 50

    service = SupplyScoreService(db_dir=store)
    project = service.seed_demo(n_ranks=2, seed=3)
    node_ids = [n.id for n in service.repo.nodes()]

    # Assessments générés À L'AVANCE (le générateur n'est pas thread-safe).
    gen = RandomSupplyChainGenerator(seed=123)
    plans = [
        [
            gen.generate_assessment(node_ids[(t + i) % len(node_ids)], project.id)
            for i in range(n_iterations)
        ]
        for t in range(n_threads)
    ]

    errors: list[BaseException] = []

    def worker(thread_idx: int) -> None:
        try:
            for i in range(n_iterations):
                if i % 2 == 0:
                    service.submit_assessment(plans[thread_idx][i])
                else:
                    service.evaluate_all(persist=(i % 10 == 9))
        except BaseException as exc:  # le test collecte toute exception
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []

    service.close()
    for db_file in (store / "registry.sqlite", store / f"{node_ids[0]}.sqlite"):
        assert db_file.exists()
        conn = sqlite3.connect(str(db_file))
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        conn.close()


# --- Fermeture propre (WAL) --------------------------------------------------------------


def test_close_leaves_no_wal_or_shm_files(tmp_path):
    store = tmp_path / "store"
    service = SupplyScoreService(db_dir=store)
    service.seed_demo(n_ranks=2, seed=3)
    service.evaluate_all(persist=True)
    service.close()

    leftovers = [p.name for p in store.iterdir() if p.name.endswith(("-wal", "-shm"))]
    assert leftovers == []
    assert (store / "registry.sqlite").exists()


# --- set_status : une seule propagation ----------------------------------------------------


def test_set_status_propagates_exactly_once(tmp_path, monkeypatch):
    with SupplyScoreService(db_dir=tmp_path / "store") as service:
        service.seed_demo(n_ranks=2, seed=3)
        deepest = max(service.repo.nodes(), key=lambda n: n.rank)
        before = service.evaluate_all()[deepest.id].ur
        assert before is not None and before > 0.0

        calls: list[str] = []
        original_all = PropagationEngine.propagate_all
        original_incremental = PropagationEngine.propagate_incremental

        def spy_all(self: PropagationEngine) -> dict[str, UrgencyState]:
            calls.append("all")
            return original_all(self)

        def spy_incremental(self: PropagationEngine) -> dict[str, UrgencyState]:
            calls.append("incremental")
            return original_incremental(self)

        monkeypatch.setattr(PropagationEngine, "propagate_all", spy_all)
        monkeypatch.setattr(PropagationEngine, "propagate_incremental", spy_incremental)
        states = service.set_status(deepest.id, TaskStatus.DONE)

        # Exactement UNE propagation par set_status — INCRÉMENTALE depuis E14.4
        # (rien de structurel n'a changé : pas de délégation au complet).
        assert calls == ["incremental"]
        after = states[deepest.id].ur
        # DONE : nœud le plus profond (sans fournisseur) -> son Ur tombe à 0.
        assert after is not None
        assert after == pytest.approx(0.0)
        assert after < before
        # Statut persisté dans le registre.
        registry_node = service.registry.get_node(deepest.id)
        assert registry_node is not None and registry_node.status is TaskStatus.DONE


# --- Réglages par projet ----------------------------------------------------------------


def test_settings_round_trip(tmp_path):
    with RegistryDatabase(tmp_path) as db:
        db.set_setting("p1", "thresholds", {"low": 0.2, "high": 0.8})
        db.set_setting("p1", "tags", ["alpha", "beta", 3])
        db.set_setting("p1", "mode", "strict")

        assert db.get_setting("p1", "thresholds") == {"low": 0.2, "high": 0.8}
        assert db.get_setting("p1", "tags") == ["alpha", "beta", 3]
        assert db.get_setting("p1", "mode") == "strict"
        assert db.get_setting("p1", "missing") is None
        assert db.get_setting("autre-projet", "mode") is None

        db.set_setting("p1", "mode", "lenient")  # remplacement (upsert)
        assert db.get_setting("p1", "mode") == "lenient"


# --- Robustesse de kpis_from_json ----------------------------------------------------------


def test_kpis_from_json_ignores_unknown_keys():
    payload = json.dumps(
        {
            "network": {"product": "Steel coil", "champ_futur": 123},
            "bloc_inconnu": {"x": 1},
        }
    )
    bundle = kpis_from_json(payload)
    assert bundle.network.product == "Steel coil"
    assert bundle.inventory.max_volume_m3 is None
