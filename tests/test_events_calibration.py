"""Tests de la typologie des événements à impact calibré (E2 — Lot 2.2)."""

from __future__ import annotations

import copy
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.domain.constraints import KPI_CONSTRAINTS
from supplyscore.domain.events import (
    EVENT_CALIBRATION,
    N0_PSEUDO_OBSERVATIONS,
    EventField,
    bayes_update,
    compute_impacts,
    ema_update,
    weekly_decay,
)
from supplyscore.domain.models import KPIBundle

TOL = 1e-4

# Chemins de KPI touchés par au moins un type d'événement.
TOUCHED_PATHS: tuple[str, ...] = (
    "network.demand",
    "inventory.flow_rate",
    "inventory.max_volume_m3",
    "time.lead_time_h",
    "time.lead_time_std_h",
    "cost.tariff",
    "cost.op_cost",
    "oee.availability",
    "oee.quality",
    "risk.failure_probability",
    "risk.recovery_time_h",
    "risk.severity",
    "risk.cost_volatility",
    "risk.env_exposure",
    "risk.political_risk",
)

# Bundle « plein » : tous les KPIs touchés sont renseignés avec des valeurs valides.
FULL_VALUES: dict[str, float] = {
    "network.demand": 120.0,
    "inventory.flow_rate": 10.0,
    "inventory.max_volume_m3": 500.0,
    "time.lead_time_h": 48.0,
    "time.lead_time_std_h": 6.0,
    "cost.tariff": 1.05,
    "cost.op_cost": 100.0,
    "oee.availability": 0.95,
    "oee.quality": 0.98,
    "risk.failure_probability": 0.02,
    "risk.recovery_time_h": 12.0,
    "risk.severity": 0.2,
    "risk.cost_volatility": 0.1,
    "risk.env_exposure": 0.1,
    "risk.political_risk": 0.1,
}

# Jeux de paramètres valides, un par type d'événement.
VALID_PARAMS: dict[str, dict[str, object]] = {
    "panne_machine": {"duree_arret_h": 24.0, "gravite": "majeure"},
    "retard_fournisseur": {"retard_h": 12.0},
    "greve": {"duree_prevue_h": 48.0, "part_effectif": 0.5},
    "hausse_tarif": {"pct": 12.0},
    "rupture_matiere": {"duree_prevue_h": 72.0, "criticite": 0.6},
    "accident": {"duree_arret_h": 8.0, "gravite": "critique"},
    "non_conformite_qualite": {"taux_rebut_obs": 0.05},
    "perturbation_transport": {"retard_h": 24.0, "surcout": 1500.0},
    "instabilite_politique": {"niveau": 0.7},
    "cyber_incident": {"duree_arret_h": 36.0},
    "hausse_energie": {"pct": 30.0},
    "alerte_financiere_fournisseur": {"gravite": "procedure"},
    "perte_capacite": {"pct_volume_perdu": 0.25},
    "pic_demande": {"nouvelle_demande": 250.0},
}

EVENT_TYPES = sorted(EVENT_CALIBRATION)

# Champs numériques strictement positifs (borne minimum=0 exclusive).
STRICT_POSITIVE = {"duree_arret_h", "retard_h", "duree_prevue_h", "nouvelle_demande"}


def make_bundle(values: dict[str, float | None]) -> KPIBundle:
    """Construit un KPIBundle à partir d'un dict chemin -> valeur."""
    bundle = KPIBundle()
    for path, value in values.items():
        block_name, field_name = path.split(".")
        setattr(getattr(bundle, block_name), field_name, value)
    return bundle


def full_bundle() -> KPIBundle:
    return make_bundle(dict(FULL_VALUES))


def impact_for(impacts: list, kpi_path: str):
    matching = [impact for impact in impacts if impact.kpi_path == kpi_path]
    assert matching, f"aucun impact sur {kpi_path}"
    return matching[0]


# --- Stratégies Hypothesis -----------------------------------------------------------


def field_strategy(field: EventField) -> st.SearchStrategy:
    """Valeur valide aléatoire pour un champ d'événement."""
    if field.kind == "choice":
        return st.sampled_from(field.choices)
    lo = field.minimum if field.minimum is not None else -1e6
    hi = field.maximum if field.maximum is not None else 1e6
    return st.floats(
        min_value=lo,
        max_value=hi,
        exclude_min=field.name in STRICT_POSITIVE,
        allow_nan=False,
        allow_infinity=False,
    )


