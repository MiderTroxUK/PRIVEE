"""Tests des composants UI d'historique (journal d'audit et trajectoire KPI).

Les entrees du tableau sont des SimpleNamespace : le composant lit les
attributs en duck-typing (getattr), sans dependre de la dataclass AuditEntry.
"""

from datetime import datetime
from types import SimpleNamespace

from supplyscore.web_ui.components.history import history_table, kpi_trajectory_figure

FRENCH_COLUMNS = [
    "Date",
    "Semaine",
    "Champ",
    "Ancienne valeur",
    "Nouvelle valeur",
    "Source",
    "Opérateur",
]


def _ts(*args) -> float:
    return datetime(*args).timestamp()


def _entry(**overrides) -> SimpleNamespace:
    base = {
        "timestamp": _ts(2026, 3, 2, 14, 30),
        "iso_week": "2026-W10",
        "field": "kpis.time.lead_time_h",
        "old_value": 120.0,
        "new_value": 96.0,
        "source": "questionnaire",
        "operator_id": "alice",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# history_table


def test_history_table_columns_and_rows():
    entries = [
        _entry(),
        _entry(timestamp=_ts(2026, 3, 9, 8, 5), old_value=None, new_value=100.0),
        _entry(timestamp=_ts(2026, 3, 16, 17, 0), old_value=100.0, new_value=None),
    ]
    table = history_table(entries)

    assert [c["name"] for c in table.columns] == FRENCH_COLUMNS
    assert len(table.data) == 3

    first = table.data[0]
    assert first["Date"] == "02/03/2026 14:30"
    assert first["Semaine"] == "2026-W10"
    assert first["Champ"] == "kpis.time.lead_time_h"
    assert first["Ancienne valeur"] == "120"
    assert first["Nouvelle valeur"] == "96"
    assert first["Source"] == "questionnaire"
    assert first["Opérateur"] == "alice"

    # None -> " - ", et l'ordre des lignes est celui fourni par l'appelant.
    assert table.data[1]["Date"] == "09/03/2026 08:05"
    assert table.data[1]["Ancienne valeur"] == "—"
    assert table.data[2]["Nouvelle valeur"] == "—"


def test_history_table_read_only_no_native_sort():
    table = history_table([_entry()])
    assert table.editable is False
    assert table.sort_action == "none"
    assert table.page_size == 15


def test_history_table_tolerates_missing_attributes():
    # Vieil objet sans operator_id ni source : getattr avec defaut, pas de crash.
    legacy = SimpleNamespace(
        timestamp=_ts(2026, 1, 5, 9, 0),
        iso_week="2026-W02",
        field="kpis.cost.unit_cost",
        old_value=10.0,
        new_value=12.5,
    )
    table = history_table([legacy])
    row = table.data[0]
    assert row["Opérateur"] == ""
    assert row["Source"] == ""
    assert row["Nouvelle valeur"] == "12.5"


def test_history_table_empty_entries():
    table = history_table([])
    assert table.data == []
    assert [c["name"] for c in table.columns] == FRENCH_COLUMNS


# kpi_trajectory_figure


def test_kpi_trajectory_figure_step_curve():
    snapshots = [
        (_ts(2026, 3, 2, 10, 0), 120.0),
        (_ts(2026, 3, 9, 10, 0), 110.0),
        (_ts(2026, 3, 16, 10, 0), None),
        (_ts(2026, 3, 23, 10, 0), 96.0),
    ]
    fig = kpi_trajectory_figure(snapshots, "time.lead_time_h", unit="h")

    assert len(fig.data) == 1
    trace = fig.data[0]
    assert trace.line.shape == "hv"
    assert len(trace.x) == 4
    assert trace.y == (120.0, 110.0, None, 96.0)
    assert fig.layout.title.text == "Trajectoire — time.lead_time_h (h)"
    assert fig.layout.template.layout.plot_bgcolor is not None  # plotly_white applique


def test_kpi_trajectory_figure_title_without_unit():
    fig = kpi_trajectory_figure([(_ts(2026, 3, 2, 10, 0), 1.0)], "risk.spof_count")
    assert fig.layout.title.text == "Trajectoire — risk.spof_count"


def test_kpi_trajectory_figure_empty_snapshots():
    fig = kpi_trajectory_figure([], "time.lead_time_h", unit="h")
    assert len(fig.data) == 0
    annotations = fig.layout.annotations
    assert len(annotations) == 1
    assert "time.lead_time_h" in annotations[0].text
    assert fig.layout.xaxis.visible is False
