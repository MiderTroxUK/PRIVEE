"""Tests de la validation exhaustive du domaine (phase E10, Lot 10.1).

Trois familles :
- cas chiffres sur :func:`validate_kpis` (erreurs de bornes, NaN, avertissements
  croises jamais bloquants) ;
- validation des entites (noeud, arc, jalon, cahier des charges) ;
- proprietes Hypothesis : un champ hors borne implique >= 1 erreur ; un bundle
  borne champ a champ implique 0 erreur ET ``UrModel().ur_local`` ne leve jamais.
"""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core.ur_model import UrModel
from supplyscore.domain.constraints import KPI_CONSTRAINTS
from supplyscore.domain.milestones import Milestone
from supplyscore.domain.models import (
    CO2KPIs,
    CostKPIs,
    InventoryKPIs,
    KPIBundle,
    NetworkKPIs,
    OEEKPIs,
    SupplyArc,
    SupplyNode,
    TimeKPIs,
)
from supplyscore.domain.specsheet import (
    CahierDesCharges,
    Deliverable,
    PenaltyClause,
    QualityRequirements,
)
from supplyscore.domain.validation import (
    ValidationIssue,
    avertissements,
    erreurs,
    validate_arc,
    validate_cdc,
    validate_kpis,
    validate_milestone,
    validate_node,
)

# Helpers


def _set_kpi(bundle: KPIBundle, path: str, value: float | None) -> None:
    """Affecte ``value`` au KPI ``bloc.champ`` du bundle (chemin de KPI_CONSTRAINTS)."""
    block_name, field_name = path.split(".", 1)
    setattr(getattr(bundle, block_name), field_name, value)


def _milestone_valide(**overrides: object) -> Milestone:
    """Jalon nominal valide, surcharges possibles champ par champ."""
    base: dict[str, object] = {
        "id": "m1",
        "node_id": "n1",
        "name": "Proto",
        "start_ts": 1_000.0,
        "deadline_ts": 2_000.0,
        "progress": 0.5,
    }
    base.update(overrides)
    return Milestone(**base)  # type: ignore[arg-type]


# Strategies Hypothesis


def _valeur_valide(lo: float | None, hi: float | None) -> st.SearchStrategy[float]:
    """Float fini dans les bornes du KPI (bornes ouvertes plafonnees a 1e6)."""
    return st.floats(
        min_value=lo if lo is not None else 0.0,
        max_value=hi if hi is not None else 1e6,
        allow_nan=False,
        allow_infinity=False,
    )


@st.composite
def _bundles_valides(draw: st.DrawFn) -> KPIBundle:
    """Bundle dont chaque champ est None ou dans les bornes de KPI_CONSTRAINTS."""
    bundle = KPIBundle()
    for path, (lo, hi, _unit) in KPI_CONSTRAINTS.items():
        value = draw(st.none() | _valeur_valide(lo, hi))
        _set_kpi(bundle, path, value)
    return bundle


@st.composite
def _bundles_un_champ_invalide(draw: st.DrawFn) -> tuple[KPIBundle, str]:
    """Bundle valide partout SAUF un champ pousse hors borne (ou NaN/+/-inf)."""
    bundle = draw(_bundles_valides())
    path = draw(st.sampled_from(sorted(KPI_CONSTRAINTS)))
    lo, hi, _unit = KPI_CONSTRAINTS[path]
    candidats: list[float] = [math.nan, math.inf, -math.inf]
    if lo is not None:
        candidats.append(lo - 1.0)
    if hi is not None:
        candidats.append(hi + 1.0)
    _set_kpi(bundle, path, draw(st.sampled_from(candidats)))
    return bundle, path


# validate_kpis : erreurs de bornes


class TestValidateKpisErreurs:
    def test_bundle_vide_aucun_constat(self):
        assert validate_kpis(KPIBundle()) == []

    def test_availability_1_2_erreur(self):
        bundle = KPIBundle(oee=OEEKPIs(availability=1.2))
        issues = validate_kpis(bundle)
        assert [i.champ for i in erreurs(issues)] == ["oee.availability"]
        assert avertissements(issues) == []

    def test_tariff_zero_erreur(self):
        issues = validate_kpis(KPIBundle(cost=CostKPIs(tariff=0.0)))
        assert [i.champ for i in erreurs(issues)] == ["cost.tariff"]

    def test_nan_erreur(self):
        issues = validate_kpis(KPIBundle(cost=CostKPIs(op_cost=math.nan)))
        errs = erreurs(issues)
        assert [i.champ for i in errs] == ["cost.op_cost"]
        assert "non finie" in errs[0].message_fr

    def test_infini_erreur(self):
        issues = validate_kpis(KPIBundle(time=TimeKPIs(lead_time_h=math.inf)))
        assert [i.champ for i in erreurs(issues)] == ["time.lead_time_h"]

    def test_distance_negative_erreur(self):
        issues = validate_kpis(KPIBundle(network=NetworkKPIs(distance_km=-5.0)))
        assert [i.champ for i in erreurs(issues)] == ["network.distance_km"]


