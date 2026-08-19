"""Tests de l'unité U9 : ForecastService — rollouts MC + contrefactuels appariés CRN.

Couvre : les vérifications analytiques (série constante sans jalon → p_issue
quasi nul et conforme au posterior Beta, jalon dépassé → p_jalon_rate = 1,
hazard Bernoulli pur → p_issue = 1 − E[(1 − q)^h] exact via les moments Beta),
l'appariement CRN (action nulle → delta_u_sim == 0 EXACTEMENT, branche sans
action bit à bit identique à rollout(), action neutralisante → delta == p0,
sémantique du délai d'effet), la décomposition de variance (mc/param, IC80
étiqueté), l'erreur française sous 4 semaines d'historique, le déterminisme à
graine égale, le bloc snapshot (contrat 7) et la performance (S = 2000, h = 4,
chaîne de 20 nœuds, < 60 s).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import numpy as np
import pytest

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import Project, SupplyArc, SupplyNode, TaskStatus, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.services.forecast import (
    K_EXTERNES,
    MIN_HISTORY_WEEKS,
    SIGMA_MIN,
    TAUX_PRIOR,
    ForecastService,
    to_snapshot_block,
)

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0
_T0 = _NOW - 10 * _WEEK  # origine du projet : 10 semaines avant « maintenant »


# --- Fixtures et aides ----------------------------------------------------------------


@pytest.fixture
def service(tmp_path: Any) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    yield svc
    svc.close()


def _creer_projet(
    service: SupplyScoreService, n_noeuds: int, beta: float = 0.8
) -> tuple[Project, list[str]]:
    """Chaîne n-00 (client final, rang 0) <- n-01 <- ... <- n-XX (fournisseur)."""
    ids = [f"n-{i:02d}" for i in range(n_noeuds)]
    nodes = [
        SupplyNode(id=nid, name=f"Noeud {i}", rank=i, project_id="p-prev")
        for i, nid in enumerate(ids)
    ]
    arcs = [
        SupplyArc(source_id=ids[i + 1], target_id=ids[i], beta=beta) for i in range(n_noeuds - 1)
    ]
    project = Project(
        id="p-prev", name="Prévision", owner_node_id=ids[0], created_at=_T0, t0_ts=_T0
    )
    service.create_project(project, nodes, arcs)
    return project, ids


def _historique(service: SupplyScoreService, node_id: str, valeurs: list[float]) -> None:
    """Insère une série hebdo d'états ur_local (dernier état = semaine courante)."""
    n = len(valeurs)
    for i, v in enumerate(valeurs):
        ts = _NOW - (n - 1 - i) * _WEEK
        service.client_db(node_id).save_urgency_state(
            node_id, UrgencyState(ur_local=float(v), timestamp=ts)
        )


def _evenement(
    service: SupplyScoreService,
    node_id: str,
    semaines_avant: int,
    gravite: str = "critique",
    annule: bool = False,
) -> None:
    """Journalise un événement dans la semaine « semaines_avant » semaines en arrière."""
    ts = _NOW - semaines_avant * _WEEK
    eid = f"evt-{node_id}-{semaines_avant}-{gravite}"
    db = service.client_db(node_id)
    db.save_event(
        eid, node_id, "panne_machine", iso_week(ts), ts, json.dumps({"gravite": gravite}), "[]", "t"
    )
    if annule:
        db.mark_reverted(eid, ts + 60.0)


def _jalon(
    service: SupplyScoreService,
    node_id: str,
    deadline_offset_weeks: float,
    status: MilestoneStatus = MilestoneStatus.ACTIVE,
    progress: float = 0.0,
) -> None:
    """Pose un jalon dont l'échéance est décalée de N semaines par rapport à maintenant."""
    service.registry.save_milestone(
        Milestone(
            id=f"m-{node_id}",
            node_id=node_id,
            name="Livraison",
            start_ts=_T0,
            deadline_ts=_NOW + deadline_offset_weeks * _WEEK,
            status=status,
            progress=progress,
        )
    )


