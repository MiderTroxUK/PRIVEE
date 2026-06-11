"""Scénarios catastrophe composites — évaluation what-if PURE du graphe (E15.1).

Un :class:`Scenario` combine plusieurs chocs simultanés : surcharges de
``ur_local``, statuts simulés, arcs rompus et multiplicateurs de lead time.
:meth:`MoteurScenario.evaluer` calcule les urgences propagées de référence
(baseline) et du scénario, puis leurs deltas par nœud, SANS JAMAIS écrire —
ni dans le dépôt, ni dans les ``UrgencyState`` des nœuds : l'état du graphe
est bit à bit inchangé après évaluation.

Approche retenue : OVERRIDES, pas « écrire puis restaurer ».
:meth:`PropagationEngine.propagate_all` persiste ``node.urgency`` ; le moteur
de scénarios n'y recourt donc jamais et réutilise les calculs PURS internes
du moteur de propagation (mécanisme déjà éprouvé par ``simulate_shock``) :

- ``PropagationEngine._compute_ur(overrides)`` : les surcharges de
  ``ur_local`` (explicites, ou dérivées d'un statut simulé via
  :func:`supplyscore.core.status_rules.effective_ur_local`) sont passées en
  overrides multiples — aucune écriture ;
- ``PropagationEngine._compute_ud()`` : calcul pur symétrique pour Ud. Les
  scénarios n'altèrent Ud que par rupture d'arc : ni les surcharges Ur ni
  les statuts simulés ne touchent Ud (décision de modélisation n°1, cf.
  :func:`supplyscore.core.status_rules.effective_ud_local` — le statut
  n'écrase pas le besoin déclaré) ;
- les arcs supprimés sont MASQUÉS par :class:`_VueArcsMasquees`, vue en
  LECTURE SEULE du dépôt qui filtre ``predecessors``/``successors``/
  ``get_arc``/``arcs`` et REFUSE toute mutation (garantie structurelle de
  pureté pendant le calcul du scénario). L'ordre topologique du graphe
  complet reste un ordre topologique valide du graphe privé d'arcs (retirer
  des arcs ne crée aucune contrainte d'ordre), la vue le délègue donc tel quel.

L'accès aux méthodes ``_compute_*`` du moteur de propagation est une
collaboration interne au package ``supplyscore.graph`` : la dupliquer ici
créerait une seconde implémentation de la récurrence de propagation.

Sémantique SIMPLE des ``multiplicateurs_lead_time`` (PLAN.md E15.1) : le
moteur analytique ne dispose ni du service ni du ``UrModel`` nécessaires pour
recalculer le ``u_time`` d'un nœud à partir d'un lead time multiplié. Les
multiplicateurs sont donc VALIDÉS (nœud connu, facteur >= 0) puis IGNORÉS,
avec un avertissement explicite dans ``ResultatScenario.avertissements``.
Champ réservé au mode Monte Carlo (E16+).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.models import SupplyArc, SupplyNode, TaskStatus
from supplyscore.graph.propagation import PropagationEngine
from supplyscore.graph.repository import GraphRepository

#: Message d'avertissement émis quand des multiplicateurs de lead time sont
#: fournis : ils sont ignorés par le moteur analytique (réservés au mode MC).
_AVERTISSEMENT_LEAD_TIME = (
    "Multiplicateurs de lead time ignorés par le moteur analytique "
    "(sémantique réservée au mode Monte Carlo, E16+). Nœuds concernés : {ids}."
)

_ERREUR_LECTURE_SEULE = (
    "Vue de scénario en lecture seule : aucune mutation du graphe n'est "
    "autorisée pendant l'évaluation d'un scénario (pureté garantie)."
)


@dataclass(frozen=True)
class Scenario:
    """Scénario catastrophe composite : plusieurs chocs simultanés sur le graphe.

    Attributes:
        nom: libellé du scénario (affichage UI, persistance E15.3).
        surcharges_ur: ``{node_id: ur_local simulé}``, valeurs dans [0, 1].
            Prioritaires sur ``statuts`` si un nœud apparaît dans les deux.
        statuts: ``{node_id: statut simulé}`` — traduit en surcharge de
            ``ur_local`` via la règle de statut unifiée (DONE → 0.0,
            ABANDONED → 1.0, ACTIVE → ``ur_local`` mesuré). Sans effet sur
            Ud (décision de modélisation n°1).
        arcs_supprimes: liste de ``(source_id, target_id)`` d'arcs rompus,
            masqués pendant le calcul (le dépôt n'est pas modifié).
        multiplicateurs_lead_time: ``{node_id: facteur >= 0}`` — validés puis
            IGNORÉS par le moteur analytique (avertissement dans le
            résultat) ; réservés au mode Monte Carlo (E16+).
    """

    nom: str = "scénario"
    surcharges_ur: dict[str, float] = field(default_factory=dict)
    statuts: dict[str, TaskStatus] = field(default_factory=dict)
    arcs_supprimes: list[tuple[str, str]] = field(default_factory=list)
    multiplicateurs_lead_time: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultatScenario:
    """Urgences propagées baseline vs scénario, et deltas par nœud.

    Attributes:
        scenario: le scénario évalué (tel que fourni).
        baseline_ur: ``{node_id: Ur}`` propagé sans choc (référence).
        scenario_ur: ``{node_id: Ur}`` propagé sous scénario.
        baseline_ud: ``{node_id: Ud}`` propagé sans choc (référence).
        scenario_ud: ``{node_id: Ud}`` propagé sous scénario.
        delta_ur: ``scenario_ur - baseline_ur`` par nœud.
        delta_ud: ``scenario_ud - baseline_ud`` par nœud.
        avertissements: messages français sur les champs non pris en compte
            (p. ex. multiplicateurs de lead time, réservés au mode MC).
    """

    scenario: Scenario
    baseline_ur: dict[str, float]
    scenario_ur: dict[str, float]
    baseline_ud: dict[str, float]
    scenario_ud: dict[str, float]
    delta_ur: dict[str, float]
    delta_ud: dict[str, float]
    avertissements: list[str]


class _VueArcsMasquees(GraphRepository):
    """Vue en LECTURE SEULE d'un dépôt, masquant un ensemble d'arcs.

    Les lectures sont déléguées au dépôt enveloppé, en filtrant les arcs
    masqués dans ``get_arc``, ``arcs``, ``predecessors`` et ``successors``
    (quelle que soit leur nature, nominal ou backup). ``topological_order``
    est délégué tel quel : l'ordre topologique du graphe complet reste valide
    pour le graphe privé d'arcs. TOUTE mutation lève ``TypeError`` — c'est la
    garantie structurelle de pureté du moteur de scénarios.
    """

    def __init__(self, repo: GraphRepository, masques: frozenset[tuple[str, str]]) -> None:
        """Enveloppe ``repo`` en masquant les arcs ``(source_id, target_id)`` donnés."""
        self._repo = repo
        self._masques = masques

    # --- Lectures (déléguées, arcs filtrés) --------------------------------

    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le nœud du dépôt enveloppé, ou None s'il est inconnu."""
        return self._repo.get_node(node_id)

    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc du dépôt enveloppé, ou None s'il est masqué ou inconnu."""
        if (source_id, target_id) in self._masques:
            return None
        return self._repo.get_arc(source_id, target_id)

    def nodes(self) -> list[SupplyNode]:
        """Tous les nœuds du dépôt enveloppé (les nœuds ne sont jamais masqués)."""
        return self._repo.nodes()

    def arcs(self, kinds: tuple[str, ...] | None = None) -> list[SupplyArc]:
        """Arcs du dépôt enveloppé filtrés par nature, sans les arcs masqués."""
        return [
            arc
            for arc in self._repo.arcs(kinds)
            if (arc.source_id, arc.target_id) not in self._masques
        ]

    def predecessors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Fournisseurs directs, sans ceux reliés par un arc masqué."""
        return [
            pred
            for pred in self._repo.predecessors(node_id, kinds=kinds)
            if (pred.id, node_id) not in self._masques
        ]

    def successors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Clients directs, sans ceux reliés par un arc masqué."""
        return [
            succ
            for succ in self._repo.successors(node_id, kinds=kinds)
            if (node_id, succ.id) not in self._masques
        ]

    def nodes_by_project(self, project_id: str) -> list[SupplyNode]:
        """Nœuds du projet donné (délégué tel quel)."""
        return self._repo.nodes_by_project(project_id)

    def topological_order(self) -> list[str]:
        """Ordre topologique du graphe complet — valide aussi privé d'arcs."""
        return self._repo.topological_order()

    # --- Mutations (interdites : pureté) ------------------------------------

    def add_node(self, node: SupplyNode) -> None:
        """Interdit — la vue de scénario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def update_node(self, node: SupplyNode) -> None:
        """Interdit — la vue de scénario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def remove_node(self, node_id: str) -> None:
        """Interdit — la vue de scénario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def add_arc(self, arc: SupplyArc) -> None:
        """Interdit — la vue de scénario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Interdit — la vue de scénario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def clear(self) -> None:
        """Interdit — la vue de scénario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)


class MoteurScenario:
    """Évalue des scénarios composites sans JAMAIS écrire dans le graphe.

    Le moteur réutilise les calculs purs du :class:`PropagationEngine`
    (``_compute_ud`` / ``_compute_ur(overrides)``) : la baseline est
    l'équivalent d'un ``propagate_all`` SANS persistance, le scénario est
    calculé avec les surcharges en overrides et les arcs rompus masqués par
    une vue en lecture seule. Voir la docstring du module pour l'approche
    complète (overrides, pas de restauration d'état).
    """

    def __init__(self, repo: GraphRepository, engine: PropagationEngine) -> None:
        """Initialise le moteur de scénarios.

        Args:
            repo: dépôt de graphe (jamais modifié par ce moteur).
            engine: moteur de propagation construit sur ``repo`` — seuls ses
                calculs PURS (sans écriture) sont utilisés.
        """
        self._repo = repo
        self._engine = engine

    def evaluer(self, scenario: Scenario) -> ResultatScenario:
        """Évalue ``scenario`` et retourne baseline, valeurs choquées et deltas.

        PUR : aucune écriture, ni dans le dépôt ni dans les ``UrgencyState``
        des nœuds — l'état du graphe est bit à bit inchangé après l'appel, et
        deux appels successifs retournent des résultats identiques.

        Args:
            scenario: scénario composite à évaluer.

        Returns:
            :class:`ResultatScenario` avec les urgences propagées de
            référence (baseline), celles du scénario et les deltas par nœud.

        Raises:
            ValueError: si un ``node_id`` ou un arc du scénario est inconnu
                du dépôt, si une surcharge sort de [0, 1], ou si un
                multiplicateur de lead time est négatif.
        """
        self._valider(scenario)

        baseline_ud = self._engine._compute_ud()
        baseline_ur = self._engine._compute_ur()

        moteur_simule = self._moteur_simule(scenario)
        scenario_ud = moteur_simule._compute_ud()
        scenario_ur = moteur_simule._compute_ur(overrides=self._surcharges_effectives(scenario))

        return ResultatScenario(
            scenario=scenario,
            baseline_ur=baseline_ur,
            scenario_ur=scenario_ur,
            baseline_ud=baseline_ud,
            scenario_ud=scenario_ud,
            delta_ur={nid: scenario_ur[nid] - baseline_ur[nid] for nid in baseline_ur},
            delta_ud={nid: scenario_ud[nid] - baseline_ud[nid] for nid in baseline_ud},
            avertissements=self._avertissements(scenario),
        )

    # --- Aides internes ------------------------------------------------------

    def _valider(self, scenario: Scenario) -> None:
        """Vérifie ids et bornes du scénario ; lève ``ValueError`` en français."""
        for node_id, valeur in scenario.surcharges_ur.items():
            self._exiger_noeud(node_id)
            if not 0.0 <= valeur <= 1.0:
                raise ValueError(f"Surcharge Ur hors [0, 1] pour {node_id!r} : {valeur!r}")
        for node_id in scenario.statuts:
            self._exiger_noeud(node_id)
        for source_id, target_id in scenario.arcs_supprimes:
            if self._repo.get_arc(source_id, target_id) is None:
                raise ValueError(f"Arc inconnu : {source_id!r} -> {target_id!r}")
        for node_id, facteur in scenario.multiplicateurs_lead_time.items():
            self._exiger_noeud(node_id)
            if not facteur >= 0.0:  # « not >= » plutôt que « < » : rejette aussi NaN
                raise ValueError(
                    f"Multiplicateur de lead time invalide pour {node_id!r} : {facteur!r}"
                )

    def _exiger_noeud(self, node_id: str) -> None:
        """Lève ``ValueError`` si ``node_id`` est inconnu du dépôt."""
        if self._repo.get_node(node_id) is None:
            raise ValueError(f"Nœud inconnu : {node_id!r}")

    def _surcharges_effectives(self, scenario: Scenario) -> dict[str, float]:
        """Overrides de ``ur_local`` : statuts simulés, puis surcharges explicites.

        Les statuts simulés passent par la règle de statut unifiée
        (:func:`effective_ur_local`) appliquée au ``ur_local`` MESURÉ du
        nœud ; une surcharge explicite sur le même nœud est prioritaire
        (elle écrase la valeur dérivée du statut).
        """
        overrides: dict[str, float] = {}
        for node_id, statut in scenario.statuts.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # garanti par _valider
            overrides[node_id] = effective_ur_local(statut, node.urgency.ur_local)
        overrides.update(scenario.surcharges_ur)
        return overrides

    def _moteur_simule(self, scenario: Scenario) -> PropagationEngine:
        """Moteur de propagation jetable sur la vue aux arcs rompus masqués.

        Sans arc supprimé, le moteur d'origine suffit (les overrides portent
        seuls le scénario) — on évite la vue et son indirection.
        """
        if not scenario.arcs_supprimes:
            return self._engine
        vue = _VueArcsMasquees(self._repo, frozenset(scenario.arcs_supprimes))
        return PropagationEngine(vue)

    def _avertissements(self, scenario: Scenario) -> list[str]:
        """Avertissements sur les champs du scénario non pris en compte."""
        if not scenario.multiplicateurs_lead_time:
            return []
        ids = ", ".join(sorted(scenario.multiplicateurs_lead_time))
        return [_AVERTISSEMENT_LEAD_TIME.format(ids=ids)]
