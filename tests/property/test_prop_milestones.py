"""Proprietes Hypothesis des jalons et de u_time v2 (E9 - Lot 9.5).

Couvre :mod:`supplyscore.domain.milestones` et le bloc temporel de
:class:`supplyscore.core.ur_model.UrModel` :

- :func:`derive_node_status` : table de verite PESSIMISTE (ACTIVE domine,
  sinon ABANDONED domine DONE, vide -> None) ;
- :func:`next_active_milestone` : minimum des jalons ACTIVE par deadline ;
- :func:`theoretical_progress` : bornes [0, 1], croissance en ``now_ts``,
  convention deadline <= start -> 1.0 ;
- u_time v2 : continuite au passage r = 0, decroissance en ``progress`` a t
  fixe, 1.0 exact apres la deadline du jalon actif.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core.ur_model import UrModel
from supplyscore.domain.milestones import (
    Milestone,
    MilestoneStatus,
    derive_node_status,
    next_active_milestone,
    theoretical_progress,
)
from supplyscore.domain.models import KPIBundle, TaskStatus, TimeKPIs

T0 = 1_700_000_000.0  # origine epoch arbitraire du projet
H = 3600.0  # secondes par heure

MODEL = UrModel()  # kappa_retard=0.5, kappa_avance=0.2 par defaut
KAPPA_SOMME = MODEL.kappa_retard + MODEL.kappa_avance

STATUTS = list(MilestoneStatus)


def make_milestone(
    status: MilestoneStatus = MilestoneStatus.ACTIVE,
    deadline_h: float = 0.0,
    start_h: float = 0.0,
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


def make_kpis() -> KPIBundle:
    """KPIs sans deadline_h : l'echeance vient du jalon (L ~ N(50, 10))."""
    return KPIBundle(time=TimeKPIs(lead_time_h=50.0, lead_time_std_h=10.0))


class TestDeriveNodeStatus:
    """Table de verite pessimiste sur des ensembles aleatoires de statuts."""

    @given(statuses=st.lists(st.sampled_from(STATUTS), max_size=8))
    def test_table_de_verite_pessimiste(self, statuses: list[MilestoneStatus]) -> None:
        milestones = [
            make_milestone(status=s, deadline_h=float(i), mid=f"m{i}")
            for i, s in enumerate(statuses)
        ]
        result = derive_node_status(milestones)
        if not statuses:
            assert result is None  # vide -> statut manuel conserve
        elif MilestoneStatus.ACTIVE in statuses:
            assert result is TaskStatus.ACTIVE  # la presence d'ACTIVE domine
        elif MilestoneStatus.ABANDONED in statuses:
            assert result is TaskStatus.ABANDONED  # sinon ABANDONED domine DONE
        else:
            assert result is TaskStatus.DONE


class TestNextActiveMilestone:
    """M* est le jalon ACTIVE de deadline minimale, None sans actif."""

    @given(
        entries=st.lists(
            st.tuples(
                st.sampled_from(STATUTS),
                st.floats(min_value=0.0, max_value=1e6),
            ),
            max_size=10,
        )
    )
    def test_min_des_actifs_par_deadline(
        self, entries: list[tuple[MilestoneStatus, float]]
    ) -> None:
        milestones = [
            make_milestone(status=s, deadline_h=d, mid=f"m{i}") for i, (s, d) in enumerate(entries)
        ]
        result = next_active_milestone(milestones)
        actives = [m for m in milestones if m.status is MilestoneStatus.ACTIVE]
        if not actives:
            assert result is None
        else:
            assert result is not None
            assert result.status is MilestoneStatus.ACTIVE
            assert result in actives
            assert result.deadline_ts == min(m.deadline_ts for m in actives)