def _p_evenement_beta(alpha: float, beta: float, k: int) -> float:
    """P(au moins un événement en k semaines) sous q ~ Beta(alpha, beta), exact."""
    produit = 1.0
    for j in range(k):
        produit *= (beta + j) / (alpha + beta + j)
    return 1.0 - produit


class ActionNulle:
    """Action identité : ne transforme rien (contrôle d'appariement parfait)."""

    delai_effet_weeks = (0.0, 0.0, 0.0)

    def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
        return state


class ActionNeutralisante:
    """Action qui annule le hazard et neutralise toutes les échéances."""

    def __init__(self, delai: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
        self.delai_effet_weeks = delai

    def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
        etat = dict(state)
        etat["hazard"] = np.zeros_like(np.asarray(state["hazard"], dtype=float))
        etat["deadlines_h"] = {}
        return etat


# --- Ajustement (AR(1), posterior Beta, garde-fous) -----------------------------------


class TestAjustement:
    def test_ar1_pente_exacte_et_plancher_sigma(self, service: SupplyScoreService) -> None:
        # Série géométrique x_{t+1} = 0.5·x_t exactement : pente OLS 0.5, résidus nuls.
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.8, 0.4, 0.2, 0.1, 0.05, 0.025])
        diag = ForecastService(service).rollout(project.id, n_draws=20).diagnostics[ids[0]]
        assert diag.phi == pytest.approx(0.5, abs=1e-9)
        assert diag.sigma == SIGMA_MIN  # résidus nuls : plancher appliqué
        assert diag.se_phi > 0.0
        assert diag.n_semaines == 6
        assert diag.ur_local_initial == pytest.approx(0.025)

    def test_ar1_serie_constante_phi_nul(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 8)
        diag = ForecastService(service).rollout(project.id, n_draws=20).diagnostics[ids[0]]
        assert diag.phi == 0.0
        assert diag.se_phi == 0.0
        assert diag.sigma == SIGMA_MIN
        assert diag.mu == pytest.approx(0.3)

    def test_ar1_pente_negative_clipee_a_zero(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.1, 0.9, 0.1, 0.9, 0.1, 0.9])
        diag = ForecastService(service).rollout(project.id, n_draws=20).diagnostics[ids[0]]
        assert diag.phi == 0.0  # pente négative : clip à [0, 0.98]

    def test_posterior_ne_compte_que_les_evenements_defavorables(
        self, service: SupplyScoreService
    ) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 10)
        _evenement(service, ids[0], 2, "critique")
        _evenement(service, ids[0], 4, "defaut")
        _evenement(service, ids[0], 6, "mineure")  # gravité non défavorable : ignorée
        _evenement(service, ids[0], 8, "critique", annule=True)  # annulé : ignoré
        diag = ForecastService(service).rollout(project.id, n_draws=20).diagnostics[ids[0]]
        assert diag.n_evenements == 2
        assert diag.alpha_post == pytest.approx(TAUX_PRIOR * 26.0 + 2)
        assert diag.beta_post == pytest.approx((1 - TAUX_PRIOR) * 26.0 + 8)
        assert diag.taux_evenement == pytest.approx(diag.alpha_post / (26.0 + 10))

    def test_historique_insuffisant_valueerror_francais(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 2)
        _historique(service, ids[0], [0.3] * 6)
        _historique(service, ids[1], [0.3] * (MIN_HISTORY_WEEKS - 1))  # 3 semaines : trop court
        with pytest.raises(ValueError, match="historique hebdomadaire insuffisant") as excinfo:
            ForecastService(service).rollout(project.id, n_draws=20)
        assert ids[1] in str(excinfo.value)
        assert str(MIN_HISTORY_WEEKS) in str(excinfo.value)
        assert ForecastService.MIN_HISTORY_WEEKS == MIN_HISTORY_WEEKS  # alias de classe (API)

    def test_entrees_invalides(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 6)
        fs = ForecastService(service)
        with pytest.raises(ValueError, match="horizon_weeks"):
            fs.rollout(project.id, horizon_weeks=0)
        with pytest.raises(ValueError, match="n_draws"):
            fs.rollout(project.id, n_draws=K_EXTERNES - 1)
        with pytest.raises(ValueError, match="Projet inconnu"):
            fs.rollout("p-fantome")


