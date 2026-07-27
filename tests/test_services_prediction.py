"""Tests de PredictionService + CLI predict (HÉLIOS v7, U11) — contrats 5 et 6 figés.

Couvre : le scoring numpy vérifiable à la main sur le fixture
``artifact_v1.json`` (3 features, calibrateur identité, IC80 sur coef_boot
artisanal) ; l'interpolation du calibrateur et l'imputation d'une feature
manquante sur un artefact construit à la main ; les erreurs de validation de
schéma ; le refus MIN_HISTORY_WEEKS et le mode features-only (import
ForecastService monkeypatché absent) sur un projet construit comme
``tests/test_calibration.py`` (chaîne à la main, historique hebdomadaire
inséré directement) ; la variation multi-horizon quand un ForecastService
factice est injecté ; le lazy-import gracieux d'ActionEngine (absent, présent,
en échec) ; les cas limites (horizons vides/invalides, projet inconnu, aucun
nœud actif) ; et le CLI en-process (tableau français, JSON, erreurs).
"""

from __future__ import annotations

import json
import math
import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import (
    KPIBundle,
    Project,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)
from supplyscore.services import SupplyScoreService
from supplyscore.services.prediction import (
    MIN_HISTORY_WEEKS,
    PredictionService,
    _charger_artifact,
    _construire_vecteur,
    _ModelArtifact,
    _score,
    _standardiser,
)
from supplyscore.tools.predict import build_parser, main

#: Mercredi 2026-06-10 12:00 locale — semaine ISO « 2026-S24 ».
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()
_WEEK = 604_800.0
_PROJECT_ID = "proj-predict"

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _sigmoid_ref(z: float) -> float:
    """Sigmoïde de référence, indépendante de l'implémentation testée."""
    return 1.0 / (1.0 + math.exp(-z))


# --- Fixtures partagées ---------------------------------------------------------------


@pytest.fixture
def artifact_path() -> Path:
    return _FIXTURES_DIR / "artifact_v1.json"


@pytest.fixture
def service(tmp_path: Path) -> Iterator[SupplyScoreService]:
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    yield svc
    svc.close()


def _inserer_semaines(
    service: SupplyScoreService, node_id: str, valeurs: list[tuple[float, float, float]]
) -> None:
    """Insère un état hebdomadaire par valeur (ur_local, hidden_risk, ud_local).

    La DERNIÈRE valeur de la liste tombe dans la semaine ISO de ``_NOW`` ; les
    précédentes reculent d'une semaine chacune (même motif que la fixture
    ``partie`` de ``tests/test_calibration.py``).
    """
    n = len(valeurs)
    for i, (ur_local, hidden_risk, ud_local) in enumerate(valeurs):
        decalage = n - 1 - i
        service.client_db(node_id).save_urgency_state(
            node_id,
            UrgencyState(
                ur_local=ur_local,
                hidden_risk=hidden_risk,
                ud_local=ud_local,
                ud=ud_local,
                ur=ur_local,
                timestamp=_NOW - decalage * _WEEK,
            ),
        )


@pytest.fixture
def projet_controle(service: SupplyScoreService) -> tuple[str, str, str, str]:
    """Projet à la main (motif ``chaine`` de test_services_criticite.py) : B -> A, C isolé.

    - A (rang 0) : 4 semaines ISO d'historique, dernier état (ur_local=1.0,
      hidden_risk=1.0) — avec le fixture artifact_v1.json (feature_names
      ["ur_local", "hidden_risk", "rang"], rang de A = 0), le vecteur
      standardisé exact est [1, 1, -1] : z = 3.0, p = sigmoid(3.0), IC80 =
      (sigmoid(2.0), sigmoid(4.0)) — vérifiable à la main (cf. module
      prediction.py et le test dédié).
    - B (rang 1, fournisseur de A) : 2 semaines seulement — exclu par
      MIN_HISTORY_WEEKS.
    - C (rang 0, isolé) : 4 semaines à valeurs CONSTANTES et basses — probabilité
      nettement plus faible que A (vérifie le tri décroissant) et
      delta_vs_last_week == 0.0 exact.
    """
    node_a = SupplyNode(id="A", name="Nœud A", rank=0, project_id=_PROJECT_ID, kpis=KPIBundle())
    node_b = SupplyNode(id="B", name="Nœud B", rank=1, project_id=_PROJECT_ID, kpis=KPIBundle())
    node_c = SupplyNode(id="C", name="Nœud C", rank=0, project_id=_PROJECT_ID, kpis=KPIBundle())
    arc = SupplyArc(source_id="B", target_id="A", gamma=0.5, beta=0.5)
    project = Project(
        id=_PROJECT_ID, name="Projet contrôlé", owner_node_id="A", t0_ts=_NOW - 10 * _WEEK
    )
    service.create_project(project, [node_a, node_b, node_c], [arc])

    _inserer_semaines(
        service, "A", [(0.2, 0.1, 0.3), (0.4, 0.15, 0.3), (0.6, 0.2, 0.3), (1.0, 1.0, 0.3)]
    )
    _inserer_semaines(service, "B", [(0.5, 0.3, 0.2), (0.5, 0.3, 0.2)])
    _inserer_semaines(
        service, "C", [(0.05, 0.02, 0.1), (0.05, 0.02, 0.1), (0.05, 0.02, 0.1), (0.05, 0.02, 0.1)]
    )
    return _PROJECT_ID, "A", "B", "C"


