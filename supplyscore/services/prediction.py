"""Prevision produit par noeud - score un artefact numpy fige (HELIOS v7, U11).

:class:`PredictionService` est le point de sortie " produit " de la chaine de
prevision : il charge un artefact de modele (contrat 5 fige - regression
logistique standardisee + calibrateur isotonique, entrainee hors-ligne par
l'unite U10), assemble pour chaque noeud ACTIF d'un projet un vecteur de
features a partir des API EXISTANTES du depot (historique d'urgence
hebdomadaire, decomposition ``explain_ur_local``, criticite systematique,
structure du graphe, rollout de prevision U9), puis score ce vecteur en pur
numpy pour produire une :class:`PredictionPoint` par noeud et par horizon.

Scoring (contrat 5 fige, identique pour chaque horizon) ::

    x_std = (x - scaler_mean) / scaler_std          (std == 0 -> diviseur 1)
    z     = coef - x_std + intercept
    p_raw = sigmoid(z)
    p     = interp(p_raw, calibrator_x, calibrator_y)
    IC80  = 10e/90e percentiles de p sur les lignes de coef_boot (si present)

Assemblage des features (un vecteur PAR noeud, PAR horizon - seuls
``p_rollout`` et ``spread`` varient selon l'horizon, tout le reste est fige
" a l'instant present ") :

- historique hebdomadaire (2 dernieres semaines ISO, dernier etat de chaque
  semaine - meme regroupement que :meth:`~supplyscore.services.calibration.\
CalibrationService.outcomes`) : ``ur_local``, ``ud_local``, ``hidden_risk``,
  ``false_urgency`` (semaine courante) et ``delta_ur_local_semaine``,
  ``delta_hidden_risk_semaine`` (tendance sur les deux semaines) ;
- blocs KPI (:func:`~supplyscore.core.explain.explain_ur_local`) : ``u_time``,
  ``u_cap``, ``u_perf``, ``u_risk``, ``u_cost``, ``u_co2`` ;
- criticite systematique (:class:`~supplyscore.services.criticite.\
ServiceCriticite`, calculee UNE fois par projet) : ``delta_ur_final``,
  ``nb_impactes``, ``delta_ell_final`` (via ``getattr`` - champ optionnel non
  encore pose par tous les depots) ;
- structure du graphe (registre/depot) : ``rang``, ``rang_max``,
  ``degre_entrant``, ``degre_sortant``, ``n_noeuds_projet`` ;
- rollout de prevision (:class:`~supplyscore.services.forecast.\
ForecastService`, LAZY - peut etre absent) : ``p_rollout``, ``spread``, PAR
  horizon.

REGLE UNIQUE ET SIMPLE pour toute donnee manquante : une feature n'est ajoutee
au dictionnaire assemble QUE si sa source vaut une valeur numerique reelle
(jamais None, jamais fabriquee) ; toute feature du ``feature_names`` de
l'artefact absente de ce dictionnaire - qu'elle n'ait pas pu etre calculee
pour CE noeud (bloc inactif, criticite indisponible...) ou que l'artefact
demande un nom que ce service ne sait pas assembler - est imputee a
``scaler_mean`` et signalee (contrat 5 fige). C'est le MEME mecanisme, sans
distinction de cause, qui degrade le service en mode " features-only " quand
:class:`ForecastService` est absent ou echoue : ``p_rollout``/``spread`` ne
sont alors jamais ajoutes, donc systematiquement imputes a la meme valeur
pour tous les horizons - d'ou une probabilite identique sur tous les
horizons dans ce mode (caveat documente, jamais silencieux : un avertissement
dedie est ajoute a :attr:`PredictionService.avertissements`).

AVERTISSEMENTS (jamais d'exception pour un simple degre de degradation) :
:meth:`PredictionService.predict` reinitialise puis alimente
:attr:`PredictionService.avertissements` (liste de phrases francaises) pour
trois cas non silencieux : noeud exclu pour historique hebdomadaire
insuffisant (:data:`MIN_HISTORY_WEEKS`), mode features-only declenche, et
imputation de feature(s) sur un noeud inclus (hors ``p_rollout``/``spread``,
deja couverts par l'avertissement de mode). Le CLI (``tools/predict.py``) les
affiche apres le tableau.

Conventions d'horizon unique : les champs NON indexes par horizon
(``drivers``, ``p_jalon_rate``, ``p_impact_client``) sont calcules a
l'horizon le plus long demande (``max(horizons)``) - la vision " sur toute la
fenetre de prevision ". ``delta_vs_last_week`` n'est PAS un delta de
probabilite modele : c'est le delta brut ``ur_local(S) - ur_local(S-1)``
observe entre les deux dernieres semaines ISO du noeud (tendance d'ENTREE, pas
de sortie modele) - None si l'une des deux valeurs manque.

Service en LECTURE SEULE : aucune ecriture, jamais.
"""

