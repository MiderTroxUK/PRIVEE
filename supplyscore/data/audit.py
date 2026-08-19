"""Journal d'audit generique append-only (table ``audit_log``).

:class:`AuditTrail` enregistre chaque mutation d'une entite (noeud, arc, jalon,
KPI...) sous forme de triplet " avant / apres " horodate, et permet de rejouer
l'historique (:meth:`AuditTrail.history`) ou de reconstituer la valeur d'un
champ a un instant donne (:meth:`AuditTrail.value_at`).

Principes de conception :

- **Append-only par construction** : la classe n'expose AUCUNE methode
  ``UPDATE``/``DELETE`` - une ligne ecrite ne peut plus etre modifiee ni
  supprimee via cette API.
- **JSON type** : ``old_value``/``new_value`` sont serialises via
  :func:`json.dumps` (jamais ``str()``), donc un ``float`` reste un ``float``,
  un ``dict`` reste un ``dict``, etc. au retour de :func:`json.loads`.
- **Transactions de l'hote respectees** : si la connexion est deja en
  transaction (``conn.in_transaction``), l'ecriture s'y integre sans commit ;
  sinon, l'ecriture est commitee immediatement (voir :meth:`AuditTrail.record`).
- **Horloge injectee** : ``iso_week`` et ``timestamp`` proviennent de la
  :class:`~supplyscore.core.clock.Clock` fournie, jamais de ``time.time()``.

La table ``audit_log`` est creee par les migrations de la base hote ; ce module
ne fait que lire/ecrire dedans. Toutes les requetes sont parametrees par "?".
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from supplyscore.core.clock import Clock, iso_week

#: Colonnes inserees (l'``id`` est auto-incremente par SQLite).
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

#: Savepoint encadrant les ecritures par lot (:meth:`AuditTrail.record_many`). Statements precomposes : aucun SQL construit dynamiquement.
_SQL_SAVEPOINT = "SAVEPOINT supplyscore_audit_batch"
_SQL_ROLLBACK_TO = "ROLLBACK TO SAVEPOINT supplyscore_audit_batch"
_SQL_RELEASE = "RELEASE SAVEPOINT supplyscore_audit_batch"

_HISTORY_SQL_BASE = (
    "SELECT " + _SELECT_COLUMNS + " FROM audit_log WHERE entity_type = ? AND entity_id = ?"
)


@dataclass(frozen=True)
class AuditEntry:
    """Une ligne du journal d'audit, valeurs deja deserialisees (JSON type)."""

    #: Identifiant auto-incremente de la ligne.
    id: int
    #: Type d'entite : "node_kpis" | "node" | "arc" | "milestone" | "spec_sheet" | ...
    entity_type: str
    #: Id du noeud/arc/jalon ; pour les KPIs, l'id du NOEUD porteur.
    entity_id: str
    #: Champ qualifie, ex. "risk.failure_probability" ; "" si entite entiere.
    field: str
    #: Valeur avant mutation, deserialisee JSON (None si creation).
    old_value: Any
    #: Valeur apres mutation, deserialisee JSON.
    new_value: Any
    #: Origine : 'onboarding'|'weekly'|'edit'|'event:<id>'|'revert:<id>'|'system'|'migration'.
    source: str
    #: Operateur a l'origine de la mutation ("" si non applicable).
    operator_id: str
    #: Semaine ISO de l'ecriture, ex. "2026-S24".
    iso_week: str
    #: Instant de l'ecriture, en secondes epoch (fourni par l'horloge injectee).
    timestamp: float


def _to_json(value: Any) -> str:
    """Serialise une valeur en JSON type (jamais ``str()``).

    ``None`` devient la chaine ``"null"`` (et non un NULL SQL) : la colonne
    contient toujours du JSON valide, et ``None`` se retrouve a l'identique
    apres :func:`json.loads`.

    Args:
        value: valeur Python serialisable en JSON.

    Returns:
        La representation JSON de ``value``.

    Raises:
        TypeError: si ``value`` n'est pas serialisable en JSON.
    """
    return json.dumps(value, sort_keys=True)


def _from_json(payload: str | None) -> Any:
    """Deserialise une colonne ``old_value``/``new_value``.

    Tolere un NULL SQL (lignes ecrites hors de cette API, ex. migrations) en
    le traitant comme ``None``.

    Args:
        payload: contenu brut de la colonne, ou ``None``.

    Returns:
        La valeur Python retypee (int, float, str, dict, list, bool ou None).
    """
    if payload is None:
        return None
    return json.loads(payload)


