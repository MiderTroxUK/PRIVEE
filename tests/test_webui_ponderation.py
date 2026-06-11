"""Tests du Lot 12.4a : page « /ponderation » — pondération FBWM des blocs d'Ur, sans serveur.

Couvre : le rendu des 2n−3 dropdowns de jugement (convention alignée sur
``resoudre_fbwm`` : a_BW saisi une seule fois côté Best→Autres), l'aperçu
live (poids ~uniformes et badge vert pour des jugements tous « également
important », badge rouge pour des jugements incohérents, avertissement de
repli si le solveur échoue), l'enregistrement par projet (persistance via
``set_poids_criteres``, message avec la semaine ISO, refus sans projet ou
si CR >= 0.10) et le retour aux poids uniformes. Callbacks appelés
directement (fonctions module), service seedé partagé via ``set_service``
et libéré en teardown, FixedClock.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import dash
import pytest
from dash.exceptions import PreventUpdate

from supplyscore.core.clock import FixedClock
from supplyscore.core.ur_model import BLOCKS
from supplyscore.mcda.fbwm import ECHELLE_LINGUISTIQUE, ResultatFBWM
from supplyscore.services import SupplyScoreService
from supplyscore.web_ui import set_service
from supplyscore.web_ui.components.explain_figures import BLOCK_LABELS_FR
from supplyscore.web_ui.components.layout import COLORS
from supplyscore.web_ui.pages import ponderation

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = "2026-S24"

_BEST, _WORST = "time", "co2"


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(_NOW)


@pytest.fixture
def seeded(tmp_path: Path, fixed_clock: FixedClock):
    """Couple (service seedé à horloge figée, projet de démo), partagé par les callbacks."""
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=fixed_clock)
    project = svc.seed_demo(n_ranks=2, seed=1)
    set_service(svc)
    yield svc, project
    set_service(None)
    svc.close()


def _project_data(project) -> dict:
    """Contenu du ``dcc.Store`` « store-project » tel que posé par la page Projets."""
    return {"project_id": project.id, "name": project.name}


# --- Helpers d'inspection d'arbres de composants Dash -------------------------------


def _walk(component):
    """Itère récursivement sur un arbre de composants Dash (children imbriqués)."""
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    else:
        yield from _walk(children)


def _pattern_ids(component, type_name: str) -> list[str]:
    """Index des composants à id composite ``{"type": type_name, "index": ...}``."""
    return [
        c.id["index"]
        for c in _walk(component)
        if isinstance(getattr(c, "id", None), dict) and c.id.get("type") == type_name
    ]


def _texts(component) -> str:
    """Concatène tous les textes feuilles de l'arbre de composants."""
    parts: list[str] = []
    for c in _walk(component):
        if isinstance(c, str):
            parts.append(c)
    return " ".join(parts)


def _saisie(best: str, worst: str, jugement: str = "egalement_important", surcharges=None):
    """Valeurs/ids des dropdowns bo/ow : ``jugement`` partout, sauf surcharges.

    Les surcharges sont indexées par ``("bo", bloc)`` ou ``("ow", bloc)``.
    """
    surcharges = surcharges or {}
    bo_ids = [{"type": "pond-bo", "index": b} for b in BLOCKS if b != best]
    ow_ids = [{"type": "pond-ow", "index": b} for b in BLOCKS if b not in (best, worst)]
    bo_vals = [surcharges.get(("bo", i["index"]), jugement) for i in bo_ids]
    ow_vals = [surcharges.get(("ow", i["index"]), jugement) for i in ow_ids]
    return bo_vals, ow_vals, bo_ids, ow_ids


def _saisie_incoherente(best: str, worst: str):
    """Jugements volontairement incohérents : a_BW = 1 mais a_Bj = a_jW = 4."""
    surcharges = {("bo", worst): "egalement_important"}
    return _saisie(best, worst, jugement="absolument_plus_important", surcharges=surcharges)


# --- Rendu des 2n−3 jugements --------------------------------------------------------


class TestRenderJugements:
    def test_best_time_worst_co2_rend_5_bo_et_4_ow(self):
        rendu = ponderation.render_judgments_callback(_BEST, _WORST)
        bo = _pattern_ids(rendu, "pond-bo")
        ow = _pattern_ids(rendu, "pond-ow")
        assert sorted(bo) == sorted(set(BLOCKS) - {_BEST})
        assert sorted(ow) == sorted(set(BLOCKS) - {_BEST, _WORST})
        assert len(bo) == 5 and len(ow) == 4  # 2n−3 = 9 jugements pour n = 6
        # Le jugement a_BW (time contre co2) est bien présent côté Best→Autres.
        assert _WORST in bo

    def test_libelles_francais_des_blocs_et_jugements(self):
        rendu = ponderation.render_judgments_callback(_BEST, _WORST)
        texte = _texts(rendu)
        assert BLOCK_LABELS_FR["time"] in texte
        assert BLOCK_LABELS_FR["co2"] in texte
        options = ponderation._jugement_options()
        assert {o["value"] for o in options} == set(ECHELLE_LINGUISTIQUE)
        assert {o["label"] for o in options} == {
            "Également important",
            "Faiblement plus important",
            "Assez plus important",
            "Très plus important",
            "Absolument plus important",
        }

    def test_best_egal_worst_message_erreur_sans_jugements(self):
        rendu = ponderation.render_judgments_callback("time", "time")
        assert _pattern_ids(rendu, "pond-bo") == []
        assert _pattern_ids(rendu, "pond-ow") == []
        assert "distincts" in _texts(rendu)

    def test_selection_partielle_invite(self):
        rendu = ponderation.render_judgments_callback("time", None)
        assert _pattern_ids(rendu, "pond-bo") == []
        assert "Choisissez" in _texts(rendu)


