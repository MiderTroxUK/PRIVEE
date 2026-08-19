"""Tests du Lot 6.5 : page " /hebdo " - revue hebdomadaire en quatre volets, sans serveur.

Couvre : la bijection Saaty<->bipolaire (17 valeurs) et l'inverse des notes,
le pre-remplissage du volet AHP depuis la derniere evaluation, " Confirmer a
l'identique " (nouvelle evaluation persistee cette semaine, volet [ok]), le
volet KPIs (enregistrement -> registre, " rien n'a change " -> decroissance,
avertissement double comptage), le volet Jalons (confirm_milestone audite),
le volet Evenements (preview avant/apres, apply, decision avec snapshot,
annulation avec ConflictError francais) et la cloture (duree, erreur
francaise si incomplet). Callbacks appeles directement (fonctions module),
service seede partage via ``set_service`` et libere en teardown, FixedClock.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import dash
import pytest

from supplyscore.core import CONSISTENCY_THRESHOLD, bipolar_to_saaty, score_6_to_9
from supplyscore.core.clock import FixedClock
from supplyscore.data.audit import AuditTrail
from supplyscore.domain.milestones import MilestoneStatus
from supplyscore.domain.models import TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services.decisions import DecisionService
from supplyscore.services.events import EventEngine
from supplyscore.services.weekly import WeeklyReview
from supplyscore.web_ui import set_service
from supplyscore.web_ui.pages import weekly
from supplyscore.web_ui.pages.questionnaire import KPI_FIELDS, PAIRS

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = "2026-S24"

#: Parametres de la panne machine du cas chiffre du PLAN (0.02 -> ~0.0563).
_PANNE = {"duree_arret_h": 24.0, "gravite": "majeure"}

_OPERATOR = {"name": "testeuse"}


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def service(tmp_path: Path, fixed_clock: FixedClock):
    """Service a horloge figee (2026-S24), partage par les callbacks de la page."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    set_service(svc)
    yield svc
    set_service(None)
    svc.close()


@pytest.fixture
def node_id(service: SupplyScoreService) -> str:
    """Premier noeud actif (ordre deterministe) du projet de demo seede."""
    service.seed_demo(n_ranks=2, seed=1)
    nodes = sorted(service.repo.nodes(), key=lambda n: n.id)
    actifs = [n for n in nodes if n.status is TaskStatus.ACTIVE]
    assert actifs, "le projet de démo doit contenir au moins un nœud actif"
    return actifs[0].id


@pytest.fixture
def store(node_id: str) -> dict:
    """Contenu de ``store-hebdo`` apres selection du noeud."""
    return {"node_id": node_id}


def _volets(service: SupplyScoreService, node_id: str) -> dict[str, int]:
    return WeeklyReview(service).review_status(node_id)["volets"]


def _kpi(service: SupplyScoreService, node_id: str, path: str) -> float | None:
    node = service.registry.get_node(node_id)
    assert node is not None
    block, field = path.split(".", 1)
    return getattr(getattr(node.kpis, block), field)


def _kpi_args(**values: float) -> tuple[list, list[dict]]:
    """Valeurs/ids des inputs {"type": "hebdo-kpi"} : tout vide sauf ``values``."""
    ids = [
        {"type": "hebdo-kpi", "index": path} for _bloc, fields in KPI_FIELDS for path, _ in fields
    ]
    vals = [values.get(id_["index"].replace(".", "_")) for id_ in ids]
    return vals, ids


def _param_args(params: dict) -> tuple[list, list[dict]]:
    """Valeurs/ids des champs {"type": "ev-param"} d'un formulaire d'evenement."""
    ids = [{"type": "ev-param", "index": name} for name in params]
    return list(params.values()), ids


# Conversions Saaty <-> UI


class TestConversions:
    def test_bijection_bipolaire_sur_les_17_valeurs(self) -> None:
        for v in range(-8, 9):
            assert weekly.saaty_to_bipolar(bipolar_to_saaty(v)) == v

    def test_bijection_notes_sur_les_6_valeurs(self) -> None:
        for v in range(1, 7):
            assert weekly.saaty_to_score6(score_6_to_9(float(v))) == v

    def test_saaty_hors_echelle_borne_sur_l_intervalle(self) -> None:
        assert weekly.saaty_to_bipolar(9.4) == 8
        assert weekly.saaty_to_score6(9.0) == 6
        assert weekly.saaty_to_score6(1.0) == 1


