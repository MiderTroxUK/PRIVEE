"""Tests des form-builders partages (wizard d'onboarding + fiche noeud).

Aucun serveur Dash : les formulaires sont construits en memoire, leurs ids
inspectes en parcourant l'arbre de composants, et les parseurs inverses sont
testes comme fonctions pures.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dash import html

from supplyscore.core import bipolar_to_saaty, score_6_to_9
from supplyscore.domain.constraints import KPI_CONSTRAINTS
from supplyscore.domain.milestones import Milestone
from supplyscore.domain.models import KPIBundle
from supplyscore.domain.specsheet import CahierDesCharges, Deliverable, QualityRequirements
from supplyscore.web_ui.components.forms_node import (
    ahp_form,
    cdc_form,
    deliverable_row,
    identity_form,
    kpi_guided_form,
    milestone_row,
    parse_ahp,
    parse_cdc,
    parse_identity,
    parse_kpis,
)
from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS, PAIRS

CONTEXTS = ["onb", "fiche"]


# Helpers d'inspection de l'arbre de composants


def _walk(component):
    """Itere sur tous les composants Dash de l'arbre (racine incluse)."""
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if hasattr(child, "to_plotly_json"):
            yield from _walk(child)


def _ids(component):
    """Tous les ids de l'arbre - dict ids normalises en tuples (type, index)."""
    found = []
    for comp in _walk(component):
        id_ = getattr(comp, "id", None)
        if id_ is None:
            continue
        found.append((id_["type"], id_["index"]) if isinstance(id_, dict) else id_)
    return found


def _find(component, target_id):
    """Composant portant exactement ``target_id`` (assert s'il est introuvable)."""
    for comp in _walk(component):
        if getattr(comp, "id", None) == target_id:
            return comp
    raise AssertionError(f"id introuvable dans l'arbre : {target_id!r}")


def _find_by_type(component, pattern_type):
    """Composants dont l'id pattern-matching a le type ``pattern_type``."""
    return [
        comp
        for comp in _walk(component)
        if isinstance(getattr(comp, "id", None), dict) and comp.id["type"] == pattern_type
    ]


# identity_form


@pytest.mark.parametrize("ctx", CONTEXTS)
def test_identity_form_builds_with_expected_ids(ctx):
    tree = str(identity_form(ctx))
    for suffix in ("name", "label", "location", "tags", "targets", "gamma", "beta", "arckind"):
        assert f"{ctx}-ident-{suffix}" in tree


def test_identity_form_prefills_fields_and_free_tags():
    form = identity_form(
        "fiche",
        name="Fonderie Sud",
        label="Factory",
        location="Lyon, France",
        selected_tags=["alu", "tag-libre"],
        tag_options=[{"label": "Aluminium", "value": "alu"}],
        node_options=[{"label": "Client A", "value": "n1"}],
        connections=[
            {"target_id": "n1", "gamma": 0.8, "beta": 0.2, "kind": "backup"},
            {"target_id": "n2", "gamma": 0.8, "beta": 0.2, "kind": "backup"},
        ],
    )
    assert _find(form, "fiche-ident-name").value == "Fonderie Sud"
    assert _find(form, "fiche-ident-label").value == "Factory"
    assert _find(form, "fiche-ident-location").value == "Lyon, France"
    tags_dd = _find(form, "fiche-ident-tags")
    assert tags_dd.multi is True
    assert tags_dd.value == ["alu", "tag-libre"]
    # Le tag libre absent des options fournies est ajoute comme option.
    assert {"label": "tag-libre", "value": "tag-libre"} in tags_dd.options
    targets_dd = _find(form, "fiche-ident-targets")
    assert targets_dd.multi is True
    assert targets_dd.value == ["n1", "n2"]
    assert _find(form, "fiche-ident-gamma").value == 0.8
    assert _find(form, "fiche-ident-beta").value == 0.2
    assert _find(form, "fiche-ident-arckind").value == "backup"


def test_identity_form_defaults_without_connections():
    form = identity_form("onb")
    assert _find(form, "onb-ident-gamma").value == 0.5
    assert _find(form, "onb-ident-beta").value == 0.5
    assert _find(form, "onb-ident-arckind").value == "nominal"
    assert _find(form, "onb-ident-targets").value == []


# cdc_form


@pytest.mark.parametrize("ctx", CONTEXTS)
def test_cdc_form_builds_with_expected_ids(ctx):
    tree = str(cdc_form(ctx))
    for suffix in (
        "budget",
        "unitcost",
        "currency",
        "standards",
        "certifications",
        "scrap",
        "deliverables",
        "add-dlv",
        "milestones",
        "add-ms",
    ):
        assert f"{ctx}-cdc-{suffix}" in tree
    # Une ligne vierge de chaque famille est pre-montee (lignes dynamiques).
    for pattern in ("dlv-name", "dlv-qty", "dlv-unit", "ms-name", "ms-kind", "ms-start"):
        assert f"{ctx}-cdc-{pattern}" in tree


