"""Tests des figures d'explication (phase E8, Lot 8.3).

Les entrées sont des SimpleNamespace : les constructeurs lisent les
attributs en duck-typing, sans dépendre des dataclasses du moteur
d'explicabilité.
"""

from types import SimpleNamespace

import pytest

from supplyscore.web_ui.components.explain_figures import (
    BLOCK_LABELS_FR,
    adequation_equation_block,
    propagation_bars_figure,
    ud_criteria_figure,
    ur_waterfall_figure,
)


def _block(block: str, share: float, **overrides) -> SimpleNamespace:
    base = {"block": block, "u": 0.5, "omega": 1.0, "share": share, "delta_without": 0.1}
    base.update(overrides)
    return SimpleNamespace(**base)


def _edge(name: str, coeff: float, share: float, u_neighbor: float = 0.7) -> SimpleNamespace:
    return SimpleNamespace(neighbor_name=name, coeff=coeff, u_neighbor=u_neighbor, share=share)


def _criterion(index: int, label: str, weight: float, score: float) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        label=label,
        weight=weight,
        score=score,
        contribution=weight * (score - 1.0) / 8.0,
    )


def _all_texts(component) -> str:
    """Concatène récursivement tous les textes d'un arbre de composants Dash."""
    if isinstance(component, str):
        return component
    children = getattr(component, "children", None)
    if children is None:
        return ""
    if not isinstance(children, (list, tuple)):
        children = [children]
    return " ".join(_all_texts(child) for child in children)


# --- ur_waterfall_figure --------------------------------------------------------------


def test_ur_waterfall_two_active_blocks():
    contributions = [_block("time", 0.6), _block("risk", 0.4)]
    fig = ur_waterfall_figure(contributions, ur_local=0.5)

    assert len(fig.data) == 1
    trace = fig.data[0]
    assert trace.type == "waterfall"
    assert trace.measure == ("relative", "relative", "total")
    assert trace.x == ("Temps", "Risque", "Ur local")
    assert trace.y == pytest.approx((0.3, 0.2, 0.5))
    # Total final == ur_local : les mesures relatives somment exactement à 0.5.
    assert trace.y[0] + trace.y[1] == pytest.approx(0.5)


def test_ur_waterfall_skips_inactive_blocks_and_annotates_approximation():
    contributions = [_block("time", 1.0), _block("cap", 0.0), _block("co2", 0.0, u=None)]
    fig = ur_waterfall_figure(contributions, ur_local=0.42)

    trace = fig.data[0]
    assert trace.x == ("Temps", "Ur local")
    assert trace.measure == ("relative", "total")
    assert trace.y == pytest.approx((0.42, 0.42))
    subtitles = [a.text for a in fig.layout.annotations]
    assert any("log-survie" in t and "affichage" in t for t in subtitles)
    assert "0.420" in fig.layout.title.text


def test_ur_waterfall_empty_contributions():
    fig = ur_waterfall_figure([], ur_local=0.0)
    assert len(fig.data) == 0
    assert len(fig.layout.annotations) == 1
    assert "Aucune contribution" in fig.layout.annotations[0].text
    assert fig.layout.xaxis.visible is False


def test_ur_waterfall_unknown_block_falls_back_to_raw_name():
    fig = ur_waterfall_figure([_block("inconnu", 1.0)], ur_local=0.3)
    assert fig.data[0].x == ("inconnu", "Ur local")


def test_block_labels_cover_the_six_kpi_blocks():
    assert set(BLOCK_LABELS_FR) == {"time", "cap", "perf", "risk", "cost", "co2"}
    assert BLOCK_LABELS_FR["perf"] == "Performance (OEE)"


# --- propagation_bars_figure ----------------------------------------------------------


def test_propagation_bars_local_plus_one_supplier():
    fig = propagation_bars_figure(0.304, [_edge("Fonderie Lyon", 0.8, 0.696)])

    assert len(fig.data) == 1
    bar = fig.data[0]
    assert bar.y == ("Local", "Fonderie Lyon (β=0.8)")
    assert bar.x == pytest.approx((30.4, 69.6))
    assert fig.layout.xaxis.range == (0, 100)
    assert fig.layout.title.text == "D'où vient l'urgence réelle ?"
    # La barre locale a une couleur distincte de celle du voisin.
    assert bar.marker.color[0] != bar.marker.color[1]


