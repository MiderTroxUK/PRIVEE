"""Moteur d'événements supply chain — application et annulation transactionnelles (E6, Lot 6.1).

:class:`EventEngine` orchestre le cycle de vie d'un événement déclaré pendant
le rituel hebdomadaire :

- :meth:`EventEngine.preview` : calcul PUR des impacts calibrés
  (:func:`~supplyscore.domain.events.compute_impacts`) — rien n'est écrit ;
- :meth:`EventEngine.apply` : UNE opération cohérente — ligne ``events`` dans
  la base CLIENT du nœud, mutation des KPIs via
  :class:`~supplyscore.services.mutations.MutationService`
  (``source="event:<id>"``), puis réévaluation complète du réseau ;
- :meth:`EventEngine.revert` : annulation tout-ou-rien — chaque KPI touché doit
  encore valoir la valeur posée par l'événement (tolérance
  :data:`REVERT_TOLERANCE`), sinon :class:`ConflictError` et AUCUNE
  restauration partielle ;
- :meth:`EventEngine.open_events` / :meth:`EventEngine.list_week` : relecture
  pour la relance hebdomadaire et la revue de la semaine ;
- :meth:`EventEngine.apply_weekly_decay` : « rien à signaler » — décroissance
  bayésienne hebdomadaire (``source="weekly"``).

Cohérence des écritures : la ligne ``events`` (trace du déclaratif) est écrite
d'abord ; si la mutation des KPIs échoue ensuite, la ligne est retirée par
compensation — il ne peut donc pas exister d'événement journalisé dont les
impacts n'auraient pas été appliqués. Un événement sans aucun impact (tous
« ignorer ») est journalisé quand même, sans mutation de KPI. L'horodatage et
la semaine ISO proviennent de l'horloge du PROJET du nœud (réelle ou de jeu).
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, cast

from supplyscore.core.clock import Clock, iso_week
from supplyscore.domain.events import KpiImpact, compute_impacts, weekly_decay
from supplyscore.domain.models import KPIBundle, SupplyNode

if TYPE_CHECKING:  # import différé : évite tout cycle services.events <-> orchestrator
    from supplyscore.services.orchestrator import SupplyScoreService

#: Tolérance absolue pour juger qu'un KPI n'a PAS été réécrit depuis l'événement.
REVERT_TOLERANCE: float = 1e-12


class ConflictError(Exception):
    """Annulation impossible : des champs ont été réécrits depuis l'événement.

    Attributes:
        champs: chemins qualifiés des KPIs dont la valeur courante ne
            correspond plus à celle posée par l'événement.
    """

    def __init__(self, champs: list[str]) -> None:
        """Initialise l'erreur avec la liste des champs divergents.

        Args:
            champs: chemins qualifiés des KPIs divergents (ex.
                ``"risk.failure_probability"``).
        """
        self.champs = list(champs)
        super().__init__(
            "Annulation impossible — champs réécrits depuis l'événement : " + ", ".join(self.champs)
        )


@dataclass(frozen=True)
class SupplyEvent:
    """Événement supply chain tel que journalisé dans la base CLIENT du nœud.

    Attributes:
        id: identifiant unique (UUID4).
        node_id: nœud déclarant.
        event_type: clé de :data:`~supplyscore.domain.events.EVENT_CALIBRATION`.
        iso_week: semaine ISO de déclaration (horloge du PROJET du nœud).
        occurred_at: instant de déclaration, en secondes epoch.
        params: paramètres saisis (validés par ``compute_impacts``).
        impacts: impacts calibrés appliqués aux KPIs.
        reverted_at: instant d'annulation, ``None`` si l'événement est ouvert.
        operator_id: opérateur déclarant.
        notes: commentaire libre.
    """

    id: str
    node_id: str
    event_type: str
    iso_week: str
    occurred_at: float
    params: dict[str, Any]
    impacts: list[KpiImpact]
    reverted_at: float | None
    operator_id: str
    notes: str


def _kpi_value(kpis: KPIBundle, kpi_path: str) -> float | None:
    """Lit la valeur d'un KPI par son chemin qualifié ``bloc.champ``."""
    block_name, _, field_name = kpi_path.partition(".")
    return cast(float | None, getattr(getattr(kpis, block_name), field_name))


def _event_from_row(row: Mapping[str, Any]) -> SupplyEvent:
    """Reconstruit un :class:`SupplyEvent` depuis une ligne de la table ``events``."""
    return SupplyEvent(
        id=row["id"],
        node_id=row["node_id"],
        event_type=row["event_type"],
        iso_week=row["iso_week"],
        occurred_at=row["occurred_at"],
        params=json.loads(row["params_json"]),
        impacts=[KpiImpact(**raw) for raw in json.loads(row["impacts_json"])],
        reverted_at=row["reverted_at"],
        operator_id=row["operator_id"],
        notes=row["notes"],
    )


