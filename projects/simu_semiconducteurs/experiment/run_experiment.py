"""Harnais d'expérience du BRAS B (HÉLIOS) : déclaration assistée par prévision.

Trois bras sont comparés sur le MÊME scénario HÉLIOS (crise des
semi-conducteurs 2020-2022 rejouée, vérité terrain GELÉE dans
``scenario.EVENTS``) :

- **bras A** — pilote LLM déjà joué (``analysis/llm_pilot_run/``) : les
  personas lisent leur fiche et déclarent leur Ud. Rien à rejouer ici.
- **bras B** — CE HARNAIS : fiche IDENTIQUE au bras A, plus (bras ``predict``
  seulement) une section « ANALYSE PRÉDICTIVE (outil) » qui expose au persona
  la prévision de SON nœud. Les personas DÉCLARENT seulement : aucune action,
  aucune modification de la vérité terrain — KPIs, jalons et événements
  restent pilotés par le pack gelé ``data/prepared``. La boucle est OUVERTE,
  donc les prévisions restent scorables.
- **bras C** — extension future (les personas agiront réellement sur la
  chaîne) : NON IMPLÉMENTÉ, cf. :func:`appliquer_actions_bras_c`.

L'A/B interne du bras B oppose deux sous-bras :

- ``control`` : la prévision est calculée et JOURNALISÉE, jamais montrée ;
- ``predict`` : la MÊME prévision est en plus rendue dans la fiche.

Les deux sous-bras produisent donc des prédictions prospectives comparables ;
seule leur VISIBILITÉ diffère (``montre_au_persona`` dans
``predictions_log.jsonl``). Hors ce bloc, les fiches des deux sous-bras sont
identiques au caractère près — c'est la validité interne de l'A/B.

Usage (une base SQLite PERSISTÉE par sous-bras) ::

    python run_experiment.py init         --arm predict --db-dir D
    python run_experiment.py prepare-tour --arm predict --db-dir D --out O --tour N
    python run_experiment.py collect-tour --arm predict --db-dir D --answers F.jsonl
    python run_experiment.py close-tour   --arm predict --db-dir D --out O --tour N
    python run_experiment.py make-sandboxes --arm predict --out O
    python run_experiment.py status       --db-dir D

Aucun appel LLM n'est fait ici : le harnais lit et écrit des fichiers, le
coordinateur fait tourner les personas (agents Haiku) sur les dossiers
``sandbox_<node>/`` produits par ``make-sandboxes``.

Garantie ANTI-FUITE (héritée de ``make_briefings``) : une fiche n'est
construite qu'à partir des fichiers préparés des tours <= N et des seules
données du nœud concerné. La section prédictive n'ajoute que des nombres
calculés SUR CE NŒUD. Le pack ``data/prepared`` est ouvert en LECTURE SEULE.
"""

from __future__ import annotations

import argparse
import json
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
from supplyscore.services.forecast import MIN_HISTORY_WEEKS, ForecastService  # noqa: E402

#: Les deux sous-bras de l'expérience B (le bras A n'est pas rejoué ici).
ARMS: tuple[str, ...] = ("control", "predict")

#: Horizon de prévision montré/journalisé, en semaines (défaut de U9).
HORIZON_PREVISION: int = 4

#: Budget de trajectoires Monte Carlo par défaut (compromis vitesse/précision
#: pour un tour interactif ; U9 exige >= 20, un multiple de 20 est consommé).
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

#: Titre EXACT du bloc de traitement — seule différence entre les deux bras.
TITRE_PREDICTIF: str = "## ANALYSE PRÉDICTIVE (outil)"

#: Phrase servie quand la prévision est impossible (jamais un chiffre inventé).
INDISPONIBLE: str = "analyse prédictive indisponible ce tour"

#: Paires AHP comparées, dans l'ordre figé de l'UI (contrat 2 du plan v7) —
#: réutilisé depuis ``inject_tour`` plutôt que redéclaré : une seule source.
_AHP_PAIRS = inject_tour._AHP_PAIRS

