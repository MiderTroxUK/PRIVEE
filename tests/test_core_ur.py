"""Tests du modèle d'urgence réelle Ur."""

import math
from itertools import pairwise

import pytest

from supplyscore.core.ur_model import (
    UrModel,
    filtered_error,
    ud_hyperbolic,
    ur_singularity,
)
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


@pytest.fixture
def model() -> UrModel:
    return UrModel()


@pytest.fixture
def empty() -> KPIBundle:
    return KPIBundle()


class TestBlocsManquants:
    """Chaque bloc renvoie None quand les KPIs nécessaires manquent."""

    def test_u_time_none(self, model, empty):
        assert model.u_time(0.0, empty) is None
        # lead_time seul ne suffit pas
        k = KPIBundle(time=TimeKPIs(lead_time_h=5.0))
        assert model.u_time(0.0, k) is None
        # deadline seule ne suffit pas
        k = KPIBundle(time=TimeKPIs(deadline_h=10.0))
        assert model.u_time(0.0, k) is None

    def test_u_cap_none(self, model, empty):
        assert model.u_cap(empty) is None

    def test_u_perf_none(self, model, empty):
        assert model.u_perf(empty) is None

    def test_u_risk_none(self, model, empty):
        assert model.u_risk(empty) is None
        # env_exposure seul ne suffit pas (noyau entièrement manquant)
        k = KPIBundle(risk=RiskKPIs(env_exposure=0.5))
        assert model.u_risk(k) is None

    def test_u_cost_none(self, model, empty):
        assert model.u_cost(empty) is None

    def test_u_co2_none(self, model, empty):
        assert model.u_co2(empty) is None
        # total sans cible/max ne suffit pas
        k = KPIBundle(co2=CO2KPIs(op_emission_g_h=100.0))
        assert model.u_co2(k) is None


class TestBornes:
    """Tous les blocs vivent dans [0, 1] même avec des KPIs extrêmes."""

    def test_u_time_bornes(self, model):
        k = KPIBundle(time=TimeKPIs(deadline_h=100.0, lead_time_h=1.0))
        assert 0.0 <= model.u_time(0.0, k) <= 1.0
        k = KPIBundle(time=TimeKPIs(deadline_h=1.0, lead_time_h=1000.0))
        assert 0.0 <= model.u_time(0.0, k) <= 1.0

    def test_u_time_apres_deadline(self, model):
        """t après la deadline -> urgence temporelle 1.0."""
        k = KPIBundle(time=TimeKPIs(deadline_h=10.0, lead_time_h=2.0))
        assert model.u_time(11.0, k) == 1.0

    def test_u_cap_bornes(self, model):
        # Stock saturé + déficit de flux massif
        k = KPIBundle(
            inventory=InventoryKPIs(
                max_volume_m3=100.0,
                current_volume_m3=100.0,
                max_weight_kg=50.0,
                current_weight_kg=50.0,
                flow_rate=0.0,
            ),
            network=NetworkKPIs(demand=1000.0),
        )
        assert 0.0 <= model.u_cap(k) <= 1.0
        # Stock vide, flux excédentaire -> proche de 0
        k = KPIBundle(
            inventory=InventoryKPIs(max_volume_m3=100.0, current_volume_m3=0.0, flow_rate=500.0),
            network=NetworkKPIs(demand=10.0),
        )
        assert 0.0 <= model.u_cap(k) <= 1.0

    def test_u_risk_bornes(self, model):
        k = KPIBundle(
            risk=RiskKPIs(
                failure_probability=1.0,
                recovery_time_h=1000.0,
                severity=1.0,
                env_exposure=0.9,
                political_risk=0.9,
            )
        )
        assert 0.0 <= model.u_risk(k) <= 1.0

    def test_u_cost_bornes(self, model):
        k = KPIBundle(
            cost=CostKPIs(op_cost=10_000.0, nominal_op_cost=10.0, tariff=5.0, storage_cost=99_999.0)
        )
        assert 0.0 <= model.u_cost(k) <= 1.0
        # Coût sous le nominal -> clip à 0
        k = KPIBundle(cost=CostKPIs(op_cost=5.0, nominal_op_cost=100.0))
        assert model.u_cost(k) == 0.0

    def test_u_co2_bornes(self, model):
        k = KPIBundle(
            co2=CO2KPIs(op_emission_g_h=10_000.0, co2_target_g_h=100.0, co2_max_g_h=200.0)
        )
        assert model.u_co2(k) == 1.0
        k = KPIBundle(co2=CO2KPIs(op_emission_g_h=50.0, co2_target_g_h=100.0, co2_max_g_h=200.0))
        assert model.u_co2(k) == 0.0