class EventEngine:
    """Moteur d'événements : prévisualisation, application et annulation.

    Toutes les écritures passent par :class:`~supplyscore.services.mutations.MutationService`
    (diff + validation + audit) et par la couche db (table ``events`` de la
    base CLIENT du nœud) ; le moteur n'écrit jamais un KPI directement.

    Thread-safety : les méthodes mutantes prennent ``self._lock`` (RLock),
    ce qui sérialise les cycles lecture-vérification-écriture du moteur
    (les services sous-jacents gardent leurs propres verrous).
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le moteur sur la façade de l'application.

        Args:
            service: façade :class:`~supplyscore.services.orchestrator.SupplyScoreService`
                (registre, bases client, mutations, horloges, pipeline).
        """
        self._service = service
        self._lock = threading.RLock()

    # --- Lecture / prévisualisation ---------------------------------------------------

    def preview(
        self, node_id: str, event_type: str, params: Mapping[str, object]
    ) -> list[KpiImpact]:
        """Prévisualise les impacts d'un événement sur les KPIs courants du nœud.

        Méthode PURE : les impacts sont calculés par
        :func:`~supplyscore.domain.events.compute_impacts` sur une lecture
        fraîche du nœud — rien n'est écrit, le bundle du nœud n'est pas
        modifié.

        Args:
            node_id: identifiant du nœud déclarant.
            event_type: clé de :data:`~supplyscore.domain.events.EVENT_CALIBRATION`.
            params: paramètres saisis, conformes aux ``fields`` de l'EventSpec.

        Returns:
            La liste des impacts calibrés (éventuellement vide si tous les
            KPIs sources sont « à ignorer »).

        Raises:
            KeyError: si le nœud est inconnu du registre.
            ValueError: type d'événement inconnu ou paramètre invalide.
        """
        node = self._node(node_id)
        return compute_impacts(event_type, params, node.kpis)

    def open_events(self, node_id: str) -> list[SupplyEvent]:
        """Événements non annulés du nœud, les plus récents d'abord.

        C'est la liste relancée à chaque revue hebdomadaire : un événement
        reste « ouvert » tant qu'il n'a pas été annulé.

        Args:
            node_id: identifiant du nœud.

        Returns:
            Les :class:`SupplyEvent` ouverts, du plus récent au plus ancien.
        """
        client = self._service.client_db(node_id)
        rows = [row for row in client.list_events(node_id) if row["reverted_at"] is None]
        return [_event_from_row(row) for row in reversed(rows)]

    def list_week(self, node_id: str, iso_week: str) -> list[SupplyEvent]:
        """Événements du nœud déclarés pendant une semaine ISO donnée.

        Annulés inclus (la revue de la semaine montre tout le déclaratif),
        en ordre chronologique.

        Args:
            node_id: identifiant du nœud.
            iso_week: semaine ISO filtrée, ex. ``"2026-S24"``.

        Returns:
            Les :class:`SupplyEvent` de la semaine, du plus ancien au plus récent.
        """
        client = self._service.client_db(node_id)
        return [_event_from_row(row) for row in client.list_events(node_id, iso_week)]

    # --- Écriture ----------------------------------------------------------------------

    def apply(
        self,
        node_id: str,
        event_type: str,
        params: Mapping[str, object],
        operator_id: str = "",
        notes: str = "",
    ) -> SupplyEvent:
        """Applique un événement : journalisation + mutation des KPIs + réévaluation.

        Déroulement (une opération cohérente) :

        1. :meth:`preview` — validation des paramètres et calcul des impacts,
           AVANT toute écriture ;
        2. ligne ``events`` dans la base CLIENT (params/impacts sérialisés
           JSON, ``iso_week`` et ``occurred_at`` posés par l'horloge du PROJET
           du nœud, id UUID4), puis ``mutations.update_kpis`` avec
           ``source="event:<id>"`` — si la mutation échoue, la ligne ``events``
           est retirée (compensation : pas de trace orpheline) ;
        3. ``service.evaluate_all(persist=True)`` — les scores du réseau
           intègrent immédiatement l'événement.

        Un événement sans aucun impact (tous « ignorer ») est journalisé quand
        même — trace du déclaratif — sans mutation de KPI.

        Args:
            node_id: identifiant du nœud déclarant.
            event_type: clé de :data:`~supplyscore.domain.events.EVENT_CALIBRATION`.
            params: paramètres saisis, conformes aux ``fields`` de l'EventSpec.
            operator_id: opérateur déclarant.
            notes: commentaire libre journalisé avec l'événement.

        Returns:
            Le :class:`SupplyEvent` journalisé (``reverted_at=None``).

        Raises:
            KeyError: si le nœud est inconnu du registre.
            ValueError: type d'événement inconnu ou paramètre invalide
                (rien n'est alors écrit).
        """
        with self._lock:
            impacts = self.preview(node_id, event_type, params)
            node = self._node(node_id)
            clock = self._clock_of(node)
            occurred_at = clock.now()
            week = iso_week(occurred_at)
            event_id = str(uuid.uuid4())

            client = self._service.client_db(node_id)
            client.save_event(
                event_id=event_id,
                node_id=node_id,
                event_type=event_type,
                iso_week=week,
                occurred_at=occurred_at,
                params_json=json.dumps(dict(params)),
                impacts_json=json.dumps([asdict(impact) for impact in impacts]),
                operator_id=operator_id,
                notes=notes,
            )
            try:
                if impacts:
                    self._service.mutations.update_kpis(
                        node_id,
                        {impact.kpi_path: impact.new for impact in impacts},
                        source=f"event:{event_id}",
                        operator_id=operator_id,
                    )
            except BaseException:
                # Compensation : aucune ligne events orpheline si la mutation échoue.
                with client.lock, client.conn:
                    client.conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
                raise

            self._service.evaluate_all(persist=True)
            return SupplyEvent(
                id=event_id,
                node_id=node_id,
                event_type=event_type,
                iso_week=week,
                occurred_at=occurred_at,
                params=dict(params),
                impacts=impacts,
                reverted_at=None,
                operator_id=operator_id,
                notes=notes,
            )

    def revert(self, event_id: str, node_id: str, operator_id: str = "") -> list[KpiImpact]:
        """Annule un événement : restauration tout-ou-rien des KPIs touchés.

        Pour CHAQUE impact de l'événement, la valeur courante du KPI doit
        encore valoir ``impact.new`` (tolérance :data:`REVERT_TOLERANCE`) —
        sinon le champ est en conflit. S'il existe NE SERAIT-CE QU'UN conflit,
        :class:`ConflictError` est levée et RIEN n'est restauré (pas de
        restauration partielle silencieuse). Sinon : les anciennes valeurs
        sont restaurées via ``mutations.update_kpis``
        (``source="revert:<id>"``), l'événement est marqué annulé à l'instant
        de l'horloge du PROJET, puis le réseau est réévalué.

        Args:
            event_id: identifiant de l'événement à annuler.
            node_id: nœud porteur de l'événement.
            operator_id: opérateur à l'origine de l'annulation.

        Returns:
            Les impacts restaurés (ceux de l'événement).

        Raises:
            ValueError: événement inconnu pour ce nœud, ou déjà annulé.
            ConflictError: au moins un KPI a été réécrit depuis l'événement
                (le message liste les champs divergents) ; rien n'est restauré.
            KeyError: si le nœud est inconnu du registre.
        """
        with self._lock:
            client = self._service.client_db(node_id)
            row = next(
                (r for r in client.list_events(node_id) if r["id"] == event_id),
                None,
            )
            if row is None:
                raise ValueError(f"Événement inconnu pour le nœud {node_id!r} : {event_id!r}")
            if row["reverted_at"] is not None:
                raise ValueError(f"Événement déjà annulé : {event_id!r}")

            node = self._node(node_id)
            event = _event_from_row(row)
            conflits = [
                impact.kpi_path
                for impact in event.impacts
                if (current := _kpi_value(node.kpis, impact.kpi_path)) is None
                or abs(current - impact.new) > REVERT_TOLERANCE
            ]
            if conflits:
                raise ConflictError(conflits)

            if event.impacts:
                self._service.mutations.update_kpis(
                    node_id,
                    {impact.kpi_path: impact.old for impact in event.impacts},
                    source=f"revert:{event_id}",
                    operator_id=operator_id,
                )
            client.mark_reverted(event_id, self._clock_of(node).now())
            self._service.evaluate_all(persist=True)
            return event.impacts

    def apply_weekly_decay(self, node_id: str, operator_id: str = "") -> list[KpiImpact]:
        """Décroissance hebdomadaire « rien à signaler » sur les KPIs du nœud.

        Les impacts viennent de :func:`~supplyscore.domain.events.weekly_decay`
        (révision bayésienne « semaine sans incident ») et sont appliqués via
        ``mutations.update_kpis`` avec ``source="weekly"`` — aucun s'il n'y a
        rien à éroder.

        Args:
            node_id: identifiant du nœud.
            operator_id: opérateur à l'origine de la confirmation hebdo.

        Returns:
            Les impacts appliqués (``[]`` si le KPI source est non renseigné).

        Raises:
            KeyError: si le nœud est inconnu du registre.
        """
        with self._lock:
            node = self._node(node_id)
            impacts = weekly_decay(node.kpis)
            if impacts:
                self._service.mutations.update_kpis(
                    node_id,
                    {impact.kpi_path: impact.new for impact in impacts},
                    source="weekly",
                    operator_id=operator_id,
                )
            return impacts

    # --- Aides internes ----------------------------------------------------------------

    def _node(self, node_id: str) -> SupplyNode:
        """Lecture fraîche du nœud depuis le registre (KeyError si inconnu)."""
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        return node

    def _clock_of(self, node: SupplyNode) -> Clock:
        """Horloge effective du nœud : celle de SON projet (réelle ou de jeu)."""
        if node.project_id:
            return self._service.clock_for(node.project_id)
        return self._service.clock
