"""Harnais d'experience du BRAS B (HELIOS) : declaration assistee par prevision.

Trois bras sont compares sur le MEME scenario HELIOS (crise des
semi-conducteurs 2020-2022 rejouee, verite terrain GELEE dans
``scenario.EVENTS``) :

- **bras A** - pilote LLM deja joue (``analysis/llm_pilot_run/``) : les
  personas lisent leur fiche et declarent leur Ud. Rien a rejouer ici.
- **bras B** - CE HARNAIS : fiche IDENTIQUE au bras A, plus (bras ``predict``
  seulement) une section " ANALYSE PREDICTIVE (outil) " qui expose au persona
  la prevision de SON noeud. Les personas DECLARENT seulement : aucune action,
  aucune modification de la verite terrain - KPIs, jalons et evenements
  restent pilotes par le pack gele ``data/prepared``. La boucle est OUVERTE,
  donc les previsions restent scorables.
- **bras C** - extension future (les personas agiront reellement sur la
  chaine) : NON IMPLEMENTE, cf. :func:`appliquer_actions_bras_c`.

L'A/B interne du bras B oppose deux sous-bras :

- ``control`` : la prevision est calculee et JOURNALISEE, jamais montree ;
- ``predict`` : la MEME prevision est en plus rendue dans la fiche.

Les deux sous-bras produisent donc des predictions prospectives comparables ;
seule leur VISIBILITE differe (``montre_au_persona`` dans
``predictions_log.jsonl``). Hors ce bloc, les fiches des deux sous-bras sont
identiques au caractere pres - c'est la validite interne de l'A/B.

Usage (une base SQLite PERSISTEE par sous-bras) ::

    python run_experiment.py init         --arm predict --db-dir D
    python run_experiment.py prepare-tour --arm predict --db-dir D --out O --tour N
    python run_experiment.py collect-tour --arm predict --db-dir D --answers F.jsonl
    python run_experiment.py close-tour   --arm predict --db-dir D --out O --tour N
    python run_experiment.py make-sandboxes --arm predict --out O
    python run_experiment.py status       --db-dir D

Aucun appel LLM n'est fait ici : le harnais lit et ecrit des fichiers, le
coordinateur fait tourner les personas (agents Haiku) sur les dossiers
``sandbox_<node>/`` produits par ``make-sandboxes``.

Garantie ANTI-FUITE (heritee de ``make_briefings``) : une fiche n'est
construite qu'a partir des fichiers prepares des tours <= N et des seules
donnees du noeud concerne. La section predictive n'ajoute que des nombres
calcules SUR CE NOEUD. Le pack ``data/prepared`` est ouvert en LECTURE SEULE.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = str(_HERE.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import _common  # noqa: E402
import export_state  # noqa: E402
import inject_tour  # noqa: E402
import make_briefings  # noqa: E402
import setup_scenario  # noqa: E402
from _common import FACILITATOR, PREPARED, PROJECT_ID, scenario  # noqa: E402

from supplyscore.core.ahp import (  # noqa: E402
    bipolar_to_saaty,
    compute_ud,
    run_ahp,
    score_6_to_9,
    ud_smoothed,
)
from supplyscore.domain.actions import (  # noqa: E402
    CATALOGUE_V1,
    contexte_pour,
)
from supplyscore.services.forecast import MIN_HISTORY_WEEKS, ForecastService  # noqa: E402
from supplyscore.services.interventions import InterventionJournal  # noqa: E402

#: Sous-bras jouables. ``control``/``predict`` sont le A/B du bras B (boucle OUVERTE, previsions scorables) ; ``act`` est le bras C - meme fiche que ``predict``, mais les personas AGISSENT et la verite terrain leur repond.
ARMS: tuple[str, ...] = ("control", "predict", "act")

#: Sous-bras ou la fiche expose l'analyse predictive au persona.
ARMS_AVEC_PREVISION: tuple[str, ...] = ("predict", "act")

#: Sous-bras ou les actions des personas sont reellement appliquees (bras C).
ARMS_AGISSANTS: tuple[str, ...] = ("act",)

#: Secondes dans une semaine - convertit ``delai_effet_weeks`` en date d'effet.
_SEMAINE_S: float = 7 * 24 * 3600.0

def _horizon_env(defaut: int) -> int:
    """Horizon de prevision, surchargeable par ``SUPPLYSCORE_HORIZON_PREVISION``.

    Canal de calibration : les balayages lancent le harnais en sous-processus,
    une variable d'environnement est donc le seul moyen de faire varier
    l'horizon sans editer le code entre deux mesures - ce qui les rendrait
    incomparables. Une valeur illisible ou hors [1, 26] retombe sur le defaut
    en le disant, plutot que d'introduire un horizon fantaisiste en silence.

    Args:
        defaut: horizon retenu en l'absence de surcharge valide.

    Returns:
        L'horizon en semaines.
    """
    brut = os.environ.get("SUPPLYSCORE_HORIZON_PREVISION")
    if brut is None:
        return defaut
    try:
        valeur = int(brut)
    except ValueError:
        print(f"  [horizon] valeur illisible {brut!r}, défaut {defaut} conservé")
        return defaut
    if not 1 <= valeur <= 26:
        print(f"  [horizon] {valeur} hors [1, 26], défaut {defaut} conservé")
        return defaut
    return valeur


#: Horizon de prevision montre/journalise, en semaines (defaut de U9). Balayable via ``SUPPLYSCORE_HORIZON_PREVISION``.
HORIZON_PREVISION: int = _horizon_env(4)

#: Budget de trajectoires Monte Carlo par defaut (compromis vitesse/precision pour un tour interactif ; U9 exige >= 20, un multiple de 20 est consomme).
N_DRAWS_DEFAUT: int = 500

#: Inertie du lissage de Ud, identique au protocole du bras A.
RHO_LISSAGE: float = 0.3

#: Valeurs admises de ``influence_prediction`` (mesure directe de l'effet).
INFLUENCES: tuple[str, ...] = (
    "aucune",
    "confirme",
    "revise_a_la_hausse",
    "revise_a_la_baisse",
)

#: Titre EXACT du bloc de traitement - seule difference entre les deux bras.
TITRE_PREDICTIF: str = "## ANALYSE PRÉDICTIVE (outil)"

#: Phrase servie quand la prevision est impossible (jamais un chiffre invente).
INDISPONIBLE: str = "analyse prédictive indisponible ce tour"

#: Paires AHP comparees, dans l'ordre fige de l'UI (contrat 2 du plan v7) - reutilise depuis ``inject_tour`` plutot que redeclare : une seule source.
_AHP_PAIRS = inject_tour._AHP_PAIRS

#: Dossier du pilote LLM (bras A) - reference des cartes de role. Absent d'une worktree fraiche : la verification ci-dessous est donc au mieux-effort.
PILOTE_BRAS_A: Path = _common.PROJECT_DIR / "analysis" / "llm_pilot_run"


class RefusExperienceError(Exception):
    """Refus explicite du harnais (sequence, couverture, reponse invalide).

    Portee par un message francais pret a afficher : :func:`main` le rend tel
    quel prefixe de " REFUS : " et sort en code 2, comme ``inject_tour.py``.
    """


# Etat d'experience


def state_path(db_dir: str) -> Path:
    """Chemin du fichier d'etat d'experience du sous-bras.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.

    Returns:
        Le chemin de ``experiment_state.json``.
    """
    return Path(db_dir) / "experiment_state.json"


def load_state(db_dir: str) -> dict | None:
    """Lit l'etat d'experience, ou None si le sous-bras n'est pas initialise.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.

    Returns:
        L'etat ``{arm, last_tour, pending_tour?, phase?}``, ou None.
    """
    path = state_path(db_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(db_dir: str, state: dict) -> None:
    """Ecrit l'etat d'experience du sous-bras.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.
        state: etat complet a persister.
    """
    state_path(db_dir).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _exiger_etat(db_dir: str, arm: str) -> dict:
    """Charge l'etat et verifie que le sous-bras demande est bien celui de la base.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.
        arm: sous-bras demande en ligne de commande.

    Returns:
        L'etat d'experience valide.

    Raises:
        RefusExperienceError: base non initialisee ou bras discordant - melanger
            deux bras dans une meme base ruinerait l'A/B.
    """
    state = load_state(db_dir)
    if state is None:
        raise RefusExperienceError(
            f"aucune expérience dans {db_dir} — lancer d'abord "
            f"« run_experiment.py init --arm {arm} --db-dir {db_dir} »."
        )
    if state["arm"] != arm:
        raise RefusExperienceError(
            f"cette base appartient au bras « {state['arm']} », or --arm "
            f"« {arm} » est demandé. Un db-dir par bras, jamais mélangés."
        )
    return state


def _exiger_out(state: dict, out: str | None) -> Path:
    """Resout ``--out`` en le verrouillant sur celui declare a ``prepare-tour``.

    Le dossier de sortie porte l'historique du bras (``results/<node>.jsonl``,
    d'ou sort le Ud lisse du tour precedent, et ``predictions_log.jsonl``).
    Changer de dossier en cours de route casserait SILENCIEUSEMENT la chaine
    de lissage - d'ou le verrou : ``prepare-tour`` enregistre le dossier, les
    etapes suivantes le reprennent ou doivent le designer a l'identique.

    Args:
        state: etat d'experience courant.
        out: valeur de ``--out``, ou None pour reprendre celle du tour ouvert.

    Returns:
        Le dossier de sortie du sous-bras.

    Raises:
        RefusExperienceError: aucun dossier connu, ou dossier discordant.
    """
    connu = state.get("out")
    if out is None:
        if connu is None:
            raise RefusExperienceError(
                "--out est requis : aucun dossier de sortie n'est enregistré "
                "pour ce bras (lancer d'abord prepare-tour)."
            )
        return Path(connu)
    resolu = str(Path(out).resolve())
    if connu is not None and resolu != connu:
        raise RefusExperienceError(
            f"--out « {resolu} » diffère du dossier de sortie du bras "
            f"« {connu} ». Un seul dossier par bras : en changer casserait la "
            "chaîne du Ud lissé et le journal de prédictions."
        )
    return Path(resolu)


def _exiger_sequence(state: dict, tour: int, phase_attendue: str | None) -> None:
    """Verifie que ``tour`` est bien le tour attendu dans la phase attendue.

    Discipline identique a ``inject_tour.py`` : pas de rejeu silencieux, pas
    de saut de tour, une seule phase possible a la fois.

    Args:
        state: etat d'experience courant.
        tour: tour demande.
        phase_attendue: phase requise (``"injecte"`` avant collecte,
            ``"collecte"`` avant cloture), ou None pour ouvrir un tour neuf.

    Raises:
        RefusExperienceError: tour hors sequence ou phase incompatible (francais).
    """
    if tour < 0 or tour > scenario.N_TOURS:
        raise RefusExperienceError(
            f"tour {tour} hors du scénario (tours 0 à {scenario.N_TOURS})."
        )
    en_cours = state.get("pending_tour")
    phase = state.get("phase")
    if phase_attendue is None:
        if en_cours is not None:
            raise RefusExperienceError(
                f"le tour {en_cours} est déjà ouvert (phase « {phase} ») — "
                f"le terminer avant d'en préparer un nouveau."
            )
        attendu = state["last_tour"] + 1
        if tour != attendu:
            raise RefusExperienceError(f"tour attendu = {attendu}, demandé = {tour}.")
        return
    if en_cours != tour:
        raise RefusExperienceError(
            f"aucun tour {tour} ouvert (tour ouvert : {en_cours}, phase « {phase} »)."
        )
    if phase != phase_attendue:
        raise RefusExperienceError(
            f"tour {tour} en phase « {phase} », or la phase « {phase_attendue} » "
            f"est requise pour cette étape."
        )


# Previsions (calculees dans LES DEUX bras)


@dataclass(frozen=True)
class _PointPrevision:
    """Point de prevision duck-type consomme par :class:`InsightService`.

    Reproduit la partie du contrat 6 (``PredictionPoint``, U11) reellement lue
    par ``InsightService`` - le harnais n'a pas d'artefact de modele entraine
    et travaille directement sur le rollout Monte Carlo (U9).

    Attributes:
        node_id: noeud concerne.
        node_name: nom lisible du noeud.
        proba_by_horizon: ``P(issue defavorable <= k semaines)`` par horizon k.
        delta_vs_last_week: variation brute de ``ur_local`` sur la derniere
            semaine ISO du noeud, None si l'historique est trop court.
        p_jalon_rate: probabilite de jalon rate a l'horizon de reference.
        p_impact_client: probabilite d'impact client a l'horizon de reference.
        impact_frac: fraction des noeuds du projet touches par le pire choc
            local de CE noeud (criticite systematique), None si indisponible.
        recommandation: TOUJOURS None en bras B - les personas ne peuvent
            agir sur rien, donc aucune action n'est recommandee (couture C).
    """

    node_id: str
    node_name: str
    proba_by_horizon: dict[int, float]
    delta_vs_last_week: float | None
    p_jalon_rate: float | None
    p_impact_client: float | None
    impact_frac: float | None
    recommandation: None = field(default=None)


def _pct(valeur: float | None, decimales: int = 1) -> str:
    """Formate une probabilite de [0, 1] en pourcentage francais.

    Args:
        valeur: probabilite a formater, ou None.
        decimales: nombre de decimales affichees.

    Returns:
        ``"27.3 %"``, ou ``"n/d"`` si ``valeur`` est None.
    """
    if valeur is None:
        return "n/d"
    return f"{valeur * 100:.{decimales}f} %"


def _impact_frac_par_noeud(service) -> dict[str, float]:
    """Fraction du projet impactee par le pire choc local, par noeud.

    Meme formule que ``PredictionService`` (``nb_impactes / n_noeuds_projet``)
    - c'est une propriete structurelle DU noeud considere, jamais l'etat d'un
    autre noeud (cf. la garantie anti-fuite du protocole d'experience).

    Args:
        service: facade SupplyScore ouverte sur la base du sous-bras.

    Returns:
        ``{node_id: fraction}`` ; dictionnaire vide si la criticite echoue.
    """
    from supplyscore.services.criticite import ServiceCriticite

    n_noeuds = len(service.repo.nodes_by_project(PROJECT_ID))
    if not n_noeuds:
        return {}
    try:
        points = ServiceCriticite(service).indice_criticite(PROJECT_ID)
    except Exception as exc:  # criticite best-effort : l'insight reste produit
        print(f"  [criticité ÉCHEC] {type(exc).__name__}: {exc}")
        return {}
    return {p.node_id: p.nb_impactes / n_noeuds for p in points}


def previsions_du_tour(
    service, n_draws: int, seed: int
) -> tuple[dict[str, dict], str | None]:
    """Rollout Monte Carlo du projet + lecture en clair, noeud par noeud.

    Enchaine ``ForecastService.rollout`` (U9), la criticite systematique et
    ``InsightService`` (U12, 100 % regles, aucun LLM). Aucune ecriture en base.

    Args:
        service: facade SupplyScore ouverte sur la base du sous-bras.
        n_draws: budget de trajectoires du rollout.
        seed: graine du rollout (determinisme : meme graine, memes chiffres).

    Returns:
        ``(par_noeud, erreur)`` - ``par_noeud`` associe a chaque noeud simule
        ``{p_issue, ic80_h4, se_mc, spread, p_jalon_rate, p_impact_client,
        insight}`` ; ``erreur`` est None en cas de succes, sinon le message
        francais expliquant pourquoi aucune prevision n'est disponible (et
        ``par_noeud`` est alors vide).
    """
    from supplyscore.services.insights import InsightService

    forecast = ForecastService(service)
    try:
        resultat = forecast.rollout(
            PROJECT_ID, horizon_weeks=HORIZON_PREVISION, n_draws=n_draws, seed=seed
        )
    except Exception as exc:  # prevision best-effort : jamais un chiffre invente
        return {}, f"{type(exc).__name__}: {exc}"

    fractions = _impact_frac_par_noeud(service)
    par_noeud: dict[str, dict] = {}
    for node_id, par_horizon in resultat.previsions.items():
        node = service.repo.get_node(node_id)
        reference = par_horizon[HORIZON_PREVISION]
        # Reutilise le regroupement hebdomadaire CANONIQUE du service de prevision (dernier etat de chaque semaine ISO) au lieu de le rederiver.
        _, valeurs = forecast._serie_hebdo(node_id)
        delta = float(valeurs[-1] - valeurs[-2]) if valeurs.size >= 2 else None
        point = _PointPrevision(
            node_id=node_id,
            node_name=node.name if node is not None else node_id,
            proba_by_horizon={k: p.p_issue for k, p in par_horizon.items()},
            delta_vs_last_week=delta,
            p_jalon_rate=reference.p_jalon_rate,
            p_impact_client=reference.p_impact_client,
            impact_frac=fractions.get(node_id),
        )
        try:
            insights = InsightService(service).insights(PROJECT_ID, [point])
            message = insights[0].message if insights else ""
        except Exception as exc:  # lecture en clair best-effort : chiffres conserves
            print(f"  [insight ÉCHEC {node_id}] {type(exc).__name__}: {exc}")
            message = ""
        par_noeud[node_id] = {
            "p_issue": {k: p.p_issue for k, p in par_horizon.items()},
            "ic80_h4": (reference.ic80.bas, reference.ic80.haut),
            "se_mc": reference.se_mc,
            "spread": reference.spread,
            "p_jalon_rate": reference.p_jalon_rate,
            "p_impact_client": reference.p_impact_client,
            # Journalisees pour la couche de calibration (contrat 5) : l'artefact EMOS attend " ur_local " et " d1_ur_local " parmi ses features, et les imputait faute de les trouver dans le journal. Elles sont calculees ici de toute facon - ne pas les ecrire revenait a faire travailler la calibration sur une information partielle.
            "ur_local": float(valeurs[-1]) if valeurs.size else None,
            "d1_ur_local": delta,
            "insight": message,
        }
    return par_noeud, None


def journaliser_previsions(
    out: Path,
    arm: str,
    tour: int,
    par_noeud: dict[str, dict],
    erreur: str | None,
    n_draws: int,
    seed: int,
) -> Path:
    """Ecrit une ligne de ``predictions_log.jsonl`` par (tour, noeud).

    C'EST LE COEUR SCIENTIFIQUE DU DISPOSITIF : le bras ``control`` journalise
    EXACTEMENT les memes predictions que le bras ``predict``, mais avec
    ``montre_au_persona = false``. Les deux bras produisent donc des
    predictions prospectives comparables ; seule leur visibilite differe.

    Idempotent : les lignes du meme tour deja presentes sont remplacees, pas
    dupliquees (une reprise apres incident ne fausse pas le journal).

    Args:
        out: dossier de sortie du sous-bras.
        arm: sous-bras (``control`` ou ``predict``).
        tour: tour journalise.
        par_noeud: previsions par noeud (vide si ``erreur`` est renseignee).
        erreur: message d'echec de la prevision, ou None.
        n_draws: budget de trajectoires effectivement demande.
        seed: graine du rollout.

    Returns:
        Le chemin du journal ecrit.
    """
    chemin = out / "predictions_log.jsonl"
    anciennes = []
    if chemin.exists():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            if not ligne.strip():
                continue
            if json.loads(ligne).get("tour") != tour:
                anciennes.append(ligne)

    montre = arm in ARMS_AVEC_PREVISION and erreur is None
    nouvelles: list[str] = []
    for spec in scenario.NODES:
        node_id = spec["id"]
        donnees = par_noeud.get(node_id)
        entree: dict = {"arm": arm, "tour": tour, "node_id": node_id}
        for k in range(1, HORIZON_PREVISION + 1):
            entree[f"p_issue_h{k}"] = donnees["p_issue"][k] if donnees else None
        entree["ic80_h4"] = list(donnees["ic80_h4"]) if donnees else None
        entree["se_mc"] = donnees["se_mc"] if donnees else None
        entree["spread"] = donnees["spread"] if donnees else None
        entree["p_jalon_rate"] = donnees["p_jalon_rate"] if donnees else None
        entree["p_impact_client"] = donnees["p_impact_client"] if donnees else None
        entree["ur_local"] = donnees["ur_local"] if donnees else None
        entree["d1_ur_local"] = donnees["d1_ur_local"] if donnees else None
        entree["montre_au_persona"] = montre and donnees is not None
        entree["n_draws"] = n_draws
        entree["seed"] = seed
        if erreur is not None:
            entree["erreur"] = erreur
        nouvelles.append(json.dumps(entree, ensure_ascii=False))

    chemin.write_text("\n".join([*anciennes, *nouvelles]) + "\n", encoding="utf-8")
    return chemin


def section_predictive(donnees: dict | None) -> str:
    """Bloc " ANALYSE PREDICTIVE (outil) " d'une fiche du bras ``predict``.

    SEUL point de divergence entre les deux sous-bras. Ne contient QUE des
    chiffres calcules sur le noeud de la fiche ; aucun nombre n'est invente -
    en l'absence de prevision exploitable, la section le dit explicitement.

    Args:
        donnees: previsions du noeud (cf. :func:`previsions_du_tour`), ou None
            si la prevision a echoue ou si l'historique est insuffisant.

    Returns:
        Le texte Markdown de la section (sans saut de ligne final).
    """
    lignes = [TITRE_PREDICTIF, ""]
    if donnees is None:
        lignes += [
            f"**{INDISPONIBLE.capitalize()}** — l'outil n'a pas assez "
            "d'historique sur votre périmètre pour produire une estimation "
            "fiable. Il n'y a donc rien à en tirer ce tour-ci : déclarez votre "
            "perception comme d'habitude.",
            "",
        ]
    else:
        bas, haut = donnees["ic80_h4"]
        lignes += [
            "*Estimation produite par l'outil à partir de VOS SEULES données "
            "historiques (tours 0 à aujourd'hui). Ce n'est ni une consigne ni "
            "« la bonne réponse » : c'est un élément de plus, que vous restez "
            "libre de juger pertinent ou non.*",
            "",
            "**Risque d'issue défavorable sur votre périmètre** — c'est-à-dire "
            "rater un de vos jalons OU subir un incident majeur :",
            "",
            "| D'ici | Probabilité |",
            "|---|---|",
        ]
        for k in range(1, HORIZON_PREVISION + 1):
            libelle = "1 semaine" if k == 1 else f"{k} semaines"
            lignes.append(f"| {libelle} | {_pct(donnees['p_issue'][k])} |")
        lignes += [
            "",
            f"- **Fourchette à 4 semaines (8 chances sur 10)** : "
            f"{_pct(bas)} à {_pct(haut)}.",
            f"- **Probabilité de rater votre jalon d'ici 4 semaines** : "
            f"{_pct(donnees['p_jalon_rate'])}.",
            f"- **Probabilité que le client final en ressente l'effet d'ici "
            f"4 semaines** : {_pct(donnees['p_impact_client'])}.",
            "",
        ]
        if donnees["insight"]:
            lignes += ["**Lecture de l'outil** : " + donnees["insight"], ""]
    lignes += [
        "### Ce que nous vous demandons en plus, ce tour-ci",
        "",
        "Dans votre ligne de `results.jsonl`, renseignez "
        "`influence_prediction` avec EXACTEMENT l'une de ces quatre valeurs. "
        "Elles se valent toutes : on constate, on ne juge pas.",
        "",
        '- `"aucune"` — pas d\'analyse, ou elle n\'a rien changé ;',
        '- `"confirme"` — elle confirme ce que je percevais déjà ;',
        '- `"revise_a_la_hausse"` — elle m\'a fait monter mon niveau d\'urgence ;',
        '- `"revise_a_la_baisse"` — elle m\'a fait baisser mon niveau d\'urgence.',
        "",
        "Et ajoutez dans votre `note` une phrase disant SI et COMMENT cette "
        "analyse a changé votre perception ce tour-ci — y compris pour dire "
        "qu'elle ne l'a pas changée.",
    ]
    return "\n".join(lignes)


# Fiches


def _ecrire_fiche(out: Path, node_id: str, tour: int, texte: str) -> Path:
    """Ecrit la fiche du noeud et la recopie dans son bac a sable s'il existe.

    Args:
        out: dossier de sortie du sous-bras.
        node_id: noeud concerne.
        tour: tour de la fiche.
        texte: contenu Markdown complet de la fiche.

    Returns:
        Le chemin de la fiche de reference (``OUT/tour_NN/<node>.md``).
    """
    dossier = out / f"tour_{tour:02d}"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{node_id}.md"
    chemin.write_text(texte, encoding="utf-8")
    tours = out / f"sandbox_{node_id}" / "tours"
    if tours.parent.is_dir():
        tours.mkdir(parents=True, exist_ok=True)
        (tours / f"tour_{tour:02d}.md").write_text(texte, encoding="utf-8")
    return chemin


# Reponses des personas


def _entier(valeur: object, contexte: str, bas: int, haut: int) -> int:
    """Valide un entier borne venant d'un fichier de reponses.

    Args:
        valeur: valeur brute lue dans le JSON.
        contexte: description du champ, pour le message d'erreur.
        bas: borne inferieure incluse.
        haut: borne superieure incluse.

    Returns:
        L'entier valide.

    Raises:
        RefusExperienceError: valeur non entiere ou hors bornes (francais).
    """
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise RefusExperienceError(f"{contexte} doit être un entier, reçu {valeur!r}.")
    if not bas <= valeur <= haut:
        raise RefusExperienceError(f"{contexte} doit être dans [{bas}, {haut}], reçu {valeur}.")
    return valeur


def lire_answers(chemin: Path, arm: str) -> dict[str, dict]:
    """Lit et valide le fichier de reponses d'un tour (une ligne JSON par noeud).

    Cles attendues : ``node_id``, ``bipolar`` (6 entiers de -8 a 8),
    ``scores_ui`` (4 entiers de 1 a 6), ``note``, ``attempts`` (optionnel,
    1 ou 2) et, en bras ``predict`` UNIQUEMENT, ``influence_prediction``.
    Toute autre cle est ignoree : le coordinateur peut donc recopier telle
    quelle la ligne ``results.jsonl`` ecrite par le persona en y ajoutant
    ``node_id``.

    Args:
        chemin: fichier de reponses du tour.
        arm: sous-bras courant (controle la presence d'``influence_prediction``).

    Returns:
        ``{node_id: reponse validee}`` couvrant EXACTEMENT les 8 noeuds.

    Raises:
        RefusExperienceError: fichier absent/malforme, couverture incomplete,
            doublon, noeud inconnu ou champ invalide (messages en francais).
    """
    if not chemin.is_file():
        raise RefusExperienceError(f"fichier de réponses introuvable : {chemin}")
    attendus = {spec["id"] for spec in scenario.NODES}
    reponses: dict[str, dict] = {}
    for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
        if not ligne.strip():
            continue
        try:
            brut = json.loads(ligne)
        except json.JSONDecodeError as exc:
            raise RefusExperienceError(
                f"{chemin}, ligne {numero} : JSON invalide ({exc})."
            ) from exc
        node_id = brut.get("node_id")
        if node_id not in attendus:
            raise RefusExperienceError(
                f"{chemin}, ligne {numero} : node_id {node_id!r} inconnu "
                f"(attendus : {', '.join(sorted(attendus))})."
            )
        if node_id in reponses:
            raise RefusExperienceError(f"{chemin} : deux réponses pour le nœud {node_id!r}.")

        bipolar = brut.get("bipolar")
        scores_ui = brut.get("scores_ui")
        if not isinstance(bipolar, list) or len(bipolar) != 6:
            raise RefusExperienceError(f"{node_id} : « bipolar » doit compter 6 valeurs.")
        if not isinstance(scores_ui, list) or len(scores_ui) != 4:
            raise RefusExperienceError(f"{node_id} : « scores_ui » doit compter 4 valeurs.")
        bipolar = [_entier(v, f"{node_id} : bipolar[{i}]", -8, 8) for i, v in enumerate(bipolar)]
        scores_ui = [
            _entier(v, f"{node_id} : scores_ui[{i}]", 1, 6) for i, v in enumerate(scores_ui)
        ]
        attempts = _entier(brut.get("attempts", 1), f"{node_id} : attempts", 1, 2)

        action_id = brut.get("action_id")
        if arm in ARMS_AGISSANTS:
            if action_id not in CATALOGUE_V1:
                raise RefusExperienceError(
                    f"{node_id} : « action_id » est obligatoire en bras act et doit "
                    f"valoir l'une de {', '.join(sorted(CATALOGUE_V1))} "
                    f"(reçu {action_id!r})."
                )
            # Controle ICI, en phase de validation, et non au moment d'agir : ``InterventionJournal.record`` refuse un objectif vide par un ValueError, qui surviendrait en phase d'ecriture - apres que les premiers noeuds ont deja ete soumis, laissant le tour a moitie declare. C'est exactement ce que l'atomicite en deux phases promet d'eviter.
            if action_id != "ne_rien_faire" and not str(
                brut.get("objectif_action", "")
            ).strip():
                raise RefusExperienceError(
                    f"{node_id} : « objectif_action » est obligatoire en bras act "
                    f"dès que action_id vaut autre chose que « ne_rien_faire » "
                    f"(reçu vide ou blanc, action {action_id!r})."
                )
        elif action_id is not None:
            raise RefusExperienceError(
                f"{node_id} : « action_id » présent hors bras act — ce persona n'a "
                "aucun levier d'action ; vérifier le bac à sable servi."
            )

        influence = brut.get("influence_prediction")
        if arm in ARMS_AVEC_PREVISION:
            if influence not in INFLUENCES:
                raise RefusExperienceError(
                    f"{node_id} : « influence_prediction » est obligatoire en bras "
                    f"predict et doit valoir l'une de {', '.join(INFLUENCES)} "
                    f"(reçu {influence!r})."
                )
        elif influence is not None:
            raise RefusExperienceError(
                f"{node_id} : « influence_prediction » présent en bras control — "
                "ce persona n'a vu aucune prédiction ; vérifier le bac à sable servi."
            )

        reponses[node_id] = {
            "node_id": node_id,
            "bipolar": bipolar,
            "scores_ui": scores_ui,
            "attempts": attempts,
            "note": str(brut.get("note", "")),
            "influence_prediction": influence if arm in ARMS_AVEC_PREVISION else None,
            "action_id": action_id,
            "objectif_action": str(brut.get("objectif_action", "")),
        }

    manquants = attendus - set(reponses)
    if manquants:
        raise RefusExperienceError(
            f"couverture incomplète : {len(reponses)}/{len(attendus)} nœuds — "
            f"manque {', '.join(sorted(manquants))}."
        )
    return reponses


def _dernier_resultat(chemin: Path) -> dict | None:
    """Derniere ligne de resultat d'un noeud (pour le Ud lisse et le report).

    Args:
        chemin: fichier ``OUT/results/<node_id>.jsonl``.

    Returns:
        Le dernier objet JSON du fichier, ou None si absent/vide.
    """
    if not chemin.is_file():
        return None
    lignes = [ligne for ligne in chemin.read_text(encoding="utf-8").splitlines() if ligne.strip()]
    return json.loads(lignes[-1]) if lignes else None


def _ecrire_resultat(chemin: Path, ligne: dict) -> None:
    """Ajoute une ligne de resultat, en remplacant celle du meme tour si besoin.

    Args:
        chemin: fichier ``OUT/results/<node_id>.jsonl``.
        ligne: ligne de resultat au schema du bras A.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    gardees: list[str] = []
    if chemin.exists():
        for existante in chemin.read_text(encoding="utf-8").splitlines():
            if existante.strip() and json.loads(existante).get("tour") != ligne["tour"]:
                gardees.append(existante)
    gardees.append(json.dumps(ligne, ensure_ascii=False))
    chemin.write_text("\n".join(gardees) + "\n", encoding="utf-8")


# Couture bras C (NON IMPLEMENTEE)


def appliquer_actions_bras_c(service, node_id: str, tour: int, reponse: dict) -> None:
    """Applique l'action choisie par le persona - BRAS C, boucle FERMEE.

    Inerte en ``control`` et ``predict`` (le champ ``action_id`` y est absent
    ou vaut ``ne_rien_faire``) : ces deux sous-bras restent en boucle ouverte,
    donc leurs previsions restent scorables contre le pack gele.

    En bras ``act``, la chaine complete documentee par le stub d'origine :

    1. lire ``action_id`` dans la reponse du persona ;
    2. le resoudre dans ``CATALOGUE_V1`` et verifier sa precondition sur le
       contexte courant du noeud (``contexte_pour``) ;
    3. l'appliquer via ``ActionSpec.apply_to_project``, qui n'ecrit que par
       le ``MutationService`` (validation + audit) ;
    4. journaliser l'intervention (``InterventionJournal.record`` puis
       ``marquer_executee``) - c'est ce journal qui alimente les effets
       causaux (U17) et le moteur de decision (U18).

    Une action dont la precondition est fausse est REFUSEE et tracee, jamais
    appliquee en silence : le persona a le droit de se tromper de levier, mais
    la chaine ne doit pas bouger pour autant.

    Attention (validite de l'experience) : des que cette fonction agit, la
    verite terrain depend des personas. Les previsions du bras ``act`` ne sont
    plus comparables a celles de ``control``/``predict`` sans appariement
    explicite - une rupture EVITEE grace a l'alerte fait passer une bonne
    prevision pour fausse (prophetie auto-refutante). Le bras C se juge sur
    l'ETAT FINAL de la chaine, pas sur la precision des previsions.

    Args:
        service: facade SupplyScore ouverte sur la base du sous-bras.
        node_id: noeud declarant.
        tour: tour courant.
        reponse: reponse validee du persona pour ce tour.

    Returns:
        Le dictionnaire de trace de l'action, ou None si rien n'a ete tente.
    """
    action_id = reponse.get("action_id")
    if not action_id or action_id == "ne_rien_faire":
        return None

    trace = {"tour": tour, "node_id": node_id, "action_id": action_id}
    spec = CATALOGUE_V1.get(action_id)
    if spec is None:
        trace["statut"] = "inconnue"
        print(f"  [action] {node_id} : action inconnue {action_id!r} — ignorée")
        return trace

    contexte = contexte_pour(service, node_id)
    if not spec.preconditions(contexte):
        trace["statut"] = "precondition_fausse"
        print(f"  [action] {node_id} : {action_id} refusée (précondition fausse)")
        return trace

    journal = InterventionJournal(service)
    # L'ouverture PRECEDE l'application : ``record`` capture ``etat_avant``, qui n'a de sens que mesure avant que l'action ne deplace quoi que ce soit.
    intervention = journal.record(
        node_id=node_id,
        action_id=action_id,
        acteur=_common.OPERATORS[node_id],
        objectif_operationnel=reponse.get("objectif_action", "")[:200],
        notes=f"bras act — tour {tour}",
    )
    try:
        spec.apply_to_project(service, node_id)
    except Exception as exc:  # noqa: BLE001 - on referme la ligne, quelle que soit la cause
        # L'application a echoue APRES l'ouverture de la ligne. Sans ce rattrapage, l'intervention resterait ``executee=None`` sans date d'effet : U17 (effets causaux) et U18 (moteur de decision) la liraient comme une intervention decidee et non tranchee, pour une action qui n'a jamais touche la chaine. On la referme explicitement en " ne sera pas executee ", ce qui est exactement la verite.
        journal.marquer_executee(
            intervention.id, node_id=node_id, executee=False, date_effet_ts=None
        )
        trace["statut"] = "echec_application"
        trace["erreur"] = f"{type(exc).__name__}: {exc}"
        trace["intervention_id"] = intervention.id
        print(f"  [action] {node_id} : {action_id} ÉCHOUE à l'application — {exc}")
        return trace
    # L'action est appliquee immediatement, mais son EFFET n'est complet qu'apres ``delai_effet_weeks`` (mode de la triangulaire) : c'est cette date qui ancre la fenetre d'observation du resultat operationnel, donc l'estimateur causal.
    delai_mode_weeks = spec.delai_effet_weeks[1]
    journal.marquer_executee(
        intervention.id,
        node_id=node_id,
        executee=True,
        date_effet_ts=intervention.decidee_ts + delai_mode_weeks * _SEMAINE_S,
    )
    trace["statut"] = "appliquee"
    trace["date_effet_ts"] = intervention.decidee_ts + delai_mode_weeks * _SEMAINE_S
    trace["intervention_id"] = intervention.id
    print(f"  [action] {node_id} : {action_id} APPLIQUÉE ({spec.libelle})")
    return trace


#: Cle supplementaire de la ligne de resultat, bras ``predict`` uniquement.
_CLE_INFLUENCE: str = (
    ',\n   "influence_prediction": '
    '"aucune|confirme|revise_a_la_hausse|revise_a_la_baisse"'
)

#: Section d'instructions propre au bras ``predict`` (le traitement mesure).
_SECTION_PREDICT: str = """## L'analyse prédictive de l'outil

À partir du tour 4, votre fiche se termine par une section
« ANALYSE PRÉDICTIVE (outil) ». Elle est produite par l'outil à partir de VOS
SEULES données historiques : probabilité d'issue défavorable d'ici 1, 2, 3 et
4 semaines, fourchette d'incertitude, probabilité de rater votre jalon,
probabilité d'impact chez le client final, et une lecture en clair. Certains
tours peuvent porter la mention « analyse prédictive indisponible ce tour » :
c'est normal, il n'y a alors rien à en tirer.

Cette analyse est une information d'OUTIL, jamais une consigne : elle ne vous
dit pas quoi déclarer et elle n'est pas « la bonne réponse ». Elle peut se
tromper, porter sur un aspect qui ne préoccupe pas votre personnage, ou ne
faire que redire ce qu'il savait déjà. Vous restez libre de la suivre, de la
nuancer ou de l'écarter — comme dans tout le reste du protocole, il n'y a pas
de bonne réponse : c'est le jugement du personnage qui tranche.

À CHAQUE tour (y compris avant le tour 4 et quand l'analyse est
indisponible), votre ligne de `results.jsonl` porte donc la clé
`"influence_prediction"`. Elle CONSTATE simplement ce qui s'est passé dans la
tête du personnage : les quatre valeurs se valent, aucune n'est meilleure ni
plus attendue qu'une autre.

- `"aucune"` — pas d'analyse ce tour, ou elle n'a rien changé ;
- `"confirme"` — elle confirme ce que je percevais déjà, sans me faire bouger ;
- `"revise_a_la_hausse"` — elle m'a fait monter mon niveau d'urgence ;
- `"revise_a_la_baisse"` — elle m'a fait baisser mon niveau d'urgence.

Votre `note` doit en outre contenir une phrase disant SI et COMMENT cette
analyse a changé votre perception ce tour-ci — y compris pour dire qu'elle ne
l'a pas changée, ce qui est une réponse aussi valable que les autres.

"""


#: Cles supplementaires de la ligne de resultat, bras ``act`` uniquement.
_CLE_ACTION: str = (
    ',\n   "action_id": "<id du catalogue>"'
    ',\n   "objectif_action": "<en une phrase, ce que vous cherchez à obtenir>"'
)

#: Section d'instructions propre au bras ``act`` (bras C - boucle fermee).
_SECTION_ACTIONS: str = """## Vos leviers d'action

Ce tour-ci, vous ne faites pas que déclarer : vous DÉCIDEZ. L'action que vous
choisissez est réellement appliquée à la chaîne, et la suite de la campagne en
tiendra compte — ce n'est pas un questionnaire, c'est votre semaine de travail.

Choisissez UNE action par tour, celle que votre personnage prendrait vraiment,
et reportez son identifiant dans `"action_id"` :

- `"ne_rien_faire"` — la situation ne justifie pas d'engager quoi que ce soit.
  C'est un choix légitime et souvent le bon : n'agissez pas pour agir.
- `"promouvoir_arc_secours"` — basculer sur un fournisseur de secours. Coûteux
  et long à porter ses fruits, mais change vraiment votre exposition amont.
- `"replanifier_jalon"` — décaler votre jalon actif de deux semaines. Vous
  achetez du temps, vous le payez en engagement rompu vis-à-vis de l'aval.
- `"expedition_express"` — réduire votre lead time de 30 % en payant le transport
  rapide. Effet quasi immédiat, sans rien régler en amont.
- `"boost_capacite"` — renforcer la capacité (débit +30 %, volume +20 %). Utile
  si le goulot est chez vous, inutile si vous attendez un fournisseur.
- `"revue_declaration"` — remettre à plat votre propre évaluation. Aucun effet
  sur le terrain, mais remet votre déclaration d'aplomb.

Une action dont les conditions ne sont pas réunies chez vous sera REFUSÉE et
tracée comme telle : ce n'est pas grave, c'est une information. Choisissez sur
ce que votre personnage sait, pas sur ce qui « devrait marcher ».

`"objectif_action"` dit en une phrase ce que vous cherchez à obtenir. Votre
`note` doit expliquer pourquoi CETTE action plutôt qu'une autre.

"""

# Sous-commandes


def cmd_init(args: argparse.Namespace) -> int:
    """Cree la base d'un sous-bras et son etat d'experience.

    Args:
        args: arguments de la sous-commande (``arm``, ``db_dir``).

    Returns:
        Code de sortie du processus (0 = succes, 2 = refus).
    """
    if load_state(args.db_dir) is not None:
        raise RefusExperienceError(
            f"{state_path(args.db_dir)} existe déjà — ce db-dir porte déjà une "
            "expérience. Utiliser un dossier neuf (une base par bras)."
        )
    code = setup_scenario.main(["--db-dir", args.db_dir])
    if code != 0:
        return code
    save_state(args.db_dir, {"arm": args.arm, "last_tour": -1})
    print(f"Bras « {args.arm} » initialisé dans {args.db_dir}.")
    print(f"Prochaine étape : prepare-tour --tour 0 --arm {args.arm} --db-dir {args.db_dir}")
    return 0


def cmd_prepare_tour(args: argparse.Namespace) -> int:
    """Injecte le tour N (pack gele) puis produit les 8 fiches et le journal.

    Sequence : decroissance hebdomadaire (N > 0), injection KPIs/jalons/
    evenements depuis ``data/prepared`` (LECTURE SEULE), prevision (des
    N >= MIN_HISTORY_WEEKS, dans LES DEUX bras), journalisation, puis fiches -
    la section predictive n'etant ajoutee qu'en bras ``predict``.

    Args:
        args: arguments de la sous-commande (``tour``, ``arm``, ``db_dir``,
            ``out``, ``n_draws``, ``seed``).

    Returns:
        Code de sortie du processus.
    """
    state = _exiger_etat(args.db_dir, args.arm)
    _exiger_sequence(state, args.tour, phase_attendue=None)
    out = _exiger_out(state, args.out)
    out.mkdir(parents=True, exist_ok=True)

    service = _common.open_service(args.db_dir)
    try:
        print(f"Tour {args.tour} ({args.arm}) — injection :")
        if args.tour > 0:
            from supplyscore.services.events import EventEngine

            engine = EventEngine(service)
            eroded = sum(
                len(engine.apply_weekly_decay(spec["id"], operator_id=FACILITATOR))
                for spec in scenario.NODES
            )
            print(f"  [décroissance] {eroded} KPI(s) érodé(s)")
        kpi_rows, events, milestones = inject_tour._load_tour_files(args.tour, PREPARED)
        print(f"  [kpi] {inject_tour._inject_kpis(service, kpi_rows)} champ(s) modifié(s)")
        print(f"  [jalons] {inject_tour._inject_milestones(service, milestones)} champ(s)")
        inject_tour._inject_events(service, events)

        # Reevaluation EXPLICITE avant de prevoir. Sans elle, l'etat d'urgence persiste de la semaine courante ne refleterait les KPIs/jalons du tour QUE sur les tours porteurs d'un evenement (``EventEngine.apply`` est le seul des trois injecteurs a reevaluer) : la prevision serait " fraiche " aux tours 3, 5, 6, 7... et " perimee " aux tours 4, 8, 9, 11, 15, 17, 18, qui n'ont aucun evenement. Un traitement inegal d'un tour a l'autre ruinerait la comparabilite des predictions.
        service.evaluate_all(persist=True)

        par_noeud: dict[str, dict] = {}
        if args.tour >= MIN_HISTORY_WEEKS:
            par_noeud, erreur = previsions_du_tour(service, args.n_draws, args.seed)
            if erreur is not None:
                print(f"  [prévision INDISPONIBLE] {erreur}")
            journal = journaliser_previsions(
                out, args.arm, args.tour, par_noeud, erreur, args.n_draws, args.seed
            )
            montre = args.arm in ARMS_AVEC_PREVISION and erreur is None
            print(f"  [prévision] {len(par_noeud)} nœud(s) -> {journal} (montrée : {montre})")
        else:
            print(
                f"  [prévision] non calculée avant le tour {MIN_HISTORY_WEEKS} "
                f"(historique hebdomadaire minimal)"
            )

        for spec in scenario.NODES:
            node_id = spec["id"]
            texte = make_briefings.briefing(node_id, args.tour)
            if args.arm in ARMS_AVEC_PREVISION and args.tour >= MIN_HISTORY_WEEKS:
                texte += "\n\n" + section_predictive(par_noeud.get(node_id)) + "\n"
            print(f"  [fiche] {_ecrire_fiche(out, node_id, args.tour, texte)}")
    finally:
        service.close()

    state["pending_tour"] = args.tour
    state["phase"] = "injecte"
    state["out"] = str(out)  # verrou : collect-tour et close-tour s'y raccrochent
    save_state(args.db_dir, state)
    print(
        f"Tour {args.tour} injecté. Fenêtre de réponse des personas ouverte — "
        f"clore avec collect-tour puis close-tour."
    )
    return 0


def cmd_collect_tour(args: argparse.Namespace) -> int:
    """Valide les 8 declarations du tour N, les soumet et ecrit les resultats.

    Les reponses sont d'abord TOUTES validees et converties (aucune ecriture),
    puis soumises : un fichier invalide ne laisse jamais un tour a moitie
    declare. En cas d'AHP incoherent (CR >= 0.10), la regle de report du
    protocole s'applique - la declaration du tour precedent est reconduite et
    consignee (``cr_echec``).

    Args:
        args: arguments de la sous-commande (``tour``, ``arm``, ``db_dir``,
            ``answers``, ``out``).

    Returns:
        Code de sortie du processus.
    """
    state = _exiger_etat(args.db_dir, args.arm)
    _exiger_sequence(state, args.tour, phase_attendue="injecte")
    answers = Path(args.answers)
    out = _exiger_out(state, args.out)
    reponses = lire_answers(answers, args.arm)

    from supplyscore.services.orchestrator import SupplyScoreService

    # Phase 1 - conversion et controle de coherence, SANS aucune ecriture.
    prepares: list[dict] = []
    for spec in scenario.NODES:
        node_id = spec["id"]
        reponse = reponses[node_id]
        comparisons = {
            pair: bipolar_to_saaty(v)
            for pair, v in zip(_AHP_PAIRS, reponse["bipolar"], strict=True)
        }
        criteres = [score_6_to_9(float(s)) for s in reponse["scores_ui"]]
        resultat = run_ahp(comparisons, n=4)
        prepares.append(
            {
                "reponse": reponse,
                "comparisons": comparisons,
                "criteres": criteres,
                "resultat": resultat,
            }
        )

    service = _common.open_service(args.db_dir)
    try:
        for prepare in prepares:
            reponse = prepare["reponse"]
            node_id = reponse["node_id"]
            resultat = prepare["resultat"]
            comparisons = prepare["comparisons"]
            criteres = prepare["criteres"]
            precedent = _dernier_resultat(out / "results" / f"{node_id}.jsonl")

            if resultat.is_consistent:
                notes = f"tour {args.tour} — {args.arm}"
                ud_raw = compute_ud(resultat.weights, criteres)
                ud_lisse = ud_smoothed(
                    precedent.get("ud_smoothed") if precedent else None, ud_raw, RHO_LISSAGE
                )
                cr_echec = False
            else:
                cr_echec = True
                ud_raw = precedent.get("ud_raw") if precedent else None
                ud_lisse = precedent.get("ud_smoothed") if precedent else None
                repli = service.client_db(node_id).latest_assessment(node_id)
                if repli is not None:
                    comparisons = repli.comparisons
                    criteres = repli.criteria_scores
                    notes = (
                        f"tour {args.tour} — {args.arm} — report (CR = "
                        f"{resultat.consistency_ratio:.3f} >= 0.10) : déclaration "
                        "du tour précédent reconduite"
                    )
                else:
                    comparisons = dict.fromkeys(_AHP_PAIRS, 1.0)
                    criteres = [score_6_to_9(3.0)] * 4
                    notes = (
                        f"tour {args.tour} — {args.arm} — repli neutre (CR = "
                        f"{resultat.consistency_ratio:.3f} >= 0.10, aucun historique)"
                    )
                print(f"  [cr_echec] {node_id} : {notes}")

            service.submit_assessment(
                SupplyScoreService.build_assessment(
                    node_id=node_id,
                    project_id=PROJECT_ID,
                    operator_id=_common.OPERATORS[node_id],
                    comparisons=comparisons,
                    criteria_scores=criteres,
                    notes=notes,
                )
            )
            # Couture bras C : inerte hors bras " act ".
            trace_action = (
                appliquer_actions_bras_c(service, node_id, args.tour, reponse)
                if args.arm in ARMS_AGISSANTS
                else None
            )

            ligne: dict = {
                "tour": args.tour,
                "bipolar": reponse["bipolar"],
                "scores_ui": reponse["scores_ui"],
                "weights": resultat.weights.tolist(),
                "lambda_max": resultat.lambda_max,
                "ci": resultat.consistency_index,
                "cr": resultat.consistency_ratio,
                "is_consistent": resultat.is_consistent,
                "attempts": reponse["attempts"],
                "cr_echec": cr_echec,
                "ud_raw": ud_raw,
                "ud_smoothed": ud_lisse,
                "note": reponse["note"],
            }
            if args.arm in ARMS_AVEC_PREVISION:
                ligne["influence_prediction"] = reponse["influence_prediction"]
            if args.arm in ARMS_AGISSANTS:
                ligne["action_id"] = reponse["action_id"]
                ligne["action_trace"] = trace_action
            _ecrire_resultat(out / "results" / f"{node_id}.jsonl", ligne)

        a_jour, total = _couverture(service)
        print(f"Tour {args.tour} collecté : {len(prepares)}/8 déclarations, "
              f"couverture hebdo {a_jour}/{total}.")
    finally:
        service.close()

    state["phase"] = "collecte"
    save_state(args.db_dir, state)
    print(f"Clore le tour avec : close-tour --tour {args.tour} --arm {args.arm}")
    return 0


def cmd_close_tour(args: argparse.Namespace) -> int:
    """Clot le tour N : avance d'une semaine et ecrit le snapshot.

    Args:
        args: arguments de la sous-commande (``tour``, ``arm``, ``db_dir``,
            ``out``).

    Returns:
        Code de sortie du processus.
    """
    state = _exiger_etat(args.db_dir, args.arm)
    _exiger_sequence(state, args.tour, phase_attendue="collecte")
    out = _exiger_out(state, args.out)

    service = _common.open_service(args.db_dir)
    try:
        service.advance_week(PROJECT_ID, n=1)
        export_state.snapshot(args.db_dir, service, args.tour, out_dir=out / "snapshots")
    finally:
        service.close()

    state["last_tour"] = args.tour
    state.pop("pending_tour", None)
    state.pop("phase", None)
    save_state(args.db_dir, state)
    # Garde ``campaign_state.json`` (scripts facilitateur) aligne : les deux fichiers d'etat ne doivent jamais raconter deux histoires differentes.
    campagne = _common.load_state(args.db_dir)
    if campagne is not None:
        campagne["last_tour"] = args.tour
        campagne.pop("pending_tour", None)
        _common.save_state(args.db_dir, campagne)
    print(f"Tour {args.tour} clos ({args.arm}).")
    return 0


def _couverture(service) -> tuple[int, int]:
    """Couverture hebdomadaire du projet (noeuds a jour / noeuds actifs).

    Args:
        service: facade SupplyScore ouverte sur la base du sous-bras.

    Returns:
        Le couple ``(a jour, total actifs)``.
    """
    from supplyscore.services.weekly import CycleHebdomadaire

    return CycleHebdomadaire(service).couverture(PROJECT_ID)


def cmd_status(args: argparse.Namespace) -> int:
    """Affiche le bras, le dernier tour clos, le tour ouvert et la couverture.

    Args:
        args: arguments de la sous-commande (``db_dir``).

    Returns:
        Code de sortie du processus.
    """
    state = load_state(args.db_dir)
    if state is None:
        raise RefusExperienceError(f"aucune expérience dans {args.db_dir}.")
    print(f"Bras            : {state['arm']}")
    print(f"Dernier tour clos : {state['last_tour']}")
    en_cours = state.get("pending_tour")
    print(
        f"Tour ouvert     : {en_cours} (phase « {state.get('phase')} »)"
        if en_cours is not None
        else "Tour ouvert     : aucun"
    )
    service = _common.open_service(args.db_dir)
    try:
        a_jour, total = _couverture(service)
        print(f"Couverture hebdo : {a_jour}/{total}")
    finally:
        service.close()
    return 0


def role_card_bras_a(node_id: str) -> tuple[str, str]:
    """Carte de role du persona, IDENTIQUE a celle du pilote (bras A).

    Les personas du bras B SONT ceux du pilote : meme affectation
    noeud <-> persona, memes ``operator_id`` C1..C8 (``scenario.NODES``), meme
    voix. Rien n'est invente ici : la carte est produite par la voie
    officielle (``make_briefings.role_card``), puis CONFRONTEE a celle du
    pilote quand ce dossier est present. En cas d'ecart, c'est la carte DU
    PILOTE qui est reprise et l'ecart est signale - les personas doivent
    rester identiques d'un bras a l'autre.

    Args:
        node_id: noeud du persona.

    Returns:
        ``(texte, provenance)`` - la carte retenue et son origine
        (``"generee"``, ``"pilote (identique)"`` ou ``"pilote (ECART)"``).
    """
    texte = make_briefings.role_card(node_id)
    reference = PILOTE_BRAS_A / f"sandbox_{node_id}" / "role_card.md"
    if not reference.is_file():
        return texte, "générée"
    attendu = reference.read_text(encoding="utf-8")
    if attendu == texte:
        return texte, "pilote (identique)"
    print(
        f"  [!] ÉCART de carte de rôle sur {node_id} : la carte générée diffère "
        f"de {reference}. La carte DU PILOTE est reprise — les personas du bras "
        "B doivent être exactement ceux du bras A."
    )
    return attendu, "pilote (ÉCART)"


def cmd_make_sandboxes(args: argparse.Namespace) -> int:
    """Cree les 8 bacs a sable persona du sous-bras, sur le modele du bras A.

    Chaque ``OUT/sandbox_<node>/`` recoit ``role_card.md`` (celle du pilote,
    cf. :func:`role_card_bras_a`), ``INSTRUCTIONS.md`` (derive de
    ``_INSTRUCTIONS_TEMPLATE.md``, avec la seule section propre au bras) et
    ``ahp_tool.py`` (copie EXACTE de ``supplyscore/core/ahp.py``, comme dans
    le pilote). ``tours/`` est cree vide : ``prepare-tour`` y depose la fiche
    du tour, une par une - le persona ne peut donc pas anticiper.

    Args:
        args: arguments de la sous-commande (``arm``, ``out``).

    Returns:
        Code de sortie du processus.
    """
    gabarit = (_HERE / "_INSTRUCTIONS_TEMPLATE.md").read_text(encoding="utf-8")
    source_ahp = _common.REPO_ROOT / "supplyscore" / "core" / "ahp.py"
    if not source_ahp.is_file():
        raise RefusExperienceError(f"module AHP introuvable : {source_ahp}")

    section = _SECTION_PREDICT if args.arm in ARMS_AVEC_PREVISION else ""
    section += _SECTION_ACTIONS if args.arm in ARMS_AGISSANTS else ""
    cle = _CLE_INFLUENCE if args.arm in ARMS_AVEC_PREVISION else ""
    cle += _CLE_ACTION if args.arm in ARMS_AGISSANTS else ""
    out = Path(args.out)
    for spec in scenario.NODES:
        node_id = spec["id"]
        bac = out / f"sandbox_{node_id}"
        (bac / "tours").mkdir(parents=True, exist_ok=True)
        # Le nom du bras n'apparait NULLE PART dans le bac a sable : un persona qui se saurait " en groupe temoin " ne declarerait plus la meme chose.
        instructions = (
            gabarit.replace("@@NOEUD@@", node_id)
            .replace("@@SECTION_BRAS@@", section)
            .replace("@@CLE_INFLUENCE@@", cle)
        )
        (bac / "INSTRUCTIONS.md").write_text(instructions, encoding="utf-8")
        carte, provenance = role_card_bras_a(node_id)
        (bac / "role_card.md").write_text(carte, encoding="utf-8")
        shutil.copy2(source_ahp, bac / "ahp_tool.py")
        # Rattrapage : si des tours ont deja ete prepares avant la creation des bacs a sable, leurs fiches y sont recopiees (``prepare-tour`` ne peut alimenter que les bacs qui existaient au moment ou il tournait).
        rattrapees = 0
        for fiche in sorted(out.glob(f"tour_*/{node_id}.md")):
            cible = bac / "tours" / f"{fiche.parent.name}.md"
            if not cible.exists():
                cible.write_text(fiche.read_text(encoding="utf-8"), encoding="utf-8")
                rattrapees += 1
        suffixe = f", {rattrapees} fiche(s) rattrapée(s)" if rattrapees else ""
        print(f"  [bac à sable] {bac} — carte de rôle : {provenance}{suffixe}")
    print(f"{len(scenario.NODES)} bacs à sable « {args.arm} » prêts dans {out}.")
    return 0


# CLI


def _ajouter_arm(parser: argparse.ArgumentParser) -> None:
    """Ajoute l'option ``--arm`` obligatoire a un sous-analyseur.

    Args:
        parser: sous-analyseur a completer.
    """
    parser.add_argument(
        "--arm", required=True, choices=ARMS, help="Sous-bras de l'expérience B"
    )


def build_parser() -> argparse.ArgumentParser:
    """Construit l'analyseur d'arguments complet du harnais.

    Returns:
        L'``ArgumentParser`` racine, sous-commandes incluses.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sous = parser.add_subparsers(dest="commande", required=True)

    p_init = sous.add_parser("init", help="Crée la base d'un sous-bras")
    _ajouter_arm(p_init)
    _common.require_db_dir(p_init)
    p_init.set_defaults(fonction=cmd_init)

    p_prep = sous.add_parser("prepare-tour", help="Injecte le tour N et produit les fiches")
    _ajouter_arm(p_prep)
    _common.require_db_dir(p_prep)
    p_prep.add_argument("--tour", type=int, required=True, help="Numéro de tour")
    p_prep.add_argument("--out", required=True, help="Dossier de sortie du sous-bras")
    p_prep.add_argument(
        "--n-draws",
        type=int,
        default=N_DRAWS_DEFAUT,
        help=f"Trajectoires Monte Carlo du rollout (défaut {N_DRAWS_DEFAUT})",
    )
    p_prep.add_argument("--seed", type=int, default=0, help="Graine du rollout (défaut 0)")
    p_prep.set_defaults(fonction=cmd_prepare_tour)

    p_col = sous.add_parser("collect-tour", help="Collecte les 8 déclarations du tour N")
    _ajouter_arm(p_col)
    _common.require_db_dir(p_col)
    p_col.add_argument("--tour", type=int, required=True, help="Numéro de tour")
    p_col.add_argument("--answers", required=True, help="Fichier JSONL des réponses")
    p_col.add_argument(
        "--out",
        default=None,
        help="Dossier de sortie du sous-bras (défaut : celui déclaré à prepare-tour)",
    )
    p_col.set_defaults(fonction=cmd_collect_tour)

    p_close = sous.add_parser("close-tour", help="Clôt le tour N (advance_week + snapshot)")
    _ajouter_arm(p_close)
    _common.require_db_dir(p_close)
    p_close.add_argument("--tour", type=int, required=True, help="Numéro de tour")
    p_close.add_argument("--out", required=True, help="Dossier de sortie du sous-bras")
    p_close.set_defaults(fonction=cmd_close_tour)

    p_sand = sous.add_parser("make-sandboxes", help="Crée les 8 bacs à sable persona")
    _ajouter_arm(p_sand)
    p_sand.add_argument("--out", required=True, help="Dossier de sortie du sous-bras")
    p_sand.set_defaults(fonction=cmd_make_sandboxes)

    p_stat = sous.add_parser("status", help="Bras, dernier tour clos, couverture")
    _common.require_db_dir(p_stat)
    p_stat.set_defaults(fonction=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI du harnais d'experience.

    Args:
        argv: arguments de ligne de commande, ou None pour ``sys.argv``.

    Returns:
        Code de sortie du processus (0 = succes, 2 = refus explicite).
    """
    args = build_parser().parse_args(argv)
    try:
        return int(args.fonction(args))
    except RefusExperienceError as exc:
        print(f"REFUS : {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
