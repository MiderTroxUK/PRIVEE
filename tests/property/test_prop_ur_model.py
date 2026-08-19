"""Proprietes Hypothesis et cas analytiques du modele Ur (phase E9, Lot 9.2).

Deux familles de tests :
- cas analytiques a valeur fermee (loi normale, OEE, exponentielle de risque,
  depassement CO2, OU probabiliste pondere), tolerance 1e-3 sauf mention ;
- invariants Hypothesis sur des bundles KPI VALIDES au sens de
  :mod:`supplyscore.domain.constraints` : bornes [0, 1], absence de NaN/Inf,
  monotonies, blocs de poids nul ignores, domination du OU probabiliste et
  ecrasement par statut (DONE -> 0.0, ABANDONED -> 1.0).
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core.ur_model import BLOCKS, UrModel
from supplyscore.domain.milestones import Milestone, MilestoneStatus, next_active_milestone
from supplyscore.domain.models import (
    CO2KPIs,
    CostKPIs,
    InventoryKPIs,
    KPIBundle,
    NetworkKPIs,
    OEEKPIs,
    RiskKPIs,
    TaskStatus,
    TimeKPIs,
)

#: Tolerance absolue pour les comparaisons de monotonie (bruit d'arrondi IEEE).
_TOL = 1e-12


def _floats(lo: float, hi: float) -> st.SearchStrategy[float]:
    """Floats finis bornes - jamais NaN ni infini."""
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)


def _opt(strategy: st.SearchStrategy[float]) -> st.SearchStrategy[float | None]:
    """KPI optionnel : None (non renseigne) ou valeur valide."""
    return st.none() | strategy


# Strategies : bundles KPI valides au sens de KPI_CONSTRAINTS Bornes alignees sur supplyscore.domain.constraints.KPI_CONSTRAINTS : ratios dans [0, 1], grandeurs physiques >= 0, tarif >= 1e-9.

_RATIO = _floats(0.0, 1.0)
_POS = _floats(0.0, 1e6)
_TARIFF = _floats(1e-9, 100.0)
_T = _floats(0.0, 1e6)

_NETWORK = st.builds(NetworkKPIs, distance_km=_opt(_POS), demand=_opt(_POS))
_INVENTORY = st.builds(
    InventoryKPIs,
    max_volume_m3=_opt(_POS),
    max_weight_kg=_opt(_POS),
    current_volume_m3=_opt(_POS),
    current_weight_kg=_opt(_POS),
    flow_rate=_opt(_POS),
)
_TIME = st.builds(
    TimeKPIs,
    lead_time_h=_opt(_POS),
    lead_time_std_h=_opt(_POS),
    delay_h=_opt(_POS),
    deadline_h=_opt(_POS),
)
_COST = st.builds(
    CostKPIs,
    tariff=_opt(_TARIFF),
    nominal_op_cost=_opt(_POS),
    op_cost=_opt(_POS),
    storage_cost=_opt(_POS),
)
_CO2 = st.builds(
    CO2KPIs,
    op_emission_g_h=_opt(_POS),
    energy_mix_g_h=_opt(_POS),
    co2_target_g_h=_opt(_POS),
    co2_max_g_h=_opt(_POS),
)
_OEE = st.builds(
    OEEKPIs,
    availability=_opt(_RATIO),
    performance=_opt(_RATIO),
    quality=_opt(_RATIO),
)
_RISK = st.builds(
    RiskKPIs,
    failure_probability=_opt(_RATIO),
    recovery_time_h=_opt(_POS),
    severity=_opt(_RATIO),
    env_exposure=_opt(_RATIO),
    political_risk=_opt(_RATIO),
)
_BUNDLES = st.builds(
    KPIBundle,
    network=_NETWORK,
    inventory=_INVENTORY,
    time=_TIME,
    cost=_COST,
    co2=_CO2,
    oee=_OEE,
    risk=_RISK,
)
_OMEGAS = st.fixed_dictionaries({name: _floats(0.0, 5.0) for name in BLOCKS})
_MILESTONES = st.lists(
    st.builds(
        Milestone,
        id=st.sampled_from(["m1", "m2", "m3"]),
        node_id=st.just("n1"),
        name=st.just("Jalon"),
        start_ts=_floats(0.0, 1e7),
        deadline_ts=_floats(0.0, 1e7),
        status=st.sampled_from(list(MilestoneStatus)),
        progress=_RATIO,
    ),
    max_size=3,
)


# Cas analytiques


class TestCasAnalytiquesUTime:
    """u_time v1 : valeurs fermees de P(L > slack) pour L ~ Normale(mu, sigma)."""

    def test_p_retard_exactement_un_demi(self):
        """slack = deadline - t = 100 = mu : P(L > mu) = 0.5 exactement."""
        k = KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0, deadline_h=200.0))
        assert UrModel().u_time(100.0, k) == pytest.approx(0.5, abs=1e-9)

    def test_slack_a_1_96_sigma(self):
        """slack = 100 + 1.96 x 20 = 139.2 : P(Z > 1.96) = 0.0250."""
        k = KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0, deadline_h=139.2))
        assert UrModel().u_time(0.0, k) == pytest.approx(0.025, abs=5e-4)

    def test_sigma_nul_retard_certain(self):
        """sigma = 0 (deterministe) : lead 100 > slack 50 -> retard certain (1.0)."""
        k = KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=0.0, deadline_h=50.0))
        assert UrModel().u_time(0.0, k) == 1.0

    def test_sigma_nul_retard_impossible(self):
        """sigma = 0 (deterministe) : lead 100 < slack 150 -> retard impossible (0.0)."""
        k = KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=0.0, deadline_h=150.0))
        assert UrModel().u_time(0.0, k) == 0.0


class TestCasAnalytiquesBlocs:
    """Valeurs fermees des blocs perf, risque et CO2."""

    def test_u_perf_oee_0_729(self):
        """availability = performance = quality = 0.9 : OEE = 0.729, u = 0.271."""
        k = KPIBundle(oee=OEEKPIs(availability=0.9, performance=0.9, quality=0.9))
        assert UrModel().u_perf(k) == pytest.approx(0.271, abs=1e-3)

    def test_u_risk_noyau_exponentiel(self):
        """fp=0.1, recup=24, sev=1, T_ref=24 : u = 1 - e^-0.1 = 0.0951626."""
        k = KPIBundle(risk=RiskKPIs(failure_probability=0.1, recovery_time_h=24.0, severity=1.0))
        assert UrModel(t_ref_h=24.0).u_risk(k) == pytest.approx(1.0 - math.exp(-0.1), abs=1e-6)

    def test_u_risk_avec_exposition_environnementale(self):
        """Composition OU avec env=0.2 : u = 1 - 0.9048374 x 0.8 = 0.2761301."""
        k = KPIBundle(
            risk=RiskKPIs(
                failure_probability=0.1,
                recovery_time_h=24.0,
                severity=1.0,
                env_exposure=0.2,
            )
        )
        attendu = 1.0 - math.exp(-0.1) * 0.8
        assert UrModel(t_ref_h=24.0).u_risk(k) == pytest.approx(attendu, abs=1e-6)

    def test_u_co2_depassement_0_75(self):
        """total = 700 + 200 = 900, cible 600, max 1000 : u = 300/400 = 0.75."""
        k = KPIBundle(
            co2=CO2KPIs(
                op_emission_g_h=700.0,
                energy_mix_g_h=200.0,
                co2_target_g_h=600.0,
                co2_max_g_h=1000.0,
            )
        )
        assert UrModel().u_co2(k) == pytest.approx(0.75, abs=1e-3)


class TestCasAnalytiquesAgregation:
    """OU probabiliste pondere : ur = 1 - prod (1 - u_m)^omega_m."""

    def test_deux_blocs_a_un_demi(self):
        """Deux blocs a 0.5 (omega = 1) : ur = 1 - 0.5 x 0.5 = 0.75."""
        # time : slack = 100 = mu -> 0.5 exact ; perf : OEE = 0.5 -> 0.5 exact.
        k = KPIBundle(
            time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0, deadline_h=100.0),
            oee=OEEKPIs(availability=0.5, performance=1.0, quality=1.0),
        )
        model = UrModel()
        blocs = model.blocks(0.0, k)
        assert blocs["time"] == pytest.approx(0.5, abs=1e-9)
        assert blocs["perf"] == pytest.approx(0.5, abs=1e-9)
        assert sum(1 for u in blocs.values() if u is not None) == 2
        assert model.ur_local(0.0, k) == pytest.approx(0.75, abs=1e-9)

    def test_un_bloc_a_un_demi_omega_deux(self):
        """Un seul bloc a 0.5 avec omega = 2 : ur = 1 - 0.5^2 = 0.75."""
        k = KPIBundle(oee=OEEKPIs(availability=0.5, performance=1.0, quality=1.0))
        model = UrModel(omega={"perf": 2.0})
        assert model.ur_local(0.0, k) == pytest.approx(0.75, abs=1e-9)


# Invariants Hypothesis


class TestProprietesBornes:
    """Bornes et finitude sur des bundles valides arbitraires."""

    @given(bundle=_BUNDLES, t=_T)
    def test_blocs_dans_01_ou_none_et_ur_dans_01(self, bundle: KPIBundle, t: float):
        model = UrModel()
        for name, u in model.blocks(t, bundle).items():
            assert name in BLOCKS
            if u is not None:
                assert math.isfinite(u), f"bloc {name} non fini : {u}"
                assert 0.0 <= u <= 1.0, f"bloc {name} hors [0, 1] : {u}"
        ur = model.ur_local(t, bundle, status=TaskStatus.ACTIVE)
        assert math.isfinite(ur)
        assert 0.0 <= ur <= 1.0

    @given(bundle=_BUNDLES, t=_floats(0.0, 5000.0), milestones=_MILESTONES)
    def test_u_time_v2_borne_et_defini_si_jalon_actif(
        self, bundle: KPIBundle, t: float, milestones: list[Milestone]
    ):
        u = UrModel().u_time(t, bundle, milestones=milestones, t0_ts=0.0)
        if u is not None:
            assert math.isfinite(u)
            assert 0.0 <= u <= 1.0
        if next_active_milestone(milestones) is not None:
            # v2 : le jalon actif fournit toujours une echeance -> jamais None.
            assert u is not None


class TestProprietesMonotonie:
    """Monotonies : slack qui fond, lead time qui gonfle, bloc qui s'aggrave."""

    @given(
        lead=_floats(0.0, 1e4),
        std=_opt(_floats(0.0, 1e3)),
        deadline=_floats(0.0, 1e4),
        t_pair=st.tuples(_floats(0.0, 2e4), _floats(0.0, 2e4)),
    )
    def test_u_time_croissante_en_t(
        self, lead: float, std: float | None, deadline: float, t_pair: tuple[float, float]
    ):
        t1, t2 = sorted(t_pair)
        k = KPIBundle(time=TimeKPIs(lead_time_h=lead, lead_time_std_h=std, deadline_h=deadline))
        model = UrModel()
        u1, u2 = model.u_time(t1, k), model.u_time(t2, k)
        assert u1 is not None and u2 is not None
        assert u1 <= u2 + _TOL

    @given(
        lead_pair=st.tuples(_floats(0.0, 1e4), _floats(0.0, 1e4)),
        std=_opt(_floats(0.0, 1e3)),
        deadline=_floats(0.0, 1e4),
        t=_floats(0.0, 2e4),
    )
    def test_u_time_croissante_en_lead_time(
        self, lead_pair: tuple[float, float], std: float | None, deadline: float, t: float
    ):
        l1, l2 = sorted(lead_pair)
        k1 = KPIBundle(time=TimeKPIs(lead_time_h=l1, lead_time_std_h=std, deadline_h=deadline))
        k2 = KPIBundle(time=TimeKPIs(lead_time_h=l2, lead_time_std_h=std, deadline_h=deadline))
        model = UrModel()
        u1, u2 = model.u_time(t, k1), model.u_time(t, k2)
        assert u1 is not None and u2 is not None
        assert u1 <= u2 + _TOL

    @given(bundle=_BUNDLES, t=_T, fp_pair=st.tuples(_RATIO, _RATIO))
    def test_ur_local_non_decroissante_quand_failure_probability_monte(
        self, bundle: KPIBundle, t: float, fp_pair: tuple[float, float]
    ):
        """Deux bundles ne differant que par failure_probability croissante."""
        fp1, fp2 = sorted(fp_pair)
        b1 = replace(bundle, risk=replace(bundle.risk, failure_probability=fp1))
        b2 = replace(bundle, risk=replace(bundle.risk, failure_probability=fp2))
        model = UrModel()
        assert model.ur_local(t, b1) <= model.ur_local(t, b2) + _TOL


