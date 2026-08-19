"""Tests de la typologie des evenements a impact calibre (E2 - Lot 2.2)."""

from __future__ import annotations

import copy
import math
from typing import ClassVar

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.domain.constraints import KPI_CONSTRAINTS
from supplyscore.domain.events import (
    EVENT_CALIBRATION,
    LAMBDA_ARRET,
    N0_PSEUDO_OBSERVATIONS,
    EventField,
    bayes_update,
    compute_impacts,
    ema_update,
    weekly_decay,
)
from supplyscore.domain.models import KPIBundle

TOL = 1e-4

# Chemins de KPI touches par au moins un type d'evenement.
TOUCHED_PATHS: tuple[str, ...] = (
    "network.demand",
    "inventory.flow_rate",
    "inventory.max_volume_m3",
    "time.delay_h",
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

# Bundle " plein " : tous les KPIs touches sont renseignes avec des valeurs valides.
FULL_VALUES: dict[str, float] = {
    "network.demand": 120.0,
    "inventory.flow_rate": 10.0,
    "inventory.max_volume_m3": 500.0,
    "time.delay_h": 30.0,
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

# Jeux de parametres valides, un par type d'evenement.
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

# Champs numeriques strictement positifs (borne minimum=0 exclusive).
STRICT_POSITIVE = {"duree_arret_h", "retard_h", "duree_prevue_h", "nouvelle_demande"}


def make_bundle(values: dict[str, float | None]) -> KPIBundle:
    """Construit un KPIBundle a partir d'un dict chemin -> valeur."""
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


# Strategies Hypothesis


def field_strategy(field: EventField) -> st.SearchStrategy:
    """Valeur valide aleatoire pour un champ d'evenement."""
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
    """Valeur de KPI aleatoire (None ou valeur dans les bornes KPI_CONSTRAINTS)."""
    lo, hi, _unit = KPI_CONSTRAINTS[kpi_path]
    low = lo if lo is not None else 0.0
    high = hi if hi is not None else 1e6
    return st.one_of(
        st.none(),
        st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False),
    )


# Operateurs de calibration


class TestBayesUpdate:
    def test_valeurs_calibrees(self):
        # p=0.02, N0=26 - cas chiffres du PLAN (gravites panne/accident).
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
        # k/n == p -> l'evenement confirme le prior sans le deplacer.
        assert bayes_update(p, p * n, n) == pytest.approx(p, abs=1e-12)


class TestEmaUpdate:
    def test_formule(self):
        assert ema_update(0.95, 1.0 - 24.0 / 168.0, 0.3) == pytest.approx(0.92214, abs=TOL)
        assert ema_update(10.0, 20.0, 0.4) == pytest.approx(14.0, abs=1e-12)

    def test_old_none_initialise(self):
        assert ema_update(None, 7.5, 0.4) == 7.5


# Cas chiffres du PLAN


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

    def test_weekly_decay(self, monkeypatch):
        # Deux effets d'une semaine sans incident : erosion du risque ET rattrapage du retard accumule (delay_h = 30 h). Le second n'existe QUE si un rattrapage est effectivement parametre : on le force ici, le defaut livre etant 0.0 (cf. test_weekly_decay_sans_rattrapage).
        monkeypatch.setattr("supplyscore.domain.events.RATTRAPAGE_HEBDO", 0.25)
        impacts = weekly_decay(full_bundle())  # p = 0.02, delay = 30 h
        assert [i.kpi_path for i in impacts] == [
            "risk.failure_probability",
            "time.delay_h",
        ]
        assert impacts[0].old == pytest.approx(0.02)
        assert impacts[0].new == pytest.approx(0.01926, abs=TOL)
        assert impacts[1].old == pytest.approx(30.0)
        assert impacts[1].new == pytest.approx(30.0 * 0.75, abs=TOL)

    def test_weekly_decay_sans_rattrapage_n_emet_aucun_impact_nul(self, monkeypatch):
        # RATTRAPAGE_HEBDO = 0 (le defaut calibre) : le retard ne bouge pas, et AUCUN impact n'est emis pour lui. Emettre " retard -> retard " ferait annoncer a l'operateur un rattrapage qui n'a pas eu lieu : la page hebdo compte les impacts RETOURNES pour composer son message.
        monkeypatch.setattr("supplyscore.domain.events.RATTRAPAGE_HEBDO", 0.0)
        impacts = weekly_decay(full_bundle())
        assert [i.kpi_path for i in impacts] == ["risk.failure_probability"]
        assert all(i.old != i.new for i in impacts)

    def test_weekly_decay_p_none(self):
        assert weekly_decay(KPIBundle()) == []

    def test_weekly_decay_sans_retard_residuel(self):
        # time.delay_h absent ou nul : rien a rattraper, un seul impact.
        bundle = make_bundle({"risk.failure_probability": 0.02})
        assert [i.kpi_path for i in weekly_decay(bundle)] == ["risk.failure_probability"]
        bundle_zero = make_bundle({"risk.failure_probability": 0.02, "time.delay_h": 0.0})
        assert [i.kpi_path for i in weekly_decay(bundle_zero)] == ["risk.failure_probability"]

    def test_weekly_decay_retard_seul(self, monkeypatch):
        # Seul le retard est renseigne : il est rattrape quand meme, des lors qu'un taux de rattrapage est parametre.
        monkeypatch.setattr("supplyscore.domain.events.RATTRAPAGE_HEBDO", 0.25)
        impacts = weekly_decay(make_bundle({"time.delay_h": 100.0}))
        assert [i.kpi_path for i in impacts] == ["time.delay_h"]
        assert impacts[0].new == pytest.approx(75.0, abs=TOL)

    def test_weekly_decay_retard_seul_sans_rattrapage(self, monkeypatch):
        # Rien a eroder, rien a rattraper : aucun impact du tout.
        monkeypatch.setattr("supplyscore.domain.events.RATTRAPAGE_HEBDO", 0.0)
        assert weekly_decay(make_bundle({"time.delay_h": 100.0})) == []

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


# compute_impacts : erreurs et couverture des 14 types


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
            ("panne_machine", {"duree_arret_h": 0.0, "gravite": "majeure"}),  # duree nulle
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
            assert impact.rule  # regle documentee en francais

    def test_les_14_types_sont_declares(self):
        assert len(EVENT_CALIBRATION) == 14
        assert set(VALID_PARAMS) == set(EVENT_CALIBRATION)
        for event_type, spec in EVENT_CALIBRATION.items():
            assert spec.event_type == event_type
            assert spec.label_fr and spec.description_fr
            assert spec.fields


# Impacts " ignorer " quand le KPI source est None


class TestImpactsIgnoresSiNone:
    def test_greve_sans_availability(self):
        # oee.availability absent -> ignore ; le temps perdu est en revanche TOUJOURS enregistre (initialise a la duree d'arret effective).
        bundle = KPIBundle()
        impacts = compute_impacts("greve", {"duree_prevue_h": 48.0, "part_effectif": 0.5}, bundle)
        assert [impact.kpi_path for impact in impacts] == [
            "risk.severity",
            "time.delay_h",
        ]
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
        assert paths == ["risk.failure_probability", "risk.severity", "time.delay_h"]

    def test_bayes_prior_par_defaut_si_none(self):
        # failure_probability None -> prior 0.02 documente dans la regle.
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
        assert impact.new == pytest.approx(1500.0)  # base 0 + surcout


# Proprietes : bornes, finitude, purete


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


# Chaine causale : choc de capacite -> temps perdu -> risque de jalon


class TestChaineCausaleArret:
    """Tout choc immobilisant doit accumuler du retard dans ``time.delay_h``.

    Regression du defaut structurel mesure sur la campagne HELIOS : les trois
    estimateurs de P(jalon rate) modelisent l'achevement comme
    ``t + (1 - avancement)*lead_time + delay_h``, or aucun choc de CAPACITE
    n'alimentait le dernier terme. P(jalon rate) valait 0,0 % pour un noeud a
    l'arret quatre semaines, dont le jalon a effectivement ete rate.

    Deux regressions distinctes sont verrouillees ici.

    1. **Le KPI cible est ``time.delay_h``, PAS ``time.lead_time_h``.** Un arret
       ne rallonge pas le cycle, il en decale l'achevement. Router l'arret dans
       le lead time le ferait multiplier par ``1 - avancement``, donc evaporer
       sur les jalons proches de l'echeance (NovaFab retombait de 84,6 % a
       0,0 % sur un jalon reellement rate).
    2. **``time.delay_h`` n'est PAS ``risk.recovery_time_h``.** Le second est un
       PARAMETRE de risque pose en referentiel par noeud (26 semaines de
       requalification aeronautique) ; le premier est un ETAT qui demarre a
       zero. Les confondre declarait le noeud le plus prudent comme le plus en
       retard : AvioSys sortait ``u_time = 1.0`` des le tour 0.
    """

    #: Chocs immobilisants -> duree d'arret EFFECTIVE attendue (heures).
    CHOCS_IMMOBILISANTS: ClassVar[dict[str, float]] = {
        "panne_machine": 24.0,  # duree_arret_h
        "accident": 8.0,  # duree_arret_h
        "cyber_incident": 36.0,  # duree_arret_h
        "greve": 48.0 * 0.5,  # duree_prevue_h x part_effectif
        "rupture_matiere": 72.0 * 0.6,  # duree_prevue_h x criticite
    }

    @pytest.mark.parametrize("event_type", sorted(CHOCS_IMMOBILISANTS))
    def test_arret_accumule_du_retard(self, event_type: str):
        impacts = compute_impacts(event_type, VALID_PARAMS[event_type], KPIBundle())
        paths = [impact.kpi_path for impact in impacts]
        assert "time.delay_h" in paths, f"{event_type} n'accumule aucun retard"

    @pytest.mark.parametrize("event_type", sorted(CHOCS_IMMOBILISANTS))
    def test_retard_sajoute_au_solde(self, event_type: str):
        # CUMUL : nouveau = ancien + LAMBDA_ARRET x duree_effective.
        duree = self.CHOCS_IMMOBILISANTS[event_type]
        bundle = make_bundle({"time.delay_h": 10.0})
        impact = impact_for(
            compute_impacts(event_type, VALID_PARAMS[event_type], bundle), "time.delay_h"
        )
        assert impact.new == pytest.approx(10.0 + LAMBDA_ARRET * duree, abs=TOL)

    @pytest.mark.parametrize("event_type", sorted(CHOCS_IMMOBILISANTS))
    def test_kpi_absent_demarre_a_zero(self, event_type: str):
        impact = impact_for(
            compute_impacts(event_type, VALID_PARAMS[event_type], KPIBundle()), "time.delay_h"
        )
        assert impact.old is None
        assert impact.new == pytest.approx(
            LAMBDA_ARRET * self.CHOCS_IMMOBILISANTS[event_type], abs=TOL
        )

    def test_deux_chocs_se_cumulent(self):
        # Deux pannes ne s'annulent pas : c'est toute la difference avec une EMA.
        params = {"duree_arret_h": 100.0, "gravite": "majeure"}
        bundle = make_bundle({"time.delay_h": 0.0})
        premier = impact_for(compute_impacts("panne_machine", params, bundle), "time.delay_h").new
        bundle2 = make_bundle({"time.delay_h": premier})
        second = impact_for(compute_impacts("panne_machine", params, bundle2), "time.delay_h").new
        assert premier == pytest.approx(LAMBDA_ARRET * 100.0, abs=TOL)
        assert second == pytest.approx(2 * LAMBDA_ARRET * 100.0, abs=TOL)

    def test_monotone_en_duree_arret(self):
        precedent = 0.0
        for duree in (1.0, 24.0, 168.0, 672.0):
            impact = impact_for(
                compute_impacts(
                    "accident", {"duree_arret_h": duree, "gravite": "critique"}, KPIBundle()
                ),
                "time.delay_h",
            )
            assert impact.new >= precedent
            precedent = impact.new

    @pytest.mark.parametrize("event_type", sorted(CHOCS_IMMOBILISANTS))
    def test_arret_ne_rallonge_pas_le_cycle(self, event_type: str):
        impacts = compute_impacts(event_type, VALID_PARAMS[event_type], full_bundle())
        assert "time.lead_time_h" not in [impact.kpi_path for impact in impacts]

    @pytest.mark.parametrize("event_type", ("panne_machine", "accident"))
    def test_recovery_time_reste_un_parametre_de_risque(self, event_type: str):
        # Panne et accident continuent d'alimenter risk.recovery_time_h par EMA : c'est le temps de recuperation ESTIME, pas le retard subi. Les deux impacts coexistent et portent sur des champs distincts.
        impacts = compute_impacts(event_type, VALID_PARAMS[event_type], full_bundle())
        paths = [impact.kpi_path for impact in impacts]
        assert "risk.recovery_time_h" in paths
        assert "time.delay_h" in paths

    @pytest.mark.parametrize("event_type", ("retard_fournisseur", "perturbation_transport"))
    def test_retards_de_flux_rallongent_bien_le_cycle(self, event_type: str):
        # Distinction symetrique : ces deux-la rendent le processus durablement plus lent, ils vont donc sur le lead time et NON sur le retard subi.
        impacts = compute_impacts(event_type, VALID_PARAMS[event_type], full_bundle())
        paths = [impact.kpi_path for impact in impacts]
        assert "time.lead_time_h" in paths
        assert "time.delay_h" not in paths

    def test_perte_capacite_ne_touche_aucun_terme_temporel(self):
        # Exclusion VOULUE : ce qui est perdu est du volume de STOCKAGE, pas du temps de production - la saturation est portee par u_cap.
        impacts = compute_impacts("perte_capacite", VALID_PARAMS["perte_capacite"], full_bundle())
        paths = [impact.kpi_path for impact in impacts]
        assert "time.lead_time_h" not in paths
        assert "time.delay_h" not in paths
