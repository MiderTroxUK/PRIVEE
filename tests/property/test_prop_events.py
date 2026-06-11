"""Propriétés Hypothesis des événements à impact calibré (E9 — Lot 9.5).

Couvre :mod:`supplyscore.domain.events` :

- bornes et monotonie de :func:`bayes_update`, point fixe k/n == p ;
- :func:`ema_update` reste entre l'ancienne valeur et l'observation ;
- pour CHAQUE type de :data:`EVENT_CALIBRATION`, avec des paramètres valides
  générés depuis ``EventSpec.fields`` (bornes/choices) sur des bundles
  aléatoires : impacts dans les bornes :data:`KPI_CONSTRAINTS`, jamais
  NaN/Inf, bundle d'entrée jamais modifié (pureté) ;
- :func:`weekly_decay` : décroissance stricte au-dessus du plancher bayésien
  p_inf = 1e-4 (point fixe de p -> p·26/27 borné), ``[]`` si le KPI est None.
"""

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
    EventSpec,
    bayes_update,
    compute_impacts,
    ema_update,
    weekly_decay,
)
from supplyscore.domain.models import KPIBundle

EVENT_TYPES = sorted(EVENT_CALIBRATION)

#: Bornes documentées de ``bayes_update`` (jamais 0 ni 1 : verrou bayésien).
BAYES_MIN, BAYES_MAX = 1e-4, 0.99

#: Champs numériques strictement positifs (borne ``minimum=0`` exclusive).
STRICT_POSITIVE = frozenset({"duree_arret_h", "retard_h", "duree_prevue_h", "nouvelle_demande"})

#: Plafond des champs et KPIs sans borne maximum déclarée.
CAP = 1e6


def make_bundle(values: dict[str, float | None]) -> KPIBundle:
    """Construit un KPIBundle à partir d'un dict chemin qualifié -> valeur."""
    bundle = KPIBundle()
    for path, value in values.items():
        block_name, field_name = path.split(".")
        setattr(getattr(bundle, block_name), field_name, value)
    return bundle


def field_strategy(fld: EventField) -> st.SearchStrategy[object]:
    """Stratégie de valeurs VALIDES pour un champ d'événement (bornes/choices)."""
    if fld.kind == "choice":
        return st.sampled_from(fld.choices)
    lo = fld.minimum if fld.minimum is not None else -CAP
    hi = fld.maximum if fld.maximum is not None else CAP
    if fld.name in STRICT_POSITIVE:
        lo = max(lo, 1e-3)  # la validation rejette les valeurs <= 0
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)


def params_strategy(spec: EventSpec) -> st.SearchStrategy[dict[str, object]]:
    """Stratégie de jeux de paramètres valides dérivée de ``spec.fields``."""
    return st.fixed_dictionaries({fld.name: field_strategy(fld) for fld in spec.fields})


def _kpi_value_strategy(lo: float | None, hi: float | None) -> st.SearchStrategy[float | None]:
    """Valeur de KPI : None (non renseigné) ou flottant valide dans ses bornes."""
    lo_eff = lo if lo is not None else 0.0
    hi_eff = hi if hi is not None else CAP
    return st.none() | st.floats(
        min_value=lo_eff, max_value=hi_eff, allow_nan=False, allow_infinity=False
    )


#: Bundle aléatoire : chaque KPI contraint est None ou une valeur dans ses bornes.
BUNDLE_VALUES = st.fixed_dictionaries(
    {path: _kpi_value_strategy(lo, hi) for path, (lo, hi, _unit) in KPI_CONSTRAINTS.items()}
)


class TestBayesUpdate:
    """Révision Beta-Bernoulli : bornes, monotonie et point fixe."""

    @given(
        p=st.floats(min_value=0.0, max_value=1.0),
        k=st.floats(min_value=0.0, max_value=1000.0),
        n=st.floats(min_value=0.0, max_value=1000.0),
    )
    def test_bornes_1e4_099(self, p: float, k: float, n: float) -> None:
        posterior = bayes_update(p, k, n)
        assert BAYES_MIN <= posterior <= BAYES_MAX
        assert math.isfinite(posterior)

    @given(
        p=st.floats(min_value=0.0, max_value=1.0),
        n=st.floats(min_value=0.0, max_value=1000.0),
        k_a=st.floats(min_value=0.0, max_value=1000.0),
        k_b=st.floats(min_value=0.0, max_value=1000.0),
    )
    def test_croissante_en_k_a_n_fixe(self, p: float, n: float, k_a: float, k_b: float) -> None:
        k_lo, k_hi = sorted((k_a, k_b))
        assert bayes_update(p, k_lo, n) <= bayes_update(p, k_hi, n)

    @given(
        p=st.floats(min_value=BAYES_MIN, max_value=BAYES_MAX),
        n=st.floats(min_value=1e-3, max_value=1000.0),
    )
    def test_point_fixe_k_sur_n_egal_p(self, p: float, n: float) -> None:
        # k/n == p : l'événement confirme le prior sans le déplacer.
        assert abs(bayes_update(p, p * n, n) - p) <= 1e-12


