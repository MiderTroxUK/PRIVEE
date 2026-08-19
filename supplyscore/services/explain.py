"""Service d'assemblage de l'explication d'un noeud (phase E8, Lot 8.2).

:class:`ExplainService` repond a " pourquoi ce noeud a-t-il ce score ? " en
UNE structure :class:`NodeExplanation` : il reconstruit le contexte temporel
du pipeline (memes regles que ``evaluate_all`` - horloge du PROJET du noeud,
jalons charges), appelle les decompositions EXACTES de
:mod:`supplyscore.core.explain` (criteres AHP, blocs KPI, trace u_time,
parts de propagation montante/descendante, equation d'adequation), puis y
joint les versions liees : derniere evaluation AHP effective, lignes d'audit
recentes des KPIs des deux blocs dominants, evenements supply chain encore
ouverts.

Le service est PUR EN LECTURE : aucune ecriture, aucun recalcul persiste -
les urgences exposees (``ud``, ``ur``, ``adequation``) sont celles posees par
le pipeline sur ``node.urgency``, et deux appels successifs a
:meth:`ExplainService.explain_node` rendent des resultats identiques tant que
rien n'a mute par ailleurs.

Choix documente : ``adequation_trace`` vaut ``None`` tant que le pipeline n'a
jamais propage le noeud (``urgency.ud`` ou ``urgency.ur`` absent) - il n'y a
alors aucune equation d'adequation a instancier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from supplyscore.core.clock import project_hours
from supplyscore.core.explain import (
    AdequationTrace,
    BlockContribution,
    CriterionContribution,
    EdgeContribution,
    UTimeTrace,
    explain_adequation,
    explain_propagation_down,
    explain_propagation_up,
    explain_u_time,
    explain_ud,
    explain_ur_local,
)
from supplyscore.core.status_rules import effective_ur_local
from supplyscore.data.audit import AuditEntry, AuditTrail
from supplyscore.domain.models import SupplyArc, SupplyNode
from supplyscore.services.events import EventEngine, SupplyEvent

if TYPE_CHECKING:  # import differe : evite tout cycle services.explain <-> orchestrator
    from supplyscore.services.orchestrator import SupplyScoreService

#: Correspondance bloc d'urgence -> blocs du KPIBundle (prefixes des champs audites).
_BLOCK_KPI_PREFIXES: dict[str, tuple[str, ...]] = {
    "time": ("time",),
    "cap": ("inventory", "network"),
    "perf": ("oee",),
    "risk": ("risk",),
    "cost": ("cost",),
    "co2": ("co2",),
}

#: Nombre de blocs dominants dont l'historique d'audit KPI est joint.
_TOP_BLOCKS: int = 2

#: Entrees d'audit relues avant filtrage par prefixe - ``AuditTrail.history`` ne filtre que par champ exact, le filtrage par bloc se fait donc en Python.
_AUDIT_FETCH_LIMIT: int = 50

#: Nombre maximal d'entrees d'audit conservees dans l'explication.
_AUDIT_MAX: int = 10

#: Seuil de saturation " retard avere " (meme valeur que ``core.explain``).
_EPS_SAT: float = 1e-9


@dataclass(frozen=True)
class NodeExplanation:
    """Explication complete d'un noeud - les 5 decompositions et leurs versions liees.

    Attributes:
        node_id: identifiant du noeud explique.
        node_name: nom lisible du noeud.
        ud: urgence declaree propagee (telle que posee par le pipeline).
        ur: urgence reelle propagee (telle que posee par le pipeline).
        adequation: score A  dans  [0, 100] pose par le pipeline.
        criteres: contributions additives des criteres AHP au Ud du dernier
            questionnaire effectif (``[]`` si le noeud n'a jamais ete evalue).
        blocs: decomposition de Ur_local par bloc KPI (parts log-survie).
        u_time_trace: trace socle/modulation planning du bloc ``time``.
        part_locale_ur: part log-survie locale de l'urgence reelle propagee.
        fournisseurs: parts des fournisseurs directs dans Ur propage
            (part_locale_ur + Sigma parts = 1, arcs nominaux seuls).
        part_locale_ud: part log-survie locale du besoin declare propage.
        clients: parts des clients directs dans Ud propage.
        adequation_trace: equation d'adequation instanciee chiffree, ou
            ``None`` si le pipeline n'a jamais propage le noeud (choix
            documente : pas de Ud/Ur propages, pas d'equation a instancier).
        derniere_evaluation: ``{operateur, semaine, ud, cr, notes}`` du
            dernier questionnaire AHP effectif, ou ``None`` si aucun.
        audits_recents: entrees d'audit des KPIs des 2 blocs dominants
            (``entity_type="node_kpis"``, 10 max, plus recentes d'abord).
        evenements_ouverts: evenements supply chain non annules du noeud,
            du plus recent au plus ancien.
        retard_avere: True si Ur_local effectif >= 1 (retard avere ou noeud
            abandonne) - la decomposition log-survie n'est pas definie, la
            cause locale est unique.
    """

    node_id: str
    node_name: str
    ud: float | None
    ur: float | None
    adequation: float | None
    criteres: list[CriterionContribution]
    blocs: list[BlockContribution]
    u_time_trace: UTimeTrace | None
    part_locale_ur: float
    fournisseurs: list[EdgeContribution]
    part_locale_ud: float
    clients: list[EdgeContribution]
    adequation_trace: AdequationTrace | None
    derniere_evaluation: dict[str, float | str] | None
    audits_recents: list[AuditEntry]
    evenements_ouverts: list[SupplyEvent]
    retard_avere: bool


class ExplainService:
    """Assembleur d'explications - lecture seule au-dessus de la facade.

    Toutes les lectures passent par les composants du
    :class:`~supplyscore.services.orchestrator.SupplyScoreService` fourni
    (graphe en memoire, registre, bases client, horloges par projet, modeles
    du pipeline) : le service ne recalcule rien hors des fonctions
    d'explication et n'ecrit jamais.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service d'explication sur la facade de l'application.

        Args:
            service: facade :class:`~supplyscore.services.orchestrator.SupplyScoreService`
                (graphe, registre, bases client, horloges, modeles).
        """
        self._service = service
        self._events = EventEngine(service)

    # API publique

    def explain_node(self, node_id: str) -> NodeExplanation:
        """Assemble l'explication complete d'un noeud (PUR en lecture).

        Le contexte temporel est reconstruit avec les MEMES regles que
        ``evaluate_all`` : t = heures ecoulees depuis l'origine du projet du
        noeud selon SON horloge (reelle ou de jeu), t0 = origine epoch du
        projet, jalons charges depuis le registre (u_time v2). Les
        decompositions sont ensuite deleguees a
        :mod:`supplyscore.core.explain` sur l'etat courant du graphe.

        Args:
            node_id: identifiant du noeud a expliquer.

        Returns:
            L'explication assemblee :class:`NodeExplanation`.

        Raises:
            KeyError: si le noeud est inconnu du graphe.
        """
        service = self._service
        node = service.repo.get_node(node_id)
        if node is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")

        t_h, t0 = self._project_time(node)
        milestones = service.registry.list_milestones(node_id)

        # Ud : criteres du dernier questionnaire AHP effectif (base CLIENT).
        assessment = service.client_db(node_id).latest_assessment(node_id)
        criteres: list[CriterionContribution] = []
        derniere_evaluation: dict[str, float | str] | None = None
        if assessment is not None:
            criteres = explain_ud(
                np.asarray(assessment.weights, dtype=float),
                np.asarray(assessment.criteria_scores, dtype=float),
            )
            derniere_evaluation = {
                "operateur": assessment.operator_id,
                "semaine": assessment.iso_week,
                "ud": assessment.ud,
                "cr": assessment.consistency_ratio,
                "notes": assessment.notes,
            }

        # Ur_local : decomposition par blocs et trace u_time (memes appels que le pipeline).
        blocs = explain_ur_local(t_h, node.kpis, milestones, service.ur_model, t0_ts=t0)
        u_time_trace = explain_u_time(t_h, node.kpis, milestones, service.ur_model, t0_ts=t0)

        # Propagation : parts locales vs voisins (arcs nominaux, Ur/Ud deja propages).
        predecessors = service.repo.predecessors(node_id)
        part_locale_ur, fournisseurs = explain_propagation_up(
            node, predecessors, self._arcs_from(predecessors, node_id)
        )
        successors = service.repo.successors(node_id)
        part_locale_ud, clients = explain_propagation_down(
            node, successors, self._arcs_to(node_id, successors)
        )

        # Adequation : equation instanciee si le pipeline a deja propage le noeud.
        state = node.urgency
        adequation_trace: AdequationTrace | None = None
        if state.ud is not None and state.ur is not None:
            adequation_trace = explain_adequation(state.ud, state.ur, service.adequation)

        ur_loc = effective_ur_local(node.status, state.ur_local)
        retard_avere = min(max(ur_loc, 0.0), 1.0) >= 1.0 - _EPS_SAT

        return NodeExplanation(
            node_id=node.id,
            node_name=node.name,
            ud=state.ud,
            ur=state.ur,
            adequation=state.adequation,
            criteres=criteres,
            blocs=blocs,
            u_time_trace=u_time_trace,
            part_locale_ur=part_locale_ur,
            fournisseurs=fournisseurs,
            part_locale_ud=part_locale_ud,
            clients=clients,
            adequation_trace=adequation_trace,
            derniere_evaluation=derniere_evaluation,
            audits_recents=self._recent_kpi_audits(node_id, blocs),
            evenements_ouverts=self._events.open_events(node_id),
            retard_avere=retard_avere,
        )

    # Aides internes (lecture seule)

    def _project_time(self, node: SupplyNode) -> tuple[float, float]:
        """Contexte temporel du noeud : ``(t_heures, t0_ts)`` de SON projet.

        Memes regles que ``evaluate_all`` / ``_project_times`` : l'horloge
        effective du projet (reelle ou de jeu) donne " maintenant ", l'origine
        du projet donne t0. Sans projet rattache (ou projet inconnu du
        registre), le referentiel degenere en ``(0.0, 0.0)``.

        Args:
            node: noeud explique.

        Returns:
            Tuple ``(t en heures depuis t0, t0 en secondes epoch)``.
        """
        if not node.project_id:
            return 0.0, 0.0
        project = self._service.registry.get_project(node.project_id)
        if project is None:
            return 0.0, 0.0
        origin = project.origin_ts
        now = self._service.clock_for(project.id).now()
        return project_hours(now, origin), origin

    def _arcs_from(self, predecessors: list[SupplyNode], node_id: str) -> dict[str, SupplyArc]:
        """Arcs entrants ``fournisseur -> noeud``, indexes par id de fournisseur.

        Args:
            predecessors: fournisseurs directs (arcs nominaux) du noeud.
            node_id: identifiant du noeud client des arcs.

        Returns:
            Dictionnaire ``{id de fournisseur: arc}`` (les voisins viennent du
            meme depot : l'arc existe toujours).
        """
        arcs: dict[str, SupplyArc] = {}
        for pred in predecessors:
            arc = self._service.repo.get_arc(pred.id, node_id)
            if arc is not None:
                arcs[pred.id] = arc
        return arcs

    def _arcs_to(self, node_id: str, successors: list[SupplyNode]) -> dict[str, SupplyArc]:
        """Arcs sortants ``noeud -> client``, indexes par id de client.

        Args:
            node_id: identifiant du noeud fournisseur des arcs.
            successors: clients directs (arcs nominaux) du noeud.

        Returns:
            Dictionnaire ``{id de client: arc}`` (les voisins viennent du
            meme depot : l'arc existe toujours).
        """
        arcs: dict[str, SupplyArc] = {}
        for succ in successors:
            arc = self._service.repo.get_arc(node_id, succ.id)
            if arc is not None:
                arcs[succ.id] = arc
        return arcs

    def _recent_kpi_audits(self, node_id: str, blocs: list[BlockContribution]) -> list[AuditEntry]:
        """Audit recent des KPIs des blocs dominants (base CLIENT du noeud).

        Les deux blocs au ``share`` le plus eleve sont retenus (tri stable :
        a parts egales, l'ordre de :data:`~supplyscore.core.ur_model.BLOCKS`
        departage), leurs blocs KPI sont traduits en prefixes de champ via
        :data:`_BLOCK_KPI_PREFIXES`, puis l'historique ``node_kpis`` est relu
        (50 entrees) et filtre par prefixe en Python -
        :meth:`~supplyscore.data.audit.AuditTrail.history` ne filtre que par
        champ exact. 10 entrees max, les plus recentes d'abord.

        Args:
            node_id: identifiant du noeud (= id de la base client).
            blocs: decomposition de Ur_local par bloc (parts log-survie).

        Returns:
            Les :class:`~supplyscore.data.audit.AuditEntry` retenues.
        """
        dominants = sorted(blocs, key=lambda bloc: bloc.share, reverse=True)[:_TOP_BLOCKS]
        prefixes = tuple(
            f"{kpi_block}." for bloc in dominants for kpi_block in _BLOCK_KPI_PREFIXES[bloc.block]
        )
        client = self._service.client_db(node_id)
        trail = AuditTrail(client.conn, self._service.clock, lock=client.lock)
        entries = trail.history("node_kpis", node_id, limit=_AUDIT_FETCH_LIMIT)
        return [entry for entry in entries if entry.field.startswith(prefixes)][:_AUDIT_MAX]