# validate_kpis : avertissements croises (jamais bloquants)


class TestValidateKpisAvertissements:
    def test_deadline_inferieure_au_lead_time_avertit_sans_bloquer(self):
        bundle = KPIBundle(time=TimeKPIs(lead_time_h=200.0, deadline_h=100.0))
        issues = validate_kpis(bundle)
        assert erreurs(issues) == []
        warns = avertissements(issues)
        assert [w.champ for w in warns] == ["time.deadline_h"]
        assert "retard quasi certain" in warns[0].message_fr

    def test_volume_courant_au_dela_de_la_capacite(self):
        bundle = KPIBundle(inventory=InventoryKPIs(max_volume_m3=100.0, current_volume_m3=120.0))
        issues = validate_kpis(bundle)
        assert erreurs(issues) == []
        warns = avertissements(issues)
        assert [w.champ for w in warns] == ["inventory.current_volume_m3"]
        assert "capacité déclarée" in warns[0].message_fr

    def test_poids_courant_au_dela_de_la_capacite(self):
        bundle = KPIBundle(inventory=InventoryKPIs(max_weight_kg=500.0, current_weight_kg=600.0))
        warns = avertissements(validate_kpis(bundle))
        assert [w.champ for w in warns] == ["inventory.current_weight_kg"]

    def test_volume_courant_sous_la_capacite_silencieux(self):
        bundle = KPIBundle(inventory=InventoryKPIs(max_volume_m3=100.0, current_volume_m3=80.0))
        assert validate_kpis(bundle) == []

    def test_cible_co2_superieure_au_max(self):
        bundle = KPIBundle(co2=CO2KPIs(co2_target_g_h=1000.0, co2_max_g_h=800.0))
        issues = validate_kpis(bundle)
        assert erreurs(issues) == []
        warns = avertissements(issues)
        assert [w.champ for w in warns] == ["co2.co2_target_g_h"]
        assert "bornes incohérentes" in warns[0].message_fr

    def test_cible_co2_egale_au_max_avertit_aussi(self):
        bundle = KPIBundle(co2=CO2KPIs(co2_target_g_h=800.0, co2_max_g_h=800.0))
        assert len(avertissements(validate_kpis(bundle))) == 1

    def test_flow_rate_sans_demande(self):
        bundle = KPIBundle(inventory=InventoryKPIs(flow_rate=5.0))
        warns = avertissements(validate_kpis(bundle))
        assert [w.champ for w in warns] == ["inventory.flow_rate"]
        assert "u_cap partiel" in warns[0].message_fr

    def test_flow_rate_avec_demande_silencieux(self):
        bundle = KPIBundle(network=NetworkKPIs(demand=10.0), inventory=InventoryKPIs(flow_rate=5.0))
        assert validate_kpis(bundle) == []

    def test_op_cost_inferieur_au_nominal(self):
        bundle = KPIBundle(cost=CostKPIs(nominal_op_cost=80.0, op_cost=50.0))
        issues = validate_kpis(bundle)
        assert erreurs(issues) == []
        warns = avertissements(issues)
        assert [w.champ for w in warns] == ["cost.op_cost"]
        assert "vérifier la saisie" in warns[0].message_fr

    def test_op_cost_au_dessus_du_nominal_silencieux(self):
        bundle = KPIBundle(cost=CostKPIs(nominal_op_cost=80.0, op_cost=90.0))
        assert validate_kpis(bundle) == []

    def test_erreur_et_avertissement_peuvent_coexister(self):
        bundle = KPIBundle(
            oee=OEEKPIs(availability=1.2),
            time=TimeKPIs(lead_time_h=200.0, deadline_h=100.0),
        )
        issues = validate_kpis(bundle)
        assert len(erreurs(issues)) == 1
        assert len(avertissements(issues)) == 1


# validate_node