def kpi_value_strategy(kpi_path: str) -> st.SearchStrategy:
    """Valeur de KPI aléatoire (None ou valeur dans les bornes KPI_CONSTRAINTS)."""
    lo, hi, _unit = KPI_CONSTRAINTS[kpi_path]
    low = lo if lo is not None else 0.0
    high = hi if hi is not None else 1e6
    return st.one_of(
        st.none(),
        st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False),
    )


# --- Opérateurs de calibration -------------------------------------------------------


class TestBayesUpdate:
    def test_valeurs_calibrees(self):
        # p=0.02, N0=26 — cas chiffrés du PLAN (gravités panne/accident).
        assert bayes_update(0.02, 1.0, 1.0) == pytest.approx(0.0563, abs=TOL)  # majeure
        assert bayes_update(0.02, 2.0, 2.0) == pytest.approx(0.09, abs=TOL)  # critique
        assert bayes_update(0.02, 0.5, 1.0) == pytest.approx(0.0378, abs=TOL)  # mineure
        assert bayes_update(0.02, 0.0, 1.0) == pytest.approx(0.01926, abs=TOL)  # semaine calme

    def test_n0_par_defaut(self):
        assert N0_PSEUDO_OBSERVATIONS == 26.0
        assert bayes_update(0.02, 1.0, 1.0) == bayes_update(0.02, 1.0, 1.0, n0=26.0)

    @given(
        p=st.floats(min_value=1e-4, max_value=0.99),
        k=st.floats(min_value=0.0, max_value=10.0),
        n=st.floats(min_value=0.5, max_value=10.0),
    )
    def test_dans_ouvert_0_1(self, p: float, k: float, n: float):
        result = bayes_update(p, k, n)
        assert 0.0 < result < 1.0

    @given(
        p=st.floats(min_value=1e-4, max_value=0.99),
        k1=st.floats(min_value=0.0, max_value=10.0),
        k2=st.floats(min_value=0.0, max_value=10.0),
        n=st.floats(min_value=0.5, max_value=10.0),
    )
    def test_croissante_en_k(self, p: float, k1: float, k2: float, n: float):
        lo, hi = min(k1, k2), max(k1, k2)
        assert bayes_update(p, lo, n) <= bayes_update(p, hi, n)

    def test_croissance_stricte_hors_bornes(self):
        assert bayes_update(0.02, 0.0, 1.0) < bayes_update(0.02, 0.5, 1.0)
        assert bayes_update(0.02, 0.5, 1.0) < bayes_update(0.02, 1.0, 1.0)

    @given(
        p=st.floats(min_value=1e-4, max_value=0.99),
        n=st.floats(min_value=0.5, max_value=10.0),
    )
    def test_point_fixe_si_k_sur_n_egale_p(self, p: float, n: float):
        # k/n == p -> l'événement confirme le prior sans le déplacer.
        assert bayes_update(p, p * n, n) == pytest.approx(p, abs=1e-12)


class TestEmaUpdate:
    def test_formule(self):
        assert ema_update(0.95, 1.0 - 24.0 / 168.0, 0.3) == pytest.approx(0.92214, abs=TOL)
        assert ema_update(10.0, 20.0, 0.4) == pytest.approx(14.0, abs=1e-12)

    def test_old_none_initialise(self):
        assert ema_update(None, 7.5, 0.4) == 7.5


# --- Cas chiffrés du PLAN ------------------------------------------------------------


