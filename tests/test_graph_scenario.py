"""Tests du MoteurScenario (E15.1) : chocs composites, purete, non-additivite.

Chaine de reference C (rang 2) -> B (rang 1) -> A (rang 0, client final),
beta(C->B)=0.5, beta(B->A)=0.7, ur_loc = (A: 0.1, B: 0.3, C: 0.6) :

    Ur_C = 0.6
    Ur_B = 1 - (1 - 0.3) - (1 - 0.5-0.6)  = 1 - 0.7-0.70  = 0.51
    Ur_A = 1 - (1 - 0.1) - (1 - 0.7-0.51) = 1 - 0.9-0.643 = 0.4213
"""

from __future__ import annotations

import copy

import pytest

from supplyscore.domain.models import SupplyArc, SupplyNode, TaskStatus, UrgencyState
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine
from supplyscore.graph.scenario import (
    MoteurScenario,
    ResultatScenario,
    Scenario,
    _VueArcsMasquees,
)

APPROX = 1e-4  # tolerance du PLAN sur les deltas chiffres

UD_LOCAL = {"A": 0.5, "B": 0.2, "C": 0.1}
UR_LOCAL = {"A": 0.1, "B": 0.3, "C": 0.6}
GAMMA = {("C", "B"): 0.8, ("B", "A"): 0.6}
BETA = {("C", "B"): 0.5, ("B", "A"): 0.7}

# Valeurs propagees de reference (recalcul manuel, cf. docstring du module).
UR_BASE = {"A": 0.4213, "B": 0.51, "C": 0.6}
# Ud : A = 0.5 ; Ud_B = 1 - 0.8-(1 - 0.6-0.5) = 0.44 ; Ud_C = 1 - 0.9-(1 - 0.8-0.44) = 0.4168
UD_BASE = {"A": 0.5, "B": 0.44, "C": 0.4168}


def make_chain() -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()
    for node_id in ("A", "B", "C"):
        repo.add_node(
            SupplyNode(
                id=node_id,
                name=f"Node {node_id}",
                urgency=UrgencyState(ud_local=UD_LOCAL[node_id], ur_local=UR_LOCAL[node_id]),
            )
        )
    for source_id, target_id in (("C", "B"), ("B", "A")):
        repo.add_arc(
            SupplyArc(
                source_id=source_id,
                target_id=target_id,
                gamma=GAMMA[(source_id, target_id)],
                beta=BETA[(source_id, target_id)],
            )
        )
    repo.assign_ranks()
    return repo


def make_moteur() -> tuple[InMemoryGraphRepository, MoteurScenario]:
    repo = make_chain()
    return repo, MoteurScenario(repo, PropagationEngine(repo))


# Baseline et scenario vide


def test_baseline_chaine_reference() -> None:
    """Baseline : Ur_A = 1 - (1-0.1)-(1 - 0.7-0.51) = 0.4213 (Ur_B = 0.51, Ur_C = 0.6)."""
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario())
    for node_id, attendu in UR_BASE.items():
        assert res.baseline_ur[node_id] == pytest.approx(attendu, abs=APPROX)
    for node_id, attendu in UD_BASE.items():
        assert res.baseline_ud[node_id] == pytest.approx(attendu, abs=APPROX)


def test_scenario_vide_deltas_exactement_nuls() -> None:
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario())
    assert all(delta == 0.0 for delta in res.delta_ur.values())
    assert all(delta == 0.0 for delta in res.delta_ud.values())
    assert res.scenario_ur == res.baseline_ur
    assert res.scenario_ud == res.baseline_ud
    assert res.avertissements == []


# Chocs unitaires et non-additivite


def test_choc_c_seul_delta_ur_a() -> None:
    """Choc C->1.0 : Ur_B' = 0.65, Ur_A' = 1 - 0.9-(1-0.7-0.65) = 0.5095 => DeltaUr_A = +0.0882."""
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario(surcharges_ur={"C": 1.0}))
    assert res.delta_ur["A"] == pytest.approx(0.0882, abs=APPROX)
    assert res.delta_ur["C"] == pytest.approx(0.4, abs=APPROX)


def test_choc_b_seul_delta_ur_a() -> None:
    """Choc B->1.0 : Ur_B' = 1.0, Ur_A' = 1 - 0.9-(1-0.7) = 0.73 => DeltaUr_A = +0.3087."""
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario(surcharges_ur={"B": 1.0}))
    assert res.delta_ur["A"] == pytest.approx(0.3087, abs=APPROX)


