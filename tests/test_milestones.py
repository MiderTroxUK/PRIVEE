"""Tests des jalons : next_active_milestone, theoretical_progress, derive_node_status."""

from itertools import permutations

import pytest

from supplyscore.domain.milestones import (
    Milestone,
    MilestoneStatus,
    derive_node_status,
    next_active_milestone,
    theoretical_progress,
)
from supplyscore.domain.models import TaskStatus

T0 = 1_700_000_000.0  # origine epoch arbitraire
H = 3600.0  # secondes par heure


def make_milestone(
    deadline_h: float,
    start_h: float = 0.0,
    status: MilestoneStatus = MilestoneStatus.ACTIVE,
    progress: float = 0.0,
    mid: str = "m1",
) -> Milestone:
    """Jalon de test ancre sur T0, echeances exprimees en heures."""
    return Milestone(
        id=mid,
        node_id="n1",
        name=f"Jalon {mid}",
        start_ts=T0 + start_h * H,
        deadline_ts=T0 + deadline_h * H,
        status=status,
        progress=progress,
    )


class TestDeriveNodeStatus:
    """Table de verite du statut derive des jalons."""

    def test_liste_vide_statut_manuel_conserve(self):
        assert derive_node_status([]) is None

    def test_au_moins_un_actif_actif(self):
        actif = make_milestone(10.0, status=MilestoneStatus.ACTIVE, mid="a")
        done = make_milestone(5.0, status=MilestoneStatus.DONE, mid="d")
        abandoned = make_milestone(8.0, status=MilestoneStatus.ABANDONED, mid="x")
        for combo in permutations([actif, done, abandoned]):
            assert derive_node_status(list(combo)) is TaskStatus.ACTIVE
        assert derive_node_status([actif]) is TaskStatus.ACTIVE

    def test_tous_done_done(self):
        done = make_milestone(5.0, status=MilestoneStatus.DONE, mid="d")
        done2 = make_milestone(8.0, status=MilestoneStatus.DONE, mid="d2")
        assert derive_node_status([done]) is TaskStatus.DONE
        assert derive_node_status([done, done2]) is TaskStatus.DONE

    def test_mix_done_abandonne_est_abandonne(self):
        """Regle PESSIMISTE : un jalon abandonne teinte le noeud (risque maximal aval)."""
        done = make_milestone(5.0, status=MilestoneStatus.DONE, mid="d")
        abandoned = make_milestone(8.0, status=MilestoneStatus.ABANDONED, mid="x")
        for combo in permutations([done, abandoned]):
            assert derive_node_status(list(combo)) is TaskStatus.ABANDONED

    def test_tous_abandonnes_abandoned(self):
        a1 = make_milestone(5.0, status=MilestoneStatus.ABANDONED, mid="x1")
        a2 = make_milestone(8.0, status=MilestoneStatus.ABANDONED, mid="x2")
        assert derive_node_status([a1]) is TaskStatus.ABANDONED
        assert derive_node_status([a1, a2]) is TaskStatus.ABANDONED


class TestNextActiveMilestone:
    """Selection du prochain jalon actif (deadline minimale)."""

    def test_liste_vide(self):
        assert next_active_milestone([]) is None

    def test_aucun_actif(self):
        done = make_milestone(5.0, status=MilestoneStatus.DONE, mid="d")
        abandoned = make_milestone(8.0, status=MilestoneStatus.ABANDONED, mid="x")
        assert next_active_milestone([done, abandoned]) is None

    def test_tri_par_deadline_minimale(self):
        tardif = make_milestone(200.0, mid="tardif")
        proche = make_milestone(50.0, mid="proche")
        moyen = make_milestone(100.0, mid="moyen")
        assert next_active_milestone([tardif, proche, moyen]) is proche
        # L'ordre de la liste n'influe pas.
        assert next_active_milestone([moyen, tardif, proche]) is proche

    def test_ignore_done_et_abandoned(self):
        done_proche = make_milestone(10.0, status=MilestoneStatus.DONE, mid="d")
        abandonne_proche = make_milestone(20.0, status=MilestoneStatus.ABANDONED, mid="x")
        actif_tardif = make_milestone(200.0, mid="a")
        assert next_active_milestone([done_proche, abandonne_proche, actif_tardif]) is actif_tardif


class TestTheoreticalProgress:
    """Avancement theorique lineaire entre start_ts et deadline_ts."""

    def test_avant_start(self):
        m = make_milestone(100.0, start_h=10.0)
        assert theoretical_progress(m, T0) == 0.0
        assert theoretical_progress(m, T0 + 5.0 * H) == 0.0

    def test_apres_deadline(self):
        m = make_milestone(100.0)
        assert theoretical_progress(m, T0 + 150.0 * H) == 1.0

    def test_a_40_pour_cent_du_chemin(self):
        m = make_milestone(100.0)
        assert theoretical_progress(m, T0 + 40.0 * H) == pytest.approx(0.4)

    def test_interpolation_avec_start_decale(self):
        m = make_milestone(110.0, start_h=10.0)
        assert theoretical_progress(m, T0 + 50.0 * H) == pytest.approx(0.4)

    def test_convention_deadline_avant_start(self):
        # Fenetre degeneree (deadline == start) -> 1.0.
        m = make_milestone(10.0, start_h=10.0)
        assert theoretical_progress(m, T0) == 1.0
        # Fenetre inversee (deadline < start) -> 1.0.
        m = make_milestone(5.0, start_h=10.0)
        assert theoretical_progress(m, T0 + 100.0 * H) == 1.0
