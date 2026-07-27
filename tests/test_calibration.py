"""Tests du Lot 11.1 : CalibrationService — le score H a-t-il prédit les ruptures ?

Couvre : le cas synthétique chiffré à la main (VP=3, FP=1, FN=1, VN=5,
précision=rappel=0.75), la courbe de calibration sur 2 tranches connues
(moyennes/taux/effectifs exacts, tranches vides omises), les outcomes d'une
vraie partie (FixedClock + seed_demo + GameClock : jalon raté, événement
critique, événement annulé ignoré, H None ignorés, nœud abandonné en proxy),
le résumé français (avertissement « échantillon trop petit », précision/rappel
non définis) et les propriétés None de ConfusionMatrix sur dénominateurs nuls.

Couvre aussi les métriques de discrimination/calibration du lot en cours :
AUC (Mann-Whitney, séparation parfaite/inversée/aléatoire, ex æquo massifs et
partiels chiffrés à la main), son IC95 bootstrap en grappes de nœuds
(reproductibilité à seed fixée, grappe unique à bornes exactes), average
precision et score de Brier/skill score chiffrés à la main, le balayage de
seuils et le seuil optimal (Youden/F1) sur des cas chiffrés à la main.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import Project, SupplyNode, TaskStatus, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.services.calibration import (
    CalibrationService,
    ConfusionMatrix,
    OutcomePoint,
    _score_f1,
    _score_youden,
    _semaine_decalee,
)
from supplyscore.services.events import EventEngine

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0


def _point(
    h: float | None,
    issue: bool,
    *,
    node: str = "n-1",
    name: str = "Nœud",
    week: str = "2026-S10",
) -> OutcomePoint:
    """Point d'observation synthétique (construit à la main, sans base)."""
    return OutcomePoint(
        node_id=node,
        node_name=name,
        iso_week=week,
        hidden_risk=h,
        ur=h,
        issue_defavorable=issue,
        causes=["cause de test"] if issue else [],
    )


# --- Fixtures -----------------------------------------------------------------------


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    yield svc
    svc.close()


@pytest.fixture
def calib(service: SupplyScoreService) -> CalibrationService:
    return CalibrationService(service)


@pytest.fixture
def partie(
    service: SupplyScoreService,
) -> tuple[SupplyScoreService, Project, tuple[str, str, str]]:
    """Vraie partie : seed_demo en S24, 5 semaines de jeu, issues contrôlées.

    Scénario (semaine courante finale : 2026-S29) :

    - les jalons générés par seed_demo sont repoussés hors de toute fenêtre ;
    - nœud A : jalon « Prototype » ACTIVE, échéance en S25, jamais livré ;
    - nœud B : panne machine de gravité critique déclarée en S26 ; plus un
      pic de demande (sans gravité) la même semaine ;
    - nœud C : état d'urgence SANS H inséré en S23, et un événement de
      gravité « defaut » déclaré en S26 puis ANNULÉ aussitôt.
    """
    # Correctif E11 : ``evaluate_all`` re-horodate désormais chaque état avec
    # l'horloge effective de SON projet (mode jeu inclus) — plus aucun
    # contournement nécessaire ici, les états tombent dans la bonne semaine.
    projet = service.seed_demo(n_ranks=2, seed=1)
    nodes = sorted(
        (
            n
            for n in service.repo.nodes()
            if n.status is TaskStatus.ACTIVE and n.onboarding_state == "complete"
        ),
        key=lambda n: n.id,
    )
    assert len(nodes) >= 3, "le projet de démo doit contenir au moins trois nœuds actifs"
    node_a, node_b, node_c = nodes[0].id, nodes[1].id, nodes[2].id

    # Jalons de seed_demo repoussés à +100 semaines : aucun « jalon raté » parasite.
    for node in service.repo.nodes():
        for milestone in service.registry.list_milestones(node.id):
            milestone.deadline_ts = _NOW + 100 * _WEEK
            service.registry.save_milestone(milestone)

    # Jalon raté contrôlé sur A : échéance dans la semaine S25, jamais livré.
    service.registry.save_milestone(
        Milestone(
            id="m-rate",
            node_id=node_a,
            name="Prototype",
            start_ts=_NOW,
            deadline_ts=_NOW + 1.5 * _WEEK,
            status=MilestoneStatus.ACTIVE,
            progress=0.2,
            position=99,
        )
    )
    # État d'urgence SANS H sur C, une semaine avant le départ (S23).
    service.client_db(node_c).save_urgency_state(node_c, UrgencyState(timestamp=_NOW - _WEEK))

    service.set_clock_mode(projet.id, "game")
    service.advance_week(projet.id)  # S25
    service.advance_week(projet.id)  # S26

    engine = EventEngine(service)
    engine.apply(node_b, "panne_machine", {"duree_arret_h": 24.0, "gravite": "critique"})
    engine.apply(node_b, "pic_demande", {"nouvelle_demande": 250.0})  # sans gravité
    annule = engine.apply(node_c, "alerte_financiere_fournisseur", {"gravite": "defaut"})
    engine.revert(annule.id, node_c)  # déclaré par erreur : ne doit pas compter

    for _ in range(3):
        service.advance_week(projet.id)  # S27, S28, S29 (semaine courante)
    return service, projet, (node_a, node_b, node_c)


