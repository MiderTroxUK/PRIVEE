"""Journal d'audit générique append-only (table ``audit_log``).

:class:`AuditTrail` enregistre chaque mutation d'une entité (nœud, arc, jalon,
KPI...) sous forme de triplet « avant / après » horodaté, et permet de rejouer
l'historique (:meth:`AuditTrail.history`) ou de reconstituer la valeur d'un
champ à un instant donné (:meth:`AuditTrail.value_at`).

Principes de conception :

- **Append-only par construction** : la classe n'expose AUCUNE méthode
  ``UPDATE``/``DELETE`` — une ligne écrite ne peut plus être modifiée ni
  supprimée via cette API.
- **JSON typé** : ``old_value``/``new_value`` sont sérialisés via
  :func:`json.dumps` (jamais ``str()``), donc un ``float`` reste un ``float``,
  un ``dict`` reste un ``dict``, etc. au retour de :func:`json.loads`.
- **Transactions de l'hôte respectées** : si la connexion est déjà en
  transaction (``conn.in_transaction``), l'écriture s'y intègre sans commit ;
  sinon, l'écriture est commitée immédiatement (voir :meth:`AuditTrail.record`).
- **Horloge injectée** : ``iso_week`` et ``timestamp`` proviennent de la
  :class:`~supplyscore.core.clock.Clock` fournie, jamais de ``time.time()``.

La table ``audit_log`` est créée par les migrations de la base hôte ; ce module
ne fait que lire/écrire dedans. Toutes les requêtes sont paramétrées par "?".
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from supplyscore.core.clock import Clock, iso_week

#: Colonnes insérées (l'``id`` est auto-incrémenté par SQLite).
_INSERT_SQL = (
    "INSERT INTO audit_log (entity_type, entity_id, field, old_value, new_value,"
    " source, operator_id, iso_week, timestamp)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

#: Colonnes lues, dans l'ordre des champs de :class:`AuditEntry`.
_SELECT_COLUMNS = (
    "id, entity_type, entity_id, field, old_value, new_value,"
    " source, operator_id, iso_week, timestamp"
)

#: Savepoint encadrant les écritures par lot (:meth:`AuditTrail.record_many`).
#: Statements précomposés : aucun SQL construit dynamiquement.
_SQL_SAVEPOINT = "SAVEPOINT supplyscore_audit_batch"
_SQL_ROLLBACK_TO = "ROLLBACK TO SAVEPOINT supplyscore_audit_batch"
_SQL_RELEASE = "RELEASE SAVEPOINT supplyscore_audit_batch"

_HISTORY_SQL_BASE = (
    "SELECT " + _SELECT_COLUMNS + " FROM audit_log WHERE entity_type = ? AND entity_id = ?"
)


@dataclass(frozen=True)
class AuditEntry:
    """Une ligne du journal d'audit, valeurs déjà désérialisées (JSON typé)."""

    #: Identifiant auto-incrémenté de la ligne.
    id: int
    #: Type d'entité : "node_kpis" | "node" | "arc" | "milestone" | "spec_sheet" | ...
    entity_type: str
    #: Id du nœud/arc/jalon ; pour les KPIs, l'id du NŒUD porteur.
    entity_id: str
    #: Champ qualifié, ex. "risk.failure_probability" ; "" si entité entière.
    field: str
    #: Valeur avant mutation, désérialisée JSON (None si création).
    old_value: Any
    #: Valeur après mutation, désérialisée JSON.
    new_value: Any
    #: Origine : 'onboarding'|'weekly'|'edit'|'event:<id>'|'revert:<id>'|'system'|'migration'.
    source: str
    #: Opérateur à l'origine de la mutation ("" si non applicable).
    operator_id: str
    #: Semaine ISO de l'écriture, ex. "2026-S24".
    iso_week: str
    #: Instant de l'écriture, en secondes epoch (fourni par l'horloge injectée).
    timestamp: float


def _to_json(value: Any) -> str:
    """Sérialise une valeur en JSON typé (jamais ``str()``).

    ``None`` devient la chaîne ``"null"`` (et non un NULL SQL) : la colonne
    contient toujours du JSON valide, et ``None`` se retrouve à l'identique
    après :func:`json.loads`.

    Args:
        value: valeur Python sérialisable en JSON.

    Returns:
        La représentation JSON de ``value``.

    Raises:
        TypeError: si ``value`` n'est pas sérialisable en JSON.
    """
    return json.dumps(value, sort_keys=True)