def _bloquer_forecast_et_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force l'absence de ForecastService et ActionEngine (import -> ImportError)."""
    monkeypatch.setitem(sys.modules, "supplyscore.services.forecast", None)
    monkeypatch.setitem(sys.modules, "supplyscore.services.action_engine", None)


# --- Scoring numpy : hand-checkable sur le fixture -------------------------------------


class TestArtifactHandCheckable:
    """Le fixture artifact_v1.json (3 features, calibrateur identité) à la main."""

    def test_probabilite_et_ic80_calcules_a_la_main(self, artifact_path: Path) -> None:
        artifact = _charger_artifact(artifact_path)
        assert artifact.feature_names == ("ur_local", "hidden_risk", "rang")

        x, imputees = _construire_vecteur(
            artifact, {"ur_local": 1.0, "hidden_risk": 1.0, "rang": 0.0}
        )
        assert imputees == []
        x_std = _standardiser(artifact, x)
        assert x_std == pytest.approx([1.0, 1.0, -1.0])

        p, ic80 = _score(artifact, x_std)
        assert p == pytest.approx(_sigmoid_ref(3.0), abs=1e-9)
        assert ic80 is not None
        lo, hi = ic80
        # Les 5 lignes de coef_boot donnent z ∈ {3, 2, 4, 2, 4} : les 10e/90e
        # percentiles retombent EXACTEMENT sur les valeurs dupliquées aux bornes.
        assert lo == pytest.approx(_sigmoid_ref(2.0), abs=1e-9)
        assert hi == pytest.approx(_sigmoid_ref(4.0), abs=1e-9)

    def test_feature_manquante_imputee_a_la_moyenne_du_scaler(self, artifact_path: Path) -> None:
        artifact = _charger_artifact(artifact_path)
        x, imputees = _construire_vecteur(artifact, {"ur_local": 0.9})
        assert sorted(imputees) == ["hidden_risk", "rang"]
        assert x[0] == pytest.approx(0.9)
        assert x[1] == pytest.approx(artifact.scaler_mean[1])
        assert x[2] == pytest.approx(artifact.scaler_mean[2])

    def test_sans_coef_boot_ic80_none(self, artifact_path: Path) -> None:
        artifact = _charger_artifact(artifact_path)
        artifact_sans_boot = _ModelArtifact(
            feature_names=artifact.feature_names,
            scaler_mean=artifact.scaler_mean,
            scaler_std=artifact.scaler_std,
            coef=artifact.coef,
            intercept=artifact.intercept,
            calibrator_x=artifact.calibrator_x,
            calibrator_y=artifact.calibrator_y,
            coef_boot=None,
        )
        x, _ = _construire_vecteur(
            artifact_sans_boot, {"ur_local": 1.0, "hidden_risk": 1.0, "rang": 0.0}
        )
        _p, ic80 = _score(artifact_sans_boot, _standardiser(artifact_sans_boot, x))
        assert ic80 is None