from __future__ import annotations

import importlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from supplyscore.core.clock import iso_week, project_hours
from supplyscore.core.explain import explain_ur_local
from supplyscore.domain.models import SupplyNode, TaskStatus, UrgencyState
from supplyscore.services.criticite import PointCriticite, ServiceCriticite
from supplyscore.services.weekly import _lundi

if TYPE_CHECKING:
    from supplyscore.services.orchestrator import SupplyScoreService

_FloatArray = NDArray[np.float64]

#: Nombre minimal de semaines ISO d'historique d'urgence exige par noeud (meme seuil que :data:`supplyscore.services.forecast.MIN_HISTORY_WEEKS` - duplique ici pour ne JAMAIS dependre d'un import du module frere absent).
MIN_HISTORY_WEEKS: int = 4

#: Version de schema supportee de l'artefact (contrat 5 fige).
_SCHEMA_VERSION: int = 1

#: Percentiles bilateraux de l'IC80 (10e / 90e) sur les lignes de coef_boot.
_PERCENTILES_IC80: tuple[float, float] = (10.0, 90.0)

#: Nombre de features conservees dans les " drivers " (contrat 6 fige).
_N_DRIVERS: int = 3

#: Noms de features horizon-dependantes - jamais comptes dans l'avertissement d'imputation par noeud (deja couverts par l'avertissement de mode global).
_FEATURES_ROLLOUT: frozenset[str] = frozenset({"p_rollout", "spread"})


# Artefact de modele (contrat 5 fige)


@dataclass(eq=False)
class _ModelArtifact:
    """Artefact de modele valide, tableaux numpy prets pour le scoring.

    Attributes:
        feature_names: noms des features, dans l'ordre du vecteur ``x``.
        scaler_mean: moyennes de standardisation (meme ordre).
        scaler_std: ecarts-types de standardisation (0 -> diviseur 1 au scoring).
        coef: coefficients de la regression logistique (meme ordre).
        intercept: ordonnee a l'origine de la regression logistique.
        calibrator_x: abscisses du calibrateur isotonique (strictement croissantes).
        calibrator_y: ordonnees calibrees correspondantes.
        coef_boot: lignes de coefficients bootstrap (IC80), ou None si absent.
    """

    feature_names: tuple[str, ...]
    scaler_mean: _FloatArray
    scaler_std: _FloatArray
    coef: _FloatArray
    intercept: float
    calibrator_x: _FloatArray
    calibrator_y: _FloatArray
    coef_boot: _FloatArray | None


def _tableau_1d(brut: dict[str, Any], cle: str, longueur: int) -> _FloatArray:
    """Lit et valide un tableau JSON 1D de longueur fixe (nombres uniquement).

    Args:
        brut: dictionnaire JSON de l'artefact.
        cle: nom du champ a lire.
        longueur: longueur exacte attendue.

    Returns:
        Le tableau numpy ``float64`` de longueur ``longueur``.

    Raises:
        ValueError: champ absent, pas une liste, mauvaise longueur ou valeur
            non numerique (message en francais).
    """
    valeurs = brut.get(cle)
    if not isinstance(valeurs, list) or len(valeurs) != longueur:
        raise ValueError(
            f"Artefact de modèle invalide : « {cle} » doit être une liste de {longueur} nombre(s)."
        )
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in valeurs):
        raise ValueError(
            f"Artefact de modèle invalide : « {cle} » doit contenir uniquement des nombres."
        )
    return np.asarray(valeurs, dtype=np.float64)


