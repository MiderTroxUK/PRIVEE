"""Cycle hebdomadaire ISO - fraicheur des evaluations AHP par noeud (information seule).

Definitions figees du lot 4.1 :

- la " semaine " d'une evaluation ``e`` est ``iso_week(e.timestamp)`` au format
  " AAAA-Sxx " (semaine ISO en heure locale) ; la " semaine courante " d'un
  noeud est celle de l'horloge de SON projet
  (:meth:`SupplyScoreService.clock_for`) ;
- **a jour** : le noeud a au moins une evaluation AHP dont ``iso_week`` est la
  semaine courante du projet ;
- **en retard** : la derniere evaluation date d'une semaine strictement
  anterieure ; ``semaines_de_retard`` est le nombre de semaines ISO d'ecart
  (difference des lundis de chaque semaine, divisee par 7 jours) ;
- **manquant** : le noeud n'a aucune evaluation ;
- les noeuds DONE/ABANDONED sont EXCLUS du decompte de couverture, mais
  :meth:`CycleHebdomadaire.statut_noeud` repond quand meme pour eux.

AUCUNE degradation automatique du Ud, aucun e-mail : :class:`CycleHebdomadaire`
ne fait que CONSTATER l'etat du cycle hebdomadaire a destination de l'UI.

Lot 6.2 : :class:`WeeklyReview` ajoute la revue hebdomadaire GUIDEE d'un noeud
en quatre volets (:data:`VOLETS`) - diff KPI d'une semaine a l'autre
(:meth:`WeeklyReview.kpi_diff`), confirmations " rien n'a change " (bloc KPI,
jalon) et suivi de progression (``start``/``mark_volet``/``complete``)
persiste dans la table ``weekly_reviews`` de la base CLIENT du noeud. Toutes
les dates proviennent de l'horloge du PROJET du noeud (reelle ou de jeu).
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
    """Statut hebdomadaire d'un noeud vis-a-vis de son evaluation AHP."""

    A_JOUR = "a_jour"
    EN_RETARD = "en_retard"
    MANQUANT = "manquant"


@dataclass(frozen=True)
class EtatHebdo:
    """Etat hebdomadaire d'un noeud : statut, semaines et retard eventuel.

    Attributes:
        statut: position du noeud dans le cycle (a jour / en retard / manquant).
        semaine_courante: semaine ISO " AAAA-Sxx " de l'horloge du projet.
        derniere_semaine: semaine de la derniere evaluation, None si aucune.
        semaines_de_retard: nombre de semaines ISO de retard (0 si a jour ou
            manquant).
    """

    statut: StatutHebdo
    semaine_courante: str
    derniere_semaine: str | None
    semaines_de_retard: int


def _lundi(week: str) -> datetime:
    """Lundi (minuit, naif) de la semaine ISO libellee " AAAA-Sxx ".

    Args:
        week: libelle " AAAA-Sxx ", ex. " 2026-S05 ".

    Returns:
        ``datetime.fromisocalendar(annee, semaine, 1)``.

    Raises:
        ValueError: si le libelle n'est pas de la forme " AAAA-Sxx " ou si la
            semaine n'existe pas dans l'annee ISO donnee.
    """
    year_str, sep, num_str = week.partition("-S")
    if not sep or not year_str.isdigit() or not num_str.isdigit():
        raise ValueError(f"libellé de semaine ISO invalide : {week!r} (attendu « AAAA-Sxx »)")
    return datetime.fromisocalendar(int(year_str), int(num_str), 1)


def semaines_ecart(week_a: str, week_b: str) -> int:
    """Nombre de semaines ISO entre deux libelles " AAAA-Sxx " (``b - a``).

    Calcule via ``datetime.fromisocalendar(annee, semaine, 1)`` : difference
    des lundis des deux semaines, divisee par 7 jours. Positif (``>= 0``) si
    ``week_b`` est posterieure ou egale a ``week_a``, negatif sinon. Les bords
    d'annee ISO sont exacts, ex. ``("2020-S53", "2021-S01") -> 1``.

    Args:
        week_a: semaine de depart, ex. " 2026-S24 ".
        week_b: semaine d'arrivee, ex. " 2026-S26 ".

    Returns:
        L'ecart en semaines ISO entieres (``b - a``).
    """
    return (_lundi(week_b) - _lundi(week_a)).days // 7


