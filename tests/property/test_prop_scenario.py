"""Proprietes Hypothesis du moteur de scenarios composites - PLAN.md, Lot 15.1 (E15).

Invariants verifies sur des DAG aleatoires (``RandomSupplyChainGenerator``
seede par Hypothesis, ``ud_local``/``ur_local``/gamma/beta re-tires dans [0, 1]) :

1. scenario VIDE => tous les deltas (Ur ET Ud) exactement nuls ;
2. monotonie : ajouter un choc AGGRAVANT (surcharge plus haute que le
   ``ur_local`` effectif, sur un noeud de plus) ne diminue aucun DeltaUr ;
3. suppression d'arc (s->t) => DeltaUr == 0 sur tout noeud hors {t, descendants(t)}
   (t lui-meme est inclus dans la zone affectee : son Ur perd la contribution
   de s) ; symetriquement DeltaUd == 0 hors {s, ancestors(s)} ;
4. purete systematique : apres ``evaluer`` d'un scenario composite aleatoire,
   toutes les ``UrgencyState`` et statuts sont bit a bit inchanges, et un
   second ``evaluer`` retourne des resultats identiques.
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

# Urgences et coefficients tires dans [0, 1], sans NaN ni infinis.
_UNIT = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


# Strategies et aides


@st.composite
def dag_cases(draw: st.DrawFn) -> tuple[list[SupplyNode], list[SupplyArc]]:
    """DAG par rangs via le generateur seede ; ud_local/ur_local/gamma/beta re-tires dans [0, 1]."""
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
    """Charge le DAG dans un depot memoire et construit le moteur de scenarios."""
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
    """Scenario composite tire au hasard : surcharges, statuts et arcs rompus."""
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


# 1. Scenario vide => deltas nuls


@given(case=dag_cases())
def test_scenario_vide_donne_des_deltas_exactement_nuls(
    case: tuple[list[SupplyNode], list[SupplyArc]],
) -> None:
    """Scenario vide : memes entrees, memes operations => deltas EXACTEMENT 0.0 partout."""
    nodes, arcs = case
    _repo, moteur = _build_moteur(nodes, arcs)
    res = moteur.evaluer(Scenario())
    assert all(delta == 0.0 for delta in res.delta_ur.values())
    assert all(delta == 0.0 for delta in res.delta_ud.values())
    assert res.avertissements == []


# 2. Monotonie : un choc aggravant de plus


@given(case=dag_cases(), data=st.data())
def test_choc_aggravant_supplementaire_ne_diminue_aucun_delta_ur(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Ajouter une surcharge >= ur_local effectif sur un noeud DE PLUS => aucun DeltaUr ne baisse.

    Ur est monotone croissant en chaque urgence locale effective : les deux
    scenarios ne different que sur le noeud supplementaire, dont l'urgence
    locale passe de sa valeur effective courante a une valeur >= (aggravante).
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


# 3. Suppression d'arc : effet confine au cone


@given(case=dag_cases(), data=st.data())
def test_suppression_arc_sans_effet_hors_du_cone(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Rompre (s->t) => DeltaUr == 0 hors {t, descendants(t)}, DeltaUd == 0 hors {s, ancestors(s)}.

    t (resp. s) appartient a la zone affectee : son Ur (resp. Ud) perd la
    contribution de l'arc. Hors zone : memes entrees, memes operations =>
    delta EXACTEMENT 0. Les cones sont calcules sur le graphe COMPLET : l'arc
    (s->t) ne participe a aucun chemin partant de t ni arrivant a s (DAG),
    les cones du graphe prive de l'arc sont donc identiques.
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


# 4. Purete systematique


@given(case=dag_cases(), data=st.data())
def test_evaluer_laisse_le_graphe_bit_a_bit_inchange(
    case: tuple[list[SupplyNode], list[SupplyArc]], data: st.DataObject
) -> None:
    """Apres evaluer (scenario composite aleatoire), etats et structure inchanges.

    L'etat de depart est REALISTE : un ``propagate_all`` prealable pose
    ud/ur/timestamp sur chaque noeud, valeurs que ``evaluer`` ne doit pas
    reecrire. Un second ``evaluer`` redonne des resultats identiques.
    """
    nodes, arcs = case
    repo, moteur = _build_moteur(nodes, arcs)
    PropagationEngine(repo).propagate_all()  # etat propage realiste avant le what-if
    scenario = _scenario_composite_aleatoire(data, nodes, arcs)

    avant_etats = {node.id: (copy.deepcopy(node.urgency), node.status) for node in repo.nodes()}
    avant_arcs = {(a.source_id, a.target_id) for a in repo.arcs()}

    res1 = moteur.evaluer(scenario)

    apres_etats = {node.id: (node.urgency, node.status) for node in repo.nodes()}
    assert apres_etats == avant_etats  # UrgencyState : dataclass, egalite champ a champ
    assert {(a.source_id, a.target_id) for a in repo.arcs()} == avant_arcs

    res2 = moteur.evaluer(scenario)
    assert res2.baseline_ur == res1.baseline_ur
    assert res2.scenario_ur == res1.scenario_ur
    assert res2.baseline_ud == res1.baseline_ud
    assert res2.scenario_ud == res1.scenario_ud
    assert res2.delta_ur == res1.delta_ur
    assert res2.delta_ud == res1.delta_ud
