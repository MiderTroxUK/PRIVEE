"""Tests d'InsightService et de son CLI (U12) — LE contrat de fin HÉLIOS v7.

Couvre : les trois branches de sévérité (:data:`SEUILS_V1`), le bloc
prescriptif complet (contrat de fin : p0/p1, effet estimé + source nommée
explicitement selon ``delta_u.source``, P(Δ>0), P(résolution opérationnelle |
exécution), P(exécution), P(éviter la rupture) — produit affiché —, valeur
nette OU heuristique — jamais confondues —, délai d'effet, niveau de preuve
— formulation exacte imposée pour ``prior_sim`` —, robustesse aux trois a
priori, incertitude de modèle) et la complétude de ``sources``, le catalogue
dégradé (5 règles, ordre figé, petit graphe avec/sans arc de secours), le
tri (sévérité puis P(≤4) décroissant), l'annotation d'amélioration à 1 et 2
semaines, la discipline duck-typing (objet unique ou séquence, mapping ou
dataclass, aucun import des modules frères U11/U18), et le CLI (mode
dégradé sans artefact, JSON, prévision réussie/en échec, erreurs).

Points de prévision (contrat 6) et recommandations (contrat 11) sont
reproduits ICI par de simples classes locales — jamais importés depuis
``supplyscore.services.prediction``/``supplyscore.services.action_engine``,
volontairement absents de ce worktree : la preuve que le duck-typing
fonctionne réellement sans ces modules.
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import ArcKind, Project, SupplyArc, SupplyNode, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.services.insights import HORIZON_REFERENCE, InsightService
from supplyscore.tools import insights as cli_insights

#: Mercredi 2026-06-10 12:00 locale — instant figé des tests.
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

PROJECT_ID = "proj-insights"


# --- Fixtures : petit graphe C -> B -> A + fournisseur de secours C2 -----------------------


@pytest.fixture
def service(tmp_path: Path) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    yield svc
    svc.close()


def _construire_chaine(svc: SupplyScoreService, project_id: str = PROJECT_ID) -> None:
    """Construit C -> B -> A (client final) + C2, fournisseur de secours de B (backup C2->B).

    A et C n'ont PAS d'arc de secours (utile pour les règles dégradées 2/4/5).
    H/F par défaut = 0.1 (sous tous les seuils dégradés à 0.3).
    """
    ranks = {"A": 0, "B": 1, "C": 2, "C2": 2}
    nodes = [
        SupplyNode(
            id=node_id,
            name=f"Nœud {node_id}",
            rank=ranks[node_id],
            project_id=project_id,
            urgency=UrgencyState(ud_local=0.2, ur_local=0.3, hidden_risk=0.1, false_urgency=0.1),
        )
        for node_id in ranks
    ]
    arcs = [
        SupplyArc(source_id="C", target_id="B"),
        SupplyArc(source_id="B", target_id="A"),
        SupplyArc(source_id="C2", target_id="B", kind_arc=ArcKind.BACKUP),
    ]
    project = Project(id=project_id, name="Chaîne de test", owner_node_id="A", t0_ts=_NOW)
    svc.create_project(project, nodes, arcs)


@pytest.fixture
def chaine(service: SupplyScoreService) -> SupplyScoreService:
    _construire_chaine(service)
    return service


def _set_urgency(svc: SupplyScoreService, node_id: str, **kwargs: float | None) -> None:
    node = svc.repo.get_node(node_id)
    assert node is not None
    for key, value in kwargs.items():
        setattr(node.urgency, key, value)
    svc.repo.update_node(node)


# --- Points et recommandations duck-typés (contrats 6 & 11, JAMAIS importés) ----------------


@dataclass
class FakePoint:
    """Point minimal — expose UNIQUEMENT les champs qu'InsightService lit réellement."""

    node_id: str
    node_name: str
    proba_by_horizon: dict[int, float] = field(default_factory=dict)
    delta_vs_last_week: float | None = None
    p_jalon_rate: float | None = None
    impact_frac: float | None = None
    recommandation: object | None = None