def test_cdc_form_prefills_from_cdc_and_milestones():
    cdc = CahierDesCharges(
        deliverables=[Deliverable(name="Carter avant", quantity=120.0, unit="pièces")],
        budget_total=50_000.0,
        target_unit_cost=12.5,
        currency="USD",
        quality=QualityRequirements(
            standards=["ISO 9001", "EN 9100"],
            certifications=["NADCAP"],
            max_scrap_rate=0.02,
        ),
    )
    start = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    deadline = datetime(2026, 3, 1, tzinfo=UTC).timestamp()
    milestones = [
        Milestone(
            id="m1",
            node_id="n1",
            name="Proto",
            kind="proto",
            start_ts=start,
            deadline_ts=deadline,
        )
    ]
    form = cdc_form("onb", cdc=cdc, milestones=milestones)

    assert _find(form, "onb-cdc-budget").value == 50_000.0
    assert _find(form, "onb-cdc-unitcost").value == 12.5
    assert _find(form, "onb-cdc-currency").value == "USD"
    assert _find(form, "onb-cdc-standards").value == "ISO 9001, EN 9100"
    assert _find(form, "onb-cdc-certifications").value == "NADCAP"
    assert _find(form, "onb-cdc-scrap").value == 0.02

    (dlv_name,) = _find_by_type(form, "onb-cdc-dlv-name")
    (dlv_qty,) = _find_by_type(form, "onb-cdc-dlv-qty")
    (dlv_unit,) = _find_by_type(form, "onb-cdc-dlv-unit")
    assert (dlv_name.value, dlv_qty.value, dlv_unit.value) == ("Carter avant", 120.0, "pièces")
    # Les composants d'une meme ligne partagent le meme index.
    assert dlv_name.id["index"] == dlv_qty.id["index"] == dlv_unit.id["index"]

    (ms_name,) = _find_by_type(form, "onb-cdc-ms-name")
    (ms_kind,) = _find_by_type(form, "onb-cdc-ms-kind")
    (ms_start,) = _find_by_type(form, "onb-cdc-ms-start")
    (ms_deadline,) = _find_by_type(form, "onb-cdc-ms-deadline")
    assert (ms_name.value, ms_kind.value) == ("Proto", "proto")
    assert ms_start.date == "2026-01-01"
    assert ms_deadline.date == "2026-03-01"


def test_row_helpers_use_pattern_matching_ids():
    dlv = deliverable_row("fiche", "abc123", name="Visserie", quantity=3.0, unit="lots")
    ids = _ids(dlv)
    assert ("fiche-cdc-dlv-name", "abc123") in ids
    assert ("fiche-cdc-dlv-qty", "abc123") in ids
    assert ("fiche-cdc-dlv-unit", "abc123") in ids

    ms = milestone_row("fiche", "def456", name="Série", kind="serie", start_date="2026-02-01")
    ids = _ids(ms)
    assert ("fiche-cdc-ms-name", "def456") in ids
    assert ("fiche-cdc-ms-kind", "def456") in ids
    assert ("fiche-cdc-ms-start", "def456") in ids
    assert ("fiche-cdc-ms-deadline", "def456") in ids


# kpi_guided_form


@pytest.mark.parametrize("ctx", CONTEXTS)
def test_kpi_guided_form_covers_all_kpi_fields(ctx):
    form = kpi_guided_form(ctx)
    indexes = {id_[1] for id_ in _ids(form) if isinstance(id_, tuple) and id_[0] == f"{ctx}-kpi"}
    expected = {key for _, fields in KPI_FIELDS for key, _ in fields}
    assert indexes == expected


def test_kpi_guided_form_prefills_and_exposes_bounds():
    kpis = KPIBundle()
    kpis.time.lead_time_h = 24.0
    kpis.oee.availability = 0.9
    form = kpi_guided_form("onb", kpis)

    lead = _find(form, {"type": "onb-kpi", "index": "time.lead_time_h"})
    assert lead.value == 24.0
    assert lead.min == KPI_CONSTRAINTS["time.lead_time_h"][0] == 0.0

    avail = _find(form, {"type": "onb-kpi", "index": "oee.availability"})
    assert avail.value == 0.9
    assert (avail.min, avail.max) == (0.0, 1.0)

    # Champ non renseigne dans le bundle -> input vide.
    deadline = _find(form, {"type": "onb-kpi", "index": "time.deadline_h"})
    assert deadline.value is None

    # Unite et bornes visibles (libelle + info-bulle title).
    tree = str(form)
    assert "ratio" in tree
    assert "Entre 0 et 1" in tree