class TestProprietesOmega:
    """Poids d'agregation : bloc de poids nul ignore, domination du OU."""

    @given(bundle=_BUNDLES, t=_T, fp1=_opt(_RATIO), fp2=_opt(_RATIO))
    def test_omega_nul_bloc_ignore(
        self, bundle: KPIBundle, t: float, fp1: float | None, fp2: float | None
    ):
        """omega_risk = 0 : changer le KPI du bloc risque ne change pas ur_local."""
        model = UrModel(omega={"risk": 0.0})
        b1 = replace(bundle, risk=replace(bundle.risk, failure_probability=fp1))
        b2 = replace(bundle, risk=replace(bundle.risk, failure_probability=fp2))
        assert model.ur_local(t, b1) == model.ur_local(t, b2)

    def test_omega_positif_bloc_sensible(self):
        """Reciproque (cas temoin) : omega_risk > 0 -> le bloc pese sur ur_local."""
        model = UrModel()
        calme = KPIBundle(risk=RiskKPIs(failure_probability=0.0))
        critique = KPIBundle(risk=RiskKPIs(failure_probability=0.9))
        assert model.ur_local(0.0, calme) < model.ur_local(0.0, critique)

    @given(bundle=_BUNDLES, t=_T, omega=_OMEGAS)
    def test_ou_domine_chaque_contribution(
        self, bundle: KPIBundle, t: float, omega: dict[str, float]
    ):
        """ur_local >= max_m [1 - (1 - u_m)^omega_m] - tolerance."""
        model = UrModel(omega=omega)
        ur = model.ur_local(t, bundle, status=TaskStatus.ACTIVE)
        for name, u in model.blocks(t, bundle).items():
            if u is None or omega[name] == 0.0:
                continue
            contribution = 1.0 - (1.0 - min(max(u, 0.0), 1.0)) ** omega[name]
            assert ur >= contribution - _TOL, f"bloc {name} : {contribution} > ur {ur}"