# --- Cas synthétique chiffré à la main ------------------------------------------------


class TestConfusionSynthetique:
    """10 points : 4 avec H>0.5 (3 issues), 6 avec H<0.5 (1 issue)."""

    POINTS: ClassVar[list[OutcomePoint]] = [
        # 4 points H > 0.5 : 3 issues constatées (VP), 1 fausse alerte (FP).
        _point(0.9, True),
        _point(0.8, True),
        _point(0.6, True),
        _point(0.7, False),
        # 6 points H < 0.5 : 1 rupture ratée (FN), 5 calmes (VN).
        _point(0.4, True),
        _point(0.1, False),
        _point(0.2, False),
        _point(0.3, False),
        _point(0.05, False),
        _point(0.45, False),
    ]

    def test_matrice_chiffree_a_la_main(self, calib: CalibrationService) -> None:
        matrice = calib.confusion(self.POINTS, seuil=0.5)
        assert (matrice.vp, matrice.fp, matrice.fn, matrice.vn) == (3, 1, 1, 5)
        assert matrice.seuil == 0.5
        assert matrice.precision == pytest.approx(0.75)
        assert matrice.rappel == pytest.approx(0.75)

    def test_points_sans_h_ignores(self, calib: CalibrationService) -> None:
        points = [*self.POINTS, _point(None, True), _point(None, False)]
        matrice = calib.confusion(points, seuil=0.5)
        assert (matrice.vp, matrice.fp, matrice.fn, matrice.vn) == (3, 1, 1, 5)

    def test_h_egal_au_seuil_n_est_pas_positif(self, calib: CalibrationService) -> None:
        # Prédiction positive STRICTE : H > seuil, pas >=.
        matrice = calib.confusion([_point(0.5, True)], seuil=0.5)
        assert (matrice.vp, matrice.fp, matrice.fn, matrice.vn) == (0, 0, 1, 0)


# --- ConfusionMatrix : dénominateurs nuls ---------------------------------------------


class TestConfusionMatrix:
    def test_precision_et_rappel_none_sur_denominateurs_nuls(self) -> None:
        matrice = ConfusionMatrix(seuil=0.5, vp=0, fp=0, fn=0, vn=4)
        assert matrice.precision is None
        assert matrice.rappel is None

    def test_precision_definie_rappel_none(self) -> None:
        matrice = ConfusionMatrix(seuil=0.5, vp=0, fp=2, fn=0, vn=4)
        assert matrice.precision == 0.0
        assert matrice.rappel is None

    def test_rappel_defini_precision_none(self) -> None:
        matrice = ConfusionMatrix(seuil=0.5, vp=0, fp=0, fn=3, vn=4)
        assert matrice.precision is None
        assert matrice.rappel == 0.0


# --- Scores internes du seuil optimal (Youden / F1) sur matrices à la main ---------------