# Volet 1 : pre-remplissage et soumissions


class TestVoletAhp:
    def test_prefill_reprend_la_derniere_evaluation(self, service, node_id) -> None:
        latest = service.client_db(node_id).latest_assessment(node_id)
        assert latest is not None

        pairs, scores = weekly.ahp_prefill(service, node_id)

        for (i, j), saaty in latest.comparisons.items():
            assert pairs[f"{i}-{j}"] == weekly.saaty_to_bipolar(saaty)
            # L'echelle de Saaty discrete du generateur fait l'aller-retour exact.
            assert bipolar_to_saaty(pairs[f"{i}-{j}"]) == pytest.approx(saaty)
        for k, s in enumerate(latest.criteria_scores):
            assert scores[str(k)] == weekly.saaty_to_score6(s)

    def test_prefill_sans_evaluation_donne_les_defauts(self, service) -> None:
        from supplyscore.domain.models import Project, SupplyNode

        project = Project(id="p9", name="Vierge", owner_node_id="n-z", created_at=_NOW, t0_ts=_NOW)
        service.create_project(project, [SupplyNode(id="n-z", name="n-z", project_id="p9")], [])

        pairs, scores = weekly.ahp_prefill(service, "n-z")

        assert set(pairs.values()) == {0}
        assert set(scores.values()) == {3}

    def test_confirm_identique_persiste_cette_semaine_et_marque_le_volet(
        self, service, node_id, store
    ) -> None:
        client = service.client_db(node_id)
        latest = client.latest_assessment(node_id)
        avant = len(client.list_assessments(node_id))

        message, _badge, _check = weekly.ahp_confirm_callback(1, store, _OPERATOR)

        assert "confirmée à l'identique" in str(message)
        assert len(client.list_assessments(node_id)) == avant + 1
        assert client.last_assessment_week(node_id) == _WEEK
        nouvelle = client.latest_assessment(node_id)
        assert nouvelle is not None
        assert nouvelle.comparisons == latest.comparisons
        assert nouvelle.criteria_scores == latest.criteria_scores
        assert nouvelle.operator_id == "testeuse"
        assert _volets(service, node_id)["ahp"] == 1

    def test_save_enregistre_les_sliders_et_marque_le_volet(self, service, node_id, store) -> None:
        pair_ids = [{"type": "hebdo-ahp-pair", "index": f"{i}-{j}"} for i, j in PAIRS]
        score_ids = [{"type": "hebdo-ahp-score", "index": str(k)} for k in range(4)]

        message, _badge, _check = weekly.ahp_save_callback(
            1, store, _OPERATOR, [0] * len(PAIRS), pair_ids, [4] * 4, score_ids
        )

        assert "Évaluation enregistrée" in str(message)
        latest = service.client_db(node_id).latest_assessment(node_id)
        assert latest is not None
        assert latest.consistency_ratio < CONSISTENCY_THRESHOLD
        assert latest.criteria_scores == [score_6_to_9(4.0)] * 4
        assert _volets(service, node_id)["ahp"] == 1

    def test_save_refuse_un_cr_incoherent(self, service, node_id, store) -> None:
        # (0,1)=+8 et (1,2)=+8 mais (0,2)=-8 : jugements volontairement incoherents.
        sliders = {"0-1": 8, "0-2": -8, "0-3": 0, "1-2": 8, "1-3": 0, "2-3": 0}
        pair_ids = [{"type": "hebdo-ahp-pair", "index": key} for key in sliders]
        score_ids = [{"type": "hebdo-ahp-score", "index": str(k)} for k in range(4)]
        avant = len(service.client_db(node_id).list_assessments(node_id))

        message, _badge, _check = weekly.ahp_save_callback(
            1, store, _OPERATOR, list(sliders.values()), pair_ids, [3] * 4, score_ids
        )

        assert "refusé" in str(message)
        assert len(service.client_db(node_id).list_assessments(node_id)) == avant
        assert _volets(service, node_id)["ahp"] == 0