class TestAgregation:
    def test_tous_blocs_none(self, model, empty):
        assert model.ur_local(0.0, empty) == 0.0

    def test_un_bloc_sature_ur_proche_de_1(self, model):
        """OR probabiliste : un seul bloc à 1.0 -> ur_local ~ 1."""
        k = KPIBundle(oee=OEEKPIs(availability=0.0, performance=1.0, quality=1.0))
        assert model.u_perf(k) == 1.0
        assert model.ur_local(0.0, k) == pytest.approx(1.0)

    def test_or_probabiliste_combinaison(self, model):
        """Deux blocs à 0.5 -> 1 - 0.5*0.5 = 0.75."""
        k = KPIBundle(
            oee=OEEKPIs(availability=0.5, performance=1.0, quality=1.0),
            co2=CO2KPIs(op_emission_g_h=150.0, co2_target_g_h=100.0, co2_max_g_h=200.0),
        )
        assert model.ur_local(0.0, k) == pytest.approx(0.75, rel=1e-6)

    def test_statut_done(self, model):
        k = KPIBundle(oee=OEEKPIs(availability=0.0, performance=1.0, quality=1.0))
        assert model.ur_local(0.0, k, status=TaskStatus.DONE) == 0.0

    def test_statut_abandoned(self, model, empty):
        assert model.ur_local(0.0, empty, status=TaskStatus.ABANDONED) == 1.0

    def test_bornes_ur_local(self, model):
        k = KPIBundle(
            time=TimeKPIs(deadline_h=1.0, lead_time_h=100.0),
            oee=OEEKPIs(availability=0.1, performance=0.1, quality=0.1),
            risk=RiskKPIs(failure_probability=1.0, recovery_time_h=100.0, severity=1.0),
        )
        assert 0.0 <= model.ur_local(0.0, k) <= 1.0

    def test_omega_negatif_rejete(self):
        with pytest.raises(ValueError):
            UrModel(omega={"time": -1.0})

    def test_bloc_inconnu_rejete(self):
        with pytest.raises(ValueError):
            UrModel(omega={"inconnu": 1.0})