class TestScoresInternes:
    def test_youden_valeur_definie_chiffree_a_la_main(self) -> None:
        # rappel=6/8=0.75, spécificité=3/5=0.6 -> Youden=0.35.
        matrice = ConfusionMatrix(seuil=0.5, vp=6, fp=2, fn=2, vn=3)
        assert _score_youden(matrice) == pytest.approx(0.35)

    def test_youden_none_si_rappel_indefini(self) -> None:
        # Aucune issue défavorable (vp+fn=0) : rappel indéfini.
        matrice = ConfusionMatrix(seuil=0.5, vp=0, fp=2, fn=0, vn=3)
        assert _score_youden(matrice) is None

    def test_youden_none_si_specificite_indefinie(self) -> None:
        # Aucun négatif (vn+fp=0) : spécificité indéfinie.
        matrice = ConfusionMatrix(seuil=0.5, vp=2, fp=0, fn=1, vn=0)
        assert _score_youden(matrice) is None

    def test_f1_valeur_definie_chiffree_a_la_main(self) -> None:
        # précision=2/3, rappel=2/4=0.5 -> F1=2*(2/3)*0.5/(2/3+0.5)=0.5714...
        matrice = ConfusionMatrix(seuil=0.5, vp=2, fp=1, fn=2, vn=1)
        assert _score_f1(matrice) == pytest.approx(2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))

    def test_f1_none_si_precision_ou_rappel_indefini(self) -> None:
        sans_prediction_positive = ConfusionMatrix(seuil=0.5, vp=0, fp=0, fn=2, vn=3)
        sans_issue_defavorable = ConfusionMatrix(seuil=0.5, vp=0, fp=2, fn=0, vn=3)
        assert _score_f1(sans_prediction_positive) is None
        assert _score_f1(sans_issue_defavorable) is None

    def test_f1_none_si_precision_et_rappel_nuls(self) -> None:
        # vp=0 avec fp>0 ET fn>0 : précision=0, rappel=0, somme nulle ->
        # F1 indéfini (division par zéro évitée).
        matrice = ConfusionMatrix(seuil=0.5, vp=0, fp=2, fn=3, vn=1)
        assert matrice.precision == 0.0
        assert matrice.rappel == 0.0
        assert _score_f1(matrice) is None


# --- Courbe de calibration -------------------------------------------------------------


class TestCalibrationCurve:
    def test_deux_tranches_connues_tranches_vides_omises(self, calib: CalibrationService) -> None:
        points = [
            _point(0.1, False),
            _point(0.15, False),  # tranche [0, 0.2) : H moyen 0.125, taux 0, n=2
            _point(0.9, True),
            _point(0.95, True),
            _point(1.0, False),  # tranche [0.8, 1] : H moyen 0.95, taux 2/3, n=3
        ]
        courbe = calib.calibration_curve(points, n_bins=5)
        assert len(courbe) == 2  # tranches 1, 2 et 3 vides : omises
        h_bas, taux_bas, n_bas = courbe[0]
        assert h_bas == pytest.approx(0.125)
        assert taux_bas == pytest.approx(0.0)
        assert n_bas == 2
        h_haut, taux_haut, n_haut = courbe[1]
        assert h_haut == pytest.approx(0.95)
        assert taux_haut == pytest.approx(2 / 3)
        assert n_haut == 3

    def test_points_sans_h_ignores_et_liste_vide(self, calib: CalibrationService) -> None:
        assert calib.calibration_curve([]) == []
        assert calib.calibration_curve([_point(None, True)]) == []

    def test_n_bins_invalide(self, calib: CalibrationService) -> None:
        with pytest.raises(ValueError, match="n_bins"):
            calib.calibration_curve([], n_bins=0)


# --- AUC (Mann-Whitney) ------------------------------------------------------------------