# Volet 2 : KPIs


class TestVoletKpis:
    def test_enregistrer_un_kpi_le_pose_au_registre_et_marque_le_volet(
        self, service, node_id, store
    ) -> None:
        values, ids = _kpi_args(time_lead_time_h=300)

        message, _badge, _check = weekly.kpi_save_callback(1, store, _OPERATOR, values, ids)

        assert "1 KPI mis à jour" in str(message)
        assert _kpi(service, node_id, "time.lead_time_h") == 300.0
        assert _volets(service, node_id)["kpis"] == 1

    def test_rien_n_a_change_applique_la_decroissance_et_marque_le_volet(
        self, service, node_id, store
    ) -> None:
        service.mutations.update_kpis(node_id, {"risk.failure_probability": 0.2}, source="edit")

        message, _badge, _check = weekly.kpi_none_callback(1, store, _OPERATOR)

        assert "décroissance hebdomadaire" in str(message)
        p_apres = _kpi(service, node_id, "risk.failure_probability")
        assert p_apres is not None and p_apres < 0.2
        assert _volets(service, node_id)["kpis"] == 1
        # Chaque bloc KPI porte sa ligne d'audit de confirmation " __confirmed__ ".
        client = service.client_db(node_id)
        trail = AuditTrail(client.conn, FixedClock(_NOW), lock=client.lock)
        entries = trail.history("node_kpis", node_id, field="__confirmed__", limit=20)
        assert {entry.new_value for entry in entries} >= set(weekly.KPI_BLOCKS)

    def test_avertissement_double_comptage_apres_un_evenement_de_la_semaine(
        self, service, node_id, store
    ) -> None:
        service.mutations.update_kpis(node_id, {"risk.failure_probability": 0.02}, source="edit")
        EventEngine(service).apply(node_id, "panne_machine", _PANNE, operator_id="op")

        body = str(weekly._kpi_body(service, node_id))

        assert "Déjà modifié par l'événement" in body
        assert "Panne machine" in body

    def test_sans_evenement_aucun_avertissement(self, service, node_id) -> None:
        body = str(weekly._kpi_body(service, node_id))
        assert "Déjà modifié par l'événement" not in body

    def test_valeur_invalide_refusee_sans_marquer_le_volet(self, service, node_id, store) -> None:
        values, ids = _kpi_args(risk_failure_probability=4.2)  # hors [0, 1]

        message, _badge, _check = weekly.kpi_save_callback(1, store, _OPERATOR, values, ids)

        assert "KPIs refusés" in str(message)
        assert _volets(service, node_id)["kpis"] == 0


# Volet 3 : jalons


class TestVoletJalons:
    def _premier_jalon_actif(self, service, node_id):
        actifs = [
            m
            for m in service.registry.list_milestones(node_id)
            if m.status is MilestoneStatus.ACTIVE
        ]
        assert actifs, "le nœud de démo doit avoir au moins un jalon actif"
        return sorted(actifs, key=lambda m: (m.position, m.deadline_ts))[0]

    def test_modifier_un_progress_audite_et_marque_le_volet(self, service, node_id, store) -> None:
        jalon = self._premier_jalon_actif(service, node_id)
        nouveau_pct = 80 if round(jalon.progress * 100) != 80 else 70

        message, _badge, _check, _body = weekly.ms_save_callback(
            1,
            store,
            _OPERATOR,
            [str(jalon.status)],
            [{"type": "hebdo-ms-status", "index": jalon.id}],
            [nouveau_pct],
            [{"type": "hebdo-ms-progress", "index": jalon.id}],
        )

        assert "Jalons confirmés (1 modifié(s))" in str(message)
        relu = service.registry.get_milestone(jalon.id)
        assert relu is not None
        assert relu.progress == pytest.approx(nouveau_pct / 100.0)
        assert _volets(service, node_id)["jalons"] == 1
        # confirm_milestone passe par MutationService : audit " milestone " au registre.
        trail = AuditTrail(service.registry.conn, FixedClock(_NOW), lock=service.registry.lock)
        entries = trail.history("milestone", jalon.id, field="progress", limit=5)
        assert entries and entries[0].source == "weekly"
        assert entries[0].operator_id == "testeuse"

    def test_jalon_inchange_est_un_noop_mais_marque_le_volet(self, service, node_id, store) -> None:
        jalon = self._premier_jalon_actif(service, node_id)

        message, _badge, _check, _body = weekly.ms_save_callback(
            1,
            store,
            _OPERATOR,
            [str(jalon.status)],
            [{"type": "hebdo-ms-status", "index": jalon.id}],
            [round(jalon.progress * 100)],
            [{"type": "hebdo-ms-progress", "index": jalon.id}],
        )

        assert "0 modifié(s)" in str(message)
        assert _volets(service, node_id)["jalons"] == 1

    def test_le_corps_affiche_l_avancement_theorique(self, service, node_id) -> None:
        body = str(weekly._ms_body(service, node_id))
        assert "théorique" in body
        assert "Confirmer les jalons" in body