#: Dossier du pilote LLM (bras A) — référence des cartes de rôle. Absent d'une
#: worktree fraîche : la vérification ci-dessous est donc au mieux-effort.
PILOTE_BRAS_A: Path = _common.PROJECT_DIR / "analysis" / "llm_pilot_run"


class RefusExperienceError(Exception):
    """Refus explicite du harnais (séquence, couverture, réponse invalide).

    Portée par un message français prêt à afficher : :func:`main` le rend tel
    quel préfixé de « REFUS : » et sort en code 2, comme ``inject_tour.py``.
    """


# --- État d'expérience -----------------------------------------------------------------


def state_path(db_dir: str) -> Path:
    """Chemin du fichier d'état d'expérience du sous-bras.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.

    Returns:
        Le chemin de ``experiment_state.json``.
    """
    return Path(db_dir) / "experiment_state.json"


def load_state(db_dir: str) -> dict | None:
    """Lit l'état d'expérience, ou None si le sous-bras n'est pas initialisé.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.

    Returns:
        L'état ``{arm, last_tour, pending_tour?, phase?}``, ou None.
    """
    path = state_path(db_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(db_dir: str, state: dict) -> None:
    """Écrit l'état d'expérience du sous-bras.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.
        state: état complet à persister.
    """
    state_path(db_dir).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _exiger_etat(db_dir: str, arm: str) -> dict:
    """Charge l'état et vérifie que le sous-bras demandé est bien celui de la base.

    Args:
        db_dir: dossier des bases SQLite du sous-bras.
        arm: sous-bras demandé en ligne de commande.

    Returns:
        L'état d'expérience validé.

    Raises:
        RefusExperienceError: base non initialisée ou bras discordant — mélanger
            deux bras dans une même base ruinerait l'A/B.
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
    """Résout ``--out`` en le verrouillant sur celui déclaré à ``prepare-tour``.

    Le dossier de sortie porte l'historique du bras (``results/<node>.jsonl``,
    d'où sort le Ud lissé du tour précédent, et ``predictions_log.jsonl``).
    Changer de dossier en cours de route casserait SILENCIEUSEMENT la chaîne
    de lissage — d'où le verrou : ``prepare-tour`` enregistre le dossier, les
    étapes suivantes le reprennent ou doivent le désigner à l'identique.

    Args:
        state: état d'expérience courant.
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
    """Vérifie que ``tour`` est bien le tour attendu dans la phase attendue.

    Discipline identique à ``inject_tour.py`` : pas de rejeu silencieux, pas
    de saut de tour, une seule phase possible à la fois.

    Args:
        state: état d'expérience courant.
        tour: tour demandé.
        phase_attendue: phase requise (``"injecte"`` avant collecte,
            ``"collecte"`` avant clôture), ou None pour ouvrir un tour neuf.

    Raises:
        RefusExperienceError: tour hors séquence ou phase incompatible (français).
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


# --- Prévisions (calculées dans LES DEUX bras) ------------------------------------------


@dataclass(frozen=True)
class _PointPrevision:
    """Point de prévision duck-typé consommé par :class:`InsightService`.

    Reproduit la partie du contrat 6 (``PredictionPoint``, U11) réellement lue
    par ``InsightService`` — le harnais n'a pas d'artefact de modèle entraîné
    et travaille directement sur le rollout Monte Carlo (U9).

    Attributes:
        node_id: nœud concerné.
        node_name: nom lisible du nœud.
        proba_by_horizon: ``P(issue défavorable <= k semaines)`` par horizon k.
        delta_vs_last_week: variation brute de ``ur_local`` sur la dernière
            semaine ISO du nœud, None si l'historique est trop court.
        p_jalon_rate: probabilité de jalon raté à l'horizon de référence.
        p_impact_client: probabilité d'impact client à l'horizon de référence.
        impact_frac: fraction des nœuds du projet touchés par le pire choc
            local de CE nœud (criticité systématique), None si indisponible.
        recommandation: TOUJOURS None en bras B — les personas ne peuvent
            agir sur rien, donc aucune action n'est recommandée (couture C).
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
    """Formate une probabilité de [0, 1] en pourcentage français.

    Args:
        valeur: probabilité à formater, ou None.
        decimales: nombre de décimales affichées.

    Returns:
        ``"27.3 %"``, ou ``"n/d"`` si ``valeur`` est None.
    """
    if valeur is None:
        return "n/d"
    return f"{valeur * 100:.{decimales}f} %"


def _impact_frac_par_noeud(service) -> dict[str, float]:
    """Fraction du projet impactée par le pire choc local, par nœud.

    Même formule que ``PredictionService`` (``nb_impactes / n_noeuds_projet``)
    — c'est une propriété structurelle DU nœud considéré, jamais l'état d'un
    autre nœud (cf. la garantie anti-fuite du protocole d'expérience).

    Args:
        service: façade SupplyScore ouverte sur la base du sous-bras.

    Returns:
        ``{node_id: fraction}`` ; dictionnaire vide si la criticité échoue.
    """
    from supplyscore.services.criticite import ServiceCriticite

    n_noeuds = len(service.repo.nodes_by_project(PROJECT_ID))
    if not n_noeuds:
        return {}
    try:
        points = ServiceCriticite(service).indice_criticite(PROJECT_ID)
    except Exception as exc:  # criticité best-effort : l'insight reste produit
        print(f"  [criticité ÉCHEC] {type(exc).__name__}: {exc}")
        return {}
    return {p.node_id: p.nb_impactes / n_noeuds for p in points}


def previsions_du_tour(
    service, n_draws: int, seed: int
) -> tuple[dict[str, dict], str | None]:
    """Rollout Monte Carlo du projet + lecture en clair, nœud par nœud.

    Enchaîne ``ForecastService.rollout`` (U9), la criticité systématique et
    ``InsightService`` (U12, 100 % règles, aucun LLM). Aucune écriture en base.

    Args:
        service: façade SupplyScore ouverte sur la base du sous-bras.
        n_draws: budget de trajectoires du rollout.
        seed: graine du rollout (déterminisme : même graine, mêmes chiffres).

    Returns:
        ``(par_noeud, erreur)`` — ``par_noeud`` associe à chaque nœud simulé
        ``{p_issue, ic80_h4, se_mc, spread, p_jalon_rate, p_impact_client,
        insight}`` ; ``erreur`` est None en cas de succès, sinon le message
        français expliquant pourquoi aucune prévision n'est disponible (et
        ``par_noeud`` est alors vide).
    """
    from supplyscore.services.insights import InsightService

    forecast = ForecastService(service)
    try:
        resultat = forecast.rollout(
            PROJECT_ID, horizon_weeks=HORIZON_PREVISION, n_draws=n_draws, seed=seed
        )
    except Exception as exc:  # prévision best-effort : jamais un chiffre inventé
        return {}, f"{type(exc).__name__}: {exc}"

    fractions = _impact_frac_par_noeud(service)
    par_noeud: dict[str, dict] = {}
    for node_id, par_horizon in resultat.previsions.items():
        node = service.repo.get_node(node_id)
        reference = par_horizon[HORIZON_PREVISION]
        # Réutilise le regroupement hebdomadaire CANONIQUE du service de
        # prévision (dernier état de chaque semaine ISO) au lieu de le redériver.
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
        except Exception as exc:  # lecture en clair best-effort : chiffres conservés
            print(f"  [insight ÉCHEC {node_id}] {type(exc).__name__}: {exc}")
            message = ""
        par_noeud[node_id] = {
            "p_issue": {k: p.p_issue for k, p in par_horizon.items()},
            "ic80_h4": (reference.ic80.bas, reference.ic80.haut),
            "se_mc": reference.se_mc,
            "spread": reference.spread,
            "p_jalon_rate": reference.p_jalon_rate,
            "p_impact_client": reference.p_impact_client,
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
    """Écrit une ligne de ``predictions_log.jsonl`` par (tour, nœud).

    C'EST LE CŒUR SCIENTIFIQUE DU DISPOSITIF : le bras ``control`` journalise
    EXACTEMENT les mêmes prédictions que le bras ``predict``, mais avec
    ``montre_au_persona = false``. Les deux bras produisent donc des
    prédictions prospectives comparables ; seule leur visibilité diffère.

    Idempotent : les lignes du même tour déjà présentes sont remplacées, pas
    dupliquées (une reprise après incident ne fausse pas le journal).

    Args:
        out: dossier de sortie du sous-bras.
        arm: sous-bras (``control`` ou ``predict``).
        tour: tour journalisé.
        par_noeud: prévisions par nœud (vide si ``erreur`` est renseignée).
        erreur: message d'échec de la prévision, ou None.
        n_draws: budget de trajectoires effectivement demandé.
        seed: graine du rollout.

    Returns:
        Le chemin du journal écrit.
    """
    chemin = out / "predictions_log.jsonl"
    anciennes = []
    if chemin.exists():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            if not ligne.strip():
                continue
            if json.loads(ligne).get("tour") != tour:
                anciennes.append(ligne)

    montre = arm == "predict" and erreur is None
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
        entree["montre_au_persona"] = montre and donnees is not None
        entree["n_draws"] = n_draws
        entree["seed"] = seed
        if erreur is not None:
            entree["erreur"] = erreur
        nouvelles.append(json.dumps(entree, ensure_ascii=False))

    chemin.write_text("\n".join([*anciennes, *nouvelles]) + "\n", encoding="utf-8")
    return chemin


def section_predictive(donnees: dict | None) -> str:
    """Bloc « ANALYSE PRÉDICTIVE (outil) » d'une fiche du bras ``predict``.

    SEUL point de divergence entre les deux sous-bras. Ne contient QUE des
    chiffres calculés sur le nœud de la fiche ; aucun nombre n'est inventé —
    en l'absence de prévision exploitable, la section le dit explicitement.

    Args:
        donnees: prévisions du nœud (cf. :func:`previsions_du_tour`), ou None
            si la prévision a échoué ou si l'historique est insuffisant.

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


# --- Fiches -----------------------------------------------------------------------------


def _ecrire_fiche(out: Path, node_id: str, tour: int, texte: str) -> Path:
    """Écrit la fiche du nœud et la recopie dans son bac à sable s'il existe.

    Args:
        out: dossier de sortie du sous-bras.
        node_id: nœud concerné.
        tour: tour de la fiche.
        texte: contenu Markdown complet de la fiche.

    Returns:
        Le chemin de la fiche de référence (``OUT/tour_NN/<node>.md``).
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


# --- Réponses des personas ---------------------------------------------------------------


def _entier(valeur: object, contexte: str, bas: int, haut: int) -> int:
    """Valide un entier borné venant d'un fichier de réponses.

    Args:
        valeur: valeur brute lue dans le JSON.
        contexte: description du champ, pour le message d'erreur.
        bas: borne inférieure incluse.
        haut: borne supérieure incluse.

    Returns:
        L'entier validé.

    Raises:
        RefusExperienceError: valeur non entière ou hors bornes (français).
    """
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise RefusExperienceError(f"{contexte} doit être un entier, reçu {valeur!r}.")
    if not bas <= valeur <= haut:
        raise RefusExperienceError(f"{contexte} doit être dans [{bas}, {haut}], reçu {valeur}.")
    return valeur


def lire_answers(chemin: Path, arm: str) -> dict[str, dict]:
    """Lit et valide le fichier de réponses d'un tour (une ligne JSON par nœud).

    Clés attendues : ``node_id``, ``bipolar`` (6 entiers de -8 à 8),
    ``scores_ui`` (4 entiers de 1 à 6), ``note``, ``attempts`` (optionnel,
    1 ou 2) et, en bras ``predict`` UNIQUEMENT, ``influence_prediction``.
    Toute autre clé est ignorée : le coordinateur peut donc recopier telle
    quelle la ligne ``results.jsonl`` écrite par le persona en y ajoutant
    ``node_id``.

    Args:
        chemin: fichier de réponses du tour.
        arm: sous-bras courant (contrôle la présence d'``influence_prediction``).

    Returns:
        ``{node_id: réponse validée}`` couvrant EXACTEMENT les 8 nœuds.

    Raises:
        RefusExperienceError: fichier absent/malformé, couverture incomplète,
            doublon, nœud inconnu ou champ invalide (messages en français).
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

        influence = brut.get("influence_prediction")
        if arm == "predict":
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
            "influence_prediction": influence if arm == "predict" else None,
        }

    manquants = attendus - set(reponses)
    if manquants:
        raise RefusExperienceError(
            f"couverture incomplète : {len(reponses)}/{len(attendus)} nœuds — "
            f"manque {', '.join(sorted(manquants))}."
        )
    return reponses


def _dernier_resultat(chemin: Path) -> dict | None:
    """Dernière ligne de résultat d'un nœud (pour le Ud lissé et le report).

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
    """Ajoute une ligne de résultat, en remplaçant celle du même tour si besoin.

    Args:
        chemin: fichier ``OUT/results/<node_id>.jsonl``.
        ligne: ligne de résultat au schéma du bras A.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    gardees: list[str] = []
    if chemin.exists():
        for existante in chemin.read_text(encoding="utf-8").splitlines():
            if existante.strip() and json.loads(existante).get("tour") != ligne["tour"]:
                gardees.append(existante)
    gardees.append(json.dumps(ligne, ensure_ascii=False))
    chemin.write_text("\n".join(gardees) + "\n", encoding="utf-8")


# --- Couture bras C (NON IMPLÉMENTÉE) ----------------------------------------------------


def appliquer_actions_bras_c(service, node_id: str, tour: int, reponse: dict) -> None:
    """Point d'extension « bras C » — volontairement INERTE en bras A et B.

    Le bras B est en boucle OUVERTE : les personas DÉCLARENT, ils n'agissent
    pas ; la vérité terrain reste pilotée par le pack gelé ``data/prepared``,
    ce qui rend les prédictions scorables. Le bras C fermera la boucle — les
    personas choisiront une action, qui modifiera réellement la chaîne.

    Quand le bras C sera implémenté, TOUT s'accroche ici, et nulle part
    ailleurs :

    1. lire l'action choisie dans ``reponse`` (clé à ajouter au format de
       réponse, p. ex. ``action_id`` + paramètres) ;
    2. la résoudre dans le catalogue ``supplyscore.domain.actions.CATALOGUE_V1``
       après vérification de sa précondition (``contexte_pour(service,
       node_id)``) ;
    3. l'appliquer au projet via ``ActionSpec.apply_to_project``, qui écrit
       exclusivement par la façade/``MutationService`` (validation + audit) ;
    4. journaliser l'intervention avec
       ``supplyscore.services.interventions.InterventionJournal.record`` puis
       ``marquer_executee`` — c'est ce journal qui alimentera ensuite les
       effets causaux (U17) et le moteur de décision (U18).

    Attention (validité de l'expérience) : dès que cette fonction agit, la
    vérité terrain dépend des personas et les prédictions du bras B ne sont
    plus comparables à celles du bras C sans appariement explicite.

    Args:
        service: façade SupplyScore ouverte sur la base du sous-bras.
        node_id: nœud déclarant.
        tour: tour courant.
        reponse: réponse validée du persona pour ce tour.
    """
    return None


#: Clé supplémentaire de la ligne de résultat, bras ``predict`` uniquement.
_CLE_INFLUENCE: str = (
    ',\n   "influence_prediction": '
    '"aucune|confirme|revise_a_la_hausse|revise_a_la_baisse"'
)

#: Section d'instructions propre au bras ``predict`` (le traitement mesuré).
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


# --- Sous-commandes ----------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Crée la base d'un sous-bras et son état d'expérience.

    Args:
        args: arguments de la sous-commande (``arm``, ``db_dir``).

    Returns:
        Code de sortie du processus (0 = succès, 2 = refus).
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
    """Injecte le tour N (pack gelé) puis produit les 8 fiches et le journal.

    Séquence : décroissance hebdomadaire (N > 0), injection KPIs/jalons/
    événements depuis ``data/prepared`` (LECTURE SEULE), prévision (dès
    N >= MIN_HISTORY_WEEKS, dans LES DEUX bras), journalisation, puis fiches —
    la section prédictive n'étant ajoutée qu'en bras ``predict``.

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

        # Réévaluation EXPLICITE avant de prévoir. Sans elle, l'état d'urgence
        # persisté de la semaine courante ne refléterait les KPIs/jalons du tour
        # QUE sur les tours porteurs d'un événement (``EventEngine.apply`` est
        # le seul des trois injecteurs à réévaluer) : la prévision serait
        # « fraîche » aux tours 3, 5, 6, 7... et « périmée » aux tours 4, 8, 9,
        # 11, 15, 17, 18, qui n'ont aucun événement. Un traitement inégal d'un
        # tour à l'autre ruinerait la comparabilité des prédictions.
        service.evaluate_all(persist=True)

        par_noeud: dict[str, dict] = {}
        if args.tour >= MIN_HISTORY_WEEKS:
            par_noeud, erreur = previsions_du_tour(service, args.n_draws, args.seed)
            if erreur is not None:
                print(f"  [prévision INDISPONIBLE] {erreur}")
            journal = journaliser_previsions(
                out, args.arm, args.tour, par_noeud, erreur, args.n_draws, args.seed
            )
            montre = args.arm == "predict" and erreur is None
            print(f"  [prévision] {len(par_noeud)} nœud(s) -> {journal} (montrée : {montre})")
        else:
            print(
                f"  [prévision] non calculée avant le tour {MIN_HISTORY_WEEKS} "
                f"(historique hebdomadaire minimal)"
            )

        for spec in scenario.NODES:
            node_id = spec["id"]
            texte = make_briefings.briefing(node_id, args.tour)
            if args.arm == "predict" and args.tour >= MIN_HISTORY_WEEKS:
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
    """Valide les 8 déclarations du tour N, les soumet et écrit les résultats.

    Les réponses sont d'abord TOUTES validées et converties (aucune écriture),
    puis soumises : un fichier invalide ne laisse jamais un tour à moitié
    déclaré. En cas d'AHP incohérent (CR >= 0.10), la règle de report du
    protocole s'applique — la déclaration du tour précédent est reconduite et
    consignée (``cr_echec``).

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

    # Phase 1 — conversion et contrôle de cohérence, SANS aucune écriture.
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
            # Couture bras C : inerte tant que les personas ne font que déclarer.
            appliquer_actions_bras_c(service, node_id, args.tour, reponse)

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
            if args.arm == "predict":
                ligne["influence_prediction"] = reponse["influence_prediction"]
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
    """Clôt le tour N : avance d'une semaine et écrit le snapshot.

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
    # Garde ``campaign_state.json`` (scripts facilitateur) aligné : les deux
    # fichiers d'état ne doivent jamais raconter deux histoires différentes.
    campagne = _common.load_state(args.db_dir)
    if campagne is not None:
        campagne["last_tour"] = args.tour
        campagne.pop("pending_tour", None)
        _common.save_state(args.db_dir, campagne)
    print(f"Tour {args.tour} clos ({args.arm}).")
    return 0


def _couverture(service) -> tuple[int, int]:
    """Couverture hebdomadaire du projet (nœuds à jour / nœuds actifs).

    Args:
        service: façade SupplyScore ouverte sur la base du sous-bras.

    Returns:
        Le couple ``(à jour, total actifs)``.
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
    """Carte de rôle du persona, IDENTIQUE à celle du pilote (bras A).

    Les personas du bras B SONT ceux du pilote : même affectation
    nœud <-> persona, mêmes ``operator_id`` C1..C8 (``scenario.NODES``), même
    voix. Rien n'est inventé ici : la carte est produite par la voie
    officielle (``make_briefings.role_card``), puis CONFRONTÉE à celle du
    pilote quand ce dossier est présent. En cas d'écart, c'est la carte DU
    PILOTE qui est reprise et l'écart est signalé — les personas doivent
    rester identiques d'un bras à l'autre.

    Args:
        node_id: nœud du persona.

    Returns:
        ``(texte, provenance)`` — la carte retenue et son origine
        (``"générée"``, ``"pilote (identique)"`` ou ``"pilote (ÉCART)"``).
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
    """Crée les 8 bacs à sable persona du sous-bras, sur le modèle du bras A.

    Chaque ``OUT/sandbox_<node>/`` reçoit ``role_card.md`` (celle du pilote,
    cf. :func:`role_card_bras_a`), ``INSTRUCTIONS.md`` (dérivé de
    ``_INSTRUCTIONS_TEMPLATE.md``, avec la seule section propre au bras) et
    ``ahp_tool.py`` (copie EXACTE de ``supplyscore/core/ahp.py``, comme dans
    le pilote). ``tours/`` est créé vide : ``prepare-tour`` y dépose la fiche
    du tour, une par une — le persona ne peut donc pas anticiper.

    Args:
        args: arguments de la sous-commande (``arm``, ``out``).

    Returns:
        Code de sortie du processus.
    """
    gabarit = (_HERE / "_INSTRUCTIONS_TEMPLATE.md").read_text(encoding="utf-8")
    source_ahp = _common.REPO_ROOT / "supplyscore" / "core" / "ahp.py"
    if not source_ahp.is_file():
        raise RefusExperienceError(f"module AHP introuvable : {source_ahp}")

    section = _SECTION_PREDICT if args.arm == "predict" else ""
    cle = _CLE_INFLUENCE if args.arm == "predict" else ""
    out = Path(args.out)
    for spec in scenario.NODES:
        node_id = spec["id"]
        bac = out / f"sandbox_{node_id}"
        (bac / "tours").mkdir(parents=True, exist_ok=True)
        # Le nom du bras n'apparaît NULLE PART dans le bac à sable : un persona
        # qui se saurait « en groupe témoin » ne déclarerait plus la même chose.
        instructions = (
            gabarit.replace("@@NOEUD@@", node_id)
            .replace("@@SECTION_BRAS@@", section)
            .replace("@@CLE_INFLUENCE@@", cle)
        )
        (bac / "INSTRUCTIONS.md").write_text(instructions, encoding="utf-8")
        carte, provenance = role_card_bras_a(node_id)
        (bac / "role_card.md").write_text(carte, encoding="utf-8")
        shutil.copy2(source_ahp, bac / "ahp_tool.py")
        # Rattrapage : si des tours ont déjà été préparés avant la création des
        # bacs à sable, leurs fiches y sont recopiées (``prepare-tour`` ne peut
        # alimenter que les bacs qui existaient au moment où il tournait).
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


# --- CLI ---------------------------------------------------------------------------------


def _ajouter_arm(parser: argparse.ArgumentParser) -> None:
    """Ajoute l'option ``--arm`` obligatoire à un sous-analyseur.

    Args:
        parser: sous-analyseur à compléter.
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
    """Point d'entrée CLI du harnais d'expérience.

    Args:
        argv: arguments de ligne de commande, ou None pour ``sys.argv``.

    Returns:
        Code de sortie du processus (0 = succès, 2 = refus explicite).
    """
    args = build_parser().parse_args(argv)
    try:
        return int(args.fonction(args))
    except RefusExperienceError as exc:
        print(f"REFUS : {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