class AuditTrail:
    """Journal d'audit append-only d'une base (registre ou client).

    Chaque methode publique prend le verrou (celui de la base hote s'il est
    fourni, sinon un :class:`threading.RLock` prive) : l'instance est donc
    utilisable depuis plusieurs threads partageant la meme connexion
    (``check_same_thread=False``), comme le fait la couche ``db``.

    **Gestion de transaction** (choix documente) : avant chaque ecriture, on
    memorise ``conn.in_transaction``. S'il est faux, l'ecriture est commitee
    ici meme ; s'il est vrai, une transaction metier est en cours et l'audit
    s'y integre SANS commit - le ``COMMIT``/``ROLLBACK`` reste la
    responsabilite de l'appelant, ce qui garantit l'atomicite " mutation
    metier + trace d'audit ".
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        lock: threading.RLock | None = None,
    ) -> None:
        """Initialise le journal d'audit.

        Args:
            conn: connexion SQLite de la base hote (la table ``audit_log``
                doit exister, creee par les migrations).
            clock: source de temps injectee (``iso_week`` et ``timestamp``).
            lock: verrou reentrant partage avec la base hote ; si ``None``,
                un verrou prive est cree (l'instance reste thread-safe, mais
                sans exclusion mutuelle vis-a-vis de la base hote).
        """
        self._conn = conn
        self._clock = clock
        self._lock = lock if lock is not None else threading.RLock()

    # Ecriture (append-only : aucune methode UPDATE/DELETE)

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
        """Ajoute une entree d'audit et renvoie l'id de la ligne creee.

        ``old``/``new`` sont serialises en JSON type via :func:`json.dumps`
        (jamais ``str()``). ``iso_week`` et ``timestamp`` proviennent de
        l'horloge injectee. Si la connexion est deja en transaction
        (``conn.in_transaction``), l'ecriture s'integre a la transaction en
        cours et n'est PAS commitee ici ; sinon elle est commitee
        immediatement (voir la docstring de classe).

        Args:
            entity_type: type d'entite ("node", "arc", "milestone", ...).
            entity_id: id de l'entite (id du noeud pour les KPIs).
            field: champ qualifie ("risk.failure_probability"), "" si entite
                entiere.
            old: valeur avant mutation (``None`` si creation).
            new: valeur apres mutation.
            source: origine ('onboarding'|'weekly'|'edit'|'event:<id>'|
                'revert:<id>'|'system'|'migration').
            operator_id: operateur a l'origine de la mutation.

        Returns:
            L'id (rowid) de la ligne d'audit inseree.

        Raises:
            TypeError: si ``old`` ou ``new`` n'est pas serialisable en JSON.
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
            if row_id is None:  # pragma: no cover - INSERT renvoie toujours un rowid
                raise RuntimeError("INSERT audit_log sans rowid")
            return row_id

    def record_many(self, entries: list[tuple[str, str, str, Any, Any, str, str]]) -> None:
        """Ajoute une liste d'entrees d'audit en UNE seule transaction.

        Les valeurs sont toutes serialisees AVANT la moindre ecriture, puis
        inserees sous un ``SAVEPOINT`` : si une entree est invalide (valeur
        non serialisable, contrainte SQL violee), AUCUNE ligne du lot n'est
        ecrite - y compris lorsque le lot s'execute au sein d'une transaction
        englobante, dont le travail anterieur est alors preserve.

        Args:
            entries: tuples ``(entity_type, entity_id, field, old, new,
                source, operator_id)`` - memes semantiques que
                :meth:`record`.

        Raises:
            TypeError: si une valeur ``old``/``new`` n'est pas serialisable
                en JSON (aucune ligne n'est alors ecrite).
            sqlite3.Error: si une insertion viole le schema (aucune ligne
                n'est alors ecrite).
        """
        with self._lock:
            now = self._clock.now()
            week = iso_week(now)
            # Serialisation (et donc validation JSON) en amont de toute ecriture.
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

    # Lecture

    def history(
        self,
        entity_type: str,
        entity_id: str,
        field: str | None = None,
        limit: int = 200,
        before: float | None = None,
    ) -> list[AuditEntry]:
        """Historique d'une entite, du plus recent au plus ancien.

        Args:
            entity_type: type d'entite filtre.
            entity_id: id d'entite filtre.
            field: si fourni, ne renvoie que les mutations de ce champ.
            limit: nombre maximal d'entrees renvoyees.
            before: si fourni, ne renvoie que les entrees strictement
                anterieures (``timestamp < before``).

        Returns:
            Les :class:`AuditEntry` triees par ``timestamp`` decroissant puis
            ``id`` decroissant (les ecritures d'un meme instant ressortent de
            la plus recente a la plus ancienne).
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
        """Valeur d'un champ telle qu'elle etait a l'instant ``t``.

        Renvoie le ``new_value`` de la derniere ecriture dont le
        ``timestamp`` est <= ``t`` (departage par ``id`` decroissant a
        timestamp egal).

        Args:
            entity_type: type d'entite.
            entity_id: id d'entite.
            field: champ qualifie recherche.
            t: instant de reference, en secondes epoch.

        Returns:
            La valeur retypee (JSON deserialise), ou ``None`` si aucune
            ecriture n'existe a ou avant ``t``.
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
