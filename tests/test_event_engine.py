"""Tests du Lot 6.1 : EventEngine - apply/revert transactionnels des evenements.

Couvre : le cas chiffre bout-en-bout (panne majeure 0.02 -> 0.0563, audit
``event:<id>`` puis ``revert:<id>``), le conflit apres edition manuelle
(ConflictError, aucune restauration partielle), la chaine complete
hausse_tarif -> KPI -> urgency, les erreurs (deja annule, evenement inconnu),
open_events/list_week, la decroissance hebdomadaire, la purete de preview,
l'horloge du PROJET (mode jeu) et la propriete Hypothesis " apply puis revert
immediat == identite sur le KPIBundle ".
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from supplyscore.core.clock import FixedClock, iso_week
from supplyscore.data.audit import AuditEntry, AuditTrail
from supplyscore.domain.constraints import KPI_CONSTRAINTS
from supplyscore.domain.events import EVENT_CALIBRATION, EventField
from supplyscore.domain.models import Project, SupplyNode, TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services.events import ConflictError, EventEngine, SupplyEvent

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0
TOL = 1e-4

#: Parametres de la panne machine du cas chiffre du PLAN.
PANNE_MAJEURE = {"duree_arret_h": 24.0, "gravite": "majeure"}

#: Chemins de KPI touches par au moins un type d'evenement (cf. calibration).
TOUCHED_PATHS: tuple[str, ...] = (
    "network.demand",
    "inventory.flow_rate",
    "inventory.max_volume_m3",
    "time.lead_time_h",
    "time.lead_time_std_h",
    "cost.tariff",
    "cost.op_cost",
    "oee.availability",
    "oee.quality",
    "risk.failure_probability",
    "risk.recovery_time_h",
    "risk.severity",
    "risk.cost_volatility",
    "risk.env_exposure",
    "risk.political_risk",
)

#: Champs numeriques strictement positifs (borne minimum=0 exclusive).
STRICT_POSITIVE = {"duree_arret_h", "retard_h", "duree_prevue_h", "nouvelle_demande"}

EVENT_TYPES = sorted(EVENT_CALIBRATION)


# Fixtures


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    yield svc
    svc.close()


@pytest.fixture
def projet(service: SupplyScoreService) -> Project:
    """Projet de demonstration reproductible (seed_demo)."""
    return service.seed_demo(n_ranks=2, seed=1)


@pytest.fixture
def node_id(service: SupplyScoreService, projet: Project) -> str:
    """Premier noeud actif (ordre deterministe) du projet de demo."""
    nodes = sorted(service.repo.nodes(), key=lambda n: n.id)
    actifs = [
        n for n in nodes if n.status is TaskStatus.ACTIVE and n.onboarding_state == "complete"
    ]
    assert actifs, "le projet de démo doit contenir au moins un nœud actif"
    return actifs[0].id


@pytest.fixture
def engine(service: SupplyScoreService) -> EventEngine:
    return EventEngine(service)


# Helpers


def _kpi(service: SupplyScoreService, node_id: str, path: str) -> float | None:
    """Valeur courante d'un KPI, relue depuis le registre."""
    node = service.registry.get_node(node_id)
    assert node is not None
    block, field = path.split(".", 1)
    return getattr(getattr(node.kpis, block), field)


def _set_kpis(service: SupplyScoreService, node_id: str, changes: dict[str, float | None]) -> None:
    service.mutations.update_kpis(node_id, changes, source="edit")


def _latest_audit(service: SupplyScoreService, node_id: str, path: str) -> AuditEntry:
    """Entree d'audit la plus recente du KPI ``path`` dans la base client."""
    db = service.client_db(node_id)
    trail = AuditTrail(db.conn, FixedClock(_NOW), lock=db.lock)
    entries = trail.history("node_kpis", node_id, field=path, limit=10)
    assert entries, f"aucune entrée d'audit pour {path}"
    return entries[0]


def _event_row(service: SupplyScoreService, node_id: str, event_id: str) -> dict:
    rows = [r for r in service.client_db(node_id).list_events(node_id) if r["id"] == event_id]
    assert len(rows) == 1
    return rows[0]


# Cas chiffre bout-en-bout : panne majeure 0.02 -> 0.0563 -> revert