class TestEmaUpdate:
    """Lissage exponentiel : la valeur lissée reste entre old et obs."""

    @given(
        old=st.floats(min_value=-CAP, max_value=CAP),
        obs=st.floats(min_value=-CAP, max_value=CAP),
        lam=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_entre_old_et_obs(self, old: float, obs: float, lam: float) -> None:
        lisse = ema_update(old, obs, lam)
        tol = 1e-9 * (1.0 + abs(old) + abs(obs))
        assert min(old, obs) - tol <= lisse <= max(old, obs) + tol

    @given(
        obs=st.floats(min_value=-CAP, max_value=CAP),
        lam=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_initialisation_si_old_none(self, obs: float, lam: float) -> None:
        assert ema_update(None, obs, lam) == obs


class TestComputeImpacts:
    """Pour chaque type calibré : bornes KPI, finitude et pureté du bundle."""

    @pytest.mark.parametrize("event_type", EVENT_TYPES)
    @given(data=st.data())
    def test_impacts_bornes_finis_et_purete(self, event_type: str, data: st.DataObject) -> None:
        spec = EVENT_CALIBRATION[event_type]
        params = data.draw(params_strategy(spec), label="params")
        values = data.draw(BUNDLE_VALUES, label="kpis")
        bundle = make_bundle(values)
        snapshot = copy.deepcopy(bundle)

        impacts = compute_impacts(event_type, params, bundle)

        # Pureté : le bundle d'entrée n'est JAMAIS modifié.
        assert bundle == snapshot
        for impact in impacts:
            assert impact.kpi_path in KPI_CONSTRAINTS
            lo, hi, _unit = KPI_CONSTRAINTS[impact.kpi_path]
            assert math.isfinite(impact.new), f"{impact.kpi_path} : new non fini"
            if lo is not None:
                assert impact.new >= lo, f"{impact.kpi_path} : {impact.new} < {lo}"
            if hi is not None:
                assert impact.new <= hi, f"{impact.kpi_path} : {impact.new} > {hi}"
            assert impact.old is None or math.isfinite(impact.old)
            assert impact.old == values[impact.kpi_path]


class TestWeeklyDecay:
    """Semaine sans incident : érosion douce vers le plancher bayésien."""

    @given(p=st.floats(min_value=BAYES_MIN, max_value=1.0, exclude_min=True))
    def test_decroissance_stricte_au_dessus_du_plancher(self, p: float) -> None:
        # Point fixe de p -> max(p·n0/(n0+1), 1e-4) : p_inf = 1e-4, donc
        # décroissance STRICTE dès que p > 1e-4.
        bundle = make_bundle({"risk.failure_probability": p})
        snapshot = copy.deepcopy(bundle)
        impacts = weekly_decay(bundle)
        assert bundle == snapshot  # pureté
        assert len(impacts) == 1
        impact = impacts[0]
        assert impact.kpi_path == "risk.failure_probability"
        assert impact.old == p
        assert impact.new < p
        assert impact.new >= BAYES_MIN
        attendu = max(p * N0_PSEUDO_OBSERVATIONS / (N0_PSEUDO_OBSERVATIONS + 1.0), BAYES_MIN)
        assert impact.new == pytest.approx(attendu, abs=1e-12)

    def test_plancher_est_un_point_fixe(self) -> None:
        bundle = make_bundle({"risk.failure_probability": BAYES_MIN})
        impacts = weekly_decay(bundle)
        assert len(impacts) == 1
        assert impacts[0].new == BAYES_MIN

    def test_kpi_none_renvoie_liste_vide(self) -> None:
        assert weekly_decay(KPIBundle()) == []