class TestValidateNode:
    def test_noeud_nominal_valide(self):
        node = SupplyNode(id="n1", name="Usine Lyon", latitude=45.76, longitude=4.84)
        assert validate_node(node) == []

    def test_nom_vide_erreur(self):
        issues = validate_node(SupplyNode(id="n1", name="  "))
        assert [i.champ for i in erreurs(issues)] == ["name"]

    def test_rang_negatif_erreur(self):
        issues = validate_node(SupplyNode(id="n1", name="N", rank=-1))
        assert [i.champ for i in erreurs(issues)] == ["rank"]

    def test_latitude_91_erreur(self):
        issues = validate_node(SupplyNode(id="n1", name="N", latitude=91.0))
        assert [i.champ for i in erreurs(issues)] == ["latitude"]

    def test_longitude_moins_181_erreur(self):
        issues = validate_node(SupplyNode(id="n1", name="N", longitude=-181.0))
        assert [i.champ for i in erreurs(issues)] == ["longitude"]

    def test_latitude_nan_erreur(self):
        issues = validate_node(SupplyNode(id="n1", name="N", latitude=math.nan))
        assert [i.champ for i in erreurs(issues)] == ["latitude"]

    def test_onboarding_state_inconnu_erreur(self):
        issues = validate_node(SupplyNode(id="n1", name="N", onboarding_state="pending"))
        assert [i.champ for i in erreurs(issues)] == ["onboarding_state"]

    def test_onboarding_draft_accepte(self):
        assert validate_node(SupplyNode(id="n1", name="N", onboarding_state="draft")) == []

    def test_bundle_invalide_remonte(self):
        node = SupplyNode(id="n1", name="N", kpis=KPIBundle(oee=OEEKPIs(availability=1.2)))
        assert [i.champ for i in erreurs(validate_node(node))] == ["oee.availability"]

    def test_avertissement_kpi_remonte_aussi(self):
        node = SupplyNode(
            id="n1", name="N", kpis=KPIBundle(time=TimeKPIs(lead_time_h=200.0, deadline_h=100.0))
        )
        issues = validate_node(node)
        assert erreurs(issues) == []
        assert [w.champ for w in avertissements(issues)] == ["time.deadline_h"]


# validate_arc


class TestValidateArc:
    def test_arc_nominal_valide(self):
        assert validate_arc(SupplyArc(source_id="a", target_id="b")) == []

    def test_arc_bornes_extremes_valide(self):
        arc = SupplyArc(source_id="a", target_id="b", gamma=1.0, beta=0.0, delta=2.0)
        assert validate_arc(arc) == []

    def test_gamma_1_5_erreur(self):
        issues = validate_arc(SupplyArc(source_id="a", target_id="b", gamma=1.5))
        assert [i.champ for i in erreurs(issues)] == ["gamma"]

    def test_beta_negatif_erreur(self):
        issues = validate_arc(SupplyArc(source_id="a", target_id="b", beta=-0.1))
        assert [i.champ for i in erreurs(issues)] == ["beta"]

    def test_delta_2_5_erreur(self):
        issues = validate_arc(SupplyArc(source_id="a", target_id="b", delta=2.5))
        assert [i.champ for i in erreurs(issues)] == ["delta"]

    def test_gamma_nan_erreur(self):
        issues = validate_arc(SupplyArc(source_id="a", target_id="b", gamma=math.nan))
        assert [i.champ for i in erreurs(issues)] == ["gamma"]

    def test_self_loop_erreur(self):
        issues = validate_arc(SupplyArc(source_id="a", target_id="a"))
        errs = erreurs(issues)
        assert [i.champ for i in errs] == ["target_id"]
        assert "boucle" in errs[0].message_fr

    def test_cumul_des_erreurs(self):
        arc = SupplyArc(source_id="a", target_id="a", gamma=2.0, beta=-1.0, delta=3.0)
        assert {i.champ for i in erreurs(validate_arc(arc))} == {
            "gamma",
            "beta",
            "delta",
            "target_id",
        }


# validate_milestone


class TestValidateMilestone:
    def test_jalon_nominal_valide(self):
        assert validate_milestone(_milestone_valide()) == []

    def test_nom_vide_erreur(self):
        issues = validate_milestone(_milestone_valide(name="  "))
        assert [i.champ for i in erreurs(issues)] == ["name"]

    def test_deadline_egale_au_start_erreur(self):
        issues = validate_milestone(_milestone_valide(start_ts=1_000.0, deadline_ts=1_000.0))
        assert [i.champ for i in erreurs(issues)] == ["deadline_ts"]

    def test_deadline_avant_le_start_erreur(self):
        issues = validate_milestone(_milestone_valide(start_ts=2_000.0, deadline_ts=1_000.0))
        errs = erreurs(issues)
        assert [i.champ for i in errs] == ["deadline_ts"]
        assert "fenêtre" in errs[0].message_fr

    def test_progress_hors_borne_erreur(self):
        issues = validate_milestone(_milestone_valide(progress=1.5))
        assert [i.champ for i in erreurs(issues)] == ["progress"]

    def test_timestamp_nan_erreur_sans_doublon_de_fenetre(self):
        issues = validate_milestone(_milestone_valide(start_ts=math.nan))
        assert [i.champ for i in erreurs(issues)] == ["start_ts"]

    def test_timestamp_infini_erreur(self):
        issues = validate_milestone(_milestone_valide(deadline_ts=math.inf))
        assert [i.champ for i in erreurs(issues)] == ["deadline_ts"]