# --- Vérifications analytiques du rollout ---------------------------------------------


class TestRolloutAnalytique:
    def test_sans_evenement_ni_jalon_p_issue_quasi_nul(self, service: SupplyScoreService) -> None:
        # phi = 0 (série constante), sigma plancher, aucun événement, aucune échéance :
        # p_issue se réduit au seul risque d'événement du prior Beta érodé par
        # 30 semaines calmes — quasi nul et exactement calculable.
        project, ids = _creer_projet(service, 2)
        for nid in ids:
            _historique(service, nid, [0.2] * 30)
        resultat = ForecastService(service).rollout(project.id, n_draws=2000, seed=0)
        alpha = TAUX_PRIOR * 26.0
        beta = (1 - TAUX_PRIOR) * 26.0 + 30
        for nid in ids:
            for k in range(1, 5):
                prevision = resultat.previsions[nid][k]
                assert prevision.p_jalon_rate == 0.0  # aucune échéance
                assert prevision.p_issue < 0.12  # « quasi nul »
                attendu = _p_evenement_beta(alpha, beta, k)
                assert prevision.p_issue == pytest.approx(attendu, abs=0.05)

    def test_hazard_bernoulli_pur_formule_exacte(self, service: SupplyScoreService) -> None:
        # 6 semaines à événement défavorable sur 26 : posterior Beta connu, pas de
        # jalon → p_issue(k) = 1 − E[(1 − q)^k], calculable exactement par les
        # moments de la Beta. Tolérance = bruit MC + paramétrique (graine figée).
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 26)
        for semaine in (2, 4, 6, 8, 10, 12):
            _evenement(service, ids[0], semaine, "critique")
        resultat = ForecastService(service).rollout(project.id, n_draws=2000, seed=0)
        alpha = TAUX_PRIOR * 26.0 + 6
        beta = (1 - TAUX_PRIOR) * 26.0 + 20
        for k in range(1, 5):
            prevision = resultat.previsions[ids[0]][k]
            attendu = _p_evenement_beta(alpha, beta, k)
            assert prevision.p_issue == pytest.approx(attendu, abs=0.06)
            assert prevision.p_jalon_rate == 0.0

    def test_jalon_depasse_deterministe(self, service: SupplyScoreService) -> None:
        # Échéance déjà passée (d <= t) : jalon raté sûr, hors estimateur MC.
        project, ids = _creer_projet(service, 2)
        for nid in ids:
            _historique(service, nid, [0.2] * 6)
        _jalon(service, ids[1], deadline_offset_weeks=-1.0)
        resultat = ForecastService(service).rollout(project.id, n_draws=100, seed=3)
        for k in range(1, 5):
            assert resultat.previsions[ids[1]][k].p_jalon_rate == 1.0
            assert resultat.previsions[ids[1]][k].p_issue == 1.0
            assert resultat.previsions[ids[0]][k].p_jalon_rate == 0.0

    def test_decomposition_variance_coherente(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 26)
        for semaine in (2, 4, 6, 8, 10, 12):
            _evenement(service, ids[0], semaine, "critique")
        resultat = ForecastService(service).rollout(project.id, n_draws=2000, seed=0)
        assert resultat.n_draws == 2000
        assert resultat.n_outer == K_EXTERNES
        for k in range(1, 5):
            prevision = resultat.previsions[ids[0]][k]
            assert prevision.var_mc >= 0.0
            assert prevision.var_param >= 0.0
            assert prevision.var_param > 0.0  # le taux Beta varie entre tirages externes
            assert prevision.se_mc == pytest.approx((prevision.var_mc / 2000) ** 0.5)
            assert prevision.ic80.couverture == ("mc", "param")
            assert prevision.ic80.bas <= prevision.p_issue <= prevision.ic80.haut
            assert prevision.spread == pytest.approx(prevision.ic80.haut - prevision.ic80.bas)
            assert 0.0 <= prevision.ic80.bas <= prevision.ic80.haut <= 1.0

    def test_meme_graine_resultats_identiques(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 2)
        for nid in ids:
            _historique(service, nid, [0.2, 0.3, 0.25, 0.35, 0.3, 0.4])
        _evenement(service, ids[1], 2, "critique")
        fs = ForecastService(service)
        a = fs.rollout(project.id, n_draws=200, seed=42)
        b = fs.rollout(project.id, n_draws=200, seed=42)
        c = fs.rollout(project.id, n_draws=200, seed=43)
        assert a == b  # dataclasses figées : égalité champ à champ
        assert a != c

    def test_to_snapshot_block_contrat_7(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 2)
        for nid in ids:
            _historique(service, nid, [0.2] * 6)
        resultat = ForecastService(service).rollout(project.id, n_draws=100, seed=0)
        bloc = to_snapshot_block(resultat)
        assert set(bloc) == set(ids)
        for nid in ids:
            forecast = bloc[nid]["forecast"]
            assert list(forecast) == ["1", "2", "3", "4"]
            for k in range(1, 5):
                cellule = forecast[str(k)]
                assert set(cellule) == {
                    "p_issue",
                    "se_mc",
                    "spread",
                    "p_jalon_rate",
                    "p_impact_client",
                }
                assert all(isinstance(v, float) for v in cellule.values())
                assert cellule["p_issue"] == resultat.previsions[nid][k].p_issue

    def test_vocabulaire_effet_selon_le_modele(self) -> None:
        # Décision D18’ : le module parle d'« effet SELON LE MODÈLE », et
        # l'équivalence avec l'issue défavorable de la calibration est énoncée.
        import supplyscore.services.forecast as module

        doc = (module.__doc__ or "").lower()
        assert "selon le modèle" in doc
        assert "issue défavorable" in doc
        assert "calibrationservice" in doc


