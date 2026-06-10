"""Persistance SQLite de supplyscore.

Principe métier : CHAQUE CLIENT (nœud, quel que soit son rang) possède sa
propre base de données (:class:`ClientDatabase`, fichier ``<client_id>.sqlite``)
qui contient ses évaluations AHP hebdomadaires, ses snapshots KPI et son
historique d'urgence. Le graphe (projets, nœuds, arcs) est partagé et vit dans
le registre global (:class:`RegistryDatabase`, fichier ``registry.sqlite``).

Toutes les requêtes sont paramétrées par "?" — aucun SQL construit par f-string.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import threading
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

from supplyscore.data.migrations import apply_migrations
from supplyscore.domain.models import (
    AHPAssessment,
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

# --- Sérialisation KPIBundle <-> JSON ----------------------------------------

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
    """Sérialise un :class:`KPIBundle` en JSON.

    ``dataclasses.asdict`` n'embarque que les champs déclarés : les propriétés
    calculées (``oee``, ``total_g_h``, ``remaining_*``...) ne sont PAS
    sérialisées et se recalculent à la reconstruction.
    """
    return json.dumps(dataclasses.asdict(kpis), sort_keys=True)


def kpis_from_json(payload: str | None) -> KPIBundle:
    """Reconstruit un :class:`KPIBundle` depuis son JSON (tolère None/vide).

    Robuste à l'évolution de schéma : les clés inconnues d'un bloc (champs
    ajoutés par une version plus récente, ou retirés depuis) sont ignorées.
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
    """dict[tuple[int, int], float] -> JSON avec clés "i-j"."""
    return json.dumps(
        {f"{i}-{j}": value for (i, j), value in comparisons.items()},
        sort_keys=True,
    )


def _comparisons_from_json(payload: str | None) -> dict[tuple[int, int], float]:
    """JSON avec clés "i-j" -> dict[tuple[int, int], float]."""
    if not payload:
        return {}
    raw: dict[str, float] = json.loads(payload)
    result: dict[tuple[int, int], float] = {}
    for key, value in raw.items():
        i_str, j_str = key.split("-", 1)
        result[(int(i_str), int(j_str))] = float(value)
    return result


# --- Base commune --------------------------------------------------------------


class _SQLiteDatabase:
    """Connexion SQLite avec WAL, migrations, verrou et context manager.

    La connexion est ouverte avec ``check_same_thread=False`` : le serveur web
    sert chaque requête dans un thread distinct. En contrepartie, CHAQUE
    méthode publique (lecture comme écriture) doit prendre ``self._lock``
    (un :class:`threading.RLock` par instance, donc réentrant).
    """

    #: famille de migrations à appliquer (surclassé : "registry" ou "client").
    MIGRATION_KIND: Literal["registry", "client"]

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self.schema_version = apply_migrations(self._conn, self.MIGRATION_KIND)
        # Les contraintes FK du schéma (v2) restent vérifiables à la demande via
        # PRAGMA foreign_key_check, mais leur APPLICATION est laissée désactivée
        # sur la connexion : les appelants historiques insèrent "enfant avant
        # parent" (nœud avant son projet, arc avant ses nœuds).
        self._conn.execute("PRAGMA foreign_keys=OFF")

    # -- context manager --
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


# --- Registre global -----------------------------------------------------------