# validate_cdc


def _cdc_nominal() -> CahierDesCharges:
    """Cahier des charges complet et valide."""
    return CahierDesCharges(
        deliverables=[Deliverable(name="Capteurs", quantity=200.0, unit="pièces")],
        budget_total=50_000.0,
        target_unit_cost=250.0,
        quality=QualityRequirements(standards=["ISO 9001"], max_scrap_rate=0.02),
        penalties=[
            PenaltyClause(
                kind="late_delivery", trigger="J+1", amount_per_day=500.0, cap_amount=10_000.0
            )
        ],
    )


class TestValidateCdc:
    def test_cdc_vide_valide(self):
        assert validate_cdc(CahierDesCharges()) == []

    def test_cdc_nominal_valide(self):
        assert validate_cdc(_cdc_nominal()) == []

    def test_budget_negatif_erreur(self):
        issues = validate_cdc(CahierDesCharges(budget_total=-1.0))
        assert [i.champ for i in erreurs(issues)] == ["budget_total"]

    def test_target_unit_cost_negatif_erreur(self):
        issues = validate_cdc(CahierDesCharges(target_unit_cost=-0.5))
        assert [i.champ for i in erreurs(issues)] == ["target_unit_cost"]

    def test_budget_nan_erreur(self):
        issues = validate_cdc(CahierDesCharges(budget_total=math.nan))
        assert [i.champ for i in erreurs(issues)] == ["budget_total"]

    def test_quantite_nulle_erreur(self):
        cdc = CahierDesCharges(deliverables=[Deliverable(name="Lot", quantity=0.0, unit="kg")])
        errs = erreurs(validate_cdc(cdc))
        assert [i.champ for i in errs] == ["deliverables[0].quantity"]
        assert "'Lot'" in errs[0].message_fr

    def test_quantite_nan_erreur(self):
        cdc = CahierDesCharges(deliverables=[Deliverable(name="Lot", quantity=math.nan, unit="kg")])
        errs = erreurs(validate_cdc(cdc))
        assert [i.champ for i in errs] == ["deliverables[0].quantity"]
        assert "non finie" in errs[0].message_fr

    def test_quantite_negative_du_second_livrable_erreur(self):
        cdc = CahierDesCharges(
            deliverables=[
                Deliverable(name="A", quantity=10.0, unit="pièces"),
                Deliverable(name="B", quantity=-3.0, unit="pièces"),
            ]
        )
        assert [i.champ for i in erreurs(validate_cdc(cdc))] == ["deliverables[1].quantity"]

    def test_max_scrap_rate_hors_borne_erreur(self):
        cdc = CahierDesCharges(quality=QualityRequirements(max_scrap_rate=1.5))
        assert [i.champ for i in erreurs(validate_cdc(cdc))] == ["quality.max_scrap_rate"]

    def test_penalite_negative_erreur(self):
        cdc = CahierDesCharges(
            penalties=[PenaltyClause(kind="quality", trigger="rebut", amount_per_day=-5.0)]
        )
        assert [i.champ for i in erreurs(validate_cdc(cdc))] == ["penalties[0].amount_per_day"]

    def test_cap_negatif_erreur(self):
        cdc = CahierDesCharges(
            penalties=[PenaltyClause(kind="other", trigger="x", cap_amount=-1.0)]
        )
        assert [i.champ for i in erreurs(validate_cdc(cdc))] == ["penalties[0].cap_amount"]


# Filtres erreurs / avertissements


class TestFiltres:
    def test_filtrage_par_severite(self):
        e1 = ValidationIssue("a", "erreur 1", "erreur")
        w1 = ValidationIssue("b", "avert 1", "avertissement")
        e2 = ValidationIssue("c", "erreur 2", "erreur")
        issues = [e1, w1, e2]
        assert erreurs(issues) == [e1, e2]
        assert avertissements(issues) == [w1]

    def test_listes_vides(self):
        assert erreurs([]) == []
        assert avertissements([]) == []


# Proprietes Hypothesis


class TestProprietes:
    @given(data=_bundles_un_champ_invalide())
    def test_un_champ_hors_borne_implique_au_moins_une_erreur(self, data: tuple[KPIBundle, str]):
        bundle, path = data
        errs = erreurs(validate_kpis(bundle))
        assert len(errs) >= 1
        assert any(issue.champ == path for issue in errs)

    @given(bundle=_bundles_valides())
    def test_bundle_borne_zero_erreur_et_ur_local_ne_leve_jamais(self, bundle: KPIBundle):
        issues = validate_kpis(bundle)
        assert erreurs(issues) == []  # avertissements toleres
        ur = UrModel().ur_local(0.0, bundle)
        assert math.isfinite(ur)
        assert 0.0 <= ur <= 1.0