class TestCasChiffres:
    def test_panne_majeure_failure_probability(self):
        impacts = compute_impacts(
            "panne_machine", {"duree_arret_h": 24.0, "gravite": "majeure"}, full_bundle()
        )
        assert impact_for(impacts, "risk.failure_probability").new == pytest.approx(0.0563, abs=TOL)

    def test_panne_critique_failure_probability(self):
        impacts = compute_impacts(
            "panne_machine", {"duree_arret_h": 24.0, "gravite": "critique"}, full_bundle()
        )
        assert impact_for(impacts, "risk.failure_probability").new == pytest.approx(0.09, abs=TOL)

    def test_panne_mineure_failure_probability(self):
        impacts = compute_impacts(
            "panne_machine", {"duree_arret_h": 24.0, "gravite": "mineure"}, full_bundle()
        )
        assert impact_for(impacts, "risk.failure_probability").new == pytest.approx(0.0378, abs=TOL)

    def test_weekly_decay(self):
        impacts = weekly_decay(full_bundle())  # p = 0.02
        assert len(impacts) == 1
        impact = impacts[0]
        assert impact.kpi_path == "risk.failure_probability"
        assert impact.old == pytest.approx(0.02)
        assert impact.new == pytest.approx(0.01926, abs=TOL)

    def test_weekly_decay_p_none(self):
        assert weekly_decay(KPIBundle()) == []

    def test_hausse_tarif_12_pct(self):
        impacts = compute_impacts("hausse_tarif", {"pct": 12.0}, full_bundle())  # tariff=1.05
        impact = impact_for(impacts, "cost.tariff")
        assert impact.old == pytest.approx(1.05)
        assert impact.new == pytest.approx(1.176, abs=1e-9)

    def test_panne_majeure_availability(self):
        impacts = compute_impacts(
            "panne_machine", {"duree_arret_h": 24.0, "gravite": "majeure"}, full_bundle()
        )
        impact = impact_for(impacts, "oee.availability")
        # EMA(0.95, 1 - 24/168, 0.3) = 0.95*0.7 + 0.8571428*0.3
        assert impact.new == pytest.approx(0.92214, abs=TOL)


# --- compute_impacts : erreurs et couverture des 14 types ----------------------------


class TestComputeImpactsValidation:
    def test_type_inconnu(self):
        with pytest.raises(ValueError, match="inconnu"):
            compute_impacts("eruption_volcanique", {}, full_bundle())

    def test_parametre_manquant(self):
        with pytest.raises(ValueError, match="manquant"):
            compute_impacts("panne_machine", {"duree_arret_h": 24.0}, full_bundle())

    def test_parametre_inconnu(self):
        with pytest.raises(ValueError, match="inconnu"):
            compute_impacts("pic_demande", {"nouvelle_demande": 10.0, "extra": 1}, full_bundle())

    @pytest.mark.parametrize(
        ("event_type", "params"),
        [
            ("panne_machine", {"duree_arret_h": 0.0, "gravite": "majeure"}),  # durée nulle
            ("panne_machine", {"duree_arret_h": -5.0, "gravite": "majeure"}),
            ("panne_machine", {"duree_arret_h": 24.0, "gravite": "enorme"}),  # choix inconnu
            ("panne_machine", {"duree_arret_h": "demain", "gravite": "majeure"}),
            ("panne_machine", {"duree_arret_h": float("nan"), "gravite": "majeure"}),
            ("greve", {"duree_prevue_h": 48.0, "part_effectif": 1.5}),  # ratio > 1
            ("greve", {"duree_prevue_h": 48.0, "part_effectif": -0.1}),
            ("hausse_tarif", {"pct": 501.0}),  # > max 500
            ("hausse_tarif", {"pct": -101.0}),  # < min -100
            ("perturbation_transport", {"retard_h": 24.0, "surcout": -1.0}),
            ("pic_demande", {"nouvelle_demande": 0.0}),
            ("alerte_financiere_fournisseur", {"gravite": "panique"}),
        ],
    )
    def test_parametre_invalide_ou_hors_bornes(self, event_type: str, params: dict):
        with pytest.raises(ValueError):
            compute_impacts(event_type, params, full_bundle())

    @pytest.mark.parametrize("event_type", EVENT_TYPES)
    def test_chaque_type_produit_un_impact_sur_bundle_plein(self, event_type: str):
        impacts = compute_impacts(event_type, VALID_PARAMS[event_type], full_bundle())
        assert len(impacts) >= 1
        for impact in impacts:
            assert impact.kpi_path in KPI_CONSTRAINTS
            assert math.isfinite(impact.new)
            assert impact.rule  # règle documentée en français

    def test_les_14_types_sont_declares(self):
        assert len(EVENT_CALIBRATION) == 14
        assert set(VALID_PARAMS) == set(EVENT_CALIBRATION)
        for event_type, spec in EVENT_CALIBRATION.items():
            assert spec.event_type == event_type
            assert spec.label_fr and spec.description_fr
            assert spec.fields


# --- Impacts « ignorer » quand le KPI source est None --------------------------------


