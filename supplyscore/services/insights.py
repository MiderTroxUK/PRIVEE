"""InsightService — insights décisionnels en texte clair français (HÉLIOS v7, U12).

:class:`InsightService` est LE contrat de fin du plan v7 : il transforme les
sorties numériques des couches prévision (contrat 6, U11) et prescription
(contrat 11, U18) en phrases françaises auditables, jamais un chiffre nu.
Chaque :class:`Insight` porte un ``sources`` qui reprend TOUS les nombres
utilisés dans son ``message`` — aucune affirmation chiffrée sans trace.

RÈGLE ABSOLUE (plan D17) : ce module est 100 % RÈGLES + GABARITS. Aucun appel
LLM, nulle part, jamais — le texte est entièrement déterministe et rejouable
(mêmes entrées -> même sortie), donc auditable par construction.

Duck-typing des contrats amont (aucun import direct d'un module frère
susceptible d'être absent) :

- Contrat 6 — ``PredictionPoint`` (U11, :mod:`supplyscore.services.prediction`) :
  consommé via ``getattr`` avec repli, jamais importé. Champs lus :
  ``node_id``, ``node_name``, ``proba_by_horizon``, ``delta_vs_last_week``,
  ``p_jalon_rate``, ``impact_frac``, ``recommandation``.
- Contrat 11 — ``ActionRecommandation`` (U18, :mod:`supplyscore.services.action_engine`),
  portée par ``PredictionPoint.recommandation`` : dans l'implémentation réelle
  observée (``ActionEngine.recommander``), ce champ est une SÉQUENCE
  ``list[ActionRecommandation]`` déjà classée (meilleure d'abord) ; ce module
  accepte AUSSI un objet unique par tolérance duck-typing (cf.
  :func:`_recommandation_principale`). Les sous-champs (``p1``, ``delta_u``,
  ``p_resolution_op``, ``valeur``, ``niveau_de_preuve``) sont des mappings
  simples, lus par clé (jamais par attribut).

Données lues directement sur la façade applicative (:class:`SupplyScoreService`),
INDÉPENDAMMENT des points fournis — ces informations n'existent pas dans le
contrat 6 :

- criticité systématique (:class:`~supplyscore.services.criticite.ServiceCriticite`) ;
- H (risque caché) / F (fausse urgence) : ``node.urgency.hidden_risk`` /
  ``node.urgency.false_urgency`` (dépôt de graphe, PAS le point de prévision) ;
- arcs de secours (:class:`~supplyscore.domain.models.ArcKind.BACKUP`) :
  MÊME convention que :func:`supplyscore.domain.actions.contexte_pour` et le
  générateur de démo (:meth:`~supplyscore.data.generator.RandomSupplyChainGenerator.\
generate_backup_arcs`) — un arc de secours d'un nœud est un arc ENTRANT
  (``target_id == node_id`) : ``source_id`` est le fournisseur de secours,
  ``target_id`` le client (CE nœud), inerte dans tous les calculs de flux.

Versionnage (jamais de rupture silencieuse d'un gabarit ou d'un seuil) :
:data:`SEUILS_V1` fige les seuils de sévérité et de détection, et
:data:`TEMPLATES_V1` fige les gabarits de phrase. Une V2 ajouterait de
nouvelles constantes/un nouveau dict sans toucher aux existants.

Service en LECTURE SEULE : aucune écriture, jamais.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from supplyscore.domain.models import ArcKind

if TYPE_CHECKING:
    from supplyscore.domain.models import SupplyArc
    from supplyscore.services.orchestrator import SupplyScoreService

# --- Constantes documentées -----------------------------------------------------------

#: Horizon (semaines) de référence pour « P(≤4) » — même horizon par défaut que
#: :data:`supplyscore.services.action_engine._HORIZON_DEFAUT` (U18) et le
#: dernier horizon du défaut ``PredictionService.predict`` (U11).
HORIZON_REFERENCE: int = 4

#: Libellés d'affichage des trois niveaux de sévérité, dans l'ordre de tri.
_LIBELLES_SEVERITE: dict[str, str] = {"alerte": "Alerte", "attention": "Attention", "info": "Info"}

#: Rang de tri des sévérités (0 = affiché en premier).
_RANG_SEVERITE: dict[str, int] = {"alerte": 0, "attention": 1, "info": 2}


@dataclass(frozen=True)
class _SeuilsV1:
    """Seuils de sévérité et de détection, version 1 (figés — cf. :data:`SEUILS_V1`).

    Toute évolution de seuil crée une V2 distincte : les insights déjà émis
    restent interprétables avec la version qui les a produits.

    Attributes:
        alerte_p_le4: seuil de ``P(issue défavorable, ≤4 semaines)`` au-delà
            duquel une alerte est posée (ET avec ``alerte_impact_frac``).
        alerte_impact_frac: seuil de fraction du réseau impactée par le pire
            choc local du nœud (criticité), requis EN PLUS de
            ``alerte_p_le4`` pour l'alerte.
        attention_p_le4: seuil de ``P(issue défavorable, ≤4 semaines)`` au-delà
            duquel une attention est posée (seul, sans condition d'impact).
        attention_delta_semaine: seuil de hausse hebdomadaire brute de
            l'urgence locale (``delta_vs_last_week``) au-delà duquel une
            attention est posée.
        amelioration_delta_semaine: seuil (négatif) de baisse hebdomadaire de
            l'urgence locale en-deçà duquel le nœud est « en voie de
            résolution ».
        degrade_hidden_risk: seuil H (risque caché) au-delà duquel le mode
            dégradé suggère une revue de déclaration.
        degrade_false_urgency: seuil F (fausse urgence) au-delà duquel le
            mode dégradé suggère une désescalade.
        degrade_jalon_dominant: seuil de ``p_jalon_rate`` au-delà duquel (ET
            supérieur à P(≤4)) le mode dégradé suggère de revoir le jalon actif.
        degrade_fournisseur_alt_p_le4: seuil de ``P(≤4)`` au-delà duquel,
            SANS arc de secours disponible, le mode dégradé suggère de
            qualifier un fournisseur alternatif.
    """

    alerte_p_le4: float = 0.25
    alerte_impact_frac: float = 0.3
    attention_p_le4: float = 0.15
    attention_delta_semaine: float = 0.08
    amelioration_delta_semaine: float = -0.05
    degrade_hidden_risk: float = 0.3
    degrade_false_urgency: float = 0.3
    degrade_jalon_dominant: float = 0.5
    degrade_fournisseur_alt_p_le4: float = 0.25


#: Seuils de sévérité et de détection — version 1, figée (cf. :class:`_SeuilsV1`).
SEUILS_V1 = _SeuilsV1()


#: Gabarits de phrase — version 1, figée. Les clés ``reco_*`` composent LE BLOC
#: PRESCRIPTIF COMPLET (contrat de fin) quand une recommandation est présente ;
#: les clés ``action_*`` sont les suggestions du catalogue dégradé (recommandation
#: absente) ; les clés ``amelioration_*`` annotent une tendance à 2 semaines.
#: Les formulations entre guillemets du contrat sont reprises AU MOT PRÈS
#: (casse comprise) pour rester grep-ables dans les messages produits.
TEMPLATES_V1: dict[str, str] = {
    "reco_entete": "Action recommandée : {libelle}.",
    "reco_p0": "risque sans action : {valeur}",
    "reco_p1": "risque avec action : {valeur}",
    "reco_effet_sim": "effet estimé : {effet} (source : simulation appariée)",
    "reco_effet_causal": "effet estimé : {effet} (corrigée IPW sur {n_reel} observations réelles)",
    "reco_effet_absent": "effet non chiffré",
    "reco_p_delta_positif": "P(Δ>0) = {valeur}",
    "reco_p_resolution": "P(résolution opérationnelle | exécution) = {valeur}{ic}",
    "reco_p_execution": "P(exécution) = {valeur}",
    "reco_p_eviter": (
        "P(éviter la rupture) = {valeur} (= P(exécution) × P(résolution) = {p_exec} × {p_res})"
    ),
    "reco_valeur_nette": "valeur nette estimée : {valeur}",
    "reco_valeur_heuristique": (
        "classement heuristique : {valeur} (score ordinal — jamais une valeur monétaire)"
    ),
    "reco_delai": "délai d'effet estimé : {texte}",
    "reco_niveau_preuve": "niveau de preuve : {texte}",
    "reco_robuste": "recommandation ROBUSTE aux trois choix de prior",
    "reco_non_robuste": (
        "recommandation NON robuste aux trois choix de prior (l'argmax change selon l'a priori)"
    ),
    "reco_incertitude": "incertitude de modèle : {valeur}",
    "amelioration_1_semaine": (
        "en voie de résolution : l'urgence locale a reculé de {valeur} sur la dernière semaine"
    ),
    "amelioration_2_semaines": (
        "en voie de résolution depuis deux semaines consécutives"
        " (recul de {valeur} cette semaine, {valeur_precedent} la semaine précédente)"
    ),
    "action_arc_secours": (
        "promouvoir l'arc de secours vers {fournisseur} (secours qualifié pour {noeud})"
    ),
    "action_revue_declaration": "demander une revue de déclaration (risque caché H élevé)",
    "action_revoir_jalon": "revoir le jalon actif (probabilité de jalon raté dominante)",
    "action_fournisseur_alternatif": (
        "qualifier un fournisseur alternatif (aucun arc de secours disponible)"
    ),
    "action_desescalade": "désescalade possible (fausse urgence)",
}


# --- Contrat de sortie ------------------------------------------------------------------


@dataclass(frozen=True)
class Insight:
    """Insight décisionnel en texte clair français pour un nœud (LE contrat de fin).

    Attributes:
        severite: ``"alerte"``, ``"attention"`` ou ``"info"`` (cf. :data:`SEUILS_V1`).
        node_id: identifiant du nœud concerné.
        node_name: nom lisible du nœud.
        message: narratif français complet — sévérité + raisons, PUIS, si une
            recommandation est présente, le bloc prescriptif intégral (contrat
            de fin : p0, p1, effet et sa source, P(Δ>0), P(résolution),
            P(exécution), P(éviter la rupture), valeur nette ou heuristique,
            délai d'effet, niveau de preuve, robustesse, incertitude modèle),
            PUIS, si applicable, l'annotation de tendance « en voie de
            résolution ».
        pourquoi: raisons de sévérité, une phrase par seuil franchi (ou
            l'absence de seuil franchi / de donnée en mode dégradé).
        action: suggestion d'action COURTE en français — le libellé de la
            recommandation si ``recommandation`` était présente, sinon la
            première règle du catalogue dégradé qui s'applique (cf.
            :data:`TEMPLATES_V1`, clés ``action_*``), ou None si aucune ne
            s'applique.
        sources: TOUS les nombres utilisés dans ``message``, par clé
            explicite — auditabilité : aucune affirmation chiffrée sans trace
            retrouvable ici. ``None`` pour un nombre référencé mais absent.
    """

    severite: str
    node_id: str
    node_name: str
    message: str
    pourquoi: list[str]
    action: str | None
    sources: dict[str, float | None]


# --- Aides pures : duck-typing, nombres, formats -----------------------------------------


def _champ(objet: Any, nom: str, defaut: Any = None) -> Any:
    """Lit un champ d'un objet OU d'un mapping, duck-typing tolérant.

    Le contrat 11 mélange des dataclasses (``ActionRecommandation``, lues par
    attribut) et des mappings simples pour ses sous-champs (``p1``,
    ``delta_u``..., lus par clé) : cette aide unifie les deux lectures.

    Args:
        objet: objet ou mapping à lire (peut être None).
        nom: nom du champ/de la clé.
        defaut: valeur de repli si absent ou si ``objet`` est None.

    Returns:
        La valeur lue, ou ``defaut``.
    """
    if objet is None:
        return defaut
    if isinstance(objet, Mapping):
        return objet.get(nom, defaut)
    return getattr(objet, nom, defaut)


def _flottant_ou_none(valeur: Any) -> float | None:
    """Convertit en flottant si c'est un nombre réel (pas un booléen), sinon None.

    Args:
        valeur: valeur quelconque à convertir.

    Returns:
        Le flottant, ou None si ``valeur`` n'est pas un ``int``/``float`` réel
        (les booléens, sous-classes d'``int`` en Python, sont explicitement
        exclus).
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    return float(valeur)


def _pct(valeur: float | None, decimales: int = 1) -> str:
    """Formate une probabilité ``[0, 1]`` en pourcentage français.

    Args:
        valeur: probabilité à formater, ou None.
        decimales: nombre de décimales affichées.

    Returns:
        ``"27.3 %"``, ou ``"n/d"`` si ``valeur`` est None.
    """
    if valeur is None:
        return "n/d"
    return f"{valeur * 100:.{decimales}f} %"


def _pp(valeur: float | None, decimales: int = 1) -> str:
    """Formate un delta de probabilité en points de pourcentage SIGNÉS.

    Args:
        valeur: delta ``[-1, 1]`` à formater, ou None.
        decimales: nombre de décimales affichées.

    Returns:
        ``"+14.0 points de pourcentage"``, ou ``"n/d"`` si ``valeur`` est None.
    """
    if valeur is None:
        return "n/d"
    return f"{valeur * 100:+.{decimales}f} points de pourcentage"


def _ic80(bas: float | None, haut: float | None) -> str:
    """Formate un IC80 ``" [IC80 : a–b %]"`` (espace de tête inclus), vide si absent.

    Args:
        bas: borne basse ``[0, 1]``, ou None.
        haut: borne haute ``[0, 1]``, ou None.

    Returns:
        Le fragment formaté (espace de tête pour un accolement direct), ou
        chaîne vide si une des deux bornes manque.
    """
    if bas is None or haut is None:
        return ""
    return f" [IC80 : {bas * 100:.1f}–{haut * 100:.1f} %]"


def _p_le4(point: Any) -> float | None:
    """``P(issue défavorable, ≤4 semaines)`` d'un point de prévision duck-typé.

    Args:
        point: point de prévision (contrat 6, duck-typé).

    Returns:
        ``proba_by_horizon[4]``, ou None si absent ou l'horizon 4 non fourni.
    """
    proba = getattr(point, "proba_by_horizon", None)
    if not isinstance(proba, Mapping):
        return None
    return _flottant_ou_none(proba.get(HORIZON_REFERENCE))


def _recommandation_principale(point: Any) -> Any | None:
    """Recommandation « top » d'un point, quelle que soit sa forme exacte.

    Le contrat 6 déclare ``recommandation: object | None`` ; l'implémentation
    réelle observée (``ActionEngine.recommander``, U18) le peuple d'une
    SÉQUENCE ``list[ActionRecommandation]`` déjà classée meilleure d'abord.
    Les deux formes sont acceptées par tolérance duck-typing : un objet
    unique est retourné tel quel, une séquence rend son premier élément.

    Args:
        point: point de prévision (contrat 6, duck-typé).

    Returns:
        La recommandation « top », ou None si absente ou séquence vide.
    """
    rec = getattr(point, "recommandation", None)
    if rec is None:
        return None
    if isinstance(rec, (list, tuple)):
        return rec[0] if rec else None
    return rec


def _trouver_point(points: Sequence[Any] | None, node_id: str) -> Any | None:
    """Le point de la séquence portant ``node_id``, ou None si absent/aucune séquence.

    Args:
        points: séquence de points duck-typés (ex. semaine précédente), ou None.
        node_id: identifiant du nœud recherché.

    Returns:
        Le premier point dont ``node_id`` correspond, ou None.
    """
    if not points:
        return None
    for point in points:
        if getattr(point, "node_id", None) == node_id:
            return point
    return None


# --- Sévérité (SEUILS_V1) -----------------------------------------------------------------


def _severite_et_raisons(
    p_le4: float | None, impact_frac: float | None, delta: float | None
) -> tuple[str, list[str], dict[str, float | None]]:
    """Sévérité et raisons d'un point selon :data:`SEUILS_V1`.

    Règle de priorité (première branche qui s'applique) : alerte (P(≤4) ET
    impact réseau), sinon attention (P(≤4) OU hausse hebdomadaire — les DEUX
    raisons sont listées si les deux conditions tiennent), sinon info.

    Args:
        p_le4: ``P(issue défavorable, ≤4 semaines)``, ou None si indisponible.
        impact_frac: fraction du réseau impactée par le pire choc local du
            nœud (criticité), ou None si indisponible.
        delta: delta hebdomadaire brut de l'urgence locale, ou None.

    Returns:
        ``(severite, raisons, sources)`` — ``sources`` porte P(≤4)/impact_frac
        /delta ainsi que les seuils effectivement cités dans ``raisons``.
    """
    sources: dict[str, float | None] = {
        "p_le4": p_le4,
        "impact_frac": impact_frac,
        "delta_vs_last_week": delta,
    }

    if (
        p_le4 is not None
        and p_le4 > SEUILS_V1.alerte_p_le4
        and impact_frac is not None
        and impact_frac > SEUILS_V1.alerte_impact_frac
    ):
        sources["seuil_alerte_p_le4"] = SEUILS_V1.alerte_p_le4
        sources["seuil_alerte_impact_frac"] = SEUILS_V1.alerte_impact_frac
        raisons = [
            f"P(issue défavorable, ≤4 semaines) = {_pct(p_le4)}"
            f" (seuil d'alerte : > {_pct(SEUILS_V1.alerte_p_le4)}).",
            f"Impact réseau du pire choc local = {_pct(impact_frac)} des nœuds du projet"
            f" (seuil : > {_pct(SEUILS_V1.alerte_impact_frac)}).",
        ]
        return "alerte", raisons, sources

    raisons = []
    if p_le4 is not None and p_le4 > SEUILS_V1.attention_p_le4:
        sources["seuil_attention_p_le4"] = SEUILS_V1.attention_p_le4
        raisons.append(
            f"P(issue défavorable, ≤4 semaines) = {_pct(p_le4)}"
            f" (seuil d'attention : > {_pct(SEUILS_V1.attention_p_le4)})."
        )
    if delta is not None and delta > SEUILS_V1.attention_delta_semaine:
        sources["seuil_attention_delta_semaine"] = SEUILS_V1.attention_delta_semaine
        raisons.append(
            f"Hausse hebdomadaire de l'urgence locale : {_pp(delta)}"
            f" (seuil : > {_pp(SEUILS_V1.attention_delta_semaine)})."
        )
    if raisons:
        return "attention", raisons, sources

    if p_le4 is None:
        raisons.append(
            "P(issue défavorable, ≤4 semaines) non disponible (mode dégradé, sans modèle)."
        )
    else:
        raisons.append(
            f"P(issue défavorable, ≤4 semaines) = {_pct(p_le4)}"
            " (sous les seuils d'alerte et d'attention)."
        )
    return "info", raisons, sources


def _annotation_amelioration(
    point: Any, previous: Sequence[Any] | None
) -> tuple[str | None, dict[str, float | None]]:
    """Annotation « en voie de résolution » si l'urgence locale recule nettement.

    Args:
        point: point de prévision courant (duck-typé).
        previous: points de la semaine précédente (duck-typés), pour établir
            la tendance à 2 semaines — None si non fournis.

    Returns:
        ``(texte, sources)`` — ``texte`` est None si le seuil d'amélioration
        n'est pas franchi (``sources`` est alors vide).
    """
    delta = _flottant_ou_none(getattr(point, "delta_vs_last_week", None))
    if delta is None or delta >= SEUILS_V1.amelioration_delta_semaine:
        return None, {}

    sources: dict[str, float | None] = {
        "amelioration_delta_semaine": delta,
        "seuil_amelioration_delta_semaine": SEUILS_V1.amelioration_delta_semaine,
    }
    node_id = getattr(point, "node_id", None)
    precedent = _trouver_point(previous, node_id) if node_id is not None else None
    delta_precedent = (
        _flottant_ou_none(getattr(precedent, "delta_vs_last_week", None))
        if precedent is not None
        else None
    )
    if delta_precedent is not None and delta_precedent < 0.0:
        sources["amelioration_delta_semaine_precedente"] = delta_precedent
        texte = TEMPLATES_V1["amelioration_2_semaines"].format(
            valeur=_pp(delta), valeur_precedent=_pp(delta_precedent)
        )
    else:
        texte = TEMPLATES_V1["amelioration_1_semaine"].format(valeur=_pp(delta))
    return texte, sources


# --- Bloc prescriptif complet (contrat de fin, recommandation présente) -------------------


def _texte_delai(delai: Any) -> tuple[str, tuple[float | None, float | None, float | None]]:
    """Texte français du délai d'effet à partir du triplet ``(min, mode, max)``.

    Args:
        delai: ``delai_effet_weeks`` duck-typé — attendu ``(min, mode, max)``.

    Returns:
        ``(texte, (min, mode, max))`` — les trois flottants sont None si
        ``delai`` n'est pas un triplet numérique exploitable.
    """
    if isinstance(delai, (tuple, list)) and len(delai) == 3:
        bornes = tuple(_flottant_ou_none(v) for v in delai)
        d_min, d_mode, d_max = bornes
        if d_min is not None and d_mode is not None and d_max is not None:
            return f"{d_min:g} à {d_max:g} semaine(s) (le plus probable : {d_mode:g})", (
                d_min,
                d_mode,
                d_max,
            )
    return "non disponible", (None, None, None)


def _texte_niveau_preuve(niveau: Any) -> tuple[str, float | None, float | None]:
    """Texte français du niveau de preuve, phrasé EXACTEMENT sur ``source_prior``.

    Impose la formulation « a priori simulé + n observations réelles » quand
    ``source_prior == "prior_sim"`` (a priori U17 par défaut), telle que
    citée par le contrat de fin.

    Args:
        niveau: ``niveau_de_preuve`` duck-typé — mapping attendu
            ``{"n_reel", "n_sim", "source_prior", "qualite"}``.

    Returns:
        ``(texte, n_reel, n_sim)`` — ``n_reel``/``n_sim`` flottants pour
        ``sources`` (None si absents/non numériques).
    """
    n_reel = _flottant_ou_none(_champ(niveau, "n_reel"))
    n_sim = _flottant_ou_none(_champ(niveau, "n_sim"))
    n_reel_i = int(n_reel) if n_reel is not None else 0
    n_sim_i = int(n_sim) if n_sim is not None else 0
    source_prior = _champ(niveau, "source_prior")
    qualite = _champ(niveau, "qualite")
    qualite_txt = qualite if isinstance(qualite, str) and qualite else "inconnue"

    if source_prior == "prior_sim":
        base = f"a priori simulé + {n_reel_i} observations réelles"
    elif source_prior == "prior_faible":
        base = f"a priori faible + {n_reel_i} observations réelles"
    elif source_prior == "donnees_seules":
        base = f"données seules + {n_reel_i} observations réelles"
    else:
        base = f"{n_reel_i} observations réelles (a priori indisponible)"
    texte = f"{base}, {n_sim_i} simulation(s) appariée(s) (qualité : {qualite_txt})"
    return texte, n_reel, n_sim


def _bloc_prescriptif(rec: Any) -> tuple[str, dict[str, float | None]]:
    """Bloc prescriptif COMPLET (contrat de fin) d'une recommandation duck-typée.

    Rend, dans l'ordre du plan v7, TOUS les éléments exigés : p0, p1, effet
    estimé (source nommée explicitement), P(Δ>0), P(résolution opérationnelle
    | exécution), P(exécution), P(éviter la rupture) (produit affiché),
    valeur nette OU heuristique (jamais confondues), délai d'effet, niveau de
    preuve, robustesse aux trois a priori, incertitude de modèle.

    Args:
        rec: recommandation duck-typée (contrat 11 — ``ActionRecommandation``
            ou équivalent structurel : objet ou mapping).

    Returns:
        ``(bloc, sources)`` — le texte français complet (clauses jointes par
        « ; ») et TOUS les nombres qui y figurent, par clé explicite.
    """
    sources: dict[str, float | None] = {}
    clauses: list[str] = []

    libelle = _champ(rec, "libelle") or _champ(rec, "action_id") or "action inconnue"
    clauses.append(TEMPLATES_V1["reco_entete"].format(libelle=libelle))

    p0 = _flottant_ou_none(_champ(rec, "p0"))
    sources["reco_p0"] = p0
    clauses.append(TEMPLATES_V1["reco_p0"].format(valeur=_pct(p0)))

    p1_est = _flottant_ou_none(_champ(_champ(rec, "p1"), "est"))
    sources["reco_p1"] = p1_est
    clauses.append(TEMPLATES_V1["reco_p1"].format(valeur=_pct(p1_est)))

    delta_u = _champ(rec, "delta_u")
    delta_source = _champ(delta_u, "source")
    delta_est = _flottant_ou_none(_champ(delta_u, "est"))
    sources["reco_delta_u_est"] = delta_est
    sources["reco_delta_u_lo80"] = _flottant_ou_none(_champ(delta_u, "lo80"))
    sources["reco_delta_u_hi80"] = _flottant_ou_none(_champ(delta_u, "hi80"))
    if delta_source == "sim":
        clauses.append(TEMPLATES_V1["reco_effet_sim"].format(effet=_pp(delta_est)))
    elif delta_source == "causal_ipw":
        n_reel_brut = _flottant_ou_none(_champ(_champ(rec, "niveau_de_preuve"), "n_reel"))
        n_reel_effet = int(n_reel_brut) if n_reel_brut is not None else 0
        clauses.append(
            TEMPLATES_V1["reco_effet_causal"].format(effet=_pp(delta_est), n_reel=n_reel_effet)
        )
    else:
        clauses.append(TEMPLATES_V1["reco_effet_absent"])

    p_delta_positif = _flottant_ou_none(_champ(rec, "p_delta_positif"))
    sources["reco_p_delta_positif"] = p_delta_positif
    clauses.append(TEMPLATES_V1["reco_p_delta_positif"].format(valeur=_pct(p_delta_positif)))

    p_res = _champ(rec, "p_resolution_op")
    p_res_est = _flottant_ou_none(_champ(p_res, "est"))
    p_res_lo = _flottant_ou_none(_champ(p_res, "lo80"))
    p_res_hi = _flottant_ou_none(_champ(p_res, "hi80"))
    sources["reco_p_resolution_op_est"] = p_res_est
    sources["reco_p_resolution_op_lo80"] = p_res_lo
    sources["reco_p_resolution_op_hi80"] = p_res_hi
    clauses.append(
        TEMPLATES_V1["reco_p_resolution"].format(
            valeur=_pct(p_res_est), ic=_ic80(p_res_lo, p_res_hi)
        )
    )

    p_execution = _flottant_ou_none(_champ(rec, "p_execution"))
    sources["reco_p_execution"] = p_execution
    clauses.append(TEMPLATES_V1["reco_p_execution"].format(valeur=_pct(p_execution)))

    p_eviter = _flottant_ou_none(_champ(rec, "p_eviter"))
    sources["reco_p_eviter"] = p_eviter
    clauses.append(
        TEMPLATES_V1["reco_p_eviter"].format(
            valeur=_pct(p_eviter), p_exec=_pct(p_execution), p_res=_pct(p_res_est)
        )
    )

    valeur = _champ(rec, "valeur")
    nette = _champ(valeur, "nette")
    if isinstance(nette, (tuple, list)) and len(nette) == 2:
        lo, hi = _flottant_ou_none(nette[0]), _flottant_ou_none(nette[1])
        sources["reco_valeur_nette_lo"] = lo
        sources["reco_valeur_nette_hi"] = hi
        lo_txt = f"{lo:.0f}" if lo is not None else "n/d"
        hi_txt = f"{hi:.0f}" if hi is not None else "n/d"
        clauses.append(TEMPLATES_V1["reco_valeur_nette"].format(valeur=f"{lo_txt} € à {hi_txt} €"))
    else:
        heuristique = _flottant_ou_none(_champ(valeur, "heuristique"))
        sources["reco_valeur_heuristique"] = heuristique
        heur_txt = f"{heuristique:.3f}" if heuristique is not None else "n/d"
        clauses.append(TEMPLATES_V1["reco_valeur_heuristique"].format(valeur=heur_txt))

    texte_delai, (d_min, d_mode, d_max) = _texte_delai(_champ(rec, "delai_effet_weeks"))
    sources["reco_delai_min"] = d_min
    sources["reco_delai_mode"] = d_mode
    sources["reco_delai_max"] = d_max
    clauses.append(TEMPLATES_V1["reco_delai"].format(texte=texte_delai))

    texte_preuve, n_reel, n_sim = _texte_niveau_preuve(_champ(rec, "niveau_de_preuve"))
    sources["reco_niveau_preuve_n_reel"] = n_reel
    sources["reco_niveau_preuve_n_sim"] = n_sim
    clauses.append(TEMPLATES_V1["reco_niveau_preuve"].format(texte=texte_preuve))

    robuste = bool(_champ(rec, "robuste_aux_priors", False))
    clauses.append(TEMPLATES_V1["reco_robuste" if robuste else "reco_non_robuste"])

    incertitude = _champ(rec, "incertitude_modele") or "non quantifiée (simulateur)"
    clauses.append(TEMPLATES_V1["reco_incertitude"].format(valeur=incertitude))

    return " ; ".join(clauses) + ".", sources


# --- Catalogue dégradé (recommandation absente) --------------------------------------------


def _fournisseurs_secours(service: SupplyScoreService, node_id: str) -> list[SupplyArc]:
    """Arcs de secours ENTRANTS du nœud (fournisseurs de secours candidats).

    Même convention que :func:`supplyscore.domain.actions.contexte_pour`
    (``arcs_backup``) et le générateur de démo : seuls les arcs BACKUP dont
    ``target_id`` est ce nœud comptent (``source_id`` = fournisseur de secours).

    Args:
        service: façade applicative (dépôt de graphe en mémoire).
        node_id: identifiant du nœud.

    Returns:
        Les :class:`~supplyscore.domain.models.SupplyArc` de secours entrants
        (liste vide si aucun).
    """
    return [a for a in service.repo.arcs(kinds=(ArcKind.BACKUP,)) if a.target_id == node_id]


class InsightService:
    """Assembleur d'insights décisionnels — lecture seule au-dessus de la façade.

    LE contrat de fin du plan v7 : transforme les points de prévision
    (contrat 6, duck-typés — jamais un import direct d'un module frère
    susceptible d'être absent) en :class:`Insight` français audités. Les
    signaux indisponibles sur le contrat 6 (H, F, arcs de secours) sont lus
    EN DIRECT sur la façade fournie, jamais fabriqués.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service d'insights sur la façade de l'application.

        Args:
            service: façade :class:`~supplyscore.services.orchestrator.SupplyScoreService`
                (dépôt de graphe, registre) — utilisée pour H/F et les arcs de
                secours, jamais pour écrire.
        """
        self._service = service

    # --- API publique ---------------------------------------------------------------

    def insights(
        self,
        project_id: str,
        points: Sequence[Any],
        previous: Sequence[Any] | None = None,
    ) -> list[Insight]:
        """Un :class:`Insight` par point fourni, trié par sévérité puis P(≤4) décroissant.

        Args:
            project_id: projet concerné (validé contre le registre).
            points: points de prévision (contrat 6, duck-typés) — un insight
                est produit par point, quelle qu'en soit la sévérité.
            previous: points de la semaine précédente (duck-typés), pour la
                tendance à 2 semaines de l'annotation d'amélioration — None
                si non fournis (l'amélioration reste détectée sur 1 semaine).

        Returns:
            Les :class:`Insight`, triés (alerte > attention > info, puis
            P(≤4) décroissant — les P(≤4) indisponibles en dernier).

        Raises:
            ValueError: si le projet est inconnu du registre (message en
                français).
        """
        if self._service.registry.get_project(project_id) is None:
            raise ValueError(f"Projet inconnu : {project_id!r}")

        resultats = [self._insight_pour_point(point, previous) for point in points]
        resultats.sort(key=self._cle_tri)
        return resultats

    # --- Assemblage d'un point --------------------------------------------------------

    def _insight_pour_point(self, point: Any, previous: Sequence[Any] | None) -> Insight:
        """Assemble l'insight complet d'un point : sévérité, prescription, amélioration.

        Args:
            point: point de prévision (contrat 6, duck-typé).
            previous: points de la semaine précédente (duck-typés), ou None.

        Returns:
            L':class:`Insight` assemblé.
        """
        node_id = str(getattr(point, "node_id", ""))
        node_name = str(getattr(point, "node_name", node_id))

        p_le4 = _p_le4(point)
        impact_frac = _flottant_ou_none(getattr(point, "impact_frac", None))
        delta = _flottant_ou_none(getattr(point, "delta_vs_last_week", None))

        severite, raisons, sources = _severite_et_raisons(p_le4, impact_frac, delta)
        morceaux = [f"{_LIBELLES_SEVERITE[severite]} — {node_name}.", *raisons]

        rec = _recommandation_principale(point)
        if rec is not None:
            bloc, sources_reco = _bloc_prescriptif(rec)
            morceaux.append(bloc)
            sources.update(sources_reco)
            libelle = _champ(rec, "libelle") or _champ(rec, "action_id")
            action: str | None = str(libelle) if libelle else None
        else:
            action = self._action_degradee(point)

        amelioration_texte, sources_amelioration = _annotation_amelioration(point, previous)
        if amelioration_texte is not None:
            morceaux.append(amelioration_texte + ".")
            sources.update(sources_amelioration)

        return Insight(
            severite=severite,
            node_id=node_id,
            node_name=node_name,
            message=" ".join(morceaux),
            pourquoi=raisons,
            action=action,
            sources=sources,
        )

    # --- Catalogue dégradé (recommandation absente) -----------------------------------

    def _action_degradee(self, point: Any) -> str | None:
        """Première règle du catalogue dégradé qui s'applique, ou None.

        Ordre FIGÉ et documenté (la première règle qui s'applique gagne) :
        (1) arc de secours disponible -> le promouvoir ; (2) risque caché H
        élevé -> revue de déclaration ; (3) jalon dominant -> le revoir ; (4)
        P(≤4) élevé SANS arc de secours -> qualifier un fournisseur alternatif ;
        (5) fausse urgence F élevée -> désescalade possible.

        Args:
            point: point de prévision (contrat 6, duck-typé) — utilisé pour
                ``node_id``, ``p_jalon_rate`` et P(≤4) ; H/F et les arcs de
                secours sont relus EN DIRECT sur la façade.

        Returns:
            Le texte français de l'action suggérée, ou None si aucune règle
            ne s'applique.
        """
        node_id = getattr(point, "node_id", None)
        if not isinstance(node_id, str) or not node_id:
            return None
        node = self._service.repo.get_node(node_id)

        backups = _fournisseurs_secours(self._service, node_id)
        if backups:
            choisi = min(backups, key=lambda a: a.source_id)
            fournisseur_node = self._service.repo.get_node(choisi.source_id)
            fournisseur_nom = (
                fournisseur_node.name if fournisseur_node is not None else choisi.source_id
            )
            noeud_nom = node.name if node is not None else node_id
            return TEMPLATES_V1["action_arc_secours"].format(
                fournisseur=fournisseur_nom, noeud=noeud_nom
            )

        hidden_risk = node.urgency.hidden_risk if node is not None else None
        if hidden_risk is not None and hidden_risk > SEUILS_V1.degrade_hidden_risk:
            return TEMPLATES_V1["action_revue_declaration"]

        p_le4 = _p_le4(point)
        p_jalon = _flottant_ou_none(getattr(point, "p_jalon_rate", None))
        if (
            p_jalon is not None
            and p_le4 is not None
            and p_jalon > SEUILS_V1.degrade_jalon_dominant
            and p_jalon > p_le4
        ):
            return TEMPLATES_V1["action_revoir_jalon"]

        if p_le4 is not None and p_le4 > SEUILS_V1.degrade_fournisseur_alt_p_le4:
            return TEMPLATES_V1["action_fournisseur_alternatif"]

        false_urgency = node.urgency.false_urgency if node is not None else None
        if false_urgency is not None and false_urgency > SEUILS_V1.degrade_false_urgency:
            return TEMPLATES_V1["action_desescalade"]

        return None

    # --- Tri ----------------------------------------------------------------------------

    @staticmethod
    def _cle_tri(insight: Insight) -> tuple[int, float]:
        """Clé de tri : sévérité (alerte > attention > info) puis P(≤4) décroissant.

        Args:
            insight: insight à ordonner.

        Returns:
            ``(rang_severite, -p_le4)`` — P(≤4) absent traité comme le plus
            bas (trié en dernier au sein de sa sévérité).
        """
        p_le4 = insight.sources.get("p_le4")
        return _RANG_SEVERITE.get(insight.severite, len(_RANG_SEVERITE)), -(
            p_le4 if p_le4 is not None else -1.0
        )