def _charger_artifact(chemin: str | Path) -> _ModelArtifact:
    """Charge et valide l'artefact JSON du modele (contrat 5 fige).

    Args:
        chemin: chemin du fichier JSON de l'artefact.

    Returns:
        L'artefact valide (tableaux numpy prets pour le scoring).

    Raises:
        ValueError: fichier illisible, JSON invalide, schema non supporte ou
            tailles de tableaux incoherentes (message en francais dans tous
            les cas - seule exception levee par cette fonction).
    """
    chemin = Path(chemin)
    try:
        texte = chemin.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Artefact de modèle illisible : {chemin} ({exc}).") from exc
    try:
        brut = json.loads(texte)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Artefact de modèle : JSON invalide dans {chemin} ({exc}).") from exc
    if not isinstance(brut, dict):
        raise ValueError(f"Artefact de modèle invalide : objet JSON attendu ({chemin}).")

    version = brut.get("schema_version")
    if version != _SCHEMA_VERSION:
        raise ValueError(
            f"Version de schéma d'artefact non supportée : {version!r} (attendu {_SCHEMA_VERSION})."
        )

    feature_names_brut = brut.get("feature_names")
    if not isinstance(feature_names_brut, list) or not feature_names_brut:
        raise ValueError(
            "Artefact de modèle invalide : « feature_names » doit être une liste non vide."
        )
    if not all(isinstance(nom, str) and nom for nom in feature_names_brut):
        raise ValueError(
            "Artefact de modèle invalide : « feature_names » doit contenir des chaînes non vides."
        )
    feature_names = tuple(feature_names_brut)
    n_features = len(feature_names)

    scaler_mean = _tableau_1d(brut, "scaler_mean", n_features)
    scaler_std = _tableau_1d(brut, "scaler_std", n_features)
    coef = _tableau_1d(brut, "coef", n_features)

    intercept_brut = brut.get("intercept")
    if not isinstance(intercept_brut, (int, float)) or isinstance(intercept_brut, bool):
        raise ValueError("Artefact de modèle invalide : « intercept » doit être un nombre.")
    intercept = float(intercept_brut)

    calibrator_x_brut = brut.get("calibrator_x")
    calibrator_y_brut = brut.get("calibrator_y")
    if (
        not isinstance(calibrator_x_brut, list)
        or not isinstance(calibrator_y_brut, list)
        or len(calibrator_x_brut) < 2
        or len(calibrator_x_brut) != len(calibrator_y_brut)
    ):
        raise ValueError(
            "Artefact de modèle invalide : « calibrator_x »/« calibrator_y » doivent être deux"
            " listes non vides de même longueur (2 points minimum)."
        )
    calibrator_x = _tableau_1d(brut, "calibrator_x", len(calibrator_x_brut))
    calibrator_y = _tableau_1d(brut, "calibrator_y", len(calibrator_y_brut))
    if bool(np.any(np.diff(calibrator_x) <= 0)):
        raise ValueError(
            "Artefact de modèle invalide : « calibrator_x » doit être strictement croissant."
        )

    coef_boot: _FloatArray | None = None
    coef_boot_brut = brut.get("coef_boot")
    if coef_boot_brut is not None:
        if not isinstance(coef_boot_brut, list) or not coef_boot_brut:
            raise ValueError(
                "Artefact de modèle invalide : « coef_boot », si présent,"
                " doit être une liste non vide."
            )
        if not all(
            isinstance(ligne, list) and len(ligne) == n_features for ligne in coef_boot_brut
        ):
            raise ValueError(
                f"Artefact de modèle invalide : chaque ligne de « coef_boot » doit compter"
                f" {n_features} coefficient(s)."
            )
        lignes = [_tableau_1d({"ligne": ligne}, "ligne", n_features) for ligne in coef_boot_brut]
        coef_boot = np.stack(lignes)

    return _ModelArtifact(
        feature_names=feature_names,
        scaler_mean=scaler_mean,
        scaler_std=scaler_std,
        coef=coef,
        intercept=intercept,
        calibrator_x=calibrator_x,
        calibrator_y=calibrator_y,
        coef_boot=coef_boot,
    )


# Scoring numpy pur (contrat 5 fige)


def _sigmoid(z: _FloatArray) -> _FloatArray:
    """Sigmoide numeriquement stable, vectorisee.

    Args:
        z: tableau de logits.

    Returns:
        ``1 / (1 + exp(-z))``, sans depassement de capacite flottante.
    """
    return np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)), np.exp(z) / (1.0 + np.exp(z)))


def _construire_vecteur(
    artifact: _ModelArtifact, features: dict[str, float]
) -> tuple[_FloatArray, list[str]]:
    """Construit le vecteur brut ``x`` dans l'ordre de l'artefact, impute les absences.

    Args:
        artifact: artefact de modele valide.
        features: features assemblees pour le noeud/horizon (nom -> valeur reelle).

    Returns:
        ``(x, features_imputees)`` - le vecteur brut (avant standardisation)
        et les noms de features imputees a ``scaler_mean`` (absentes de
        ``features``, quelle qu'en soit la cause).
    """
    x = np.empty(len(artifact.feature_names), dtype=np.float64)
    imputees: list[str] = []
    for i, nom in enumerate(artifact.feature_names):
        valeur = features.get(nom)
        if valeur is None:
            x[i] = artifact.scaler_mean[i]
            imputees.append(nom)
        else:
            x[i] = valeur
    return x, imputees


def _standardiser(artifact: _ModelArtifact, x: _FloatArray) -> _FloatArray:
    """Standardise ``x`` selon l'artefact (ecart-type nul -> diviseur 1).

    Args:
        artifact: artefact de modele valide.
        x: vecteur brut (contrat 5 : memes unites que ``scaler_mean``).

    Returns:
        ``(x - scaler_mean) / scaler_std`` avec diviseur 1 ou ``scaler_std == 0``.
    """
    diviseur = np.where(artifact.scaler_std == 0.0, 1.0, artifact.scaler_std)
    return (x - artifact.scaler_mean) / diviseur