class TestImpactsIgnoresSiNone:
    def test_greve_sans_availability(self):
        # oee.availability absent -> ignoré ; le lead time est en revanche
        # TOUJOURS impacté (initialisé à la durée d'arrêt effective).
        bundle = KPIBundle()
        impacts = compute_impacts("greve", {"duree_prevue_h": 48.0, "part_effectif": 0.5}, bundle)
        assert [impact.kpi_path for impact in impacts] == ["risk.severity", "time.lead_time_h"]
        assert impacts[0].new == pytest.approx(0.5)

    def test_hausse_energie_sans_op_cost(self):
        impacts = compute_impacts("hausse_energie", {"pct": 30.0}, KPIBundle())
        assert [impact.kpi_path for impact in impacts] == ["risk.cost_volatility"]

    def test_perte_capacite_sans_volume(self):
        impacts = compute_impacts("perte_capacite", {"pct_volume_perdu": 0.25}, KPIBundle())
        assert [impact.kpi_path for impact in impacts] == ["risk.env_exposure"]

    def test_rupture_matiere_sans_flow_rate(self):
        impacts = compute_impacts(
            "rupture_matiere", {"duree_prevue_h": 72.0, "criticite": 0.6}, KPIBundle()
        )
        paths = [impact.kpi_path for impact in impacts]
        assert "inventory.flow_rate" not in paths
        assert paths == ["risk.failure_probability", "risk.severity", "time.lead_time_h"]

    def test_bayes_prior_par_defaut_si_none(self):
        # failure_probability None -> prior 0.02 documenté dans la règle.
        impacts = compute_impacts("cyber_incident", {"duree_arret_h": 12.0}, KPIBundle())
        impact = impact_for(impacts, "risk.failure_probability")
        assert impact.old is None
        assert impact.new == pytest.approx(bayes_update(0.02, 1.0, 1.0), abs=1e-12)
        assert "0.02" in impact.rule

    def test_retard_fournisseur_lead_time_none(self):
        impacts = compute_impacts("retard_fournisseur", {"retard_h": 12.0}, KPIBundle())
        impact = impact_for(impacts, "time.lead_time_h")
        assert impact.old is None
        assert impact.new == pytest.approx(12.0)  # old None -> obs = retard

    def test_hausse_tarif_tariff_none(self):
        impacts = compute_impacts("hausse_tarif", {"pct": 12.0}, KPIBundle())
        impact = impact_for(impacts, "cost.tariff")
        assert impact.old is None
        assert impact.new == pytest.approx(1.12)  # base neutre 1

    def test_perturbation_transport_op_cost_none(self):
        impacts = compute_impacts(
            "perturbation_transport", {"retard_h": 24.0, "surcout": 1500.0}, KPIBundle()
        )
        impact = impact_for(impacts, "cost.op_cost")
        assert impact.old is None
        assert impact.new == pytest.approx(1500.0)  # base 0 + surcoût


# --- Propriétés : bornes, finitude, pureté -------------------------------------------


class TestProprietes:
    @pytest.mark.parametrize("event_type", EVENT_TYPES)
    @given(data=st.data())
    def test_impacts_toujours_dans_les_bornes(self, event_type: str, data: st.DataObject):
        spec = EVENT_CALIBRATION[event_type]
        params = {field.name: data.draw(field_strategy(field)) for field in spec.fields}
        values = {path: data.draw(kpi_value_strategy(path), label=path) for path in TOUCHED_PATHS}
        bundle = make_bundle(values)

        impacts = compute_impacts(event_type, params, bundle)

        for impact in impacts:
            assert math.isfinite(impact.new), f"{impact.kpi_path} non fini : {impact.new}"
            lo, hi, _unit = KPI_CONSTRAINTS[impact.kpi_path]
            if lo is not None:
                assert impact.new >= lo
            if hi is not None:
                assert impact.new <= hi

    @pytest.mark.parametrize("event_type", EVENT_TYPES)
    def test_purete_bundle_jamais_modifie(self, event_type: str):
        bundle = full_bundle()
        avant = copy.deepcopy(bundle)
        compute_impacts(event_type, VALID_PARAMS[event_type], bundle)
        assert bundle == avant

    def test_purete_weekly_decay(self):
        bundle = full_bundle()
        avant = copy.deepcopy(bundle)
        weekly_decay(bundle)
        assert bundle == avant

    @pytest.mark.parametrize("event_type", EVENT_TYPES)
    @given(data=st.data())
    def test_purete_sur_bundle_aleatoire(self, event_type: str, data: st.DataObject):
        spec = EVENT_CALIBRATION[event_type]
        params = {field.name: data.draw(field_strategy(field)) for field in spec.fields}
        values = {path: data.draw(kpi_value_strategy(path), label=path) for path in TOUCHED_PATHS}
        bundle = make_bundle(values)
        avant = copy.deepcopy(bundle)
        compute_impacts(event_type, params, bundle)
        assert bundle == avant