class TestAuc:
    def test_separation_parfaite_auc_1(self, calib: CalibrationService) -> None:
        points = [
            _point(0.9, True, node="n-1"),
            _point(0.8, True, node="n-2"),
            _point(0.2, False, node="n-3"),
            _point(0.1, False, node="n-4"),
        ]
        assert calib.auc(points) == pytest.approx(1.0)

    def test_separation_inversee_auc_0(self, calib: CalibrationService) -> None:
        points = [
            _point(0.1, True, node="n-1"),
            _point(0.2, True, node="n-2"),
            _point(0.8, False, node="n-3"),
            _point(0.9, False, node="n-4"),
        ]
        assert calib.auc(points) == pytest.approx(0.0)

    def test_auc_intermediaire_chiffre_a_la_main(self, calib: CalibrationService) -> None:
        # Paires (positif, négatif) : (0.9,0.8) concordante, (0.9,0.3) concordante,
        # (0.2,0.8) discordante, (0.2,0.3) discordante -> 2/4 = AUC 0.5.
        points = [
            _point(0.9, True, node="n-1"),
            _point(0.2, True, node="n-2"),
            _point(0.8, False, node="n-3"),
            _point(0.3, False, node="n-4"),
        ]
        assert calib.auc(points) == pytest.approx(0.5)

    def test_ex_aequo_massifs_toutes_valeurs_egales(self, calib: CalibrationService) -> None:
        # Toutes les valeurs de H sont égales : chaque paire ne vaut que 0.5,
        # quel que soit le déséquilibre des classes (2 positifs, 3 négatifs).
        points = [
            _point(0.5, True, node="n-1"),
            _point(0.5, True, node="n-2"),
            _point(0.5, False, node="n-3"),
            _point(0.5, False, node="n-4"),
            _point(0.5, False, node="n-5"),
        ]
        assert calib.auc(points) == pytest.approx(0.5)

    def test_ex_aequo_partiels_chiffres_a_la_main(self, calib: CalibrationService) -> None:
        # 2 positifs à H=0.7, 1 négatif ex æquo à H=0.7, 1 négatif à H=0.2.
        # Paires : (pos,neg=0.7) ex æquo -> 0.5 chacune (x2) ; (pos,neg=0.2)
        # concordantes -> 1 chacune (x2). Somme 3 sur 4 paires : AUC = 0.75.
        points = [
            _point(0.7, True, node="n-1"),
            _point(0.7, True, node="n-2"),
            _point(0.7, False, node="n-3"),
            _point(0.2, False, node="n-4"),
        ]
        assert calib.auc(points) == pytest.approx(0.75)

    def test_classe_unique_none(self, calib: CalibrationService) -> None:
        assert calib.auc([_point(0.9, True, node="n-1"), _point(0.1, True, node="n-2")]) is None
        assert calib.auc([_point(0.9, False, node="n-1"), _point(0.1, False, node="n-2")]) is None

    def test_points_sans_h_ignores(self, calib: CalibrationService) -> None:
        points = [
            _point(0.9, True, node="n-1"),
            _point(0.1, False, node="n-2"),
            _point(None, True, node="n-3"),
        ]
        assert calib.auc(points) == pytest.approx(1.0)

    def test_liste_vide_none(self, calib: CalibrationService) -> None:
        assert calib.auc([]) is None


# --- Intervalle de confiance de l'AUC (bootstrap en grappes) -----------------------------


class TestAucCi:
    def test_grappe_unique_bornes_exactes(self, calib: CalibrationService) -> None:
        # Un seul nœud : chaque tirage bootstrap ré-échantillonne TOUJOURS ce
        # même (et seul) nœud -> l'AUC est strictement identique à chaque tirage.
        points = [_point(0.9, True, node="n-1"), _point(0.1, False, node="n-1")]
        ic = calib.auc_ci(points, n_boot=10, seed=0)
        assert ic is not None
        bas, haut = ic
        assert bas == pytest.approx(1.0)
        assert haut == pytest.approx(1.0)

    def test_reproductible_a_seed_fixe(self, calib: CalibrationService) -> None:
        points = [
            _point(0.9, True, node="n-1"),
            _point(0.8, True, node="n-1"),
            _point(0.6, True, node="n-2"),
            _point(0.4, False, node="n-3"),
            _point(0.2, False, node="n-4"),
            _point(0.3, False, node="n-2"),
        ]
        ic_a = calib.auc_ci(points, n_boot=200, seed=42)
        ic_b = calib.auc_ci(points, n_boot=200, seed=42)
        assert ic_a == ic_b
        assert ic_a is not None
        bas, haut = ic_a
        assert 0.0 <= bas <= haut <= 1.0

    def test_moins_de_deux_tirages_none(self, calib: CalibrationService) -> None:
        # Un seul tirage bootstrap ne peut jamais produire deux valeurs.
        points = [_point(0.9, True, node="n-1"), _point(0.1, False, node="n-2")]
        assert calib.auc_ci(points, n_boot=1) is None

    def test_classe_unique_none(self, calib: CalibrationService) -> None:
        points = [_point(0.9, True, node="n-1"), _point(0.5, True, node="n-2")]
        assert calib.auc_ci(points, n_boot=50) is None

    def test_liste_vide_none(self, calib: CalibrationService) -> None:
        assert calib.auc_ci([]) is None


# --- Average precision (aire sous la courbe précision-rappel) ----------------------------


