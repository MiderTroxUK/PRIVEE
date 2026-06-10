"""Tests des règles de statut unifiées (supplyscore.core.status_rules)."""

from __future__ import annotations

import pytest

from supplyscore.core.status_rules import effective_ud_local, effective_ur_local
from supplyscore.core.ur_model import UrModel
from supplyscore.domain.models import (
    KPIBundle,
    OEEKPIs,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)
from supplyscore.graph import InMemoryGraphRepository, PropagationEngine

APPROX = 1e-12

ALL_STATUSES = (TaskStatus.ACTIVE, TaskStatus.DONE, TaskStatus.ABANDONED)


# --- Table de vérité : effective_ur_local -------------------------------------------


@pytest.mark.parametrize(
    ("status", "ur_local", "expected"),
    [
        # ACTIVE : la mesure passe telle quelle, None vaut 0.0.
        (TaskStatus.ACTIVE, None, 0.0),
        (TaskStatus.ACTIVE, 0.3, 0.3),
        (TaskStatus.ACTIVE, 1.2, 1.2),  # > 1 autorisé (tâche en retard), pas de clip ici
        # DONE : plus urgent, quelle que soit la mesure.
        (TaskStatus.DONE, None, 0.0),
        (TaskStatus.DONE, 0.3, 0.0),
        (TaskStatus.DONE, 1.2, 0.0),
        # ABANDONED : urgence maximale pour l'aval, quelle que soit la mesure.
        (TaskStatus.ABANDONED, None, 1.0),
        (TaskStatus.ABANDONED, 0.3, 1.0),
        (TaskStatus.ABANDONED, 1.2, 1.0),
    ],
)
def test_effective_ur_local_truth_table(
    status: TaskStatus, ur_local: float | None, expected: float
) -> None:
    assert effective_ur_local(status, ur_local) == pytest.approx(expected, abs=APPROX)


# --- Table de vérité : effective_ud_local -------------------------------------------


@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize(
    ("ud_local", "expected"),
    [(None, 0.0), (0.3, 0.3), (1.2, 1.2)],
)
def test_effective_ud_local_status_does_not_override(
    status: TaskStatus, ud_local: float | None, expected: float
) -> None:
    # Décision E9 en attente : le statut n'écrase pas le besoin déclaré.
    assert effective_ud_local(status, ud_local) == pytest.approx(expected, abs=APPROX)


# --- Cohérence croisée UrModel / PropagationEngine ----------------------------------


def _bundle_half_urgency() -> KPIBundle:
    """Bundle minimal : seul le bloc perf est actif, u_perf = 1 - OEE = 0.5."""
    return KPIBundle(oee=OEEKPIs(availability=0.5, performance=1.0, quality=1.0))


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_ur_model_and_propagation_agree_on_effective_ur(status: TaskStatus) -> None:
    """UrModel et PropagationEngine appliquent la même règle pour chaque statut."""
    model = UrModel()
    kpis = _bundle_half_urgency()
    base = model.ur_local(0.0, kpis)  # valeur ACTIVE issue des KPIs (0.5)
    assert base == pytest.approx(0.5, abs=APPROX)
    expected = effective_ur_local(status, base)

    # Côté core : le statut passe par status_rules.
    assert model.ur_local(0.0, kpis, status=status) == pytest.approx(expected, abs=APPROX)

    # Côté graphe : nœud isolé (sans arc), Ur propagé = Ur_local effectif.
    repo = InMemoryGraphRepository()
    repo.add_node(
        SupplyNode(id="solo", name="Solo", status=status, urgency=UrgencyState(ur_local=base))
    )
    states = PropagationEngine(repo).propagate_all()
    assert states["solo"].ur == pytest.approx(expected, abs=APPROX)


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_propagation_uses_same_rule_as_status_rules_on_chain(status: TaskStatus) -> None:
    """Sur une chaîne B -> A, l'amont contribue exactement son Ur_local effectif."""
    beta = 0.7
    ur_local_b = 0.6
    ur_local_a = 0.1
    repo = InMemoryGraphRepository()
    repo.add_node(SupplyNode(id="A", name="A", urgency=UrgencyState(ur_local=ur_local_a)))
    repo.add_node(
        SupplyNode(id="B", name="B", status=status, urgency=UrgencyState(ur_local=ur_local_b))
    )
    repo.add_arc(SupplyArc(source_id="B", target_id="A", gamma=0.5, beta=beta))
    states = PropagationEngine(repo).propagate_all()

    ur_b = effective_ur_local(status, ur_local_b)
    ur_a = 1.0 - (1.0 - ur_local_a) * (1.0 - beta * ur_b)
    assert states["B"].ur == pytest.approx(ur_b, abs=APPROX)
    assert states["A"].ur == pytest.approx(ur_a, abs=APPROX)