# --- Chaîne causale : choc de capacité -> lead time ----------------------------------


class TestChaineCausaleArret:
    """Tout choc qui immobilise la production doit atteindre ``time.lead_time_h``.

    Régression du défaut structurel mesuré sur la campagne HÉLIOS : le bloc
    temporel du modèle Ur ne lit que ``time.lead_time_h``, or aucun choc de
    CAPACITÉ n'y touchait. P(jalon raté) valait 0,0 % pour un nœud à l'arrêt
    quatre semaines, dont le jalon a effectivement été raté.
    """

    #: Chocs immobilisants -> durée d'arrêt EFFECTIVE attendue (heures).
    CHOCS_IMMOBILISANTS: dict[str, float] = {
        "panne_machine": 24.0,           # duree_arret_h
        "accident": 8.0,                 # duree_arret_h
        "cyber_incident": 36.0,          # duree_arret_h
        "greve": 48.0 * 0.5,             # duree_prevue_h x part_effectif
        "rupture_matiere": 72.0 * 0.6,   # duree_prevue_h x criticite
    }

    @pytest.mark.parametrize("event_type", sorted(CHOCS_IMMOBILISANTS))
    def test_arret_allonge_le_lead_time(self, event_type: str):
        bundle = make_bundle({"time.lead_time_h": 200.0})
        impacts = compute_impacts(event_type, VALID_PARAMS[event_type], bundle)
        paths = [impact.kpi_path for impact in impacts]
        assert "time.lead_time_h" in paths, f"{event_type} n'atteint pas le bloc temporel"
        assert impact_for(impacts, "time.lead_time_h").new > 200.0

    @pytest.mark.parametrize("event_type", sorted(CHOCS_IMMOBILISANTS))
    def test_duree_effective_lissee_lambda_04(self, event_type: str):
        # EMA(obs = ancien + duree_effective, lambda = 0.4), comme retard_fournisseur.
        duree = self.CHOCS_IMMOBILISANTS[event_type]
        bundle = make_bundle({"time.lead_time_h": 200.0})
        impact = impact_for(
            compute_impacts(event_type, VALID_PARAMS[event_type], bundle), "time.lead_time_h"
        )
        assert impact.new == pytest.approx(200.0 + 0.4 * duree, abs=TOL)

    @pytest.mark.parametrize("event_type", sorted(CHOCS_IMMOBILISANTS))
    def test_lead_time_absent_initialise_a_la_duree(self, event_type: str):
        impact = impact_for(
            compute_impacts(event_type, VALID_PARAMS[event_type], KPIBundle()),
            "time.lead_time_h",
        )
        assert impact.old is None
        assert impact.new == pytest.approx(self.CHOCS_IMMOBILISANTS[event_type], abs=TOL)

    def test_monotone_en_duree_arret(self):
        # Un arrêt plus long ne peut pas produire un lead time plus court.
        precedent = 0.0
        for duree in (1.0, 24.0, 168.0, 672.0):
            bundle = make_bundle({"time.lead_time_h": 200.0})
            impact = impact_for(
                compute_impacts("accident", {"duree_arret_h": duree, "gravite": "critique"}, bundle),
                "time.lead_time_h",
            )
            assert impact.new >= precedent
            precedent = impact.new

    def test_perte_capacite_ne_touche_pas_le_lead_time(self):
        # Exclusion VOULUE : ce qui est perdu est du volume de STOCKAGE, pas
        # du temps de production — la saturation est portée par u_cap.
        impacts = compute_impacts("perte_capacite", VALID_PARAMS["perte_capacite"], full_bundle())
        assert "time.lead_time_h" not in [impact.kpi_path for impact in impacts]
