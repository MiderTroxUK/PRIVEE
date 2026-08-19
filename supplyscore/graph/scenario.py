"""Scenarios catastrophe composites - evaluation what-if PURE du graphe (E15.1).

Un :class:`Scenario` combine plusieurs chocs simultanes : surcharges de
``ur_local``, statuts simules, arcs rompus et multiplicateurs de lead time.
:meth:`MoteurScenario.evaluer` calcule les urgences propagees de reference
(baseline) et du scenario, puis leurs deltas par noeud, SANS JAMAIS ecrire -
ni dans le depot, ni dans les ``UrgencyState`` des noeuds : l'etat du graphe
est bit a bit inchange apres evaluation.

Approche retenue : OVERRIDES, pas " ecrire puis restaurer ".
:meth:`PropagationEngine.propagate_all` persiste ``node.urgency`` ; le moteur
de scenarios n'y recourt donc jamais et reutilise les calculs PURS internes
du moteur de propagation (mecanisme deja eprouve par ``simulate_shock``) :

- ``PropagationEngine._compute_ur(overrides)`` : les surcharges de
  ``ur_local`` (explicites, ou derivees d'un statut simule via
  :func:`supplyscore.core.status_rules.effective_ur_local`) sont passees en
  overrides multiples - aucune ecriture ;
- ``PropagationEngine._compute_ud()`` : calcul pur symetrique pour Ud. Les
  scenarios n'alterent Ud que par rupture d'arc : ni les surcharges Ur ni
  les statuts simules ne touchent Ud (decision de modelisation no1, cf.
  :func:`supplyscore.core.status_rules.effective_ud_local` - le statut
  n'ecrase pas le besoin declare) ;
- les arcs supprimes sont MASQUES par :class:`_VueArcsMasquees`, vue en
  LECTURE SEULE du depot qui filtre ``predecessors``/``successors``/
  ``get_arc``/``arcs`` et REFUSE toute mutation (garantie structurelle de
  purete pendant le calcul du scenario). L'ordre topologique du graphe
  complet reste un ordre topologique valide du graphe prive d'arcs (retirer
  des arcs ne cree aucune contrainte d'ordre), la vue le delegue donc tel quel.

L'acces aux methodes ``_compute_*`` du moteur de propagation est une
collaboration interne au package ``supplyscore.graph`` : la dupliquer ici
creerait une seconde implementation de la recurrence de propagation.

Semantique SIMPLE des ``multiplicateurs_lead_time`` (PLAN.md E15.1) : le
moteur analytique ne dispose ni du service ni du ``UrModel`` necessaires pour
recalculer le ``u_time`` d'un noeud a partir d'un lead time multiplie. Les
multiplicateurs sont donc VALIDES (noeud connu, facteur >= 0) puis IGNORES,
avec un avertissement explicite dans ``ResultatScenario.avertissements``.
Champ reserve au mode Monte Carlo (E16+).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.models import SupplyArc, SupplyNode, TaskStatus
from supplyscore.graph.propagation import PropagationEngine
from supplyscore.graph.repository import GraphRepository

#: Message d'avertissement emis quand des multiplicateurs de lead time sont fournis : ils sont ignores par le moteur analytique (reserves au mode MC).
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
    """Scenario catastrophe composite : plusieurs chocs simultanes sur le graphe.

    Attributes:
        nom: libelle du scenario (affichage UI, persistance E15.3).
        surcharges_ur: ``{node_id: ur_local simule}``, valeurs dans [0, 1].
            Prioritaires sur ``statuts`` si un noeud apparait dans les deux.
        statuts: ``{node_id: statut simule}`` - traduit en surcharge de
            ``ur_local`` via la regle de statut unifiee (DONE -> 0.0,
            ABANDONED -> 1.0, ACTIVE -> ``ur_local`` mesure). Sans effet sur
            Ud (decision de modelisation no1).
        arcs_supprimes: liste de ``(source_id, target_id)`` d'arcs rompus,
            masques pendant le calcul (le depot n'est pas modifie).
        multiplicateurs_lead_time: ``{node_id: facteur >= 0}`` - valides puis
            IGNORES par le moteur analytique (avertissement dans le
            resultat) ; reserves au mode Monte Carlo (E16+).
    """

    nom: str = "scénario"
    surcharges_ur: dict[str, float] = field(default_factory=dict)
    statuts: dict[str, TaskStatus] = field(default_factory=dict)
    arcs_supprimes: list[tuple[str, str]] = field(default_factory=list)
    multiplicateurs_lead_time: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultatScenario:
    """Urgences propagees baseline vs scenario, et deltas par noeud.

    Attributes:
        scenario: le scenario evalue (tel que fourni).
        baseline_ur: ``{node_id: Ur}`` propage sans choc (reference).
        scenario_ur: ``{node_id: Ur}`` propage sous scenario.
        baseline_ud: ``{node_id: Ud}`` propage sans choc (reference).
        scenario_ud: ``{node_id: Ud}`` propage sous scenario.
        delta_ur: ``scenario_ur - baseline_ur`` par noeud.
        delta_ud: ``scenario_ud - baseline_ud`` par noeud.
        avertissements: messages francais sur les champs non pris en compte
            (p. ex. multiplicateurs de lead time, reserves au mode MC).
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
    """Vue en LECTURE SEULE d'un depot, masquant un ensemble d'arcs.

    Les lectures sont deleguees au depot enveloppe, en filtrant les arcs
    masques dans ``get_arc``, ``arcs``, ``predecessors`` et ``successors``
    (quelle que soit leur nature, nominal ou backup). ``topological_order``
    est delegue tel quel : l'ordre topologique du graphe complet reste valide
    pour le graphe prive d'arcs. TOUTE mutation leve ``TypeError`` - c'est la
    garantie structurelle de purete du moteur de scenarios.
    """

    def __init__(self, repo: GraphRepository, masques: frozenset[tuple[str, str]]) -> None:
        """Enveloppe ``repo`` en masquant les arcs ``(source_id, target_id)`` donnes."""
        self._repo = repo
        self._masques = masques

    # Lectures (deleguees, arcs filtres)

    def get_node(self, node_id: str) -> SupplyNode | None:
        """Retourne le noeud du depot enveloppe, ou None s'il est inconnu."""
        return self._repo.get_node(node_id)

    def get_arc(self, source_id: str, target_id: str) -> SupplyArc | None:
        """Retourne l'arc du depot enveloppe, ou None s'il est masque ou inconnu."""
        if (source_id, target_id) in self._masques:
            return None
        return self._repo.get_arc(source_id, target_id)

    def nodes(self) -> list[SupplyNode]:
        """Tous les noeuds du depot enveloppe (les noeuds ne sont jamais masques)."""
        return self._repo.nodes()

    def arcs(self, kinds: tuple[str, ...] | None = None) -> list[SupplyArc]:
        """Arcs du depot enveloppe filtres par nature, sans les arcs masques."""
        return [
            arc
            for arc in self._repo.arcs(kinds)
            if (arc.source_id, arc.target_id) not in self._masques
        ]

    def predecessors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Fournisseurs directs, sans ceux relies par un arc masque."""
        return [
            pred
            for pred in self._repo.predecessors(node_id, kinds=kinds)
            if (pred.id, node_id) not in self._masques
        ]

    def successors(
        self, node_id: str, *, kinds: tuple[str, ...] = ("nominal",)
    ) -> list[SupplyNode]:
        """Clients directs, sans ceux relies par un arc masque."""
        return [
            succ
            for succ in self._repo.successors(node_id, kinds=kinds)
            if (node_id, succ.id) not in self._masques
        ]

    def nodes_by_project(self, project_id: str) -> list[SupplyNode]:
        """Noeuds du projet donne (delegue tel quel)."""
        return self._repo.nodes_by_project(project_id)

    def topological_order(self) -> list[str]:
        """Ordre topologique du graphe complet - valide aussi prive d'arcs."""
        return self._repo.topological_order()

    # Mutations (interdites : purete)

    def add_node(self, node: SupplyNode) -> None:
        """Interdit - la vue de scenario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def update_node(self, node: SupplyNode) -> None:
        """Interdit - la vue de scenario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def remove_node(self, node_id: str) -> None:
        """Interdit - la vue de scenario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def add_arc(self, arc: SupplyArc) -> None:
        """Interdit - la vue de scenario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Interdit - la vue de scenario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)

    def clear(self) -> None:
        """Interdit - la vue de scenario est en lecture seule."""
        raise TypeError(_ERREUR_LECTURE_SEULE)


