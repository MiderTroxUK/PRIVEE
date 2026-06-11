"""Tests du Lot 6.2 : WeeklyReview — revue hebdomadaire guidée en quatre volets.

Couvre : le diff KPI semaine à semaine (previous = fin de semaine précédente
via ``kpis_at``, current = valeur courante, KPI jamais renseigné → None),
``confirm_block`` (aucune écriture KPI, ligne d'audit ``__confirmed__``),
``confirm_milestone`` (audit milestone, statut done → jalon DONE), la
progression ``start``/``mark_volet``/``complete`` (started_at posé une seule
fois, completed_at = horloge du PROJET, ValueError français si incomplet,
volet inconnu) et l'horloge de jeu (GameClock).
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.data.audit import AuditTrail
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import Project, SupplyNode
from supplyscore.services import SupplyScoreService
from supplyscore.services.weekly import VOLETS, WeeklyReview

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    project = Project(
        id="p1",
        name="Projet",
        owner_node_id="n-a",
        created_at=_NOW - 5 * _WEEK,
        t0_ts=_NOW - 5 * _WEEK,
    )
    nodes = [
        SupplyNode(id="n-a", name="n-a", project_id="p1", rank=0),
        SupplyNode(id="n-b", name="n-b", project_id="p1", rank=1),
    ]
    svc.create_project(project, nodes, [])
    yield svc
    svc.close()


@pytest.fixture
def review(service: SupplyScoreService) -> WeeklyReview:
    return WeeklyReview(service)


# --- week_of -------------------------------------------------------------------------


class TestWeekOf:
    def test_semaine_courante_du_projet(self, review: WeeklyReview) -> None:
        assert review.week_of("n-a") == iso_week(_NOW) == "2026-S24"

    def test_mode_jeu_suit_l_horloge_du_projet(
        self, service: SupplyScoreService, review: WeeklyReview
    ) -> None:
        service.set_clock_mode("p1", "game")
        service.advance_week("p1", 2)
        assert review.week_of("n-a") == iso_week(_NOW + 2 * _WEEK) == "2026-S26"

    def test_noeud_inconnu_leve_value_error(self, review: WeeklyReview) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            review.week_of("fantome")


# --- kpi_diff ------------------------------------------------------------------------


class TestKpiDiff:
    def test_previous_fin_de_semaine_precedente_et_current_courant(
        self, service: SupplyScoreService, review: WeeklyReview, fixed_clock: FixedClock
    ) -> None:
        # Semaine S−1 : deux KPIs posés (le snapshot date de la semaine passée).
        fixed_clock.set(_NOW - _WEEK)
        service.mutations.update_kpis(
            "n-a", {"time.lead_time_h": 10.0, "risk.severity": 0.4}, source="edit"
        )
        # Semaine S : un seul KPI modifié cette semaine.
        fixed_clock.set(_NOW)
        service.mutations.update_kpis("n-a", {"time.lead_time_h": 12.0}, source="edit")

        rows = {row.path: row for row in review.kpi_diff("n-a")}

        lead = rows["time.lead_time_h"]
        assert lead.previous == 10.0  # valeur de fin de semaine S−1
        assert lead.current == 12.0  # valeur courante du nœud
        assert lead.label_fr == "Lead time (h)"
        assert lead.unit == "h"

        # KPI posé en S−1 et intact depuis : previous == current.
        severite = rows["risk.severity"]
        assert severite.previous == 0.4
        assert severite.current == 0.4

        # KPI jamais renseigné : previous None (et current None).
        jamais = rows["oee.availability"]
        assert jamais.previous is None
        assert jamais.current is None
        assert jamais.unit == "ratio"

    def test_aucun_snapshot_avant_la_semaine_donne_previous_none(
        self, service: SupplyScoreService, review: WeeklyReview
    ) -> None:
        # Première saisie CETTE semaine : pas d'historique de fin de semaine S−1.
        service.mutations.update_kpis("n-a", {"time.lead_time_h": 8.0}, source="edit")
        rows = {row.path: row for row in review.kpi_diff("n-a")}
        assert rows["time.lead_time_h"].previous is None
        assert rows["time.lead_time_h"].current == 8.0

    def test_couvre_tous_les_champs_de_kpi_fields_dans_l_ordre(self, review: WeeklyReview) -> None:
        from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS

        attendu = [path for _bloc, fields in KPI_FIELDS for path, _label in fields]
        assert [row.path for row in review.kpi_diff("n-a")] == attendu


# --- confirm_block -------------------------------------------------------------------


class TestConfirmBlock:
    def test_aucune_ecriture_kpi_une_ligne_d_audit(
        self, service: SupplyScoreService, review: WeeklyReview
    ) -> None:
        service.mutations.update_kpis("n-a", {"time.lead_time_h": 10.0}, source="edit")
        node_avant = service.registry.get_node("n-a")
        assert node_avant is not None
        bundle_avant = copy.deepcopy(node_avant.kpis)
        db = service.client_db("n-a")
        with db.lock:
            snapshots_avant = db.conn.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()[0]

        review.confirm_block("n-a", "time", operator_id="op-1")

        # Le bundle KPI est inchangé et AUCUN snapshot n'a été ajouté.
        node_apres = service.registry.get_node("n-a")
        assert node_apres is not None
        assert node_apres.kpis == bundle_avant
        with db.lock:
            snapshots_apres = db.conn.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()[0]
        assert snapshots_apres == snapshots_avant

        # Une ligne d'audit __confirmed__ dans la base CLIENT du nœud.
        trail = AuditTrail(db.conn, FixedClock(_NOW), lock=db.lock)
        entries = trail.history("node_kpis", "n-a", field="__confirmed__")
        assert len(entries) == 1
        entry = entries[0]
        assert entry.entity_type == "node_kpis"
        assert entry.entity_id == "n-a"
        assert entry.old_value is None
        assert entry.new_value == "time"
        assert entry.source == "weekly"
        assert entry.operator_id == "op-1"
        assert entry.iso_week == "2026-S24"
        assert entry.timestamp == _NOW


# --- confirm_milestone ---------------------------------------------------------------


class TestConfirmMilestone:
    def _jalon(self, service: SupplyScoreService, milestone_id: str, progress: float) -> Milestone:
        m = Milestone(
            id=milestone_id,
            node_id="n-a",
            name="Proto",
            start_ts=_NOW - _WEEK,
            deadline_ts=_NOW + 4 * _WEEK,
            progress=progress,
        )
        service.registry.save_milestone(m)
        return m

    def test_progress_modifie_est_audite(
        self, service: SupplyScoreService, review: WeeklyReview
    ) -> None:
        self._jalon(service, "m1", 0.3)

        review.confirm_milestone("m1", "active", 0.7, operator_id="op-1")

        maj = service.registry.get_milestone("m1")
        assert maj is not None
        assert maj.progress == 0.7
        assert maj.status is MilestoneStatus.ACTIVE

        trail = AuditTrail(service.registry.conn, FixedClock(_NOW), lock=service.registry.lock)
        entries = trail.history("milestone", "m1", field="progress")
        assert len(entries) == 1
        assert entries[0].old_value == 0.3
        assert entries[0].new_value == 0.7
        assert entries[0].source == "weekly"
        assert entries[0].operator_id == "op-1"
        # Le statut, inchangé, n'a pas été audité (seuls les champs modifiés).
        assert trail.history("milestone", "m1", field="status") == []

    def test_statut_done_termine_le_jalon(
        self, service: SupplyScoreService, review: WeeklyReview
    ) -> None:
        self._jalon(service, "m2", 0.7)

        review.confirm_milestone("m2", "done", 1.0)

        maj = service.registry.get_milestone("m2")
        assert maj is not None
        assert maj.status is MilestoneStatus.DONE
        assert maj.progress == 1.0


# --- start / mark_volet / review_status / complete -----------------------------------


class TestProgressionRevue:
    def test_mark_volet_x4_puis_complete(
        self, review: WeeklyReview, fixed_clock: FixedClock
    ) -> None:
        for volet in VOLETS:
            statut = review.mark_volet("n-a", volet, operator_id="op-1")
        assert statut["done"] == 4
        assert statut["completed_at"] is None

        final = review.complete("n-a")
        assert final["volets"] == {"ahp": 1, "kpis": 1, "jalons": 1, "evenements": 1}
        assert final["done"] == 4
        assert final["total"] == 4
        assert final["started_at"] == _NOW
        assert final["completed_at"] == _NOW  # epoch de l'horloge du projet

    def test_complete_avant_les_4_volets_leve_value_error_francais(
        self, review: WeeklyReview
    ) -> None:
        review.mark_volet("n-a", "ahp")
        review.mark_volet("n-a", "kpis")
        with pytest.raises(ValueError, match="volets restants : jalons, evenements"):
            review.complete("n-a")
        assert review.review_status("n-a")["completed_at"] is None

    def test_mark_volet_pose_started_at_une_seule_fois(
        self, review: WeeklyReview, fixed_clock: FixedClock
    ) -> None:
        review.mark_volet("n-a", "ahp")
        fixed_clock.set(_NOW + 3600.0)  # une heure plus tard, même semaine
        statut = review.mark_volet("n-a", "kpis")
        assert statut["started_at"] == _NOW  # le premier appel fait foi

    def test_review_status_coherent(self, review: WeeklyReview) -> None:
        vierge = review.review_status("n-a")
        assert vierge == {
            "volets": {"ahp": 0, "kpis": 0, "jalons": 0, "evenements": 0},
            "done": 0,
            "total": 4,
            "started_at": None,
            "completed_at": None,
        }

        review.mark_volet("n-a", "jalons")
        statut = review.review_status("n-a")
        assert statut["volets"] == {"ahp": 0, "kpis": 0, "jalons": 1, "evenements": 0}
        assert statut["done"] == 1
        assert statut["total"] == 4

    def test_volet_inconnu_leve_value_error(self, review: WeeklyReview) -> None:
        with pytest.raises(ValueError, match="volet inconnu"):
            review.mark_volet("n-a", "meteo")
        # Rien n'a été écrit pour la semaine.
        assert review.review_status("n-a")["done"] == 0

    def test_start_idempotent(self, review: WeeklyReview, fixed_clock: FixedClock) -> None:
        review.start("n-a")
        assert review.review_status("n-a")["started_at"] == _NOW
        fixed_clock.set(_NOW + 3600.0)
        review.start("n-a")  # ne réécrase pas started_at
        assert review.review_status("n-a")["started_at"] == _NOW

    def test_noeuds_independants(self, review: WeeklyReview) -> None:
        review.mark_volet("n-a", "ahp")
        assert review.review_status("n-a")["done"] == 1
        assert review.review_status("n-b")["done"] == 0


# --- Horloge du PROJET : mode jeu ----------------------------------------------------


class TestHorlogeJeu:
    def test_revue_en_mode_jeu_suit_la_semaine_simulee(
        self, service: SupplyScoreService, review: WeeklyReview
    ) -> None:
        review.mark_volet("n-a", "ahp")  # revue de la semaine réelle S24

        service.set_clock_mode("p1", "game")
        service.advance_week("p1", 1)  # semaine simulée S25

        # La revue de S25 repart de zéro.
        assert review.review_status("n-a")["done"] == 0

        for volet in VOLETS:
            review.mark_volet("n-a", volet)
        final = review.complete("n-a")
        # completed_at = epoch de l'horloge du PROJET (GameClock).
        assert final["completed_at"] == _NOW + _WEEK
        assert review.week_of("n-a") == iso_week(_NOW + _WEEK) == "2026-S25"