class TestCasChiffreBoutEnBout:
    def test_preview_apply_revert(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        _set_kpis(service, node_id, {"risk.failure_probability": 0.02})

        # preview : 0.02 -> 0.0563, rien n'est ecrit.
        impacts = engine.preview(node_id, "panne_machine", PANNE_MAJEURE)
        imp = next(i for i in impacts if i.kpi_path == "risk.failure_probability")
        assert imp.old == pytest.approx(0.02)
        assert imp.new == pytest.approx(0.0563, abs=TOL)
        assert _kpi(service, node_id, "risk.failure_probability") == pytest.approx(0.02)
        assert service.client_db(node_id).list_events(node_id) == []

        # apply : KPI a 0.0563, ligne events, audit source="event:<id>".
        event = engine.apply(node_id, "panne_machine", PANNE_MAJEURE, "op-1", "ligne 3 en panne")
        assert isinstance(event, SupplyEvent)
        assert event.node_id == node_id
        assert event.event_type == "panne_machine"
        assert event.iso_week == iso_week(_NOW) == "2026-S24"
        assert event.occurred_at == _NOW
        assert event.reverted_at is None
        assert event.operator_id == "op-1"
        assert event.notes == "ligne 3 en panne"
        assert event.params == PANNE_MAJEURE
        assert event.impacts == impacts

        assert _kpi(service, node_id, "risk.failure_probability") == pytest.approx(0.0563, abs=TOL)
        row = _event_row(service, node_id, event.id)
        assert row["iso_week"] == "2026-S24"  # semaine de l'horloge du projet
        assert row["occurred_at"] == _NOW
        assert row["reverted_at"] is None

        entry = _latest_audit(service, node_id, "risk.failure_probability")
        assert entry.source == f"event:{event.id}"
        assert entry.old_value == pytest.approx(0.02)
        assert entry.new_value == pytest.approx(0.0563, abs=TOL)

        # La relecture (open_events) restitue l'evenement a l'identique.
        assert engine.open_events(node_id) == [event]

        # revert immediat : 0.02 restaure, audit source="revert:<id>", mark_reverted.
        restored = engine.revert(event.id, node_id, operator_id="op-1")
        assert restored == impacts
        assert _kpi(service, node_id, "risk.failure_probability") == pytest.approx(0.02)

        entry = _latest_audit(service, node_id, "risk.failure_probability")
        assert entry.source == f"revert:{event.id}"
        assert entry.new_value == pytest.approx(0.02)

        row = _event_row(service, node_id, event.id)
        assert row["reverted_at"] == _NOW
        assert engine.open_events(node_id) == []


# Conflit : edition manuelle entre apply et revert


class TestConflit:
    def test_edition_manuelle_puis_revert_leve_conflict_error(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        _set_kpis(service, node_id, {"risk.failure_probability": 0.02})
        event = engine.apply(node_id, "panne_machine", PANNE_MAJEURE)
        recovery_apres_event = _kpi(service, node_id, "risk.recovery_time_h")

        # Edition manuelle du MEME KPI : la valeur de l'evenement est ecrasee.
        _set_kpis(service, node_id, {"risk.failure_probability": 0.10})

        with pytest.raises(ConflictError) as exc_info:
            engine.revert(event.id, node_id)
        assert exc_info.value.champs == ["risk.failure_probability"]
        assert "risk.failure_probability" in str(exc_info.value)

        # AUCUNE restauration partielle : le KPI edite reste a 0.10, les autres impacts de l'evenement restent appliques, l'evenement reste ouvert.
        assert _kpi(service, node_id, "risk.failure_probability") == pytest.approx(0.10)
        assert _kpi(service, node_id, "risk.recovery_time_h") == recovery_apres_event
        assert _event_row(service, node_id, event.id)["reverted_at"] is None
        assert [e.id for e in engine.open_events(node_id)] == [event.id]

    def test_champ_efface_depuis_l_evenement_est_un_conflit(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        _set_kpis(service, node_id, {"network.demand": 100.0})
        event = engine.apply(node_id, "pic_demande", {"nouvelle_demande": 250.0})
        _set_kpis(service, node_id, {"network.demand": None})

        with pytest.raises(ConflictError) as exc_info:
            engine.revert(event.id, node_id)
        assert exc_info.value.champs == ["network.demand"]
        assert _event_row(service, node_id, event.id)["reverted_at"] is None


# hausse_tarif : chaine complete jusqu'au score


class TestHausseTarif:
    def test_apply_met_a_jour_le_tarif_et_l_urgency(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        _set_kpis(service, node_id, {"cost.tariff": 1.05})
        service.evaluate_all(persist=True)
        node_avant = service.repo.get_node(node_id)
        assert node_avant is not None
        avant = (node_avant.urgency.ur_local, node_avant.urgency.ur)

        engine.apply(node_id, "hausse_tarif", {"pct": 12.0})

        assert _kpi(service, node_id, "cost.tariff") == pytest.approx(1.176, abs=1e-9)
        # evaluate_all a ete appele : l'urgency du noeud a bouge (u_cost recalcule).
        node_apres = service.repo.get_node(node_id)
        assert node_apres is not None
        apres = (node_apres.urgency.ur_local, node_apres.urgency.ur)
        assert apres != avant


# Erreurs : deja annule, evenement inconnu, noeud inconnu


class TestErreurs:
    def test_revert_deja_reverte_leve_value_error(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        event = engine.apply(node_id, "pic_demande", {"nouvelle_demande": 250.0})
        engine.revert(event.id, node_id)
        with pytest.raises(ValueError, match="déjà annulé"):
            engine.revert(event.id, node_id)

    def test_revert_event_id_inconnu_leve_value_error(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            engine.revert("evt-fantome", node_id)

    def test_preview_noeud_inconnu_leve_key_error(
        self, service: SupplyScoreService, engine: EventEngine, projet: Project
    ) -> None:
        with pytest.raises(KeyError, match="fantome"):
            engine.preview("fantome", "pic_demande", {"nouvelle_demande": 10.0})

    def test_apply_parametre_invalide_n_ecrit_rien(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        with pytest.raises(ValueError):
            engine.apply(node_id, "panne_machine", {"duree_arret_h": -5.0, "gravite": "majeure"})
        assert service.client_db(node_id).list_events(node_id) == []


# open_events / list_week


class TestRelecture:
    def test_open_events_exclut_les_revertes_plus_recents_d_abord(
        self,
        service: SupplyScoreService,
        engine: EventEngine,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        e1 = engine.apply(node_id, "pic_demande", {"nouvelle_demande": 250.0})
        fixed_clock.set(_NOW + 3600.0)  # une heure plus tard, meme semaine
        e2 = engine.apply(node_id, "instabilite_politique", {"niveau": 0.7})

        assert [e.id for e in engine.open_events(node_id)] == [e2.id, e1.id]

        engine.revert(e1.id, node_id)
        assert [e.id for e in engine.open_events(node_id)] == [e2.id]

    def test_list_week_filtre_par_semaine(
        self,
        service: SupplyScoreService,
        engine: EventEngine,
        node_id: str,
        fixed_clock: FixedClock,
    ) -> None:
        e1 = engine.apply(node_id, "pic_demande", {"nouvelle_demande": 250.0})
        fixed_clock.set(_NOW + 3600.0)
        e2 = engine.apply(node_id, "instabilite_politique", {"niveau": 0.7})
        fixed_clock.set(_NOW + _WEEK)  # semaine suivante
        e3 = engine.apply(node_id, "pic_demande", {"nouvelle_demande": 300.0})

        s24, s25 = iso_week(_NOW), iso_week(_NOW + _WEEK)
        assert s24 == "2026-S24" and s25 == "2026-S25"
        assert [e.id for e in engine.list_week(node_id, s24)] == [e1.id, e2.id]
        assert [e.id for e in engine.list_week(node_id, s25)] == [e3.id]
        assert engine.list_week(node_id, "2026-S01") == []


# Horloge du PROJET : mode jeu


class TestHorlogeProjet:
    def test_iso_week_vient_de_l_horloge_du_projet_en_mode_jeu(
        self,
        service: SupplyScoreService,
        engine: EventEngine,
        projet: Project,
        node_id: str,
    ) -> None:
        service.set_clock_mode(projet.id, "game")
        service.advance_week(projet.id, 2)

        event = engine.apply(node_id, "instabilite_politique", {"niveau": 0.8})
        assert event.iso_week == iso_week(_NOW + 2 * _WEEK) == "2026-S26"
        assert event.occurred_at == _NOW + 2 * _WEEK

        engine.revert(event.id, node_id)
        assert _event_row(service, node_id, event.id)["reverted_at"] == _NOW + 2 * _WEEK


# Evenement sans aucun impact (tous " ignorer ")


class TestEvenementSansImpact:
    def test_la_ligne_events_est_ecrite_sans_update_kpis(
        self,
        service: SupplyScoreService,
        engine: EventEngine,
        node_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "supplyscore.services.events.compute_impacts", lambda *args, **kwargs: []
        )
        event = engine.apply(node_id, "pic_demande", {"nouvelle_demande": 250.0})
        assert event.impacts == []

        # La trace du declaratif existe, mais aucun KPI n'a ete audite/ecrit.
        assert [r["id"] for r in service.client_db(node_id).list_events(node_id)] == [event.id]
        db = service.client_db(node_id)
        trail = AuditTrail(db.conn, FixedClock(_NOW), lock=db.lock)
        assert trail.history("node_kpis", node_id, limit=200) == []


# Decroissance hebdomadaire


class TestWeeklyDecay:
    def test_decroissance_appliquee_source_weekly(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        # time.delay_h laisse a None : seule l'erosion du risque s'applique.
        _set_kpis(
            service, node_id, {"risk.failure_probability": 0.02, "time.delay_h": None}
        )

        impacts = engine.apply_weekly_decay(node_id, operator_id="op-2")
        assert [i.kpi_path for i in impacts] == ["risk.failure_probability"]
        assert impacts[0].new == pytest.approx(0.01926, abs=TOL)
        assert _kpi(service, node_id, "risk.failure_probability") == pytest.approx(0.01926, abs=TOL)

        entry = _latest_audit(service, node_id, "risk.failure_probability")
        assert entry.source == "weekly"
        assert entry.operator_id == "op-2"

    def test_rien_a_eroder_si_kpi_non_renseigne(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        _set_kpis(
            service, node_id, {"risk.failure_probability": None, "time.delay_h": None}
        )
        assert engine.apply_weekly_decay(node_id) == []


# preview est pur


class TestPreviewPur:
    def test_le_bundle_du_noeud_n_est_pas_modifie(
        self, service: SupplyScoreService, engine: EventEngine, node_id: str
    ) -> None:
        node_repo = service.repo.get_node(node_id)
        node_reg = service.registry.get_node(node_id)
        assert node_repo is not None and node_reg is not None
        avant_repo = copy.deepcopy(node_repo.kpis)
        avant_reg = copy.deepcopy(node_reg.kpis)

        engine.preview(node_id, "panne_machine", PANNE_MAJEURE)

        node_repo = service.repo.get_node(node_id)
        node_reg = service.registry.get_node(node_id)
        assert node_repo is not None and node_repo.kpis == avant_repo
        assert node_reg is not None and node_reg.kpis == avant_reg
        assert service.client_db(node_id).list_events(node_id) == []


# Hypothesis : apply puis revert immediat == identite


def field_strategy(field: EventField) -> st.SearchStrategy:
    """Valeur valide aleatoire pour un champ d'evenement."""
    if field.kind == "choice":
        return st.sampled_from(field.choices)
    lo = field.minimum if field.minimum is not None else 0.0
    hi = field.maximum if field.maximum is not None else 1e6
    return st.floats(
        min_value=lo,
        max_value=hi,
        exclude_min=field.name in STRICT_POSITIVE,
        allow_nan=False,
        allow_infinity=False,
    )


def kpi_value_strategy(kpi_path: str) -> st.SearchStrategy:
    """Valeur de KPI aleatoire (None ou valeur dans les bornes KPI_CONSTRAINTS)."""
    lo, hi, _unit = KPI_CONSTRAINTS[kpi_path]
    low = lo if lo is not None else 0.0
    high = hi if hi is not None else 1e6
    return st.one_of(
        st.none(),
        st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False),
    )


@pytest.fixture(scope="module")
def moteur_hyp(tmp_path_factory: pytest.TempPathFactory):
    """Service mono-noeud partage entre les exemples Hypothesis (etat remis a zero)."""
    svc = SupplyScoreService(db_dir=tmp_path_factory.mktemp("hyp_store"), clock=FixedClock(_NOW))
    project = Project(id="p-hyp", name="Hyp", owner_node_id="n-hyp", created_at=_NOW, t0_ts=_NOW)
    svc.create_project(project, [SupplyNode(id="n-hyp", name="Nœud Hyp", project_id="p-hyp")], [])
    yield svc, EventEngine(svc)
    svc.close()


@pytest.mark.parametrize("event_type", EVENT_TYPES)
@given(data=st.data())
@settings(max_examples=10, deadline=None)
def test_apply_puis_revert_immediat_est_identite(
    moteur_hyp: tuple[SupplyScoreService, EventEngine], event_type: str, data: st.DataObject
) -> None:
    svc, engine = moteur_hyp
    spec = EVENT_CALIBRATION[event_type]
    params = {field.name: data.draw(field_strategy(field)) for field in spec.fields}
    baseline = {path: data.draw(kpi_value_strategy(path), label=path) for path in TOUCHED_PATHS}

    # Etat de depart tire au sort, pose sur TOUS les chemins touchables (reinitialise aussi les restes de l'exemple precedent).
    svc.mutations.update_kpis("n-hyp", baseline, source="edit")
    node = svc.registry.get_node("n-hyp")
    assert node is not None
    avant = copy.deepcopy(node.kpis)

    event = engine.apply("n-hyp", event_type, params)
    engine.revert(event.id, "n-hyp")

    node = svc.registry.get_node("n-hyp")
    assert node is not None
    # Identite champ a champ : l'egalite des dataclasses compare chaque bloc/champ.
    assert node.kpis == avant