# ahp_form


@pytest.mark.parametrize("ctx", CONTEXTS)
def test_ahp_form_builds_sliders_and_notes(ctx):
    form = ahp_form(ctx)
    pair_indexes = [c.id["index"] for c in _find_by_type(form, f"{ctx}-ahp-pair")]
    assert pair_indexes == [f"{i}-{j}" for i, j in PAIRS]
    score_indexes = [c.id["index"] for c in _find_by_type(form, f"{ctx}-ahp-score")]
    assert score_indexes == ["0", "1", "2", "3"]
    label_indexes = [c.id["index"] for c in _find_by_type(form, f"{ctx}-ahp-pair-label")]
    assert label_indexes == pair_indexes
    assert _find(form, f"{ctx}-ahp-notes") is not None
    # Echelles identiques au questionnaire.
    pair_slider = _find_by_type(form, f"{ctx}-ahp-pair")[0]
    assert (pair_slider.min, pair_slider.max, pair_slider.value) == (-8, 8, 0)
    score_slider = _find_by_type(form, f"{ctx}-ahp-score")[0]
    assert (score_slider.min, score_slider.max, score_slider.value) == (1, 6, 3)


# Anti-collision : les deux contextes montes ensemble


def test_both_contexts_mounted_together_have_disjoint_ids():
    root = html.Div(
        [
            form_builder(ctx)
            for ctx in CONTEXTS
            for form_builder in (identity_form, cdc_form, kpi_guided_form, ahp_form)
        ]
    )
    all_ids = _ids(root)
    assert len(all_ids) == len(set(all_ids)), "ids dupliqués entre wizard et fiche"
    # Tous les ids sont prefixes par leur contexte - jamais les ids reserves du questionnaire (" ahp-pair " / " ahp-score " / " kpi-input ").
    for id_ in all_ids:
        head = id_[0] if isinstance(id_, tuple) else id_
        assert head.startswith(("onb-", "fiche-")), f"id non préfixé : {id_!r}"
        assert head not in {"ahp-pair", "ahp-score", "ahp-pair-label", "kpi-input"}


# parse_identity


def test_parse_identity_round_trip():
    values = {
        "onb-ident-name": "  Fonderie Sud  ",
        "onb-ident-label": "Factory",
        "onb-ident-location": " Lyon ",
        "onb-ident-tags": ["alu", "europe"],
        "onb-ident-targets": ["n1", "n2"],
        "onb-ident-gamma": 0.7,
        "onb-ident-beta": 0.3,
        "onb-ident-arckind": "backup",
    }
    payload = parse_identity(values)
    assert payload == {
        "name": "Fonderie Sud",
        "label": "Factory",
        "location": "Lyon",
        "tags": ["alu", "europe"],
        "connections": [
            {"target_id": "n1", "gamma": 0.7, "beta": 0.3, "kind": "backup"},
            {"target_id": "n2", "gamma": 0.7, "beta": 0.3, "kind": "backup"},
        ],
    }


def test_parse_identity_accepts_bare_keys_and_defaults():
    payload = parse_identity({"name": "Atelier", "targets": ["n9"]})
    assert payload["name"] == "Atelier"
    assert payload["label"] == "Supplier"
    assert payload["location"] == ""
    assert payload["tags"] == []
    assert payload["connections"] == [
        {"target_id": "n9", "gamma": 0.5, "beta": 0.5, "kind": "nominal"}
    ]


def test_parse_identity_empty_values():
    payload = parse_identity({})
    assert payload == {
        "name": "",
        "label": "Supplier",
        "location": "",
        "tags": [],
        "connections": [],
    }


# parse_cdc


def test_parse_cdc_converts_iso_dates_to_epoch_and_skips_empty_rows():
    payload = parse_cdc(
        names=["Carter", "", None, ""],
        quantities=[120, None, None, None],
        units=["pièces", "", "", "lots"],
        ms_names=["Proto", ""],
        ms_kinds=["proto", "livraison"],
        ms_starts=["2026-01-01", None],
        ms_deadlines=["2026-03-01", None],
        extras={
            "onb-cdc-budget": 50_000,
            "onb-cdc-unitcost": "12.5",
            "onb-cdc-currency": "USD",
            "onb-cdc-standards": "ISO 9001, EN 9100, ",
            "onb-cdc-certifications": "",
            "onb-cdc-scrap": 0.02,
        },
    )
    # Lignes livrables : la ligne 1 est complete, la ligne 4 partielle (unite seule) est conservee, les lignes entierement vides sont ignorees.
    assert payload["deliverables"] == [
        {"name": "Carter", "quantity": 120.0, "unit": "pièces"},
        {"name": "", "quantity": None, "unit": "lots"},
    ]
    assert len(payload["milestones"]) == 1
    milestone = payload["milestones"][0]
    assert milestone["name"] == "Proto"
    assert milestone["kind"] == "proto"
    assert milestone["start_ts"] == datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    assert milestone["deadline_ts"] == datetime(2026, 3, 1, tzinfo=UTC).timestamp()
    assert payload["budget_total"] == 50_000.0
    assert payload["target_unit_cost"] == 12.5
    assert payload["currency"] == "USD"
    assert payload["quality"] == {
        "standards": ["ISO 9001", "EN 9100"],
        "certifications": [],
        "max_scrap_rate": 0.02,
    }