def _from_json(payload: str | None) -> Any:
    """Désérialise une colonne ``old_value``/``new_value``.

    Tolère un NULL SQL (lignes écrites hors de cette API, ex. migrations) en
    le traitant comme ``None``.

    Args:
        payload: contenu brut de la colonne, ou ``None``.

    Returns:
        La valeur Python retypée (int, float, str, dict, list, bool ou None).
    """
    if payload is None:
        return None
    return json.loads(payload)


class AuditTrail:
    """Journal d'audit append-only d'une base (registre ou client).

    Chaque méthode publique prend le verrou (celui de la base hôte s'il est
    fourni, sinon un :class:`threading.RLock` privé) : l'instance est donc
    utilisable depuis plusieurs threads partageant la même connexion
    (``check_same_thread=False``), comme le fait la couche ``db``.

    **Gestion de transaction** (choix documenté) : avant chaque écriture, on
    mémorise ``conn.in_transaction``. S'il est faux, l'écriture est commitée
    ici même ; s'il est vrai, une transaction métier est en cours et l'audit
    s'y intègre SANS commit — le ``COMMIT``/``ROLLBACK`` reste la
    responsabilité de l'appelant, ce qui garantit l'atomicité « mutation
    métier + trace d'audit ».
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        lock: threading.RLock | None = None,
    ) -> None:
        """Initialise le journal d'audit.

        Args:
            conn: connexion SQLite de la base hôte (la table ``audit_log``
                doit exister, créée par les migrations).
            clock: source de temps injectée (``iso_week`` et ``timestamp``).
            lock: verrou réentrant partagé avec la base hôte ; si ``None``,
                un verrou privé est créé (l'instance reste thread-safe, mais
                sans exclusion mutuelle vis-à-vis de la base hôte).
        """
        self._conn = conn
        self._clock = clock
        self._lock = lock if lock is not None else threading.RLock()

    # --- Écriture (append-only : aucune méthode UPDATE/DELETE) -------------------

    def record(
        self,
        entity_type: str,
        entity_id: str,
        field: str,
        old: Any,
        new: Any,
        source: str,
        operator_id: str = "",
    ) -> int:
        """Ajoute une entrée d'audit et renvoie l'id de la ligne créée.

        ``old``/``new`` sont sérialisés en JSON typé via :func:`json.dumps`
        (jamais ``str()``). ``iso_week`` et ``timestamp`` proviennent de
        l'horloge injectée. Si la connexion est déjà en transaction
        (``conn.in_transaction``), l'écriture s'intègre à la transaction en
        cours et n'est PAS commitée ici ; sinon elle est commitée
        immédiatement (voir la docstring de classe).

        Args:
            entity_type: type d'entité ("node", "arc", "milestone", ...).
            entity_id: id de l'entité (id du nœud pour les KPIs).
            field: champ qualifié ("risk.failure_probability"), "" si entité
                entière.
            old: valeur avant mutation (``None`` si création).
            new: valeur après mutation.
            source: origine ('onboarding'|'weekly'|'edit'|'event:<id>'|
                'revert:<id>'|'system'|'migration').
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            L'id (rowid) de la ligne d'audit insérée.

        Raises:
            TypeError: si ``old`` ou ``new`` n'est pas sérialisable en JSON.
        """
        with self._lock:
            now = self._clock.now()
            owns_transaction = not self._conn.in_transaction
            cursor = self._conn.execute(
                _INSERT_SQL,
                (
                    entity_type,
                    entity_id,
                    field,
                    _to_json(old),
                    _to_json(new),
                    source,
                    operator_id,
                    iso_week(now),
                    now,
                ),
            )
            if owns_transaction:
                self._conn.commit()
            row_id = cursor.lastrowid
            if row_id is None:  # pragma: no cover — INSERT renvoie toujours un rowid
                raise RuntimeError("INSERT audit_log sans rowid")
            return row_id

    def record_many(self, entries: list[tuple[str, str, str, Any, Any, str, str]]) -> None:
        """Ajoute une liste d'entrées d'audit en UNE seule transaction.

        Les valeurs sont toutes sérialisées AVANT la moindre écriture, puis
        insérées sous un ``SAVEPOINT`` : si une entrée est invalide (valeur
        non sérialisable, contrainte SQL violée), AUCUNE ligne du lot n'est
        écrite — y compris lorsque le lot s'exécute au sein d'une transaction
        englobante, dont le travail antérieur est alors préservé.

        Args:
            entries: tuples ``(entity_type, entity_id, field, old, new,
                source, operator_id)`` — mêmes sémantiques que
                :meth:`record`.

        Raises:
            TypeError: si une valeur ``old``/``new`` n'est pas sérialisable
                en JSON (aucune ligne n'est alors écrite).
            sqlite3.Error: si une insertion viole le schéma (aucune ligne
                n'est alors écrite).
        """
        with self._lock:
            now = self._clock.now()
            week = iso_week(now)
            # Sérialisation (et donc validation JSON) en amont de toute écriture.
            rows = [
                (
                    entity_type,
                    entity_id,
                    field,
                    _to_json(old),
                    _to_json(new),
                    source,
                    operator_id,
                    week,
                    now,
                )
                for entity_type, entity_id, field, old, new, source, operator_id in entries
            ]
            owns_transaction = not self._conn.in_transaction
            self._conn.execute(_SQL_SAVEPOINT)
            try:
                self._conn.executemany(_INSERT_SQL, rows)
            except Exception:
                self._conn.execute(_SQL_ROLLBACK_TO)
                self._conn.execute(_SQL_RELEASE)
                raise
            self._conn.execute(_SQL_RELEASE)
            if owns_transaction:
                self._conn.commit()

    # --- Lecture --------------------------------------------------------------------

    def history(
        self,
        entity_type: str,
        entity_id: str,
        field: str | None = None,
        limit: int = 200,
        before: float | None = None,
    ) -> list[AuditEntry]:
        """Historique d'une entité, du plus récent au plus ancien.

        Args:
            entity_type: type d'entité filtré.
            entity_id: id d'entité filtré.
            field: si fourni, ne renvoie que les mutations de ce champ.
            limit: nombre maximal d'entrées renvoyées.
            before: si fourni, ne renvoie que les entrées strictement
                antérieures (``timestamp < before``).

        Returns:
            Les :class:`AuditEntry` triées par ``timestamp`` décroissant puis
            ``id`` décroissant (les écritures d'un même instant ressortent de
            la plus récente à la plus ancienne).
        """
        sql = _HISTORY_SQL_BASE
        params: list[object] = [entity_type, entity_id]
        if field is not None:
            sql += " AND field = ?"
            params.append(field)
        if before is not None:
            sql += " AND timestamp < ?"
            params.append(before)
        sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            AuditEntry(
                id=row[0],
                entity_type=row[1],
                entity_id=row[2],
                field=row[3],
                old_value=_from_json(row[4]),
                new_value=_from_json(row[5]),
                source=row[6],
                operator_id=row[7],
                iso_week=row[8],
                timestamp=row[9],
            )
            for row in rows
        ]

    def value_at(self, entity_type: str, entity_id: str, field: str, t: float) -> Any:
        """Valeur d'un champ telle qu'elle était à l'instant ``t``.

        Renvoie le ``new_value`` de la dernière écriture dont le
        ``timestamp`` est ≤ ``t`` (départage par ``id`` décroissant à
        timestamp égal).

        Args:
            entity_type: type d'entité.
            entity_id: id d'entité.
            field: champ qualifié recherché.
            t: instant de référence, en secondes epoch.

        Returns:
            La valeur retypée (JSON désérialisé), ou ``None`` si aucune
            écriture n'existe à ou avant ``t``.
        """
        sql = (
            "SELECT new_value FROM audit_log"
            " WHERE entity_type = ? AND entity_id = ? AND field = ? AND timestamp <= ?"
            " ORDER BY timestamp DESC, id DESC LIMIT 1"
        )
        with self._lock:
            row = self._conn.execute(sql, (entity_type, entity_id, field, t)).fetchone()
        if row is None:
            return None
        return _from_json(row[0])