def _score(
    artifact: _ModelArtifact, x_std: _FloatArray
) -> tuple[float, tuple[float, float] | None]:
    """Score un vecteur standardise : probabilite calibree et IC80 optionnel.

    Args:
        artifact: artefact de modele valide.
        x_std: vecteur standardise (cf. :func:`_standardiser`).

    Returns:
        ``(p, ic80)`` - probabilite calibree ``p = interp(sigmoid(coef-x_std +
        intercept), calibrator_x, calibrator_y)`` et IC80 ``(10e, 90e)``
        percentiles de ``p`` sur les lignes de ``coef_boot`` quand present,
        sinon None.
    """
    z = float(np.dot(artifact.coef, x_std) + artifact.intercept)
    p_raw = float(_sigmoid(np.asarray(z, dtype=np.float64)))
    p = float(np.interp(p_raw, artifact.calibrator_x, artifact.calibrator_y))

    if artifact.coef_boot is None:
        return p, None
    z_boot = artifact.coef_boot @ x_std + artifact.intercept
    p_raw_boot = _sigmoid(z_boot)
    p_boot = np.interp(p_raw_boot, artifact.calibrator_x, artifact.calibrator_y)
    lo, hi = np.percentile(p_boot, _PERCENTILES_IC80)
    return p, (float(lo), float(hi))


# Sortie figee (contrat 6)


@dataclass(frozen=True)
class PredictionPoint:
    """Prevision d'un noeud, tous horizons demandes (contrat 6 fige - consomme par U12).

    Attributes:
        node_id: identifiant du noeud prevu.
        node_name: nom lisible du noeud.
        proba_by_horizon: probabilite calibree d'issue defavorable par horizon
            (semaines), meme definition que :class:`~supplyscore.services.\
calibration.CalibrationService` (jalon rate OU evenement critique/defaut).
        ic80_by_horizon: IC80 ``(bas, haut)`` par horizon (percentiles 10/90
            de la probabilite sur les lignes ``coef_boot``), None si
            l'artefact n'embarque pas de bootstrap.
        incertitude_mc: erreur-type Monte Carlo du rollout par horizon
            (:attr:`~supplyscore.services.forecast.PrevisionNoeud.se_mc`),
            None si le rollout est indisponible (mode features-only).
        incertitude_param: ecart-type de la composante parametrique du
            rollout par horizon (racine de ``var_param``), None si le rollout
            est indisponible.
        delta_vs_last_week: Deltaur_local BRUT observe entre les deux dernieres
            semaines ISO du noeud (``ur_local(S) - ur_local(S-1)``) - PAS une
            difference de probabilite modele ; None si l'une des deux valeurs
            manque.
        p_jalon_rate: probabilite que le prochain jalon soit rate, reprise du
            rollout a l'horizon le plus long demande ; None si indisponible.
        p_impact_client: probabilite d'impact client significatif (DeltaUr au
            rang 0 > seuil), reprise du rollout au meme horizon ; None si
            indisponible.
        drivers: 3 features dominantes a l'horizon le plus long, par
            contribution SIGNEE ``coef_i - x_std_i`` decroissante en valeur
            absolue - ``[(nom, contribution), ...]``.
        impact_frac: fraction des noeuds du projet impactes par le pire choc
            local de CE noeud (``nb_impactes / n_noeuds_projet``,
            :class:`~supplyscore.services.criticite.ServiceCriticite`), None
            si la criticite est indisponible.
        delta_ell_final: DeltaEchelle-log finale du pire choc local, si le depot
            expose ce champ (extension optionnelle de
            :class:`~supplyscore.services.criticite.PointCriticite`), None sinon.
        recommandation: recommandations d'action de
            :class:`~supplyscore.services.action_engine.ActionEngine`
            (``list[ActionRecommandation]``, contrat 11), ou None si le
            moteur est indisponible ou a echoue pour ce noeud.
    """

    node_id: str
    node_name: str
    proba_by_horizon: dict[int, float]
    ic80_by_horizon: dict[int, tuple[float, float] | None]
    incertitude_mc: dict[int, float] | None
    incertitude_param: dict[int, float] | None
    delta_vs_last_week: float | None
    p_jalon_rate: float | None
    p_impact_client: float | None
    drivers: list[tuple[str, float]]
    impact_frac: float | None
    delta_ell_final: float | None
    recommandation: object | None


# Service


