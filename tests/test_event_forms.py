"""Tests des formulaires d'événements générés depuis la calibration (Lot 6.4).

Aucun serveur Dash : les composants sont construits en mémoire et inspectés
en parcourant l'arbre ; les parseurs sont testés comme fonctions pures. Les
impacts et événements sont des SimpleNamespace (duck-typing volontaire du
composant — le service est développé en parallèle).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from supplyscore.domain.events import EVENT_CALIBRATION
from supplyscore.web_ui.components.event_forms import (
    event_param_fields,
    event_type_options,
    events_list,
    impacts_preview_table,
    parse_event_params,
)

# --- Helpers d'inspection de l'arbre de composants -----------------------------------


def _walk(component):
    """Itère sur tous les composants Dash de l'arbre (racine incluse)."""
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if hasattr(child, "to_plotly_json"):
            yield from _walk(child)


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


# --- event_type_options ----------------------------------------------------------------


def test_event_type_options_cover_all_14_types_sorted_by_french_label():
    options = event_type_options()
    assert len(options) == 14
    labels = [opt["label"] for opt in options]
    assert labels == sorted(labels)
    assert {opt["value"] for opt in options} == set(EVENT_CALIBRATION)
    assert {"label": "Panne machine", "value": "panne_machine"} in options


# --- event_param_fields ----------------------------------------------------------------


def test_event_param_fields_panne_machine_generates_number_and_choice():
    form = event_param_fields("panne_machine")
    duree = _find(form, {"type": "ev-param", "index": "duree_arret_h"})
    assert duree.type == "number"
    assert duree.min > 0  # durée strictement positive : le zéro est exclu
    gravite = _find(form, {"type": "ev-param", "index": "gravite"})
    assert [opt["value"] for opt in gravite.options] == ["mineure", "majeure", "critique"]
    tree = str(form)
    assert "Durée d'arrêt (h)" in tree  # unité reprise dans le libellé
    assert "Arrêt non planifié" in tree  # description_fr en sous-titre


def test_event_param_fields_ratio_bounds_and_custom_ctx():
    form = event_param_fields("greve", ctx="hb")
    part = _find(form, {"type": "hb-param", "index": "part_effectif"})
    assert (part.type, part.min, part.max) == ("number", 0.0, 1.0)
    duree = _find(form, {"type": "hb-param", "index": "duree_prevue_h"})
    assert duree.min > 0  # champ strictement positif lui aussi
    # Aucun id résiduel du contexte par défaut.
    assert _find_by_type(form, "ev-param") == []


def test_event_param_fields_all_types_build_with_ev_prefixed_ids():
    for event_type, spec in EVENT_CALIBRATION.items():
        form = event_param_fields(event_type)
        indexes = {comp.id["index"] for comp in _find_by_type(form, "ev-param")}
        assert indexes == {field.name for field in spec.fields}, event_type


def test_event_param_fields_unknown_type_raises_value_error():
    with pytest.raises(ValueError, match="inconnu"):
        event_param_fields("meteorite")


# --- parse_event_params ----------------------------------------------------------------


def test_parse_event_params_converts_floats_skips_empty_sorts_by_index():
    ids = [
        {"type": "ev-param", "index": "gravite"},
        {"type": "ev-param", "index": "duree_arret_h"},
        {"type": "ev-param", "index": "part_effectif"},
        {"type": "ev-param", "index": "criticite"},
    ]
    values = ["majeure", 24, None, ""]
    # Listes volontairement mélangées : l'ordre DOM n'est pas garanti.
    shuffled = list(zip(ids, values, strict=True))[::-1]
    result = parse_event_params([v for _, v in shuffled], [i for i, _ in shuffled])
    assert result == {"duree_arret_h": 24.0, "gravite": "majeure"}
    assert isinstance(result["duree_arret_h"], float)
    assert list(result) == ["duree_arret_h", "gravite"]  # tri par index


def test_parse_event_params_keeps_zero_and_handles_empty_lists():
    ids = [{"type": "ev-param", "index": "part_effectif"}]
    assert parse_event_params([0], ids) == {"part_effectif": 0.0}
    assert parse_event_params([], []) == {}


# --- impacts_preview_table -------------------------------------------------------------


def test_impacts_preview_table_renders_four_columns_and_values():
    impacts = [
        SimpleNamespace(
            kpi_path="risk.failure_probability",
            old=0.02,
            new=0.056308,
            rule="BAYES(p=0.02, k=1, n=1) : panne machine majeure",
        ),
        SimpleNamespace(
            kpi_path="risk.recovery_time_h",
            old=None,
            new=24.0,
            rule="EMA(obs=24, λ=0.4) : temps de récupération observé",
        ),
    ]
    tree = str(impacts_preview_table(impacts))
    for header in ("KPI", "Avant", "Après", "Règle appliquée"):
        assert header in tree
    assert "risk.failure_probability" in tree
    assert "0.02" in tree
    assert "0.05631" in tree  # 4 décimales utiles (:.4g)
    assert "non renseigné" in tree  # old None
    assert "BAYES" in tree  # règle appliquée affichée telle quelle


def test_impacts_preview_table_empty_shows_grey_message():
    assert "Aucun impact" in str(impacts_preview_table([]))
    custom = impacts_preview_table([], no_impact_msg="Rien à prévisualiser.")
    assert "Rien à prévisualiser." in str(custom)


# --- events_list -----------------------------------------------------------------------


def _evt(**overrides):
    """Événement factice duck-typé (SimpleNamespace), champs surchargés à la demande."""
    base = {
        "id": "e1",
        "event_type": "panne_machine",
        "iso_week": "2026-W23",
        "params": {},
        "notes": "",
        "reverted_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_events_list_revert_button_only_for_active_events():
    events = [
        _evt(id="e1", params={"duree_arret_h": 24.0, "gravite": "majeure"}, notes="ligne 3"),
        _evt(
            id="e2",
            event_type="greve",
            params={"duree_prevue_h": 8.0, "part_effectif": 0.5},
            reverted_at=1_765_000_000.0,
        ),
    ]
    listing = events_list(events)
    buttons = _find_by_type(listing, "ev-revert")
    assert len(buttons) == 1  # l'événement reverté n'a pas de bouton
    assert buttons[0].id["index"] == "e1"
    tree = str(listing)
    assert "Panne machine" in tree  # libellé français du type
    assert "Grève" in tree
    assert "2026-W23" in tree
    assert "Annulé" in tree  # badge sur l'événement reverté
    assert "Durée d'arrêt : 24 h" in tree  # params résumés (libellé + unité)
    assert "majeure" in tree
    assert "ligne 3" in tree  # notes affichées


def test_events_list_custom_ctx_unknown_type_and_empty_message():
    listing = events_list([_evt(event_type="type_disparu")], ctx="hb")
    assert len(_find_by_type(listing, "hb-revert")) == 1
    assert "type_disparu" in str(listing)  # type inconnu affiché brut, sans planter
    assert "Aucun événement" in str(events_list([]))