class TestPrAuc:
    def test_valeur_chiffree_a_la_main(self, calib: CalibrationService) -> None:
        # H décroissant [0.9,0.8,0.7,0.6], issues [T,F,T,F] :
        # recall 0.5 à precision 1 (poids 0.5) + recall 1 à precision 2/3 (poids 0.5)
        # = 0.5 + 1/3 = 5/6.
        points = [
            _point(0.9, True, node="n-1"),
            _point(0.8, False, node="n-2"),
            _point(0.7, True, node="n-3"),
            _point(0.6, False, node="n-4"),
        ]
        assert calib.pr_auc(points) == pytest.approx(5 / 6)

    def test_ex_aequo_chiffre_a_la_main(self, calib: CalibrationService) -> None:
        # Un positif et un négatif ex æquo à H=0.5 : palier unique, précision
        # 1/2, rappel 1 -> AP = 0.5.
        points = [_point(0.5, True, node="n-1"), _point(0.5, False, node="n-2")]
        assert calib.pr_auc(points) == pytest.approx(0.5)

    def test_aucune_issue_none(self, calib: CalibrationService) -> None:
        points = [_point(0.9, False, node="n-1"), _point(0.1, False, node="n-2")]
        assert calib.pr_auc(points) is None

    def test_points_sans_h_ignores(self, calib: CalibrationService) -> None:
        points = [_point(0.9, True, node="n-1"), _point(None, False, node="n-2")]
        assert calib.pr_auc(points) == pytest.approx(1.0)

    def test_liste_vide_none(self, calib: CalibrationService) -> None:
        assert calib.pr_auc([]) is None


# --- Score de Brier et skill score --------------------------------------------------------


class TestBrier:
    def test_valeurs_chiffrees_a_la_main(self, calib: CalibrationService) -> None:
        # Erreurs quadratiques : 0.01, 0.01, 0.36, 0.36 -> brier = 0.74/4 = 0.185.
        # Taux de base 0.5 -> brier climatologique = 0.25 -> skill = 1-0.74 = 0.26.
        points = [
            _point(0.9, True, node="n-1"),
            _point(0.1, False, node="n-2"),
            _point(0.4, True, node="n-3"),
            _point(0.6, False, node="n-4"),
        ]
        resultat = calib.brier(points)
        assert resultat is not None
        brier_score, skill = resultat
        assert brier_score == pytest.approx(0.185)
        assert skill == pytest.approx(0.26)

    def test_climatologie_parfaite_skill_zero_sans_division_par_zero(
        self, calib: CalibrationService
    ) -> None:
        # Classe unique (toujours défavorable) : brier climatologique nul ;
        # convention documentée -> skill score à 0.0, pas de crash.
        points = [_point(0.9, True, node="n-1"), _point(0.6, True, node="n-2")]
        resultat = calib.brier(points)
        assert resultat is not None
        brier_score, skill = resultat
        assert brier_score == pytest.approx(0.085)
        assert skill == 0.0

    def test_points_sans_h_ignores(self, calib: CalibrationService) -> None:
        assert calib.brier([_point(None, True)]) is None

    def test_liste_vide_none(self, calib: CalibrationService) -> None:
        assert calib.brier([]) is None


# --- Balayage de seuils --------------------------------------------------------------------


class TestSweep:
    def test_longueur_egale_au_nombre_de_seuils_distincts(self, calib: CalibrationService) -> None:
        points = [
            _point(0.1, False, node="n-1"),
            _point(0.1, True, node="n-2"),  # ex æquo avec le précédent : pas de doublon
            _point(0.5, True, node="n-3"),
            _point(0.9, False, node="n-4"),
        ]
        matrices = calib.sweep(points)
        assert [m.seuil for m in matrices] == [0.1, 0.5, 0.9]

    def test_seuils_fournis_reutilises_dans_l_ordre(self, calib: CalibrationService) -> None:
        points = TestConfusionSynthetique.POINTS
        matrices = calib.sweep(points, seuils=[0.9, 0.1])
        assert [m.seuil for m in matrices] == [0.9, 0.1]
        assert matrices[0] == calib.confusion(points, seuil=0.9)
        assert matrices[1] == calib.confusion(points, seuil=0.1)

    def test_points_sans_h_ignores_du_defaut(self, calib: CalibrationService) -> None:
        assert calib.sweep([_point(None, True)]) == []

    def test_liste_vide(self, calib: CalibrationService) -> None:
        assert calib.sweep([]) == []


