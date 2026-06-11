"""Cycle hebdomadaire ISO — fraîcheur des évaluations AHP par nœud (information seule).

Définitions figées du lot 4.1 :

- la « semaine » d'une évaluation ``e`` est ``iso_week(e.timestamp)`` au format
  « AAAA-Sxx » (semaine ISO en heure locale) ; la « semaine courante » d'un
  nœud est celle de l'horloge de SON projet
  (:meth:`SupplyScoreService.clock_for`) ;
- **à jour** : le nœud a au moins une évaluation AHP dont ``iso_week`` est la
  semaine courante du projet ;
- **en retard** : la dernière évaluation date d'une semaine strictement
  antérieure ; ``semaines_de_retard`` est le nombre de semaines ISO d'écart
  (différence des lundis de chaque semaine, divisée par 7 jours) ;
- **manquant** : le nœud n'a aucune évaluation ;
- les nœuds DONE/ABANDONED sont EXCLUS du décompte de couverture, mais
  :meth:`CycleHebdomadaire.statut_noeud` répond quand même pour eux.

AUCUNE dégradation automatique du Ud, aucun e-mail : :class:`CycleHebdomadaire`
ne fait que CONSTATER l'état du cycle hebdomadaire à destination de l'UI.

Lot 6.2 : :class:`WeeklyReview` ajoute la revue hebdomadaire GUIDÉE d'un nœud
en quatre volets (:data:`VOLETS`) — diff KPI d'une semaine à l'autre
(:meth:`WeeklyReview.kpi_diff`), confirmations « rien n'a changé » (bloc KPI,
jalon) et suivi de progression (``start``/``mark_volet``/``complete``)
persisté dans la table ``weekly_reviews`` de la base CLIENT du nœud. Toutes
les dates proviennent de l'horloge du PROJET du nœud (réelle ou de jeu).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from supplyscore.core.clock import iso_week
from supplyscore.data.audit import AuditTrail
from supplyscore.domain.constraints import kpi_unit
from supplyscore.domain.models import TaskStatus

if TYPE_CHECKING:
    from supplyscore.core.clock import Clock
    from supplyscore.domain.models import SupplyNode
    from supplyscore.services.orchestrator import SupplyScoreService


class StatutHebdo(StrEnum):
    """Statut hebdomadaire d'un nœud vis-à-vis de son évaluation AHP."""

    A_JOUR = "a_jour"
    EN_RETARD = "en_retard"
    MANQUANT = "manquant"


@dataclass(frozen=True)
class EtatHebdo:
    """État hebdomadaire d'un nœud : statut, semaines et retard éventuel.

    Attributes:
        statut: position du nœud dans le cycle (à jour / en retard / manquant).
        semaine_courante: semaine ISO « AAAA-Sxx » de l'horloge du projet.
        derniere_semaine: semaine de la dernière évaluation, None si aucune.
        semaines_de_retard: nombre de semaines ISO de retard (0 si à jour ou
            manquant).
    """

    statut: StatutHebdo
    semaine_courante: str
    derniere_semaine: str | None
    semaines_de_retard: int


def _lundi(week: str) -> datetime:
    """Lundi (minuit, naïf) de la semaine ISO libellée « AAAA-Sxx ».

    Args:
        week: libellé « AAAA-Sxx », ex. « 2026-S05 ».

    Returns:
        ``datetime.fromisocalendar(année, semaine, 1)``.

    Raises:
        ValueError: si le libellé n'est pas de la forme « AAAA-Sxx » ou si la
            semaine n'existe pas dans l'année ISO donnée.
    """
    year_str, sep, num_str = week.partition("-S")
    if not sep or not year_str.isdigit() or not num_str.isdigit():
        raise ValueError(f"libellé de semaine ISO invalide : {week!r} (attendu « AAAA-Sxx »)")
    return datetime.fromisocalendar(int(year_str), int(num_str), 1)


def semaines_ecart(week_a: str, week_b: str) -> int:
    """Nombre de semaines ISO entre deux libellés « AAAA-Sxx » (``b − a``).

    Calculé via ``datetime.fromisocalendar(année, semaine, 1)`` : différence
    des lundis des deux semaines, divisée par 7 jours. Positif (``>= 0``) si
    ``week_b`` est postérieure ou égale à ``week_a``, négatif sinon. Les bords
    d'année ISO sont exacts, ex. ``("2020-S53", "2021-S01") -> 1``.

    Args:
        week_a: semaine de départ, ex. « 2026-S24 ».
        week_b: semaine d'arrivée, ex. « 2026-S26 ».

    Returns:
        L'écart en semaines ISO entières (``b − a``).
    """
    return (_lundi(week_b) - _lundi(week_a)).days // 7