class CycleHebdomadaire:
    """Suivi du cycle hebdomadaire ISO des evaluations AHP d'un reseau.

    S'appuie sur la facade :class:`SupplyScoreService` : le registre fournit
    les noeuds et l'horloge effective de chaque projet (reelle ou de jeu via
    ``clock_for``), les bases client fournissent les semaines d'evaluation
    materialisees (colonne ``assessments.iso_week``).
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le cycle hebdomadaire au-dessus de la facade.

        Args:
            service: facade applicative (registre, bases client, horloges).
        """
        self._service = service

    def _semaine_courante(self, project_id: str | None) -> str:
        """Semaine ISO courante selon l'horloge du projet (ou l'horloge reelle).

        Args:
            project_id: projet dont l'horloge fait foi ; None ou vide ->
                horloge par defaut du service.

        Returns:
            Libelle " AAAA-Sxx " de la semaine courante.
        """
        clock = self._service.clock_for(project_id) if project_id else self._service.clock
        return iso_week(clock.now())

    def _etat(self, node_id: str, semaine_courante: str) -> EtatHebdo:
        """Construit l'EtatHebdo du noeud pour une semaine courante donnee.

        Args:
            node_id: identifiant du noeud.
            semaine_courante: semaine ISO de reference (" AAAA-Sxx ").

        Returns:
            L'etat hebdomadaire du noeud (statut, semaines, retard).
        """
        derniere = self._service.client_db(node_id).last_assessment_week(node_id)
        if derniere is None:
            return EtatHebdo(StatutHebdo.MANQUANT, semaine_courante, None, 0)
        retard = semaines_ecart(derniere, semaine_courante)
        if retard <= 0:
            # Evaluation de la semaine courante (ou, garde-fou, d'une semaine posterieure si l'horloge a recule) : le noeud est a jour.
            return EtatHebdo(StatutHebdo.A_JOUR, semaine_courante, derniere, 0)
        return EtatHebdo(StatutHebdo.EN_RETARD, semaine_courante, derniere, retard)

    def statut_noeud(self, node_id: str) -> EtatHebdo:
        """Etat hebdomadaire d'un noeud (repond aussi pour DONE/ABANDONED).

        Args:
            node_id: identifiant du noeud (doit exister dans le registre).

        Returns:
            L'etat hebdomadaire du noeud, semaine courante = celle de l'horloge
            de SON projet.

        Raises:
            ValueError: si le noeud est inconnu du registre.
        """
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise ValueError(f"nœud inconnu du registre : {node_id!r}")
        return self._etat(node_id, self._semaine_courante(node.project_id))

    def synthese(self, project_id: str) -> dict[str, EtatHebdo]:
        """Etats hebdomadaires de TOUS les noeuds du projet (statuts confondus).

        Args:
            project_id: identifiant du projet.

        Returns:
            ``node_id -> EtatHebdo``, la semaine courante (commune) etant celle
            de l'horloge du projet.
        """
        semaine = self._semaine_courante(project_id)
        return {
            node.id: self._etat(node.id, semaine)
            for node in self._service.registry.list_nodes(project_id)
        }

    def couverture(self, project_id: str) -> tuple[int, int]:
        """Couverture hebdomadaire du projet : ``(noeuds a jour, total actifs)``.

        Seuls les noeuds ACTIVE comptent : les noeuds DONE/ABANDONED sont exclus
        du numerateur comme du denominateur.

        Args:
            project_id: identifiant du projet.

        Returns:
            Le couple ``(nombre de noeuds actifs a jour, nombre de noeuds actifs)``.
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


# Revue hebdomadaire guidee (Lot 6.2)

#: Les quatre volets de la revue hebdomadaire, dans l'ordre du deroule.
VOLETS: tuple[str, ...] = ("ahp", "kpis", "jalons", "evenements")


@dataclass(frozen=True)
class KpiRow:
    """Ligne du diff KPI hebdomadaire : valeur precedente vs valeur courante.

    Attributes:
        path: chemin qualifie du KPI, ex. ``"time.lead_time_h"``.
        label_fr: libelle francais du champ (depuis ``KPI_FIELDS`` de la page
            questionnaire ; le chemin sert de repli si le libelle est vide).
        unit: unite d'affichage (:func:`supplyscore.domain.constraints.kpi_unit`).
        previous: valeur du KPI en fin de semaine PRECEDENTE - dernier snapshot
            KPI anterieur au lundi 00:00 (heure locale) de la semaine courante
            du projet ; None si aucun snapshot ou champ non renseigne.
        current: valeur courante du KPI sur le noeud, None si non renseignee.
    """

    path: str
    label_fr: str
    unit: str
    previous: float | None
    current: float | None


def _kpi_fields() -> list[tuple[str, str]]:
    """Chemins et libelles francais des KPIs saisissables, ordre du questionnaire.

    Import DIFFERE de ``KPI_FIELDS`` : la page questionnaire importe elle-meme
    ce module - un import au niveau module creerait un cycle.

    Returns:
        La liste aplatie ``[(chemin, libelle), ...]`` de tous les blocs.
    """
    from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS

    return [(path, label) for _bloc, fields in KPI_FIELDS for path, label in fields]


class WeeklyReview:
    """Revue hebdomadaire guidee d'un noeud : quatre volets, diff KPI, confirmations.

    S'appuie sur la facade :class:`SupplyScoreService` : l'horloge effective du
    projet du noeud (``clock_for``) date toutes les ecritures, la base CLIENT du
    noeud porte l'etat de la revue (table ``weekly_reviews``), les snapshots KPI
    (``kpis_at``) et les lignes d'audit de confirmation ; les jalons passent
    par :class:`~supplyscore.services.mutations.MutationService`.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise la revue hebdomadaire au-dessus de la facade.

        Args:
            service: facade applicative (registre, bases client, mutations,
                horloges).
        """
        self._service = service

    # aides internes

    def _node(self, node_id: str) -> SupplyNode:
        """Lecture fraiche du noeud depuis le registre.

        Args:
            node_id: identifiant du noeud.

        Returns:
            Le :class:`~supplyscore.domain.models.SupplyNode` du registre.

        Raises:
            ValueError: si le noeud est inconnu du registre.
        """
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise ValueError(f"nœud inconnu du registre : {node_id!r}")
        return node

    def _clock_of(self, node: SupplyNode) -> Clock:
        """Horloge effective du noeud : celle de SON projet (reelle ou de jeu)."""
        if node.project_id:
            return self._service.clock_for(node.project_id)
        return self._service.clock

    # lecture

    def week_of(self, node_id: str) -> str:
        """Semaine ISO courante du PROJET du noeud (" AAAA-Sxx ").

        Args:
            node_id: identifiant du noeud.

        Returns:
            Le libelle de la semaine courante selon l'horloge du projet.

        Raises:
            ValueError: si le noeud est inconnu du registre.
        """
        node = self._node(node_id)
        return iso_week(self._clock_of(node).now())

    def kpi_diff(self, node_id: str) -> list[KpiRow]:
        """Diff KPI de la semaine : valeur de fin de semaine precedente vs courante.

        Couvre TOUS les champs de ``KPI_FIELDS`` (ordre du questionnaire). La
        valeur precedente est lue par ``ClientDatabase.kpis_at`` au lundi 00:00
        (heure locale, ``datetime.fromisocalendar``) de la semaine courante du
        projet : c'est le dernier snapshot KPI pose avant le debut de la
        semaine, donc l'etat en fin de semaine precedente. La valeur courante
        est celle du noeud (lecture fraiche du registre).

        Args:
            node_id: identifiant du noeud.

        Returns:
            Une :class:`KpiRow` par champ de ``KPI_FIELDS``, dans l'ordre.

        Raises:
            ValueError: si le noeud est inconnu du registre.
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
        """Etat de la revue de la semaine courante du noeud.

        Args:
            node_id: identifiant du noeud.

        Returns:
            ``{"volets": {volet: 0|1}, "done": int, "total": 4,
            "started_at": float | None, "completed_at": float | None}`` -
            les quatre volets de :data:`VOLETS` sont toujours presents.

        Raises:
            ValueError: si le noeud est inconnu du registre.
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

    # confirmations " rien n'a change "

    def confirm_block(self, node_id: str, block: str, operator_id: str = "") -> None:
        """Confirme qu'un bloc de KPIs n'a pas change cette semaine.

        AUCUN KPI n'est ecrit (ni snapshot, ni mutation) : seule une ligne
        d'audit est ajoutee dans la base CLIENT du noeud
        (``entity_type="node_kpis"``, ``entity_id=node_id``,
        ``field="__confirmed__"``, ``old=None``, ``new=block``,
        ``source="weekly"``), datee par l'horloge du projet.

        Args:
            node_id: identifiant du noeud.
            block: nom du bloc confirme (ex. ``"time"``, ``"risk"``).
            operator_id: operateur a l'origine de la confirmation.

        Raises:
            ValueError: si le noeud est inconnu du registre.
        """
        node = self._node(node_id)
        client = self._service.client_db(node_id)
        trail = AuditTrail(client.conn, self._clock_of(node), lock=client.lock)
        trail.record("node_kpis", node_id, "__confirmed__", None, block, "weekly", operator_id)

    def confirm_milestone(
        self, milestone_id: str, status: str, progress: float, operator_id: str = ""
    ) -> None:
        """Confirme (ou met a jour) un jalon pendant la revue hebdomadaire.

        Passe par ``service.mutations.update_milestone`` (``source="weekly"``) :
        seuls les champs reellement modifies sont ecrits et audites - confirmer
        un jalon inchange est un no-op complet.

        Args:
            milestone_id: identifiant du jalon.
            status: statut declare (``"active"``/``"done"``/``"abandoned"``).
            progress: avancement declare, dans [0, 1].
            operator_id: operateur a l'origine de la confirmation.

        Raises:
            KeyError: si le jalon est inconnu du registre.
            ValueError: statut inconnu ou ``progress`` hors [0, 1] (rien n'est
                alors ecrit).
        """
        self._service.mutations.update_milestone(
            milestone_id,
            {"status": status, "progress": progress},
            source="weekly",
            operator_id=operator_id,
        )

    # progression de la revue

    def start(self, node_id: str) -> None:
        """Demarre la revue de la semaine courante (pose ``started_at`` si absent).

        Idempotent : un ``started_at`` deja pose n'est jamais ecrase.

        Args:
            node_id: identifiant du noeud.

        Raises:
            ValueError: si le noeud est inconnu du registre.
        """
        node = self._node(node_id)
        now = self._clock_of(node).now()
        self._service.client_db(node_id).upsert_weekly_review(
            node_id, iso_week(now), started_at=now
        )

    def mark_volet(self, node_id: str, volet: str, operator_id: str = "") -> dict[str, Any]:
        """Marque un volet de la revue comme traite pour la semaine courante.

        Pose ``started_at`` au premier appel de la semaine (horloge du projet).
        ``operator_id`` est accepte pour l'uniformite de l'API (la table
        ``weekly_reviews`` ne le persiste pas).

        Args:
            node_id: identifiant du noeud.
            volet: un des volets de :data:`VOLETS`.
            operator_id: operateur a l'origine du marquage.

        Returns:
            L'etat de la revue apres marquage (:meth:`review_status`).

        Raises:
            ValueError: volet inconnu, ou noeud inconnu du registre.
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
        """Clot la revue de la semaine courante (exige les quatre volets).

        Pose ``completed_at`` a l'instant de l'horloge du PROJET du noeud.

        Args:
            node_id: identifiant du noeud.

        Returns:
            L'etat final de la revue (:meth:`review_status`).

        Raises:
            ValueError: s'il reste au moins un volet non traite (le message
                liste les volets restants), ou si le noeud est inconnu.
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