# --- Contrefactuels appariés (CRN) ----------------------------------------------------


class TestRolloutApparie:
    def _projet_avec_risque(self, service: SupplyScoreService) -> tuple[Project, list[str]]:
        project, ids = _creer_projet(service, 2)
        _historique(service, ids[0], [0.2] * 12)
        _historique(service, ids[1], [0.3] * 12)
        for semaine in (1, 3, 5, 7):
            _evenement(service, ids[1], semaine, "critique")
        _jalon(service, ids[1], deadline_offset_weeks=-0.5)  # déjà ratée : p0 = 1 sur n-01
        return project, ids

    def test_action_nulle_delta_exactement_zero(self, service: SupplyScoreService) -> None:
        project, ids = self._projet_avec_risque(service)
        fs = ForecastService(service)
        apparie = fs.rollout_with_action(project.id, ActionNulle(), n_draws=400, seed=7)
        simple = fs.rollout(project.id, n_draws=400, seed=7)
        for nid in ids:
            for k in range(1, 5):
                paire = apparie.previsions[nid][k]
                assert paire.delta_u_sim == 0.0  # appariement parfait : zéro EXACT
                assert paire.p0 == paire.p1
                # Différences appariées toutes nulles : IC mc et param dégénérés en 0.
                assert paire.ic80_delta_mc.bas == 0.0
                assert paire.ic80_delta_mc.haut == 0.0
                assert paire.ic80_delta_param.bas == 0.0
                assert paire.ic80_delta_param.haut == 0.0
                assert paire.p_delta_positif == 0.0
                assert paire.p_impact_client_0 == paire.p_impact_client_1
                # Flux aléatoires séparés : la branche SANS action reproduit
                # bit à bit le rollout simple à graine égale.
                assert paire.p0 == simple.previsions[nid][k].p_issue

    def test_action_neutralisante_delta_egale_p0(self, service: SupplyScoreService) -> None:
        project, ids = self._projet_avec_risque(service)
        fs = ForecastService(service)
        apparie = fs.rollout_with_action(project.id, ActionNeutralisante(), n_draws=400, seed=7)
        for nid in ids:
            for k in range(1, 5):
                paire = apparie.previsions[nid][k]
                assert paire.p1 == 0.0  # hazard nul + échéances neutralisées
                assert paire.delta_u_sim == pytest.approx(paire.p0, abs=1e-12)
        # Le jalon déjà raté de n-01 est sauvé par la neutralisation immédiate :
        # delta = p0 = 1 et toutes les moyennes externes sont positives.
        paire_f1 = apparie.previsions[ids[1]][4]
        assert paire_f1.p0 == 1.0
        assert paire_f1.delta_u_sim == 1.0
        assert paire_f1.p_delta_positif == 1.0
        assert paire_f1.ic80_delta_param.bas == 1.0

    def test_delai_effet_une_semaine(self, service: SupplyScoreService) -> None:
        # Délai (1, 1, 1) : ⌊1⌋ = 1 semaine pleine sans effet — la semaine 1
        # est identique à la branche sans action (delta = 0 EXACT), l'effet
        # n'apparaît qu'à partir de la semaine 2.
        project, ids = _creer_projet(service, 2)
        _historique(service, ids[0], [0.2] * 26)
        _historique(service, ids[1], [0.3] * 26)
        for semaine in range(1, 27):
            _evenement(service, ids[1], semaine, "critique")
        action = ActionNeutralisante(delai=(1.0, 1.0, 1.0))
        apparie = ForecastService(service).rollout_with_action(
            project.id, action, n_draws=2000, seed=0
        )
        paire = apparie.previsions[ids[1]]
        assert paire[1].delta_u_sim == 0.0
        assert paire[1].p1 == paire[1].p0
        assert paire[4].delta_u_sim > 0.0
        assert paire[4].p1 < paire[4].p0

    def test_impact_client_via_propagation(self, service: SupplyScoreService) -> None:
        # n-01 très événementiel alimente n-00 (β = 0.9) : ses bumps propagés
        # dépassent le seuil ΔUr > 0.2 au rang 0 bien plus souvent que ceux du
        # client final resté calme.
        project, ids = _creer_projet(service, 2, beta=0.9)
        _historique(service, ids[0], [0.2] * 26)
        _historique(service, ids[1], [0.2] * 26)
        for semaine in range(1, 27):
            _evenement(service, ids[1], semaine, "critique")
        resultat = ForecastService(service).rollout(project.id, n_draws=2000, seed=0)
        impact_f1 = resultat.previsions[ids[1]][4].p_impact_client
        impact_c0 = resultat.previsions[ids[0]][4].p_impact_client
        assert impact_f1 > 0.2
        assert impact_f1 > impact_c0

    def test_action_neutralisant_un_arc(self, service: SupplyScoreService) -> None:
        # Action qui coupe l'arc n-01 -> n-00 (β = 0 pour les tirages actifs) :
        # les événements de n-01 ne se propagent plus au client final, son
        # p_impact_client s'effondre dans la branche AVEC action.
        project, ids = _creer_projet(service, 2, beta=0.9)
        _historique(service, ids[0], [0.2] * 26)
        _historique(service, ids[1], [0.2] * 26)
        for semaine in range(1, 26):
            _evenement(service, ids[1], semaine, "critique")

        class ActionCoupeArc:
            delai_effet_weeks = (0.0, 0.0, 0.0)

            def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
                etat = dict(state)
                arcs = dict(state["arc_beta"])
                arcs[("n-01", "n-00")] = 0.0
                etat["arc_beta"] = arcs
                return etat

        apparie = ForecastService(service).rollout_with_action(
            project.id, ActionCoupeArc(), n_draws=2000, seed=0
        )
        paire = apparie.previsions[ids[1]][4]
        assert paire.p_impact_client_0 > 0.2  # β = 0.9 : impact réel sans action
        assert paire.p_impact_client_1 == 0.0  # arc coupé : plus aucun ΔUr au rang 0
        # L'issue (événements du nœud lui-même) ne change pas : delta nul.
        assert paire.delta_u_sim == 0.0

    def test_action_promouvant_un_arc(self, service: SupplyScoreService) -> None:
        # Chaîne de 3 : promotion d'un arc direct n-02 -> n-00 (β = 0.9) qui
        # court-circuite la chaîne, plus une promotion topologiquement invalide
        # (n-00 -> n-02, sens client -> fournisseur) qui doit être IGNORÉE.
        project, ids = _creer_projet(service, 3, beta=0.5)
        for nid in ids:
            _historique(service, nid, [0.2] * 26)
        for semaine in range(1, 26):
            _evenement(service, ids[2], semaine, "critique")

        class ActionPromotion:
            delai_effet_weeks = (0.0, 0.0, 0.0)

            def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
                etat = dict(state)
                arcs = dict(state["arc_beta"])
                arcs[("n-02", "n-00")] = 0.9  # secours promu : exposition directe
                arcs[("n-00", "n-02")] = 0.9  # sens invalide : doit être ignoré
                etat["arc_beta"] = arcs
                return etat

        apparie = ForecastService(service).rollout_with_action(
            project.id, ActionPromotion(), n_draws=2000, seed=0
        )
        paire = apparie.previsions[ids[2]][4]
        # L'arc direct ajoute un chemin d'exposition : l'impact client du
        # fournisseur profond augmente strictement dans la branche AVEC.
        assert paire.p_impact_client_1 > paire.p_impact_client_0

    def test_delai_invalide_valueerror(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 6)

        class ActionDelaiIncoherent:
            delai_effet_weeks = (2.0, 1.0, 3.0)

            def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
                return state

        class ActionDelaiMalForme:
            delai_effet_weeks = (1.0, 2.0)  # pas un triplet

            def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
                return state

        fs = ForecastService(service)
        with pytest.raises(ValueError, match="delai_effet_weeks"):
            fs.rollout_with_action(project.id, ActionDelaiIncoherent(), n_draws=40)
        with pytest.raises(ValueError, match="delai_effet_weeks"):
            fs.rollout_with_action(project.id, ActionDelaiMalForme(), n_draws=40)  # type: ignore[arg-type]

    def test_etat_retourne_incomplet_valueerror(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 6)

        class ActionCassee:
            delai_effet_weeks = (0.0, 0.0, 0.0)

            def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
                return {"ur_local": state["ur_local"]}  # clés manquantes

        with pytest.raises(ValueError, match="clé"):
            ForecastService(service).rollout_with_action(project.id, ActionCassee(), n_draws=40)