# --- Seuil optimal (Youden / F1) ------------------------------------------------------------


class TestSeuilOptimal:
    def test_youden_sur_points_synthetiques_chiffre_a_la_main(
        self, calib: CalibrationService
    ) -> None:
        # Balayage à la main des 10 seuils distincts de TestConfusionSynthetique.POINTS :
        # l'indice de Youden (rappel + spécificité - 1) culmine à 0.667 pour
        # seuil=0.3 (rappel 4/4=1, spécificité 4/6=0.667).
        resultat = calib.seuil_optimal(TestConfusionSynthetique.POINTS, critere="youden")
        assert resultat is not None
        seuil, matrice = resultat
        assert seuil == pytest.approx(0.3)
        assert (matrice.vp, matrice.fp, matrice.fn, matrice.vn) == (4, 2, 0, 4)

    def test_f1_chiffre_a_la_main(self, calib: CalibrationService) -> None:
        # Seuils distincts [0.1, 0.3, 0.8, 0.9] : F1 vaut 0.8 (seuil 0.1),
        # 0.5 (seuil 0.3), 0.667 (seuil 0.8), indéfini (seuil 0.9, aucune
        # prédiction positive) -> maximum à seuil=0.1.
        points = [
            _point(0.9, True, node="n-1"),
            _point(0.8, False, node="n-2"),
            _point(0.3, True, node="n-3"),
            _point(0.1, False, node="n-4"),
        ]
        resultat = calib.seuil_optimal(points, critere="f1")
        assert resultat is not None
        seuil, matrice = resultat
        assert seuil == pytest.approx(0.1)
        assert (matrice.vp, matrice.fp, matrice.fn, matrice.vn) == (2, 1, 0, 1)

    def test_critere_invalide(self, calib: CalibrationService) -> None:
        with pytest.raises(ValueError, match="critère"):
            calib.seuil_optimal(TestConfusionSynthetique.POINTS, critere="n_importe_quoi")

    def test_youden_classe_unique_none(self, calib: CalibrationService) -> None:
        # Youden requiert rappel ET spécificité définis : classe unique, dans
        # un sens comme dans l'autre, laisse toujours l'un des deux indéfini.
        positifs_seuls = [_point(0.9, True, node="n-1"), _point(0.1, True, node="n-2")]
        negatifs_seuls = [_point(0.9, False, node="n-1"), _point(0.1, False, node="n-2")]
        assert calib.seuil_optimal(positifs_seuls, critere="youden") is None
        assert calib.seuil_optimal(negatifs_seuls, critere="youden") is None

    def test_f1_sans_positifs_none(self, calib: CalibrationService) -> None:
        # F1 requiert un rappel défini (donc au moins une issue défavorable) :
        # aucun positif -> indéfini à tous les seuils.
        negatifs_seuls = [_point(0.9, False, node="n-1"), _point(0.1, False, node="n-2")]
        assert calib.seuil_optimal(negatifs_seuls, critere="f1") is None

    def test_f1_defini_avec_positifs_seuls_youden_indefini(self, calib: CalibrationService) -> None:
        # Asymétrie documentée : contrairement à Youden, F1 ne requiert PAS
        # de négatifs (seulement rappel ET précision définis). Avec deux
        # positifs à H=0.9 et H=0.1, seul le seuil 0.1 laisse une prédiction
        # positive (H=0.9 strictement supérieur) -> vp=1, fn=1 (le point à
        # 0.1 n'est pas strictement > 0.1) ; précision=1, rappel=0.5,
        # F1=2*1*0.5/1.5=0.667. Le seuil 0.9 ne prédit plus rien de positif :
        # précision indéfinie, écarté.
        points = [_point(0.9, True, node="n-1"), _point(0.1, True, node="n-2")]
        assert calib.seuil_optimal(points, critere="youden") is None
        resultat_f1 = calib.seuil_optimal(points, critere="f1")
        assert resultat_f1 is not None
        seuil, matrice = resultat_f1
        assert seuil == pytest.approx(0.1)
        assert (matrice.vp, matrice.fp, matrice.fn, matrice.vn) == (1, 0, 1, 0)

    def test_liste_vide_none(self, calib: CalibrationService) -> None:
        assert calib.seuil_optimal([]) is None


# --- Outcomes sur une vraie partie ------------------------------------------------------


