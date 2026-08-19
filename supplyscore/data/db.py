"""Persistance SQLite de supplyscore.

Principe metier : CHAQUE CLIENT (noeud, quel que soit son rang) possede sa
propre base de donnees (:class:`ClientDatabase`, fichier ``<client_id>.sqlite``)
qui contient ses evaluations AHP hebdomadaires, ses snapshots KPI et son
historique d'urgence. Le graphe (projets, noeuds, arcs) est partage et vit dans
le registre global (:class:`RegistryDatabase`, fichier ``registry.sqlite``).

Toutes les requetes sont parametrees par "?" - aucun SQL construit par f-string.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

from supplyscore.core.clock import iso_week as _ts_iso_week
from supplyscore.data.migrations import apply_migrations
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import (
    AHPAssessment,
    ArcKind,
    CO2KPIs,
    CostKPIs,
    InventoryKPIs,
    KPIBundle,
    NetworkKPIs,
    NodeKind,
    OEEKPIs,
    Project,
    RiskKPIs,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    TimeKPIs,
    UrgencyState,
)
from supplyscore.domain.tags import Tag, TagCategory

# Serialisation KPIBundle <-> JSON

_KPI_BLOCK_TYPES: dict[str, type] = {
    "network": NetworkKPIs,
    "inventory": InventoryKPIs,
    "time": TimeKPIs,
    "cost": CostKPIs,
    "co2": CO2KPIs,
    "oee": OEEKPIs,
    "risk": RiskKPIs,
}


def kpis_to_json(kpis: KPIBundle) -> str:
    """Serialise un :class:`KPIBundle` en JSON.

    ``dataclasses.asdict`` n'embarque que les champs declares : les proprietes
    calculees (``oee``, ``total_g_h``, ``remaining_*``...) ne sont PAS
    serialisees et se recalculent a la reconstruction.
    """
    return json.dumps(dataclasses.asdict(kpis), sort_keys=True)


def kpis_from_json(payload: str | None) -> KPIBundle:
    """Reconstruit un :class:`KPIBundle` depuis son JSON (tolere None/vide).

    Robuste a l'evolution de schema : les cles inconnues d'un bloc (champs
    ajoutes par une version plus recente, ou retires depuis) sont ignorees.
    """
    if not payload:
        return KPIBundle()
    raw: dict[str, Any] = json.loads(payload)
    blocks: dict[str, Any] = {}
    for name, cls in _KPI_BLOCK_TYPES.items():
        block_raw: dict[str, Any] = raw.get(name, {})
        known = {f.name for f in dataclasses.fields(cls)}
        blocks[name] = cls(**{k: v for k, v in block_raw.items() if k in known})
    return KPIBundle(**blocks)


def _comparisons_to_json(comparisons: dict[tuple[int, int], float]) -> str:
    """dict[tuple[int, int], float] -> JSON avec cles "i-j"."""
    return json.dumps(
        {f"{i}-{j}": value for (i, j), value in comparisons.items()},
        sort_keys=True,
    )


def _comparisons_from_json(payload: str | None) -> dict[tuple[int, int], float]:
    """JSON avec cles "i-j" -> dict[tuple[int, int], float]."""
    if not payload:
        return {}
    raw: dict[str, float] = json.loads(payload)
    result: dict[tuple[int, int], float] = {}
    for key, value in raw.items():
        i_str, j_str = key.split("-", 1)
        result[(int(i_str), int(j_str))] = float(value)
    return result


# Base commune


class _SQLiteDatabase:
    """Connexion SQLite avec WAL, migrations, verrou et context manager.

    La connexion est ouverte avec ``check_same_thread=False`` : le serveur web
    sert chaque requete dans un thread distinct. En contrepartie, CHAQUE
    methode publique (lecture comme ecriture) doit prendre ``self._lock``
    (un :class:`threading.RLock` par instance, donc reentrant).
    """

    #: famille de migrations a appliquer (surclasse : "registry" ou "client").
    MIGRATION_KIND: Literal["registry", "client"]

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        # COMPROMIS DOCUMENTE (faiblesse #14) : avec le journal WAL, synchronous=NORMAL ne force le fsync qu'au CHECKPOINT (plus a chaque COMMIT) - gain massif en ecriture. En cas de coupure brutale, les dernieres transactions commitees depuis le dernier checkpoint peuvent etre perdues (durabilite au niveau du checkpoint), mais l'INTEGRITE de la base reste garantie par le WAL (jamais de corruption, atomicite conservee) ; :meth:`close` checkpointe explicitement a la fermeture.
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.schema_version = apply_migrations(self._conn, self.MIGRATION_KIND)
        # Les contraintes FK du schema (v2) restent verifiables a la demande via PRAGMA foreign_key_check, mais leur APPLICATION est laissee desactivee sur la connexion : les appelants historiques inserent "enfant avant parent" (noeud avant son projet, arc avant ses noeuds).
        self._conn.execute("PRAGMA foreign_keys=OFF")

    # acces partages (couches data)

    @property
    def conn(self) -> sqlite3.Connection:
        """Connexion SQLite de l'instance - reserve aux couches data (AuditTrail).

        Permet a un ``AuditTrail`` externe de journaliser dans la MEME base que
        l'instance, en se placant sous le MEME verrou (voir :attr:`lock`).
        """
        return self._conn

    @property
    def lock(self) -> threading.RLock:
        """Verrou reentrant de l'instance - reserve aux couches data (AuditTrail).

        Toute utilisation de :attr:`conn` hors de cette classe doit se faire
        sous ce verrou (``with db.lock: ...``), comme les methodes publiques.
        """
        return self._lock

    # context manager
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Commit, checkpoint WAL (purge des fichiers -wal/-shm) puis fermeture."""
        with self._lock:
            if self._conn is not None:
                self._conn.commit()
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.close()
                self._conn = None  # type: ignore[assignment]


# Registre global


