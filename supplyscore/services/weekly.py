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

AUCUNE dégradation automatique du Ud, aucun e-mail : ce service ne fait que
CONSTATER l'état du cycle hebdomadaire à destination de l'UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from supplyscore.core.clock import iso_week
from supplyscore.domain.models import TaskStatus

if TYPE_CHECKING:
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