class TestOutcomesPartie:
    def test_points_des_semaines_passees_tries(
        self, partie: tuple[SupplyScoreService, Project, tuple[str, str, str]]
    ) -> None:
        service, projet, _ids = partie
        points = CalibrationService(service).outcomes(projet.id)

        # Les semaines passées S24..S28 existent ; la semaine courante S29 est
        # exclue, la semaine S23 (état sans H) est ignorée.
        assert {p.iso_week for p in points} == {f"2026-S{w}" for w in range(24, 29)}
        assert all(p.hidden_risk is not None for p in points)

        # Tri par (semaine, nom de nœud).
        cles = [(p.iso_week, p.node_name) for p in points]
        assert cles == sorted(cles)

    def test_jalon_rate_sur_le_bon_noeud(
        self, partie: tuple[SupplyScoreService, Project, tuple[str, str, str]]
    ) -> None:
        service, projet, (node_a, _b, _c) = partie
        points = CalibrationService(service).outcomes(projet.id)

        # (A, S24) : l'échéance S25 du jalon « Prototype » est dans la fenêtre
        # S25..S28 et le jalon est toujours ACTIVE — issue constatée.
        p24 = next(p for p in points if p.node_id == node_a and p.iso_week == "2026-S24")
        assert p24.issue_defavorable
        assert any("jalon" in cause and "Prototype" in cause for cause in p24.causes)

        # (A, S25) : fenêtre S26..S29, l'échéance S25 n'y est plus — pas d'issue.
        p25 = next(p for p in points if p.node_id == node_a and p.iso_week == "2026-S25")
        assert not p25.issue_defavorable
        assert p25.causes == []

    def test_evenement_critique_sur_le_bon_noeud(
        self, partie: tuple[SupplyScoreService, Project, tuple[str, str, str]]
    ) -> None:
        service, projet, (_a, node_b, _c) = partie
        points = CalibrationService(service).outcomes(projet.id)

        # L'événement critique de S26 tombe dans les fenêtres de S24 et S25.
        for semaine in ("2026-S24", "2026-S25"):
            point = next(p for p in points if p.node_id == node_b and p.iso_week == semaine)
            assert point.issue_defavorable
            assert any(
                "événement" in cause and "panne_machine" in cause and "critique" in cause
                for cause in point.causes
            )

        # Dès S26, la fenêtre S27..S30 ne contient plus l'événement.
        for semaine in ("2026-S26", "2026-S27", "2026-S28"):
            point = next(p for p in points if p.node_id == node_b and p.iso_week == semaine)
            assert not point.issue_defavorable

    def test_seuls_les_bons_points_sont_defavorables(
        self, partie: tuple[SupplyScoreService, Project, tuple[str, str, str]]
    ) -> None:
        service, projet, (node_a, node_b, _c) = partie
        points = CalibrationService(service).outcomes(projet.id)

        # Le pic de demande (sans gravité) et l'événement « defaut » ANNULÉ de
        # C ne comptent pas : seuls le jalon raté de A et la panne critique de
        # B produisent des issues.
        positifs = {(p.node_id, p.iso_week) for p in points if p.issue_defavorable}
        assert positifs == {
            (node_a, "2026-S24"),
            (node_b, "2026-S24"),
            (node_b, "2026-S25"),
        }

    def test_noeud_abandonne_compte_en_proxy(
        self, partie: tuple[SupplyScoreService, Project, tuple[str, str, str]]
    ) -> None:
        service, projet, (_a, _b, node_c) = partie
        # Jalon ABANDONNÉ avec échéance en S26 : compte dans les fenêtres de
        # S24 et S25 (critère (a), branche « abandonné »).
        service.registry.save_milestone(
            Milestone(
                id="m-abandonne",
                node_id=node_c,
                name="Qualification",
                start_ts=_NOW,
                deadline_ts=_NOW + 2.5 * _WEEK,
                status=MilestoneStatus.ABANDONED,
                progress=0.1,
                position=98,
            )
        )
        service.set_status(node_c, TaskStatus.ABANDONED)

        points = [p for p in CalibrationService(service).outcomes(projet.id) if p.node_id == node_c]
        assert points, "le nœud abandonné garde ses points d'observation"
        assert all(p.issue_defavorable for p in points)
        assert all(any("abandonné" in cause for cause in p.causes) for p in points)

        p24 = next(p for p in points if p.iso_week == "2026-S24")
        assert any("jalon" in cause and "Qualification" in cause for cause in p24.causes)
        assert any("statut" in cause and "proxy" in cause for cause in p24.causes)

    def test_horizon_invalide(self, calib: CalibrationService) -> None:
        with pytest.raises(ValueError, match="horizon_weeks"):
            calib.outcomes("p-quelconque", horizon_weeks=0)