class TestProprietesStatuts:
    """Ecrasement par statut, quels que soient les KPIs."""

    @given(bundle=_BUNDLES, t=_T)
    def test_done_ecrase_a_zero_et_abandoned_a_un(self, bundle: KPIBundle, t: float):
        model = UrModel()
        assert model.ur_local(t, bundle, status=TaskStatus.DONE) == 0.0
        assert model.ur_local(t, bundle, status=TaskStatus.ABANDONED) == 1.0


# Bug decouvert par les proprietes, corrige en E9.6


def test_u_co2_span_nul_ne_crashe_pas():
    """Bornes incoherentes (cible > max) : u_co2 sature vers 1 au lieu de planter.

    Regression E9.6 : l'ancien denominateur " max - cible + eps " valait 0
    exactement pour cible = eps et max = 0 (ZeroDivisionError), alors que ces
    entrees sont valides champ a champ au sens de KPI_CONSTRAINTS.
    """
    k = KPIBundle(co2=CO2KPIs(op_emission_g_h=100.0, co2_target_g_h=1e-9, co2_max_g_h=0.0))
    u = UrModel().u_co2(k)
    assert u is not None
    assert 0.0 <= u <= 1.0
    assert u == 1.0  # depassement massif de la cible avec span degenere -> saturation
