"""Vue « données brutes » type administrateur (phase E10, Lot 10.5).

:class:`RawTableService` expose les tables SQLite du registre et des bases
client en lecture paginée et en édition cellule par cellule, sous garde-fous
stricts :

- **Liste blanche d'édition** (:attr:`RawTableService.EDITABLE_TABLES`) :
  seules les tables métier qui y figurent acceptent une écriture ;
- **Tables d'historique inéditables par construction**
  (:attr:`RawTableService.FORBIDDEN`) : ``audit_log``, ``urgency_history``,
  ``kpi_snapshots``, ``weekly_reviews`` et ``decisions`` sont append-only —
  la promesse « jamais de perte » s'effondre si elles deviennent éditables ;
- **Validation typée AVANT écriture** : les colonnes à contrainte connue
  (``gamma``/``beta`` ∈ [0, 1], ``delta`` ∈ [0, 2], ``progress`` ∈ [0, 1],
  ``ud``/``consistency_ratio`` bornés, fenêtre ``start_ts < deadline_ts`` des
  jalons, colonnes ``*_json``) sont validées — refus SANS écriture sinon ;
- **Audit systématique** : chaque cellule modifiée laisse une ligne dans le
  journal d'audit de la base concernée (``entity_type="raw:<table>"``,
  ``source="edit"``), dans la MÊME transaction que l'UPDATE.

Les noms de table et de colonne ne peuvent pas être passés en paramètre « ? »
de SQLite : ils sont donc validés par appartenance STRICTE aux métadonnées de
la base (``sqlite_master``, ``PRAGMA table_info``) avant d'être interpolés
entre guillemets doubles — aucune injection possible. Les VALEURS, elles,
restent toujours paramétrées par « ? ».
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import ClassVar

from supplyscore.data.audit import AuditTrail
from supplyscore.data.db import ClientDatabase, RegistryDatabase
from supplyscore.services.orchestrator import SupplyScoreService

#: Bornes [min, max] par NOM de colonne (les noms sont uniques aux tables
#: éditables qui les portent : gamma/beta/delta -> arcs, progress -> milestones,
#: ud/consistency_ratio -> assessments).
_RANGE_RULES: dict[str, tuple[float, float]] = {
    "gamma": (0.0, 1.0),
    "beta": (0.0, 1.0),
    "delta": (0.0, 2.0),
    "progress": (0.0, 1.0),
    "ud": (0.0, 1.0),
    "consistency_ratio": (0.0, 1.0),
}


class ForbiddenTableError(Exception):
    """Table interdite d'édition (historique append-only ou hors liste blanche)."""


@dataclass(frozen=True)
class TableInfo:
    """Métadonnées d'une table : nom, éditabilité et nombre de lignes."""

    #: Nom SQL de la table (tel que dans ``sqlite_master``).
    name: str
    #: True si la table est dans la liste blanche d'édition (jamais pour FORBIDDEN).
    editable: bool
    #: Nombre de lignes au moment de la lecture.
    row_count: int


@dataclass(frozen=True)
class CellResult:
    """Résultat d'une édition de cellule : verdict et message français."""

    #: True si la cellule a été écrite (et auditée), False si refusée.
    ok: bool
    #: Message français : « ancienne → nouvelle » si ok, cause du refus sinon.
    message_fr: str