# Volet 4 : evenements et decision


class TestVoletEvenements:
    def test_preview_panne_machine_montre_avant_apres(self, service, node_id, store) -> None:
        service.mutations.update_kpis(node_id, {"risk.failure_probability": 0.02}, source="edit")
        values, ids = _param_args(_PANNE)

        table = str(weekly.ev_preview_callback(1, store, "panne_machine", values, ids))

        assert "Avant" in table and "Après" in table
        assert "risk.failure_probability" in table
        assert "0.02" in table
        # Rien n'est ecrit : la previsualisation est pure.
        assert _kpi(service, node_id, "risk.failure_probability") == 0.02

    def test_apply_journalise_et_marque_le_volet(self, service, node_id, store) -> None:
        service.mutations.update_kpis(node_id, {"risk.failure_probability": 0.02}, source="edit")
        values, ids = _param_args(_PANNE)

        message, _badge, _check, week_list, _open_list, _kpi_body = weekly.ev_apply_callback(
            1, store, _OPERATOR, "panne_machine", values, ids
        )

        assert "Panne machine" in str(message)
        events = EventEngine(service).list_week(node_id, _WEEK)
        assert len(events) == 1
        assert events[0].operator_id == "testeuse"
        assert _kpi(service, node_id, "risk.failure_probability") == pytest.approx(0.0563, abs=1e-3)
        assert _volets(service, node_id)["evenements"] == 1
        assert "Panne machine" in str(week_list)

    def test_revert_conflit_affiche_le_message_francais(
        self, service, node_id, store, monkeypatch
    ) -> None:
        service.mutations.update_kpis(node_id, {"risk.failure_probability": 0.02}, source="edit")
        event = EventEngine(service).apply(node_id, "panne_machine", _PANNE, operator_id="op")
        # Reecriture manuelle d'un KPI touche : l'annulation doit refuser.
        service.mutations.update_kpis(node_id, {"risk.failure_probability": 0.5}, source="edit")
        monkeypatch.setattr(
            weekly, "_triggered_id", lambda: {"type": "ev-revert", "index": event.id}
        )

        message, *_rest = weekly.ev_revert_callback([1], store)

        assert "Annulation impossible" in str(message)
        assert _kpi(service, node_id, "risk.failure_probability") == 0.5

    def test_revert_restaure_les_kpis(self, service, node_id, store, monkeypatch) -> None:
        service.mutations.update_kpis(node_id, {"risk.failure_probability": 0.02}, source="edit")
        event = EventEngine(service).apply(node_id, "panne_machine", _PANNE, operator_id="op")
        monkeypatch.setattr(
            weekly, "_triggered_id", lambda: {"type": "ev-revert", "index": event.id}
        )

        message, *_rest = weekly.ev_revert_callback([1], store)

        assert "Événement annulé" in str(message)
        assert _kpi(service, node_id, "risk.failure_probability") == pytest.approx(0.02)

    def test_decision_enregistree_avec_snapshot(self, service, node_id, store) -> None:
        message, _badge, _check, liste, texte = weekly.decision_callback(
            1, store, _OPERATOR, "Doubler le stock de sécurité"
        )

        assert "Décision consignée" in str(message)
        assert texte == ""
        decisions = DecisionService(service).list_for_node(node_id, _WEEK)
        assert len(decisions) == 1
        assert decisions[0].description == "Doubler le stock de sécurité"
        assert decisions[0].operator_id == "testeuse"
        assert set(decisions[0].scores) == {"ud", "ur", "a", "f", "h"}
        assert "Doubler le stock" in str(liste)
        assert _volets(service, node_id)["evenements"] == 1

    def test_decision_vide_refusee(self, service, node_id, store) -> None:
        message, *_rest = weekly.decision_callback(1, store, _OPERATOR, "   ")
        assert "Décision refusée" in str(message)
        assert _volets(service, node_id)["evenements"] == 0

    def test_aucun_evenement_ni_decision_marque_le_volet(self, service, node_id, store) -> None:
        message, _badge, _check = weekly.ev_none_callback(1, store, _OPERATOR)
        assert "Rien à signaler" in str(message)
        assert _volets(service, node_id)["evenements"] == 1


