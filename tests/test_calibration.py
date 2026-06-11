"""Tests du Lot 11.1 : CalibrationService — le score H a-t-il prédit les ruptures ?

Couvre : le cas synthétique chiffré à la main (VP=3, FP=1, FN=1, VN=5,
précision=rappel=0.75), la courbe de calibration sur 2 tranches connues
(moyennes/taux/effectifs exacts, tranches vides omises), les outcomes d'une
vraie partie (FixedClock + seed_demo + GameClock : jalon raté, événement
critique, événement annulé ignoré, H None ignorés, nœud abandonné en proxy),
le résumé français (avertissement « échantillon trop petit », précision/rappel
non définis) et les propriétés None de ConfusionMatrix sur dénominateurs nuls.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

import supplyscore.graph.propagation as propagation_mod
from supplyscore.core.clock import FixedClock
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import Project, SupplyNode, TaskStatus, UrgencyState
from supplyscore.services import SupplyScoreService
from supplyscore.services.calibration import (
    CalibrationService,
    ConfusionMatrix,
    OutcomePoint,
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
    service: SupplyScoreService, monkeypatch: pytest.MonkeyPatch
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
    # La propagation horodate les états d'urgence avec ``time.time()`` (horloge
    # murale), même en mode jeu — limite connue du moteur, hors périmètre du
    # lot 11.1. Pour une partie DÉTERMINISTE, on fait suivre à ces horodatages
    # l'horloge effective du projet (FixedClock puis GameClock).
    project_ref: dict[str, str] = {}

    def _now_projet() -> float:
        pid = project_ref.get("id")
        return (service.clock_for(pid) if pid else service.clock).now()

    monkeypatch.setattr(propagation_mod, "time", SimpleNamespace(time=_now_projet))

    projet = service.seed_demo(n_ranks=2, seed=1)
    project_ref["id"] = projet.id
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