class MoteurScenario:
    """Evalue des scenarios composites sans JAMAIS ecrire dans le graphe.

    Le moteur reutilise les calculs purs du :class:`PropagationEngine`
    (``_compute_ud`` / ``_compute_ur(overrides)``) : la baseline est
    l'equivalent d'un ``propagate_all`` SANS persistance, le scenario est
    calcule avec les surcharges en overrides et les arcs rompus masques par
    une vue en lecture seule. Voir la docstring du module pour l'approche
    complete (overrides, pas de restauration d'etat).
    """

    def __init__(self, repo: GraphRepository, engine: PropagationEngine) -> None:
        """Initialise le moteur de scenarios.

        Args:
            repo: depot de graphe (jamais modifie par ce moteur).
            engine: moteur de propagation construit sur ``repo`` - seuls ses
                calculs PURS (sans ecriture) sont utilises.
        """
        self._repo = repo
        self._engine = engine

    def evaluer(self, scenario: Scenario) -> ResultatScenario:
        """Evalue ``scenario`` et retourne baseline, valeurs choquees et deltas.

        PUR : aucune ecriture, ni dans le depot ni dans les ``UrgencyState``
        des noeuds - l'etat du graphe est bit a bit inchange apres l'appel, et
        deux appels successifs retournent des resultats identiques.

        Args:
            scenario: scenario composite a evaluer.

        Returns:
            :class:`ResultatScenario` avec les urgences propagees de
            reference (baseline), celles du scenario et les deltas par noeud.

        Raises:
            ValueError: si un ``node_id`` ou un arc du scenario est inconnu
                du depot, si une surcharge sort de [0, 1], ou si un
                multiplicateur de lead time est negatif.
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

    # Aides internes

    def _valider(self, scenario: Scenario) -> None:
        """Verifie ids et bornes du scenario ; leve ``ValueError`` en francais."""
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
            if not facteur >= 0.0:  # " not >= " plutot que " < " : rejette aussi NaN
                raise ValueError(
                    f"Multiplicateur de lead time invalide pour {node_id!r} : {facteur!r}"
                )

    def _exiger_noeud(self, node_id: str) -> None:
        """Leve ``ValueError`` si ``node_id`` est inconnu du depot."""
        if self._repo.get_node(node_id) is None:
            raise ValueError(f"Nœud inconnu : {node_id!r}")

    def _surcharges_effectives(self, scenario: Scenario) -> dict[str, float]:
        """Overrides de ``ur_local`` : statuts simules, puis surcharges explicites.

        Les statuts simules passent par la regle de statut unifiee
        (:func:`effective_ur_local`) appliquee au ``ur_local`` MESURE du
        noeud ; une surcharge explicite sur le meme noeud est prioritaire
        (elle ecrase la valeur derivee du statut).
        """
        overrides: dict[str, float] = {}
        for node_id, statut in scenario.statuts.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # garanti par _valider
            overrides[node_id] = effective_ur_local(statut, node.urgency.ur_local)
        overrides.update(scenario.surcharges_ur)
        return overrides

    def _moteur_simule(self, scenario: Scenario) -> PropagationEngine:
        """Moteur de propagation jetable sur la vue aux arcs rompus masques.

        Sans arc supprime, le moteur d'origine suffit (les overrides portent
        seuls le scenario) - on evite la vue et son indirection.
        """
        if not scenario.arcs_supprimes:
            return self._engine
        vue = _VueArcsMasquees(self._repo, frozenset(scenario.arcs_supprimes))
        return PropagationEngine(vue)

    def _avertissements(self, scenario: Scenario) -> list[str]:
        """Avertissements sur les champs du scenario non pris en compte."""
        if not scenario.multiplicateurs_lead_time:
            return []
        ids = ", ".join(sorted(scenario.multiplicateurs_lead_time))
        return [_AVERTISSEMENT_LEAD_TIME.format(ids=ids)]
