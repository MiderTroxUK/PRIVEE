"""Tests d'intégration de la phase E3 : toute écriture métier est auditée."""

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.services import SupplyScoreService


@pytest.fixture
def service(tmp_path):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(1_750_000_000.0))
    yield svc
    svc.close()


def test_facade_exposes_mutation_service(service):
    assert service.mutations is not None
    assert service.mutations.update_kpis is not None


def test_questionnaire_save_path_is_audited(tmp_path):
    """Le callback de sauvegarde du questionnaire écrit via MutationService (audit)."""
    from supplyscore import web_ui
    from supplyscore.data.audit import AuditTrail
    from supplyscore.web_ui.pages.questionnaire import save_assessment_callback

    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(1_750_000_000.0))
    web_ui.set_service(svc)
    try:
        project = svc.seed_demo(n_ranks=2, seed=1)
        node = svc.repo.nodes()[0]

        pair_ids = [
            {"type": "ahp-pair", "index": f"{i}-{j}"}
            for i, j in [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        ]
        score_ids = [{"type": "ahp-score", "index": k} for k in range(4)]
        kpi_ids = [{"type": "kpi-input", "index": "time.lead_time_h"}]

        result = save_assessment_callback(
            1,
            {"project_id": project.id, "name": project.name},
            node.id,
            "testeur",
            "note",
            [0] * 6,
            pair_ids,
            [3] * 4,
            score_ids,
            [123.0],
            kpi_ids,
        )
        assert "enregistrée" in str(result)

        db = svc.client_db(node.id)
        trail = AuditTrail(db.conn, svc.clock, db.lock)
        entries = trail.history("node_kpis", node.id, field="time.lead_time_h")
        assert entries, "la saisie KPI du questionnaire doit laisser une trace d'audit"
        assert entries[0].new_value == 123.0
        assert entries[0].source == "weekly"
        assert entries[0].operator_id == "testeur"
    finally:
        web_ui.set_service(None)
        svc.close()


def test_kpi_rejected_by_constraints_blocks_save(tmp_path):
    """Une valeur hors bornes est refusée par le chemin questionnaire (rien n'est écrit)."""
    from supplyscore import web_ui
    from supplyscore.web_ui.pages.questionnaire import save_assessment_callback

    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(1_750_000_000.0))
    web_ui.set_service(svc)
    try:
        project = svc.seed_demo(n_ranks=2, seed=1)
        node = svc.repo.nodes()[0]
        before = node.kpis.risk.failure_probability

        pair_ids = [
            {"type": "ahp-pair", "index": f"{i}-{j}"}
            for i, j in [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        ]
        score_ids = [{"type": "ahp-score", "index": k} for k in range(4)]
        kpi_ids = [{"type": "kpi-input", "index": "risk.failure_probability"}]

        result = save_assessment_callback(
            1,
            {"project_id": project.id, "name": project.name},
            node.id,
            "testeur",
            "",
            [0] * 6,
            pair_ids,
            [3] * 4,
            score_ids,
            [1.7],  # hors borne [0, 1]
            kpi_ids,
        )
        assert "refusés" in str(result) or "refusé" in str(result)
        reloaded = svc.registry.get_node(node.id)
        assert reloaded.kpis.risk.failure_probability == before
    finally:
        web_ui.set_service(None)
        svc.close()
