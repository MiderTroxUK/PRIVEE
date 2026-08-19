"""Tests du moteur d'explicabilite (E8, Lot 8.1) - cas chiffres et invariants."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core import explain as explain_mod
from supplyscore.core.adequation import AdequationEngine
from supplyscore.core.ahp import CRITERIA, compute_ud
from supplyscore.core.explain import (
    explain_adequation,
    explain_propagation_down,
    explain_propagation_up,
    explain_u_time,
    explain_ud,
    explain_ur_local,
)
from supplyscore.core.ur_model import BLOCKS, UrModel
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import (
    ArcKind,
    CO2KPIs,
    CostKPIs,
    InventoryKPIs,
    KPIBundle,
    NetworkKPIs,
    OEEKPIs,
    RiskKPIs,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    TimeKPIs,
    UrgencyState,
)
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine

T0 = 1_700_000_000.0  # origine epoch arbitraire du projet
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


def rebuilt_ur(contributions) -> float:
    """Reconstruction 1 - exp(-somme des log-survies) depuis les contributions."""
    total = 0.0
    for c in contributions:
        if c.u is not None and c.omega > 0.0:
            total += explain_mod._log_survival(c.u, c.omega)
    return 1.0 - math.exp(-total)


# Ud (AHP)


class TestExplainUd:
    W = np.array([0.4, 0.3, 0.2, 0.1])
    S = np.array([9.0, 5.0, 1.0, 3.0])

    def test_cas_chiffre_contributions(self):
        contribs = explain_ud(self.W, self.S)
        attendu = [0.400, 0.150, 0.000, 0.025]
        assert [c.contribution for c in contribs] == pytest.approx(attendu, abs=1e-12)

    def test_somme_egale_ud_exactement(self):
        contribs = explain_ud(self.W, self.S)
        total = sum(c.contribution for c in contribs)
        assert total == pytest.approx(0.575, abs=1e-12)
        # Et coincide avec le Ud du pipeline (meme appel compute_ud).
        assert total == pytest.approx(compute_ud(self.W, self.S), abs=1e-12)

    def test_labels_et_indices(self):
        contribs = explain_ud(self.W, self.S)
        assert [c.label for c in contribs] == CRITERIA
        assert [c.index for c in contribs] == [0, 1, 2, 3]
        assert [c.score for c in contribs] == pytest.approx([9.0, 5.0, 1.0, 3.0])

    def test_poids_normalises(self):
        contribs = explain_ud(np.array([4.0, 3.0, 2.0, 1.0]), self.S)
        assert sum(c.weight for c in contribs) == pytest.approx(1.0, abs=1e-12)
        assert [c.weight for c in contribs] == pytest.approx([0.4, 0.3, 0.2, 0.1], abs=1e-12)

    def test_note_hors_bornes_rejetee(self):
        with pytest.raises(ValueError):
            explain_ud(self.W, np.array([9.0, 5.0, 0.5, 3.0]))


# Ur_local (blocs KPI)


def kpis_time_risk_05() -> KPIBundle:
    """KPIs donnant exactement u_time = 0.5 et u_risk = 0.5, autres blocs None.

    - time : t = 0, slack = deadline = 50 h = lead time moyen -> P(L > 50) = 0.5
      (fonction de survie normale en sa moyenne, erf(0) = 0) ;
    - risk : fp = ln 2, t_recup = 24 h = T_ref, sev = 1 -> base = 1 - exp(-ln 2) = 0.5.
    """
    return KPIBundle(
        time=TimeKPIs(deadline_h=50.0, lead_time_h=50.0, lead_time_std_h=10.0),
        risk=RiskKPIs(failure_probability=math.log(2.0), recovery_time_h=24.0, severity=1.0),
    )


def kpis_risk09_perf01() -> KPIBundle:
    """KPIs donnant u_risk = 0.9 et u_perf = 0.1, autres blocs None.

    - risk : fp = 1, t_recup = 24-ln 10, sev = 1 -> base = 1 - exp(-ln 10) = 0.9 ;
    - perf : OEE = 0.9-1-1 -> u_perf = 1 - 0.9 = 0.1.
    """
    return KPIBundle(
        risk=RiskKPIs(failure_probability=1.0, recovery_time_h=24.0 * math.log(10.0), severity=1.0),
        oee=OEEKPIs(availability=0.9, performance=1.0, quality=1.0),
    )


class TestExplainUrLocal:
    def test_deux_blocs_05_05(self):
        model = UrModel()
        contribs = explain_ur_local(0.0, kpis_time_risk_05(), None, model)
        par_bloc = {c.block: c for c in contribs}
        assert [c.block for c in contribs] == list(BLOCKS)

        assert par_bloc["time"].u == pytest.approx(0.5, abs=1e-9)
        assert par_bloc["risk"].u == pytest.approx(0.5, abs=1e-9)
        # Ur = 1 - 0.5-0.5 = 0.75 ; parts egales ; delta chacun 0.25.
        assert model.ur_local(0.0, kpis_time_risk_05()) == pytest.approx(0.75, abs=1e-9)
        assert par_bloc["time"].share == pytest.approx(0.5, abs=1e-9)
        assert par_bloc["risk"].share == pytest.approx(0.5, abs=1e-9)
        assert par_bloc["time"].delta_without == pytest.approx(0.25, abs=1e-9)
        assert par_bloc["risk"].delta_without == pytest.approx(0.25, abs=1e-9)
        # Blocs inactifs : u None, share 0, delta 0.
        for name in ("cap", "perf", "cost", "co2"):
            assert par_bloc[name].u is None
            assert par_bloc[name].share == 0.0
            assert par_bloc[name].delta_without == 0.0

    def test_delta_without_non_additif(self):
        # Somme des deltas = 0.5 != Ur = 0.75 : la marginale n'est PAS additive.
        contribs = explain_ur_local(0.0, kpis_time_risk_05(), None, UrModel())
        somme_deltas = sum(c.delta_without for c in contribs)
        assert somme_deltas == pytest.approx(0.5, abs=1e-6)
        assert somme_deltas != pytest.approx(0.75, abs=1e-3)

    def test_blocs_09_01(self):
        model = UrModel()
        kpis = kpis_risk09_perf01()
        contribs = explain_ur_local(0.0, kpis, None, model)
        par_bloc = {c.block: c for c in contribs}

        assert par_bloc["risk"].u == pytest.approx(0.9, abs=1e-9)
        assert par_bloc["perf"].u == pytest.approx(0.1, abs=1e-9)
        # l = (-ln 0.1, -ln 0.9) = (2.302585, 0.105361).
        l_risk = explain_mod._log_survival(par_bloc["risk"].u, par_bloc["risk"].omega)
        l_perf = explain_mod._log_survival(par_bloc["perf"].u, par_bloc["perf"].omega)
        assert l_risk == pytest.approx(2.302585, abs=1e-3)
        assert l_perf == pytest.approx(0.105361, abs=1e-3)
        assert par_bloc["risk"].share == pytest.approx(0.9562, abs=1e-3)
        assert par_bloc["perf"].share == pytest.approx(0.0438, abs=1e-3)
        assert model.ur_local(0.0, kpis) == pytest.approx(0.91, abs=1e-3)

    def test_reconstruction_1e_12(self):
        model = UrModel()
        for kpis in (kpis_time_risk_05(), kpis_risk09_perf01()):
            contribs = explain_ur_local(0.0, kpis, None, model)
            assert rebuilt_ur(contribs) == pytest.approx(model.ur_local(0.0, kpis), abs=1e-12)

    def test_somme_shares_egale_1(self):
        contribs = explain_ur_local(0.0, kpis_time_risk_05(), None, UrModel())
        assert sum(c.share for c in contribs) == pytest.approx(1.0, abs=1e-9)

    def test_aucun_bloc_actif_shares_nulles(self):
        contribs = explain_ur_local(0.0, KPIBundle(), None, UrModel())
        assert all(c.u is None for c in contribs)
        assert all(c.share == 0.0 for c in contribs)
        assert all(c.delta_without == 0.0 for c in contribs)

    def test_omega_zero_bloc_inactif(self):
        # omega[risk] = 0 : le bloc risk est exclu, time porte tout.
        model = UrModel(omega={name: (0.0 if name == "risk" else 1.0) for name in BLOCKS})
        contribs = explain_ur_local(0.0, kpis_time_risk_05(), None, model)
        par_bloc = {c.block: c for c in contribs}
        assert par_bloc["risk"].share == 0.0
        assert par_bloc["risk"].delta_without == 0.0
        assert par_bloc["time"].share == pytest.approx(1.0, abs=1e-9)
        assert par_bloc["time"].delta_without == pytest.approx(0.5, abs=1e-9)


class TestSaturation:
    def kpis_time_sature(self) -> KPIBundle:
        """t > deadline -> u_time = 1.0 exactement ; u_perf = 0.3 en second bloc."""
        return KPIBundle(
            time=TimeKPIs(deadline_h=10.0, lead_time_h=5.0),
            oee=OEEKPIs(availability=0.7, performance=1.0, quality=1.0),
        )

    def test_bloc_sature_part_1(self):
        model = UrModel()
        contribs = explain_ur_local(20.0, self.kpis_time_sature(), None, model)
        par_bloc = {c.block: c for c in contribs}
        assert par_bloc["time"].u == 1.0
        assert par_bloc["time"].share == 1.0
        assert par_bloc["perf"].share == 0.0
        # delta : sans time, Ur = u_perf = 0.3 -> delta = 1.0 - 0.3 = 0.7.
        assert par_bloc["time"].delta_without == pytest.approx(0.7, abs=1e-9)
        assert par_bloc["perf"].delta_without == pytest.approx(0.0, abs=1e-9)
        # Aucun NaN/Inf dans les champs exposes.
        for c in contribs:
            assert math.isfinite(c.share)
            assert math.isfinite(c.delta_without)
            if c.u is not None:
                assert math.isfinite(c.u)
        # Reconstruction : somme des l = inf -> 1 - exp(-inf) = 1.0 == ur_local.
        assert rebuilt_ur(contribs) == 1.0
        assert model.ur_local(20.0, self.kpis_time_sature()) == 1.0

    def test_deux_blocs_satures_parts_egales(self):
        kpis = KPIBundle(
            time=TimeKPIs(deadline_h=10.0, lead_time_h=5.0),
            risk=RiskKPIs(failure_probability=1.0, recovery_time_h=1e9, severity=1.0),
        )
        contribs = explain_ur_local(20.0, kpis, None, UrModel())
        par_bloc = {c.block: c for c in contribs}
        assert par_bloc["time"].share == pytest.approx(0.5, abs=1e-12)
        assert par_bloc["risk"].share == pytest.approx(0.5, abs=1e-12)
        assert sum(c.share for c in contribs) == pytest.approx(1.0, abs=1e-9)


# u_time (trace planning)


class TestExplainUTime:
    @pytest.fixture
    def model(self) -> UrModel:
        return UrModel()  # kappa_retard = 0.5, kappa_avance = 0.2

    @pytest.fixture
    def kpis(self) -> KPIBundle:
        return KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0))

    def test_cas_chiffre_v2(self, model, kpis):
        # d* = 100 h, lead 100/std 20, t = 40, progress = 0.25. Socle sur travail restant : reste = 0.75 -> L_restant ~ N(75, 17.32) (sigma en RACINE du reste), marge 60 -> z = -0.866 -> u_base = 0.806762 ; r = 0.15.
        m = make_milestone(100.0, progress=0.25)
        trace = explain_u_time(40.0, kpis, [m], model, t0_ts=T0)
        assert trace.u_base == pytest.approx(0.806762, abs=1e-4)
        assert trace.p_th == pytest.approx(0.4, abs=1e-12)
        assert trace.progress == pytest.approx(0.25, abs=1e-12)
        assert trace.planning_adjust == pytest.approx(0.075, abs=1e-12)
        assert trace.final == pytest.approx(0.881762, abs=1e-4)
        # final == pipeline (meme appel) et == clip01(u_base + adjust).
        assert trace.final == model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        reconstruit = min(max(trace.u_base + trace.planning_adjust, 0.0), 1.0)
        assert trace.final == pytest.approx(reconstruit, abs=1e-12)

    def test_avance_bonus_negatif(self, model, kpis):
        # progress = 0.9 -> r = -0.5 -> adjust = -0.2-0.5 = -0.1.
        m = make_milestone(100.0, progress=0.9)
        trace = explain_u_time(40.0, kpis, [m], model, t0_ts=T0)
        assert trace.planning_adjust == pytest.approx(-0.1, abs=1e-12)
        assert trace.final == model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)

    def test_retard_avere_cause_unique(self, model, kpis):
        m = make_milestone(100.0, progress=0.1)
        trace = explain_u_time(120.0, kpis, [m], model, t0_ts=T0)
        assert trace.final == 1.0
        assert trace.u_base is None
        assert trace.p_th is None
        assert trace.progress == pytest.approx(0.1)
        assert trace.planning_adjust == 0.0

    def test_v1_sans_jalon(self, model):
        kpis = KPIBundle(time=TimeKPIs(deadline_h=100.0, lead_time_h=50.0, lead_time_std_h=10.0))
        trace = explain_u_time(40.0, kpis, None, model)
        attendu = model.u_time(40.0, kpis)
        assert trace.final == attendu
        assert trace.u_base == attendu
        assert trace.p_th is None
        assert trace.progress is None
        assert trace.planning_adjust == 0.0

    def test_v1_kpis_incomplets_none(self, model):
        trace = explain_u_time(0.0, KPIBundle(), None, model)
        assert trace.final is None
        assert trace.u_base is None
        assert trace.planning_adjust == 0.0

    def test_v2_sans_lead_time_socle_nul(self, model):
        # Choix documente du pipeline : lead time absent -> u_base = 0.0.
        m = make_milestone(100.0, progress=0.0)
        trace = explain_u_time(40.0, KPIBundle(), [m], model, t0_ts=T0)
        assert trace.u_base == 0.0
        assert trace.planning_adjust == pytest.approx(0.2, abs=1e-12)  # 0.5-0.4
        assert trace.final == pytest.approx(0.2, abs=1e-12)


# Propagation


def make_pair_up() -> tuple[InMemoryGraphRepository, PropagationEngine]:
    """Mini-graphe reel S (fournisseur, Ur_loc=0.5) -> I (client, Ur_loc=0.2), beta=0.8."""
    repo = InMemoryGraphRepository()
    repo.add_node(SupplyNode(id="I", name="Client I", urgency=UrgencyState(ur_local=0.2)))
    repo.add_node(SupplyNode(id="S", name="Fournisseur S", urgency=UrgencyState(ur_local=0.5)))
    repo.add_arc(SupplyArc(source_id="S", target_id="I", beta=0.8))
    repo.assign_ranks()
    return repo, PropagationEngine(repo)


class TestPropagationUp:
    def test_cas_chiffre_contre_propagation_engine(self):
        repo, engine = make_pair_up()
        ur = engine.propagate_ascending()
        # Ur_I = 1 - (1 - 0.2)-(1 - 0.8-0.5) = 0.52 (verifie contre le moteur).
        assert ur["I"] == pytest.approx(0.52, abs=1e-12)

        node = repo.get_node("I")
        pred = repo.get_node("S")
        arc = repo.get_arc("S", "I")
        part_locale, contribs = explain_propagation_up(node, [pred], {"S": arc})

        assert len(contribs) == 1
        c = contribs[0]
        assert c.neighbor_id == "S"
        assert c.neighbor_name == "Fournisseur S"
        assert c.coeff == pytest.approx(0.8)
        assert c.u_neighbor == pytest.approx(0.5, abs=1e-12)
        # Part propagee = ln(0.6) / (ln(0.8) + ln(0.6)) = 0.696.
        attendu = math.log(0.6) / (math.log(0.8) + math.log(0.6))
        assert c.share == pytest.approx(attendu, abs=1e-12)
        assert c.share == pytest.approx(0.696, abs=1e-3)
        assert part_locale == pytest.approx(1.0 - attendu, abs=1e-12)
        # part_locale + somme des parts == 1.
        assert part_locale + sum(e.share for e in contribs) == pytest.approx(1.0, abs=1e-9)
        # Reconstruction == Ur du moteur a 1e-12.
        l_loc = -math.log(1.0 - 0.2)
        l_s = -math.log(1.0 - 0.8 * 0.5)
        assert 1.0 - math.exp(-(l_loc + l_s)) == pytest.approx(ur["I"], abs=1e-12)

    def test_retard_avere_part_locale_1(self):
        # Ur_loc >= 1 (ici ABANDONED -> 1.0) : cause locale unique.
        node = SupplyNode(id="I", name="I", status=TaskStatus.ABANDONED)
        pred = SupplyNode(id="S", name="S", urgency=UrgencyState(ur=0.5))
        arc = SupplyArc(source_id="S", target_id="I", beta=0.8)
        part_locale, contribs = explain_propagation_up(node, [pred], {"S": arc})
        assert part_locale == 1.0
        assert [c.share for c in contribs] == [0.0]

    def test_arc_backup_exclu(self):
        node = SupplyNode(id="I", name="I", urgency=UrgencyState(ur_local=0.2))
        pred = SupplyNode(id="S", name="S", urgency=UrgencyState(ur=0.5))
        arc = SupplyArc(source_id="S", target_id="I", beta=0.8, kind_arc=ArcKind.BACKUP)
        part_locale, contribs = explain_propagation_up(node, [pred], {"S": arc})
        assert contribs == []
        assert part_locale == pytest.approx(1.0, abs=1e-12)

    def test_arc_manquant_rejete(self):
        node = SupplyNode(id="I", name="I")
        pred = SupplyNode(id="S", name="S")
        with pytest.raises(ValueError, match="manquant"):
            explain_propagation_up(node, [pred], {})

    def test_tout_nul_parts_nulles(self):
        node = SupplyNode(id="I", name="I", urgency=UrgencyState(ur_local=0.0))
        pred = SupplyNode(id="S", name="S", urgency=UrgencyState(ur=0.0))
        arc = SupplyArc(source_id="S", target_id="I", beta=0.8)
        part_locale, contribs = explain_propagation_up(node, [pred], {"S": arc})
        assert part_locale == 0.0
        assert [c.share for c in contribs] == [0.0]


class TestPropagationDown:
    def test_cas_chiffre_contre_propagation_engine(self):
        # I (fournisseur, Ud_loc = 0.2) -> C (client, Ud_loc = 0.5), gamma = 0.8.
        repo = InMemoryGraphRepository()
        repo.add_node(SupplyNode(id="C", name="Client C", urgency=UrgencyState(ud_local=0.5)))
        repo.add_node(SupplyNode(id="I", name="Noeud I", urgency=UrgencyState(ud_local=0.2)))
        repo.add_arc(SupplyArc(source_id="I", target_id="C", gamma=0.8))
        repo.assign_ranks()
        ud = PropagationEngine(repo).propagate_descending()
        assert ud["I"] == pytest.approx(0.52, abs=1e-12)

        node = repo.get_node("I")
        succ = repo.get_node("C")
        arc = repo.get_arc("I", "C")
        part_locale, contribs = explain_propagation_down(node, [succ], {"C": arc})

        attendu = math.log(0.6) / (math.log(0.8) + math.log(0.6))
        assert contribs[0].share == pytest.approx(attendu, abs=1e-12)
        assert contribs[0].coeff == pytest.approx(0.8)
        assert contribs[0].u_neighbor == pytest.approx(0.5, abs=1e-12)
        assert part_locale + sum(e.share for e in contribs) == pytest.approx(1.0, abs=1e-9)
        # Reconstruction == Ud du moteur a 1e-12.
        l_loc = -math.log(1.0 - 0.2)
        l_c = -math.log(1.0 - 0.8 * 0.5)
        assert 1.0 - math.exp(-(l_loc + l_c)) == pytest.approx(ud["I"], abs=1e-12)

    def test_arc_manquant_rejete(self):
        node = SupplyNode(id="I", name="I")
        succ = SupplyNode(id="C", name="C")
        with pytest.raises(ValueError, match="manquant"):
            explain_propagation_down(node, [succ], {})


# Adequation


class TestExplainAdequation:
    def test_cas_chiffre(self):
        engine = AdequationEngine()
        trace = explain_adequation(0.21, 0.52, engine)
        assert trace.e_under == pytest.approx(0.31, abs=1e-12)
        assert trace.e_over == 0.0
        assert trace.penalty == pytest.approx(2.25 * 0.31**0.88, abs=1e-12)
        assert trace.penalty == pytest.approx(0.8027, abs=1e-3)
        # Score : exactement la valeur du moteur (meme appel).
        assert trace.adequation == engine.adequation_asym(0.21, 0.52)
        assert trace.adequation == pytest.approx(38.31, abs=0.2)
        assert trace.lambda_under == 2.25
        assert trace.lambda_over == 1.0
        assert trace.alpha == 0.88

    def test_surestimation(self):
        engine = AdequationEngine()
        trace = explain_adequation(0.6, 0.4, engine)
        assert trace.e_under == 0.0
        assert trace.e_over == pytest.approx(0.2, abs=1e-12)
        assert trace.penalty == pytest.approx(1.0 * 0.2**0.88, abs=1e-9)
        assert trace.adequation == engine.adequation_asym(0.6, 0.4)

    def test_parametres_moteur_personnalises(self):
        engine = AdequationEngine(lambda_under=3.0, lambda_over=1.5, alpha=1.0)
        trace = explain_adequation(0.2, 0.5, engine)
        assert trace.penalty == pytest.approx(3.0 * 0.3, abs=1e-12)
        assert trace.adequation == engine.adequation_asym(0.2, 0.5)
        assert (trace.lambda_under, trace.lambda_over, trace.alpha) == (3.0, 1.5, 1.0)

    def test_alignement_parfait(self):
        engine = AdequationEngine()
        trace = explain_adequation(0.4, 0.4, engine)
        assert trace.e_under == 0.0
        assert trace.e_over == 0.0
        assert trace.penalty == 0.0
        assert trace.adequation == pytest.approx(100.0, abs=1e-9)


# Invariants Hypothesis


def opt_floats(lo: float, hi: float) -> st.SearchStrategy[float | None]:
    """Float optionnel borne (None = KPI absent), jamais NaN/Inf."""
    return st.one_of(st.none(), st.floats(min_value=lo, max_value=hi, allow_nan=False))


KPI_BUNDLES = st.builds(
    KPIBundle,
    network=st.builds(NetworkKPIs, demand=opt_floats(0.0, 1e4)),
    inventory=st.builds(
        InventoryKPIs,
        max_volume_m3=opt_floats(0.0, 1e4),
        max_weight_kg=opt_floats(0.0, 1e5),
        current_volume_m3=opt_floats(0.0, 1e4),
        current_weight_kg=opt_floats(0.0, 1e5),
        flow_rate=opt_floats(0.0, 1e4),
    ),
    time=st.builds(
        TimeKPIs,
        lead_time_h=opt_floats(0.1, 500.0),
        lead_time_std_h=opt_floats(0.0, 100.0),
        deadline_h=opt_floats(0.0, 1000.0),
    ),
    cost=st.builds(
        CostKPIs,
        nominal_op_cost=opt_floats(0.0, 1e5),
        op_cost=opt_floats(0.0, 1e5),
        tariff=opt_floats(0.0, 5.0),
        storage_cost=opt_floats(0.0, 1e5),
    ),
    co2=st.builds(
        CO2KPIs,
        op_emission_g_h=opt_floats(0.0, 1e5),
        energy_mix_g_h=opt_floats(0.0, 1e5),
        co2_target_g_h=opt_floats(0.0, 1e5),
        co2_max_g_h=opt_floats(0.0, 1e5),
    ),
    oee=st.builds(
        OEEKPIs,
        availability=opt_floats(0.0, 1.0),
        performance=opt_floats(0.0, 1.0),
        quality=opt_floats(0.0, 1.0),
    ),
    risk=st.builds(
        RiskKPIs,
        failure_probability=opt_floats(0.0, 1.0),
        recovery_time_h=opt_floats(0.0, 1000.0),
        severity=opt_floats(0.0, 1.0),
        env_exposure=opt_floats(0.0, 1.0),
        political_risk=opt_floats(0.0, 1.0),
    ),
)


class TestInvariantsHypothesis:
    @given(kpis=KPI_BUNDLES, t=st.floats(0.0, 1000.0))
    def test_reconstruction_coincide_avec_ur_local(self, kpis, t):
        # Coherence OBLIGATOIRE : 1 - exp(-somme l) == ur_local() a 1e-12.
        model = UrModel()
        contribs = explain_ur_local(t, kpis, None, model)
        assert rebuilt_ur(contribs) == pytest.approx(model.ur_local(t, kpis), abs=1e-12)

    @given(kpis=KPI_BUNDLES, t=st.floats(0.0, 1000.0))
    def test_somme_shares_0_ou_1(self, kpis, t):
        model = UrModel()
        contribs = explain_ur_local(t, kpis, None, model)
        somme = sum(c.share for c in contribs)
        assert abs(somme) < 1e-9 or abs(somme - 1.0) < 1e-9
        # Somme 1 ssi au moins un bloc actif porte une urgence > 0.
        actif_non_nul = any(
            c.u is not None and c.omega > 0.0 and explain_mod._log_survival(c.u, c.omega) > 0.0
            for c in contribs
        )
        if actif_non_nul:
            assert somme == pytest.approx(1.0, abs=1e-9)
        else:
            assert somme == 0.0

    @given(kpis=KPI_BUNDLES, t=st.floats(0.0, 1000.0))
    def test_jamais_nan_ni_inf(self, kpis, t):
        contribs = explain_ur_local(t, kpis, None, UrModel())
        for c in contribs:
            assert math.isfinite(c.share)
            assert math.isfinite(c.delta_without)
            assert math.isfinite(c.omega)
            assert -1e-12 <= c.share <= 1.0 + 1e-12
            # Retirer un bloc ne peut qu'abaisser Ur : delta >= 0.
            assert c.delta_without >= -1e-12
            if c.u is not None:
                assert math.isfinite(c.u)