def test_propagation_bars_direction_clients_uses_gamma():
    fig = propagation_bars_figure(0.5, [_edge("Client final", 0.6, 0.5)], direction="clients")
    assert fig.data[0].y == ("Local", "Client final (γ=0.6)")
    assert fig.layout.title.text == "Qui tire le besoin déclaré ?"


def test_propagation_bars_fully_local_message():
    fig = propagation_bars_figure(1.0, [])
    assert len(fig.data) == 0
    assert "entièrement locale" in fig.layout.annotations[0].text


def test_propagation_bars_fully_local_message_clients():
    fig = propagation_bars_figure(1.0, [], direction="clients")
    assert "entièrement local" in fig.layout.annotations[0].text


def test_propagation_bars_no_edges_but_partial_local_still_draws_local_bar():
    # Cas tout-nul : part locale 0 sans voisin -> on trace quand même « Local ».
    fig = propagation_bars_figure(0.0, [])
    assert fig.data[0].y == ("Local",)
    assert fig.data[0].x == pytest.approx((0.0,))


# --- ud_criteria_figure ---------------------------------------------------------------


def test_ud_criteria_four_bars_and_sum_annotation():
    criteres = [
        _criterion(0, "Criticité client", 0.4, 7.0),
        _criterion(1, "Délai contractuel", 0.3, 5.0),
        _criterion(2, "Pénalités", 0.2, 3.0),
        _criterion(3, "Image", 0.1, 1.0),
    ]
    fig = ud_criteria_figure(criteres)

    bar = fig.data[0]
    assert len(bar.x) == 4
    assert bar.y == ("Criticité client", "Délai contractuel", "Pénalités", "Image")
    total = sum(c.contribution for c in criteres)
    assert sum(bar.x) == pytest.approx(total)
    annotation = fig.layout.annotations[0].text
    assert "Σ κ = Ud" in annotation
    assert f"{total:.3f}" in annotation


def test_ud_criteria_sorted_by_index():
    criteres = [_criterion(1, "B", 0.5, 3.0), _criterion(0, "A", 0.5, 9.0)]
    fig = ud_criteria_figure(criteres)
    assert fig.data[0].y == ("A", "B")


def test_ud_criteria_empty_message():
    fig = ud_criteria_figure([])
    assert len(fig.data) == 0
    assert "Aucun critère" in fig.layout.annotations[0].text


# --- adequation_equation_block --------------------------------------------------------


def _trace(**overrides) -> SimpleNamespace:
    base = {
        "e_under": 0.31,
        "e_over": 0.0,
        "penalty": 0.8027,
        "adequation": 38.4,
        "lambda_under": 2.25,
        "lambda_over": 1.0,
        "alpha": 0.88,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_adequation_block_instantiates_equation():
    text = _all_texts(adequation_equation_block(_trace()))

    assert "2.25" in text
    assert "38.4" in text
    assert "sous-estimation" in text
    # Équation chiffrée : erreurs, pénalité instanciée, normalisation e^−2.25.
    assert "e_sous = [Ur − Ud]+ = 0.31" in text
    assert "e_sur = [Ud − Ur]+ = 0.00" in text
    assert "pénalité = 2.25×0.31^0.88 = 0.80" in text
    assert "100·(e^−0.80 − e^−2.25)/(1 − e^−2.25) = 38.4" in text
    assert "Kahneman-Tversky" in text


def test_adequation_block_with_overestimation_term():
    block = adequation_equation_block(
        _trace(e_under=0.0, e_over=0.2, penalty=0.2426, adequation=77.9)
    )
    text = _all_texts(block)
    assert "pénalité = 1×0.20^0.88 = 0.24" in text
    assert "77.9" in text


def test_adequation_block_perfect_alignment_zero_penalty():
    block = adequation_equation_block(
        _trace(e_under=0.0, e_over=0.0, penalty=0.0, adequation=100.0)
    )
    text = _all_texts(block)
    assert "pénalité = 0 = 0.00" in text
    assert "100.0" in text
