"""Moteur de décision et sélection de portefeuille — cœur prescriptif (HÉLIOS v7, U18).

:class:`ActionEngine` transforme des prévisions (rollouts contrefactuels U9) et
des effets estimés (journal d'interventions U17) en recommandations d'action
CLASSÉES et HONNÊTES, puis compose un portefeuille cohérent à l'échelle du
projet. Il consomme ses contrats voisins par DUCK-TYPING : aucun import direct
d'un module frère susceptible d'être absent — tout est typé structurellement,
importé paresseusement et dégradé proprement quand une brique manque.

Contrats CONSOMMÉS (tous optionnels, dégradation gracieuse) :

- Contrat 8 — catalogue d'actions (U15, ``supplyscore.domain.actions``) :
  chaque ``ActionSpec`` expose ``id``, ``libelle``, ``preconditions(ctx) ->
  bool``, ``apply_to_rollout``, ``delai_effet_weeks``, ``cout`` (dont
  ``monetaire``, ``penalite_client_evitee``, ``temps_h``,
  ``p_echec_execution_defaut``), ``incompatibles`` et
  ``objectifs_operationnels``. Importé si présent, sinon INJECTÉ.
- Contrat 12 — ``PairedForecast`` (U9, ``ForecastService.rollout_with_action``) :
  par nœud × horizon, ``p0``, ``p1``, ``delta_u_sim``, ``ic80_delta_mc``,
  ``ic80_delta_param``, ``p_delta_positif``. Fournisseur INJECTÉ ou auto-construit.
- Contrat 10 — ``action_effects.json`` (U17) : ``p_execution`` (Beta) et, par
  segment × a priori (``prior_sim`` / ``prior_faible`` / ``donnees_seules``),
  ``p_resolution``, ``delta_causal_ipw``, ``e_value``, ``overlap_ok``. Chargé
  depuis un chemin si fourni, sinon absent.

Contrats PRODUITS :

- Contrat 11 — :class:`ActionRecommandation` (figé) : recommandation par action.
- Contrat 13 — :class:`Selection` : portefeuille retenu / exclu à l'échelle projet.

HONNÊTETÉ (invariants) : la valeur n'est appelée « nette » (en euros) que si des
montants existent des DEUX côtés (coût ET pénalité évitée) ET qu'une estimation
d'effet est disponible ; sinon un score ORDINAL (« heuristique ») est produit,
jamais étiqueté comme valeur monétaire. L'incertitude du simulateur reste « non
quantifiée (simulateur) » : un grand nombre de tirages ne fabrique pas de preuve
réelle. Aucune écriture : service en LECTURE SEULE.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supplyscore.services.orchestrator import SupplyScoreService

# --- Constantes documentées ---------------------------------------------------------

#: Rang canonique à partir duquel un nœud est « profond » (fournisseur amont).
_SEUIL_RANG_PROFOND: int = 2

#: ur_local à partir duquel un nœud est considéré « saturé » (urgence quasi pleine).
_SEUIL_SATURATION: float = 0.8

#: hidden_risk à partir duquel le profil bascule « risque caché » (Ur sous-déclaré).
_SEUIL_RISQUE_CACHE: float = 0.2

#: Les trois a priori U17 comparés pour la robustesse (décision D27).
_POSTERIORS: tuple[str, ...] = ("prior_sim", "prior_faible", "donnees_seules")

#: A priori U17 par défaut pour p_resolution / p_eviter des recommandations.
_POSTERIOR_DEFAUT: str = "prior_sim"

#: Décote ORDINALE documentée du bénéfice pour risque secondaire (décision D28) :
#: 15 % de la pénalité évitée sont retranchés pour couvrir ce que l'action peut
#: dégrader ailleurs (le ``risque_secondaire`` de l'``ActionSpec``). Propagée par
#: bornes de l'intervalle — jamais un chiffrage fin, un abattement conservateur.
_HAIRCUT_RISQUE_SECONDAIRE: float = 0.15

#: Poids (faible) du temps humain dans le score heuristique : départage les
#: actions à effet égal sans jamais dominer l'effet lui-même.
_POIDS_TEMPS_HEURISTIQUE: float = 0.001

#: Seuils documentés de qualité de preuve, en nombre d'interventions RÉELLES.
_SEUIL_PREUVE_FORTE: int = 30
_SEUIL_PREUVE_MOYENNE: int = 8

#: Étiquette figée de l'incertitude du simulateur (décision D18’ : jamais « réel »).
_INCERTITUDE_MODELE: str = "non quantifiée (simulateur)"

#: Horizon (semaines) lu dans le rollout apparié pour l'effet cumulé.
_HORIZON_DEFAUT: int = 4

#: Identifiant conventionnel du bras de référence « ne rien faire ».
_ID_NE_RIEN_FAIRE: str = "ne_rien_faire"

#: Objectif opérationnel marquant une action de RÉAPPROVISIONNEMENT (ciblant un
#: fournisseur) — deux telles actions sur un fournisseur commun entrent en conflit.
_OBJECTIF_FOURNISSEUR: str = "fiabiliser_approvisionnement"

#: Sentinelle « fournisseur de prévision pas encore tenté » (auto-construction paresseuse).
_NON_TENTE: object = object()


# --- Contrats produits (figés) ------------------------------------------------------


@dataclass(frozen=True)
class ActionRecommandation:
    """Recommandation d'une action pour un nœud (contrat 11 figé).

    Attributes:
        action_id: identifiant de l'action recommandée.
        libelle: libellé d'affichage en français.
        p0: probabilité d'issue défavorable SANS action (baseline simulateur),
            None si aucune prévision disponible.
        p1: ``{"est": float | None, "source": str}`` — probabilité AVEC action
            et provenance (``"sim"`` / ``"causal_ipw"`` / ``"absent"``).
        delta_u: ``{"est", "lo80", "hi80", "source", "couverture_ic"}`` — effet
            estimé (réduction de l'issue) et couverture de son IC (``["mc",
            "param"]`` pour U9, ``["causal"]`` pour U17, ``[]`` si absent).
        p_delta_positif: fraction des tirages externes à effet positif (U9), ou None.
        p_resolution_op: ``{"est", "lo80", "hi80"}`` — probabilité que l'action
            résolve l'issue (posterior U17 ``prior_sim`` par défaut), None si absent.
        p_execution: probabilité de bonne exécution (moyenne Beta U17, sinon
            ``1 − p_echec_execution_defaut`` de l'``ActionSpec``).
        p_eviter: ``p_execution × p_resolution_op["est"]`` (décision D29), None
            si p_resolution_op est indisponible.
        valeur: ``{"nette": (lo, hi)}`` en euros SI montants + effet disponibles,
            sinon ``{"heuristique": float}`` (score ordinal, jamais des euros).
        delai_effet_weeks: triplet ``(min, mode, max)`` du délai d'effet.
        niveau_de_preuve: ``{"n_reel", "n_sim", "source_prior", "qualite"}`` —
            qualité ``"faible"``/``"moyen"``/``"fort"`` (seuils documentés).
        robuste_aux_priors: vrai si l'action reste l'argmax de ``p_eviter`` sous
            les TROIS a priori U17 (décision D27) ; faux si non vérifiable.
        justification: raisons en français (source, preuve, robustesse, dégradation).
        incertitude_modele: étiquette figée :data:`_INCERTITUDE_MODELE`.
    """

    action_id: str
    libelle: str
    p0: float | None
    p1: dict[str, Any]
    delta_u: dict[str, Any]
    p_delta_positif: float | None
    p_resolution_op: dict[str, float | None]
    p_execution: float
    p_eviter: float | None
    valeur: dict[str, Any]
    delai_effet_weeks: tuple[float, float, float]
    niveau_de_preuve: dict[str, Any]
    robuste_aux_priors: bool
    justification: list[str]
    incertitude_modele: str = _INCERTITUDE_MODELE


@dataclass(frozen=True)
class Selection:
    """Portefeuille d'actions retenues à l'échelle d'un projet (contrat 13 figé).

    Attributes:
        retenues: ``[{"node_id", "action_id", "valeur", "rang"}]`` — actions
            retenues, dans l'ordre de sélection (rang 1 = meilleure).
        exclues: ``[{"node_id", "action_id", "raison"}]`` — actions écartées,
            chacune avec une raison en français.
        budget_consomme: somme des coûts monétaires (milieux d'intervalle) retenus.
        avertissements: alertes en français (effets de substitution, budget non
            applicable, etc.).
    """

    retenues: list[dict[str, Any]]
    exclues: list[dict[str, Any]]
    budget_consomme: float
    avertissements: list[str]


# --- Aides pures --------------------------------------------------------------------


def _segment(rang: int, ur_local: float | None, hidden_risk: float | None) -> str:
    """Segment à 8 cellules d'un nœud (reproduit la définition U17).

    Trois axes binaires : rang (``profond``/``proche``), charge
    (``sature``/``fluide``) et profil (``risque_cache``/``u_temps``). Les
    scores manquants (None) sont traités comme nuls (``fluide`` / ``u_temps``).

    Args:
        rang: rang canonique du nœud (0 = client final, N = fournisseur profond).
        ur_local: urgence locale observée du nœud, ou None.
        hidden_risk: risque caché H = [Ur − Ud]+ du nœud, ou None.

    Returns:
        L'identifiant de segment, p. ex. ``"profond_sature_risque_cache"``.
    """
    rang_lbl = "profond" if rang >= _SEUIL_RANG_PROFOND else "proche"
    charge_lbl = "sature" if (ur_local or 0.0) >= _SEUIL_SATURATION else "fluide"
    profil_lbl = "risque_cache" if (hidden_risk or 0.0) >= _SEUIL_RISQUE_CACHE else "u_temps"
    return f"{rang_lbl}_{charge_lbl}_{profil_lbl}"


def segment_pour_etat(etat_avant: Mapping[str, float | None], rang: int) -> str:
    """Segment d'un nœud à partir de son état AVANT observable et de son rang.

    Args:
        etat_avant: état observable ``{"ur_local", "ud_local", "hidden_risk",
            "false_urgency"}`` (clés absentes tolérées).
        rang: rang canonique du nœud.

    Returns:
        L'identifiant de segment (cf. :func:`_segment`).
    """
    return _segment(rang, etat_avant.get("ur_local"), etat_avant.get("hidden_risk"))


def _valeur_scalaire(valeur: Mapping[str, Any]) -> float:
    """Réduit une ``valeur`` (nette ou heuristique) à un scalaire comparable.

    Args:
        valeur: ``{"nette": (lo, hi)}`` ou ``{"heuristique": float}``.

    Returns:
        Le milieu de l'intervalle net, sinon le score heuristique, sinon 0.0.
    """
    if "nette" in valeur:
        lo, hi = valeur["nette"]
        return (float(lo) + float(hi)) / 2.0
    if "heuristique" in valeur:
        return float(valeur["heuristique"])
    return 0.0


def _borne(objet: Any, attr: str) -> float | None:
    """Lit une borne (``bas``/``haut``) d'un intervalle de confiance duck-typé.

    Args:
        objet: intervalle exposant ``bas`` et ``haut`` (ou None).
        attr: nom de l'attribut (``"bas"`` ou ``"haut"``).

    Returns:
        La valeur flottante, ou None si absente/non convertible.
    """
    valeur = getattr(objet, attr, None)
    if valeur is None:
        return None
    try:
        return float(valeur)
    except (TypeError, ValueError):  # pragma: no cover - garde-fou duck-typing
        return None


def _union_ic(intervalles: Iterable[Any], repli: float) -> tuple[float, float]:
    """Union (enveloppe) de plusieurs IC — couvre toutes leurs sources.

    Args:
        intervalles: intervalles duck-typés (``bas``/``haut``), None ignorés.
        repli: valeur de repli (bas = haut) si aucun intervalle exploitable.

    Returns:
        ``(min des bas, max des hauts)``, ou ``(repli, repli)`` à défaut.
    """
    bas: list[float] = []
    haut: list[float] = []
    for ic in intervalles:
        b = _borne(ic, "bas")
        h = _borne(ic, "haut")
        if b is not None and h is not None:
            bas.append(b)
            haut.append(h)
    if not bas:
        return repli, repli
    return min(bas), max(haut)


def _produit_intervalle(scalaire: float, borne_lo: float, borne_hi: float) -> tuple[float, float]:
    """Produit d'un scalaire (signe quelconque) par un intervalle, bornes triées.

    Args:
        scalaire: facteur scalaire (peut être négatif).
        borne_lo: borne basse de l'intervalle.
        borne_hi: borne haute de l'intervalle.

    Returns:
        ``(min, max)`` des deux produits.
    """
    a = scalaire * borne_lo
    b = scalaire * borne_hi
    return (a, b) if a <= b else (b, a)


# --- Moteur -------------------------------------------------------------------------


class ActionEngine:
    """Recommandations d'action classées et sélection de portefeuille (U18).

    Service en LECTURE SEULE : ne passe jamais par la couche d'écriture, ne
    persiste rien. Construit au-dessus de la façade applicative et de trois
    briques optionnelles (catalogue U15, prévision U9, effets U17), toutes
    dégradées proprement en leur absence.
    """

    def __init__(
        self,
        service: SupplyScoreService,
        action_effects_path: str | None = None,
        catalogue: dict[str, Any] | None = None,
    ) -> None:
        """Initialise le moteur au-dessus de la façade et de ses briques optionnelles.

        Args:
            service: façade applicative (dépôt de graphe, registre) — utilisée
                pour construire le contexte, lire le nœud et dériver les
                incidences de graphe du portefeuille.
            action_effects_path: chemin d'un ``action_effects.json`` (contrat 10
                U17), ou None si les effets ne sont pas disponibles.
            catalogue: catalogue d'actions injecté ``{action_id: ActionSpec}`` ;
                si None, le catalogue U15 (``CATALOGUE_V1``) est importé s'il existe.
        """
        self._service = service
        self._catalogue_injecte = catalogue
        self._effets = self._charger_effets(action_effects_path)
        self._forecast_auto: Any = _NON_TENTE
        self._horizon = _HORIZON_DEFAUT

    # -- chargement des briques optionnelles ------------------------------------

    @staticmethod
    def _charger_effets(chemin: str | None) -> dict[str, Any] | None:
        """Charge le fichier d'effets U17 depuis un chemin, ou None.

        Args:
            chemin: chemin du JSON d'effets, ou None.

        Returns:
            Le dictionnaire d'effets, ou None si aucun chemin, fichier absent
            ou JSON illisible (dégradation silencieuse).
        """
        if not chemin:
            return None
        try:
            texte = Path(chemin).read_text(encoding="utf-8")
            charge = json.loads(texte)
        except (OSError, ValueError):  # pragma: no cover - garde-fou I/O
            return None
        return charge if isinstance(charge, dict) else None

    def _catalogue(self) -> dict[str, Any]:
        """Catalogue effectif : injecté en priorité, sinon U15 importé, sinon vide.

        Returns:
            Le catalogue ``{action_id: ActionSpec}`` (éventuellement vide).
        """
        if self._catalogue_injecte is not None:
            return self._catalogue_injecte
        try:
            module = importlib.import_module("supplyscore.domain.actions")
        except ImportError:
            return {}
        catalogue = getattr(module, "CATALOGUE_V1", None)
        return dict(catalogue) if isinstance(catalogue, Mapping) else {}

    def _fournisseur_prevision(self, forecast: Any) -> Any:
        """Fournisseur de prévision effectif : injecté, sinon U9 auto-construit.

        Args:
            forecast: fournisseur injecté (duck-typé ``rollout_with_action``) ou None.

        Returns:
            Le fournisseur à interroger, ou None si aucun disponible.
        """
        if forecast is not None:
            return forecast
        if self._forecast_auto is _NON_TENTE:
            self._forecast_auto = self._construire_forecast()
        return self._forecast_auto

    def _construire_forecast(self) -> Any:
        """Construit un ``ForecastService`` U9 sur la façade, ou None si indisponible.

        Returns:
            L'instance de service de prévision, ou None (module absent ou façade
            incompatible — dégradation gracieuse).
        """
        try:
            module = importlib.import_module("supplyscore.services.forecast")
            return module.ForecastService(self._service)
        except Exception:
            return None

    def _contexte(self, node_id: str) -> Any:
        """Construit le contexte U15 d'un nœud via la façade, ou None.

        Args:
            node_id: identifiant du nœud.

        Returns:
            Le contexte (duck-typé) attendu par les préconditions, ou None si le
            catalogue U15 est absent ou le contexte inconstructible.
        """
        try:
            module = importlib.import_module("supplyscore.domain.actions")
            return module.contexte_pour(self._service, node_id)
        except Exception:
            return None

    # -- accès aux effets U17 (tolérants) ---------------------------------------

    def _cellule_effets(self, action_id: str, segment: str | None) -> Mapping[str, Any] | None:
        """Cellule d'effets ``(action, segment)`` du fichier U17, ou None.

        Args:
            action_id: identifiant d'action.
            segment: segment du nœud (None si indéterminable).

        Returns:
            Le dictionnaire de la cellule (posteriors, delta_causal_ipw,
            e_value, overlap_ok), ou None si absent.
        """
        if not self._effets or segment is None:
            return None
        try:
            cellule = self._effets["actions"][action_id]["segments"][segment]
        except (KeyError, TypeError):
            return None
        return cellule if isinstance(cellule, Mapping) else None

    def _p_resolution(
        self, action_id: str, segment: str | None, posterior: str
    ) -> dict[str, float | None]:
        """Probabilité de résolution ``p_resolution`` d'un a priori donné.

        Args:
            action_id: identifiant d'action.
            segment: segment du nœud.
            posterior: a priori U17 (``prior_sim`` / ``prior_faible`` / ``donnees_seules``).

        Returns:
            ``{"est", "lo80", "hi80"}`` — valeurs None si l'entrée est absente.
        """
        vide: dict[str, float | None] = {"est": None, "lo80": None, "hi80": None}
        cellule = self._cellule_effets(action_id, segment)
        if cellule is None:
            return vide
        try:
            res = cellule["posteriors"][posterior]["p_resolution"]
            return {
                "est": float(res["mean"]),
                "lo80": float(res["lo80"]),
                "hi80": float(res["hi80"]),
            }
        except (KeyError, TypeError, ValueError):
            return vide

    def _p_execution(self, action_id: str, spec: Any) -> float:
        """Probabilité d'exécution : moyenne Beta U17, sinon repli de l'``ActionSpec``.

        Args:
            action_id: identifiant d'action.
            spec: spécification d'action (pour le repli ``p_echec_execution_defaut``).

        Returns:
            La probabilité d'exécution, dans [0, 1].
        """
        if self._effets:
            try:
                beta = self._effets["actions"][action_id]["p_execution"]
                alpha = float(beta["alpha"])
                beta_param = float(beta["beta"])
                if alpha + beta_param > 0.0:
                    return alpha / (alpha + beta_param)
            except (KeyError, TypeError, ValueError):
                pass
        cout = getattr(spec, "cout", {})
        p_echec = 0.0
        if isinstance(cout, Mapping):
            try:
                p_echec = float(cout.get("p_echec_execution_defaut", 0.0))
            except (TypeError, ValueError):
                p_echec = 0.0
        return min(max(1.0 - p_echec, 0.0), 1.0)

    def _n_reel(self, action_id: str) -> int:
        """Nombre d'interventions RÉELLES observées pour l'action (U17 ``p_execution.n``).

        Args:
            action_id: identifiant d'action.

        Returns:
            Le compte d'exécutions réelles, ou 0 si indisponible.
        """
        if not self._effets:
            return 0
        try:
            return int(self._effets["actions"][action_id]["p_execution"]["n"])
        except (KeyError, TypeError, ValueError):
            return 0

    @staticmethod
    def _qualite_preuve(n_reel: int) -> str:
        """Qualité de preuve à partir du nombre d'interventions réelles (seuils documentés).

        Le simulateur seul ne relève JAMAIS la qualité au-dessus de « faible » :
        la précision d'un rollout n'est pas une preuve terrain (D18’).

        Args:
            n_reel: nombre d'interventions réelles observées.

        Returns:
            ``"fort"`` (>= 30), ``"moyen"`` (>= 8) ou ``"faible"`` sinon.
        """
        if n_reel >= _SEUIL_PREUVE_FORTE:
            return "fort"
        if n_reel >= _SEUIL_PREUVE_MOYENNE:
            return "moyen"
        return "faible"

    # -- prévision appariée U9 (best effort) ------------------------------------

    def _prevision_appariee(
        self, project_id: str, node_id: str, spec: Any, sim: Any
    ) -> tuple[Any, int]:
        """Prévision appariée U9 pour ``(action, nœud)`` — au mieux, jamais fatale.

        Args:
            project_id: projet simulé.
            node_id: nœud ciblé.
            spec: action duck-typée (passée telle quelle au rollout).
            sim: fournisseur de prévision (ou None).

        Returns:
            ``(prevision_appariee | None, n_draws)`` — None si indisponible, en
            échec (historique insuffisant, projet inconnu…) ou nœud absent.
        """
        if sim is None:
            return None, 0
        try:
            paire = sim.rollout_with_action(project_id, spec, horizon_weeks=self._horizon)
            par_horizon = paire.previsions[node_id]
        except Exception:
            return None, 0
        if not par_horizon:
            return None, 0
        horizon = max(par_horizon)
        n_draws = int(getattr(paire, "n_draws", 0) or 0)
        return par_horizon[horizon], n_draws

    # -- valeur (décision D28) --------------------------------------------------

    @staticmethod
    def _valeur(
        cout: Mapping[str, Any] | Any,
        delta_est: float | None,
        p_execution: float,
        p_eviter: float | None,
        temps_h: float,
    ) -> dict[str, Any]:
        """Valeur d'une action : nette (euros) si possible, sinon heuristique.

        Nette (D28) : ``(1 − décote) × (delta_est × pénalité_évitée) −
        coût_monétaire``, propagée par bornes — exige des montants des DEUX
        côtés ET une estimation d'effet. Sinon un score ORDINAL
        ``p_eviter × effet − poids·temps`` (jamais des euros).

        Args:
            cout: coût structuré de l'action (``monetaire``, ``penalite_client_evitee``).
            delta_est: effet estimé (réduction d'issue), ou None.
            p_execution: probabilité d'exécution (repli de fiabilité).
            p_eviter: ``p_execution × p_resolution`` (fiabilité), ou None.
            temps_h: charge humaine en heures (départage heuristique).

        Returns:
            ``{"nette": (lo, hi)}`` ou ``{"heuristique": float}``.
        """
        monetaire = cout.get("monetaire") if isinstance(cout, Mapping) else None
        penalite = cout.get("penalite_client_evitee") if isinstance(cout, Mapping) else None
        if monetaire is not None and penalite is not None and delta_est is not None:
            cout_lo, cout_hi = float(monetaire[0]), float(monetaire[1])
            evite_lo, evite_hi = _produit_intervalle(
                delta_est, float(penalite[0]), float(penalite[1])
            )
            reste = 1.0 - _HAIRCUT_RISQUE_SECONDAIRE
            net_lo = reste * evite_lo - cout_hi
            net_hi = reste * evite_hi - cout_lo
            return {"nette": (net_lo, net_hi)}
        effet = delta_est if delta_est is not None else 0.0
        fiabilite = p_eviter if p_eviter is not None else p_execution
        score = fiabilite * effet - _POIDS_TEMPS_HEURISTIQUE * temps_h
        return {"heuristique": score}

    # -- robustesse aux a priori (décision D27) ---------------------------------

    def _argmax_par_posterior(
        self, applicables: Sequence[tuple[str, Any]], segment: str | None
    ) -> dict[str, str | None]:
        """Action argmax de ``p_eviter`` sous chacun des trois a priori U17.

        Args:
            applicables: couples ``(action_id, spec)`` retenus par préconditions.
            segment: segment du nœud (None si indéterminable).

        Returns:
            ``{posterior: action_id | None}`` — None si aucune action n'a de cellule.
        """
        argmax: dict[str, str | None] = {}
        for posterior in _POSTERIORS:
            meilleur_id: str | None = None
            meilleur_score = float("-inf")
            for action_id, spec in applicables:
                est = self._p_resolution(action_id, segment, posterior)["est"]
                if est is None:
                    continue
                score = self._p_execution(action_id, spec) * est
                if score > meilleur_score:
                    meilleur_score = score
                    meilleur_id = action_id
            argmax[posterior] = meilleur_id
        return argmax

    # -- recommandation par action ----------------------------------------------

    def _recommander_action(
        self,
        project_id: str,
        node_id: str,
        action_id: str,
        spec: Any,
        sim: Any,
        segment: str | None,
        argmax: dict[str, str | None],
    ) -> ActionRecommandation:
        """Construit la recommandation d'une action pour un nœud.

        Args:
            project_id: projet concerné.
            node_id: nœud ciblé.
            action_id: identifiant d'action.
            spec: spécification d'action (duck-typée).
            sim: fournisseur de prévision (ou None).
            segment: segment du nœud (ou None).
            argmax: argmax de p_eviter par a priori (pour la robustesse).

        Returns:
            La :class:`ActionRecommandation` figée.
        """
        libelle = str(getattr(spec, "libelle", action_id))
        cout = getattr(spec, "cout", {})
        delai = tuple(float(v) for v in getattr(spec, "delai_effet_weeks", (0.0, 0.0, 0.0)))
        temps_h = 0.0
        if isinstance(cout, Mapping) and cout.get("temps_h") is not None:
            temps_h = float(cout["temps_h"])
        justification: list[str] = []

        prev, n_sim = self._prevision_appariee(project_id, node_id, spec, sim)
        p_execution = self._p_execution(action_id, spec)
        p_res = self._p_resolution(action_id, segment, _POSTERIOR_DEFAUT)
        p_res_est = p_res["est"]
        p_eviter = p_execution * p_res_est if p_res_est is not None else None

        cellule = self._cellule_effets(action_id, segment)
        delta_causal = self._delta_causal(cellule)

        p0 = float(prev.p0) if prev is not None else None
        p_delta_positif = float(prev.p_delta_positif) if prev is not None else None

        delta_u: dict[str, Any]
        p1: dict[str, Any]
        delta_est: float | None
        if delta_causal is not None:
            est = float(delta_causal["est"])
            delta_est = est
            delta_u = {
                "est": est,
                "lo80": float(delta_causal.get("lo80", est)),
                "hi80": float(delta_causal.get("hi80", est)),
                "source": "causal_ipw",
                "couverture_ic": ["causal"],
            }
            p1 = {"est": (p0 - est) if p0 is not None else None, "source": "causal_ipw"}
            justification.append(
                "Effet causal (IPW observationnel), recouvrement suffisant (overlap_ok)."
            )
            if cellule is not None and cellule.get("e_value") is not None:
                justification.append(
                    f"E-value = {float(cellule['e_value']):.2f} "
                    "(robustesse aux confondants non observés)."
                )
        elif prev is not None:
            est = float(prev.delta_u_sim)
            delta_est = est
            lo, hi = _union_ic((prev.ic80_delta_mc, prev.ic80_delta_param), est)
            delta_u = {
                "est": est,
                "lo80": lo,
                "hi80": hi,
                "source": "sim",
                "couverture_ic": ["mc", "param"],
            }
            p1 = {"est": float(prev.p1), "source": "sim"}
            justification.append(
                "Effet SELON LE MODÈLE (rollout contrefactuel apparié U9), IC mc+param."
            )
        else:
            delta_est = None
            delta_u = {
                "est": None,
                "lo80": None,
                "hi80": None,
                "source": "absent",
                "couverture_ic": [],
            }
            p1 = {"est": None, "source": "absent"}
            justification.append(
                "Aucune estimation quantitative d'effet disponible (U9 et U17 absents) : "
                "recommandation fondée sur les seules propriétés de l'action."
            )

        valeur = self._valeur(cout, delta_est, p_execution, p_eviter, temps_h)
        if "nette" not in valeur:
            justification.append(
                "Valeur ORDINALE (heuristique) : montants monétaires ou effet non renseignés."
            )

        n_reel = self._n_reel(action_id)
        source_prior = _POSTERIOR_DEFAUT if (self._effets and segment is not None) else None
        niveau_de_preuve = {
            "n_reel": n_reel,
            "n_sim": n_sim,
            "source_prior": source_prior,
            "qualite": self._qualite_preuve(n_reel),
        }

        robuste = (
            bool(self._effets)
            and segment is not None
            and all(argmax.get(posterior) == action_id for posterior in _POSTERIORS)
        )
        if robuste:
            justification.append("Choix ROBUSTE : argmax sous les trois a priori U17.")
        elif self._effets and segment is not None:
            justification.append("Choix NON robuste : l'argmax change selon l'a priori U17.")

        return ActionRecommandation(
            action_id=action_id,
            libelle=libelle,
            p0=p0,
            p1=p1,
            delta_u=delta_u,
            p_delta_positif=p_delta_positif,
            p_resolution_op=p_res,
            p_execution=p_execution,
            p_eviter=p_eviter,
            valeur=valeur,
            delai_effet_weeks=(delai[0], delai[1], delai[2]),
            niveau_de_preuve=niveau_de_preuve,
            robuste_aux_priors=robuste,
            justification=justification,
        )

    @staticmethod
    def _delta_causal(cellule: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        """Effet causal IPW exploitable d'une cellule (présent, overlap OK, estimé).

        Args:
            cellule: cellule d'effets ``(action, segment)`` ou None.

        Returns:
            Le dictionnaire ``delta_causal_ipw`` si utilisable, sinon None.
        """
        if cellule is None or not cellule.get("overlap_ok"):
            return None
        delta = cellule.get("delta_causal_ipw")
        if isinstance(delta, Mapping) and delta.get("est") is not None:
            return delta
        return None

    # -- API publique : recommandations d'un nœud -------------------------------

    def recommander(
        self, project_id: str, node_id: str, forecast: Any, contexte: Any
    ) -> list[ActionRecommandation]:
        """Recommandations d'action CLASSÉES pour un nœud (contrat 11).

        Filtre le catalogue par préconditions, évalue chaque action (source
        d'effet par priorité causal_ipw > sim > absent), classe par valeur
        décroissante, puis écarte les actions incompatibles avec une action
        MIEUX classée. Le bras ``ne_rien_faire`` est toujours évalué comme
        référence (valeur 0) et n'écarte jamais les autres.

        Args:
            project_id: projet concerné.
            node_id: nœud ciblé.
            forecast: fournisseur de prévision U9 (duck-typé ``rollout_with_action``)
                ou None (auto-construction U9, sinon effet « absent »).
            contexte: contexte U15 pour les préconditions (ou None : construit via
                la façade, sinon préconditions non vérifiées).

        Returns:
            Les recommandations, meilleures d'abord ; liste vide si aucun catalogue.
        """
        catalogue = self._catalogue()
        if not catalogue:
            return []
        ctx = contexte if contexte is not None else self._contexte(node_id)
        etat_avant, rang = self._etat_et_rang(node_id, ctx)
        segment = segment_pour_etat(etat_avant, rang) if etat_avant is not None else None
        sim = self._fournisseur_prevision(forecast)

        applicables = [
            (action_id, spec)
            for action_id, spec in catalogue.items()
            if self._precondition_ok(spec, ctx)
        ]
        argmax = self._argmax_par_posterior(applicables, segment)

        recos = [
            self._recommander_action(project_id, node_id, action_id, spec, sim, segment, argmax)
            for action_id, spec in applicables
        ]
        return self._classer_et_filtrer(recos, catalogue)

    def _etat_et_rang(self, node_id: str, ctx: Any) -> tuple[dict[str, float | None] | None, int]:
        """État AVANT observable et rang du nœud, depuis le contexte ou la façade.

        Args:
            node_id: identifiant du nœud.
            ctx: contexte U15 (peut porter ``node`` et ``urgency``), ou None.

        Returns:
            ``(etat_avant | None, rang)`` — etat_avant None si aucune urgence lisible.
        """
        urgence = getattr(ctx, "urgency", None)
        node = getattr(ctx, "node", None)
        if node is None:
            node = self._noeud_facade(node_id)
            if urgence is None and node is not None:
                urgence = getattr(node, "urgency", None)
        rang = int(getattr(node, "rank", 0)) if node is not None else 0
        if urgence is None:
            return None, rang
        etat_avant = {
            "ur_local": _flottant_ou_none(getattr(urgence, "ur_local", None)),
            "ud_local": _flottant_ou_none(getattr(urgence, "ud_local", None)),
            "hidden_risk": _flottant_ou_none(getattr(urgence, "hidden_risk", None)),
            "false_urgency": _flottant_ou_none(getattr(urgence, "false_urgency", None)),
        }
        return etat_avant, rang

    def _noeud_facade(self, node_id: str) -> Any:
        """Lecture d'un nœud via la façade, tolérante aux façades minimales.

        Args:
            node_id: identifiant du nœud.

        Returns:
            Le nœud, ou None si la façade ne peut pas le fournir.
        """
        repo = getattr(self._service, "repo", None)
        if repo is None:
            return None
        try:
            return repo.get_node(node_id)
        except Exception:
            return None

    @staticmethod
    def _precondition_ok(spec: Any, ctx: Any) -> bool:
        """Évalue la précondition d'une action (permissive si non vérifiable).

        Args:
            spec: spécification d'action (duck-typée).
            ctx: contexte U15, ou None.

        Returns:
            Vrai si applicable ; vrai par défaut si contexte absent ou
            précondition non évaluable (l'action reste candidate, à charge des
            couches aval de vérifier).
        """
        precond = getattr(spec, "preconditions", None)
        if precond is None or ctx is None:
            return True
        try:
            return bool(precond(ctx))
        except Exception:
            return True

    def _classer_et_filtrer(
        self, recos: Sequence[ActionRecommandation], catalogue: Mapping[str, Any]
    ) -> list[ActionRecommandation]:
        """Classe par valeur décroissante puis retire les incompatibles moins bien classés.

        ``ne_rien_faire`` est conservé comme référence et n'entre pas dans le jeu
        d'incompatibilités (il n'écarte pas et n'est pas écarté).

        Args:
            recos: recommandations non triées.
            catalogue: catalogue (pour lire ``incompatibles``).

        Returns:
            La liste classée et cohérente (sans conflits d'incompatibilité).
        """
        ordonnees = sorted(recos, key=lambda r: r.action_id)
        ordonnees.sort(key=lambda r: _valeur_scalaire(r.valeur), reverse=True)
        resultat: list[ActionRecommandation] = []
        retenus: list[str] = []
        for reco in ordonnees:
            if reco.action_id == _ID_NE_RIEN_FAIRE:
                resultat.append(reco)
                continue
            if self._en_conflit(reco.action_id, retenus, catalogue):
                continue
            resultat.append(reco)
            retenus.append(reco.action_id)
        return resultat

    @staticmethod
    def _en_conflit(action_id: str, retenus: Sequence[str], catalogue: Mapping[str, Any]) -> bool:
        """Vrai si l'action est incompatible avec une action déjà retenue (mieux classée).

        Args:
            action_id: action candidate.
            retenus: actions déjà retenues (hors ``ne_rien_faire``).
            catalogue: catalogue (pour ``incompatibles`` des deux côtés).

        Returns:
            Vrai en cas d'incompatibilité (symétrique) avec un retenu.
        """
        propres = set(_incompatibles(catalogue.get(action_id)))
        for autre in retenus:
            if autre == _ID_NE_RIEN_FAIRE:
                continue
            if autre in propres or action_id in set(_incompatibles(catalogue.get(autre))):
                return True
        return False

    # -- API publique : portefeuille (décision D30) -----------------------------

    def portefeuille(
        self,
        project_id: str,
        recos_par_noeud: Mapping[str, Sequence[ActionRecommandation]],
        budget: float | None = None,
        capacites: Mapping[str, int] | None = None,
    ) -> Selection:
        """Compose un portefeuille cohérent d'actions à l'échelle du projet (contrat 13).

        Sélection GLOUTONNE par ratio valeur/coût, honorant : le budget
        monétaire, la capacité par type d'action, les incompatibilités
        intra-nœud (``ActionSpec.incompatibles``) et inter-nœud (arc partagé ou
        fournisseur cible commun, dérivés du graphe via la façade). Seules les
        actions qui BATTENT ``ne_rien_faire`` de leur nœud sont candidates. Des
        avertissements signalent les effets de substitution (fournisseur commun).

        Args:
            project_id: projet concerné (réservé ; le graphe est lu via la façade).
            recos_par_noeud: recommandations par nœud (sortie de :meth:`recommander`).
            budget: budget monétaire total, ou None (non contraint).
            capacites: capacité maximale par ``action_id``, ou None (non contrainte).

        Returns:
            La :class:`Selection` (retenues classées, exclues motivées, budget
            consommé, avertissements).
        """
        del project_id  # topologie lue via la façade, pas besoin de l'id ici
        catalogue = self._catalogue()
        exclues: list[dict[str, Any]] = []
        avertissements: list[str] = []

        candidats = self._candidats_portefeuille(recos_par_noeud, exclues)
        if budget is not None and not self._budget_applicable(candidats, catalogue):
            avertissements.append(
                "Budget non appliqué : coûts monétaires indisponibles (catalogue absent)."
            )
            budget = None

        incidence = self._incidence_par_noeud(node_id for node_id, _ in candidats)
        retenus: list[tuple[str, ActionRecommandation]] = []
        budget_consomme = 0.0
        compte_par_action: dict[str, int] = {}

        for node_id, reco in candidats:
            spec = catalogue.get(reco.action_id)
            raison = self._raison_exclusion(
                node_id,
                reco,
                spec,
                retenus,
                incidence,
                catalogue,
                compte_par_action,
                capacites,
                budget,
                budget_consomme,
            )
            if raison is not None:
                exclues.append({"node_id": node_id, "action_id": reco.action_id, "raison": raison})
                continue
            retenus.append((node_id, reco))
            compte_par_action[reco.action_id] = compte_par_action.get(reco.action_id, 0) + 1
            cout = _cout_monetaire_mid(spec)
            if cout is not None:
                budget_consomme += cout

        retenues = [
            {
                "node_id": node_id,
                "action_id": reco.action_id,
                "valeur": _valeur_scalaire(reco.valeur),
                "rang": rang,
            }
            for rang, (node_id, reco) in enumerate(retenus, start=1)
        ]
        avertissements.extend(self._avertissements_substitution(retenus, incidence))
        return Selection(
            retenues=retenues,
            exclues=exclues,
            budget_consomme=budget_consomme,
            avertissements=avertissements,
        )

    def _candidats_portefeuille(
        self,
        recos_par_noeud: Mapping[str, Sequence[ActionRecommandation]],
        exclues: list[dict[str, Any]],
    ) -> list[tuple[str, ActionRecommandation]]:
        """Candidats (nœud, action) battant ``ne_rien_faire``, triés par ratio valeur/coût.

        Args:
            recos_par_noeud: recommandations par nœud.
            exclues: liste d'exclusions ENRICHIE en place pour les actions qui
                n'améliorent pas l'inaction.

        Returns:
            Les candidats triés (meilleur ratio d'abord).
        """
        catalogue = self._catalogue()
        candidats: list[tuple[str, ActionRecommandation]] = []
        for node_id, recos in recos_par_noeud.items():
            seuil = self._seuil_inaction(recos)
            for reco in recos:
                if reco.action_id == _ID_NE_RIEN_FAIRE:
                    continue
                if _valeur_scalaire(reco.valeur) <= seuil:
                    exclues.append(
                        {
                            "node_id": node_id,
                            "action_id": reco.action_id,
                            "raison": "n'améliore pas l'inaction (ne_rien_faire).",
                        }
                    )
                    continue
                candidats.append((node_id, reco))
        candidats.sort(key=lambda t: t[1].action_id)
        candidats.sort(key=lambda t: self._ratio(t[1], catalogue.get(t[1].action_id)), reverse=True)
        return candidats

    @staticmethod
    def _seuil_inaction(recos: Sequence[ActionRecommandation]) -> float:
        """Valeur de ``ne_rien_faire`` du nœud (seuil à battre), 0.0 par défaut.

        Args:
            recos: recommandations du nœud.

        Returns:
            La valeur scalaire de ``ne_rien_faire``, ou 0.0 si absent.
        """
        for reco in recos:
            if reco.action_id == _ID_NE_RIEN_FAIRE:
                return _valeur_scalaire(reco.valeur)
        return 0.0

    @staticmethod
    def _ratio(reco: ActionRecommandation, spec: Any) -> float:
        """Ratio valeur/coût d'une action pour l'ordre glouton.

        Args:
            reco: recommandation.
            spec: spécification d'action (pour le coût monétaire/temps), ou None.

        Returns:
            Le ratio ``valeur / coût`` (coût minimal 1.0 pour éviter la division
            par zéro et pour les actions sans coût chiffré).
        """
        valeur = _valeur_scalaire(reco.valeur)
        cout = _cout_monetaire_mid(spec)
        if cout is None or cout <= 0.0:
            cout_temps = 0.0
            cout_obj = getattr(spec, "cout", {})
            if isinstance(cout_obj, Mapping) and cout_obj.get("temps_h") is not None:
                cout_temps = float(cout_obj["temps_h"])
            cout = cout_temps
        return valeur / cout if cout > 0.0 else valeur

    @staticmethod
    def _budget_applicable(
        candidats: Sequence[tuple[str, ActionRecommandation]], catalogue: Mapping[str, Any]
    ) -> bool:
        """Vrai si au moins un candidat porte un coût monétaire chiffrable.

        Args:
            candidats: candidats du portefeuille.
            catalogue: catalogue (pour les coûts).

        Returns:
            Vrai si le budget peut être appliqué à au moins un candidat.
        """
        return any(
            _cout_monetaire_mid(catalogue.get(reco.action_id)) is not None for _, reco in candidats
        )

    def _raison_exclusion(
        self,
        node_id: str,
        reco: ActionRecommandation,
        spec: Any,
        retenus: Sequence[tuple[str, ActionRecommandation]],
        incidence: Mapping[str, tuple[set[str], set[str]]],
        catalogue: Mapping[str, Any],
        compte_par_action: Mapping[str, int],
        capacites: Mapping[str, int] | None,
        budget: float | None,
        budget_consomme: float,
    ) -> str | None:
        """Première raison d'exclure un candidat, ou None s'il est retenable.

        Ordre des critères : capacité, incompatibilité intra-nœud, conflit
        inter-nœud (arc partagé puis fournisseur cible commun), budget.

        Args:
            node_id: nœud du candidat.
            reco: recommandation candidate.
            spec: spécification d'action (ou None).
            retenus: couples ``(node_id, reco)`` déjà retenus.
            incidence: incidences de graphe ``{node_id: (arcs, fournisseurs)}``.
            catalogue: catalogue (incompatibilités, objectifs).
            compte_par_action: compteur d'actions déjà retenues par type.
            capacites: capacités par ``action_id`` (ou None).
            budget: budget total (ou None).
            budget_consomme: budget déjà consommé.

        Returns:
            La raison (français) ou None.
        """
        if capacites is not None:
            cap = capacites.get(reco.action_id)
            if cap is not None and compte_par_action.get(reco.action_id, 0) >= cap:
                return f"capacité atteinte pour l'action « {reco.action_id} » (max {cap})."

        propres_incompat = set(_incompatibles(spec))
        arcs_c, fournisseurs_c = incidence.get(node_id, (set(), set()))
        for autre_node, autre_reco in retenus:
            if autre_node == node_id and (
                autre_reco.action_id in propres_incompat
                or reco.action_id in set(_incompatibles(catalogue.get(autre_reco.action_id)))
            ):
                return f"incompatible avec « {autre_reco.action_id} » déjà retenue sur le nœud."
            if autre_node == node_id:
                continue
            arcs_a, fournisseurs_a = incidence.get(autre_node, (set(), set()))
            if arcs_c & arcs_a:
                return (
                    f"conflit d'arc partagé avec « {autre_reco.action_id} » sur "
                    f"le nœud {autre_node}."
                )
            if (
                fournisseurs_c & fournisseurs_a
                and _cible_fournisseur(spec)
                and _cible_fournisseur(catalogue.get(autre_reco.action_id))
            ):
                return (
                    f"conflit de fournisseur cible commun avec « {autre_reco.action_id} » "
                    f"sur le nœud {autre_node}."
                )

        if budget is not None:
            cout = _cout_monetaire_mid(spec)
            if cout is not None and budget_consomme + cout > budget + 1e-9:
                return (
                    f"budget insuffisant (coût {cout:.0f}, reste "
                    f"{max(budget - budget_consomme, 0.0):.0f})."
                )
        return None

    def _incidence_par_noeud(self, node_ids: Iterable[str]) -> dict[str, tuple[set[str], set[str]]]:
        """Incidences de graphe par nœud : arcs incidents et fournisseurs directs.

        Args:
            node_ids: nœuds pour lesquels calculer l'incidence.

        Returns:
            ``{node_id: (ids d'arcs incidents, ids de fournisseurs directs)}``.
        """
        cibles = set(node_ids)
        incidence: dict[str, tuple[set[str], set[str]]] = {
            node_id: (set(), set()) for node_id in cibles
        }
        for arc in self._arcs_registre():
            source = getattr(arc, "source_id", None)
            cible = getattr(arc, "target_id", None)
            arc_id = getattr(arc, "id", f"{source}->{cible}")
            if cible in incidence:
                arcs, fournisseurs = incidence[cible]
                arcs.add(arc_id)
                if source is not None:
                    fournisseurs.add(source)
            if source in incidence:
                incidence[source][0].add(arc_id)
        return incidence

    def _arcs_registre(self) -> Sequence[Any]:
        """Liste des arcs connus de la façade (tolérante aux façades minimales).

        Returns:
            La liste des arcs, ou une liste vide si indisponible.
        """
        registre = getattr(self._service, "registry", None)
        if registre is None or not hasattr(registre, "list_arcs"):
            return []
        try:
            return list(registre.list_arcs())
        except Exception:
            return []

    @staticmethod
    def _avertissements_substitution(
        retenus: Sequence[tuple[str, ActionRecommandation]],
        incidence: Mapping[str, tuple[set[str], set[str]]],
    ) -> list[str]:
        """Avertit des effets de substitution entre retenus partageant un fournisseur.

        Args:
            retenus: couples ``(node_id, reco)`` retenus.
            incidence: incidences de graphe par nœud.

        Returns:
            Les avertissements (un par paire concernée).
        """
        messages: list[str] = []
        for i in range(len(retenus)):
            node_i, reco_i = retenus[i]
            fournisseurs_i = incidence.get(node_i, (set(), set()))[1]
            for j in range(i + 1, len(retenus)):
                node_j, reco_j = retenus[j]
                communs = fournisseurs_i & incidence.get(node_j, (set(), set()))[1]
                if communs:
                    fournisseur = sorted(communs)[0]
                    messages.append(
                        f"Effet de substitution possible entre « {reco_i.action_id} » "
                        f"({node_i}) et « {reco_j.action_id} » ({node_j}) : "
                        f"fournisseur commun {fournisseur} — bénéfices non additifs."
                    )
        return messages


# --- Aides de portefeuille (pures) --------------------------------------------------


def _incompatibles(spec: Any) -> Sequence[str]:
    """Liste des identifiants incompatibles d'une action (vide si absente).

    Args:
        spec: spécification d'action (duck-typée) ou None.

    Returns:
        La séquence d'identifiants incompatibles.
    """
    valeur = getattr(spec, "incompatibles", None)
    return valeur if isinstance(valeur, Sequence) and not isinstance(valeur, str) else []


def _cible_fournisseur(spec: Any) -> bool:
    """Vrai si l'action cible un fournisseur (objectif de réapprovisionnement).

    Args:
        spec: spécification d'action (duck-typée) ou None.

    Returns:
        Vrai si ``fiabiliser_approvisionnement`` figure dans ses objectifs.
    """
    objectifs = getattr(spec, "objectifs_operationnels", None)
    return isinstance(objectifs, Sequence) and _OBJECTIF_FOURNISSEUR in objectifs


def _cout_monetaire_mid(spec: Any) -> float | None:
    """Milieu de l'intervalle de coût monétaire d'une action, ou None.

    Args:
        spec: spécification d'action (duck-typée) ou None.

    Returns:
        Le milieu ``(lo + hi) / 2``, ou None si aucun coût monétaire.
    """
    cout = getattr(spec, "cout", None)
    if not isinstance(cout, Mapping):
        return None
    monetaire = cout.get("monetaire")
    if monetaire is None:
        return None
    try:
        return (float(monetaire[0]) + float(monetaire[1])) / 2.0
    except (TypeError, ValueError, IndexError):  # pragma: no cover - garde-fou duck-typing
        return None


def _flottant_ou_none(valeur: Any) -> float | None:
    """Convertit une valeur en flottant, ou None si impossible/absente.

    Args:
        valeur: valeur à convertir.

    Returns:
        Le flottant, ou None.
    """
    if valeur is None:
        return None
    try:
        return float(valeur)
    except (TypeError, ValueError):  # pragma: no cover - garde-fou duck-typing
        return None