def test_parse_cdc_empty_everything_gives_clean_defaults():
    payload = parse_cdc([], [], [], [], [], [], [], {})
    assert payload == {
        "deliverables": [],
        "milestones": [],
        "budget_total": None,
        "target_unit_cost": None,
        "currency": "EUR",
        "quality": {"standards": [], "certifications": [], "max_scrap_rate": None},
    }


def test_parse_cdc_milestone_without_dates_gets_zero_epochs():
    payload = parse_cdc([], [], [], ["Série"], ["serie"], [None], [None], {"currency": "  "})
    assert payload["milestones"] == [
        {"name": "Série", "kind": "serie", "start_ts": 0.0, "deadline_ts": 0.0}
    ]
    assert payload["currency"] == "EUR"  # devise blanche -> defaut


# parse_kpis


def test_parse_kpis_sorts_by_index_and_skips_empty():
    ids = [
        {"type": "onb-kpi", "index": "time.lead_time_h"},
        {"type": "onb-kpi", "index": "cost.op_cost"},
        {"type": "onb-kpi", "index": "oee.availability"},
        {"type": "onb-kpi", "index": "risk.severity"},
    ]
    values = [24, None, 0.9, ""]
    # Listes volontairement melangees : l'ordre DOM n'est pas garanti.
    shuffled = list(zip(ids, values, strict=True))[::-1]
    result = parse_kpis([v for _, v in shuffled], [i for i, _ in shuffled])
    assert result == {"oee.availability": 0.9, "time.lead_time_h": 24.0}
    assert list(result.keys()) == sorted(result.keys())
    assert all(isinstance(v, float) for v in result.values())


def test_parse_kpis_empty_lists():
    assert parse_kpis([], []) == {}


# parse_ahp


def test_parse_ahp_round_trip_with_shuffled_inputs():
    pair_ids = [{"type": "fiche-ahp-pair", "index": f"{i}-{j}"} for i, j in PAIRS]
    pair_values = [0, 2, -3, 0, 5, -1]
    score_ids = [{"type": "fiche-ahp-score", "index": str(k)} for k in range(4)]
    score_values = [None, 2, 6, 1]

    shuffled_pairs = list(zip(pair_ids, pair_values, strict=True))[::-1]
    shuffled_scores = list(zip(score_ids, score_values, strict=True))[::-1]
    payload = parse_ahp(
        [v for _, v in shuffled_pairs],
        [i for i, _ in shuffled_pairs],
        [v for _, v in shuffled_scores],
        [i for i, _ in shuffled_scores],
        "  premier remplissage  ",
    )

    # Tri par index restaure malgre le melange.
    assert list(payload["comparisons"].keys()) == [f"{i}-{j}" for i, j in PAIRS]
    assert payload["comparisons"]["0-2"] == bipolar_to_saaty(2)
    assert payload["comparisons"]["0-3"] == bipolar_to_saaty(-3)
    assert payload["comparisons"]["1-3"] == bipolar_to_saaty(5)
    assert payload["comparisons"]["0-1"] == 1.0  # curseur au centre
    # Notes : None -> defaut 3, ordre des criteres restaure.
    assert payload["criteria_scores"] == [
        score_6_to_9(3),
        score_6_to_9(2),
        score_6_to_9(6),
        score_6_to_9(1),
    ]
    assert payload["notes"] == "premier remplissage"


def test_parse_ahp_defaults_and_empty_notes():
    pair_ids = [{"type": "onb-ahp-pair", "index": f"{i}-{j}"} for i, j in PAIRS]
    score_ids = [{"type": "onb-ahp-score", "index": str(k)} for k in range(4)]
    payload = parse_ahp([None] * 6, pair_ids, [None] * 4, score_ids, None)
    assert all(v == 1.0 for v in payload["comparisons"].values())
    assert payload["criteria_scores"] == [score_6_to_9(3)] * 4
    assert payload["notes"] == ""