class TestUTimeOverride:
    """Point d'extension u_time_override du mode Monte Carlo (E13, Lot 13.2)."""

    @pytest.fixture
    def kpis_temps_complets(self) -> KPIBundle:
        """Bundle avec KPIs temps complets (le calcul local serait possible)."""
        return KPIBundle(time=TimeKPIs(deadline_h=100.0, lead_time_h=10.0, lead_time_std_h=2.0))

    def test_override_prime_sur_kpis_temps_complets(self, model, kpis_temps_complets):
        """L'override remplace le calcul local même quand celui-ci est possible."""
        local = model.blocks(0.0, kpis_temps_complets)["time"]
        assert local is not None and local != 0.42  # le calcul local existe et diffère
        blocks = model.blocks(0.0, kpis_temps_complets, u_time_override=0.42)
        assert blocks["time"] == 0.42

    def test_override_clipe_au_dessus(self, model, kpis_temps_complets):
        blocks = model.blocks(0.0, kpis_temps_complets, u_time_override=1.7)
        assert blocks["time"] == 1.0

    def test_override_clipe_en_dessous(self, model, kpis_temps_complets):
        blocks = model.blocks(0.0, kpis_temps_complets, u_time_override=-0.3)
        assert blocks["time"] == 0.0

    def test_override_nan_rejete(self, model, kpis_temps_complets):
        with pytest.raises(ValueError, match="u_time_override"):
            model.blocks(0.0, kpis_temps_complets, u_time_override=float("nan"))

    def test_override_inf_rejete(self, model, kpis_temps_complets):
        with pytest.raises(ValueError, match="u_time_override"):
            model.blocks(0.0, kpis_temps_complets, u_time_override=float("inf"))
        with pytest.raises(ValueError, match="u_time_override"):
            model.ur_local(0.0, kpis_temps_complets, u_time_override=-math.inf)

    def test_override_active_un_bloc_time_absent(self, model, empty):
        """KPIs temps absents : u_time local None, mais l'override active le bloc."""
        assert model.blocks(0.0, empty)["time"] is None
        blocks = model.blocks(0.0, empty, u_time_override=0.6)
        assert blocks["time"] == 0.6

    def test_ur_local_override_monte_l_agregat_selon_ou(self, model):
        """L'override s'agrège par OU probabiliste : 1 − (1 − 0.5)(1 − 0.5) = 0.75."""
        k = KPIBundle(oee=OEEKPIs(availability=0.5, performance=1.0, quality=1.0))
        sans = model.ur_local(0.0, k)
        avec = model.ur_local(0.0, k, u_time_override=0.5)
        assert sans == pytest.approx(0.5)
        assert avec == pytest.approx(0.75, rel=1e-6)
        assert avec > sans

    def test_ur_local_statut_done_prime_sur_override(self, model, kpis_temps_complets):
        """Les règles de statut restent prioritaires : DONE → 0.0 malgré l'override."""
        assert (
            model.ur_local(0.0, kpis_temps_complets, status=TaskStatus.DONE, u_time_override=0.9)
            == 0.0
        )

    def test_ur_local_statut_abandoned_prime_sur_override(self, model, empty):
        assert model.ur_local(0.0, empty, status=TaskStatus.ABANDONED, u_time_override=0.1) == 1.0

    def test_override_none_egalite_bit_a_bit(self, model):
        """u_time_override=None : strictement aucun changement de comportement."""
        bundle = KPIBundle(
            time=TimeKPIs(deadline_h=50.0, lead_time_h=30.0, lead_time_std_h=8.0),
            inventory=InventoryKPIs(max_volume_m3=100.0, current_volume_m3=70.0, flow_rate=5.0),
            network=NetworkKPIs(demand=8.0),
            oee=OEEKPIs(availability=0.9, performance=0.8, quality=0.95),
            risk=RiskKPIs(failure_probability=0.1, recovery_time_h=12.0, severity=0.7),
            cost=CostKPIs(op_cost=120.0, nominal_op_cost=100.0, tariff=1.2, storage_cost=300.0),
            co2=CO2KPIs(op_emission_g_h=150.0, co2_target_g_h=100.0, co2_max_g_h=200.0),
        )
        assert model.blocks(3.0, bundle, u_time_override=None) == model.blocks(3.0, bundle)
        assert model.ur_local(3.0, bundle, u_time_override=None) == model.ur_local(3.0, bundle)


class TestSingularite:
    def test_monotone_croissante_vers_tc(self):
        ts = [0.0, 2.0, 5.0, 8.0, 9.5, 9.99]
        values = [ur_singularity(t, tc=10.0) for t in ts]
        assert all(b > a for a, b in pairwise(values))
        assert all(0.0 <= v <= 1.0 for v in values)

    def test_depasse_1_apres_tc(self):
        assert ur_singularity(12.0, tc=10.0, K=1.0) == pytest.approx(3.0)
        assert ur_singularity(10.5, tc=10.0) > 1.0

    def test_continuite_en_tc(self):
        assert ur_singularity(10.0, tc=10.0) == pytest.approx(1.0)

    def test_parametres_invalides(self):
        with pytest.raises(ValueError):
            ur_singularity(0.0, 10.0, K=0.0)
        with pytest.raises(ValueError):
            ur_singularity(0.0, 10.0, eps_min=-1.0)


class TestFonctionsAuxiliaires:
    def test_filtered_error_zone_morte(self):
        assert filtered_error(0.5, 0.45, eps_tol=0.1) == 0.0
        assert filtered_error(0.8, 0.5, eps_tol=0.1) == pytest.approx(0.2)
        assert filtered_error(0.5, 0.8, eps_tol=0.1) == pytest.approx(-0.2)

    def test_filtered_error_sans_tolerance(self):
        assert filtered_error(0.7, 0.4) == pytest.approx(0.3)
        assert filtered_error(0.4, 0.7) == pytest.approx(-0.3)

    def test_filtered_error_eps_negatif(self):
        with pytest.raises(ValueError):
            filtered_error(0.5, 0.5, eps_tol=-0.01)

    def test_ud_hyperbolic(self):
        # Loin de tc : urgence perçue faible ; à tc : 1
        assert ud_hyperbolic(0.0, tc=100.0, k=0.05) == pytest.approx(1 / 6)
        assert ud_hyperbolic(100.0, tc=100.0) == pytest.approx(1.0)
        assert ud_hyperbolic(150.0, tc=100.0) == pytest.approx(1.0)
        with pytest.raises(ValueError):
            ud_hyperbolic(0.0, 10.0, k=-0.1)