# --- Aperçu live -----------------------------------------------------------------------


class TestApercu:
    def test_jugements_uniformes_poids_uniformes_cr_nul_badge_vert(self):
        bo_vals, ow_vals, bo_ids, ow_ids = _saisie(_BEST, _WORST)
        fig, badges = ponderation.preview_callback(_BEST, _WORST, bo_vals, ow_vals, bo_ids, ow_ids)
        poids = list(fig.data[0].x)
        assert len(poids) == len(BLOCKS)
        for p in poids:
            assert p == pytest.approx(1.0 / len(BLOCKS), abs=0.02)
        texte = _texts(badges)
        assert "cohérents" in texte
        assert "incohérents" not in texte
        spans = [c for c in _walk(badges) if isinstance(getattr(c, "style", None), dict)]
        assert any(s.style.get("color") == COLORS["ok"] for s in spans)
        resultat = ponderation._resultat_depuis_saisie(
            _BEST, _WORST, bo_vals, bo_ids, ow_vals, ow_ids
        )
        assert resultat is not None and resultat.coherent
        assert resultat.cr == pytest.approx(0.0, abs=0.02)

    def test_jugements_incoherents_badge_rouge(self):
        bo_vals, ow_vals, bo_ids, ow_ids = _saisie_incoherente(_BEST, _WORST)
        _fig, badges = ponderation.preview_callback(_BEST, _WORST, bo_vals, ow_vals, bo_ids, ow_ids)
        texte = _texts(badges)
        assert "incohérents" in texte and "révisez" in texte
        spans = [c for c in _walk(badges) if isinstance(getattr(c, "style", None), dict)]
        assert any(s.style.get("color") == COLORS["alert"] for s in spans)

    def test_selection_incomplete_figure_vide(self):
        fig, badges = ponderation.preview_callback(None, None, [], [], [], [])
        assert fig.data == ()  # figure vide à message, aucune barre
        assert _texts(badges) == ""

    def test_jugement_manquant_figure_vide(self):
        bo_vals, ow_vals, bo_ids, ow_ids = _saisie(_BEST, _WORST)
        bo_vals[0] = None
        fig, _badges = ponderation.preview_callback(_BEST, _WORST, bo_vals, ow_vals, bo_ids, ow_ids)
        assert fig.data == ()

    def test_converge_false_avertissement_repli(self):
        repli = ResultatFBWM(
            poids={b: 1.0 / len(BLOCKS) for b in BLOCKS},
            poids_flous={b: (1 / 6, 1 / 6, 1 / 6) for b in BLOCKS},
            xi_star=math.inf,
            cr=math.inf,
            coherent=False,
            converge=False,
        )
        badges = ponderation._badges_resultat(repli)
        texte = _texts(badges)
        assert "Solveur en échec" in texte
        assert "poids uniformes de repli" in texte


# --- Enregistrement --------------------------------------------------------------------