class TestCalibrateur:
    """Interpolation du calibrateur isotonique, isolée du reste du scoring."""

    def test_interpolation_lineaire_par_morceaux(self) -> None:
        # coef nul + intercept = logit(0.25) : p_raw = 0.25 quel que soit x
        # (feature absente -> imputée, valeur sans incidence puisque coef=0).
        artifact = _ModelArtifact(
            feature_names=("x",),
            scaler_mean=np.array([0.0]),
            scaler_std=np.array([1.0]),
            coef=np.array([0.0]),
            intercept=math.log(0.25 / 0.75),
            calibrator_x=np.array([0.0, 0.5, 1.0]),
            calibrator_y=np.array([0.0, 0.8, 1.0]),
            coef_boot=None,
        )
        x, imputees = _construire_vecteur(artifact, {})
        assert imputees == ["x"]
        p, ic80 = _score(artifact, _standardiser(artifact, x))
        assert p == pytest.approx(0.4)  # interp(0.25, [0,.5,1], [0,.8,1])
        assert ic80 is None


# --- Validation de schéma (contrat 5) ---------------------------------------------------


class TestValidationArtefact:
    _BASE: ClassVar[dict[str, object]] = {
        "schema_version": 1,
        "feature_names": ["a", "b"],
        "scaler_mean": [0.0, 0.0],
        "scaler_std": [1.0, 1.0],
        "coef": [1.0, 1.0],
        "intercept": 0.0,
        "calibrator_x": [0.0, 1.0],
        "calibrator_y": [0.0, 1.0],
    }

    def _ecrire(self, tmp_path: Path, **overrides: object) -> Path:
        contenu = {**self._BASE, **overrides}
        chemin = tmp_path / "artifact.json"
        chemin.write_text(json.dumps(contenu), encoding="utf-8")
        return chemin

    def test_fichier_absent(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="illisible"):
            _charger_artifact(tmp_path / "absent.json")

    def test_json_invalide(self, tmp_path: Path) -> None:
        chemin = tmp_path / "artifact.json"
        chemin.write_text("{ceci n'est pas du JSON", encoding="utf-8")
        with pytest.raises(ValueError, match="JSON invalide"):
            _charger_artifact(chemin)

    def test_racine_non_objet(self, tmp_path: Path) -> None:
        chemin = tmp_path / "artifact.json"
        chemin.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ValueError, match="objet JSON"):
            _charger_artifact(chemin)

    def test_schema_version_non_supportee(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="schéma"):
            _charger_artifact(self._ecrire(tmp_path, schema_version=2))

    def test_feature_names_vide(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="feature_names"):
            _charger_artifact(self._ecrire(tmp_path, feature_names=[]))

    def test_feature_names_contient_non_chaine(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="feature_names"):
            _charger_artifact(self._ecrire(tmp_path, feature_names=["a", 2]))

    def test_scaler_mean_longueur_incoherente(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="scaler_mean"):
            _charger_artifact(self._ecrire(tmp_path, scaler_mean=[0.0]))

    def test_coef_valeur_non_numerique(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="coef"):
            _charger_artifact(self._ecrire(tmp_path, coef=[1.0, "beaucoup"]))

    def test_intercept_non_numerique(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="intercept"):
            _charger_artifact(self._ecrire(tmp_path, intercept="zero"))

    def test_calibrator_longueurs_differentes(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="calibrator_x"):
            _charger_artifact(self._ecrire(tmp_path, calibrator_y=[0.0, 0.5, 1.0]))

    def test_calibrator_non_strictement_croissant(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="croissant"):
            _charger_artifact(self._ecrire(tmp_path, calibrator_x=[0.0, 0.0]))

    def test_coef_boot_ligne_longueur_incoherente(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="coef_boot"):
            _charger_artifact(self._ecrire(tmp_path, coef_boot=[[1.0]]))

    def test_coef_boot_vide(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="coef_boot"):
            _charger_artifact(self._ecrire(tmp_path, coef_boot=[]))


# --- MIN_HISTORY_WEEKS + mode features-only + tri ---------------------------------------