class PredictionService:
    """Prevision produit : score l'artefact de modele pour les noeuds d'un projet.

    S'appuie sur la facade :class:`~supplyscore.services.orchestrator.\
SupplyScoreService` (registre, depot de graphe, bases client) et sur les
    services EXISTANTS :class:`~supplyscore.services.criticite.ServiceCriticite`
    (criticite systematique). Les dependances du plan v7 -
    :class:`~supplyscore.services.forecast.ForecastService` et
    :class:`~supplyscore.services.action_engine.ActionEngine` - sont importees
    PARESSEUSEMENT et degradees proprement si absentes ou en echec : ce
    service ne plante JAMAIS pour leur absence, il le SIGNALE (cf.
    :attr:`avertissements`). Service en LECTURE SEULE : aucune ecriture.
    """

    def __init__(self, service: SupplyScoreService, artifact_path: str | Path) -> None:
        """Charge et valide l'artefact de modele au-dessus de la facade applicative.

        Args:
            service: facade applicative (registre, depot de graphe, bases client).
            artifact_path: chemin du fichier JSON de l'artefact (contrat 5 fige).

        Raises:
            ValueError: artefact illisible, JSON invalide ou schema incoherent
                (message en francais).
        """
        self._service = service
        self._artifact = _charger_artifact(artifact_path)
        #: Avertissements francais du DERNIER appel a :meth:`predict` (jamais d'exception pour une simple degradation) : noeuds exclus pour historique insuffisant, mode features-only, features imputees.
        self.avertissements: list[str] = []

    # API publique

    def predict(
        self,
        project_id: str,
        horizons: tuple[int, ...] = (1, 2, 3, 4),
        n_draws: int = 2000,
        seed: int = 0,
    ) -> list[PredictionPoint]:
        """Prevoit chaque noeud ACTIF du projet sur les horizons demandes.

        Etapes : (1) resout les noeuds actifs (statut ACTIVE, onboarding
        termine) ; (2) calcule la criticite systematique UNE fois pour le
        projet ; (3) tente un rollout :class:`ForecastService` UNE fois pour
        l'horizon le plus long (couvre tous les horizons demandes), degrade
        en mode features-only s'il est indisponible ; (4) par noeud passant le
        seuil :data:`MIN_HISTORY_WEEKS`, assemble les features et score
        l'artefact a chaque horizon ; (5) joint la recommandation
        :class:`ActionEngine` si disponible. Les noeuds exclus et les
        degradations sont consignes dans :attr:`avertissements` (jamais
        d'exception pour ces cas).

        Args:
            project_id: projet a prevoir.
            horizons: horizons en semaines (dedupliques, tries ; defaut 1-4).
            n_draws: budget de trajectoires du rollout U9 (defaut 2000).
            seed: graine du rollout U9 - deterministe (defaut 0).

        Returns:
            Une :class:`PredictionPoint` par noeud eligible, triees par
            probabilite decroissante a l'horizon le plus long (puis par nom).
            Liste vide si le projet n'a aucun noeud actif ou qu'aucun noeud
            n'atteint :data:`MIN_HISTORY_WEEKS` (avertissement dans les deux cas).

        Raises:
            ValueError: horizons vide ou contenant un entier < 1, ou projet
                inconnu du registre (message en francais).
        """
        if not horizons:
            raise ValueError("horizons ne peut pas être vide.")
        horizons_triees = tuple(sorted({int(h) for h in horizons}))
        if horizons_triees[0] < 1:
            raise ValueError(f"horizons doit contenir des entiers >= 1, reçu {horizons}.")
        horizon_ref = horizons_triees[-1]

        self.avertissements = []
        service = self._service
        if service.registry.get_project(project_id) is None:
            raise ValueError(f"Projet inconnu : {project_id!r}.")

        tous_noeuds = service.repo.nodes_by_project(project_id)
        actifs = [
            n
            for n in tous_noeuds
            if n.status == TaskStatus.ACTIVE and n.onboarding_state != "draft"
        ]
        if not actifs:
            self.avertissements.append(
                f"Projet {project_id!r} : aucun nœud actif (onboarding terminé) —"
                " aucune prévision produite."
            )
            return []

        rang_max = max((n.rank for n in tous_noeuds), default=0)
        n_noeuds_projet = len(tous_noeuds)

        criticite_par_noeud: dict[str, PointCriticite] = {}
        try:
            criticite_par_noeud = {
                p.node_id: p for p in ServiceCriticite(service).indice_criticite(project_id)
            }
        except ValueError as exc:
            self.avertissements.append(f"Analyse de criticité indisponible : {exc}")

        forecast_result, raison_absence = self._rollout(project_id, horizon_ref, n_draws, seed)
        if forecast_result is None:
            self.avertissements.append(
                "Mode features-only : ForecastService indisponible"
                f" ({raison_absence}) — p_rollout/spread imputés (moyenne du scaler),"
                " probabilité identique sur tous les horizons."
            )

        action_engine = self._charger_action_engine()

        points: list[PredictionPoint] = []
        for node in sorted(actifs, key=lambda n: n.id):
            point = self._predire_noeud(
                node,
                project_id=project_id,
                horizons=horizons_triees,
                horizon_ref=horizon_ref,
                criticite_par_noeud=criticite_par_noeud,
                rang_max=rang_max,
                n_noeuds_projet=n_noeuds_projet,
                forecast_result=forecast_result,
                action_engine=action_engine,
            )
            if point is not None:
                points.append(point)

        points.sort(key=lambda p: (-p.proba_by_horizon[horizon_ref], p.node_name))
        return points

    # Assemblage + scoring d'un noeud

    def _predire_noeud(
        self,
        node: SupplyNode,
        *,
        project_id: str,
        horizons: tuple[int, ...],
        horizon_ref: int,
        criticite_par_noeud: dict[str, PointCriticite],
        rang_max: int,
        n_noeuds_projet: int,
        forecast_result: Any,
        action_engine: Any,
    ) -> PredictionPoint | None:
        """Assemble les features et score l'artefact pour un noeud, tous horizons.

        Args:
            node: noeud actif a prevoir.
            project_id: projet du noeud.
            horizons: horizons tries, dedupliques (>= 1).
            horizon_ref: horizon de reference (``max(horizons)``) pour les
                champs non indexes par horizon.
            criticite_par_noeud: criticite pre-calculee du projet, par noeud.
            rang_max: rang maximal observe sur le projet.
            n_noeuds_projet: nombre total de noeuds du projet (tous statuts).
            forecast_result: resultat de rollout U9 (``ForecastResult``
                duck-type) ou None (mode features-only).
            action_engine: moteur de recommandation U18 (``ActionEngine``
                duck-type) ou None.

        Returns:
            La :class:`PredictionPoint` du noeud, ou None si son historique
            hebdomadaire est sous :data:`MIN_HISTORY_WEEKS` (noeud exclu, un
            avertissement est ajoute a :attr:`avertissements`).
        """
        semaines, etats = self._serie_hebdomadaire(node.id)
        if len(semaines) < MIN_HISTORY_WEEKS:
            self.avertissements.append(
                f"Nœud {node.name!r} ({node.id}) exclu : historique hebdomadaire"
                f" insuffisant ({len(semaines)} semaine(s) < {MIN_HISTORY_WEEKS})."
            )
            return None

        etat_dernier = etats[semaines[-1]]
        etat_precedent = etats[semaines[-2]]
        base = self._features_base(
            node,
            etat_dernier=etat_dernier,
            etat_precedent=etat_precedent,
            criticite_par_noeud=criticite_par_noeud,
            rang_max=rang_max,
            n_noeuds_projet=n_noeuds_projet,
        )

        proba_by_horizon: dict[int, float] = {}
        ic80_by_horizon: dict[int, tuple[float, float] | None] = {}
        incertitude_mc: dict[int, float] = {}
        incertitude_param: dict[int, float] = {}
        imputees_hors_rollout: set[str] = set()
        drivers_ref: list[tuple[str, float]] = []
        p_jalon_rate: float | None = None
        p_impact_client: float | None = None

        for h in horizons:
            features = dict(base)
            prevision_h = self._prevision_horizon(forecast_result, node.id, h)
            if prevision_h is not None:
                features["p_rollout"] = float(prevision_h.p_issue)
                features["spread"] = float(prevision_h.spread)
                incertitude_mc[h] = float(prevision_h.se_mc)
                incertitude_param[h] = math.sqrt(max(float(prevision_h.var_param), 0.0))

            x, imputees = _construire_vecteur(self._artifact, features)
            x_std = _standardiser(self._artifact, x)
            p, ic80 = _score(self._artifact, x_std)
            proba_by_horizon[h] = p
            ic80_by_horizon[h] = ic80
            imputees_hors_rollout.update(nom for nom in imputees if nom not in _FEATURES_ROLLOUT)

            if h == horizon_ref:
                contributions = self._artifact.coef * x_std
                drivers_ref = self._top_drivers(self._artifact.feature_names, contributions)
                if prevision_h is not None:
                    p_jalon_rate = float(prevision_h.p_jalon_rate)
                    p_impact_client = float(prevision_h.p_impact_client)

        if imputees_hors_rollout:
            self.avertissements.append(
                f"Nœud {node.name!r} ({node.id}) : imputation de la moyenne du scaler pour"
                f" {', '.join(sorted(imputees_hors_rollout))}."
            )

        point_crit = criticite_par_noeud.get(node.id)
        impact_frac = None
        delta_ell_final = None
        if point_crit is not None:
            impact_frac = point_crit.nb_impactes / n_noeuds_projet if n_noeuds_projet else None
            delta_ell_final = getattr(point_crit, "delta_ell_final", None)

        return PredictionPoint(
            node_id=node.id,
            node_name=node.name,
            proba_by_horizon=proba_by_horizon,
            ic80_by_horizon=ic80_by_horizon,
            incertitude_mc=incertitude_mc or None,
            incertitude_param=incertitude_param or None,
            delta_vs_last_week=self._delta_ur_local(etat_dernier, etat_precedent),
            p_jalon_rate=p_jalon_rate,
            p_impact_client=p_impact_client,
            drivers=drivers_ref,
            impact_frac=impact_frac,
            delta_ell_final=delta_ell_final,
            recommandation=self._recommander(action_engine, project_id, node.id),
        )

    @staticmethod
    def _top_drivers(
        feature_names: tuple[str, ...], contributions: _FloatArray
    ) -> list[tuple[str, float]]:
        """Les :data:`_N_DRIVERS` features dominantes par contribution absolue.

        Args:
            feature_names: noms des features, dans l'ordre de ``contributions``.
            contributions: contribution signee ``coef_i - x_std_i`` par feature.

        Returns:
            ``[(nom, contribution_signee), ...]``, tries par ``|contribution|``
            decroissante (egalite departagee par l'ordre d'origine).
        """
        ordre = sorted(range(len(contributions)), key=lambda i: -abs(float(contributions[i])))
        return [(feature_names[i], float(contributions[i])) for i in ordre[:_N_DRIVERS]]

    @staticmethod
    def _delta_ur_local(dernier: UrgencyState, precedent: UrgencyState) -> float | None:
        """Delta BRUT ``ur_local(S) - ur_local(S-1)`` entre deux etats hebdomadaires.

        Args:
            dernier: dernier etat persiste de la semaine ISO la plus recente.
            precedent: dernier etat persiste de la semaine ISO precedente.

        Returns:
            Le delta, ou None si l'une des deux valeurs de ``ur_local`` manque.
        """
        if dernier.ur_local is None or precedent.ur_local is None:
            return None
        return dernier.ur_local - precedent.ur_local

    # Assemblage des features horizon-invariantes

    def _features_base(
        self,
        node: SupplyNode,
        *,
        etat_dernier: UrgencyState,
        etat_precedent: UrgencyState,
        criticite_par_noeud: dict[str, PointCriticite],
        rang_max: int,
        n_noeuds_projet: int,
    ) -> dict[str, float]:
        """Features horizon-invariantes d'un noeud (tout sauf ``p_rollout``/``spread``).

        Une cle n'est ajoutee QUE si sa source vaut une valeur numerique
        reelle (jamais None fabrique) - cf. regle unique documentee en tete
        de module : toute feature absente d'ici est imputee par
        :func:`_construire_vecteur`, quelle qu'en soit la cause.

        Args:
            node: noeud actif du projet.
            etat_dernier: dernier etat hebdomadaire (semaine la plus recente).
            etat_precedent: dernier etat hebdomadaire (semaine precedente).
            criticite_par_noeud: criticite pre-calculee du projet, par noeud.
            rang_max: rang maximal observe sur le projet.
            n_noeuds_projet: nombre total de noeuds du projet (tous statuts).

        Returns:
            Le dictionnaire ``{nom_feature: valeur}`` assemble.
        """
        features: dict[str, float] = {}

        for nom, valeur in (
            ("ur_local", etat_dernier.ur_local),
            ("ud_local", etat_dernier.ud_local),
            ("hidden_risk", etat_dernier.hidden_risk),
            ("false_urgency", etat_dernier.false_urgency),
        ):
            if valeur is not None:
                features[nom] = float(valeur)
        if etat_dernier.ur_local is not None and etat_precedent.ur_local is not None:
            features["delta_ur_local_semaine"] = etat_dernier.ur_local - etat_precedent.ur_local
        if etat_dernier.hidden_risk is not None and etat_precedent.hidden_risk is not None:
            features["delta_hidden_risk_semaine"] = (
                etat_dernier.hidden_risk - etat_precedent.hidden_risk
            )

        t_h, t0 = self._project_time(node)
        milestones = self._service.registry.list_milestones(node.id)
        blocs = explain_ur_local(t_h, node.kpis, milestones, self._service.ur_model, t0_ts=t0)
        for bloc in blocs:
            if bloc.u is not None:
                features[f"u_{bloc.block}"] = float(bloc.u)

        point_crit = criticite_par_noeud.get(node.id)
        if point_crit is not None:
            features["delta_ur_final"] = float(point_crit.delta_ur_final)
            features["nb_impactes"] = float(point_crit.nb_impactes)
            delta_ell = getattr(point_crit, "delta_ell_final", None)
            if delta_ell is not None:
                features["delta_ell_final"] = float(delta_ell)

        features["rang"] = float(node.rank)
        features["rang_max"] = float(rang_max)
        features["degre_entrant"] = float(len(self._service.repo.predecessors(node.id)))
        features["degre_sortant"] = float(len(self._service.repo.successors(node.id)))
        features["n_noeuds_projet"] = float(n_noeuds_projet)

        return features

    def _project_time(self, node: SupplyNode) -> tuple[float, float]:
        """Contexte temporel du noeud : ``(t_heures, t0_ts)`` de SON projet.

        Memes regles que :meth:`~supplyscore.services.explain.ExplainService.\
_project_time` : l'horloge effective du projet (reelle ou de jeu) donne
        " maintenant ", l'origine du projet donne t0. Sans projet rattache (ou
        projet inconnu du registre), le referentiel degenere en ``(0.0, 0.0)``.

        Args:
            node: noeud dont on calcule le contexte temporel.

        Returns:
            ``(t en heures depuis t0, t0 en secondes epoch)``.
        """
        if not node.project_id:
            return 0.0, 0.0
        project = self._service.registry.get_project(node.project_id)
        if project is None:
            return 0.0, 0.0
        origin = project.origin_ts
        now = self._service.clock_for(project.id).now()
        return project_hours(now, origin), origin

    def _serie_hebdomadaire(self, node_id: str) -> tuple[list[str], dict[str, UrgencyState]]:
        """Historique hebdomadaire du noeud : dernier etat persiste par semaine ISO.

        Meme regroupement que :meth:`~supplyscore.services.calibration.\
CalibrationService.outcomes` : serie croissante par timestamp, le dernier
        etat de chaque semaine ecrase les precedents - AUCUN filtrage sur la
        completude des champs a ce stade (seul le NOMBRE de semaines distinctes
        compte pour :data:`MIN_HISTORY_WEEKS` ; les champs manquants au sein
        d'une semaine retenue sont geres par l'imputation de features).

        Args:
            node_id: identifiant du noeud.

        Returns:
            ``(semaines, derniers)`` - semaines ISO triees chronologiquement
            et dictionnaire ``{semaine: dernier UrgencyState}``.
        """
        derniers: dict[str, UrgencyState] = {}
        for state in self._service.client_db(node_id).urgency_series(node_id):
            derniers[iso_week(state.timestamp)] = state
        semaines = sorted(derniers, key=_lundi)
        return semaines, derniers

    # Dependances optionnelles (imports paresseux, degradation gracieuse)

    def _rollout(
        self, project_id: str, horizon_weeks: int, n_draws: int, seed: int
    ) -> tuple[Any, str]:
        """Tente un rollout :class:`ForecastService` (U9), degrade proprement.

        Args:
            project_id: projet a projeter.
            horizon_weeks: horizon le plus long demande (couvre les horizons
                plus courts, le rollout renvoyant 1..horizon_weeks).
            n_draws: budget de trajectoires.
            seed: graine du rollout.

        Returns:
            ``(resultat, raison_absence)`` - le ``ForecastResult`` duck-type
            et chaine vide en cas de succes, ou ``(None, raison en francais)``
            si le module est absent ou si le rollout echoue (projet sans
            historique suffisant, etc. - jamais une exception propagee).
        """
        try:
            module = importlib.import_module("supplyscore.services.forecast")
        except ImportError as exc:
            return None, f"module indisponible ({exc})"
        try:
            resultat = module.ForecastService(self._service).rollout(
                project_id, horizon_weeks=horizon_weeks, n_draws=n_draws, seed=seed
            )
        except Exception as exc:  # degradation volontaire d'une dependance optionnelle
            return None, f"échec du rollout ({exc})"
        return resultat, ""

    @staticmethod
    def _prevision_horizon(forecast_result: Any, node_id: str, horizon: int) -> Any:
        """Lit la prevision d'un noeud a un horizon dans un ``ForecastResult`` duck-type.

        Args:
            forecast_result: resultat de rollout (objet exposant
                ``.previsions: dict[str, dict[int, PrevisionNoeud]]``), ou None.
            node_id: identifiant du noeud.
            horizon: horizon en semaines.

        Returns:
            La ``PrevisionNoeud`` duck-typee, ou None si indisponible.
        """
        if forecast_result is None:
            return None
        previsions = getattr(forecast_result, "previsions", None)
        if not isinstance(previsions, dict):
            return None
        return previsions.get(node_id, {}).get(horizon)

    def _charger_action_engine(self) -> Any:
        """Construit un :class:`ActionEngine` (U18) si le module est disponible.

        Returns:
            L'instance du moteur, ou None si le module est absent ou si sa
            construction echoue (degradation gracieuse, jamais d'exception).
        """
        try:
            module = importlib.import_module("supplyscore.services.action_engine")
            return module.ActionEngine(self._service)
        except Exception:
            return None

    def _recommander(self, action_engine: Any, project_id: str, node_id: str) -> object | None:
        """Recommandations d'action du noeud via :class:`ActionEngine` (U18).

        Args:
            action_engine: instance du moteur (duck-typee), ou None si indisponible.
            project_id: projet concerne.
            node_id: noeud cible.

        Returns:
            Le resultat de ``action_engine.recommander(project_id, node_id,
            None, None)`` (``list[ActionRecommandation]``, potentiellement
            vide), ou None si le moteur est indisponible ou si l'appel echoue
            (un avertissement est alors ajoute a :attr:`avertissements`).
        """
        if action_engine is None:
            return None
        try:
            return action_engine.recommander(project_id, node_id, None, None)
        except Exception as exc:  # degradation volontaire d'une dependance optionnelle
            self.avertissements.append(f"Nœud {node_id!r} : recommandation indisponible ({exc}).")
            return None
