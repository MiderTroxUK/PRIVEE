"""Framework de migrations de schéma SQLite versionnées par ``PRAGMA user_version``.

Chaque base (registre global ou base client) porte sa version de schéma dans
l'entête SQLite (``PRAGMA user_version``). :func:`apply_migrations` rejoue,
dans l'ordre, toutes les migrations dont la version est supérieure à la
version courante de la base, puis retourne la version finale.

Conventions :
- la migration v1 reproduit le schéma historique EXACT en ``CREATE TABLE IF
  NOT EXISTS`` : elle est idempotente et "passe par-dessus" une base existante
  créée par l'ancien code (tables déjà présentes mais ``user_version = 0``) ;
- chaque migration se termine par ``PRAGMA user_version = N`` dans la même
  transaction que ses DDL/DML : une migration est appliquée entièrement ou pas
  du tout.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Literal

MigrationFn = Callable[[sqlite3.Connection], None]

# --- Migrations du registre global ----------------------------------------------


def _registry_v1(conn: sqlite3.Connection) -> None:
    """v1 registre : schéma historique (projects, nodes, arcs), idempotent."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner_node_id TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
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
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS arcs (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                label TEXT NOT NULL,
                gamma REAL NOT NULL,
                beta REAL NOT NULL,
                delta REAL NOT NULL,
                kpis_json TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id)
            )
            """
        )
        conn.execute("PRAGMA user_version = 1")


def _registry_v2(conn: sqlite3.Connection) -> None:
    """v2 registre : node_urgency, project_settings, vraies FK et index.

    SQLite ne supporte pas ``ALTER TABLE ... ADD CONSTRAINT`` : les tables
    ``nodes`` et ``arcs`` sont reconstruites (CREATE nouvelle table avec FK,
    INSERT ... SELECT, DROP, RENAME). ``PRAGMA foreign_keys`` est désactivé
    pendant la reconstruction (la pragma est sans effet dans une transaction,
    elle est donc basculée hors transaction) puis réactivé.

    Les vieilles bases peuvent contenir des références pendantes : les arcs
    orphelins sont purgés et les ``project_id`` inconnus remis à NULL AVANT la
    reconstruction, pour que ``PRAGMA foreign_key_check`` soit vide après coup.
    """
    conn.commit()  # garantit qu'aucune transaction n'est ouverte
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        # BEGIN explicite : les DDL participent aussi à la transaction (le
        # mode legacy de sqlite3 n'ouvre une transaction implicite que sur DML).
        conn.execute("BEGIN IMMEDIATE")
        try:
            # a. états d'urgence courants par nœud (cache de redémarrage).
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS node_urgency (
                    node_id TEXT PRIMARY KEY,
                    ud_local REAL,
                    ur_local REAL,
                    ud REAL,
                    ur REAL,
                    adequation REAL,
                    false_urgency REAL,
                    hidden_risk REAL,
                    timestamp REAL
                )
                """
            )
            # b. réglages par projet (valeurs JSON arbitraires).
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_settings (
                    project_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, key)
                )
                """
            )
            # c. assainissement des références pendantes AVANT la reconstruction.
            conn.execute(
                """
                DELETE FROM arcs
                WHERE source_id NOT IN (SELECT id FROM nodes)
                   OR target_id NOT IN (SELECT id FROM nodes)
                """
            )
            conn.execute(
                """
                UPDATE nodes SET project_id = NULL
                WHERE project_id IS NOT NULL
                  AND project_id NOT IN (SELECT id FROM projects)
                """
            )
            # c. reconstruction de nodes avec FK vers projects.
            conn.execute("DROP TABLE IF EXISTS nodes_new")
            conn.execute(
                """
                CREATE TABLE nodes_new (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    label TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    location TEXT,
                    latitude REAL,
                    longitude REAL,
                    status TEXT NOT NULL,
                    kpis_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO nodes_new (id, name, label, kind, rank, project_id,
                                       location, latitude, longitude, status, kpis_json)
                SELECT id, name, label, kind, rank, project_id,
                       location, latitude, longitude, status, kpis_json
                FROM nodes
                """
            )
            conn.execute("DROP TABLE nodes")
            conn.execute("ALTER TABLE nodes_new RENAME TO nodes")
            # c. reconstruction de arcs avec FK vers nodes.
            conn.execute("DROP TABLE IF EXISTS arcs_new")
            conn.execute(
                """
                CREATE TABLE arcs_new (
                    source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    gamma REAL NOT NULL,
                    beta REAL NOT NULL,
                    delta REAL NOT NULL,
                    kpis_json TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO arcs_new (source_id, target_id, label, gamma,
                                      beta, delta, kpis_json)
                SELECT source_id, target_id, label, gamma, beta, delta, kpis_json
                FROM arcs
                """
            )
            conn.execute("DROP TABLE arcs")
            conn.execute("ALTER TABLE arcs_new RENAME TO arcs")
            # d. index de filtrage des nœuds par projet.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project_id)")
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


# --- Migrations des bases client ---------------------------------------------------


def _client_v1(conn: sqlite3.Connection) -> None:
    """v1 client : schéma historique (assessments, kpi_snapshots, urgency_history)."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                comparisons_json TEXT NOT NULL,
                criteria_scores_json TEXT NOT NULL,
                weights_json TEXT NOT NULL,
                consistency_ratio REAL NOT NULL,
                is_consistent INTEGER NOT NULL,
                ud REAL NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                timestamp REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kpi_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                kpis_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS urgency_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                ud_local REAL,
                ur_local REAL,
                ud REAL,
                ur REAL,
                adequation REAL,
                false_urgency REAL,
                hidden_risk REAL,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.execute("PRAGMA user_version = 1")


# --- Registres de migrations ---------------------------------------------------------

_REGISTRY_MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _registry_v1),
    (2, _registry_v2),
]

_CLIENT_MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _client_v1),
]

_MIGRATIONS_BY_KIND: dict[str, list[tuple[int, MigrationFn]]] = {
    "registry": _REGISTRY_MIGRATIONS,
    "client": _CLIENT_MIGRATIONS,
}


def schema_version(conn: sqlite3.Connection) -> int:
    """Retourne la version de schéma courante (``PRAGMA user_version``)."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def apply_migrations(conn: sqlite3.Connection, kind: Literal["registry", "client"]) -> int:
    """Applique les migrations manquantes de la base ``kind`` et retourne sa version.

    Args:
        conn: connexion SQLite ouverte sur la base à migrer.
        kind: ``"registry"`` (registre global) ou ``"client"`` (base par client).

    Returns:
        La version finale du schéma (``PRAGMA user_version``) après migration.
    """
    migrations = _MIGRATIONS_BY_KIND[kind]
    current = schema_version(conn)
    for version, migrate in migrations:
        if version > current:
            migrate(conn)
            current = version
    return current
