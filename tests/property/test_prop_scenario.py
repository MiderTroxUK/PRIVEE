"""Propriétés Hypothesis du moteur de scénarios composites — PLAN.md, Lot 15.1 (E15).

Invariants vérifiés sur des DAG aléatoires (``RandomSupplyChainGenerator``
seedé par Hypothesis, ``ud_local``/``ur_local``/γ/β re-tirés dans [0, 1]) :

1. scénario VIDE ⇒ tous les deltas (Ur ET Ud) exactement nuls ;
2. monotonie : ajouter un choc AGGRAVANT (surcharge plus haute que le
   ``ur_local`` effectif, sur un nœud de plus) ne diminue aucun ΔUr ;
3. suppression d'arc (s→t) ⇒ ΔUr == 0 sur tout nœud hors {t, descendants(t)}
   (t lui-même est inclus dans la zone affectée : son Ur perd la contribution
   de s) ; symétriquement ΔUd == 0 hors {s, ancestors(s)} ;
4. pureté systématique : après ``evaluer`` d'un scénario composite aléatoire,
   toutes les ``UrgencyState`` et statuts sont bit à bit inchangés, et un
   second ``evaluer`` retourne des résultats identiques.
"""

from __future__ import annotations

import copy

from hypothesis import assume, given
from hypothesis import strategies as st

from supplyscore.core.status_rules import effective_ur_local
from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.models import SupplyArc, SupplyNode, TaskStatus, UrgencyState
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine
from supplyscore.graph.scenario import MoteurScenario, Scenario

# Urgences et coefficients tirés dans [0, 1], sans NaN ni infinis.
_UNIT = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


# --- Stratégies et aides -------------------------------------------------------------


@st.composite
def dag_cases(draw: st.DrawFn) -> tuple[list[SupplyNode], list[SupplyArc]]:
    """DAG par rangs via le générateur seedé ; ud_local/ur_local/γ/β re-tirés dans [0, 1]."""
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    n_ranks = draw(st.integers(min_value=1, max_value=3))
    _project, nodes, arcs = RandomSupplyChainGenerator(seed=seed).generate(
        n_ranks=n_ranks, breadth=(1, 2)
    )
    for node in nodes:
        node.urgency = UrgencyState(ud_local=draw(_UNIT), ur_local=draw(_UNIT), timestamp=0.0)
    for arc in arcs:
        arc.gamma = draw(_UNIT)
        arc.beta = draw(_UNIT)
    return nodes, arcs


def _build_moteur(
    nodes: list[SupplyNode], arcs: list[SupplyArc]
) -> tuple[InMemoryGraphRepository, MoteurScenario]:
    """Charge le DAG dans un dépôt mémoire et construit le moteur de scénarios."""
    repo = InMemoryGraphRepository()
    for node in nodes:
        repo.add_node(node)
    for arc in arcs:
        repo.add_arc(arc)
    repo.assign_ranks()
    return repo, MoteurScenario(repo, PropagationEngine(repo))


def _scenario_composite_aleatoire(
    data: st.DataObject, nodes: list[SupplyNode], arcs: list[SupplyArc]
) -> Scenario:
    """Scénario composite tiré au hasard : surcharges, statuts et arcs rompus."""
    surcharges: dict[str, float] = {}
    statuts: dict[str, TaskStatus] = {}
    for node in nodes:
        if data.draw(st.booleans(), label=f"surcharger {node.id} ?"):
            surcharges[node.id] = data.draw(_UNIT, label=f"surcharge de {node.id}")
        if data.draw(st.booleans(), label=f"simuler un statut sur {node.id} ?"):
            statuts[node.id] = data.draw(
                st.sampled_from(list(TaskStatus)), label=f"statut de {node.id}"
            )
    arcs_supprimes = [
        (arc.source_id, arc.target_id)
        for arc in arcs
        if data.draw(st.booleans(), label=f"rompre {arc.id} ?")
    ]
    return Scenario(surcharges_ur=surcharges, statuts=statuts, arcs_supprimes=arcs_supprimes)


# --- 1. Scénario vide ⇒ deltas nuls ---------------------------------------------------


@given(case=dag_cases())
def test_scenario_vide_donne_des_deltas_exactement_nuls(
    case: tuple[list[SupplyNode], list[SupplyArc]],
) -> None:
    """Scénario vide : mêmes entrées, mêmes opérations ⇒ deltas EXACTEMENT 0.0 partout."""
    nodes, arcs = case
    _repo, moteur = _build_moteur(nodes, arcs)
    res = moteur.evaluer(Scenario())
    assert all(delta == 0.0 for delta in res.delta_ur.values())
    assert all(delta == 0.0 for delta in res.delta_ud.values())
    assert res.avertissements == []