class TestSave:
    def test_save_persiste_poids_et_message_avec_semaine(self, seeded):
        service, project = seeded
        assert service.poids_criteres(project.id) is None
        bo_vals, ow_vals, bo_ids, ow_ids = _saisie(_BEST, _WORST)
        msg, courant = ponderation.save_callback(
            1, _BEST, _WORST, bo_vals, ow_vals, bo_ids, ow_ids, _project_data(project)
        )
        poids = service.poids_criteres(project.id)
        assert poids is not None
        assert set(poids) == set(BLOCKS)
        assert sum(poids.values()) == pytest.approx(1.0, abs=1e-6)
        texte = _texts(msg)
        assert _WEEK in texte and "enregistrés" in texte
        assert msg.style["color"] == COLORS["ok"]
        assert "Poids actuels du projet" in _texts(courant)
        # La provenance FBWM (méthode + ξ*) est consignée dans le registre.
        brut = service.registry.get_setting(project.id, "omega_ur")
        assert brut["methode"] == "fbwm"
        assert brut["iso_week"] == _WEEK
        assert brut["xi_star"] is not None

    def test_save_sans_projet_erreur_francaise(self, seeded):
        service, project = seeded
        bo_vals, ow_vals, bo_ids, ow_ids = _saisie(_BEST, _WORST)
        msg, courant = ponderation.save_callback(
            1, _BEST, _WORST, bo_vals, ow_vals, bo_ids, ow_ids, None
        )
        assert "Aucun projet actif" in _texts(msg)
        assert msg.style["color"] == COLORS["alert"]
        assert courant is dash.no_update
        assert service.poids_criteres(project.id) is None

    def test_save_incoherent_refus_sans_persistance(self, seeded):
        service, project = seeded
        bo_vals, ow_vals, bo_ids, ow_ids = _saisie_incoherente(_BEST, _WORST)
        msg, courant = ponderation.save_callback(
            1, _BEST, _WORST, bo_vals, ow_vals, bo_ids, ow_ids, _project_data(project)
        )
        texte = _texts(msg)
        assert "incohérents" in texte and "révisez" in texte
        assert msg.style["color"] == COLORS["alert"]
        assert courant is dash.no_update
        assert service.poids_criteres(project.id) is None

    def test_save_saisie_incomplete_refus(self, seeded):
        service, project = seeded
        msg, courant = ponderation.save_callback(
            1, _BEST, None, [], [], [], [], _project_data(project)
        )
        assert "incomplète" in _texts(msg)
        assert courant is dash.no_update
        assert service.poids_criteres(project.id) is None

    def test_save_sans_clic_prevent_update(self, seeded):
        with pytest.raises(PreventUpdate):
            ponderation.save_callback(None, _BEST, _WORST, [], [], [], [], None)


# --- Retour aux poids uniformes ---------------------------------------------------------


class TestReset:
    def test_reset_persiste_poids_uniformes(self, seeded):
        service, project = seeded
        bo_vals, ow_vals, bo_ids, ow_ids = _saisie(
            _BEST, _WORST, surcharges={("bo", "co2"): "tres_plus_important"}
        )
        ponderation.save_callback(
            1, _BEST, _WORST, bo_vals, ow_vals, bo_ids, ow_ids, _project_data(project)
        )
        msg, courant = ponderation.reset_callback(1, _project_data(project))
        poids = service.poids_criteres(project.id)
        assert poids == {b: pytest.approx(1.0 / len(BLOCKS)) for b in BLOCKS}
        texte = _texts(msg)
        assert "uniformes" in texte and _WEEK in texte
        assert msg.style["color"] == COLORS["ok"]
        assert "Poids actuels du projet" in _texts(courant)

    def test_reset_sans_projet_erreur_francaise(self, seeded):
        msg, courant = ponderation.reset_callback(1, None)
        assert "Aucun projet actif" in _texts(msg)
        assert courant is dash.no_update

    def test_reset_sans_clic_prevent_update(self, seeded):
        with pytest.raises(PreventUpdate):
            ponderation.reset_callback(None, _project_data(seeded[1]))


# --- Bandeau des poids actuels et figure ------------------------------------------------


class TestPoidsActuels:
    def test_sans_projet_invite(self, seeded):
        rendu = ponderation.current_weights_callback(None)
        assert "Aucun projet actif" in _texts(rendu)

    def test_sans_poids_stockes_uniformes(self, seeded):
        _service, project = seeded
        rendu = ponderation.current_weights_callback(_project_data(project))
        assert "uniformes" in _texts(rendu)

    def test_avec_poids_stockes_detail_francais(self, seeded):
        service, project = seeded
        service.set_poids_criteres(project.id, {b: 1.0 / len(BLOCKS) for b in BLOCKS})
        rendu = ponderation.current_weights_callback(_project_data(project))
        texte = _texts(rendu)
        for label in BLOCK_LABELS_FR.values():
            assert label in texte
        assert "0.167" in texte


class TestFigure:
    def test_barres_dans_l_ordre_canonique_des_blocs(self):
        poids = {b: (i + 1) / 21 for i, b in enumerate(BLOCKS)}
        fig = ponderation.poids_bars_figure(poids)
        assert list(fig.data[0].y) == [BLOCK_LABELS_FR[b] for b in BLOCKS]
        assert list(fig.data[0].x) == pytest.approx([poids[b] for b in BLOCKS])


# --- Layout et enregistrement des callbacks ---------------------------------------------


class TestLayoutEtCallbacks:
    def test_layout_contient_les_ids_attendus(self, seeded):
        page = ponderation.layout()
        ids = {getattr(c, "id", None) for c in _walk(page)}
        for attendu in (
            "pond-best-dd",
            "pond-worst-dd",
            "pond-judgments",
            "pond-preview-badges",
            "pond-weights-fig",
            "pond-save-btn",
            "pond-reset-btn",
            "pond-save-msg",
            "pond-reset-msg",
            "pond-current-weights",
        ):
            assert attendu in ids
        texte = _texts(page)
        assert "FBWM pondère les 6 BLOCS KPI" in texte
        assert "besoin déclaré Ud" in texte

    def test_register_callbacks_sans_erreur(self):
        app = dash.Dash(__name__)
        app.layout = ponderation.layout()
        ponderation.register_callbacks(app)
        assert len(app.callback_map) == 5