class RegistryDatabase(_SQLiteDatabase):
    """Registre global partage : projets, noeuds et arcs du graphe logistique.

    Fichier : ``db_dir/registry.sqlite``. Les evaluations restent par client
    (voir :class:`ClientDatabase`).
    """

    FILENAME = "registry.sqlite"
    MIGRATION_KIND: Literal["registry", "client"] = "registry"

    def __init__(self, db_dir: Path) -> None:
        """Ouvre (ou cree) le fichier ``registry.sqlite`` dans ``db_dir``."""
        super().__init__(Path(db_dir) / self.FILENAME)

    # projets

    def save_project(self, project: Project) -> None:
        """Insere ou met a jour le projet (upsert sur son id)."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO projects (id, name, owner_node_id, description, created_at, t0_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    owner_node_id = excluded.owner_node_id,
                    description = excluded.description,
                    created_at = excluded.created_at,
                    t0_ts = excluded.t0_ts
                """,
                (
                    project.id,
                    project.name,
                    project.owner_node_id,
                    project.description,
                    project.created_at,
                    project.t0_ts,
                ),
            )

    def get_project(self, project_id: str) -> Project | None:
        """Retourne le projet ou None s'il est inconnu."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            return self._row_to_project(row) if row else None

    def list_projects(self) -> list[Project]:
        """Liste tous les projets, ordonnes par date de creation."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
            return [self._row_to_project(row) for row in rows]

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            owner_node_id=row["owner_node_id"],
            description=row["description"],
            created_at=row["created_at"],
            t0_ts=row["t0_ts"],
        )

    # noeuds

    def save_node(self, node: SupplyNode) -> None:
        """Insere ou met a jour le noeud, son etat d'urgence ET ses liens de tags.

        La table ``node_tags`` est resynchronisee sur ``node.tags`` (DELETE des
        liens du noeud puis INSERT des ids) dans la MEME transaction que l'upsert.
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO nodes (id, name, label, kind, rank, project_id,
                                   location, latitude, longitude, status, kpis_json,
                                   onboarding_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    label = excluded.label,
                    kind = excluded.kind,
                    rank = excluded.rank,
                    project_id = excluded.project_id,
                    location = excluded.location,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    status = excluded.status,
                    kpis_json = excluded.kpis_json,
                    onboarding_state = excluded.onboarding_state
                """,
                (
                    node.id,
                    node.name,
                    node.label,
                    str(node.kind),
                    node.rank,
                    node.project_id,
                    node.location,
                    node.latitude,
                    node.longitude,
                    str(node.status),
                    kpis_to_json(node.kpis),
                    node.onboarding_state,
                ),
            )
            self._upsert_urgency(node.id, node.urgency)
            self._sync_node_tags(node.id, node.tags)

    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le noeud (urgence incluse) ou None s'il est inconnu."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return self._row_to_node(row) if row else None

    def list_nodes(self, project_id: str | None = None) -> list[SupplyNode]:
        """Liste les noeuds (filtres par projet si ``project_id`` est fourni)."""
        with self._lock:
            if project_id is None:
                rows = self._conn.execute("SELECT * FROM nodes ORDER BY rank, id").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM nodes WHERE project_id = ? ORDER BY rank, id",
                    (project_id,),
                ).fetchall()
            return [self._row_to_node(row) for row in rows]

    def delete_node(self, node_id: str) -> None:
        """Supprime un noeud et tout ce qui s'y rattache (arcs, urgence, jalons, tags...).

        Les FK ``ON DELETE CASCADE`` du schema ne sont pas APPLIQUEES sur cette
        connexion (``PRAGMA foreign_keys=OFF``, cf. ``__init__``) : les cascades
        vers ``node_tags``, ``milestones`` et ``onboarding_progress`` sont donc
        executees explicitement, dans la meme transaction.
        """
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM arcs WHERE source_id = ? OR target_id = ?",
                (node_id, node_id),
            )
            self._conn.execute("DELETE FROM node_urgency WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM node_tags WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM milestones WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM onboarding_progress WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

    def set_node_status(self, node_id: str, status: TaskStatus | str) -> None:
        """Met a jour le statut du noeud (valide la valeur via :class:`TaskStatus`)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE nodes SET status = ? WHERE id = ?",
                (str(TaskStatus(status)), node_id),
            )

    def _row_to_node(self, row: sqlite3.Row) -> SupplyNode:
        return SupplyNode(
            id=row["id"],
            name=row["name"],
            label=row["label"],
            kind=NodeKind(row["kind"]),
            rank=row["rank"],
            project_id=row["project_id"],
            location=row["location"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            status=TaskStatus(row["status"]),
            kpis=kpis_from_json(row["kpis_json"]),
            urgency=self._load_urgency(row["id"]),
            tags=self._node_tag_ids(row["id"]),
            onboarding_state=row["onboarding_state"],
        )

    # etat d'urgence courant

    #: upsert de node_urgency, partage par le chemin unitaire et le chemin par lot.
    _URGENCY_UPSERT_SQL = """
        INSERT INTO node_urgency (node_id, ud_local, ur_local, ud, ur,
                                  adequation, false_urgency, hidden_risk, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
            ud_local = excluded.ud_local,
            ur_local = excluded.ur_local,
            ud = excluded.ud,
            ur = excluded.ur,
            adequation = excluded.adequation,
            false_urgency = excluded.false_urgency,
            hidden_risk = excluded.hidden_risk,
            timestamp = excluded.timestamp
        """

    @staticmethod
    def _urgency_row(node_id: str, state: UrgencyState) -> tuple[str | float | None, ...]:
        """Ligne de parametres de :data:`_URGENCY_UPSERT_SQL` pour un noeud."""
        return (
            node_id,
            state.ud_local,
            state.ur_local,
            state.ud,
            state.ur,
            state.adequation,
            state.false_urgency,
            state.hidden_risk,
            state.timestamp,
        )

    def save_urgency(self, node_id: str, state: UrgencyState) -> None:
        """Insere ou met a jour l'etat d'urgence courant du noeud (table node_urgency)."""
        with self._lock, self._conn:
            self._upsert_urgency(node_id, state)

    def save_urgencies(self, states: dict[str, UrgencyState]) -> None:
        """Upsert PAR LOT des etats d'urgence courants, en UNE transaction.

        Equivalent champ a champ a N appels :meth:`save_urgency`, mais en un
        seul ``executemany`` sous le verrou : une transaction (un seul couple
        BEGIN/COMMIT) pour tout le reseau au lieu d'une par noeud
        (faiblesse #14 - O(N) commits dans ``evaluate_all``).

        Args:
            states: etats d'urgence courants par id de noeud.
        """
        with self._lock, self._conn:
            self._conn.executemany(
                self._URGENCY_UPSERT_SQL,
                [self._urgency_row(node_id, state) for node_id, state in states.items()],
            )

    def _upsert_urgency(self, node_id: str, state: UrgencyState) -> None:
        """Upsert SQL de node_urgency (appelant responsable du verrou/transaction)."""
        self._conn.execute(self._URGENCY_UPSERT_SQL, self._urgency_row(node_id, state))

    def _load_urgency(self, node_id: str) -> UrgencyState:
        """Restaure l'UrgencyState du noeud (UrgencyState() vierge si absent)."""
        row = self._conn.execute(
            "SELECT * FROM node_urgency WHERE node_id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return UrgencyState()
        state = UrgencyState(
            ud_local=row["ud_local"],
            ur_local=row["ur_local"],
            ud=row["ud"],
            ur=row["ur"],
            adequation=row["adequation"],
            false_urgency=row["false_urgency"],
            hidden_risk=row["hidden_risk"],
        )
        if row["timestamp"] is not None:
            state.timestamp = row["timestamp"]
        return state

    # reglages par projet

    def set_setting(self, project_id: str, key: str, value: Any) -> None:
        """Pose (ou remplace) un reglage du projet, serialise en JSON."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO project_settings (project_id, key, value_json)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id, key) DO UPDATE SET
                    value_json = excluded.value_json
                """,
                (project_id, key, json.dumps(value, sort_keys=True)),
            )

    def get_setting(self, project_id: str, key: str) -> Any | None:
        """Retourne la valeur du reglage (deserialisee du JSON) ou None si absent."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM project_settings WHERE project_id = ? AND key = ?",
                (project_id, key),
            ).fetchone()
            return json.loads(row["value_json"]) if row else None

    # arcs

    def save_arc(self, arc: SupplyArc) -> None:
        """Insere ou met a jour l'arc (upsert sur (source_id, target_id))."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO arcs (source_id, target_id, label, gamma, beta, delta,
                                  kpis_json, arc_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id) DO UPDATE SET
                    label = excluded.label,
                    gamma = excluded.gamma,
                    beta = excluded.beta,
                    delta = excluded.delta,
                    kpis_json = excluded.kpis_json,
                    arc_kind = excluded.arc_kind
                """,
                (
                    arc.source_id,
                    arc.target_id,
                    arc.label,
                    arc.gamma,
                    arc.beta,
                    arc.delta,
                    kpis_to_json(arc.kpis),
                    str(arc.kind_arc),
                ),
            )

    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc source -> target ou None s'il est inconnu."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM arcs WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            ).fetchone()
            return self._row_to_arc(row) if row else None

    def list_arcs(self) -> list[SupplyArc]:
        """Liste tous les arcs, ordonnes par (source_id, target_id)."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM arcs ORDER BY source_id, target_id").fetchall()
            return [self._row_to_arc(row) for row in rows]

    def delete_arc(self, source_id: str, target_id: str) -> None:
        """Supprime l'arc source -> target (silencieux s'il est absent)."""
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM arcs WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            )

    @staticmethod
    def _row_to_arc(row: sqlite3.Row) -> SupplyArc:
        return SupplyArc(
            source_id=row["source_id"],
            target_id=row["target_id"],
            label=row["label"],
            gamma=row["gamma"],
            beta=row["beta"],
            delta=row["delta"],
            kind_arc=ArcKind(row["arc_kind"]),
            kpis=kpis_from_json(row["kpis_json"]),
        )

    # jalons (milestones)

    def save_milestone(self, milestone: Milestone) -> None:
        """Insere ou met a jour le jalon (upsert sur son id).

        ``created_at``/``updated_at`` sont geres ici : poses tous deux a
        maintenant a l'insertion, seul ``updated_at`` bouge a la mise a jour.
        """
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO milestones (id, node_id, name, kind, start_ts, deadline_ts,
                                        status, progress, position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    node_id = excluded.node_id,
                    name = excluded.name,
                    kind = excluded.kind,
                    start_ts = excluded.start_ts,
                    deadline_ts = excluded.deadline_ts,
                    status = excluded.status,
                    progress = excluded.progress,
                    position = excluded.position,
                    updated_at = excluded.updated_at
                """,
                (
                    milestone.id,
                    milestone.node_id,
                    milestone.name,
                    milestone.kind,
                    milestone.start_ts,
                    milestone.deadline_ts,
                    str(milestone.status),
                    milestone.progress,
                    milestone.position,
                    now,
                    now,
                ),
            )

    def get_milestone(self, milestone_id: str) -> Milestone | None:
        """Retourne le jalon ou None s'il est inconnu."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM milestones WHERE id = ?", (milestone_id,)
            ).fetchone()
            return self._row_to_milestone(row) if row else None

    def list_milestones(self, node_id: str) -> list[Milestone]:
        """Liste les jalons du noeud, ordonnes par position croissante."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM milestones WHERE node_id = ? ORDER BY position, id",
                (node_id,),
            ).fetchall()
            return [self._row_to_milestone(row) for row in rows]

    def delete_milestone(self, milestone_id: str) -> None:
        """Supprime le jalon (silencieux s'il est absent)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM milestones WHERE id = ?", (milestone_id,))

    @staticmethod
    def _row_to_milestone(row: sqlite3.Row) -> Milestone:
        return Milestone(
            id=row["id"],
            node_id=row["node_id"],
            name=row["name"],
            kind=row["kind"],
            start_ts=row["start_ts"],
            deadline_ts=row["deadline_ts"],
            status=MilestoneStatus(row["status"]),
            progress=row["progress"],
            position=row["position"],
        )

    # tags et categories

    def save_tag_category(self, category: TagCategory) -> None:
        """Insere ou met a jour la categorie de tags (upsert sur son id)."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO tag_categories (id, project_id, name, color)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id = excluded.project_id,
                    name = excluded.name,
                    color = excluded.color
                """,
                (category.id, category.project_id, category.name, category.color),
            )

    def list_tag_categories(self, project_id: str) -> list[TagCategory]:
        """Liste les categories de tags du projet, ordonnees par nom."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tag_categories WHERE project_id = ? ORDER BY name, id",
                (project_id,),
            ).fetchall()
            return [
                TagCategory(
                    id=row["id"],
                    project_id=row["project_id"],
                    name=row["name"],
                    color=row["color"],
                )
                for row in rows
            ]

    def save_tag(self, tag: Tag) -> None:
        """Insere ou met a jour le tag (upsert sur son id)."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO tags (id, project_id, category_id, name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id = excluded.project_id,
                    category_id = excluded.category_id,
                    name = excluded.name
                """,
                (tag.id, tag.project_id, tag.category_id, tag.name),
            )

    def list_tags(self, project_id: str) -> list[Tag]:
        """Liste les tags du projet, ordonnes par nom."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tags WHERE project_id = ? ORDER BY name, id",
                (project_id,),
            ).fetchall()
            return [self._row_to_tag(row) for row in rows]

    def set_node_tags(self, node_id: str, tag_ids: list[str]) -> None:
        """Remplace les liens de tags du noeud par ``tag_ids`` (transaction unique)."""
        with self._lock, self._conn:
            self._sync_node_tags(node_id, tag_ids)

    def tags_of_node(self, node_id: str) -> list[Tag]:
        """Retourne les tags lies au noeud, dans l'ordre d'association."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT tags.* FROM tags
                JOIN node_tags ON node_tags.tag_id = tags.id
                WHERE node_tags.node_id = ?
                ORDER BY node_tags.rowid
                """,
                (node_id,),
            ).fetchall()
            return [self._row_to_tag(row) for row in rows]

    def _sync_node_tags(self, node_id: str, tag_ids: list[str]) -> None:
        """Resynchronise node_tags (appelant responsable du verrou/transaction)."""
        self._conn.execute("DELETE FROM node_tags WHERE node_id = ?", (node_id,))
        self._conn.executemany(
            "INSERT OR IGNORE INTO node_tags (node_id, tag_id) VALUES (?, ?)",
            [(node_id, tag_id) for tag_id in tag_ids],
        )

    def _node_tag_ids(self, node_id: str) -> list[str]:
        """Ids des tags lies au noeud, dans l'ordre d'association."""
        rows = self._conn.execute(
            "SELECT tag_id FROM node_tags WHERE node_id = ? ORDER BY rowid",
            (node_id,),
        ).fetchall()
        return [row["tag_id"] for row in rows]

    @staticmethod
    def _row_to_tag(row: sqlite3.Row) -> Tag:
        return Tag(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            category_id=row["category_id"],
        )

    # progression d'onboarding

    def save_onboarding(
        self,
        node_id: str,
        sections_done: dict[str, Any],
        draft: dict[str, Any],
        current_step: int,
    ) -> None:
        """Insere ou met a jour la progression du wizard d'onboarding du noeud."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO onboarding_progress (node_id, sections_done_json,
                                                 draft_json, current_step, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    sections_done_json = excluded.sections_done_json,
                    draft_json = excluded.draft_json,
                    current_step = excluded.current_step,
                    updated_at = excluded.updated_at
                """,
                (
                    node_id,
                    json.dumps(sections_done, sort_keys=True),
                    json.dumps(draft, sort_keys=True),
                    current_step,
                    time.time(),
                ),
            )

    def get_onboarding(self, node_id: str) -> dict[str, Any] | None:
        """Retourne {sections_done, draft, current_step, updated_at} ou None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM onboarding_progress WHERE node_id = ?", (node_id,)
            ).fetchone()
            if row is None:
                return None
            return {
                "sections_done": json.loads(row["sections_done_json"]),
                "draft": json.loads(row["draft_json"]),
                "current_step": row["current_step"],
                "updated_at": row["updated_at"],
            }

    def delete_onboarding(self, node_id: str) -> None:
        """Supprime la progression d'onboarding du noeud (silencieux si absente)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM onboarding_progress WHERE node_id = ?", (node_id,))

    # scenarios nommes

    def save_scenario(
        self,
        scenario_id: str,
        project_id: str,
        nom: str,
        payload_json: str,
        now: float,
    ) -> None:
        """Insere ou met a jour le scenario nomme (upsert sur son id).

        Le contenu ``payload_json`` est OPAQUE pour la couche data (aucune
        interpretation), mais sa syntaxe JSON est validee AVANT toute ecriture.
        A l'insertion, ``created_at`` et ``updated_at`` valent ``now`` ; a la
        mise a jour, seul ``updated_at`` est rafraichi (``created_at`` est
        preserve). Le nom est unique PAR projet : un doublon de
        ``(project_id, nom)`` porte par un AUTRE id est refuse.

        Args:
            scenario_id: identifiant du scenario (cle d'upsert).
            project_id: projet auquel le scenario est rattache.
            nom: nom du scenario, unique au sein du projet.
            payload_json: contenu du scenario, deja serialise en JSON.
            now: timestamp courant, fourni par l'appelant (testabilite).

        Raises:
            ValueError: si ``payload_json`` n'est pas du JSON valide, ou si un
                scenario de ce nom existe deja dans le projet sous un autre id.
        """
        try:
            json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"payload_json n'est pas du JSON valide : {exc}") from exc
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    """
                    INSERT INTO scenarios (id, project_id, nom, payload_json,
                                           created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        project_id = excluded.project_id,
                        nom = excluded.nom,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (scenario_id, project_id, nom, payload_json, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"un scénario de ce nom existe déjà dans le projet : {nom!r}"
                ) from exc

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        """Retourne le scenario ou None s'il est inconnu.

        Le dict retourne contient ``id``, ``project_id``, ``nom``, ``payload``
        (deserialise du JSON), ``created_at`` et ``updated_at``.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
            return self._row_to_scenario(row) if row else None

    def list_scenarios(self, project_id: str) -> list[dict[str, Any]]:
        """Liste les scenarios du projet, les plus recemment modifies d'abord.

        Tri par ``updated_at`` decroissant (departage par id pour un ordre
        stable). Meme forme de dict que :meth:`get_scenario`. Servie par
        l'index ``idx_scenarios_project``.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM scenarios WHERE project_id = ?
                ORDER BY updated_at DESC, id
                """,
                (project_id,),
            ).fetchall()
            return [self._row_to_scenario(row) for row in rows]

    def delete_scenario(self, scenario_id: str) -> None:
        """Supprime le scenario (silencieux s'il est absent)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))

    @staticmethod
    def _row_to_scenario(row: sqlite3.Row) -> dict[str, Any]:
        """Ligne SQL -> dict de scenario (payload deserialise du JSON)."""
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "nom": row["nom"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


# Base par client


class ClientDatabase(_SQLiteDatabase):
    """Base de donnees privee d'un client (un fichier sqlite par noeud).

    Contient l'historique hebdomadaire des questionnaires AHP, les snapshots
    KPI et la serie temporelle des etats d'urgence du noeud.
    """

    MIGRATION_KIND: Literal["registry", "client"] = "client"

    def __init__(self, db_dir: Path, client_id: str) -> None:
        """Ouvre (ou cree) le fichier ``<client_id>.sqlite`` dans ``db_dir``."""
        self.client_id = client_id
        super().__init__(Path(db_dir) / f"{client_id}.sqlite")

    # evaluations AHP

    def save_assessment(self, assessment: AHPAssessment, replaces_id: int | None = None) -> int:
        """Insere l'evaluation AHP et retourne son rowid.

        Garde-fou : si ``assessment.iso_week`` est vide, la semaine ISO est
        calculee depuis ``assessment.timestamp`` et POSEE sur l'objet avant
        persistance (l'objet reflete alors exactement la ligne ecrite).

        Args:
            assessment: evaluation AHP a persister.
            replaces_id: id de l'evaluation que celle-ci corrige (NULL =
                evaluation originale). L'evaluation referencee est alors
                exclue de :meth:`latest_assessment`.
        """
        if not assessment.iso_week:
            assessment.iso_week = _ts_iso_week(assessment.timestamp)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO assessments (node_id, project_id, operator_id,
                                         comparisons_json, criteria_scores_json,
                                         weights_json, consistency_ratio,
                                         is_consistent, ud, notes, timestamp,
                                         replaces_id, iso_week)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.node_id,
                    assessment.project_id,
                    assessment.operator_id,
                    _comparisons_to_json(assessment.comparisons),
                    json.dumps(assessment.criteria_scores),
                    json.dumps(assessment.weights),
                    assessment.consistency_ratio,
                    int(assessment.is_consistent),
                    assessment.ud,
                    assessment.notes,
                    assessment.timestamp,
                    replaces_id,
                    assessment.iso_week,
                ),
            )
            rowid = cursor.lastrowid
            assert rowid is not None  # INSERT abouti : lastrowid est defini
            return int(rowid)

    def latest_assessment(self, node_id: str) -> AHPAssessment | None:
        """Retourne l'evaluation EFFECTIVE la plus recente du noeud, ou None.

        Les evaluations remplacees par une correction (id reference par le
        ``replaces_id`` d'une autre ligne) sont exclues, meme si leur
        timestamp est plus recent que celui de la correction.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM assessments
                WHERE node_id = ?
                  AND id NOT IN (SELECT replaces_id FROM assessments
                                 WHERE replaces_id IS NOT NULL)
                ORDER BY timestamp DESC, id DESC LIMIT 1
                """,
                (node_id,),
            ).fetchone()
            return self._row_to_assessment(row) if row else None

    def list_assessments(self, node_id: str, include_replaced: bool = True) -> list[AHPAssessment]:
        """Liste les evaluations du noeud, par timestamp croissant.

        Args:
            node_id: identifiant du noeud.
            include_replaced: si True (defaut), l'historique COMPLET est
                retourne (evaluations remplacees comprises) ; si False, les
                evaluations remplacees par une correction sont exclues.
        """
        with self._lock:
            if include_replaced:
                rows = self._conn.execute(
                    """
                    SELECT * FROM assessments WHERE node_id = ?
                    ORDER BY timestamp, id
                    """,
                    (node_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM assessments
                    WHERE node_id = ?
                      AND id NOT IN (SELECT replaces_id FROM assessments
                                     WHERE replaces_id IS NOT NULL)
                    ORDER BY timestamp, id
                    """,
                    (node_id,),
                ).fetchall()
            return [self._row_to_assessment(row) for row in rows]

    @staticmethod
    def _row_to_assessment(row: sqlite3.Row) -> AHPAssessment:
        return AHPAssessment(
            node_id=row["node_id"],
            project_id=row["project_id"],
            operator_id=row["operator_id"],
            comparisons=_comparisons_from_json(row["comparisons_json"]),
            criteria_scores=list(json.loads(row["criteria_scores_json"])),
            weights=list(json.loads(row["weights_json"])),
            consistency_ratio=row["consistency_ratio"],
            is_consistent=bool(row["is_consistent"]),
            ud=row["ud"],
            notes=row["notes"],
            timestamp=row["timestamp"],
            iso_week=row["iso_week"],
        )

    def assessment_weeks(self, node_id: str) -> list[str]:
        """Semaines ISO distinctes ayant au moins une evaluation, les plus recentes d'abord.

        L'ordre DESC est lexicographique sur les libelles " AAAA-Sxx "
        (zero-paddes), ce qui coincide avec l'ordre chronologique. Les lignes
        sans semaine (``iso_week = ''``, jamais produites par les chemins
        d'ecriture normaux) sont ignorees. Servie par ``idx_assessments_week``.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT DISTINCT iso_week FROM assessments
                WHERE node_id = ? AND iso_week != ''
                ORDER BY iso_week DESC
                """,
                (node_id,),
            ).fetchall()
            return [row["iso_week"] for row in rows]

    def last_assessment_week(self, node_id: str) -> str | None:
        """Semaine ISO de la derniere evaluation du noeud, ou None si aucune.

        " Derniere " au sens du libelle " AAAA-Sxx " maximal (equivalent a la
        semaine de l'evaluation la plus recente).
        """
        weeks = self.assessment_weeks(node_id)
        return weeks[0] if weeks else None

    # snapshots KPI

    def save_kpi_snapshot(
        self, node_id: str, kpis: KPIBundle, timestamp: float | None = None
    ) -> int:
        """Insere un snapshot KPI (timestamp = maintenant si None) et retourne son rowid."""
        import time as _time

        ts = _time.time() if timestamp is None else timestamp
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO kpi_snapshots (node_id, kpis_json, timestamp)
                VALUES (?, ?, ?)
                """,
                (node_id, kpis_to_json(kpis), ts),
            )
            rowid = cursor.lastrowid
            assert rowid is not None  # INSERT abouti : lastrowid est defini
            return int(rowid)

    def kpi_series(self, node_id: str, limite: int = 12) -> list[tuple[float, KPIBundle]]:
        """Les ``limite`` derniers snapshots KPI du noeud, du plus ancien au plus recent.

        Complement de :meth:`kpis_at`, qui ne rend qu'un instantane. Une
        prevision qui veut distinguer un fournisseur STABLE d'un fournisseur
        qui S'ENLISE a besoin de la serie, pas du dernier point : les deux ont
        la meme valeur du jour et des avenirs opposes.

        Args:
            node_id: noeud dont on lit l'historique.
            limite: nombre maximal de snapshots rendus, les plus recents.

        Returns:
            Les couples ``(timestamp, KPIBundle)`` tries chronologiquement.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT kpis_json, timestamp FROM kpi_snapshots
                WHERE node_id = ?
                ORDER BY timestamp DESC, id DESC LIMIT ?
                """,
                (node_id, int(max(limite, 0))),
            ).fetchall()
        return [(float(r["timestamp"]), kpis_from_json(r["kpis_json"])) for r in reversed(rows)]

    def kpis_at(self, node_id: str, t: float) -> KPIBundle | None:
        """Retourne les KPI du noeud tels qu'ils etaient a l'instant ``t``.

        Lecture temporelle : dernier snapshot de ``kpi_snapshots`` dont le
        timestamp est <= ``t`` (borne incluse), deserialise en
        :class:`KPIBundle`. None si aucun snapshot n'existait encore a ``t``.
        Servie par l'index ``idx_kpi_snap_node_ts``.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT kpis_json FROM kpi_snapshots
                WHERE node_id = ? AND timestamp <= ?
                ORDER BY timestamp DESC, id DESC LIMIT 1
                """,
                (node_id, t),
            ).fetchone()
            return kpis_from_json(row["kpis_json"]) if row else None

    # historique d'urgence

    #: insertion dans urgency_history, partagee par le chemin unitaire et le lot.
    _URGENCY_HISTORY_INSERT_SQL = """
        INSERT INTO urgency_history (node_id, ud_local, ur_local, ud, ur,
                                     adequation, false_urgency, hidden_risk,
                                     timestamp, iso_week)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

    @staticmethod
    def _urgency_history_row(node_id: str, state: UrgencyState) -> tuple[str | float | None, ...]:
        """Ligne de parametres de :data:`_URGENCY_HISTORY_INSERT_SQL` pour un etat.

        La semaine ISO (" AAAA-Sxx ") est calculee depuis ``state.timestamp``,
        exactement comme dans le chemin unitaire historique.
        """
        return (
            node_id,
            state.ud_local,
            state.ur_local,
            state.ud,
            state.ur,
            state.adequation,
            state.false_urgency,
            state.hidden_risk,
            state.timestamp,
            _ts_iso_week(state.timestamp),
        )

    def save_urgency_state(self, node_id: str, state: UrgencyState) -> int:
        """Insere un etat d'urgence dans l'historique et retourne son rowid.

        La semaine ISO (" AAAA-Sxx ") est calculee depuis ``state.timestamp``
        et persistee dans la colonne ``iso_week``.
        """
        with self._lock, self._conn:
            cursor = self._conn.execute(
                self._URGENCY_HISTORY_INSERT_SQL,
                self._urgency_history_row(node_id, state),
            )
            rowid = cursor.lastrowid
            assert rowid is not None  # INSERT abouti : lastrowid est defini
            return int(rowid)

    def save_urgency_states(self, rows: list[tuple[str, UrgencyState]]) -> None:
        """Insere un LOT d'etats d'urgence dans l'historique, en UNE transaction.

        Equivalent champ a champ a N appels :meth:`save_urgency_state`
        (``iso_week`` comprise, calculee depuis le timestamp de CHAQUE etat),
        mais en un seul ``executemany`` sous le verrou - une transaction pour
        tout le lot au lieu d'une par etat (faiblesse #14).

        Args:
            rows: couples ``(node_id, etat)`` a journaliser, dans l'ordre.
        """
        with self._lock, self._conn:
            self._conn.executemany(
                self._URGENCY_HISTORY_INSERT_SQL,
                [self._urgency_history_row(node_id, state) for node_id, state in rows],
            )

    def urgency_series(self, node_id: str) -> list[UrgencyState]:
        """Serie temporelle des etats d'urgence, ordonnee par timestamp croissant."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM urgency_history WHERE node_id = ?
                ORDER BY timestamp, id
                """,
                (node_id,),
            ).fetchall()
        return [
            UrgencyState(
                ud_local=row["ud_local"],
                ur_local=row["ur_local"],
                ud=row["ud"],
                ur=row["ur"],
                adequation=row["adequation"],
                false_urgency=row["false_urgency"],
                hidden_risk=row["hidden_risk"],
                timestamp=row["timestamp"],
            )
            for row in rows
        ]

    # cahier des charges versionne (spec_sheet)

    def save_spec_sheet(self, node_id: str, payload_json: str, source: str) -> int:
        """Insere une nouvelle version du cahier des charges et la retourne.

        La version est auto-incrementee par noeud (max existant + 1, en
        commencant a 1) dans la meme transaction que l'INSERT.
        """
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM spec_sheet WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            version = int(row[0]) + 1
            self._conn.execute(
                """
                INSERT INTO spec_sheet (node_id, version, payload_json, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node_id, version, payload_json, source, time.time()),
            )
            return version

    def latest_spec_sheet(self, node_id: str) -> tuple[int, str] | None:
        """Retourne (version, payload_json) de la derniere version, ou None."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT version, payload_json FROM spec_sheet
                WHERE node_id = ? ORDER BY version DESC LIMIT 1
                """,
                (node_id,),
            ).fetchone()
            return (int(row["version"]), row["payload_json"]) if row else None

    def spec_sheet_versions(self, node_id: str) -> list[int]:
        """Liste les versions du cahier des charges du noeud, croissantes."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT version FROM spec_sheet WHERE node_id = ? ORDER BY version",
                (node_id,),
            ).fetchall()
            return [int(row["version"]) for row in rows]

    # journal d'evenements

    def save_event(
        self,
        event_id: str,
        node_id: str,
        event_type: str,
        iso_week: str,
        occurred_at: float,
        params_json: str,
        impacts_json: str,
        operator_id: str,
        notes: str = "",
    ) -> None:
        """Insere un evenement dans le journal (``reverted_at`` initialement NULL)."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO events (id, node_id, event_type, iso_week, occurred_at,
                                    params_json, impacts_json, reverted_at,
                                    operator_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    event_id,
                    node_id,
                    event_type,
                    iso_week,
                    occurred_at,
                    params_json,
                    impacts_json,
                    operator_id,
                    notes,
                ),
            )

    def list_events(self, node_id: str, iso_week: str | None = None) -> list[dict[str, Any]]:
        """Liste les evenements du noeud (filtres par semaine ISO si fournie).

        Chaque evenement est retourne comme dict (cles = colonnes de la table),
        ordonne par ``occurred_at`` croissant.
        """
        with self._lock:
            if iso_week is None:
                rows = self._conn.execute(
                    "SELECT * FROM events WHERE node_id = ? ORDER BY occurred_at, id",
                    (node_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM events WHERE node_id = ? AND iso_week = ?
                    ORDER BY occurred_at, id
                    """,
                    (node_id, iso_week),
                ).fetchall()
            return [dict(row) for row in rows]

    def mark_reverted(self, event_id: str, reverted_at: float) -> None:
        """Marque l'evenement comme annule a la date ``reverted_at``."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE events SET reverted_at = ? WHERE id = ?",
                (reverted_at, event_id),
            )

    # revue hebdomadaire

    def get_weekly_review(self, node_id: str, iso_week: str) -> dict[str, Any] | None:
        """Retourne l'etat de la revue hebdomadaire du noeud pour la semaine, ou None.

        Le dict retourne contient ``volets`` (deserialise du JSON, ex.
        ``{"ahp": 1, "kpis": 0}``), ``started_at`` et ``completed_at``
        (timestamps, ou None tant que non poses).
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT volets_json, started_at, completed_at FROM weekly_reviews
                WHERE node_id = ? AND iso_week = ?
                """,
                (node_id, iso_week),
            ).fetchone()
            if row is None:
                return None
            return {
                "volets": json.loads(row["volets_json"]),
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
            }

    def upsert_weekly_review(
        self,
        node_id: str,
        iso_week: str,
        *,
        volets: dict[str, Any] | None = None,
        started_at: float | None = None,
        completed_at: float | None = None,
    ) -> None:
        """Cree la revue hebdomadaire au besoin et ne touche QUE les champs fournis.

        Semantique champ a champ (transaction unique, sous le verrou) :

        - ``volets`` est FUSIONNE cle a cle avec l'existant (les volets non
          mentionnes sont conserves, ceux fournis sont ecrases) ;
        - ``started_at`` n'est pose que s'il est encore NULL en base (premier
          demarrage de la revue - les appels suivants ne l'ecrasent pas) ;
        - ``completed_at`` est ecrase chaque fois qu'il est fourni.
        """
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO weekly_reviews (node_id, iso_week) VALUES (?, ?)",
                (node_id, iso_week),
            )
            if volets is not None:
                row = self._conn.execute(
                    "SELECT volets_json FROM weekly_reviews WHERE node_id = ? AND iso_week = ?",
                    (node_id, iso_week),
                ).fetchone()
                merged: dict[str, Any] = json.loads(row["volets_json"])
                merged.update(volets)
                self._conn.execute(
                    """
                    UPDATE weekly_reviews SET volets_json = ?
                    WHERE node_id = ? AND iso_week = ?
                    """,
                    (json.dumps(merged, sort_keys=True), node_id, iso_week),
                )
            if started_at is not None:
                self._conn.execute(
                    """
                    UPDATE weekly_reviews SET started_at = ?
                    WHERE node_id = ? AND iso_week = ? AND started_at IS NULL
                    """,
                    (started_at, node_id, iso_week),
                )
            if completed_at is not None:
                self._conn.execute(
                    """
                    UPDATE weekly_reviews SET completed_at = ?
                    WHERE node_id = ? AND iso_week = ?
                    """,
                    (completed_at, node_id, iso_week),
                )

    # journal des decisions

    def save_decision(
        self,
        decision_id: str,
        node_id: str,
        iso_week: str,
        operator_id: str,
        description: str,
        scores_snapshot_json: str,
        created_at: float,
    ) -> None:
        """Insere une decision dans le journal.

        ``scores_snapshot_json`` est le snapshot JSON des scores
        ``{ud, ur, a, f, h}`` au moment de la decision, fourni deja serialise
        par l'appelant et stocke tel quel.
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO decisions (id, node_id, iso_week, operator_id,
                                       description, scores_snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    node_id,
                    iso_week,
                    operator_id,
                    description,
                    scores_snapshot_json,
                    created_at,
                ),
            )

    def list_decisions(self, node_id: str, iso_week: str | None = None) -> list[dict[str, Any]]:
        """Liste les decisions du noeud (filtrees par semaine ISO si fournie).

        Chaque decision est un dict : ``id``, ``node_id``, ``iso_week``,
        ``operator_id``, ``description``, ``scores`` (snapshot deserialise) et
        ``created_at``. Tri par ``created_at`` decroissant (les plus recentes
        d'abord). Servie par l'index ``idx_decisions_node_week``.
        """
        with self._lock:
            if iso_week is None:
                rows = self._conn.execute(
                    """
                    SELECT * FROM decisions WHERE node_id = ?
                    ORDER BY created_at DESC, id
                    """,
                    (node_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM decisions WHERE node_id = ? AND iso_week = ?
                    ORDER BY created_at DESC, id
                    """,
                    (node_id, iso_week),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "node_id": row["node_id"],
                    "iso_week": row["iso_week"],
                    "operator_id": row["operator_id"],
                    "description": row["description"],
                    "scores": json.loads(row["scores_snapshot_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    # journal des interventions (contrat no9, HELIOS v7)

    #: colonnes de la table ``interventions``, dans l'ordre du contrat no9.
    _INTERVENTION_COLUMNS: tuple[str, ...] = (
        "id",
        "node_id",
        "date_ts",
        "etat_avant_json",
        "action_id",
        "acteur",
        "objectif_operationnel",
        "decidee_ts",
        "executee",
        "executee_ts",
        "date_effet_ts",
        "resultat",
        "etat_apres_json",
        "etat_risque_avant_json",
        "etat_risque_apres_json",
        "succes",
        "effets_voisins_json",
        "notes",
    )

    #: colonnes modifiables par :meth:`update_intervention` (tout sauf ``id``, la cle d'identite de la ligne) - sert de liste blanche : les noms de colonnes de ``changes`` sont interpoles dans le SQL (impossible de les parametrer avec " ? "), donc valides contre cet ensemble fixe avant toute construction de requete.
    _INTERVENTION_UPDATABLE_COLUMNS: frozenset[str] = frozenset(_INTERVENTION_COLUMNS) - {"id"}

    def insert_intervention(self, row: dict[str, Any]) -> str:
        """Insere une ligne du journal des interventions et retourne son id.

        ``row`` porte EXACTEMENT les colonnes de la table (voir
        :data:`_INTERVENTION_COLUMNS`), les champs ``*_json`` deja serialises
        par l'appelant - la couche data reste opaque a leur contenu, comme
        pour ``scenarios`` (:meth:`RegistryDatabase.save_scenario`).

        Args:
            row: valeurs de la ligne a inserer, indexees par nom de colonne.

        Returns:
            L'id de la ligne inseree (``row["id"]``).
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO interventions (
                    id, node_id, date_ts, etat_avant_json, action_id, acteur,
                    objectif_operationnel, decidee_ts, executee, executee_ts,
                    date_effet_ts, resultat, etat_apres_json,
                    etat_risque_avant_json, etat_risque_apres_json, succes,
                    effets_voisins_json, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(row[col] for col in self._INTERVENTION_COLUMNS),
            )
        return str(row["id"])

    def update_intervention(self, intervention_id: str, changes: dict[str, Any]) -> None:
        """Met a jour PARTIELLEMENT la ligne (seules les colonnes de ``changes``).

        Args:
            intervention_id: id de la ligne a modifier.
            changes: valeurs a ecraser, indexees par nom de colonne - doit
                etre un sous-ensemble non vide des colonnes modifiables de la
                table (:data:`_INTERVENTION_UPDATABLE_COLUMNS`).

        Raises:
            ValueError: ``changes`` est vide, ou contient une cle qui n'est
                pas une colonne modifiable de la table ``interventions``.
        """
        if not changes:
            raise ValueError("update_intervention : 'changes' ne peut pas être vide.")
        inconnues = sorted(set(changes) - self._INTERVENTION_UPDATABLE_COLUMNS)
        if inconnues:
            raise ValueError(f"update_intervention : colonnes inconnues {inconnues}")
        colonnes = sorted(changes)  # ordre deterministe
        assignation = ", ".join(f"{col} = ?" for col in colonnes)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE interventions SET {assignation} WHERE id = ?",
                (*(changes[col] for col in colonnes), intervention_id),
            )

    def list_interventions(self, node_id: str, only_open: bool = False) -> list[dict[str, Any]]:
        """Liste les interventions du noeud, ordonnees par ``date_ts`` croissant.

        Args:
            node_id: identifiant du noeud.
            only_open: si True, ne retourne que les interventions dont le
                resultat operationnel est encore ``'en_cours'``.

        Returns:
            Chaque intervention comme dict (cles = colonnes de la table).
        """
        with self._lock:
            if only_open:
                rows = self._conn.execute(
                    """
                    SELECT * FROM interventions
                    WHERE node_id = ? AND resultat = 'en_cours'
                    ORDER BY date_ts, id
                    """,
                    (node_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM interventions WHERE node_id = ? ORDER BY date_ts, id",
                    (node_id,),
                ).fetchall()
            return [dict(row) for row in rows]