# --- Résumé français ---------------------------------------------------------------------


class TestSummary:
    def test_projet_vide_division_par_zero_geree(
        self, service: SupplyScoreService, calib: CalibrationService
    ) -> None:
        service.registry.save_project(
            Project(id="p-vide", name="Vide", owner_node_id="n-0", created_at=_NOW, t0_ts=_NOW)
        )
        # Nœud SANS aucun historique d'urgence : aucun point d'observation.
        service.registry.save_node(SupplyNode(id="n-0", name="Sans histoire", project_id="p-vide"))
        texte = calib.summary("p-vide")
        assert "Points d'observation : 0." in texte
        assert "Précision : non définie (aucune prédiction positive)." in texte
        assert "Rappel : non défini (aucune issue défavorable observée)." in texte
        assert (
            "AUC (aire sous la courbe ROC) : non définie"
            " (classe unique ou aucun point exploitable)." in texte
        )
        assert "Score de Brier : non défini (aucun point exploitable)." in texte
        assert (
            "Seuil optimal (Youden) : non défini"
            " (classe unique ou aucun point exploitable)." in texte
        )
        assert "échantillon trop petit" in texte

    def test_resume_d_une_partie(
        self, partie: tuple[SupplyScoreService, Project, tuple[str, str, str]]
    ) -> None:
        service, projet, (_a, node_b, _c) = partie
        # Dernier état de la semaine S25 de B forcé à H = 0.9 : le point
        # (B, S25) — issue constatée — devient une prédiction positive, donc
        # précision ET rappel sont définis.
        service.client_db(node_b).save_urgency_state(
            node_b,
            UrgencyState(hidden_risk=0.9, ur=0.9, timestamp=_NOW + _WEEK + 3600.0),
        )
        calib = CalibrationService(service)
        points = calib.outcomes(projet.id)
        matrice = calib.confusion(points)
        assert matrice.vp >= 1

        texte = calib.summary(projet.id)
        assert f"Points d'observation : {len(points)}." in texte
        assert (
            f"Matrice de confusion : VP={matrice.vp}, FP={matrice.fp},"
            f" FN={matrice.fn}, VN={matrice.vn}." in texte
        )
        assert matrice.precision is not None and matrice.rappel is not None
        assert f"Précision : {matrice.precision:.2f}" in texte
        assert f"Rappel : {matrice.rappel:.2f}" in texte

        # La partie mélange nœuds à risque et nœuds calmes : les deux
        # classes sont représentées, AUC/Brier/seuil optimal sont définis.
        auc_valeur = calib.auc(points)
        assert auc_valeur is not None
        assert f"AUC : {auc_valeur:.2f}" in texte

        brier_resultat = calib.brier(points)
        assert brier_resultat is not None
        brier_score, skill = brier_resultat
        assert f"Score de Brier : {brier_score:.3f}" in texte
        assert f"skill score vs climatologie : {skill:.2f}" in texte

        seuil_opt = calib.seuil_optimal(points, critere="youden")
        assert seuil_opt is not None
        valeur_seuil, _matrice_opt = seuil_opt
        assert f"Seuil optimal (Youden) : H > {valeur_seuil:g}" in texte

        # L'avertissement suit STRICTEMENT la règle des 30 points.
        assert ("échantillon trop petit" in texte) == (len(points) < 30)


# --- Décalage de semaines ISO -------------------------------------------------------------


class TestSemaineDecalee:
    def test_bords_d_annee_iso_exacts(self) -> None:
        assert _semaine_decalee("2026-S24", 1) == "2026-S25"
        assert _semaine_decalee("2020-S53", 1) == "2021-S01"
        assert _semaine_decalee("2021-S01", -1) == "2020-S53"
        assert _semaine_decalee("2026-S24", 0) == "2026-S24"

    def test_libelle_invalide(self) -> None:
        with pytest.raises(ValueError, match="invalide"):
            _semaine_decalee("n-importe-quoi", 1)