class RegistryDatabase(_SQLiteDatabase):
    """Registre global partagé : projets, nœuds et arcs du graphe logistique.

    Fichier : ``db_dir/registry.sqlite``. Les évaluations restent par client
    (voir :class:`ClientDatabase`).
    """

    FILENAME = "registry.sqlite"
    MIGRATION_KIND: Literal["registry", "client"] = "registry"

    def __init__(self, db_dir: Path) -> None:
        """Ouvre (ou crée) le fichier ``registry.sqlite`` dans ``db_dir``."""
        super().__init__(Path(db_dir) / self.FILENAME)

    # -- projets --

    def save_project(self, project: Project) -> None:
        """Insère ou met à jour le projet (upsert sur son id)."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO projects (id, name, owner_node_id, description, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    owner_node_id = excluded.owner_node_id,
                    description = excluded.description,
                    created_at = excluded.created_at
                """,
                (
                    project.id,
                    project.name,
                    project.owner_node_id,
                    project.description,
                    project.created_at,
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
        """Liste tous les projets, ordonnés par date de création."""
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
        )

    # -- nœuds --

    def save_node(self, node: SupplyNode) -> None:
        """Insère ou met à jour le nœud ET son état d'urgence (upsert sur son id)."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO nodes (id, name, label, kind, rank, project_id,
                                   location, latitude, longitude, status, kpis_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    kpis_json = excluded.kpis_json
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
                ),
            )
            self._upsert_urgency(node.id, node.urgency)

    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le nœud (urgence incluse) ou None s'il est inconnu."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return self._row_to_node(row) if row else None

    def list_nodes(self, project_id: str | None = None) -> list[SupplyNode]:
        """Liste les nœuds (filtrés par projet si ``project_id`` est fourni)."""
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
        """Supprime un nœud, son état d'urgence ET tous les arcs qui le touchent."""
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM arcs WHERE source_id = ? OR target_id = ?",
                (node_id, node_id),
            )
            self._conn.execute("DELETE FROM node_urgency WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

    def set_node_status(self, node_id: str, status: TaskStatus | str) -> None:
        """Met à jour le statut du nœud (valide la valeur via :class:`TaskStatus`)."""
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
        )

    # -- état d'urgence courant --

    def save_urgency(self, node_id: str, state: UrgencyState) -> None:
        """Insère ou met à jour l'état d'urgence courant du nœud (table node_urgency)."""
        with self._lock, self._conn:
            self._upsert_urgency(node_id, state)

    def _upsert_urgency(self, node_id: str, state: UrgencyState) -> None:
        """Upsert SQL de node_urgency (appelant responsable du verrou/transaction)."""
        self._conn.execute(
            """
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
            """,
            (
                node_id,
                state.ud_local,
                state.ur_local,
                state.ud,
                state.ur,
                state.adequation,
                state.false_urgency,
                state.hidden_risk,
                state.timestamp,
            ),
        )

    def _load_urgency(self, node_id: str) -> UrgencyState:
        """Restaure l'UrgencyState du nœud (UrgencyState() vierge si absent)."""
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

    # -- réglages par projet --

    def set_setting(self, project_id: str, key: str, value: Any) -> None:
        """Pose (ou remplace) un réglage du projet, sérialisé en JSON."""
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
        """Retourne la valeur du réglage (désérialisée du JSON) ou None si absent."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM project_settings WHERE project_id = ? AND key = ?",
                (project_id, key),
            ).fetchone()
            return json.loads(row["value_json"]) if row else None

    # -- arcs --

    def save_arc(self, arc: SupplyArc) -> None:
        """Insère ou met à jour l'arc (upsert sur (source_id, target_id))."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO arcs (source_id, target_id, label, gamma, beta, delta, kpis_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id) DO UPDATE SET
                    label = excluded.label,
                    gamma = excluded.gamma,
                    beta = excluded.beta,
                    delta = excluded.delta,
                    kpis_json = excluded.kpis_json
                """,
                (
                    arc.source_id,
                    arc.target_id,
                    arc.label,
                    arc.gamma,
                    arc.beta,
                    arc.delta,
                    kpis_to_json(arc.kpis),
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
        """Liste tous les arcs, ordonnés par (source_id, target_id)."""
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
            kpis=kpis_from_json(row["kpis_json"]),
        )


# --- Base par client -------------------------------------------------------------


class ClientDatabase(_SQLiteDatabase):
    """Base de données privée d'un client (un fichier sqlite par nœud).

    Contient l'historique hebdomadaire des questionnaires AHP, les snapshots
    KPI et la série temporelle des états d'urgence du nœud.
    """

    MIGRATION_KIND: Literal["registry", "client"] = "client"

    def __init__(self, db_dir: Path, client_id: str) -> None:
        """Ouvre (ou crée) le fichier ``<client_id>.sqlite`` dans ``db_dir``."""
        self.client_id = client_id
        super().__init__(Path(db_dir) / f"{client_id}.sqlite")

    # -- évaluations AHP --

    def save_assessment(self, assessment: AHPAssessment) -> int:
        """Insère l'évaluation AHP et retourne son rowid."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO assessments (node_id, project_id, operator_id,
                                         comparisons_json, criteria_scores_json,
                                         weights_json, consistency_ratio,
                                         is_consistent, ud, notes, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            rowid = cursor.lastrowid
            assert rowid is not None  # INSERT abouti : lastrowid est défini
            return int(rowid)

    def latest_assessment(self, node_id: str) -> AHPAssessment | None:
        """Retourne l'évaluation la plus récente du nœud, ou None."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM assessments WHERE node_id = ?
                ORDER BY timestamp DESC, id DESC LIMIT 1
                """,
                (node_id,),
            ).fetchone()
            return self._row_to_assessment(row) if row else None

    def list_assessments(self, node_id: str) -> list[AHPAssessment]:
        """Liste les évaluations du nœud, par timestamp croissant."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM assessments WHERE node_id = ?
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
        )

    # -- snapshots KPI --

    def save_kpi_snapshot(
        self, node_id: str, kpis: KPIBundle, timestamp: float | None = None
    ) -> int:
        """Insère un snapshot KPI (timestamp = maintenant si None) et retourne son rowid."""
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
            assert rowid is not None  # INSERT abouti : lastrowid est défini
            return int(rowid)

    # -- historique d'urgence --

    def save_urgency_state(self, node_id: str, state: UrgencyState) -> int:
        """Insère un état d'urgence dans l'historique et retourne son rowid."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO urgency_history (node_id, ud_local, ur_local, ud, ur,
                                             adequation, false_urgency, hidden_risk,
                                             timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    state.ud_local,
                    state.ur_local,
                    state.ud,
                    state.ur,
                    state.adequation,
                    state.false_urgency,
                    state.hidden_risk,
                    state.timestamp,
                ),
            )
            rowid = cursor.lastrowid
            assert rowid is not None  # INSERT abouti : lastrowid est défini
            return int(rowid)

    def urgency_series(self, node_id: str) -> list[UrgencyState]:
        """Série temporelle des états d'urgence, ordonnée par timestamp croissant."""
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
