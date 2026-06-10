"""Point de passage obligatoire de toute écriture métier (diff + validation + audit).

:class:`MutationService` est l'unique porte d'entrée des écritures métier :
chaque mutation est diffée champ à champ (seuls les champs réellement modifiés
sont écrits), validée (bornes des KPIs, listes blanches de champs), tracée dans
le journal d'audit (:class:`~supplyscore.data.audit.AuditTrail`) et regroupée
en transaction avec l'écriture métier de la même base.

Choix de conception :

- **Diff d'abord** : une valeur identique à l'existante n'est ni écrite ni
  journalisée — un appel sans changement effectif est un no-op complet
  (aucun snapshot, aucune ligne d'audit, liste retournée vide).
- **Validation bloquante** : si UNE seule valeur est invalide, RIEN n'est
  écrit ; le ``ValueError`` levé liste TOUTES les erreurs en français.
- **Trace d'abord** : dans chaque base, les lignes d'audit sont insérées dans
  la MÊME transaction que l'écriture métier, AVANT elle — le commit final de
  la méthode ``save_*`` de la couche db emporte le tout, il ne peut donc pas
  exister d'écriture commitée sans sa trace. Exception documentée :
  :meth:`MutationService.replace_assessment`, où l'id audité n'existe qu'après
  l'INSERT ; l'audit suit immédiatement, sous le même verrou.
- **Deux bases, deux transactions** : pour les KPIs, le couple « lignes
  d'audit + snapshot » est atomique dans la base CLIENT du nœud, puis le nœud
  est upserté dans le REGISTRE — deux fichiers SQLite distincts ne partagent
  pas de transaction.
- **Graphe en mémoire** : si un ``repo`` est fourni, le nœud ou l'arc en
  mémoire est synchronisé après chaque écriture réussie (c'est l'orchestrateur
  qui le fournit).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from supplyscore.core.clock import Clock
from supplyscore.data.audit import AuditEntry, AuditTrail
from supplyscore.data.db import ClientDatabase, RegistryDatabase
from supplyscore.domain.constraints import validate_kpi_value
from supplyscore.domain.milestones import MilestoneStatus
from supplyscore.domain.models import AHPAssessment, SupplyArc
from supplyscore.graph.repository import GraphRepository

#: Champs simples d'un nœud modifiables via :meth:`MutationService.update_node_fields`.
_NODE_FIELDS: tuple[str, ...] = (
    "name",
    "label",
    "location",
    "latitude",
    "longitude",
    "onboarding_state",
)

#: Champs d'un jalon modifiables via :meth:`MutationService.update_milestone`.
_MILESTONE_FIELDS: tuple[str, ...] = (
    "name",
    "kind",
    "start_ts",
    "deadline_ts",
    "status",
    "progress",
    "position",
)

#: Champs diffés d'un arc existant (:meth:`MutationService.upsert_arc`).
_ARC_FIELDS: tuple[str, ...] = ("gamma", "beta", "delta", "kind_arc", "label")

#: Nombre d'entrées relues pour retrouver une ligne d'audit fraîchement insérée.
_READBACK_LIMIT = 50


class MutationService:
    """Point de passage obligatoire de toute écriture métier.

    Chaque mutation suit le même chemin : diff + validation + audit +
    transaction. Construit en interne un :class:`~supplyscore.data.audit.AuditTrail` sur le
    registre (connexion et verrou partagés) et, à la demande, un ``AuditTrail``
    par base client (cache léger, invalidé si la fabrique retourne une
    nouvelle instance — éviction LRU côté orchestrateur, par exemple).

    Thread-safety : chaque méthode publique mutante prend ``self._lock``
    (RLock réentrant), ce qui sérialise les cycles lecture-diff-écriture et
    évite les pertes de mise à jour entre threads concurrents.
    """

    def __init__(
        self,
        registry: RegistryDatabase,
        client_db_factory: Callable[[str], ClientDatabase],
        clock: Clock,
        repo: GraphRepository | None = None,
    ) -> None:
        """Initialise le service de mutation.

        Args:
            registry: registre global (nœuds, arcs, jalons, tags).
            client_db_factory: fabrique ``node_id -> ClientDatabase`` (la base
                privée du nœud) ; typiquement ``SupplyScoreService.client_db``.
            clock: horloge injectée (horodatage des audits et snapshots).
            repo: dépôt de graphe en mémoire à synchroniser après chaque
                écriture réussie ; ``None`` = pas de synchronisation.
        """
        self._registry = registry
        self._client_db_factory = client_db_factory
        self._clock = clock
        self._repo = repo
        self._registry_audit = AuditTrail(registry.conn, clock, lock=registry.lock)
        self._client_audits: dict[str, tuple[ClientDatabase, AuditTrail]] = {}
        self._lock = threading.RLock()

    # --- KPIs ----------------------------------------------------------------------

    def update_kpis(
        self,
        node_id: str,
        changes: dict[str, float | None],
        source: str,
        operator_id: str = "",
    ) -> list[AuditEntry]:
        """Met à jour des KPIs d'un nœud : diff, validation, snapshot et audit.

        Étapes : lecture du nœud, validation de TOUTES les valeurs demandées
        (rien n'est écrit si une seule est invalide), diff champ à champ
        (égalité stricte sur les flottants — seuls les champs réellement
        changés sont écrits), puis persistance cohérente : lignes d'audit
        (une PAR champ changé, dans la base CLIENT du nœud) + snapshot KPI
        dans la même transaction client, et upsert du nœud dans le registre.

        Args:
            node_id: identifiant du nœud porteur des KPIs.
            changes: ``{"bloc.champ": nouvelle valeur}`` ; ``None`` efface le
                champ (KPI non renseigné).
            source: origine de la mutation ('edit', 'weekly', 'event:<id>'...).
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            Les :class:`AuditEntry` créées (``entity_type="node_kpis"``,
            ``field`` = chemin qualifié), ``[]`` si aucun changement effectif
            — et dans ce cas AUCUN snapshot ni ligne d'audit.

        Raises:
            KeyError: si le nœud est inconnu du registre.
            ValueError: si au moins une valeur est invalide (le message liste
                toutes les erreurs) ; rien n'est alors écrit.
        """
        with self._lock:
            node = self._registry.get_node(node_id)
            if node is None:
                raise KeyError(f"Nœud inconnu : {node_id!r}")

            errors = [
                message
                for message in (validate_kpi_value(path, value) for path, value in changes.items())
                if message is not None
            ]
            if errors:
                raise ValueError(
                    "Mise à jour des KPIs refusée — aucune écriture effectuée : "
                    + " ; ".join(errors)
                )

            diff: list[tuple[str, float | None, float | None]] = []
            for path, value in changes.items():
                block_name, field_name = path.split(".", 1)
                old = getattr(getattr(node.kpis, block_name), field_name)
                new = None if value is None else float(value)
                if old != new:
                    diff.append((path, old, new))
            if not diff:
                return []

            for path, _old, new in diff:
                block_name, field_name = path.split(".", 1)
                setattr(getattr(node.kpis, block_name), field_name, new)

            client, trail = self._client_audit(node_id)
            entries: list[AuditEntry] = []
            with self._transaction(client):
                for path, old, new in diff:
                    entries.append(
                        self._record(
                            trail, "node_kpis", node_id, path, old, new, source, operator_id
                        )
                    )
                client.save_kpi_snapshot(node_id, node.kpis, timestamp=self._clock.now())
            self._registry.save_node(node)

            if self._repo is not None:
                cached = self._repo.get_node(node_id)
                if cached is not None:
                    cached.kpis = node.kpis
                    self._repo.update_node(cached)
            return entries

    # --- Champs simples du nœud ---------------------------------------------------

    def update_node_fields(
        self, node_id: str, changes: dict[str, Any], source: str, operator_id: str = ""
    ) -> list[AuditEntry]:
        """Met à jour des champs simples du nœud (liste blanche stricte).

        Champs autorisés : ``name``, ``label``, ``location``, ``latitude``,
        ``longitude``, ``onboarding_state``. Audit ``entity_type="node"`` dans
        le REGISTRE, une ligne par champ réellement changé.

        Args:
            node_id: identifiant du nœud.
            changes: ``{champ: nouvelle valeur}`` (champs de la liste blanche).
            source: origine de la mutation.
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            Les :class:`AuditEntry` créées, ``[]`` si aucun changement effectif.

        Raises:
            KeyError: si le nœud est inconnu du registre.
            ValueError: si un champ demandé est hors liste blanche.
        """
        with self._lock:
            unknown = sorted(set(changes) - set(_NODE_FIELDS))
            if unknown:
                raise ValueError(
                    "Champs de nœud hors liste blanche : "
                    + ", ".join(unknown)
                    + " (autorisés : "
                    + ", ".join(_NODE_FIELDS)
                    + ")"
                )
            node = self._registry.get_node(node_id)
            if node is None:
                raise KeyError(f"Nœud inconnu : {node_id!r}")

            diff = [
                (field, getattr(node, field), value)
                for field, value in changes.items()
                if getattr(node, field) != value
            ]
            if not diff:
                return []
            for field, _old, new in diff:
                setattr(node, field, new)

            entries: list[AuditEntry] = []
            with self._transaction(self._registry):
                for field, old, new in diff:
                    entries.append(
                        self._record(
                            self._registry_audit,
                            "node",
                            node_id,
                            field,
                            old,
                            new,
                            source,
                            operator_id,
                        )
                    )
                self._registry.save_node(node)

            if self._repo is not None:
                cached = self._repo.get_node(node_id)
                if cached is not None:
                    for field, _old, new in diff:
                        setattr(cached, field, new)
                    self._repo.update_node(cached)
            return entries

    # --- Arcs ----------------------------------------------------------------------

    def upsert_arc(self, arc: SupplyArc, source: str, operator_id: str = "") -> list[AuditEntry]:
        """Crée l'arc, ou le met à jour avec un diff par champ s'il existe déjà.

        Création : une ligne d'audit ``field=""``, ``old=None``,
        ``new="created"``. Modification : une ligne par champ changé parmi
        ``gamma``/``beta``/``delta``/``kind_arc``/``label``. Audit
        ``entity_type="arc"``, ``entity_id=arc.id``, dans le REGISTRE.

        Args:
            arc: arc à persister (la clé est ``(source_id, target_id)``).
            source: origine de la mutation.
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            Les :class:`AuditEntry` créées, ``[]`` si l'arc existant est
            identique champ à champ.

        Raises:
            ValueError: si ``gamma`` ou ``beta`` sort de [0, 1], ou ``delta``
                de [0, 2] (le message liste toutes les bornes violées).
        """
        with self._lock:
            errors: list[str] = []
            if not 0.0 <= arc.gamma <= 1.0:
                errors.append(f"gamma hors [0, 1] : {arc.gamma}")
            if not 0.0 <= arc.beta <= 1.0:
                errors.append(f"beta hors [0, 1] : {arc.beta}")
            if not 0.0 <= arc.delta <= 2.0:
                errors.append(f"delta hors [0, 2] : {arc.delta}")
            if errors:
                raise ValueError("Arc invalide — aucune écriture effectuée : " + " ; ".join(errors))

            existing = self._registry.get_arc(arc.source_id, arc.target_id)
            entries: list[AuditEntry] = []
            if existing is None:
                with self._transaction(self._registry):
                    entries.append(
                        self._record(
                            self._registry_audit,
                            "arc",
                            arc.id,
                            "",
                            None,
                            "created",
                            source,
                            operator_id,
                        )
                    )
                    self._registry.save_arc(arc)
            else:
                diff = [
                    (field, getattr(existing, field), getattr(arc, field))
                    for field in _ARC_FIELDS
                    if getattr(existing, field) != getattr(arc, field)
                ]
                if not diff:
                    return []
                with self._transaction(self._registry):
                    for field, old, new in diff:
                        entries.append(
                            self._record(
                                self._registry_audit,
                                "arc",
                                arc.id,
                                field,
                                old,
                                new,
                                source,
                                operator_id,
                            )
                        )
                    self._registry.save_arc(arc)

            self._sync_repo_arc(arc)
            return entries

    def delete_arc(
        self, source_id: str, target_id: str, source: str, operator_id: str = ""
    ) -> list[AuditEntry]:
        """Supprime l'arc ``source_id -> target_id`` (audité dans le REGISTRE).

        Args:
            source_id: nœud fournisseur de l'arc.
            target_id: nœud client de l'arc.
            source: origine de la mutation.
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            La :class:`AuditEntry` créée (``field=""``, ``old="exists"``,
            ``new="deleted"``), dans une liste.

        Raises:
            KeyError: si l'arc est inconnu du registre.
        """
        with self._lock:
            existing = self._registry.get_arc(source_id, target_id)
            if existing is None:
                raise KeyError(f"Arc inconnu : {source_id!r} -> {target_id!r}")
            with self._transaction(self._registry):
                entry = self._record(
                    self._registry_audit,
                    "arc",
                    existing.id,
                    "",
                    "exists",
                    "deleted",
                    source,
                    operator_id,
                )
                self._registry.delete_arc(source_id, target_id)
            if self._repo is not None and self._repo.get_arc(source_id, target_id) is not None:
                self._repo.remove_arc(source_id, target_id)
            return [entry]

    # --- Tags ----------------------------------------------------------------------

    def set_node_tags(
        self, node_id: str, tag_ids: list[str], source: str, operator_id: str = ""
    ) -> list[AuditEntry]:
        """Remplace les tags du nœud (diff sur l'ENSEMBLE, audité dans le REGISTRE).

        Args:
            node_id: identifiant du nœud.
            tag_ids: nouvelle liste d'ids de tags.
            source: origine de la mutation.
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            La :class:`AuditEntry` créée (``field="tags"``, ``old`` = liste
            avant, ``new`` = liste après) dans une liste, ou ``[]`` si
            l'ensemble des tags est inchangé (l'ordre seul ne compte pas).

        Raises:
            KeyError: si le nœud est inconnu du registre.
        """
        with self._lock:
            node = self._registry.get_node(node_id)
            if node is None:
                raise KeyError(f"Nœud inconnu : {node_id!r}")
            before = list(node.tags)
            after = list(tag_ids)
            if set(before) == set(after):
                return []
            with self._transaction(self._registry):
                entry = self._record(
                    self._registry_audit,
                    "node",
                    node_id,
                    "tags",
                    before,
                    after,
                    source,
                    operator_id,
                )
                self._registry.set_node_tags(node_id, after)
            if self._repo is not None:
                cached = self._repo.get_node(node_id)
                if cached is not None:
                    cached.tags = list(after)
                    self._repo.update_node(cached)
            return [entry]

    # --- Jalons --------------------------------------------------------------------

    def update_milestone(
        self, milestone_id: str, changes: dict[str, Any], source: str, operator_id: str = ""
    ) -> list[AuditEntry]:
        """Met à jour un jalon (liste blanche stricte, validation après application).

        Champs autorisés : ``name``, ``kind``, ``start_ts``, ``deadline_ts``,
        ``status``, ``progress``, ``position``. Après application des
        changements, ``progress`` doit rester dans [0, 1] et la fenêtre
        ``start_ts < deadline_ts`` doit rester valide. Audit
        ``entity_type="milestone"`` dans le REGISTRE, une ligne par champ.

        Args:
            milestone_id: identifiant du jalon.
            changes: ``{champ: nouvelle valeur}`` (``status`` accepte une
                chaîne ou un :class:`~supplyscore.domain.milestones.MilestoneStatus`).
            source: origine de la mutation.
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            Les :class:`AuditEntry` créées, ``[]`` si aucun changement effectif.

        Raises:
            KeyError: si le jalon est inconnu du registre.
            ValueError: champ hors liste blanche, ``progress`` hors [0, 1] ou
                ``deadline_ts <= start_ts`` après application des changements
                (rien n'est alors écrit).
        """
        with self._lock:
            unknown = sorted(set(changes) - set(_MILESTONE_FIELDS))
            if unknown:
                raise ValueError(
                    "Champs de jalon hors liste blanche : "
                    + ", ".join(unknown)
                    + " (autorisés : "
                    + ", ".join(_MILESTONE_FIELDS)
                    + ")"
                )
            milestone = self._registry.get_milestone(milestone_id)
            if milestone is None:
                raise KeyError(f"Jalon inconnu : {milestone_id!r}")

            diff: list[tuple[str, Any, Any]] = []
            for field, value in changes.items():
                if field == "status":
                    value = MilestoneStatus(value)
                old = getattr(milestone, field)
                if old != value:
                    diff.append((field, old, value))
            if not diff:
                return []
            for field, _old, new in diff:
                setattr(milestone, field, new)

            errors: list[str] = []
            if "progress" in changes and not 0.0 <= milestone.progress <= 1.0:
                errors.append(f"progress hors [0, 1] : {milestone.progress}")
            if ("start_ts" in changes or "deadline_ts" in changes) and (
                milestone.deadline_ts <= milestone.start_ts
            ):
                errors.append(
                    f"deadline_ts ({milestone.deadline_ts}) <= start_ts ({milestone.start_ts})"
                )
            if errors:
                raise ValueError(
                    "Jalon invalide — aucune écriture effectuée : " + " ; ".join(errors)
                )

            entries: list[AuditEntry] = []
            with self._transaction(self._registry):
                for field, old, new in diff:
                    entries.append(
                        self._record(
                            self._registry_audit,
                            "milestone",
                            milestone_id,
                            field,
                            str(old) if isinstance(old, MilestoneStatus) else old,
                            str(new) if isinstance(new, MilestoneStatus) else new,
                            source,
                            operator_id,
                        )
                    )
                self._registry.save_milestone(milestone)
            return entries

    # --- Cahier des charges versionné -----------------------------------------------

    def save_spec_sheet(
        self, node_id: str, payload_json: str, source: str, operator_id: str = ""
    ) -> int:
        """Enregistre une nouvelle version du cahier des charges du nœud.

        L'audit (``entity_type="spec_sheet"``, ``field="version"``,
        ``old`` = version précédente ou ``None``, ``new`` = nouvelle version)
        est écrit dans la base CLIENT, dans la même transaction que l'INSERT.

        Args:
            node_id: identifiant du nœud.
            payload_json: contenu JSON du cahier des charges.
            source: origine de la mutation.
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            La version créée (auto-incrémentée par nœud, en commençant à 1).
        """
        with self._lock:
            client, trail = self._client_audit(node_id)
            with self._transaction(client):
                previous = client.latest_spec_sheet(node_id)
                old_version = previous[0] if previous is not None else None
                new_version = (old_version or 0) + 1
                self._record(
                    trail,
                    "spec_sheet",
                    node_id,
                    "version",
                    old_version,
                    new_version,
                    source,
                    operator_id,
                )
                version = client.save_spec_sheet(node_id, payload_json, source)
            if version != new_version:  # pragma: no cover — MAX+1 calculé sous le même verrou
                raise RuntimeError(
                    f"Version de cahier des charges incohérente :"
                    f" audit {new_version}, base {version}"
                )
            return version

    # --- Corrections d'évaluations ----------------------------------------------------

    def replace_assessment(
        self, node_id: str, old_id: int, new: AHPAssessment, operator_id: str = ""
    ) -> int:
        """Corrige une évaluation AHP : insère ``new`` en remplacement de ``old_id``.

        L'évaluation originale reste dans l'historique (``list_assessments``)
        mais est exclue de ``latest_assessment``. L'id audité n'existant
        qu'après l'INSERT, l'audit (``entity_type="assessment"``,
        ``field="replaces"``, ``old=old_id``, ``new`` = nouvel id,
        ``source="edit"``) est écrit juste après, sous le même verrou client.

        Args:
            node_id: identifiant du nœud évalué.
            old_id: id de l'évaluation corrigée (posé dans ``replaces_id``).
            new: évaluation corrective à insérer.
            operator_id: opérateur à l'origine de la correction.

        Returns:
            L'id de la nouvelle évaluation.
        """
        with self._lock:
            client, trail = self._client_audit(node_id)
            with client.lock:
                new_id = client.save_assessment(new, replaces_id=old_id)
                self._record(
                    trail, "assessment", node_id, "replaces", old_id, new_id, "edit", operator_id
                )
            return new_id

    # --- Aides internes ---------------------------------------------------------------

    def _client_audit(self, node_id: str) -> tuple[ClientDatabase, AuditTrail]:
        """Base client du nœud et son journal d'audit (cache léger).

        Le cache est invalidé si la fabrique retourne une autre instance que
        celle mémorisée (ex. éviction LRU côté orchestrateur) : le journal est
        alors reconstruit sur la nouvelle connexion, sous le nouveau verrou.

        Args:
            node_id: identifiant du nœud (= id de la base client).

        Returns:
            Le couple ``(ClientDatabase, AuditTrail)`` du nœud.
        """
        with self._lock:
            db = self._client_db_factory(node_id)
            cached = self._client_audits.get(node_id)
            if cached is not None and cached[0] is db:
                return cached
            pair = (db, AuditTrail(db.conn, self._clock, lock=db.lock))
            self._client_audits[node_id] = pair
            return pair

    @contextmanager
    def _transaction(self, db: RegistryDatabase | ClientDatabase) -> Iterator[None]:
        """Transaction explicite sur ``db`` : verrou + BEGIN, rollback sur erreur.

        Les méthodes ``save_*`` de la couche db commitent elles-mêmes en fin
        de bloc ``with conn:`` : appelées DANS cette transaction, elles
        commitent d'un coup tout ce qui précède (lignes d'audit incluses) —
        c'est le mécanisme d'atomicité « trace + écriture métier ». Toute
        exception avant ce commit annule l'ensemble.

        Args:
            db: base hôte (registre ou client) dont la connexion est utilisée.

        Yields:
            ``None`` — le corps du ``with`` s'exécute dans la transaction.
        """
        with db.lock:
            owns = not db.conn.in_transaction
            if owns:
                db.conn.execute("BEGIN")
            try:
                yield
            except BaseException:
                if owns and db.conn.in_transaction:
                    db.conn.rollback()
                raise
            if owns and db.conn.in_transaction:  # filet : si aucun save_* n'a commité
                db.conn.commit()

    def _record(
        self,
        trail: AuditTrail,
        entity_type: str,
        entity_id: str,
        field: str,
        old: Any,
        new: Any,
        source: str,
        operator_id: str,
    ) -> AuditEntry:
        """Écrit une ligne d'audit et la relit telle que persistée.

        La relecture (par id, parmi les entrées les plus récentes du champ)
        garantit que l'objet retourné reflète EXACTEMENT la ligne en base
        (id, horodatage, semaine ISO et valeurs JSON retypées).

        Args:
            trail: journal d'audit cible (registre ou client).
            entity_type: type d'entité auditée.
            entity_id: id de l'entité auditée.
            field: champ qualifié ("" si entité entière).
            old: valeur avant mutation.
            new: valeur après mutation.
            source: origine de la mutation.
            operator_id: opérateur à l'origine de la mutation.

        Returns:
            L':class:`AuditEntry` telle qu'insérée en base.
        """
        rid = trail.record(entity_type, entity_id, field, old, new, source, operator_id)
        for entry in trail.history(entity_type, entity_id, field=field, limit=_READBACK_LIMIT):
            if entry.id == rid:
                return entry
        raise RuntimeError(  # pragma: no cover — la ligne vient d'être insérée
            f"Ligne d'audit {rid} introuvable en relecture ({entity_type}/{entity_id}/{field})"
        )

    def _sync_repo_arc(self, arc: SupplyArc) -> None:
        """Synchronise l'arc dans le graphe en mémoire (remplacement complet).

        No-op si aucun ``repo`` n'est fourni ou si l'un des deux nœuds n'est
        pas chargé en mémoire. Un arc déjà présent est remplacé (suppression
        puis ré-ajout : la nature nominal/backup peut avoir changé).

        Args:
            arc: arc tel que persisté dans le registre.
        """
        if self._repo is None:
            return
        if self._repo.get_node(arc.source_id) is None or self._repo.get_node(arc.target_id) is None:
            return
        if self._repo.get_arc(arc.source_id, arc.target_id) is not None:
            self._repo.remove_arc(arc.source_id, arc.target_id)
        self._repo.add_arc(arc)
