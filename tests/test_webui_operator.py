"""Tests du selecteur d'operateur global (" qui joue ? ") - aucun serveur lance.

Meme convention que ``test_webui.py`` : les callbacks sont des fonctions
nommees au niveau module, appelees directement sans contexte de requete Dash.
"""

import pytest

from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.app import create_app
from supplyscore.web_ui.components.operator import (
    current_operator,
    operator_selector,
    set_operator_callback,
)


@pytest.fixture
def service(tmp_path):
    """Service seede avec une petite demo, partage par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store")
    svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc
    set_service(None)


# current_operator (helper pur)


@pytest.mark.parametrize(
    ("store_value", "expected"),
    [
        (None, "anonyme"),
        ({}, "anonyme"),
        ({"name": ""}, "anonyme"),
        ({"name": "   "}, "anonyme"),
        ({"name": "  Marie  "}, "Marie"),
        ({"name": "JoSé"}, "JoSé"),
    ],
    ids=["none", "empty-dict", "empty-name", "spaces-only", "trimmed", "case-kept"],
)
def test_current_operator(store_value, expected):
    assert current_operator(store_value) == expected


# Callback du selecteur


def test_set_operator_callback_sets_trimmed_name():
    data, badge = set_operator_callback("  Marie  ", None)
    assert data == {"name": "Marie"}
    assert badge == "Marie"


def test_set_operator_callback_keeps_case():
    data, badge = set_operator_callback("JoSé", {"name": "Marie"})
    assert data == {"name": "JoSé"}
    assert badge == "JoSé"


def test_set_operator_callback_blank_falls_back_to_anonyme():
    for blank in ("", "   "):
        data, badge = set_operator_callback(blank, {"name": "Marie"})
        assert data == {"name": "anonyme"}
        assert badge == "anonyme"


def test_set_operator_callback_initial_call_restores_session():
    # Au chargement (value=None), l'operateur memorise en session est conserve.
    data, badge = set_operator_callback(None, {"name": "Marie"})
    assert data == {"name": "Marie"}
    assert badge == "Marie"


def test_set_operator_callback_initial_call_without_store():
    data, badge = set_operator_callback(None, None)
    assert data == {"name": "anonyme"}
    assert badge == "anonyme"


def test_set_operator_callback_preserves_other_store_keys():
    data, badge = set_operator_callback("Bob", {"name": "Marie", "team": "bleu"})
    assert data == {"name": "Bob", "team": "bleu"}
    assert badge == "Bob"


# Composant et integration au layout de l'application


def test_operator_selector_contains_input_and_badge():
    tree = str(operator_selector())
    assert "operator-name-input" in tree
    assert "operator-badge" in tree
    assert "Opérateur" in tree


def test_create_app_layout_contains_operator_components(service):
    app = create_app(service=service)
    tree = str(app.layout)
    for component_id in ("store-operator", "operator-name-input", "operator-badge"):
        assert component_id in tree
