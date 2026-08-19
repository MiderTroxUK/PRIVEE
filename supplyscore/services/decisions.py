"""Journal des decisions hebdomadaires - enregistrement et relecture (E6, Lot 6.3).

:class:`DecisionService` consigne les decisions prises pendant la revue
hebdomadaire d'un noeud. Chaque decision embarque un snapshot AUTOMATIQUE des
scores courants du noeud (``{ud, ur, a, f, h}`` depuis ``node.urgency``, None
tolere) : le journal restitue ainsi le contexte chiffre dans lequel la
decision a ete prise, meme si les scores ont bouge depuis.

L'horodatage (``created_at``) et la semaine ISO (``iso_week``) proviennent de
l'horloge du PROJET du noeud (reelle ou de jeu, via
:meth:`~supplyscore.services.orchestrator.SupplyScoreService.clock_for`).
La persistance passe par la base CLIENT du noeud
(:meth:`~supplyscore.data.db.ClientDatabase.save_decision` /
:meth:`~supplyscore.data.db.ClientDatabase.list_decisions`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from supplyscore.core.clock import iso_week as _iso_week

if TYPE_CHECKING:
    from supplyscore.core.clock import Clock
    from supplyscore.domain.models import SupplyNode
    from supplyscore.services.orchestrator import SupplyScoreService


@dataclass(frozen=True)
class Decision:
    """Decision consignee pendant la revue hebdomadaire d'un noeud.

    Attributes:
        id: identifiant unique (UUID4).
        node_id: noeud concerne par la decision.
        iso_week: semaine ISO de la decision (horloge du PROJET du noeud).
        operator_id: operateur ayant consigne la decision.
        description: texte libre de la decision (jamais vide).
        scores: snapshot ``{"ud", "ur", "a", "f", "h"}`` des scores du noeud au
            moment de la decision (None pour un score non encore calcule).
        created_at: instant de la decision, en secondes epoch.
    """

    id: str
    node_id: str
    iso_week: str
    operator_id: str
    description: str
    scores: dict[str, float | None]
    created_at: float


def _decision_from_row(row: Mapping[str, Any]) -> Decision:
    """Reconstruit une :class:`Decision` depuis une ligne de la table ``decisions``."""
    return Decision(
        id=row["id"],
        node_id=row["node_id"],
        iso_week=row["iso_week"],
        operator_id=row["operator_id"],
        description=row["description"],
        scores=row["scores"],
        created_at=row["created_at"],
    )


class DecisionService:
    """Journal des decisions : enregistrement avec snapshot des scores, relecture.

    S'appuie sur la facade :class:`SupplyScoreService` : le registre fournit
    les noeuds (et leur etat d'urgence courant), ``clock_for`` l'horloge
    effective du projet, et la base CLIENT du noeud porte la table
    ``decisions``.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le journal des decisions au-dessus de la facade.

        Args:
            service: facade applicative (registre, bases client, horloges).
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

    # ecriture

    def record(self, node_id: str, description: str, operator_id: str = "") -> Decision:
        """Consigne une decision pour le noeud, avec snapshot des scores courants.

        Le snapshot ``{ud, ur, a, f, h}`` est pris AUTOMATIQUEMENT depuis
        ``node.urgency`` (lecture fraiche du registre, None tolere pour un
        score non encore calcule). ``iso_week`` et ``created_at`` proviennent
        de l'horloge du PROJET du noeud ; l'id est un UUID4.

        Args:
            node_id: identifiant du noeud concerne.
            description: texte libre de la decision (non vide).
            operator_id: operateur ayant consigne la decision.

        Returns:
            La :class:`Decision` telle que persistee.

        Raises:
            ValueError: description vide (ou blanche), ou noeud inconnu du
                registre - rien n'est alors ecrit.
        """
        if not description.strip():
            raise ValueError("La description de la décision ne peut pas être vide.")
        node = self._node(node_id)
        created_at = self._clock_of(node).now()
        urgence = node.urgency
        scores: dict[str, float | None] = {
            "ud": urgence.ud,
            "ur": urgence.ur,
            "a": urgence.adequation,
            "f": urgence.false_urgency,
            "h": urgence.hidden_risk,
        }
        decision = Decision(
            id=str(uuid.uuid4()),
            node_id=node_id,
            iso_week=_iso_week(created_at),
            operator_id=operator_id,
            description=description,
            scores=scores,
            created_at=created_at,
        )
        self._service.client_db(node_id).save_decision(
            decision.id,
            decision.node_id,
            decision.iso_week,
            decision.operator_id,
            decision.description,
            json.dumps(scores, sort_keys=True),
            decision.created_at,
        )
        return decision

    # relecture

    def list_for_node(self, node_id: str, iso_week: str | None = None) -> list[Decision]:
        """Decisions du noeud, les plus recentes d'abord.

        Args:
            node_id: identifiant du noeud.
            iso_week: si fourni, ne retourne que les decisions de cette
                semaine ISO (" AAAA-Sxx ").

        Returns:
            Les :class:`Decision` du noeud, triees par ``created_at`` decroissant.
        """
        rows = self._service.client_db(node_id).list_decisions(node_id, iso_week)
        return [_decision_from_row(row) for row in rows]

    def list_for_project(self, project_id: str, iso_week: str | None = None) -> list[Decision]:
        """Decisions de TOUS les noeuds du projet, les plus recentes d'abord.

        Agrege les journaux des bases CLIENT de chaque noeud du projet, puis
        trie l'ensemble par ``created_at`` decroissant.

        Args:
            project_id: identifiant du projet.
            iso_week: si fourni, ne retourne que les decisions de cette
                semaine ISO (" AAAA-Sxx ").

        Returns:
            Les :class:`Decision` du projet, triees par ``created_at`` decroissant.
        """
        decisions: list[Decision] = []
        for node in self._service.registry.list_nodes(project_id):
            decisions.extend(self.list_for_node(node.id, iso_week))
        decisions.sort(key=lambda decision: decision.created_at, reverse=True)
        return decisions