# --- 2. Monotonie : un choc aggravant de plus ------------------------------------------


@given(case=dag_cases(), data=st.data())
def test_choc_aggravant_supplementaire_ne_diminue_aucun_delta_ur(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Ajouter une surcharge >= ur_local effectif sur un nœud DE PLUS ⇒ aucun ΔUr ne baisse.

    Ur est monotone croissant en chaque urgence locale effective : les deux
    scénarios ne diffèrent que sur le nœud supplémentaire, dont l'urgence
    locale passe de sa valeur effective courante à une valeur >= (aggravante).
    """
    nodes, arcs = case
    _repo, moteur = _build_moteur(nodes, arcs)

    extra = nodes[data.draw(st.integers(0, len(nodes) - 1), label="indice du nœud aggravé")]
    base: dict[str, float] = {}
    for node in nodes:
        if node.id != extra.id and data.draw(st.booleans(), label=f"surcharger {node.id} ?"):
            base[node.id] = data.draw(_UNIT, label=f"surcharge de {node.id}")

    effectif = effective_ur_local(extra.status, extra.urgency.ur_local)
    frac = data.draw(_UNIT, label="fraction aggravante")
    aggravante = effectif + frac * (1.0 - effectif)  # reste dans [effectif, 1]

    res_base = moteur.evaluer(Scenario(surcharges_ur=base))
    res_plus = moteur.evaluer(Scenario(surcharges_ur={**base, extra.id: aggravante}))
    for node_id, delta in res_base.delta_ur.items():
        assert res_plus.delta_ur[node_id] >= delta - 1e-12


# --- 3. Suppression d'arc : effet confiné au cône --------------------------------------


@given(case=dag_cases(), data=st.data())
def test_suppression_arc_sans_effet_hors_du_cone(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Rompre (s→t) ⇒ ΔUr == 0 hors {t, descendants(t)}, ΔUd == 0 hors {s, ancestors(s)}.

    t (resp. s) appartient à la zone affectée : son Ur (resp. Ud) perd la
    contribution de l'arc. Hors zone : mêmes entrées, mêmes opérations ⇒
    delta EXACTEMENT 0. Les cônes sont calculés sur le graphe COMPLET : l'arc
    (s→t) ne participe à aucun chemin partant de t ni arrivant à s (DAG),
    les cônes du graphe privé de l'arc sont donc identiques.
    """
    nodes, arcs = case
    assume(arcs)
    repo, moteur = _build_moteur(nodes, arcs)

    arc = arcs[data.draw(st.integers(0, len(arcs) - 1), label="indice de l'arc rompu")]
    res = moteur.evaluer(Scenario(arcs_supprimes=[(arc.source_id, arc.target_id)]))

    zone_ur = {arc.target_id} | repo.descendants(arc.target_id)
    for node_id, delta in res.delta_ur.items():
        if node_id not in zone_ur:
            assert delta == 0.0

    zone_ud = {arc.source_id} | repo.ancestors(arc.source_id)
    for node_id, delta in res.delta_ud.items():
        if node_id not in zone_ud:
            assert delta == 0.0


# --- 4. Pureté systématique --------------------------------------------------------------


@given(case=dag_cases(), data=st.data())
def test_evaluer_laisse_le_graphe_bit_a_bit_inchange(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Après evaluer (scénario composite aléatoire), états et structure inchangés.

    L'état de départ est RÉALISTE : un ``propagate_all`` préalable pose
    ud/ur/timestamp sur chaque nœud, valeurs que ``evaluer`` ne doit pas
    réécrire. Un second ``evaluer`` redonne des résultats identiques.
    """
    nodes, arcs = case
    repo, moteur = _build_moteur(nodes, arcs)
    PropagationEngine(repo).propagate_all()  # état propagé réaliste avant le what-if
    scenario = _scenario_composite_aleatoire(data, nodes, arcs)

    avant_etats = {node.id: (copy.deepcopy(node.urgency), node.status) for node in repo.nodes()}
    avant_arcs = {(a.source_id, a.target_id) for a in repo.arcs()}

    res1 = moteur.evaluer(scenario)

    apres_etats = {node.id: (node.urgency, node.status) for node in repo.nodes()}
    assert apres_etats == avant_etats  # UrgencyState : dataclass, égalité champ à champ
    assert {(a.source_id, a.target_id) for a in repo.arcs()} == avant_arcs

    res2 = moteur.evaluer(scenario)
    assert res2.baseline_ur == res1.baseline_ur
    assert res2.scenario_ur == res1.scenario_ur
    assert res2.baseline_ud == res1.baseline_ud
    assert res2.scenario_ud == res1.scenario_ud
    assert res2.delta_ur == res1.delta_ur
    assert res2.delta_ud == res1.delta_ud
