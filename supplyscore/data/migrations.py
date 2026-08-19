"""Framework de migrations de schema SQLite versionnees par ``PRAGMA user_version``.

Chaque base (registre global ou base client) porte sa version de schema dans
l'entete SQLite (``PRAGMA user_version``). :func:`apply_migrations` rejoue,
dans l'ordre, toutes les migrations dont la version est superieure a la
version courante de la base, puis retourne la version finale.

Conventions :
- la migration v1 reproduit le schema historique EXACT en ``CREATE TABLE IF
  NOT EXISTS`` : elle est idempotente et "passe par-dessus" une base existante
  creee par l'ancien code (tables deja presentes mais ``user_version = 0``) ;
- chaque migration se termine par ``PRAGMA user_version = N`` dans la meme
  transaction que ses DDL/DML : une migration est appliquee entierement ou pas
  du tout.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Literal

from supplyscore.core.clock import iso_week

MigrationFn = Callable[[sqlite3.Connection], None]

# Migrations du registre global


def _registry_v1(conn: sqlite3.Connection) -> None:
    """v1 registre : schema historique (projects, nodes, arcs), idempotent."""
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
    INSERT ... SELECT, DROP, RENAME). ``PRAGMA foreign_keys`` est desactive
    pendant la reconstruction (la pragma est sans effet dans une transaction,
    elle est donc basculee hors transaction) puis reactive.

    Les vieilles bases peuvent contenir des references pendantes : les arcs
    orphelins sont purges et les ``project_id`` inconnus remis a NULL AVANT la
    reconstruction, pour que ``PRAGMA foreign_key_check`` soit vide apres coup.
    """
    conn.commit()  # garantit qu'aucune transaction n'est ouverte
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        # BEGIN explicite : les DDL participent aussi a la transaction (le mode legacy de sqlite3 n'ouvre une transaction implicite que sur DML).
        conn.execute("BEGIN IMMEDIATE")
        try:
            # a. etats d'urgence courants par noeud (cache de redemarrage).
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
            # b. reglages par projet (valeurs JSON arbitraires).
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
            # c. assainissement des references pendantes AVANT la reconstruction.
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
            # d. index de filtrage des noeuds par projet.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project_id)")
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _registry_v3(conn: sqlite3.Connection) -> None:
    """v3 registre : t0 projet, onboarding, arcs backup, jalons et tags.

    Ajouts : colonne ``projects.t0_ts`` (backfillee sur ``created_at``),
    ``nodes.onboarding_state``, ``arcs.arc_kind``, tables ``milestones``,
    ``tag_categories``/``tags``/``node_tags`` et ``onboarding_progress``.

    SQLite ne supporte pas ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` : la
    rejouabilite est garantie par le garde ``user_version`` du framework, et
    l'atomicite par la transaction explicite (``BEGIN IMMEDIATE`` ... commit) -
    une interruption laisse la base en v2, rejouable proprement.
    """
    conn.commit()  # garantit qu'aucune transaction n'est ouverte
    conn.execute("BEGIN IMMEDIATE")
    try:
        # a. origine temporelle du projet, backfillee sur la date de creation.
        conn.execute("ALTER TABLE projects ADD COLUMN t0_ts REAL")
        conn.execute("UPDATE projects SET t0_ts = created_at WHERE t0_ts IS NULL")
        # b. etat d'onboarding du noeud ('draft' tant que le wizard n'est pas fini).
        conn.execute(
            "ALTER TABLE nodes ADD COLUMN onboarding_state TEXT NOT NULL DEFAULT 'complete'"
        )
        # c. nature de l'arc (backup = inerte dans tous les calculs).
        conn.execute("ALTER TABLE arcs ADD COLUMN arc_kind TEXT NOT NULL DEFAULT 'nominal'")
        # d. jalons dates du cahier des charges d'un noeud.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS milestones (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'livraison',
                start_ts REAL NOT NULL,
                deadline_ts REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                progress REAL NOT NULL DEFAULT 0.0 CHECK (progress BETWEEN 0 AND 1),
                position INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE,
                CHECK (deadline_ts > start_ts)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_milestones_node ON milestones(node_id, position)"
        )
        # e. taxonomie par projet : categories controlees, tags libres, liaisons.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tag_categories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                color TEXT,
                UNIQUE(project_id, name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                category_id TEXT REFERENCES tag_categories(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                UNIQUE(project_id, name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS node_tags (
                node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (node_id, tag_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_tags_tag ON node_tags(tag_id)")
        # f. progression du wizard d'onboarding (brouillon JSON par noeud).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS onboarding_progress (
                node_id TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
                sections_done_json TEXT NOT NULL,
                draft_json TEXT NOT NULL DEFAULT '{}',
                current_step INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _create_audit_log(conn: sqlite3.Connection) -> None:
    """Cree la table ``audit_log`` et ses index (DDL partage registre/client).

    Journal d'audit generique : une ligne par changement de champ d'une entite
    (``old_value``/``new_value`` serialisees en texte), horodatee et rattachee
    a une semaine ISO. Idempotent (``IF NOT EXISTS`` partout) ; l'appelant est
    responsable de la transaction.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            source TEXT NOT NULL,
            operator_id TEXT NOT NULL DEFAULT '',
            iso_week TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_entity
        ON audit_log(entity_type, entity_id, field, timestamp)
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_week ON audit_log(iso_week)")


def _registry_v4(conn: sqlite3.Connection) -> None:
    """v4 registre : journal d'audit (``audit_log`` et ses index), idempotent."""
    with conn:
        _create_audit_log(conn)
        conn.execute("PRAGMA user_version = 4")


def _registry_v5(conn: sqlite3.Connection) -> None:
    """v5 registre : scenarios nommes par projet (table ``scenarios``), idempotent.

    Un scenario est un instantane nomme de parametres de simulation rattache a
    un projet. Son contenu (``payload_json``) est OPAQUE pour la couche data :
    stocke et restitue tel quel, sans interpretation. Le nom est unique PAR
    projet (``UNIQUE(project_id, nom)``) ; l'index ``idx_scenarios_project``
    sert les listages par projet.
    """
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                nom TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(project_id, nom)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_project ON scenarios(project_id)")
        conn.execute("PRAGMA user_version = 5")


# Migrations des bases client


def _client_v1(conn: sqlite3.Connection) -> None:
    """v1 client : schema historique (assessments, kpi_snapshots, urgency_history)."""
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


def _client_v2(conn: sqlite3.Connection) -> None:
    """v2 client : cahier des charges versionne (spec_sheet) et journal d'evenements."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spec_sheet (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(node_id, version)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                iso_week TEXT NOT NULL,
                occurred_at REAL NOT NULL,
                params_json TEXT NOT NULL,
                impacts_json TEXT NOT NULL,
                reverted_at REAL,
                operator_id TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_node_week ON events(node_id, iso_week)")
        conn.execute("PRAGMA user_version = 2")


def _client_v3(conn: sqlite3.Connection) -> None:
    """v3 client : journal d'audit, index temporel des snapshots, corrections d'evaluations.

    Ajouts : table ``audit_log`` (meme contenu que cote registre, v4), index
    ``idx_kpi_snap_node_ts`` pour les lectures temporelles (``kpis_at``) et
    colonne ``assessments.replaces_id`` (NULL = evaluation originale, sinon id
    de l'evaluation que cette ligne corrige).

    L'``ALTER TABLE ... ADD COLUMN`` n'est pas rejouable : la rejouabilite est
    garantie par le garde ``user_version`` du framework, et l'atomicite par la
    transaction explicite (``BEGIN IMMEDIATE`` ... commit) - une interruption
    laisse la base en v2, rejouable proprement.
    """
    conn.commit()  # garantit qu'aucune transaction n'est ouverte
    conn.execute("BEGIN IMMEDIATE")
    try:
        # a. journal d'audit partage avec le registre.
        _create_audit_log(conn)
        # b. index de lecture temporelle des snapshots KPI (kpis_at).
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_kpi_snap_node_ts
            ON kpi_snapshots(node_id, timestamp)
            """
        )
        # c. chainage des corrections d'evaluations (NULL = originale).
        conn.execute("ALTER TABLE assessments ADD COLUMN replaces_id INTEGER")
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _client_v4(conn: sqlite3.Connection) -> None:
    """v4 client : semaine ISO materialisee sur les evaluations et l'historique d'urgence.

    Ajoute la colonne ``iso_week`` (libelle " AAAA-Sxx ") aux tables
    ``assessments`` et ``urgency_history``, backfille chaque ligne existante en
    Python via :func:`supplyscore.core.clock.iso_week` appliquee a son
    ``timestamp`` (heure locale), puis pose les index ``idx_assessments_week``
    et ``idx_urgency_week`` qui servent le cycle hebdomadaire
    (:mod:`supplyscore.services.weekly`).

    L'``ALTER TABLE ... ADD COLUMN`` n'est pas rejouable : la rejouabilite est
    garantie par le garde ``user_version`` du framework, et l'atomicite par la
    transaction explicite (``BEGIN IMMEDIATE`` ... commit) - une interruption
    laisse la base en v3, rejouable proprement.
    """
    conn.commit()  # garantit qu'aucune transaction n'est ouverte
    conn.execute("BEGIN IMMEDIATE")
    try:
        # a. colonne iso_week + backfill Python (semaine ISO du timestamp).
        conn.execute("ALTER TABLE assessments ADD COLUMN iso_week TEXT NOT NULL DEFAULT ''")
        rows = conn.execute("SELECT id, timestamp FROM assessments").fetchall()
        conn.executemany(
            "UPDATE assessments SET iso_week = ? WHERE id = ?",
            [(iso_week(row[1]), row[0]) for row in rows],
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_assessments_week ON assessments(node_id, iso_week)"
        )
        # b. idem pour l'historique d'urgence.
        conn.execute("ALTER TABLE urgency_history ADD COLUMN iso_week TEXT NOT NULL DEFAULT ''")
        rows = conn.execute("SELECT id, timestamp FROM urgency_history").fetchall()
        conn.executemany(
            "UPDATE urgency_history SET iso_week = ? WHERE id = ?",
            [(iso_week(row[1]), row[0]) for row in rows],
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_urgency_week ON urgency_history(node_id, iso_week)"
        )
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _client_v5(conn: sqlite3.Connection) -> None:
    """v5 client : revue hebdomadaire par volets et journal des decisions.

    Ajouts : table ``weekly_reviews`` (avancement des volets de la revue d'une
    semaine ISO d'un noeud - ``volets_json`` de la forme ``{"ahp": 0|1, ...}`` -
    avec horodatages de demarrage et de completion) et table ``decisions``
    (journal des decisions prises en revue, chacune emportant un snapshot des
    scores ``{ud, ur, a, f, h}`` au moment T), plus l'index
    ``idx_decisions_node_week``. Idempotent (``IF NOT EXISTS`` partout).
    """
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_reviews (
                node_id TEXT NOT NULL,
                iso_week TEXT NOT NULL,
                volets_json TEXT NOT NULL DEFAULT '{}',
                started_at REAL,
                completed_at REAL,
                PRIMARY KEY (node_id, iso_week)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                iso_week TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                description TEXT NOT NULL,
                scores_snapshot_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_node_week ON decisions(node_id, iso_week)"
        )
        conn.execute("PRAGMA user_version = 5")


def _client_v6(conn: sqlite3.Connection) -> None:
    """v6 client : index temporels manquants (faiblesse #15), idempotent.

    Constat avant ajout : ``idx_kpi_snap_node_ts`` (v3) couvre deja
    ``kpi_snapshots(node_id, timestamp)`` et, cote registre, ``idx_audit_entity``
    / ``idx_audit_week`` existent depuis la v4 - seuls manquent les index
    temporels des tables ``urgency_history`` et ``assessments`` (leurs index v4
    ``idx_urgency_week``/``idx_assessments_week`` ne couvrent que
    ``(node_id, iso_week)``, pas les tris par ``timestamp``) :

    - ``idx_urgency_node_ts`` sur ``urgency_history(node_id, timestamp)`` -
      sert ``urgency_series`` (``WHERE node_id ORDER BY timestamp``) ;
    - ``idx_assessments_node_ts`` sur ``assessments(node_id, timestamp)`` -
      sert ``latest_assessment`` et ``list_assessments``.
    """
    with conn:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_urgency_node_ts
            ON urgency_history(node_id, timestamp)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assessments_node_ts
            ON assessments(node_id, timestamp)
            """
        )
        conn.execute("PRAGMA user_version = 6")


def _client_v7(conn: sqlite3.Connection) -> None:
    """v7 client : journal des interventions (contrat no9, HELIOS v7), idempotent.

    Ajoute la table ``interventions`` : une ligne par intervention decidee sur
    un noeud, de l'ouverture (``etat_avant_json`` - etat OBSERVABLE seulement -
    ``action_id``, ``acteur``, ``objectif_operationnel``, ``decidee_ts``) a la
    cloture (``resultat`` causal, ``etat_apres_json``, ``succes`` derive,
    ``effets_voisins_json``). L'etat de risque (``etat_risque_avant_json`` /
    ``etat_risque_apres_json``) est porte par des colonnes SEPAREES des
    colonnes ``etat_*_json`` : c'est une information d'INTERFACE, jamais le
    label causal du resultat operationnel (voir docs/modele_mathematique.md,
    section 13, et :mod:`supplyscore.services.interventions`). Index
    ``idx_interventions_node_date`` sur ``(node_id, date_ts)``.
    """
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interventions (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                date_ts REAL NOT NULL,
                etat_avant_json TEXT NOT NULL,
                action_id TEXT NOT NULL,
                acteur TEXT NOT NULL,
                objectif_operationnel TEXT NOT NULL,
                decidee_ts REAL NOT NULL,
                executee INTEGER,
                executee_ts REAL,
                date_effet_ts REAL,
                resultat TEXT NOT NULL DEFAULT 'en_cours',
                etat_apres_json TEXT,
                etat_risque_avant_json TEXT NOT NULL,
                etat_risque_apres_json TEXT,
                succes INTEGER,
                effets_voisins_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_interventions_node_date
            ON interventions(node_id, date_ts)
            """
        )
        conn.execute("PRAGMA user_version = 7")


# Registres de migrations

_REGISTRY_MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _registry_v1),
    (2, _registry_v2),
    (3, _registry_v3),
    (4, _registry_v4),
    (5, _registry_v5),
]

_CLIENT_MIGRATIONS: list[tuple[int, MigrationFn]] = [
    (1, _client_v1),
    (2, _client_v2),
    (3, _client_v3),
    (4, _client_v4),
    (5, _client_v5),
    (6, _client_v6),
    (7, _client_v7),
]

_MIGRATIONS_BY_KIND: dict[str, list[tuple[int, MigrationFn]]] = {
    "registry": _REGISTRY_MIGRATIONS,
    "client": _CLIENT_MIGRATIONS,
}


def schema_version(conn: sqlite3.Connection) -> int:
    """Retourne la version de schema courante (``PRAGMA user_version``)."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def apply_migrations(conn: sqlite3.Connection, kind: Literal["registry", "client"]) -> int:
    """Applique les migrations manquantes de la base ``kind`` et retourne sa version.

    Args:
        conn: connexion SQLite ouverte sur la base a migrer.
        kind: ``"registry"`` (registre global) ou ``"client"`` (base par client).

    Returns:
        La version finale du schema (``PRAGMA user_version``) apres migration.
    """
    migrations = _MIGRATIONS_BY_KIND[kind]
    current = schema_version(conn)
    for version, migrate in migrations:
        if version > current:
            migrate(conn)
            current = version
    return current