def test_double_choc_non_additif() -> None:
    """NON-ADDITIVITE des chocs - encart pedagogique du PLAN (E15.1).

    Les chocs ne s'additionnent PAS : la propagation est multiplicative
    (forme " survie " 1 - Pi(1 - beta-Ur)), pas lineaire.

    - choc C->1 seul   : DeltaUr_A = +0.0882 ;
    - choc B->1 seul   : DeltaUr_A = +0.3087 ;
    - double {B->1, C->1} : Ur_B' = 1 - (1-1)-(1-0.5-1) = 1.0 - le ur_local
      simule de B SATURE B a 1.0 et MASQUE entierement le choc sur C
      (le facteur (1 - Ur_loc_B) = 0 annule la contribution amont) ;
      d'ou Ur_A' = 0.73 et DeltaUr_A = +0.3087, IDENTIQUE au choc B seul,
      et non 0.0882 + 0.3087 = 0.3969.

    Un tableau de bord qui sommerait des DeltaUr unitaires SURESTIMERAIT donc le
    risque combine : seul le scenario composite donne la vraie valeur.
    """
    _, moteur = make_moteur()
    delta_c = moteur.evaluer(Scenario(surcharges_ur={"C": 1.0})).delta_ur["A"]
    delta_b = moteur.evaluer(Scenario(surcharges_ur={"B": 1.0})).delta_ur["A"]
    delta_double = moteur.evaluer(Scenario(surcharges_ur={"B": 1.0, "C": 1.0})).delta_ur["A"]

    assert delta_double == pytest.approx(0.3087, abs=APPROX)
    # Exactement le choc B seul : B sature masque C (memes operations flottantes).
    assert delta_double == delta_b
    # ... et PAS la somme des chocs unitaires (0.3969) : sous-additivite ici.
    somme = delta_b + delta_c
    assert somme == pytest.approx(0.3969, abs=APPROX)
    assert abs(delta_double - somme) > 1e-3
    assert delta_double < somme


# Statuts simules


def test_statut_abandonne_equivaut_surcharge_un() -> None:
    """ABANDONED simule sur C == surcharge C->1.0 : deltas STRICTEMENT identiques."""
    _, moteur = make_moteur()
    res_statut = moteur.evaluer(Scenario(statuts={"C": TaskStatus.ABANDONED}))
    res_surcharge = moteur.evaluer(Scenario(surcharges_ur={"C": 1.0}))
    assert res_statut.delta_ur == res_surcharge.delta_ur
    assert res_statut.scenario_ur == res_surcharge.scenario_ur
    assert res_statut.delta_ud == res_surcharge.delta_ud


def test_statut_done_b_contribution_nulle() -> None:
    """DONE simule sur B : Ur_loc_B effectif 0 => delta NEGATIF sur B et sur A.

    Ur_B' = 1 - (1-0)-(1-0.5-0.6) = 0.30 (B portait 0.3 d'urgence propre) ;
    Ur_A' = 1 - 0.9-(1-0.7-0.30) = 0.289 => DeltaUr_B = -0.21, DeltaUr_A = -0.1323.
    """
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario(statuts={"B": TaskStatus.DONE}))
    assert res.delta_ur["B"] == pytest.approx(-0.21, abs=APPROX)
    assert res.delta_ur["A"] == pytest.approx(-0.1323, abs=APPROX)
    assert res.delta_ur["A"] < 0.0
    assert res.delta_ur["C"] == 0.0  # l'amont de B n'est pas touche


def test_surcharge_explicite_prioritaire_sur_statut() -> None:
    """Surcharge ET statut sur le meme noeud : la surcharge explicite l'emporte.

    ABANDONED vaudrait 1.0, mais la surcharge 0.6 (== ur_local courant de C)
    est prioritaire => aucun delta nulle part.
    """
    _, moteur = make_moteur()
    res = moteur.evaluer(
        Scenario(statuts={"C": TaskStatus.ABANDONED}, surcharges_ur={"C": UR_LOCAL["C"]})
    )
    assert all(delta == 0.0 for delta in res.delta_ur.values())


# Arcs supprimes


