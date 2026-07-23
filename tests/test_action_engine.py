"""Tests du moteur de décision U18 — ActionEngine (contrats 11 & 13, HÉLIOS v7).

Couvre : la définition de segment à 8 cellules, le classement hand-verifiable
(source d'effet par priorité, valeur nette vs heuristique), le filtrage par
préconditions et par incompatibilités, le bras ``ne_rien_faire`` comme plancher
de référence, la robustesse aux trois a priori U17 (qui bascule quand ils sont
en désaccord), la source causale IPW, le portefeuille glouton sous budget /
capacité / conflits inter-nœud (arc partagé, fournisseur commun) avec raisons
et avertissements de substitution, le chargement des effets depuis un fichier,
et la dégradation complète (ni U9 ni U17) sans jamais planter.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import Project, SupplyArc, SupplyNode, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.services.action_engine import (
    ActionEngine,
    ActionRecommandation,
    Selection,
    _segment,
    _union_ic,
    _valeur_scalaire,
    segment_pour_etat,
)

_SEGMENT = "proche_fluide_risque_cache"  # rang 0, ur_local 0.5, hidden_risk 0.3


# --- Doublures duck-typées ----------------------------------------------------------


@dataclass
class FakeUrgency:
    ur_local: float | None = 0.5
    ud_local: float | None = 0.2
    hidden_risk: float | None = 0.3
    false_urgency: float | None = 0.0


@dataclass
class FakeNode:
    id: str
    rank: int = 0
    urgency: FakeUrgency = field(default_factory=FakeUrgency)


@dataclass
class FakeContexte:
    node: FakeNode
    urgency: FakeUrgency
    arcs_entrants: list[Any] = field(default_factory=list)
    arcs_backup: list[Any] = field(default_factory=list)
    milestones: list[Any] = field(default_factory=list)


@dataclass
class FakeAction:
    id: str
    libelle: str
    preconditions: Callable[[Any], bool]
    delai_effet_weeks: tuple[float, float, float]
    cout: dict[str, Any]
    incompatibles: list[str]
    objectifs_operationnels: list[str]
    risque_secondaire: str = "risque secondaire de test"


@dataclass
class FakeIC:
    bas: float
    haut: float
    couverture: tuple[str, ...]


@dataclass
class FakePrev:
    p0: float
    p1: float
    delta_u_sim: float
    ic80_delta_mc: FakeIC
    ic80_delta_param: FakeIC
    p_delta_positif: float
    p_impact_client_0: float = 0.0
    p_impact_client_1: float = 0.0


@dataclass
class FakePaired:
    previsions: dict[str, dict[int, FakePrev]]
    n_draws: int


class FakeForecast:
    """Fournisseur de prévision : renvoie une prévision canned par action.id."""

    def __init__(
        self, node_id: str, prevs_par_action: dict[str, FakePrev], n_draws: int = 2000
    ) -> None:
        self._node_id = node_id
        self._prevs = prevs_par_action
        self._n_draws = n_draws

    def rollout_with_action(
        self, project_id: str, action: Any, horizon_weeks: int = 4, **_: Any
    ) -> FakePaired:
        prev = self._prevs[action.id]  # KeyError -> le moteur dégrade proprement
        return FakePaired({self._node_id: {horizon_weeks: prev}}, self._n_draws)


def make_action(
    action_id: str,
    *,
    money: str = "none",  # "both" | "one" | "none"
    precond: Callable[[Any], bool] | None = None,
    incompat: list[str] | None = None,
    objectifs: list[str] | None = None,
    temps_h: float = 1.0,
    p_echec: float = 0.05,
) -> FakeAction:
    if money == "both":
        cout: dict[str, Any] = {
            "monetaire": (1000.0, 2000.0),
            "penalite_client_evitee": (5000.0, 15000.0),
        }
    elif money == "one":
        cout = {"monetaire": (500.0, 1500.0), "penalite_client_evitee": None}
    elif money == "zero":  # bras de référence : coût et pénalité nuls (comme U15)
        cout = {"monetaire": (0.0, 0.0), "penalite_client_evitee": (0.0, 0.0)}
    else:
        cout = {"monetaire": None, "penalite_client_evitee": None}
    cout.update(
        {"temps_h": temps_h, "mobilisation": "équipe test", "p_echec_execution_defaut": p_echec}
    )
    return FakeAction(
        id=action_id,
        libelle=f"Action {action_id}",
        preconditions=precond if precond is not None else (lambda _ctx: True),
        delai_effet_weeks=(0.0, 1.0, 2.0),
        cout=cout,
        incompatibles=incompat if incompat is not None else ["ne_rien_faire"],
        objectifs_operationnels=objectifs if objectifs is not None else ["tenir_echeance_client"],
    )


def catalogue_jouet() -> dict[str, FakeAction]:
    """Catalogue jouet : 5 actions + ne_rien_faire, incompatibilités réalistes."""
    return {
        "expedition_express": make_action(
            "expedition_express",
            money="both",
            incompat=["replanifier_jalon", "ne_rien_faire"],
            objectifs=["tenir_echeance_client"],
            temps_h=1.0,
            p_echec=0.05,
        ),
        "replanifier_jalon": make_action(
            "replanifier_jalon",
            money="none",
            precond=lambda ctx: bool(ctx.milestones),
            incompat=["expedition_express", "ne_rien_faire"],
            objectifs=["renegocier_echeance"],
            temps_h=2.0,
            p_echec=0.10,
        ),
        "promouvoir_arc_secours": make_action(
            "promouvoir_arc_secours",
            money="none",
            precond=lambda ctx: bool(ctx.arcs_backup),
            incompat=["ne_rien_faire"],
            objectifs=["fiabiliser_approvisionnement"],
            temps_h=8.0,
            p_echec=0.15,
        ),
        "boost_capacite": make_action(
            "boost_capacite",
            money="one",
            incompat=["ne_rien_faire"],
            objectifs=["augmenter_capacite"],
            temps_h=4.0,
            p_echec=0.10,
        ),
        "ne_rien_faire": make_action(
            "ne_rien_faire",
            money="zero",
            incompat=[
                "expedition_express",
                "replanifier_jalon",
                "promouvoir_arc_secours",
                "boost_capacite",
            ],
            objectifs=[],
            temps_h=0.0,
            p_echec=0.0,
        ),
    }


def contexte_jouet(*, backup: bool = True, milestones: bool = True) -> FakeContexte:
    urg = FakeUrgency(ur_local=0.5, ud_local=0.2, hidden_risk=0.3, false_urgency=0.0)
    node = FakeNode(id="n1", rank=0, urgency=urg)
    return FakeContexte(
        node=node,
        urgency=urg,
        arcs_backup=["arc-backup"] if backup else [],
        milestones=["jalon"] if milestones else [],
    )


def forecast_jouet(node_id: str = "n1") -> FakeForecast:
    def ic(lo: float, hi: float, *cov: str) -> FakeIC:
        return FakeIC(lo, hi, tuple(cov))

    prevs = {
        "expedition_express": FakePrev(
            0.5, 0.2, 0.30, ic(0.25, 0.35, "mc"), ic(0.20, 0.40, "param"), 0.90
        ),
        "replanifier_jalon": FakePrev(
            0.5, 0.4, 0.10, ic(0.05, 0.15, "mc"), ic(0.00, 0.20, "param"), 0.70
        ),
        "promouvoir_arc_secours": FakePrev(
            0.5, 0.3, 0.20, ic(0.15, 0.25, "mc"), ic(0.10, 0.30, "param"), 0.80
        ),
        "boost_capacite": FakePrev(
            0.5, 0.35, 0.15, ic(0.10, 0.20, "mc"), ic(0.05, 0.25, "param"), 0.75
        ),
        "ne_rien_faire": FakePrev(
            0.5, 0.5, 0.0, ic(-0.02, 0.02, "mc"), ic(-0.05, 0.05, "param"), 0.5
        ),
    }
    return FakeForecast(node_id, prevs)


def make_reco(action_id: str, valeur: dict[str, Any]) -> ActionRecommandation:
    return ActionRecommandation(
        action_id=action_id,
        libelle=action_id,
        p0=None,
        p1={"est": None, "source": "absent"},
        delta_u={"est": None, "lo80": None, "hi80": None, "source": "absent", "couverture_ic": []},
        p_delta_positif=None,
        p_resolution_op={"est": None, "lo80": None, "hi80": None},
        p_execution=0.9,
        p_eviter=None,
        valeur=valeur,
        delai_effet_weeks=(0.0, 1.0, 2.0),
        niveau_de_preuve={"n_reel": 0, "n_sim": 0, "source_prior": None, "qualite": "faible"},
        robuste_aux_priors=False,
        justification=[],
    )


@pytest.fixture
def service(tmp_path: Path) -> Any:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(0.0))
    yield svc
    svc.close()


def _by_id(recos: list[ActionRecommandation]) -> dict[str, ActionRecommandation]:
    return {r.action_id: r for r in recos}


# --- Segment à 8 cellules ------------------------------------------------------------


class TestSegment:
    def test_huit_cellules_distinctes(self) -> None:
        combos = {
            _segment(rang, ur, h) for rang in (0, 3) for ur in (0.1, 0.9) for h in (0.05, 0.5)
        }
        assert len(combos) == 8

    def test_valeurs_nommees(self) -> None:
        assert _segment(0, 0.5, 0.3) == "proche_fluide_risque_cache"
        assert _segment(3, 0.9, 0.05) == "profond_sature_u_temps"

    def test_scores_none_traites_comme_nuls(self) -> None:
        assert _segment(0, None, None) == "proche_fluide_u_temps"

    def test_segment_pour_etat(self) -> None:
        etat = {"ur_local": 0.9, "hidden_risk": 0.5}
        assert segment_pour_etat(etat, 3) == "profond_sature_risque_cache"


# --- Recommandation : classement hand-verifiable -------------------------------------


class TestRecommander:
    def test_classement_source_sim_et_filtre_incompatibilite(self, service: Any) -> None:
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = engine.recommander("p", "n1", forecast_jouet(), contexte_jouet())
        ids = [r.action_id for r in recos]

        # expedition_express (valeur nette ~1050 €) domine largement les scores
        # ordinaux ; il classe premier.
        assert ids[0] == "expedition_express"
        # replanifier_jalon est incompatible avec expedition_express mieux classé.
        assert "replanifier_jalon" not in ids
        # ne_rien_faire reste comme référence, jamais écarté.
        assert "ne_rien_faire" in ids

    def test_valeur_nette_chiffree_a_la_main(self, service: Any) -> None:
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = _by_id(engine.recommander("p", "n1", forecast_jouet(), contexte_jouet()))
        exp = recos["expedition_express"]
        # delta 0.30 ; pénalité (5000, 15000) ; coût (1000, 2000) ; décote 0.15.
        # évité = (1500, 4500) ; net = (0.85·1500−2000, 0.85·4500−1000) = (−725, 2825).
        lo, hi = exp.valeur["nette"]
        assert lo == pytest.approx(-725.0)
        assert hi == pytest.approx(2825.0)
        assert exp.delta_u["source"] == "sim"
        assert exp.delta_u["couverture_ic"] == ["mc", "param"]
        # IC : union de mc(0.25,0.35) et param(0.20,0.40) = (0.20, 0.40).
        assert exp.delta_u["lo80"] == pytest.approx(0.20)
        assert exp.delta_u["hi80"] == pytest.approx(0.40)
        assert exp.p0 == pytest.approx(0.5)
        assert exp.p1 == {"est": pytest.approx(0.2), "source": "sim"}
        assert exp.niveau_de_preuve["n_sim"] == 2000
        assert exp.incertitude_modele == "non quantifiée (simulateur)"

    def test_heuristique_vs_nette(self, service: Any) -> None:
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = _by_id(engine.recommander("p", "n1", forecast_jouet(), contexte_jouet()))
        # montants des deux côtés -> nette.
        assert "nette" in recos["expedition_express"].valeur
        # aucun montant -> heuristique.
        assert "heuristique" in recos["promouvoir_arc_secours"].valeur
        # montant d'un seul côté (coût sans pénalité) -> heuristique, jamais des euros.
        assert "heuristique" in recos["boost_capacite"].valeur
        assert "nette" not in recos["boost_capacite"].valeur

    def test_precondition_sans_arc_backup_filtre_la_promotion(self, service: Any) -> None:
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = engine.recommander("p", "n1", forecast_jouet(), contexte_jouet(backup=False))
        ids = [r.action_id for r in recos]
        assert "promouvoir_arc_secours" not in ids

    def test_ne_rien_faire_gagne_quand_tous_les_deltas_sont_nuls(self, service: Any) -> None:
        nul = FakePrev(0.5, 0.5, 0.0, FakeIC(0.0, 0.0, ("mc",)), FakeIC(0.0, 0.0, ("param",)), 0.5)
        forecast = FakeForecast("n1", dict.fromkeys(catalogue_jouet(), nul))
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = engine.recommander("p", "n1", forecast, contexte_jouet())
        # Aucune action ne bat l'inaction : ne_rien_faire est en tête.
        assert recos[0].action_id == "ne_rien_faire"

    def test_catalogue_absent_retourne_liste_vide(self, service: Any) -> None:
        engine = ActionEngine(service, catalogue={})
        assert engine.recommander("p", "n1", forecast_jouet(), contexte_jouet()) == []

    def test_contexte_none_construit_via_facade(self, service: Any) -> None:
        # Nœud réel avec urgence dans le graphe ; contexte non fourni.
        node = SupplyNode(id="n1", name="N1", project_id="p", rank=0)
        node.urgency = UrgencyState(ur_local=0.5, hidden_risk=0.3)
        proj = Project(id="p", name="P", owner_node_id="n1", created_at=0.0, t0_ts=0.0)
        service.create_project(proj, [node], [])
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = engine.recommander("p", "n1", forecast_jouet(), None)
        assert recos  # préconditions permissives : au moins une recommandation


# --- Source causale IPW (U17) --------------------------------------------------------


def _effets(
    posteriors_par_action: dict[str, dict[str, float]],
    *,
    delta_causal: dict[str, dict[str, Any] | None] | None = None,
    overlap: dict[str, bool] | None = None,
    n_reel: int = 40,
) -> dict[str, Any]:
    """Construit un action_effects.json minimal pour un unique segment."""
    delta_causal = delta_causal or {}
    overlap = overlap or {}
    actions: dict[str, Any] = {}
    for aid, means in posteriors_par_action.items():
        posteriors = {
            prior: {
                "p_resolution": {"mean": m, "lo80": max(m - 0.1, 0.0), "hi80": min(m + 0.1, 1.0)}
            }
            for prior, m in means.items()
        }
        cellule: dict[str, Any] = {
            "posteriors": posteriors,
            "delta_causal_ipw": delta_causal.get(aid),
            "e_value": 1.8,
            "overlap_ok": overlap.get(aid, False),
        }
        actions[aid] = {
            "p_execution": {"alpha": 19.0, "beta": 1.0, "n": n_reel},
            "segments": {_SEGMENT: cellule},
        }
    return {"schema_version": 2, "actions": actions, "segments": {_SEGMENT: {}}}


class TestSourceCausale:
    def test_delta_causal_prioritaire_sur_sim(self, service: Any) -> None:
        effets = _effets(
            {"expedition_express": {"prior_sim": 0.8, "prior_faible": 0.7, "donnees_seules": 0.75}},
            delta_causal={
                "expedition_express": {"est": 0.25, "lo80": 0.15, "hi80": 0.35, "n_eff": 30}
            },
            overlap={"expedition_express": True},
        )
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        engine._effets = effets  # injection directe (équivaut au chargement fichier)
        recos = _by_id(engine.recommander("p", "n1", forecast_jouet(), contexte_jouet()))
        exp = recos["expedition_express"]
        assert exp.delta_u["source"] == "causal_ipw"
        assert exp.delta_u["couverture_ic"] == ["causal"]
        assert exp.delta_u["est"] == pytest.approx(0.25)
        # p1 = p0(sim) − delta_causal = 0.5 − 0.25.
        assert exp.p1["est"] == pytest.approx(0.25)
        assert exp.p1["source"] == "causal_ipw"
        # p_execution = moyenne Beta 19/(19+1) = 0.95.
        assert exp.p_execution == pytest.approx(0.95)
        assert exp.niveau_de_preuve["qualite"] == "fort"
        assert exp.niveau_de_preuve["n_reel"] == 40

    def test_overlap_insuffisant_ignore_le_causal(self, service: Any) -> None:
        effets = _effets(
            {"expedition_express": {"prior_sim": 0.8, "prior_faible": 0.7, "donnees_seules": 0.75}},
            delta_causal={
                "expedition_express": {"est": 0.25, "lo80": 0.15, "hi80": 0.35, "n_eff": 30}
            },
            overlap={"expedition_express": False},  # recouvrement insuffisant
        )
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        engine._effets = effets
        recos = _by_id(engine.recommander("p", "n1", forecast_jouet(), contexte_jouet()))
        # Retombe sur la source simulateur.
        assert recos["expedition_express"].delta_u["source"] == "sim"


# --- Robustesse aux trois a priori (D27) ---------------------------------------------


class TestRobustesse:
    def test_robuste_quand_les_priors_concordent(self, service: Any) -> None:
        effets = _effets(
            {
                "expedition_express": {
                    "prior_sim": 0.8,
                    "prior_faible": 0.7,
                    "donnees_seules": 0.75,
                },
                "promouvoir_arc_secours": {
                    "prior_sim": 0.5,
                    "prior_faible": 0.4,
                    "donnees_seules": 0.45,
                },
            }
        )
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        engine._effets = effets
        recos = _by_id(engine.recommander("p", "n1", None, contexte_jouet()))
        assert recos["expedition_express"].robuste_aux_priors is True
        assert recos["promouvoir_arc_secours"].robuste_aux_priors is False

    def test_non_robuste_quand_les_priors_divergent(self, service: Any) -> None:
        effets = _effets(
            {
                "expedition_express": {
                    "prior_sim": 0.8,
                    "prior_faible": 0.3,
                    "donnees_seules": 0.6,
                },
                "promouvoir_arc_secours": {
                    "prior_sim": 0.5,
                    "prior_faible": 0.6,
                    "donnees_seules": 0.4,
                },
            }
        )
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        engine._effets = effets
        recos = _by_id(engine.recommander("p", "n1", None, contexte_jouet()))
        # prior_faible désigne promouvoir, les autres expedition -> aucun robuste.
        assert recos["expedition_express"].robuste_aux_priors is False
        assert recos["promouvoir_arc_secours"].robuste_aux_priors is False


# --- Dégradation complète ------------------------------------------------------------


class TestDegradation:
    def test_ni_u9_ni_u17_produit_des_recommandations_saines(self, service: Any) -> None:
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = engine.recommander("p", "n1", None, contexte_jouet())
        assert recos  # jamais vide (catalogue présent)
        for reco in recos:
            assert reco.delta_u["source"] == "absent"
            assert reco.delta_u["est"] is None
            assert "heuristique" in reco.valeur  # jamais de valeur monétaire sans effet
            assert reco.niveau_de_preuve["qualite"] == "faible"
            assert reco.robuste_aux_priors is False
        # p_execution vient du défaut de l'ActionSpec (1 − p_echec).
        exp = _by_id(recos)["expedition_express"]
        assert exp.p_execution == pytest.approx(0.95)
        assert any("Aucune estimation quantitative" in note for note in exp.justification)
        # Sans preuve d'effet, l'inaction reste en tête.
        assert recos[0].action_id == "ne_rien_faire"


# --- Chargement des effets depuis un fichier -----------------------------------------


class TestChargementEffets:
    def test_chargement_json(self, service: Any, tmp_path: Path) -> None:
        effets = _effets(
            {"expedition_express": {"prior_sim": 0.8, "prior_faible": 0.7, "donnees_seules": 0.75}},
            n_reel=12,
        )
        chemin = tmp_path / "action_effects.json"
        chemin.write_text(json.dumps(effets), encoding="utf-8")
        engine = ActionEngine(service, action_effects_path=str(chemin), catalogue=catalogue_jouet())
        recos = _by_id(engine.recommander("p", "n1", None, contexte_jouet()))
        # n_reel = 12 -> qualité « moyen » (>= 8, < 30).
        assert recos["expedition_express"].niveau_de_preuve["qualite"] == "moyen"
        assert recos["expedition_express"].p_resolution_op["est"] == pytest.approx(0.8)

    def test_chemin_absent_degrade(self, service: Any, tmp_path: Path) -> None:
        engine = ActionEngine(service, action_effects_path=str(tmp_path / "absent.json"))
        assert engine._effets is None

    def test_json_non_dict_degrade(self, service: Any, tmp_path: Path) -> None:
        chemin = tmp_path / "liste.json"
        chemin.write_text("[1, 2, 3]", encoding="utf-8")
        engine = ActionEngine(service, action_effects_path=str(chemin))
        assert engine._effets is None


# --- Portefeuille (contrat 13, D30) --------------------------------------------------


def _graphe_deux_noeuds(service: Any, arc: bool) -> None:
    """Projet à deux nœuds n1, n2 ; arc n2->n1 (n2 fournit n1) si demandé."""
    n1 = SupplyNode(id="n1", name="N1", project_id="p", rank=0)
    n2 = SupplyNode(id="n2", name="N2", project_id="p", rank=1)
    arcs = [SupplyArc(source_id="n2", target_id="n1")] if arc else []
    proj = Project(id="p", name="P", owner_node_id="n1", created_at=0.0, t0_ts=0.0)
    service.create_project(proj, [n1, n2], arcs)


class TestPortefeuille:
    def test_budget_serre_exclut_avec_raison(self, service: Any) -> None:
        _graphe_deux_noeuds(service, arc=False)  # nœuds indépendants
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = {
            "n1": [make_reco("expedition_express", {"nette": (900.0, 1100.0)})],  # coût mid 1500
            "n2": [make_reco("boost_capacite", {"heuristique": 800.0})],  # coût mid 1000
        }
        sel = engine.portefeuille("p", recos, budget=1500.0)
        assert isinstance(sel, Selection)
        retenues = {r["action_id"] for r in sel.retenues}
        # ratio boost 0.8 > expedition 0.667 : boost retenu (coût 1000), expedition exclu.
        assert retenues == {"boost_capacite"}
        assert sel.budget_consomme == pytest.approx(1000.0)
        raisons = {(e["action_id"], e["raison"]) for e in sel.exclues}
        assert any(a == "expedition_express" and "budget" in r for a, r in raisons)

    def test_conflit_arc_partage_inter_noeud(self, service: Any) -> None:
        _graphe_deux_noeuds(service, arc=True)  # arc n2->n1 partagé
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = {
            "n1": [make_reco("expedition_express", {"nette": (900.0, 1100.0)})],  # ratio 0.667
            "n2": [make_reco("boost_capacite", {"heuristique": 800.0})],  # ratio 0.8
        }
        sel = engine.portefeuille("p", recos)
        retenues = {r["action_id"] for r in sel.retenues}
        assert retenues == {"boost_capacite"}
        assert any(
            e["action_id"] == "expedition_express" and "arc partagé" in e["raison"]
            for e in sel.exclues
        )

    def test_capacite_par_type_exclut(self, service: Any) -> None:
        _graphe_deux_noeuds(service, arc=False)
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = {
            "n1": [make_reco("boost_capacite", {"heuristique": 900.0})],
            "n2": [make_reco("boost_capacite", {"heuristique": 800.0})],
        }
        sel = engine.portefeuille("p", recos, capacites={"boost_capacite": 1})
        assert len(sel.retenues) == 1
        assert any("capacité" in e["raison"] for e in sel.exclues)

    def test_incompatibilite_intra_noeud_exclut(self, service: Any) -> None:
        _graphe_deux_noeuds(service, arc=False)
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        # Deux actions incompatibles sur le MÊME nœud (contournant le filtre de
        # recommander pour éprouver le garde-fou du portefeuille).
        recos = {
            "n1": [
                make_reco("expedition_express", {"nette": (1400.0, 1600.0)}),  # ratio 1.0
                make_reco("replanifier_jalon", {"heuristique": 5.0}),  # ratio ~2.5 (temps 2)
            ]
        }
        sel = engine.portefeuille("p", recos)
        retenues = {r["action_id"] for r in sel.retenues}
        # replanifier (meilleur ratio) retenu, expedition exclu (incompatible intra-nœud).
        assert "replanifier_jalon" in retenues
        assert any(
            e["action_id"] == "expedition_express" and "incompatible" in e["raison"]
            for e in sel.exclues
        )

    def test_conflit_fournisseur_cible_commun_inter_noeud(self, service: Any) -> None:
        # n1 et n2 partagent le fournisseur n3, deux actions de réappro
        # (promouvoir_arc_secours) : conflit de fournisseur cible commun.
        n1 = SupplyNode(id="n1", name="N1", project_id="p", rank=0)
        n2 = SupplyNode(id="n2", name="N2", project_id="p", rank=0)
        n3 = SupplyNode(id="n3", name="N3", project_id="p", rank=1)
        arcs = [
            SupplyArc(source_id="n3", target_id="n1"),
            SupplyArc(source_id="n3", target_id="n2"),
        ]
        proj = Project(id="p", name="P", owner_node_id="n1", created_at=0.0, t0_ts=0.0)
        service.create_project(proj, [n1, n2, n3], arcs)
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = {
            "n1": [make_reco("promouvoir_arc_secours", {"heuristique": 900.0})],
            "n2": [make_reco("promouvoir_arc_secours", {"heuristique": 800.0})],
        }
        sel = engine.portefeuille("p", recos)
        assert len(sel.retenues) == 1  # une seule des deux réappros sur n3
        assert any("fournisseur cible commun" in e["raison"] for e in sel.exclues)

    def test_avertissement_substitution_fournisseur_commun(self, service: Any) -> None:
        # n1 et n2 partagent le fournisseur n3 (n3->n1, n3->n2), pas d'arc commun.
        n1 = SupplyNode(id="n1", name="N1", project_id="p", rank=0)
        n2 = SupplyNode(id="n2", name="N2", project_id="p", rank=0)
        n3 = SupplyNode(id="n3", name="N3", project_id="p", rank=1)
        arcs = [
            SupplyArc(source_id="n3", target_id="n1"),
            SupplyArc(source_id="n3", target_id="n2"),
        ]
        proj = Project(id="p", name="P", owner_node_id="n1", created_at=0.0, t0_ts=0.0)
        service.create_project(proj, [n1, n2, n3], arcs)
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = {
            "n1": [make_reco("boost_capacite", {"heuristique": 900.0})],
            "n2": [make_reco("boost_capacite", {"heuristique": 800.0})],
        }
        sel = engine.portefeuille("p", recos)
        assert len(sel.retenues) == 2  # actions non ciblant-fournisseur : coexistent
        assert any("substitution" in a and "n3" in a for a in sel.avertissements)

    def test_action_n_ameliorant_pas_l_inaction_exclue(self, service: Any) -> None:
        _graphe_deux_noeuds(service, arc=False)
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = {
            "n1": [
                make_reco("ne_rien_faire", {"heuristique": 0.0}),
                make_reco("boost_capacite", {"heuristique": -0.5}),  # sous l'inaction
            ]
        }
        sel = engine.portefeuille("p", recos)
        assert sel.retenues == []
        assert any("n'améliore pas l'inaction" in e["raison"] for e in sel.exclues)

    def test_budget_non_applicable_sans_catalogue(self, service: Any) -> None:
        engine = ActionEngine(service, catalogue={})  # aucun coût connu
        recos = {"n1": [make_reco("boost_capacite", {"heuristique": 5.0})]}
        sel = engine.portefeuille("p", recos, budget=100.0)
        assert any("Budget non appliqué" in a for a in sel.avertissements)
        assert {r["action_id"] for r in sel.retenues} == {"boost_capacite"}


# --- Aides pures et dégradation fine -------------------------------------------------


class TestAidesPures:
    def test_valeur_scalaire_repli_zero(self) -> None:
        assert _valeur_scalaire({}) == 0.0

    def test_union_ic_repli_sans_intervalle_valide(self) -> None:
        # Aucun intervalle exploitable (bornes absentes) -> repli (est, est).
        assert _union_ic((None, None), 0.42) == (0.42, 0.42)

    def test_urgence_absente_segment_indetermine(self, service: Any) -> None:
        # Contexte sans urgence : segment indéterminable, mais recommandations
        # produites sans planter (effet absent, valeur heuristique).
        ctx = FakeContexte(node=FakeNode(id="n1", rank=0), urgency=None)
        engine = ActionEngine(service, catalogue=catalogue_jouet())
        recos = engine.recommander("p", "n1", None, ctx)
        assert recos
        assert all(r.niveau_de_preuve["source_prior"] is None for r in recos)