class CycleHebdomadaire:
    """Suivi du cycle hebdomadaire ISO des évaluations AHP d'un réseau.

    S'appuie sur la façade :class:`SupplyScoreService` : le registre fournit
    les nœuds et l'horloge effective de chaque projet (réelle ou de jeu via
    ``clock_for``), les bases client fournissent les semaines d'évaluation
    matérialisées (colonne ``assessments.iso_week``).
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le cycle hebdomadaire au-dessus de la façade.

        Args:
            service: façade applicative (registre, bases client, horloges).
        """
        self._service = service

    def _semaine_courante(self, project_id: str | None) -> str:
        """Semaine ISO courante selon l'horloge du projet (ou l'horloge réelle).

        Args:
            project_id: projet dont l'horloge fait foi ; None ou vide ->
                horloge par défaut du service.

        Returns:
            Libellé « AAAA-Sxx » de la semaine courante.
        """
        clock = self._service.clock_for(project_id) if project_id else self._service.clock
        return iso_week(clock.now())

    def _etat(self, node_id: str, semaine_courante: str) -> EtatHebdo:
        """Construit l'EtatHebdo du nœud pour une semaine courante donnée.

        Args:
            node_id: identifiant du nœud.
            semaine_courante: semaine ISO de référence (« AAAA-Sxx »).

        Returns:
            L'état hebdomadaire du nœud (statut, semaines, retard).
        """
        derniere = self._service.client_db(node_id).last_assessment_week(node_id)
        if derniere is None:
            return EtatHebdo(StatutHebdo.MANQUANT, semaine_courante, None, 0)
        retard = semaines_ecart(derniere, semaine_courante)
        if retard <= 0:
            # Évaluation de la semaine courante (ou, garde-fou, d'une semaine
            # postérieure si l'horloge a reculé) : le nœud est à jour.
            return EtatHebdo(StatutHebdo.A_JOUR, semaine_courante, derniere, 0)
        return EtatHebdo(StatutHebdo.EN_RETARD, semaine_courante, derniere, retard)

    def statut_noeud(self, node_id: str) -> EtatHebdo:
        """État hebdomadaire d'un nœud (répond aussi pour DONE/ABANDONED).

        Args:
            node_id: identifiant du nœud (doit exister dans le registre).

        Returns:
            L'état hebdomadaire du nœud, semaine courante = celle de l'horloge
            de SON projet.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise ValueError(f"nœud inconnu du registre : {node_id!r}")
        return self._etat(node_id, self._semaine_courante(node.project_id))

    def synthese(self, project_id: str) -> dict[str, EtatHebdo]:
        """États hebdomadaires de TOUS les nœuds du projet (statuts confondus).

        Args:
            project_id: identifiant du projet.

        Returns:
            ``node_id -> EtatHebdo``, la semaine courante (commune) étant celle
            de l'horloge du projet.
        """
        semaine = self._semaine_courante(project_id)
        return {
            node.id: self._etat(node.id, semaine)
            for node in self._service.registry.list_nodes(project_id)
        }

    def couverture(self, project_id: str) -> tuple[int, int]:
        """Couverture hebdomadaire du projet : ``(nœuds à jour, total actifs)``.

        Seuls les nœuds ACTIVE comptent : les nœuds DONE/ABANDONED sont exclus
        du numérateur comme du dénominateur.

        Args:
            project_id: identifiant du projet.

        Returns:
            Le couple ``(nombre de nœuds actifs à jour, nombre de nœuds actifs)``.
        """
        semaine = self._semaine_courante(project_id)
        actifs = [
            node
            for node in self._service.registry.list_nodes(project_id)
            if node.status is TaskStatus.ACTIVE
        ]
        a_jour = sum(
            1 for node in actifs if self._etat(node.id, semaine).statut is StatutHebdo.A_JOUR
        )
        return (a_jour, len(actifs))


# --- Revue hebdomadaire guidée (Lot 6.2) ---------------------------------------------

#: Les quatre volets de la revue hebdomadaire, dans l'ordre du déroulé.
VOLETS: tuple[str, ...] = ("ahp", "kpis", "jalons", "evenements")


@dataclass(frozen=True)
class KpiRow:
    """Ligne du diff KPI hebdomadaire : valeur précédente vs valeur courante.

    Attributes:
        path: chemin qualifié du KPI, ex. ``"time.lead_time_h"``.
        label_fr: libellé français du champ (depuis ``KPI_FIELDS`` de la page
            questionnaire ; le chemin sert de repli si le libellé est vide).
        unit: unité d'affichage (:func:`supplyscore.domain.constraints.kpi_unit`).
        previous: valeur du KPI en fin de semaine PRÉCÉDENTE — dernier snapshot
            KPI antérieur au lundi 00:00 (heure locale) de la semaine courante
            du projet ; None si aucun snapshot ou champ non renseigné.
        current: valeur courante du KPI sur le nœud, None si non renseignée.
    """

    path: str
    label_fr: str
    unit: str
    previous: float | None
    current: float | None


def _kpi_fields() -> list[tuple[str, str]]:
    """Chemins et libellés français des KPIs saisissables, ordre du questionnaire.

    Import DIFFÉRÉ de ``KPI_FIELDS`` : la page questionnaire importe elle-même
    ce module — un import au niveau module créerait un cycle.

    Returns:
        La liste aplatie ``[(chemin, libellé), ...]`` de tous les blocs.
    """
    from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS

    return [(path, label) for _bloc, fields in KPI_FIELDS for path, label in fields]


class WeeklyReview:
    """Revue hebdomadaire guidée d'un nœud : quatre volets, diff KPI, confirmations.

    S'appuie sur la façade :class:`SupplyScoreService` : l'horloge effective du
    projet du nœud (``clock_for``) date toutes les écritures, la base CLIENT du
    nœud porte l'état de la revue (table ``weekly_reviews``), les snapshots KPI
    (``kpis_at``) et les lignes d'audit de confirmation ; les jalons passent
    par :class:`~supplyscore.services.mutations.MutationService`.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise la revue hebdomadaire au-dessus de la façade.

        Args:
            service: façade applicative (registre, bases client, mutations,
                horloges).
        """
        self._service = service

    # -- aides internes --

    def _node(self, node_id: str) -> SupplyNode:
        """Lecture fraîche du nœud depuis le registre.

        Args:
            node_id: identifiant du nœud.

        Returns:
            Le :class:`~supplyscore.domain.models.SupplyNode` du registre.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise ValueError(f"nœud inconnu du registre : {node_id!r}")
        return node

    def _clock_of(self, node: SupplyNode) -> Clock:
        """Horloge effective du nœud : celle de SON projet (réelle ou de jeu)."""
        if node.project_id:
            return self._service.clock_for(node.project_id)
        return self._service.clock

    # -- lecture --

    def week_of(self, node_id: str) -> str:
        """Semaine ISO courante du PROJET du nœud (« AAAA-Sxx »).

        Args:
            node_id: identifiant du nœud.

        Returns:
            Le libellé de la semaine courante selon l'horloge du projet.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._node(node_id)
        return iso_week(self._clock_of(node).now())

    def kpi_diff(self, node_id: str) -> list[KpiRow]:
        """Diff KPI de la semaine : valeur de fin de semaine précédente vs courante.

        Couvre TOUS les champs de ``KPI_FIELDS`` (ordre du questionnaire). La
        valeur précédente est lue par ``ClientDatabase.kpis_at`` au lundi 00:00
        (heure locale, ``datetime.fromisocalendar``) de la semaine courante du
        projet : c'est le dernier snapshot KPI posé avant le début de la
        semaine, donc l'état en fin de semaine précédente. La valeur courante
        est celle du nœud (lecture fraîche du registre).

        Args:
            node_id: identifiant du nœud.

        Returns:
            Une :class:`KpiRow` par champ de ``KPI_FIELDS``, dans l'ordre.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._node(node_id)
        semaine = iso_week(self._clock_of(node).now())
        t_debut = _lundi(semaine).timestamp()
        previous_bundle = self._service.client_db(node_id).kpis_at(node_id, t_debut)
        rows: list[KpiRow] = []
        for path, label in _kpi_fields():
            bloc, champ = path.split(".", 1)
            current = getattr(getattr(node.kpis, bloc), champ)
            previous = (
                getattr(getattr(previous_bundle, bloc), champ)
                if previous_bundle is not None
                else None
            )
            rows.append(
                KpiRow(
                    path=path,
                    label_fr=label or path,
                    unit=kpi_unit(path),
                    previous=previous,
                    current=current,
                )
            )
        return rows

    def review_status(self, node_id: str) -> dict[str, Any]:
        """État de la revue de la semaine courante du nœud.

        Args:
            node_id: identifiant du nœud.

        Returns:
            ``{"volets": {volet: 0|1}, "done": int, "total": 4,
            "started_at": float | None, "completed_at": float | None}`` —
            les quatre volets de :data:`VOLETS` sont toujours présents.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._node(node_id)
        semaine = iso_week(self._clock_of(node).now())
        stored = self._service.client_db(node_id).get_weekly_review(node_id, semaine)
        bruts: dict[str, Any] = stored["volets"] if stored is not None else {}
        volets = {volet: 1 if bruts.get(volet) else 0 for volet in VOLETS}
        return {
            "volets": volets,
            "done": sum(volets.values()),
            "total": len(VOLETS),
            "started_at": stored["started_at"] if stored is not None else None,
            "completed_at": stored["completed_at"] if stored is not None else None,
        }

    # -- confirmations « rien n'a changé » --

    def confirm_block(self, node_id: str, block: str, operator_id: str = "") -> None:
        """Confirme qu'un bloc de KPIs n'a pas changé cette semaine.

        AUCUN KPI n'est écrit (ni snapshot, ni mutation) : seule une ligne
        d'audit est ajoutée dans la base CLIENT du nœud
        (``entity_type="node_kpis"``, ``entity_id=node_id``,
        ``field="__confirmed__"``, ``old=None``, ``new=block``,
        ``source="weekly"``), datée par l'horloge du projet.

        Args:
            node_id: identifiant du nœud.
            block: nom du bloc confirmé (ex. ``"time"``, ``"risk"``).
            operator_id: opérateur à l'origine de la confirmation.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._node(node_id)
        client = self._service.client_db(node_id)
        trail = AuditTrail(client.conn, self._clock_of(node), lock=client.lock)
        trail.record("node_kpis", node_id, "__confirmed__", None, block, "weekly", operator_id)

    def confirm_milestone(
        self, milestone_id: str, status: str, progress: float, operator_id: str = ""
    ) -> None:
        """Confirme (ou met à jour) un jalon pendant la revue hebdomadaire.

        Passe par ``service.mutations.update_milestone`` (``source="weekly"``) :
        seuls les champs réellement modifiés sont écrits et audités — confirmer
        un jalon inchangé est un no-op complet.

        Args:
            milestone_id: identifiant du jalon.
            status: statut déclaré (``"active"``/``"done"``/``"abandoned"``).
            progress: avancement déclaré, dans [0, 1].
            operator_id: opérateur à l'origine de la confirmation.

        Raises:
            KeyError: si le jalon est inconnu du registre.
            ValueError: statut inconnu ou ``progress`` hors [0, 1] (rien n'est
                alors écrit).
        """
        self._service.mutations.update_milestone(
            milestone_id,
            {"status": status, "progress": progress},
            source="weekly",
            operator_id=operator_id,
        )

    # -- progression de la revue --

    def start(self, node_id: str) -> None:
        """Démarre la revue de la semaine courante (pose ``started_at`` si absent).

        Idempotent : un ``started_at`` déjà posé n'est jamais écrasé.

        Args:
            node_id: identifiant du nœud.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._node(node_id)
        now = self._clock_of(node).now()
        self._service.client_db(node_id).upsert_weekly_review(
            node_id, iso_week(now), started_at=now
        )

    def mark_volet(self, node_id: str, volet: str, operator_id: str = "") -> dict[str, Any]:
        """Marque un volet de la revue comme traité pour la semaine courante.

        Pose ``started_at`` au premier appel de la semaine (horloge du projet).
        ``operator_id`` est accepté pour l'uniformité de l'API (la table
        ``weekly_reviews`` ne le persiste pas).

        Args:
            node_id: identifiant du nœud.
            volet: un des volets de :data:`VOLETS`.
            operator_id: opérateur à l'origine du marquage.

        Returns:
            L'état de la revue après marquage (:meth:`review_status`).

        Raises:
            ValueError: volet inconnu, ou nœud inconnu du registre.
        """
        if volet not in VOLETS:
            raise ValueError(f"volet inconnu : {volet!r} (attendus : {', '.join(VOLETS)})")
        node = self._node(node_id)
        now = self._clock_of(node).now()
        self._service.client_db(node_id).upsert_weekly_review(
            node_id, iso_week(now), volets={volet: 1}, started_at=now
        )
        return self.review_status(node_id)

    def complete(self, node_id: str) -> dict[str, Any]:
        """Clôt la revue de la semaine courante (exige les quatre volets).

        Pose ``completed_at`` à l'instant de l'horloge du PROJET du nœud.

        Args:
            node_id: identifiant du nœud.

        Returns:
            L'état final de la revue (:meth:`review_status`).

        Raises:
            ValueError: s'il reste au moins un volet non traité (le message
                liste les volets restants), ou si le nœud est inconnu.
        """
        node = self._node(node_id)
        statut = self.review_status(node_id)
        restants = [volet for volet in VOLETS if not statut["volets"][volet]]
        if restants:
            raise ValueError(
                "Revue hebdomadaire incomplète — volets restants : " + ", ".join(restants)
            )
        now = self._clock_of(node).now()
        self._service.client_db(node_id).upsert_weekly_review(
            node_id, iso_week(now), completed_at=now
        )
        return self.review_status(node_id)