# --- Bords : nœuds statiques, rangs 0 multiples ou absents, lois dégénérées -----------


class TestBords:
    def test_serie_ignore_les_etats_sans_ur_local(self, service: SupplyScoreService) -> None:
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 6)
        # État SANS ur_local dans une semaine plus ancienne : ignoré par la série.
        service.client_db(ids[0]).save_urgency_state(
            ids[0], UrgencyState(timestamp=_NOW - 10 * _WEEK)
        )
        diag = ForecastService(service).rollout(project.id, n_draws=20).diagnostics[ids[0]]
        assert diag.n_semaines == 6

    def test_projet_sans_noeud_actif(self, service: SupplyScoreService) -> None:
        projet = Project(id="p-brouillon", name="Brouillon", owner_node_id="d-0", created_at=_T0)
        noeud = SupplyNode(
            id="d-0", name="Brouillon", project_id="p-brouillon", onboarding_state="draft"
        )
        service.create_project(projet, [noeud], [])
        with pytest.raises(ValueError, match="aucun nœud actif"):
            ForecastService(service).rollout("p-brouillon", n_draws=20)

    def test_noeud_done_statique_hors_previsions(self, service: SupplyScoreService) -> None:
        # Le fournisseur profond passe DONE : il n'est plus simulé (aucune
        # exigence d'historique) mais reste un nœud STATIQUE de la propagation.
        project, ids = _creer_projet(service, 3)
        for nid in ids[:2]:
            _historique(service, nid, [0.2] * 6)
        node = service.repo.get_node(ids[2])
        assert node is not None
        node.status = TaskStatus.DONE
        service.repo.update_node(node)
        resultat = ForecastService(service).rollout(project.id, n_draws=40, seed=1)
        assert set(resultat.previsions) == {ids[0], ids[1]}
        assert set(resultat.diagnostics) == {ids[0], ids[1]}

    def test_projet_sans_rang_zero_impact_nul(self, service: SupplyScoreService) -> None:
        projet = Project(id="p-r1", name="Sans client", owner_node_id="s-1", created_at=_T0)
        noeud = SupplyNode(id="s-1", name="Fournisseur seul", rank=1, project_id="p-r1")
        service.create_project(projet, [noeud], [])
        _historique(service, "s-1", [0.3] * 6)
        resultat = ForecastService(service).rollout("p-r1", n_draws=40, seed=1)
        assert all(resultat.previsions["s-1"][k].p_impact_client == 0.0 for k in range(1, 5))

    def test_deux_noeuds_de_rang_zero(self, service: SupplyScoreService) -> None:
        # Deux clients finaux alimentés par le même fournisseur : ΔUr au rang 0
        # est le max des deux cibles.
        projet = Project(id="p-2r0", name="Deux clients", owner_node_id="c-a", created_at=_T0)
        noeuds = [
            SupplyNode(id="c-a", name="Client A", rank=0, project_id="p-2r0"),
            SupplyNode(id="c-b", name="Client B", rank=0, project_id="p-2r0"),
            SupplyNode(id="f-1", name="Fournisseur", rank=1, project_id="p-2r0"),
        ]
        arcs = [
            SupplyArc(source_id="f-1", target_id="c-a", beta=0.9),
            SupplyArc(source_id="f-1", target_id="c-b", beta=0.9),
        ]
        service.create_project(projet, noeuds, arcs)
        for nid in ("c-a", "c-b", "f-1"):
            _historique(service, nid, [0.2] * 26)
        for semaine in range(1, 26):
            _evenement(service, "f-1", semaine, "critique")
        resultat = ForecastService(service).rollout("p-2r0", n_draws=2000, seed=0)
        assert resultat.previsions["f-1"][4].p_impact_client > 0.2

    def test_delai_triangulaire_non_degenere(self, service: SupplyScoreService) -> None:
        # Support (0, 0.5, 1) non dégénéré : tous les délais tirés ont ⌊d⌋ = 0,
        # l'action neutralisante agit donc dès la semaine 1 — delta == p0.
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.3] * 12)
        for semaine in (1, 3, 5):
            _evenement(service, ids[0], semaine, "critique")
        action = ActionNeutralisante(delai=(0.0, 0.5, 1.0))
        apparie = ForecastService(service).rollout_with_action(
            project.id, action, n_draws=400, seed=5
        )
        for k in range(1, 5):
            paire = apparie.previsions[ids[0]][k]
            assert paire.p1 == 0.0
            assert paire.delta_u_sim == pytest.approx(paire.p0, abs=1e-12)

    def test_loi_externe_degeneree_en_deterministe(self) -> None:
        # Loi normale de moyenne très négative : les tirages (clip à 0) donnent
        # des moments nuls — le bootstrap dégénère en loi déterministe.
        from supplyscore.mc.lead_time import LoiLeadTime
        from supplyscore.services.forecast import _loi_externe

        loi = _loi_externe(LoiLeadTime("normale", m=-50.0, s=1.0), np.random.default_rng(0))
        assert loi.famille == "deterministe"
        assert loi.m == 0.0