# Cloture


class TestCloture:
    def test_complete_avant_les_quatre_volets_erreur_francaise(
        self, service, node_id, store
    ) -> None:
        message, _badge = weekly.complete_callback(1, store)

        assert "Revue hebdomadaire incomplète" in str(message)
        assert WeeklyReview(service).review_status(node_id)["completed_at"] is None

    def test_complete_apres_les_quatre_volets_pose_completed_at(
        self, service, node_id, store
    ) -> None:
        review = WeeklyReview(service)
        for volet in ("ahp", "kpis", "jalons", "evenements"):
            review.mark_volet(node_id, volet, "testeuse")

        message, _badge = weekly.complete_callback(1, store)

        assert "Revue clôturée en 0 minute(s)" in str(message)
        assert f"semaine {_WEEK}" in str(message)
        assert review.review_status(node_id)["completed_at"] == _NOW


# Selection de noeud, layout et cablage


class TestPage:
    def test_select_node_demarre_la_revue_et_monte_les_volets(self, service, node_id) -> None:
        outputs = weekly.select_node_callback(node_id)

        data, banner = outputs[0], outputs[1]
        assert data == {"node_id": node_id}
        assert f"Semaine {_WEEK}" in str(banner)
        assert "0/4 volets" in str(outputs[2])
        # started_at pose par WeeklyReview.start (idempotent).
        assert WeeklyReview(service).review_status(node_id)["started_at"] == _NOW
        corps = "".join(str(part) for part in outputs[7:11])
        assert "hebdo-ahp-confirm-btn" in corps
        assert "hebdo-kpi-save-btn" in corps
        assert "hebdo-ms-save-btn" in corps
        assert "hebdo-ev-none-btn" in corps

    def test_progress_badge_suit_les_volets(self, service, node_id, store) -> None:
        weekly.ev_none_callback(1, store, _OPERATOR)
        status = WeeklyReview(service).review_status(node_id)
        assert "1/4 volets" in str(weekly._progress_badge(status))

    def test_options_dropdown_portent_le_statut_hebdo(self, service, node_id) -> None:
        node = service.registry.get_node(node_id)
        assert node is not None
        _info, options = weekly.project_info_callback(
            {"project_id": node.project_id, "name": "Démo"}
        )
        labels = {option["value"]: option["label"] for option in options}
        # seed_demo soumet une evaluation cette semaine : le noeud est " A jour ".
        assert "À jour" in labels[node_id]

    def test_layout_et_enregistrement_des_callbacks(self, service, node_id) -> None:
        page = weekly.layout()
        rendu = str(page)
        assert "hebdo-node-dd" in rendu
        assert "store-hebdo" in rendu
        assert "hebdo-complete-btn" in rendu
        for volet in ("ahp", "kpis", "jalons", "evenements"):
            assert f"hebdo-volet-check-{volet}" in rendu

        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        weekly.register_callbacks(app)  # aucun DuplicateCallback / output invalide

    def test_ev_type_callback_genere_les_champs(self) -> None:
        rendu = str(weekly.ev_type_callback("panne_machine"))
        assert "ev-param" in rendu
        assert "duree_arret_h" in rendu
        assert str(weekly.ev_type_callback(None)) == str(weekly.ev_type_callback(""))