class TestPredictMinHistoryEtFeaturesOnly:
    def test_min_history_exclut_b_et_signale(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _bloquer_forecast_et_actions(monkeypatch)
        project_id, node_a, node_b, node_c = projet_controle
        pred = PredictionService(service, artifact_path)

        points = pred.predict(project_id, horizons=(1, 2, 3, 4))

        assert {p.node_id for p in points} == {node_a, node_c}
        avert = " ".join(pred.avertissements)
        assert node_b in avert
        assert "historique hebdomadaire" in avert
        assert "insuffisant" in avert
        assert f"{MIN_HISTORY_WEEKS}" in avert

    def test_mode_features_only_meme_p_sur_tous_horizons(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _bloquer_forecast_et_actions(monkeypatch)
        project_id, node_a, _node_b, _node_c = projet_controle
        pred = PredictionService(service, artifact_path)

        points = pred.predict(project_id, horizons=(1, 2, 3, 4))
        point_a = next(p for p in points if p.node_id == node_a)

        assert len(set(point_a.proba_by_horizon.values())) == 1
        assert point_a.proba_by_horizon[1] == pytest.approx(_sigmoid_ref(3.0), abs=1e-9)
        assert point_a.proba_by_horizon[4] == pytest.approx(_sigmoid_ref(3.0), abs=1e-9)
        assert point_a.ic80_by_horizon[1] == point_a.ic80_by_horizon[4]
        assert point_a.incertitude_mc is None
        assert point_a.incertitude_param is None
        assert point_a.p_jalon_rate is None
        assert point_a.p_impact_client is None
        assert point_a.recommandation is None
        assert any("features-only" in a for a in pred.avertissements)

    def test_drivers_et_delta_vs_last_week_a_la_main(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _bloquer_forecast_et_actions(monkeypatch)
        project_id, node_a, _node_b, node_c = projet_controle
        pred = PredictionService(service, artifact_path)

        points = pred.predict(project_id, horizons=(1,))
        point_a = next(p for p in points if p.node_id == node_a)
        point_c = next(p for p in points if p.node_id == node_c)

        # coef = [1, 1, -1], x_std(A) = [1, 1, -1] : les 3 contributions valent 1.0
        # (égalité) -> ordre d'origine conservé par le tri stable.
        assert [nom for nom, _ in point_a.drivers] == ["ur_local", "hidden_risk", "rang"]
        assert all(valeur == pytest.approx(1.0) for _, valeur in point_a.drivers)
        assert point_a.delta_vs_last_week == pytest.approx(1.0 - 0.6)

        # C : 4 semaines à valeurs constantes -> delta nul exact.
        assert point_c.delta_vs_last_week == pytest.approx(0.0)

    def test_tri_par_probabilite_decroissante(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _bloquer_forecast_et_actions(monkeypatch)
        project_id, node_a, _node_b, node_c = projet_controle
        pred = PredictionService(service, artifact_path)

        points = pred.predict(project_id, horizons=(1,))

        # A (ur_local=hidden_risk=1.0) domine largement C (valeurs proches de 0).
        assert [p.node_id for p in points] == [node_a, node_c]
        assert points[0].proba_by_horizon[1] > points[1].proba_by_horizon[1]

    def test_imputation_hors_rollout_signalee(
        self,
        service: SupplyScoreService,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _bloquer_forecast_et_actions(monkeypatch)
        project_id, node_a, _node_b, _node_c = projet_controle
        # Artefact demandant une feature que le service n'assemble jamais.
        chemin = tmp_path / "artifact.json"
        chemin.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "feature_names": ["ur_local", "feature_inconnue"],
                    "scaler_mean": [0.5, 0.0],
                    "scaler_std": [0.5, 1.0],
                    "coef": [1.0, 0.0],
                    "intercept": 0.0,
                    "calibrator_x": [0.0, 1.0],
                    "calibrator_y": [0.0, 1.0],
                }
            ),
            encoding="utf-8",
        )
        pred = PredictionService(service, chemin)
        pred.predict(project_id, horizons=(1,))
        avert = " ".join(pred.avertissements)
        assert node_a in avert
        assert "feature_inconnue" in avert
        assert "imputation" in avert.lower()


# --- Rollout injecté : variation multi-horizon -------------------------------------------


@dataclass
class _FakePrevisionNoeud:
    p_issue: float
    se_mc: float
    var_mc: float
    var_param: float
    spread: float
    p_jalon_rate: float
    p_impact_client: float


class _FakeForecastResult:
    def __init__(self, previsions: dict[str, dict[int, _FakePrevisionNoeud]]) -> None:
        self.previsions = previsions


class TestRolloutPresent:
    """ForecastService injecté (module factice) : p_rollout/spread varient par horizon."""

    def test_probabilite_varie_par_horizon_et_incertitudes_transmises(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, node_a, _node_b, node_c = projet_controle
        monkeypatch.setitem(sys.modules, "supplyscore.services.action_engine", None)

        class FakeForecastService:
            def __init__(self, service: object) -> None:
                del service

            def rollout(
                self, project_id: str, horizon_weeks: int, n_draws: int, seed: int
            ) -> _FakeForecastResult:
                del project_id, n_draws, seed
                previsions = {
                    node_a: {
                        h: _FakePrevisionNoeud(
                            p_issue=0.1 * h,
                            se_mc=0.01,
                            var_mc=0.0001,
                            var_param=0.0004,
                            spread=0.2,
                            p_jalon_rate=0.05 * h,
                            p_impact_client=0.02 * h,
                        )
                        for h in range(1, horizon_weeks + 1)
                    }
                }
                return _FakeForecastResult(previsions)

        fake_module = types.ModuleType("supplyscore.services.forecast")
        fake_module.ForecastService = FakeForecastService  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "supplyscore.services.forecast", fake_module)

        pred = PredictionService(service, artifact_path)
        # Bascule l'artefact sur un modèle "p_rollout only" pour isoler l'effet du
        # rollout du reste des features (artifact_v1.json n'utilise pas p_rollout).
        # Accès direct à l'attribut interne : bascule l'artefact chargé sans
        # dépendre d'un second fichier fixture pour isoler l'effet du rollout.
        pred._artifact = _ModelArtifact(
            feature_names=("p_rollout", "spread"),
            scaler_mean=np.array([0.0, 0.0]),
            scaler_std=np.array([1.0, 1.0]),
            coef=np.array([1.0, 0.0]),
            intercept=0.0,
            calibrator_x=np.array([0.0, 1.0]),
            calibrator_y=np.array([0.0, 1.0]),
            coef_boot=None,
        )

        points = pred.predict(project_id, horizons=(1, 2, 3))
        point_a = next(p for p in points if p.node_id == node_a)

        for h in (1, 2, 3):
            assert point_a.proba_by_horizon[h] == pytest.approx(_sigmoid_ref(0.1 * h), abs=1e-9)
            assert point_a.incertitude_mc is not None
            assert point_a.incertitude_mc[h] == pytest.approx(0.01)
            assert point_a.incertitude_param is not None
            assert point_a.incertitude_param[h] == pytest.approx(math.sqrt(0.0004))

        # p_jalon_rate/p_impact_client repris à l'horizon de référence (max = 3).
        assert point_a.p_jalon_rate == pytest.approx(0.05 * 3)
        assert point_a.p_impact_client == pytest.approx(0.02 * 3)
        assert not any("features-only" in a for a in pred.avertissements)

        # C n'a pas de prévision dans le rollout factice (dict vide) -> imputé,
        # mais reste un nœud éligible (historique suffisant) : pas d'exception.
        assert any(p.node_id == node_c for p in points)

    def test_rollout_qui_leve_degrade_en_features_only(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, _node_a, _node_b, _node_c = projet_controle
        monkeypatch.setitem(sys.modules, "supplyscore.services.action_engine", None)

        class BrokenForecastService:
            def __init__(self, service: object) -> None:
                del service

            def rollout(self, *args: object, **kwargs: object) -> None:
                raise ValueError("historique hebdomadaire insuffisant (simulé)")

        fake_module = types.ModuleType("supplyscore.services.forecast")
        fake_module.ForecastService = BrokenForecastService  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "supplyscore.services.forecast", fake_module)

        pred = PredictionService(service, artifact_path)
        pred.predict(project_id, horizons=(1,))
        assert any("features-only" in a and "échec du rollout" in a for a in pred.avertissements)


# --- ActionEngine : lazy import gracieux --------------------------------------------------


class TestActionEngineLazyImport:
    def test_absent_recommandation_none(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _bloquer_forecast_et_actions(monkeypatch)
        project_id, node_a, _node_b, _node_c = projet_controle
        pred = PredictionService(service, artifact_path)
        points = pred.predict(project_id, horizons=(1,))
        point_a = next(p for p in points if p.node_id == node_a)
        assert point_a.recommandation is None

    def test_present_recommandation_transmise(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, node_a, _node_b, _node_c = projet_controle
        monkeypatch.setitem(sys.modules, "supplyscore.services.forecast", None)

        class FakeActionEngine:
            def __init__(self, service: object) -> None:
                del service

            def recommander(
                self, project_id: str, node_id: str, forecast: object, contexte: object
            ) -> list[dict[str, str]]:
                del forecast, contexte
                return [{"action_id": "test", "project_id": project_id, "node_id": node_id}]

        fake_module = types.ModuleType("supplyscore.services.action_engine")
        fake_module.ActionEngine = FakeActionEngine  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "supplyscore.services.action_engine", fake_module)

        pred = PredictionService(service, artifact_path)
        points = pred.predict(project_id, horizons=(1,))
        point_a = next(p for p in points if p.node_id == node_a)
        assert point_a.recommandation == [
            {"action_id": "test", "project_id": project_id, "node_id": node_a}
        ]

    def test_echec_recommandation_none_avec_avertissement(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, node_a, _node_b, _node_c = projet_controle
        monkeypatch.setitem(sys.modules, "supplyscore.services.forecast", None)

        class FailingActionEngine:
            def __init__(self, service: object) -> None:
                del service

            def recommander(self, *args: object, **kwargs: object) -> list[object]:
                raise RuntimeError("panne simulée")

        fake_module = types.ModuleType("supplyscore.services.action_engine")
        fake_module.ActionEngine = FailingActionEngine  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "supplyscore.services.action_engine", fake_module)

        pred = PredictionService(service, artifact_path)
        points = pred.predict(project_id, horizons=(1,))
        point_a = next(p for p in points if p.node_id == node_a)
        assert point_a.recommandation is None
        assert any("recommandation indisponible" in a for a in pred.avertissements)

    def test_construction_echoue_degrade_a_none(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id, node_a, _node_b, _node_c = projet_controle
        monkeypatch.setitem(sys.modules, "supplyscore.services.forecast", None)

        class ExplosiveActionEngine:
            def __init__(self, service: object) -> None:
                del service
                raise RuntimeError("catalogue introuvable")

        fake_module = types.ModuleType("supplyscore.services.action_engine")
        fake_module.ActionEngine = ExplosiveActionEngine  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "supplyscore.services.action_engine", fake_module)

        pred = PredictionService(service, artifact_path)
        points = pred.predict(project_id, horizons=(1,))
        point_a = next(p for p in points if p.node_id == node_a)
        assert point_a.recommandation is None


# --- Cas limites et erreurs ---------------------------------------------------------------


class TestErreursEtCasLimites:
    def test_horizons_vide_leve(self, service: SupplyScoreService, artifact_path: Path) -> None:
        pred = PredictionService(service, artifact_path)
        with pytest.raises(ValueError, match="horizons"):
            pred.predict("p-quelconque", horizons=())

    def test_horizon_sous_un_leve(self, service: SupplyScoreService, artifact_path: Path) -> None:
        pred = PredictionService(service, artifact_path)
        with pytest.raises(ValueError, match="horizons"):
            pred.predict("p-quelconque", horizons=(0, 1))

    def test_projet_inconnu_leve(self, service: SupplyScoreService, artifact_path: Path) -> None:
        pred = PredictionService(service, artifact_path)
        with pytest.raises(ValueError, match="inconnu"):
            pred.predict("fantome")

    def test_aucun_noeud_actif_retourne_liste_vide_avec_avertissement(
        self, service: SupplyScoreService, artifact_path: Path
    ) -> None:
        service.registry.save_project(
            Project(id="p-vide", name="Vide", owner_node_id="n-0", created_at=_NOW, t0_ts=_NOW)
        )
        node = SupplyNode(id="n-0", name="Solo", project_id="p-vide", status=TaskStatus.DONE)
        service.repo.add_node(node)
        pred = PredictionService(service, artifact_path)

        points = pred.predict("p-vide")

        assert points == []
        assert any("aucun nœud actif" in a for a in pred.avertissements)

    def test_horizons_dupliques_dedupliques(
        self,
        service: SupplyScoreService,
        artifact_path: Path,
        projet_controle: tuple[str, str, str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _bloquer_forecast_et_actions(monkeypatch)
        project_id, node_a, _node_b, _node_c = projet_controle
        pred = PredictionService(service, artifact_path)
        points = pred.predict(project_id, horizons=(2, 1, 2, 1))
        point_a = next(p for p in points if p.node_id == node_a)
        assert set(point_a.proba_by_horizon) == {1, 2}


# --- CLI en-process -------------------------------------------------------------------------


class TestCliPredict:
    def test_build_parser_defauts(self) -> None:
        args = build_parser().parse_args(["--project", "p-1"])
        assert args.db_dir == "data_store"
        assert args.model == "models/latest/artifact.json"
        assert args.horizon == 4
        assert args.draws == 2000
        assert args.seed == 0
        assert args.json is False

    def test_main_modele_absent(self, tmp_path: Path) -> None:
        code = main(
            [
                "--project",
                "p-1",
                "--db-dir",
                str(tmp_path / "store"),
                "--model",
                str(tmp_path / "absent.json"),
            ]
        )
        assert code == 1

    def test_main_projet_inconnu(self, tmp_path: Path, artifact_path: Path) -> None:
        db_dir = tmp_path / "store"
        code = main(
            ["--project", "fantome", "--db-dir", str(db_dir), "--model", str(artifact_path)]
        )
        assert code == 1

    def test_main_artefact_invalide(self, tmp_path: Path) -> None:
        mauvais_artefact = tmp_path / "mauvais.json"
        mauvais_artefact.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
        code = main(
            [
                "--project",
                "p-1",
                "--db-dir",
                str(tmp_path / "store"),
                "--model",
                str(mauvais_artefact),
            ]
        )
        assert code == 1

    def test_main_horizon_invalide(self, tmp_path: Path, artifact_path: Path) -> None:
        db_dir = tmp_path / "store"
        svc = SupplyScoreService(db_dir=db_dir)
        svc.registry.save_project(
            Project(id="p-1", name="P", owner_node_id="n-0", created_at=_NOW, t0_ts=_NOW)
        )
        svc.close()
        code = main(
            [
                "--project",
                "p-1",
                "--db-dir",
                str(db_dir),
                "--model",
                str(artifact_path),
                "--horizon",
                "0",
            ]
        )
        assert code == 1


class TestCliPredictAvecProjet:
    @pytest.fixture
    def db_dir_avec_projet(self, tmp_path: Path) -> tuple[Path, str]:
        db_dir = tmp_path / "store"
        svc = SupplyScoreService(db_dir=db_dir, clock=FixedClock(_NOW))
        try:
            project = svc.seed_demo(n_ranks=1, seed=2)
            svc.set_clock_mode(project.id, "game")
            # Un appel PAR semaine (n=3 en un seul appel ne produirait qu'un
            # unique bond de 3 semaines, donc 2 semaines ISO distinctes au
            # total) — même motif que la fixture ``partie`` de
            # tests/test_calibration.py : 4 semaines d'historique au total.
            for _ in range(3):
                svc.advance_week(project.id)
        finally:
            svc.close()
        return db_dir, project.id

    def test_tableau_humain_rendu(
        self,
        db_dir_avec_projet: tuple[Path, str],
        artifact_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_dir, project_id = db_dir_avec_projet
        code = main(
            ["--project", project_id, "--db-dir", str(db_dir), "--model", str(artifact_path)]
        )
        assert code == 0
        sortie = capsys.readouterr().out
        assert "Nœud" in sortie
        assert "P<=1sem" in sortie
        assert "P<=4sem" in sortie

    def test_json_valide_cle_par_horizon(
        self,
        db_dir_avec_projet: tuple[Path, str],
        artifact_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_dir, project_id = db_dir_avec_projet
        code = main(
            [
                "--project",
                project_id,
                "--db-dir",
                str(db_dir),
                "--model",
                str(artifact_path),
                "--json",
                "--horizon",
                "2",
            ]
        )
        assert code == 0
        donnees = json.loads(capsys.readouterr().out)
        assert isinstance(donnees, list)
        if donnees:
            assert set(donnees[0]["proba_by_horizon"].keys()) == {"1", "2"}
            assert "node_id" in donnees[0]
            assert "drivers" in donnees[0]
