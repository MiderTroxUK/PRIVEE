"""Tests du cahier des charges structure (supplyscore.domain.specsheet)."""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.domain.specsheet import (
    CahierDesCharges,
    Deliverable,
    PenaltyClause,
    QualityRequirements,
    cdc_from_json,
    cdc_to_json,
)


def _full_cdc() -> CahierDesCharges:
    """CdC complet : 3 livrables, 2 penalites, normes et certifications."""
    return CahierDesCharges(
        deliverables=[
            Deliverable(name="Carter usiné", quantity=120.0, unit="pièces", milestone_id="m-proto"),
            Deliverable(name="Visserie inox", quantity=4.5, unit="kg", milestone_id="m-serie"),
            Deliverable(name="Dossier FAI", quantity=1.0, unit="lot"),
        ],
        budget_total=250_000.0,
        target_unit_cost=180.5,
        currency="EUR",
        quality=QualityRequirements(
            standards=["ISO 9001", "EN 9100"],
            certifications=["NADCAP traitement thermique"],
            max_scrap_rate=0.02,
            notes="Contrôle dimensionnel 100 % sur cote critique.",
        ),
        penalties=[
            PenaltyClause(
                kind="late_delivery",
                trigger="Retard > 5 jours ouvrés sur le jalon série",
                amount_per_day=500.0,
                cap_amount=25_000.0,
            ),
            PenaltyClause(
                kind="quality",
                trigger="Taux de rebut constaté > 2 %",
                cap_amount=10_000.0,
            ),
        ],
        notes="Incoterm DAP usine cliente.",
    )


# Round-trip


class TestRoundTrip:
    def test_round_trip_full(self):
        cdc = _full_cdc()
        rebuilt = cdc_from_json(cdc_to_json(cdc))
        assert rebuilt == cdc
        assert len(rebuilt.deliverables) == 3
        assert len(rebuilt.penalties) == 2
        assert rebuilt.quality.standards == ["ISO 9001", "EN 9100"]
        assert rebuilt.deliverables[2].milestone_id is None
        assert rebuilt.penalties[1].amount_per_day is None

    def test_round_trip_empty(self):
        rebuilt = cdc_from_json(cdc_to_json(CahierDesCharges()))
        assert rebuilt == CahierDesCharges()
        assert rebuilt.deliverables == []
        assert rebuilt.penalties == []
        assert rebuilt.quality == QualityRequirements()
        assert rebuilt.currency == "EUR"
        assert rebuilt.budget_total is None

    def test_max_scrap_rate_stays_float(self):
        rebuilt = cdc_from_json(cdc_to_json(_full_cdc()))
        assert isinstance(rebuilt.quality.max_scrap_rate, float)
        assert rebuilt.quality.max_scrap_rate == pytest.approx(0.02)

    def test_to_json_is_stable(self):
        # Cles triees : deux serialisations du meme objet sont identiques.
        assert cdc_to_json(_full_cdc()) == cdc_to_json(_full_cdc())


# Tolerance au schema


class TestSchemaTolerance:
    def test_unknown_keys_ignored_at_every_level(self):
        payload = json.loads(cdc_to_json(_full_cdc()))
        payload["future_field"] = {"nested": True}
        payload["deliverables"][0]["lead_time_weeks"] = 6
        payload["quality"]["ppm_target"] = 50
        payload["penalties"][0]["escalation"] = "comité mensuel"
        rebuilt = cdc_from_json(json.dumps(payload))
        assert rebuilt == _full_cdc()

    def test_missing_lists_become_empty(self):
        rebuilt = cdc_from_json('{"budget_total": 1000.0}')
        assert rebuilt.deliverables == []
        assert rebuilt.penalties == []
        assert rebuilt.quality == QualityRequirements()
        assert rebuilt.budget_total == pytest.approx(1000.0)

    def test_null_lists_become_empty(self):
        raw = '{"deliverables": null, "penalties": null, "quality": null, "notes": null}'
        rebuilt = cdc_from_json(raw)
        assert rebuilt == CahierDesCharges()

    def test_missing_quality_sublists_become_empty(self):
        rebuilt = cdc_from_json('{"quality": {"max_scrap_rate": 0.05}}')
        assert rebuilt.quality.standards == []
        assert rebuilt.quality.certifications == []
        assert isinstance(rebuilt.quality.max_scrap_rate, float)

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="invalide"):
            cdc_from_json("{pas du json")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="invalide"):
            cdc_from_json("")

    def test_non_object_json_raises_value_error(self):
        with pytest.raises(ValueError, match="objet"):
            cdc_from_json("[1, 2, 3]")


# Propriete : round-trip exact (hypothesis)

_text = st.text(max_size=30)
_finite = st.floats(allow_nan=False, allow_infinity=False)
_opt_finite = st.none() | _finite

_deliverables = st.builds(
    Deliverable,
    name=_text,
    quantity=_finite,
    unit=_text,
    milestone_id=st.none() | _text,
)
_quality = st.builds(
    QualityRequirements,
    standards=st.lists(_text, max_size=4),
    certifications=st.lists(_text, max_size=4),
    max_scrap_rate=_opt_finite,
    notes=_text,
)
_penalties = st.builds(
    PenaltyClause,
    kind=st.sampled_from(["late_delivery", "quality", "other"]),
    trigger=_text,
    amount_per_day=_opt_finite,
    cap_amount=_opt_finite,
)
_cdc = st.builds(
    CahierDesCharges,
    deliverables=st.lists(_deliverables, max_size=4),
    budget_total=_opt_finite,
    target_unit_cost=_opt_finite,
    currency=_text,
    quality=_quality,
    penalties=st.lists(_penalties, max_size=4),
    notes=_text,
)


@given(cdc=_cdc)
def test_round_trip_property(cdc: CahierDesCharges) -> None:
    assert cdc_from_json(cdc_to_json(cdc)) == cdc