def test_arc_supprime_isole_le_choc_amont() -> None:
    """Arc (C, B) rompu : un choc sur C ne change plus RIEN sur B ni A.

    Sous {arc rompu + choc C->1} comme sous {arc rompu seul}, B est prive de
    son fournisseur : Ur_B' = ur_loc_B = 0.3, Ur_A' = 1 - 0.9-(1-0.7-0.3) =
    0.289 - STRICTEMENT identiques, le choc sur C est isole.
    """
    _, moteur = make_moteur()
    res_combo = moteur.evaluer(Scenario(arcs_supprimes=[("C", "B")], surcharges_ur={"C": 1.0}))
    res_arc_seul = moteur.evaluer(Scenario(arcs_supprimes=[("C", "B")]))

    # DeltaUr du choc sur C, a arc rompu : NUL sur A et B (memes valeurs exactes).
    assert res_combo.scenario_ur["B"] == res_arc_seul.scenario_ur["B"]
    assert res_combo.scenario_ur["A"] == res_arc_seul.scenario_ur["A"]
    assert res_combo.scenario_ur["B"] == pytest.approx(UR_LOCAL["B"], abs=APPROX)
    assert res_combo.scenario_ur["A"] == pytest.approx(0.289, abs=APPROX)
    # Le choc reste visible sur C lui-meme.
    assert res_combo.delta_ur["C"] == pytest.approx(0.4, abs=APPROX)
    assert res_arc_seul.delta_ur["C"] == 0.0


def test_arc_supprime_effet_ud_remonte_vers_la_source() -> None:
    """Arc (C, B) rompu : C perd son client => Ud_C retombe a ud_local ; A et B intacts.

    Ud_C passe de 0.4168 a ud_loc_C = 0.1 (DeltaUd_C = -0.3168) ; Ud_A et Ud_B ne
    dependent pas de l'arc (C, B) => deltas EXACTEMENT nuls.
    """
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario(arcs_supprimes=[("C", "B")]))
    assert res.delta_ud["C"] == pytest.approx(UD_LOCAL["C"] - UD_BASE["C"], abs=APPROX)
    assert res.delta_ud["A"] == 0.0
    assert res.delta_ud["B"] == 0.0


def test_surcharges_et_statuts_ne_changent_pas_ud() -> None:
    """Sans rupture d'arc, Ud est INSENSIBLE au scenario (decision no1 : statut sans effet)."""
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario(surcharges_ur={"C": 1.0}, statuts={"B": TaskStatus.ABANDONED}))
    assert all(delta == 0.0 for delta in res.delta_ud.values())


# Validation


@pytest.mark.parametrize("valeur", [-0.1, 1.5, float("nan")])
def test_surcharge_hors_bornes_leve_value_error(valeur: float) -> None:
    _, moteur = make_moteur()
    with pytest.raises(ValueError, match="hors \\[0, 1\\]"):
        moteur.evaluer(Scenario(surcharges_ur={"C": valeur}))


def test_noeud_inconnu_dans_surcharges_leve_value_error() -> None:
    _, moteur = make_moteur()
    with pytest.raises(ValueError, match="inconnu"):
        moteur.evaluer(Scenario(surcharges_ur={"fantome": 0.5}))


def test_noeud_inconnu_dans_statuts_leve_value_error() -> None:
    _, moteur = make_moteur()
    with pytest.raises(ValueError, match="inconnu"):
        moteur.evaluer(Scenario(statuts={"fantome": TaskStatus.DONE}))


def test_arc_inconnu_leve_value_error() -> None:
    _, moteur = make_moteur()
    with pytest.raises(ValueError, match="Arc inconnu"):
        moteur.evaluer(Scenario(arcs_supprimes=[("A", "C")]))  # sens inverse : inexistant


def test_noeud_inconnu_dans_multiplicateurs_leve_value_error() -> None:
    _, moteur = make_moteur()
    with pytest.raises(ValueError, match="inconnu"):
        moteur.evaluer(Scenario(multiplicateurs_lead_time={"fantome": 2.0}))


@pytest.mark.parametrize("facteur", [-0.5, float("nan")])
def test_multiplicateur_invalide_leve_value_error(facteur: float) -> None:
    _, moteur = make_moteur()
    with pytest.raises(ValueError, match="Multiplicateur"):
        moteur.evaluer(Scenario(multiplicateurs_lead_time={"C": facteur}))


# Multiplicateurs de lead time : ignores avec avertissement