class RawTableService:
    """Lecture et édition brutes des tables SQLite, sous liste blanche et audit.

    Chaque lecture se fait sous le verrou de la base concernée ; chaque
    écriture passe par :meth:`update_cell` (validation typée, UPDATE
    paramétré et ligne d'audit dans la même transaction).
    """

    #: Tables éditables par famille de base (« registry » ou « client »).
    EDITABLE_TABLES: ClassVar[dict[str, frozenset[str]]] = {
        "registry": frozenset(
            {"nodes", "arcs", "milestones", "tags", "tag_categories", "projects"}
        ),
        "client": frozenset({"assessments", "spec_sheet", "events"}),
    }

    #: Tables d'historique append-only : la promesse « jamais de perte »
    #: s'effondre si elles deviennent éditables — toujours en lecture seule.
    FORBIDDEN: ClassVar[frozenset[str]] = frozenset(
        {"audit_log", "urgency_history", "kpi_snapshots", "weekly_reviews", "decisions"}
    )

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise la vue brute sur la façade applicative.

        Args:
            service: façade :class:`SupplyScoreService` (registre, bases
                client et horloge pour l'horodatage des audits).
        """
        self._service = service

    # --- Lecture ----------------------------------------------------------------------

    def list_databases(self) -> list[str]:
        """Liste les bases accessibles : ``"registry"`` puis les ids de nœuds.

        Returns:
            ``["registry"]`` suivi des ids des nœuds du registre (chaque nœud
            possède sa base client) ; le NOM du nœud sert de libellé côté page.
        """
        return ["registry"] + [node.id for node in self._service.registry.list_nodes()]

    def list_tables(self, db: str) -> list[TableInfo]:
        """Liste les tables de la base avec leur éditabilité et leur volumétrie.

        L'éditabilité vient de la liste blanche de la famille de base
        (:attr:`EDITABLE_TABLES`) ; les tables :attr:`FORBIDDEN` sont
        TOUJOURS ``editable=False``, quelle que soit la liste blanche.

        Args:
            db: ``"registry"`` ou l'id d'un nœud (base client).

        Returns:
            Les :class:`TableInfo` triées par nom (tables internes
            ``sqlite_*`` exclues).

        Raises:
            ValueError: si ``db`` n'est ni « registry » ni un id de nœud connu.
        """
        database = self._database(db)
        whitelist = self.EDITABLE_TABLES["registry" if db == "registry" else "client"]
        infos: list[TableInfo] = []
        with database.lock:
            for name in self._table_names(database):
                count_row = database.conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
                infos.append(
                    TableInfo(
                        name=name,
                        editable=name in whitelist and name not in self.FORBIDDEN,
                        row_count=int(count_row[0]),
                    )
                )
        return infos

    def fetch(
        self, db: str, table: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], list[str]]:
        """Lit une page de la table, ``rowid`` inclus (clé de ligne universelle).

        La lecture se fait sous le verrou de la base. Le ``rowid`` SQLite est
        retourné en première colonne : il sert d'identifiant de ligne pour
        :meth:`update_cell` quand la table n'a pas de clé primaire simple.

        Args:
            db: ``"registry"`` ou l'id d'un nœud (base client).
            table: nom de la table à lire.
            limit: nombre maximal de lignes retournées.
            offset: décalage de pagination (lignes sautées).

        Returns:
            Le couple ``(lignes, noms de colonnes)`` — chaque ligne est un
            dict ``{colonne: valeur}`` avec la clé ``"rowid"`` en tête.

        Raises:
            ValueError: si la base ou la table est inconnue.
        """
        database = self._database(db)
        with database.lock:
            if table not in self._table_names(database):
                raise ValueError(f"Table inconnue : « {table} » (base « {db} »).")
            cursor = database.conn.execute(
                f'SELECT rowid AS rowid, * FROM "{table}" LIMIT ? OFFSET ?',
                (limit, offset),
            )
            columns = [description[0] for description in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return rows, columns

    # --- Écriture ---------------------------------------------------------------------

    def update_cell(
        self,
        db: str,
        table: str,
        pk: dict[str, object],
        column: str,
        new_value: object,
        operator_id: str = "",
    ) -> CellResult:
        """Modifie UNE cellule : validation typée, UPDATE paramétré et audit.

        Une valeur qui viole une contrainte connue (bornes numériques,
        fenêtre de jalon, JSON invalide) est refusée par un
        :class:`CellResult` ``ok=False`` SANS la moindre écriture. En cas de
        succès, la ligne d'audit (``entity_type="raw:<table>"``,
        ``entity_id=str(pk)``, ``field=column``, ``source="edit"``) est
        écrite dans la MÊME transaction que l'UPDATE.

        Args:
            db: ``"registry"`` ou l'id d'un nœud (base client).
            table: table cible (doit être dans la liste blanche).
            pk: clé de ligne ``{colonne: valeur}`` — ``{"rowid": n}`` accepté
                pour toute table (clé universelle fournie par :meth:`fetch`).
            column: colonne à modifier (jamais une colonne de clé primaire).
            new_value: nouvelle valeur (coercée en float pour les colonnes à
                bornes numériques).
            operator_id: opérateur à l'origine de l'édition (audit).

        Returns:
            :class:`CellResult` — ``ok=True`` avec « ancienne → nouvelle »,
            ou ``ok=False`` avec la cause du refus (rien n'est alors écrit).

        Raises:
            ForbiddenTableError: table d'historique (:attr:`FORBIDDEN`) ou
                hors liste blanche d'édition.
            ValueError: base inconnue, colonne inconnue ou de clé primaire,
                clé ``pk`` invalide ou ligne introuvable.
        """
        database = self._database(db)
        if table in self.FORBIDDEN:
            raise ForbiddenTableError(
                f"Table « {table} » inéditable par construction : historique append-only, "
                "la promesse « jamais de perte » interdit toute modification."
            )
        whitelist = self.EDITABLE_TABLES["registry" if db == "registry" else "client"]
        if table not in whitelist:
            raise ForbiddenTableError(
                f"Table « {table} » hors liste blanche d'édition de la base « {db} »."
            )
        with database.lock:
            columns = self._columns(database, table)
            pk_columns = self._pk_columns(database, table)
            if column not in columns:
                raise ValueError(f"Colonne inconnue : « {column} » (table « {table} »).")
            if column in pk_columns or column in pk or column == "rowid":
                raise ValueError(
                    f"Colonne « {column} » : clé primaire de « {table} », non éditable."
                )
            if not pk:
                raise ValueError("Clé de ligne vide : fournissez au moins une colonne de clé.")
            for key in pk:
                if key != "rowid" and key not in columns:
                    raise ValueError(f"Clé primaire inconnue : « {key} » (table « {table} »).")

            where = " AND ".join(f'"{key}" = ?' for key in pk)
            row = database.conn.execute(
                f'SELECT * FROM "{table}" WHERE {where}', tuple(pk.values())
            ).fetchone()
            if row is None:
                raise ValueError(f"Ligne introuvable dans « {table} » pour la clé {pk}.")
            old_value = row[column]

            coerced, error = self._validate(column, new_value, row)
            if error is not None:
                return CellResult(ok=False, message_fr=error)

            trail = AuditTrail(database.conn, self._service.clock, lock=database.lock)
            owns = not database.conn.in_transaction
            if owns:
                database.conn.execute("BEGIN")
            try:
                trail.record(
                    f"raw:{table}", str(pk), column, old_value, coerced, "edit", operator_id
                )
                database.conn.execute(
                    f'UPDATE "{table}" SET "{column}" = ? WHERE {where}',
                    (coerced, *pk.values()),
                )
            except BaseException:
                if owns and database.conn.in_transaction:
                    database.conn.rollback()
                raise
            if owns and database.conn.in_transaction:
                database.conn.commit()
        return CellResult(
            ok=True,
            message_fr=(
                f"1 cellule modifiée — « {table}.{column} » : {old_value!r} → {coerced!r}."
            ),
        )

    # --- Validation typée ---------------------------------------------------------------

    @staticmethod
    def _validate(column: str, new_value: object, row: sqlite3.Row) -> tuple[object, str | None]:
        """Valide ``new_value`` contre les contraintes connues de la colonne.

        Args:
            column: colonne cible.
            new_value: valeur proposée (souvent une chaîne venue de l'UI).
            row: ligne courante, pour les contraintes croisées (fenêtre de
                jalon ``start_ts``/``deadline_ts``).

        Returns:
            ``(valeur coercée, None)`` si acceptée, ``(None, message
            français)`` si refusée — l'appelant n'écrit alors RIEN.
        """
        row_columns = set(row.keys())
        if column.endswith("_json"):
            if not isinstance(new_value, str):
                return None, (
                    f"« {column} » : JSON attendu sous forme de chaîne — aucune écriture."
                )
            try:
                json.loads(new_value)
            except json.JSONDecodeError as exc:
                return None, f"« {column} » : JSON invalide ({exc}) — aucune écriture."
            return new_value, None

        bounds = _RANGE_RULES.get(column)
        if bounds is not None:
            number, error = RawTableService._as_number(column, new_value)
            if error is not None or number is None:
                return None, error
            lo, hi = bounds
            if not lo <= number <= hi:
                return None, (f"« {column} » : {number:g} hors [{lo:g}, {hi:g}] — aucune écriture.")
            return number, None

        if column == "deadline_ts" and "start_ts" in row_columns:
            number, error = RawTableService._as_number(column, new_value)
            if error is not None or number is None:
                return None, error
            start_ts = float(row["start_ts"])
            if number <= start_ts:
                return None, (
                    f"« deadline_ts » : {number:g} doit être strictement postérieure à "
                    f"start_ts ({start_ts:g}) — aucune écriture."
                )
            return number, None

        if column == "start_ts" and "deadline_ts" in row_columns:
            number, error = RawTableService._as_number(column, new_value)
            if error is not None or number is None:
                return None, error
            deadline_ts = float(row["deadline_ts"])
            if number >= deadline_ts:
                return None, (
                    f"« start_ts » : {number:g} doit être strictement antérieure à "
                    f"deadline_ts ({deadline_ts:g}) — aucune écriture."
                )
            return number, None

        return new_value, None

    @staticmethod
    def _as_number(column: str, value: object) -> tuple[float | None, str | None]:
        """Coerce ``value`` en flottant fini (message français sinon).

        Args:
            column: colonne cible (pour le message d'erreur).
            value: valeur proposée (chaîne, nombre...).

        Returns:
            ``(nombre, None)`` si la valeur est un flottant fini,
            ``(None, message français)`` sinon.
        """
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None, f"« {column} » : valeur non numérique ({value!r}) — aucune écriture."
        if not math.isfinite(number):
            return None, (
                f"« {column} » : valeur non finie ({value!r}) — NaN et ±inf sont rejetés."
            )
        return number, None

    # --- Aides internes -------------------------------------------------------------------

    def _database(self, db: str) -> RegistryDatabase | ClientDatabase:
        """Retourne la base demandée (registre ou base client d'un nœud connu).

        Le nœud doit exister dans le registre : on ne crée JAMAIS de fichier
        sqlite pour un id inconnu (une faute de frappe ne crée pas de base).

        Args:
            db: ``"registry"`` ou l'id d'un nœud.

        Returns:
            La :class:`RegistryDatabase` ou la :class:`ClientDatabase` du nœud.

        Raises:
            ValueError: si ``db`` n'est ni « registry » ni un id de nœud connu.
        """
        if db == "registry":
            return self._service.registry
        if self._service.registry.get_node(db) is None:
            raise ValueError(f"Base inconnue : « {db} » (ni « registry » ni un id de nœud).")
        return self._service.client_db(db)

    @staticmethod
    def _table_names(database: RegistryDatabase | ClientDatabase) -> list[str]:
        """Noms des tables de la base, triés (tables internes ``sqlite_*`` exclues).

        Args:
            database: base hôte (l'appelant tient déjà son verrou ou non —
                la requête est une simple lecture de ``sqlite_master``).

        Returns:
            Les noms de tables, ordonnés alphabétiquement.
        """
        rows = database.conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [row["name"] for row in rows]

    @staticmethod
    def _columns(database: RegistryDatabase | ClientDatabase, table: str) -> list[str]:
        """Colonnes déclarées de la table (via ``PRAGMA table_info``).

        Args:
            database: base hôte.
            table: nom de table DÉJÀ validé par appartenance à la liste
                blanche (jamais interpolé sans cette garantie).

        Returns:
            Les noms de colonnes, dans l'ordre du schéma.
        """
        rows = database.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return [row["name"] for row in rows]

    @staticmethod
    def _pk_columns(database: RegistryDatabase | ClientDatabase, table: str) -> set[str]:
        """Colonnes de clé primaire de la table (via ``PRAGMA table_info``).

        Args:
            database: base hôte.
            table: nom de table DÉJÀ validé (cf. :meth:`_columns`).

        Returns:
            L'ensemble des colonnes participant à la clé primaire.
        """
        rows = database.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return {row["name"] for row in rows if int(row["pk"]) > 0}