@dataclass(frozen=True)
class FakeRecommandation:
    """Reproduit structurellement ``ActionRecommandation`` (contrat 11, U18)."""

    action_id: str = "promouvoir_arc_secours"
    libelle: str = "Promouvoir un arc de secours en arc nominal"
    p0: float | None = 0.32
    p1: dict[str, Any] = field(default_factory=lambda: {"est": 0.18, "source": "sim"})
    delta_u: dict[str, Any] = field(
        default_factory=lambda: {
            "est": 0.14,
            "lo80": 0.05,
            "hi80": 0.22,
            "source": "sim",
            "couverture_ic": ["mc", "param"],
        }
    )
    p_delta_positif: float | None = 0.82
    p_resolution_op: dict[str, float | None] = field(
        default_factory=lambda: {"est": 0.70, "lo80": 0.60, "hi80": 0.80}
    )
    p_execution: float = 0.90
    p_eviter: float | None = 0.63
    valeur: dict[str, Any] = field(default_factory=lambda: {"nette": (1200.0, 4500.0)})
    delai_effet_weeks: Any = (0.5, 1.0, 2.0)
    niveau_de_preuve: dict[str, Any] = field(
        default_factory=lambda: {
            "n_reel": 12,
            "n_sim": 500,
            "source_prior": "prior_sim",
            "qualite": "moyen",
        }
    )
    robuste_aux_priors: bool = True
    justification: list[str] = field(default_factory=list)
    incertitude_modele: str = "non quantifiée (simulateur)"


REC_COMPLETE = FakeRecommandation()


# --- Discipline duck-typing : aucun import des modules frères ------------------------------