# --- Performance ----------------------------------------------------------------------


class TestPerformance:
    def test_performance_chaine_20_noeuds(self, service: SupplyScoreService) -> None:
        # Budget du plan : S = 2000, h = 4, chaîne de 20 nœuds, < 60 s — la
        # durée mesurée est consignée dans la docstring du module forecast.
        project, ids = _creer_projet(service, 20)
        for i, nid in enumerate(ids):
            _historique(service, nid, [0.2 + 0.01 * (i % 5)] * 6)
            node = service.repo.get_node(nid)
            assert node is not None
            node.kpis.time.lead_time_h = 300.0
            node.kpis.time.lead_time_std_h = 80.0
            service.repo.update_node(node)
        for nid in ids[::4]:
            _evenement(service, nid, 2, "critique")
        for nid in ids[::5]:
            _jalon(service, nid, deadline_offset_weeks=2.0)
        fs = ForecastService(service)
        debut = time.perf_counter()
        resultat = fs.rollout(project.id, horizon_weeks=4, n_draws=2000, seed=0)
        apparie = fs.rollout_with_action(
            project.id, ActionNulle(), horizon_weeks=4, n_draws=2000, seed=0
        )
        duree = time.perf_counter() - debut
        assert duree < 60.0, f"rollout + rollout apparié en {duree:.1f} s (budget 60 s)"
        assert len(resultat.previsions) == 20
        assert len(apparie.previsions) == 20
        # Les jalons à échéance S+2 exposés à un lead time ~300 h produisent un
        # risque de jalon raté non trivial dès la semaine 2.
        assert any(resultat.previsions[nid][4].p_jalon_rate > 0.0 for nid in ids[::5])


