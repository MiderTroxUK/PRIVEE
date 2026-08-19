"""Moteur d'evenements supply chain - application et annulation transactionnelles (E6, Lot 6.1).

:class:`EventEngine` orchestre le cycle de vie d'un evenement declare pendant
le rituel hebdomadaire :

- :meth:`EventEngine.preview` : calcul PUR des impacts calibres
  (:func:`~supplyscore.domain.events.compute_impacts`) - rien n'est ecrit ;
- :meth:`EventEngine.apply` : UNE operation coherente - ligne ``events`` dans
  la base CLIENT du noeud, mutation des KPIs via
  :class:`~supplyscore.services.mutations.MutationService`
  (``source="event:<id>"``), puis reevaluation complete du reseau ;
- :meth:`EventEngine.revert` : annulation tout-ou-rien - chaque KPI touche doit
  encore valoir la valeur posee par l'evenement (tolerance
  :data:`REVERT_TOLERANCE`), sinon :class:`ConflictError` et AUCUNE
  restauration partielle ;
- :meth:`EventEngine.open_events` / :meth:`EventEngine.list_week` : relecture
  pour la relance hebdomadaire et la revue de la semaine ;
- :meth:`EventEngine.apply_weekly_decay` : " rien a signaler " - decroissance
  bayesienne hebdomadaire (``source="weekly"``).

Coherence des ecritures : la ligne ``events`` (trace du declaratif) est ecrite
d'abord ; si la mutation des KPIs echoue ensuite, la ligne est retiree par
compensation - il ne peut donc pas exister d'evenement journalise dont les
impacts n'auraient pas ete appliques. Un evenement sans aucun impact (tous
" ignorer ") est journalise quand meme, sans mutation de KPI. L'horodatage et
la semaine ISO proviennent de l'horloge du PROJET du noeud (reelle ou de jeu).
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

if TYPE_CHECKING:  # import differe : evite tout cycle services.events <-> orchestrator
    from supplyscore.services.orchestrator import SupplyScoreService

#: Tolerance absolue pour juger qu'un KPI n'a PAS ete reecrit depuis l'evenement.
REVERT_TOLERANCE: float = 1e-12


class ConflictError(Exception):
    """Annulation impossible : des champs ont ete reecrits depuis l'evenement.

    Attributes:
        champs: chemins qualifies des KPIs dont la valeur courante ne
            correspond plus a celle posee par l'evenement.
    """

    def __init__(self, champs: list[str]) -> None:
        """Initialise l'erreur avec la liste des champs divergents.

        Args:
            champs: chemins qualifies des KPIs divergents (ex.
                ``"risk.failure_probability"``).
        """
        self.champs = list(champs)
        super().__init__(
            "Annulation impossible — champs réécrits depuis l'événement : " + ", ".join(self.champs)
        )


@dataclass(frozen=True)
class SupplyEvent:
    """Evenement supply chain tel que journalise dans la base CLIENT du noeud.

    Attributes:
        id: identifiant unique (UUID4).
        node_id: noeud declarant.
        event_type: cle de :data:`~supplyscore.domain.events.EVENT_CALIBRATION`.
        iso_week: semaine ISO de declaration (horloge du PROJET du noeud).
        occurred_at: instant de declaration, en secondes epoch.
        params: parametres saisis (valides par ``compute_impacts``).
        impacts: impacts calibres appliques aux KPIs.
        reverted_at: instant d'annulation, ``None`` si l'evenement est ouvert.
        operator_id: operateur declarant.
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
    """Lit la valeur d'un KPI par son chemin qualifie ``bloc.champ``."""
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
    """Moteur d'evenements : previsualisation, application et annulation.

    Toutes les ecritures passent par :class:`~supplyscore.services.mutations.MutationService`
    (diff + validation + audit) et par la couche db (table ``events`` de la
    base CLIENT du noeud) ; le moteur n'ecrit jamais un KPI directement.

    Thread-safety : les methodes mutantes prennent ``self._lock`` (RLock),
    ce qui serialise les cycles lecture-verification-ecriture du moteur
    (les services sous-jacents gardent leurs propres verrous).
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le moteur sur la facade de l'application.

        Args:
            service: facade :class:`~supplyscore.services.orchestrator.SupplyScoreService`
                (registre, bases client, mutations, horloges, pipeline).
        """
        self._service = service
        self._lock = threading.RLock()

    # Lecture / previsualisation

    def preview(
        self, node_id: str, event_type: str, params: Mapping[str, object]
    ) -> list[KpiImpact]:
        """Previsualise les impacts d'un evenement sur les KPIs courants du noeud.

        Methode PURE : les impacts sont calcules par
        :func:`~supplyscore.domain.events.compute_impacts` sur une lecture
        fraiche du noeud - rien n'est ecrit, le bundle du noeud n'est pas
        modifie.

        Args:
            node_id: identifiant du noeud declarant.
            event_type: cle de :data:`~supplyscore.domain.events.EVENT_CALIBRATION`.
            params: parametres saisis, conformes aux ``fields`` de l'EventSpec.

        Returns:
            La liste des impacts calibres (eventuellement vide si tous les
            KPIs sources sont " a ignorer ").

        Raises:
            KeyError: si le noeud est inconnu du registre.
            ValueError: type d'evenement inconnu ou parametre invalide.
        """
        node = self._node(node_id)
        return compute_impacts(event_type, params, node.kpis)

    def open_events(self, node_id: str) -> list[SupplyEvent]:
        """Evenements non annules du noeud, les plus recents d'abord.

        C'est la liste relancee a chaque revue hebdomadaire : un evenement
        reste " ouvert " tant qu'il n'a pas ete annule.

        Args:
            node_id: identifiant du noeud.

        Returns:
            Les :class:`SupplyEvent` ouverts, du plus recent au plus ancien.
        """
        client = self._service.client_db(node_id)
        rows = [row for row in client.list_events(node_id) if row["reverted_at"] is None]
        return [_event_from_row(row) for row in reversed(rows)]

    def list_week(self, node_id: str, iso_week: str) -> list[SupplyEvent]:
        """Evenements du noeud declares pendant une semaine ISO donnee.

        Annules inclus (la revue de la semaine montre tout le declaratif),
        en ordre chronologique.

        Args:
            node_id: identifiant du noeud.
            iso_week: semaine ISO filtree, ex. ``"2026-S24"``.

        Returns:
            Les :class:`SupplyEvent` de la semaine, du plus ancien au plus recent.
        """
        client = self._service.client_db(node_id)
        return [_event_from_row(row) for row in client.list_events(node_id, iso_week)]

    # Ecriture

    def apply(
        self,
        node_id: str,
        event_type: str,
        params: Mapping[str, object],
        operator_id: str = "",
        notes: str = "",
    ) -> SupplyEvent:
        """Applique un evenement : journalisation + mutation des KPIs + reevaluation.

        Deroulement (une operation coherente) :

        1. :meth:`preview` - validation des parametres et calcul des impacts,
           AVANT toute ecriture ;
        2. ligne ``events`` dans la base CLIENT (params/impacts serialises
           JSON, ``iso_week`` et ``occurred_at`` poses par l'horloge du PROJET
           du noeud, id UUID4), puis ``mutations.update_kpis`` avec
           ``source="event:<id>"`` - si la mutation echoue, la ligne ``events``
           est retiree (compensation : pas de trace orpheline) ;
        3. ``service.evaluate_all(persist=True)`` - les scores du reseau
           integrent immediatement l'evenement.

        Un evenement sans aucun impact (tous " ignorer ") est journalise quand
        meme - trace du declaratif - sans mutation de KPI.

        Args:
            node_id: identifiant du noeud declarant.
            event_type: cle de :data:`~supplyscore.domain.events.EVENT_CALIBRATION`.
            params: parametres saisis, conformes aux ``fields`` de l'EventSpec.
            operator_id: operateur declarant.
            notes: commentaire libre journalise avec l'evenement.

        Returns:
            Le :class:`SupplyEvent` journalise (``reverted_at=None``).

        Raises:
            KeyError: si le noeud est inconnu du registre.
            ValueError: type d'evenement inconnu ou parametre invalide
                (rien n'est alors ecrit).
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
                # Compensation : aucune ligne events orpheline si la mutation echoue.
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
        """Annule un evenement : restauration tout-ou-rien des KPIs touches.

        Pour CHAQUE impact de l'evenement, la valeur courante du KPI doit
        encore valoir ``impact.new`` (tolerance :data:`REVERT_TOLERANCE`) -
        sinon le champ est en conflit. S'il existe NE SERAIT-CE QU'UN conflit,
        :class:`ConflictError` est levee et RIEN n'est restaure (pas de
        restauration partielle silencieuse). Sinon : les anciennes valeurs
        sont restaurees via ``mutations.update_kpis``
        (``source="revert:<id>"``), l'evenement est marque annule a l'instant
        de l'horloge du PROJET, puis le reseau est reevalue.

        Args:
            event_id: identifiant de l'evenement a annuler.
            node_id: noeud porteur de l'evenement.
            operator_id: operateur a l'origine de l'annulation.

        Returns:
            Les impacts restaures (ceux de l'evenement).

        Raises:
            ValueError: evenement inconnu pour ce noeud, ou deja annule.
            ConflictError: au moins un KPI a ete reecrit depuis l'evenement
                (le message liste les champs divergents) ; rien n'est restaure.
            KeyError: si le noeud est inconnu du registre.
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
        """Decroissance hebdomadaire " rien a signaler " sur les KPIs du noeud.

        Les impacts viennent de :func:`~supplyscore.domain.events.weekly_decay`
        (revision bayesienne " semaine sans incident ") et sont appliques via
        ``mutations.update_kpis`` avec ``source="weekly"`` - aucun s'il n'y a
        rien a eroder.

        Args:
            node_id: identifiant du noeud.
            operator_id: operateur a l'origine de la confirmation hebdo.

        Returns:
            Les impacts appliques (``[]`` si le KPI source est non renseigne).

        Raises:
            KeyError: si le noeud est inconnu du registre.
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

    # Aides internes

    def _node(self, node_id: str) -> SupplyNode:
        """Lecture fraiche du noeud depuis le registre (KeyError si inconnu)."""
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        return node

    def _clock_of(self, node: SupplyNode) -> Clock:
        """Horloge effective du noeud : celle de SON projet (reelle ou de jeu)."""
        if node.project_id:
            return self._service.clock_for(node.project_id)
        return self._service.clock