def test_ne_importe_pas_les_modules_freres() -> None:
    """Aucun ``import``/``from ... import`` réel ne cible U11/U18 (mentions en docstring OK)."""
    import ast

    import supplyscore.services.insights as module_insights

    source = Path(module_insights.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    modules_importes: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            modules_importes.update(alias.name for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            modules_importes.add(noeud.module)

    interdits = {"supplyscore.services.prediction", "supplyscore.services.action_engine"}
    assert not (modules_importes & interdits)


# --- Sévérité (SEUILS_V1) -------------------------------------------------------------------


def test_severite_alerte(chaine: SupplyScoreService) -> None:
    point = FakePoint(
        node_id="A",
        node_name="Nœud A",
        proba_by_horizon={HORIZON_REFERENCE: 0.30},
        impact_frac=0.40,
    )
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.severite == "alerte"
    assert "30.0 %" in insight.message
    assert "40.0 %" in insight.message
    assert insight.sources["p_le4"] == pytest.approx(0.30)
    assert insight.sources["impact_frac"] == pytest.approx(0.40)
    assert len(insight.pourquoi) == 2


def test_severite_alerte_necessite_les_deux_conditions(chaine: SupplyScoreService) -> None:
    # P(≤4) élevé mais impact_frac sous le seuil -> attention, pas alerte.
    point = FakePoint(
        node_id="A",
        node_name="Nœud A",
        proba_by_horizon={HORIZON_REFERENCE: 0.30},
        impact_frac=0.10,
    )
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.severite == "attention"


def test_severite_attention_via_p_le4(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="B", node_name="Nœud B", proba_by_horizon={HORIZON_REFERENCE: 0.20})
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.severite == "attention"
    assert len(insight.pourquoi) == 1


def test_severite_attention_via_delta(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="B", node_name="Nœud B", delta_vs_last_week=0.10)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.severite == "attention"
    assert len(insight.pourquoi) == 1
    assert "points de pourcentage" in insight.pourquoi[0]


def test_severite_attention_deux_raisons_simultanees(chaine: SupplyScoreService) -> None:
    point = FakePoint(
        node_id="B",
        node_name="Nœud B",
        proba_by_horizon={HORIZON_REFERENCE: 0.20},
        delta_vs_last_week=0.10,
    )
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.severite == "attention"
    assert len(insight.pourquoi) == 2


def test_severite_info_p_le4_sous_les_seuils(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="C", node_name="Nœud C", proba_by_horizon={HORIZON_REFERENCE: 0.05})
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.severite == "info"
    assert "5.0 %" in insight.message


def test_severite_info_p_le4_indisponible(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="C", node_name="Nœud C")
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.severite == "info"
    assert "non disponible" in insight.message
    assert insight.sources["p_le4"] is None


# --- Bloc prescriptif complet (contrat de fin) ----------------------------------------------


def test_bloc_prescriptif_complet_tous_les_nombres(chaine: SupplyScoreService) -> None:
    point = FakePoint(
        node_id="A",
        node_name="Nœud A",
        proba_by_horizon={HORIZON_REFERENCE: 0.10},  # info : isole le bloc prescriptif
        recommandation=REC_COMPLETE,
    )
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    msg = insight.message

    assert "risque sans action : 32.0 %" in msg
    assert "risque avec action : 18.0 %" in msg
    assert insight.sources["reco_p0"] == pytest.approx(0.32)
    assert insight.sources["reco_p1"] == pytest.approx(0.18)

    assert "effet estimé : +14.0 points de pourcentage (source : simulation appariée)" in msg
    assert insight.sources["reco_delta_u_est"] == pytest.approx(0.14)
    assert insight.sources["reco_delta_u_lo80"] == pytest.approx(0.05)
    assert insight.sources["reco_delta_u_hi80"] == pytest.approx(0.22)

    assert "P(Δ>0) = 82.0 %" in msg
    assert insight.sources["reco_p_delta_positif"] == pytest.approx(0.82)

    assert "P(résolution opérationnelle | exécution) = 70.0 % [IC80 : 60.0–80.0 %]" in msg
    assert insight.sources["reco_p_resolution_op_est"] == pytest.approx(0.70)
    assert insight.sources["reco_p_resolution_op_lo80"] == pytest.approx(0.60)
    assert insight.sources["reco_p_resolution_op_hi80"] == pytest.approx(0.80)

    assert "P(exécution) = 90.0 %" in msg
    assert insight.sources["reco_p_execution"] == pytest.approx(0.90)

    assert "P(éviter la rupture) = 63.0 % (= P(exécution) × P(résolution) = 90.0 % × 70.0 %)" in msg
    assert insight.sources["reco_p_eviter"] == pytest.approx(0.63)

    assert "valeur nette estimée : 1200 € à 4500 €" in msg
    assert insight.sources["reco_valeur_nette_lo"] == pytest.approx(1200.0)
    assert insight.sources["reco_valeur_nette_hi"] == pytest.approx(4500.0)

    assert "délai d'effet estimé : 0.5 à 2 semaine(s) (le plus probable : 1)" in msg
    assert insight.sources["reco_delai_min"] == pytest.approx(0.5)
    assert insight.sources["reco_delai_mode"] == pytest.approx(1.0)
    assert insight.sources["reco_delai_max"] == pytest.approx(2.0)

    assert "niveau de preuve : a priori simulé + 12 observations réelles" in msg
    assert insight.sources["reco_niveau_preuve_n_reel"] == pytest.approx(12.0)
    assert insight.sources["reco_niveau_preuve_n_sim"] == pytest.approx(500.0)

    assert "recommandation ROBUSTE aux trois choix de prior" in msg
    assert "incertitude de modèle : non quantifiée (simulateur)" in msg
    assert insight.action == REC_COMPLETE.libelle


def test_sources_completude_bloc_prescriptif(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=REC_COMPLETE)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    attendues = {
        "reco_p0",
        "reco_p1",
        "reco_delta_u_est",
        "reco_delta_u_lo80",
        "reco_delta_u_hi80",
        "reco_p_delta_positif",
        "reco_p_resolution_op_est",
        "reco_p_resolution_op_lo80",
        "reco_p_resolution_op_hi80",
        "reco_p_execution",
        "reco_p_eviter",
        "reco_valeur_nette_lo",
        "reco_valeur_nette_hi",
        "reco_delai_min",
        "reco_delai_mode",
        "reco_delai_max",
        "reco_niveau_preuve_n_reel",
        "reco_niveau_preuve_n_sim",
    }
    assert attendues <= insight.sources.keys()
    for cle in attendues:
        assert insight.sources[cle] is not None, f"{cle} ne devrait pas être None"


# --- « nette » vs « heuristique » : jamais confondues ---------------------------------------


def test_valeur_nette_quand_montants_disponibles(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=REC_COMPLETE)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "valeur nette estimée" in insight.message
    assert "classement heuristique" not in insight.message


def test_valeur_heuristique_jamais_appelee_valeur_nette(chaine: SupplyScoreService) -> None:
    rec = replace(REC_COMPLETE, valeur={"heuristique": 0.037})
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert (
        "classement heuristique : 0.037 (score ordinal — jamais une valeur monétaire)"
        in insight.message
    )
    assert "valeur nette estimée" not in insight.message
    assert insight.sources["reco_valeur_heuristique"] == pytest.approx(0.037)
    assert "reco_valeur_nette_lo" not in insight.sources


# --- Source nommée explicitement selon delta_u.source ---------------------------------------


def test_effet_source_sim(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=REC_COMPLETE)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "(source : simulation appariée)" in insight.message


def test_effet_source_causal_ipw(chaine: SupplyScoreService) -> None:
    rec = replace(
        REC_COMPLETE,
        delta_u={
            "est": 0.09,
            "lo80": 0.02,
            "hi80": 0.16,
            "source": "causal_ipw",
            "couverture_ic": ["causal"],
        },
    )
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert (
        "effet estimé : +9.0 points de pourcentage (corrigée IPW sur 12 observations réelles)"
        in insight.message
    )


def test_effet_absent(chaine: SupplyScoreService) -> None:
    rec = replace(
        REC_COMPLETE,
        delta_u={"est": None, "lo80": None, "hi80": None, "source": "absent", "couverture_ic": []},
    )
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "effet non chiffré" in insight.message
    assert insight.sources["reco_delta_u_est"] is None


# --- Robustesse aux trois a priori -----------------------------------------------------------


def test_robustesse_vraie(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=REC_COMPLETE)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "recommandation ROBUSTE aux trois choix de prior" in insight.message


def test_robustesse_fausse(chaine: SupplyScoreService) -> None:
    rec = replace(REC_COMPLETE, robuste_aux_priors=False)
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "recommandation NON robuste aux trois choix de prior" in insight.message
    assert "recommandation ROBUSTE aux trois choix de prior" not in insight.message


def test_niveau_preuve_donnees_seules(chaine: SupplyScoreService) -> None:
    rec = replace(
        REC_COMPLETE,
        niveau_de_preuve={
            "n_reel": 40,
            "n_sim": 0,
            "source_prior": "donnees_seules",
            "qualite": "fort",
        },
    )
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "données seules + 40 observations réelles" in insight.message


def test_bloc_prescriptif_delai_malforme_rend_non_disponible(chaine: SupplyScoreService) -> None:
    rec = replace(REC_COMPLETE, delai_effet_weeks="invalide")
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "délai d'effet estimé : non disponible" in insight.message
    assert insight.sources["reco_delai_min"] is None


def test_bloc_prescriptif_libelle_replie_sur_action_id(chaine: SupplyScoreService) -> None:
    rec = replace(REC_COMPLETE, libelle="")
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert f"Action recommandée : {REC_COMPLETE.action_id}" in insight.message
    assert insight.action == REC_COMPLETE.action_id


def test_p_eviter_absent_quand_resolution_inconnue(chaine: SupplyScoreService) -> None:
    rec = replace(
        REC_COMPLETE, p_resolution_op={"est": None, "lo80": None, "hi80": None}, p_eviter=None
    )
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "P(éviter la rupture) = n/d" in insight.message
    assert insight.sources["reco_p_eviter"] is None


# --- Recommandation : objet unique, séquence, mapping ----------------------------------------


def test_recommandation_liste_prend_le_premier(chaine: SupplyScoreService) -> None:
    autre = replace(REC_COMPLETE, action_id="ne_rien_faire", libelle="Ne rien faire")
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=[REC_COMPLETE, autre])
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action == REC_COMPLETE.libelle


def test_recommandation_liste_vide_bascule_en_degrade(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=[])
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "Action recommandée" not in insight.message


def test_recommandation_mapping_duck_type(chaine: SupplyScoreService) -> None:
    rec_dict = {
        "action_id": "x",
        "libelle": "Action X",
        "p0": 0.5,
        "p1": {"est": 0.4, "source": "sim"},
        "delta_u": {"est": 0.1, "lo80": 0.1, "hi80": 0.1, "source": "sim"},
        "p_delta_positif": 0.6,
        "p_resolution_op": {"est": 0.5, "lo80": 0.4, "hi80": 0.6},
        "p_execution": 0.8,
        "p_eviter": 0.4,
        "valeur": {"heuristique": 0.2},
        "delai_effet_weeks": (0.0, 1.0, 2.0),
        "niveau_de_preuve": {"n_reel": 0, "n_sim": 10, "source_prior": None, "qualite": "faible"},
        "robuste_aux_priors": False,
        "incertitude_modele": "non quantifiée (simulateur)",
    }
    point = FakePoint(node_id="A", node_name="Nœud A", recommandation=rec_dict)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "Action recommandée : Action X" in insight.message
    assert insight.action == "Action X"


def test_duck_typing_champs_optionnels_totalement_absents(chaine: SupplyScoreService) -> None:
    """Point et recommandation minimalistes (attributs optionnels manquants) : jamais un crash.

    Couvre les replis internes (:func:`_champ` sur un sous-objet absent,
    :func:`_pp`/:func:`_p_le4` sur une valeur/un mapping manquant) qu'aucun
    autre test — construit sur des dataclasses complètes — n'atteint.
    """

    class RecommandationNue:
        action_id = "x"
        libelle = "Action nue"
        p0 = None
        p1 = None  # sous-mapping absent -> _champ(None, "est")
        delta_u: ClassVar[dict[str, Any]] = {"est": None, "source": "sim"}  # -> _pp(None)=="n/d"
        p_delta_positif = None
        p_resolution_op = None
        p_execution = 0.5
        p_eviter = None
        valeur: ClassVar[dict[str, Any]] = {"heuristique": 0.0}
        delai_effet_weeks = (0.0, 0.0, 0.0)
        niveau_de_preuve = None  # -> _texte_niveau_preuve(None)
        robuste_aux_priors = False
        incertitude_modele = "non quantifiée (simulateur)"

    class PointNu:
        node_id = "A"
        node_name = "Nœud A"
        # proba_by_horizon absent (pas même un dict vide) -> _p_le4 replie sur None.
        recommandation = RecommandationNue()

    insight = InsightService(chaine).insights(PROJECT_ID, [PointNu()])[0]
    assert insight.sources["p_le4"] is None
    assert "effet estimé : n/d (source : simulation appariée)" in insight.message
    assert "niveau de preuve : 0 observations réelles (a priori indisponible)" in insight.message


# --- Catalogue dégradé (recommandation absente) — ordre figé, petit graphe -----------------


def test_action_degradee_arc_de_secours(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="B", node_name="Nœud B")
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action == (
        "promouvoir l'arc de secours vers Nœud C2 (secours qualifié pour Nœud B)"
    )


def test_action_degradee_priorite_arc_de_secours_sur_hidden_risk(
    chaine: SupplyScoreService,
) -> None:
    _set_urgency(chaine, "B", hidden_risk=0.9)
    point = FakePoint(node_id="B", node_name="Nœud B")
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action is not None
    assert insight.action.startswith("promouvoir l'arc de secours")


def test_action_degradee_arc_de_secours_departage_source_id(service: SupplyScoreService) -> None:
    project_id = "proj-departage"
    nodes = [
        SupplyNode(id="X", name="Nœud X", rank=1, project_id=project_id, urgency=UrgencyState()),
        SupplyNode(id="Y1", name="Nœud Y1", rank=2, project_id=project_id, urgency=UrgencyState()),
        SupplyNode(id="Y2", name="Nœud Y2", rank=2, project_id=project_id, urgency=UrgencyState()),
    ]
    arcs = [
        SupplyArc(source_id="Y2", target_id="X", kind_arc=ArcKind.BACKUP),
        SupplyArc(source_id="Y1", target_id="X", kind_arc=ArcKind.BACKUP),
    ]
    project = Project(id=project_id, name="Départage", owner_node_id="X", t0_ts=_NOW)
    service.create_project(project, nodes, arcs)

    point = FakePoint(node_id="X", node_name="Nœud X")
    insight = InsightService(service).insights(project_id, [point])[0]
    assert (
        insight.action == "promouvoir l'arc de secours vers Nœud Y1 (secours qualifié pour Nœud X)"
    )


def test_action_degradee_revue_declaration_sans_arc_de_secours(chaine: SupplyScoreService) -> None:
    _set_urgency(chaine, "A", hidden_risk=0.5)
    point = FakePoint(node_id="A", node_name="Nœud A")
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action == "demander une revue de déclaration (risque caché H élevé)"


def test_action_degradee_revoir_jalon(chaine: SupplyScoreService) -> None:
    point = FakePoint(
        node_id="A",
        node_name="Nœud A",
        proba_by_horizon={HORIZON_REFERENCE: 0.10},
        p_jalon_rate=0.60,
    )
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action == "revoir le jalon actif (probabilité de jalon raté dominante)"


def test_action_degradee_fournisseur_alternatif(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", proba_by_horizon={HORIZON_REFERENCE: 0.30})
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action == "qualifier un fournisseur alternatif (aucun arc de secours disponible)"


def test_action_degradee_desescalade(chaine: SupplyScoreService) -> None:
    _set_urgency(chaine, "A", false_urgency=0.5)
    point = FakePoint(node_id="A", node_name="Nœud A")
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action == "désescalade possible (fausse urgence)"


def test_action_degradee_aucune_regle(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A")
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert insight.action is None


# --- Tri : sévérité puis P(≤4) décroissant ---------------------------------------------------


def test_tri_severite_puis_p_le4(chaine: SupplyScoreService) -> None:
    points = [
        FakePoint(node_id="A", node_name="Info sans P"),
        FakePoint(
            node_id="B",
            node_name="Alerte",
            proba_by_horizon={HORIZON_REFERENCE: 0.5},
            impact_frac=0.5,
        ),
        FakePoint(
            node_id="C", node_name="Attention haute", proba_by_horizon={HORIZON_REFERENCE: 0.20}
        ),
        FakePoint(
            node_id="C2", node_name="Attention basse", proba_by_horizon={HORIZON_REFERENCE: 0.16}
        ),
    ]
    insights = InsightService(chaine).insights(PROJECT_ID, points)
    assert [i.severite for i in insights] == ["alerte", "attention", "attention", "info"]
    assert [i.node_id for i in insights] == ["B", "C", "C2", "A"]


# --- Annotation « en voie de résolution » -----------------------------------------------------


def test_amelioration_une_semaine(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", delta_vs_last_week=-0.06)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert (
        "en voie de résolution : l'urgence locale a reculé de -6.0 points de pourcentage"
        in insight.message
    )
    assert insight.sources["amelioration_delta_semaine"] == pytest.approx(-0.06)


def test_amelioration_sous_le_seuil_ne_declenche_rien(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", delta_vs_last_week=-0.03)
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    assert "en voie de résolution" not in insight.message
    assert "amelioration_delta_semaine" not in insight.sources


def test_amelioration_deux_semaines_consecutives(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", delta_vs_last_week=-0.06)
    precedent = FakePoint(node_id="A", node_name="Nœud A", delta_vs_last_week=-0.02)
    insight = InsightService(chaine).insights(PROJECT_ID, [point], previous=[precedent])[0]
    assert "en voie de résolution depuis deux semaines consécutives" in insight.message
    assert (
        "recul de -6.0 points de pourcentage cette semaine,"
        " -2.0 points de pourcentage la semaine précédente" in insight.message
    )
    assert insight.sources["amelioration_delta_semaine_precedente"] == pytest.approx(-0.02)


def test_amelioration_precedent_sans_correspondance(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A", delta_vs_last_week=-0.06)
    precedent = FakePoint(node_id="AUTRE", node_name="Autre nœud", delta_vs_last_week=-0.10)
    insight = InsightService(chaine).insights(PROJECT_ID, [point], previous=[precedent])[0]
    assert "en voie de résolution :" in insight.message
    assert "deux semaines consécutives" not in insight.message


def test_amelioration_precedent_ne_confirme_pas(chaine: SupplyScoreService) -> None:
    # La semaine précédente n'était PAS en recul (delta positif) : signal 1 semaine seulement.
    point = FakePoint(node_id="A", node_name="Nœud A", delta_vs_last_week=-0.06)
    precedent = FakePoint(node_id="A", node_name="Nœud A", delta_vs_last_week=0.03)
    insight = InsightService(chaine).insights(PROJECT_ID, [point], previous=[precedent])[0]
    assert "deux semaines consécutives" not in insight.message


# --- Erreurs et cas limites --------------------------------------------------------------------


def test_projet_inconnu_leve_valueerror(chaine: SupplyScoreService) -> None:
    with pytest.raises(ValueError, match="inconnu"):
        InsightService(chaine).insights("fantome", [])


def test_points_vides_retourne_liste_vide(chaine: SupplyScoreService) -> None:
    assert InsightService(chaine).insights(PROJECT_ID, []) == []


def test_insight_est_gele(chaine: SupplyScoreService) -> None:
    point = FakePoint(node_id="A", node_name="Nœud A")
    insight = InsightService(chaine).insights(PROJECT_ID, [point])[0]
    with pytest.raises(AttributeError):
        insight.severite = "alerte"  # type: ignore[misc]


# --- CLI (supplyscore.tools.insights) ---------------------------------------------------------


@pytest.fixture
def db_dir_chaine(tmp_path: Path) -> Path:
    """Persiste la fixture de chaîne sur disque pour un run du CLI (processus séparé)."""
    db_dir = tmp_path / "store_cli"
    svc = SupplyScoreService(db_dir=db_dir, clock=FixedClock(_NOW))
    try:
        _construire_chaine(svc)
    finally:
        svc.close()
    return db_dir


def test_cli_mode_degrade_sans_artefact(
    db_dir_chaine: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli_insights.main(
        [
            "--db-dir",
            str(db_dir_chaine),
            "--project",
            PROJECT_ID,
            "--model",
            "chemin/inexistant.json",
        ]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    assert "Nœud" in sortie
    assert "Avertissement" in sortie
    # Mode dégradé sans artefact : selon que U11 (PredictionService) soit présent
    # ou non, le CLI passe par la branche « consulter l'unité U11 » ou « artefact
    # introuvable » — les deux portent le même marqueur « Mode dégradé ».
    assert "Mode dégradé" in sortie


def test_cli_json(db_dir_chaine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_insights.main(
        ["--db-dir", str(db_dir_chaine), "--project", PROJECT_ID, "--model", "x.json", "--json"]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    donnees = json.loads(sortie)
    assert isinstance(donnees, list)
    assert donnees
    assert {"severite", "node_id", "message", "sources"} <= donnees[0].keys()


def test_cli_projet_inconnu(db_dir_chaine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_insights.main(["--db-dir", str(db_dir_chaine), "--project", "fantome"])
    assert code == 1
    assert "Erreur" in capsys.readouterr().err


def test_cli_module_present_mais_artefact_introuvable(
    db_dir_chaine: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Le module de prévision EST importable (contrairement au reste de ce worktree),
    # mais le fichier d'artefact pointé par --model n'existe pas : bascule dégradée
    # AVANT toute tentative de construction de PredictionService.
    faux_module = types.ModuleType("supplyscore.services.prediction")
    monkeypatch.setitem(sys.modules, "supplyscore.services.prediction", faux_module)

    code = cli_insights.main(
        [
            "--db-dir",
            str(db_dir_chaine),
            "--project",
            PROJECT_ID,
            "--model",
            str(tmp_path / "absent.json"),
        ]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    assert "Artefact de modèle introuvable" in sortie


def test_cli_prevision_reussie_utilise_predictionservice(
    db_dir_chaine: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FausseServicePrevision:
        avertissements: ClassVar[list[str]] = ["nœud X exclu (test)"]

        def __init__(self, service: Any, model_path: Any) -> None:
            del service, model_path

        def predict(self, project_id: str) -> list[FakePoint]:
            del project_id
            return [
                FakePoint(
                    node_id="A",
                    node_name="Nœud A",
                    proba_by_horizon={HORIZON_REFERENCE: 0.5},
                    impact_frac=0.5,
                )
            ]

    faux_module = types.ModuleType("supplyscore.services.prediction")
    faux_module.PredictionService = FausseServicePrevision  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "supplyscore.services.prediction", faux_module)

    artefact = tmp_path / "artifact.json"
    artefact.write_text("{}", encoding="utf-8")

    code = cli_insights.main(
        ["--db-dir", str(db_dir_chaine), "--project", PROJECT_ID, "--model", str(artefact)]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    assert "ALERTE" in sortie
    assert "Prévision : nœud X exclu (test)" in sortie


def test_cli_prevision_echoue_bascule_en_degrade(
    db_dir_chaine: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FausseServicePrevisionEnEchec:
        def __init__(self, service: Any, model_path: Any) -> None:
            del service, model_path
            raise ValueError("artefact invalide (test)")

    faux_module = types.ModuleType("supplyscore.services.prediction")
    faux_module.PredictionService = FausseServicePrevisionEnEchec  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "supplyscore.services.prediction", faux_module)

    artefact = tmp_path / "artifact.json"
    artefact.write_text("{}", encoding="utf-8")

    code = cli_insights.main(
        ["--db-dir", str(db_dir_chaine), "--project", PROJECT_ID, "--model", str(artefact)]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    assert "Avertissement : Prévision indisponible" in sortie


def test_cli_sans_points_eligibles(
    service: SupplyScoreService, capsys: pytest.CaptureFixture[str]
) -> None:
    project = Project(id="proj-vide", name="Projet vide", owner_node_id="Z", t0_ts=_NOW)
    node = SupplyNode(
        id="Z", name="Nœud Z", rank=0, project_id="proj-vide", onboarding_state="draft"
    )
    service.create_project(project, [node], [])
    service.close()

    db_dir = Path(service.db_dir)
    code = cli_insights.main(["--db-dir", str(db_dir), "--project", "proj-vide"])
    assert code == 0
    assert "Aucun insight produit" in capsys.readouterr().out


def test_build_parser_defaults() -> None:
    args = cli_insights.build_parser().parse_args(["--project", "p"])
    assert args.db_dir == "data_store"
    assert args.model == cli_insights._DEFAULT_MODEL
    assert args.json is False