class TestJalonTravailRestant:
    """P(jalon raté) porte sur le TRAVAIL RESTANT, pas sur un cycle complet.

    Régression du défaut mesuré sur la campagne HÉLIOS : le rollout tirait un
    lead time de cycle ENTIER et le comparait à la marge, donc tout nœud dont
    le lead time nominal dépassait sa marge était déclaré perdu d'avance quel
    que soit son avancement — 99,6 % annoncé sur un jalon livré à l'heure.
    """

    @staticmethod
    def _projet_lead_long(service: SupplyScoreService, progress: float) -> tuple[str, str]:
        """Nœud unique, cycle nominal 400 h, jalon à 1 semaine (168 h) de marge."""
        project, ids = _creer_projet(service, 1)
        _historique(service, ids[0], [0.2] * 30)
        node = service.repo.get_node(ids[0])
        node.kpis.time.lead_time_h = 400.0
        node.kpis.time.lead_time_std_h = 40.0
        service.repo.update_node(node)
        _jalon(service, ids[0], deadline_offset_weeks=1.0, progress=progress)
        return project.id, ids[0]

    def _p_jalon(self, service: SupplyScoreService, progress: float) -> float:
        project_id, nid = self._projet_lead_long(service, progress)
        resultat = ForecastService(service).rollout(project_id, n_draws=2000, seed=0)
        return resultat.previsions[nid][4].p_jalon_rate

    def test_avancement_nul_jalon_perdu(self, service: SupplyScoreService) -> None:
        # 400 h de cycle a faire en 168 h : rate quasi certain. Comportement
        # INCHANGE a progress = 0 — la correction est un sur-ensemble.
        assert self._p_jalon(service, 0.0) > 0.99

    def test_avancement_avance_desature(self, service: SupplyScoreService) -> None:
        # Meme noeud a 90 % : il reste 40 h a faire pour 168 h de marge.
        assert self._p_jalon(service, 0.9) < 0.05

    def test_decroissant_en_progress(self, tmp_path: Any) -> None:
        # Un jalon plus avance ne peut pas etre plus a risque, toutes choses
        # egales par ailleurs (meme graine, meme scenario).
        precedent = 1.1
        for progress in (0.0, 0.3, 0.6, 0.9, 1.0):
            svc = SupplyScoreService(db_dir=tmp_path / f"store-{progress}", clock=FixedClock(_NOW))
            try:
                courant = self._p_jalon(svc, progress)
            finally:
                svc.close()
            assert courant <= precedent + 1e-12, f"remontee a progress={progress}"
            precedent = courant

    def test_jalon_termine_aucun_risque(self, service: SupplyScoreService) -> None:
        # progress = 1 : plus rien a faire, la marge suffit toujours.
        assert self._p_jalon(service, 1.0) == 0.0