class TestTheoreticalProgress:
    """Interpolation lineaire : bornes, croissance et fenetre degeneree."""

    @given(
        start_h=st.floats(min_value=-1e5, max_value=1e5),
        span_h=st.floats(min_value=1e-3, max_value=1e5),
        now_a=st.floats(min_value=-2e5, max_value=2e5),
        now_b=st.floats(min_value=-2e5, max_value=2e5),
    )
    def test_bornes_et_croissance_en_now_ts(
        self, start_h: float, span_h: float, now_a: float, now_b: float
    ) -> None:
        m = make_milestone(start_h=start_h, deadline_h=start_h + span_h)
        t_lo, t_hi = sorted((now_a, now_b))
        p_lo = theoretical_progress(m, T0 + t_lo * H)
        p_hi = theoretical_progress(m, T0 + t_hi * H)
        assert 0.0 <= p_lo <= 1.0
        assert 0.0 <= p_hi <= 1.0
        assert p_lo <= p_hi  # croissante en now_ts

    @given(
        start_h=st.floats(min_value=-1e5, max_value=1e5),
        recul_h=st.floats(min_value=0.0, max_value=1e5),
        now_h=st.floats(min_value=-2e5, max_value=2e5),
    )
    def test_deadline_avant_start_vaut_1(
        self, start_h: float, recul_h: float, now_h: float
    ) -> None:
        # Fenetre degeneree ou inversee : le jalon aurait deja du etre termine.
        m = make_milestone(start_h=start_h, deadline_h=start_h - recul_h)
        assert theoretical_progress(m, T0 + now_h * H) == 1.0


class TestUTimeV2:
    """Modulation planning : continuite, decroissance et retard avere."""

    @given(
        d=st.floats(min_value=1.0, max_value=1000.0),
        t_frac=st.floats(min_value=0.0, max_value=1.0),
        eps=st.floats(min_value=1e-6, max_value=0.5),
    )
    def test_continuite_au_passage_r_zero(self, d: float, t_frac: float, eps: float) -> None:
        # progress == p_th +/- epsilon : la MODULATION PLANNING contribue au plus (kappar + kappaa)-epsilon au saut de u_time. Le socle depend lui aussi de progress depuis qu'il porte sur le travail restant (u_base_jalon), et sa pente n'est PAS bornee uniformement : elle diverge quand progress -> 1 (l'ecart-type du travail restant tend vers 0). On borne donc le saut total par " saut du socle + (kappar + kappaa)-epsilon " - exact, puisque u_time = clip01(u_base + ajustement) et que clip01 est 1-lipschitzienne. La contrainte GLOBALE sur progress est la decroissance, testee ci-dessous.
        t = t_frac * (d - 1e-3)
        p_th = theoretical_progress(make_milestone(deadline_h=d), T0 + t * H)
        p_moins = max(p_th - eps, 0.0)
        p_plus = min(p_th + eps, 1.0)
        kpis = make_kpis()
        u_moins = MODEL.u_time(
            t, kpis, milestones=[make_milestone(deadline_h=d, progress=p_moins)], t0_ts=T0
        )
        u_plus = MODEL.u_time(
            t, kpis, milestones=[make_milestone(deadline_h=d, progress=p_plus)], t0_ts=T0
        )
        assert u_moins is not None
        assert u_plus is not None
        saut_socle = abs(
            MODEL.u_base_jalon(d - t, kpis.time, p_plus)
            - MODEL.u_base_jalon(d - t, kpis.time, p_moins)
        )
        assert abs(u_plus - u_moins) <= saut_socle + KAPPA_SOMME * eps + 1e-9

    @given(
        d=st.floats(min_value=1.0, max_value=1000.0),
        t_frac=st.floats(min_value=0.0, max_value=1.0),
        prog_a=st.floats(min_value=0.0, max_value=1.0),
        prog_b=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_decroissante_en_progress_a_t_fixe(
        self, d: float, t_frac: float, prog_a: float, prog_b: float
    ) -> None:
        # Plus le jalon est avance, moins le noeud est urgent (a t fixe).
        t = t_frac * (d - 1e-3)
        p_lo, p_hi = sorted((prog_a, prog_b))
        u_lo = MODEL.u_time(
            t, make_kpis(), milestones=[make_milestone(deadline_h=d, progress=p_lo)], t0_ts=T0
        )
        u_hi = MODEL.u_time(
            t, make_kpis(), milestones=[make_milestone(deadline_h=d, progress=p_hi)], t0_ts=T0
        )
        assert u_lo is not None
        assert u_hi is not None
        assert u_hi <= u_lo + 1e-12

    @given(
        d=st.floats(min_value=1.0, max_value=1000.0),
        delta=st.floats(min_value=1e-3, max_value=1e4),
        progress=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_retard_avere_vaut_1_exactement(self, d: float, delta: float, progress: float) -> None:
        # t > deadline du jalon actif : retard avere, u_time == 1.0 EXACTEMENT.
        m = make_milestone(deadline_h=d, progress=progress)
        assert MODEL.u_time(d + delta, make_kpis(), milestones=[m], t0_ts=T0) == 1.0
