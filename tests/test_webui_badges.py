"""Tests des badges hebdo et de completude - composants purs, aucun serveur.

Les statuts sont passes en chaines (duck-typing) : le StrEnum des services
n'est volontairement pas importe (lot parallele sur ``services/weekly.py``).
"""

from enum import StrEnum

import pytest
from dash import html

from supplyscore.web_ui.components.badges import (
    badge_hebdo,
    completeness_badge,
    draft_badge,
    style_hebdo_conditionnel,
    texte_hebdo,
)
from supplyscore.web_ui.components.layout import COLORS

STATUTS = ["a_jour", "en_retard", "manquant", "inconnu"]


class _StatutLocal(StrEnum):
    """Mime le StrEnum des services sans l'importer (duck-typing)."""

    A_JOUR = "a_jour"
    EN_RETARD = "en_retard"


# texte_hebdo : libelles exacts


@pytest.mark.parametrize(
    ("statut", "semaines", "libelle"),
    [
        ("a_jour", 0, "À jour"),
        ("en_retard", 1, "En retard (1 sem.)"),
        ("en_retard", 2, "En retard (2 sem.)"),
        ("manquant", 0, "Manquant"),
        ("inconnu", 0, "—"),
        ("", 0, "—"),
    ],
    ids=["a-jour", "retard-1", "retard-2", "manquant", "inconnu", "vide"],
)
def test_texte_hebdo_libelles_exacts(statut, semaines, libelle):
    assert texte_hebdo(statut, semaines) == libelle


def test_texte_hebdo_accepte_strenum():
    assert texte_hebdo(_StatutLocal.A_JOUR) == "À jour"
    assert texte_hebdo(_StatutLocal.EN_RETARD, 3) == "En retard (3 sem.)"


# badge_hebdo


def test_badge_hebdo_est_un_span_avec_libelle_exact():
    badge = badge_hebdo("en_retard", 2)
    assert isinstance(badge, html.Span)
    assert badge.children == "En retard (2 sem.)"


@pytest.mark.parametrize("statut", STATUTS)
def test_badge_hebdo_texte_identique_a_texte_hebdo(statut):
    assert badge_hebdo(statut, 3).children == texte_hebdo(statut, 3)


def test_badge_hebdo_statut_inconnu_gris_tiret():
    badge = badge_hebdo("n_importe_quoi")
    assert badge.children == "—"
    assert badge.style["color"] == COLORS["muted"]


def test_badge_hebdo_couleurs_attendues_par_statut():
    assert badge_hebdo("a_jour").style["color"] == COLORS["ok"]
    assert badge_hebdo("en_retard", 1).style["color"] == COLORS["warn"]
    assert badge_hebdo("manquant").style["color"] == COLORS["alert"]


def test_badge_hebdo_couleurs_distinctes_par_statut():
    textes = {badge_hebdo(s).style["color"] for s in STATUTS}
    fonds = {badge_hebdo(s).style["backgroundColor"] for s in STATUTS}
    assert len(textes) == 4
    assert len(fonds) == 4


@pytest.mark.parametrize("statut", STATUTS)
def test_badge_hebdo_style_pilule(statut):
    style = badge_hebdo(statut).style
    assert style["borderRadius"] == "10px"
    assert style["fontSize"] == "12px"
    assert style["fontWeight"] == "600"
    # Fond pale distinct du texte fonce (pilule lisible).
    assert style["backgroundColor"] != style["color"]


# completeness_badge et draft_badge


def test_completeness_badge_complet_vert():
    badge = completeness_badge(4, 4)
    assert badge.children == "4/4 sections"
    assert badge.style["color"] == COLORS["ok"]


def test_completeness_badge_incomplet_orange():
    badge = completeness_badge(2, 4)
    assert badge.children == "2/4 sections"
    assert badge.style["color"] == COLORS["warn"]


def test_completeness_badge_zero_orange():
    assert completeness_badge(0, 4).style["color"] == COLORS["warn"]


def test_draft_badge_gris_incomplet():
    badge = draft_badge()
    assert isinstance(badge, html.Span)
    assert badge.children == "Incomplet"
    assert badge.style["color"] == COLORS["muted"]
    assert badge.style["borderRadius"] == "10px"


# style_hebdo_conditionnel


def test_style_hebdo_conditionnel_trois_regles_filter_query():
    regles = style_hebdo_conditionnel("Hebdo")
    assert len(regles) == 3
    assert [r["if"]["filter_query"] for r in regles] == [
        '{Hebdo} contains "À jour"',
        '{Hebdo} contains "En retard"',
        '{Hebdo} contains "Manquant"',
    ]
    assert all(r["if"]["column_id"] == "Hebdo" for r in regles)


def test_style_hebdo_conditionnel_couleurs_alignees_sur_les_badges():
    regles = {r["if"]["filter_query"]: r for r in style_hebdo_conditionnel("Statut")}
    attendu = {
        '{Statut} contains "À jour"': badge_hebdo("a_jour"),
        '{Statut} contains "En retard"': badge_hebdo("en_retard", 1),
        '{Statut} contains "Manquant"': badge_hebdo("manquant"),
    }
    assert set(regles) == set(attendu)
    for query, badge in attendu.items():
        assert regles[query]["color"] == badge.style["color"]
        assert regles[query]["backgroundColor"] == badge.style["backgroundColor"]
    # 3 couleurs distinctes entre les regles.
    assert len({r["color"] for r in regles.values()}) == 3