def test_multiplicateurs_lead_time_ignores_avec_avertissement() -> None:
    """Semantique E15.1 : multiplicateurs valides puis IGNORES (reserves au mode MC)."""
    _, moteur = make_moteur()
    res = moteur.evaluer(Scenario(multiplicateurs_lead_time={"B": 3.0, "C": 0.0}))
    assert all(delta == 0.0 for delta in res.delta_ur.values())
    assert all(delta == 0.0 for delta in res.delta_ud.values())
    assert len(res.avertissements) == 1
    assert "lead time" in res.avertissements[0]
    assert "Monte Carlo" in res.avertissements[0]
    assert "B, C" in res.avertissements[0]


# Purete


def _scenario_composite() -> Scenario:
    return Scenario(
        nom="catastrophe composite",
        surcharges_ur={"C": 1.0},
        statuts={"B": TaskStatus.ABANDONED},
        arcs_supprimes=[("B", "A")],
        multiplicateurs_lead_time={"A": 2.0},
    )


def test_evaluer_laisse_les_urgency_state_bit_a_bit_inchangees() -> None:
    """PURETE : toutes les UrgencyState (deepcopy avant) sont identiques apres evaluer."""
    repo, moteur = make_moteur()
    avant = {node.id: (copy.deepcopy(node.urgency), node.status) for node in repo.nodes()}
    moteur.evaluer(_scenario_composite())
    apres = {node.id: (node.urgency, node.status) for node in repo.nodes()}
    assert apres == avant  # UrgencyState est un dataclass : egalite champ a champ
    # La structure n'a pas bouge non plus : l'arc " supprime " est toujours la.
    assert repo.get_arc("B", "A") is not None
    assert len(repo.arcs()) == 2


def test_evaluer_pur_meme_apres_propagation_persistee() -> None:
    """PURETE apres propagate_all : les valeurs propagees en cache ne sont pas reecrites."""
    repo = make_chain()
    engine = PropagationEngine(repo)
    engine.propagate_all()  # pose ud/ur/timestamp sur chaque noeud
    moteur = MoteurScenario(repo, engine)

    avant = {node.id: copy.deepcopy(node.urgency) for node in repo.nodes()}
    moteur.evaluer(_scenario_composite())
    apres = {node.id: node.urgency for node in repo.nodes()}
    assert apres == avant


def test_evaluer_deux_fois_donne_des_resultats_identiques() -> None:
    _repo, moteur = make_moteur()
    scenario = _scenario_composite()
    res1 = moteur.evaluer(scenario)
    res2 = moteur.evaluer(scenario)
    assert isinstance(res1, ResultatScenario)
    assert res2.baseline_ur == res1.baseline_ur
    assert res2.scenario_ur == res1.scenario_ur
    assert res2.baseline_ud == res1.baseline_ud
    assert res2.scenario_ud == res1.scenario_ud
    assert res2.delta_ur == res1.delta_ur
    assert res2.delta_ud == res1.delta_ud
    assert res2.avertissements == res1.avertissements


# Vue en lecture seule (garantie structurelle de purete)


def test_vue_arcs_masques_refuse_toute_mutation() -> None:
    repo = make_chain()
    vue = _VueArcsMasquees(repo, frozenset())
    node = repo.get_node("A")
    assert node is not None
    arc = repo.get_arc("C", "B")
    assert arc is not None
    with pytest.raises(TypeError, match="lecture seule"):
        vue.add_node(node)
    with pytest.raises(TypeError, match="lecture seule"):
        vue.update_node(node)
    with pytest.raises(TypeError, match="lecture seule"):
        vue.remove_node("A")
    with pytest.raises(TypeError, match="lecture seule"):
        vue.add_arc(arc)
    with pytest.raises(TypeError, match="lecture seule"):
        vue.remove_arc("C", "B")
    with pytest.raises(TypeError, match="lecture seule"):
        vue.clear()


def test_vue_arcs_masques_filtre_les_lectures() -> None:
    repo = make_chain()
    vue = _VueArcsMasquees(repo, frozenset({("C", "B")}))
    # L'arc masque disparait de toutes les lectures...
    assert vue.get_arc("C", "B") is None
    assert {(a.source_id, a.target_id) for a in vue.arcs()} == {("B", "A")}
    assert vue.predecessors("B") == []
    assert [s.id for s in vue.successors("C")] == []
    # ... mais le reste du graphe est delegue tel quel.
    assert vue.get_arc("B", "A") is not None
    assert [p.id for p in vue.predecessors("A")] == ["B"]
    assert vue.get_node("A") is repo.get_node("A")
    assert len(vue.nodes()) == 3
    assert vue.topological_order() == repo.topological_order()
    assert vue.nodes_by_project("aucun") == []
