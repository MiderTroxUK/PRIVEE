"""Usine de campagnes sur chaines ALEATOIRES (U6) -- CLI de la campagne HELIOS.

Usage :
    python run_random_campaign.py --chains M --weeks N --seed S --out DIR
        [--tier {0,1,2}] [--behavior module:fonction] [--rollout]

Pour chaque chaine (un point du plan QMC de :func:`dgp.sample_regimes`) :

1. Base SQLite temporaire (``tempfile.mkdtemp``), service ouvert dessus,
   projet aleatoire complet via ``seed_demo(n_ranks, chain_seed)``.
2. Horloge de jeu (``advance_week`` l'exige) + mode Monte Carlo du lead time.
3. Boucle hebdomadaire, tour 1..N :
   a. decroissance bayesienne hebdo (" rien a signaler ", tous les noeuds) ;
   b. derive KPI (marche AR(1) log-normale) + tirage d'evenement DGP --
      UN SEUL appel par noeud a :func:`dgp.dynamics_week_step` (flux
      DYNAMIQUE, forme fixe -- condition de la paire CRN, cf. ``dgp.py``) ;
   c. relance d'un jalon actif (regle HELIOS : toujours un jalon ACTIF) ;
   d. injection des evenements declenches (:class:`~supplyscore.services.events.EventEngine`) ;
   e. operateur synthetique confondu sur le stress LATENT (decide / choisit /
      execute -- flux OPERATEUR, separe du flux dynamique) ;
   f. declarations hebdomadaires (palier 0 local ancre sur ``ur_local``, ou
      ``--behavior module:fonction`` pour les paliers 1/2) ;
   g. avance du temps de jeu + snapshot JSON.
4. Resolution des interventions en attente (paire CRN sur la fenetre de 4
   semaines, D18) puis ecriture de ``interventions_truth.jsonl``,
   ``dgp_manifest.json`` et ``variant_manifest.json`` dans le dossier de la
   chaine.

Recette E2E :
    python run_random_campaign.py --chains 2 --weeks 6 --seed 7 --out <scratch>
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import dgp
import numpy as np

from supplyscore.domain.constraints import clamp_kpi_value

# Aides pures (etat observable, JSON)


def _kpi_value(kpis: Any, path: str) -> float | None:
    """Lit un KPI par son chemin qualifie ``bloc.champ``."""
    block, _, field_name = path.partition(".")
    return getattr(getattr(kpis, block), field_name)


def _build_ctx(node: Any, milestones: list[Any]) -> dict[str, Any]:
    """Etat OBSERVABLE d'un noeud -- JAMAIS le stress latent (cf. ``dgp`` module docstring).

    Sert a la fois de ``ctx`` pour les preconditions d'action et de
    ``etat_avant`` dans ``interventions_truth.jsonl``.
    """
    from supplyscore.domain.milestones import next_active_milestone

    u = node.urgency
    return {
        "ur_local": u.ur_local,
        "ud_local": u.ud_local,
        "adequation": u.adequation,
        "false_urgency": u.false_urgency,
        "hidden_risk": u.hidden_risk,
        "kpis": {path: _kpi_value(node.kpis, path) for path in dgp.KPI_PATHS},
        "has_active_milestone": next_active_milestone(milestones) is not None,
    }


def _to_jsonable(obj: Any) -> Any:
    """Convertit recursivement les scalaires numpy en types Python natifs pour ``json.dumps``."""
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(_to_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(_to_jsonable(record), ensure_ascii=False) + "\n")


# Ouverture du service, snapshot, jalons


def _open_service(db_dir: str) -> Any:
    """Ouvre la facade SupplyScore sur ``db_dir`` (import differe, cache client genereux)."""
    from supplyscore.services.orchestrator import SupplyScoreService

    # client_cache_size genereux : les chaines a n_ranks eleve (jusqu'a 7, cf. dgp.N_RANKS_CHOICES) peuvent compter largement plus de noeuds que le defaut (64) -- au-dela, le cache LRU rouvrirait des connexions SQLite en boucle chaque semaine (cout I/O inutile sur une campagne longue).
    return SupplyScoreService(db_dir=db_dir, client_cache_size=256)


def write_snapshot(service: Any, project: Any, chain_dir: Path, tour: int) -> dict[str, Any]:
    """Snapshot du reseau au tour courant -- meme schema que ``export_state.py`` (+ ``blocs``)."""
    from supplyscore.core.clock import project_hours
    from supplyscore.core.explain import explain_ur_local
    from supplyscore.services.criticite import ServiceCriticite

    origin = project.origin_ts
    now = service.clock_for(project.id).now()
    t_h = project_hours(now, origin)

    nodes_out: dict[str, dict[str, Any]] = {}
    for node in service.repo.nodes_by_project(project.id):
        u = node.urgency
        blocs: list[dict[str, Any]] | None
        try:
            milestones = service.registry.list_milestones(node.id)
            contribs = explain_ur_local(t_h, node.kpis, milestones, service.ur_model, t0_ts=origin)
            blocs = [
                {"block": c.block, "u": c.u, "omega": c.omega, "share": c.share} for c in contribs
            ]
        except Exception:
            blocs = None
        nodes_out[node.id] = {
            "name": node.name,
            "rank": node.rank,
            "status": str(node.status),
            "ud": u.ud,
            "ur": u.ur,
            "ud_local": u.ud_local,
            "ur_local": u.ur_local,
            "adequation": u.adequation,
            "false_urgency": u.false_urgency,
            "hidden_risk": u.hidden_risk,
            "blocs": blocs,
        }

    try:
        criticite = [
            {
                "node_id": p.node_id,
                "rank": p.rank,
                "delta_ur_final": p.delta_ur_final,
                "delta_ur_max": p.delta_ur_max,
                "nb_impactes": p.nb_impactes,
            }
            for p in ServiceCriticite(service).indice_criticite(project.id)
        ]
    except Exception as exc:
        criticite = [{"erreur": f"{type(exc).__name__}: {exc}"}]

    data = {"tour": tour, "horodatage": time.time(), "nodes": nodes_out, "criticite": criticite}
    _write_json(chain_dir / f"tour_{tour:02d}.json", data)
    return data


def _nudge_milestone(service: Any, node: Any, rng: np.random.Generator) -> None:
    """Relance hebdomadaire du jalon actif -- regle HELIOS : toujours un jalon ACTIF.

    Nudge l'avancement du jalon actif courant ; s'il se termine (ou s'il n'y
    en avait plus), ouvre immediatement le suivant. La creation d'un nouveau
    jalon passe par une ecriture DIRECTE du registre (``registry.save_milestone``),
    comme le fait ``SupplyScoreService.seed_demo`` -- ``MutationService``
    n'expose pas de creation de jalon, seulement des mises a jour du jalon
    EXISTANT (:meth:`~supplyscore.services.mutations.MutationService.update_milestone`),
    utilise ici pour le nudge de progression.
    """
    from supplyscore.domain.milestones import Milestone, MilestoneStatus, next_active_milestone

    milestones = service.registry.list_milestones(node.id)
    actif = next_active_milestone(milestones)
    now = service.clock_for(node.project_id).now() if node.project_id else service.clock.now()

    def _new_milestone(position: int) -> Milestone:
        deadline = now + float(rng.uniform(7 * 24, 40 * 24)) * 3600.0
        return Milestone(
            id=str(uuid.uuid4()),
            node_id=node.id,
            name="Étape",
            kind="custom",
            start_ts=now,
            deadline_ts=deadline,
            status=MilestoneStatus.ACTIVE,
            progress=0.0,
            position=position,
        )

    if actif is None:
        service.registry.save_milestone(_new_milestone(len(milestones)))
        return

    new_progress = min(1.0, actif.progress + float(rng.uniform(0.05, 0.15)))
    changes: dict[str, Any] = {"progress": new_progress}
    if new_progress >= 1.0:
        changes["status"] = MilestoneStatus.DONE
    service.mutations.update_milestone(actif.id, changes, source="dgp:weekly", operator_id="dgp")
    if new_progress >= 1.0:
        service.registry.save_milestone(_new_milestone(len(milestones) + 1))


# Operateur synthetique : selection d'action


def _preconditions_ok(action: Any, ctx: dict[str, Any]) -> bool:
    try:
        return bool(action.preconditions(ctx))
    except Exception:
        return False


def _choose_action(catalogue: dict[str, Any], ctx: dict[str, Any], rng: np.random.Generator) -> Any:
    """Choisit une action dont les preconditions tiennent, ``ne_rien_faire`` a defaut."""
    eligible = [
        a for aid, a in catalogue.items() if aid != "ne_rien_faire" and _preconditions_ok(a, ctx)
    ]
    if not eligible:
        return catalogue["ne_rien_faire"]
    idx = int(rng.integers(0, len(eligible)))
    return eligible[idx]


def _mitigation_now(effects: list[tuple[int, int, float]], tour: int) -> float:
    """Reduction de stress actuellement en vigueur (somme des effets actifs, plafonnee)."""
    total = sum(mag for start, end, mag in effects if start <= tour < end)
    return min(total, dgp.MAX_MITIGATION)


def _effective_window_start(date_effet: int, tour: int) -> int:
    """Premiere semaine que la paire CRN peut REELLEMENT comparer, pour une intervention.

    Le checkpoint du flux dynamique (cf. :func:`_run_intervention`) est pris
    APRES que les tirages de la semaine ``tour`` ont deja ete consommes -- la
    premiere semaine que la branche fantome peut effectivement rejouer est
    donc ``tour + 1``, jamais ``tour`` lui-meme (deja passe au moment de la
    decision). Quand ``date_effet <= tour`` (delai nul ou arrondi a 0), la
    fenetre de comparaison est donc plancheree a ``tour + 1`` plutot que de
    prendre ``date_effet`` brut : sans ce plancher, la fenetre cote
    ``issue_without`` (rejouee depuis le checkpoint, qui demarre forcement a
    ``tour + 1``) et la fenetre cote ``issue_with`` (relue dans
    ``event_fired_timeline`` a partir de ``date_effet``) porteraient sur des
    semaines DECALEES d'une unite -- deux fenetres de 4 semaines qui se
    chevauchent sans coincider, capables de faire diverger ``delta_u_vrai``
    meme a mitigation nulle (comparaison de deux ensembles de semaines
    differents, pas un effet causal). Utilise pour ancrer A LA FOIS la duree
    de ``active_effects`` (branche reelle) et la fenetre de
    :func:`~dgp.replay_without_action` (branche contrefactuelle) -- les deux
    DOIVENT rester synchronisees.
    """
    return max(date_effet, tour + 1)


def _run_intervention(
    service: Any,
    node_id: str,
    node: Any,
    action: Any,
    ctx: dict[str, Any],
    tour: int,
    op_rng: np.random.Generator,
    dyn_rng: np.random.Generator,
    stress_kpi_now: float,
    hidden_now: float,
    stress_latent_now: float,
    regime: dgp.Regime,
    active_effects: dict[str, list[tuple[int, int, float]]],
) -> dict[str, Any]:
    """Decide/execute une intervention, calcule l'effet vrai et amorce la paire CRN (D18).

    Retourne un enregistrement PARTIEL : ``delta_u_vrai`` et
    ``resultat_operationnel`` sont finalises a posteriori par
    :func:`_resolve_interventions` une fois la chaine entierement simulee
    (la fenetre de 4 semaines peut depasser le tour courant). Les cles
    prefixees ``_`` sont des champs de resolution INTERNES, retires avant
    l'ecriture finale.

    ``stress_latent`` (``stress_latent_now``, la valeur ``s`` de
    :class:`~dgp.DynStepResult` au moment de la decision) est journalise en
    cle de PREMIER NIVEAU de l'enregistrement -- verite-terrain pour l'audit
    et la validation de la confusion (D21/D32) -- mais JAMAIS dans
    ``etat_avant`` (``ctx``), qui reste strictement l'ensemble des grandeurs
    OBSERVABLES sur lesquelles l'operateur synthetique a fonde sa decision
    (cf. :func:`_build_ctx`). Les deux regles coexistent : le latent est
    enregistre pour permettre de VERIFIER apres coup que la confusion opere
    bien sur une variable absente de l'observable, sans jamais y fuiter.

    ``ne_rien_faire`` suit EXACTEMENT le meme chemin que les autres actions
    (meme tirage d'execution -- toujours vrai puisque son
    ``apply_to_project`` est un no-op documente --, meme calcul d'effet vrai
    -- necessairement 0.0 puisque ``ur_local`` ne bouge pas --, meme paire
    CRN) : c'est une PROPRIETE AUTO-VERIFIANTE de l'implementation --
    ``delta_u_vrai`` doit alors toujours ressortir exactement a 0.0, les deux
    branches consommant un flux identique sans aucune mitigation.
    """
    action_id = getattr(action, "id", "?")
    record: dict[str, Any] = {
        "tour": tour,
        "node": node_id,
        "action_id": action_id,
        "etat_avant": ctx,
        "stress_latent": stress_latent_now,
        "decidee": True,
        "executee": None,
        "date_effet": None,
        "effet_vrai_param": None,
        "delta_u_vrai": None,
        "resultat_operationnel": None,
        "effets_voisins": None,
        "_window_start": None,
        "_window_end": None,
        "_issue_without": None,
        "_ur_local_avant": ctx.get("ur_local"),
    }

    executee = (
        True
        if action_id == "ne_rien_faire"
        else op_rng.random() < (1.0 - dgp.DEFAULT_P_ECHEC_EXECUTION)
    )
    record["executee"] = executee
    if not executee:
        record["resultat_operationnel"] = "echec"
        return record

    mn, mode, mx = action.delai_effet_weeks
    delay = round(float(op_rng.triangular(mn, mode, mx))) if mx > mn else round(mn)
    date_effet = tour + max(0, delay)
    record["date_effet"] = date_effet
    effective_window_start = _effective_window_start(date_effet, tour)

    predecessors = service.repo.predecessors(node_id)
    successors = service.repo.successors(node_id)
    ur_before_neighbours = {n.id: n.urgency.ur for n in predecessors + successors}
    ur_local_before = node.urgency.ur_local

    action.apply_to_project(service, node_id)
    service.evaluate_all(persist=True)

    refreshed = service.repo.get_node(node_id)
    ur_local_after = refreshed.urgency.ur_local if refreshed is not None else None
    reduction = max(0.0, (ur_local_before or 0.0) - (ur_local_after or 0.0))
    effet_vrai = min(dgp.MAX_MITIGATION, dgp.K_MITIG * reduction)
    record["effet_vrai_param"] = effet_vrai
    if effet_vrai > 0.0:
        # Ancree sur effective_window_start (pas le date_effet brut) : la mitigation REELLEMENT appliquee a la branche "avec" doit couvrir EXACTEMENT les memes 4 semaines que celles comparees par la paire CRN plus bas -- sinon la derniere semaine de la fenetre comparerait une branche "avec" deja retombee a mitigation nulle contre une branche "sans" elle aussi a mitigation nulle : un delta correct par chance, mais pour la MAUVAISE raison (fenetre de mitigation trop courte plutot que reel epuisement de l'effet).
        active_effects[node_id].append(
            (effective_window_start, effective_window_start + dgp.EFFECT_WINDOW_WEEKS, effet_vrai)
        )

    effets_voisins: dict[str, float] = {}
    for n in predecessors + successors:
        after = service.repo.get_node(n.id)
        if after is None:
            continue
        before_ur = ur_before_neighbours.get(n.id)
        after_ur = after.urgency.ur
        if before_ur is not None and after_ur is not None and abs(after_ur - before_ur) > 1e-9:
            effets_voisins[n.id] = after_ur - before_ur
    record["effets_voisins"] = effets_voisins or None

    # Paire CRN (D18) : clone de l'etat du flux DYNAMIQUE -- la branche reelle continue sur son propre generateur, non affectee par ce clone. ``effective_window_start`` (plancheree a tour + 1, cf. commentaire plus haut) -- PAS ``date_effet`` brut -- ancre a la fois skip_weeks et la fenetre relue dans ``event_fired_timeline`` par ``_resolve_interventions``.
    skip_weeks = effective_window_start - (tour + 1)
    checkpoint = copy.deepcopy(dyn_rng.bit_generator.state)
    issue_without = dgp.replay_without_action(
        checkpoint,
        stress_kpi_now,
        hidden_now,
        regime,
        skip_weeks=skip_weeks,
        weeks=dgp.EFFECT_WINDOW_WEEKS,
    )
    record["_window_start"] = effective_window_start
    record["_window_end"] = effective_window_start + dgp.EFFECT_WINDOW_WEEKS - 1
    record["_issue_without"] = issue_without
    return record


def _resolve_interventions(
    pending: list[tuple[dict[str, Any], Any]],
    event_fired_timeline: dict[str, dict[int, bool]],
    ur_local_timeline: dict[str, dict[int, float | None]],
    total_weeks: int,
) -> list[dict[str, Any]]:
    """Finalise ``delta_u_vrai`` et ``resultat_operationnel`` une fois la chaine simulee.

    Definition figee de ``resultat_operationnel`` (cascade, premier
    predicat vrai retenu) :
        1. fenetre tronquee (depasse la fin de la chaine) -> None ;
        2. pas d'evenement indesirable sur la fenetre ET objectif atteint -> "resolu" ;
        3. amelioration de ur_local (meme partielle) -> "partiel" ;
        4. sinon -> "echec" (evenement survenu, ou aucune amelioration).
    """
    resolved: list[dict[str, Any]] = []
    for record, action in pending:
        node_id = record["node"]
        window_start = record.pop("_window_start")
        window_end = record.pop("_window_end")
        issue_without = record.pop("_issue_without")
        ur_local_avant = record.pop("_ur_local_avant")

        if record["executee"]:
            truncated = window_end is None or window_end > total_weeks
            if truncated:
                record["delta_u_vrai"] = None
                record["resultat_operationnel"] = None
            else:
                timeline = event_fired_timeline.get(node_id, {})
                issue_with = any(
                    timeline.get(t, False) for t in range(window_start, window_end + 1)
                )
                record["delta_u_vrai"] = float(bool(issue_without)) - float(bool(issue_with))
                ur_local_apres = ur_local_timeline.get(node_id, {}).get(window_end)
                ameliore = (
                    ur_local_apres is not None
                    and ur_local_avant is not None
                    and (ur_local_avant - ur_local_apres) > 0.02
                )
                atteint = dgp.objectif_atteint(action, ur_local_avant, ur_local_apres)
                if (not issue_with) and atteint:
                    record["resultat_operationnel"] = "resolu"
                elif ameliore:
                    record["resultat_operationnel"] = "partiel"
                else:
                    record["resultat_operationnel"] = "echec"
        resolved.append(record)
    return resolved


# Boucle par chaine


def run_chain(
    regime: dgp.Regime,
    chain_seed: int,
    weeks: int,
    out_dir: Path,
    tier: int,
    behavior_fn: Callable[..., dict[str, list[int]]] | None,
) -> Path:
    """Execute une chaine complete, ecrit ses artefacts dans ``out_dir/chain_<seed>/``."""
    from supplyscore.services.events import EventEngine

    db_dir = tempfile.mkdtemp(prefix=f"helios_factory_chain{chain_seed}_")
    service = _open_service(db_dir)
    chain_dir = out_dir / f"chain_{chain_seed}"
    chain_dir.mkdir(parents=True, exist_ok=True)

    try:
        project = service.seed_demo(n_ranks=regime.n_ranks, seed=chain_seed)
        service.set_clock_mode(project.id, "game")
        service.set_lead_time_mode(project.id, "monte_carlo", n_tirages=2_000, graine=chain_seed)
        service.evaluate_all(persist=True)  # re-evalue sous MC avant le snapshot tour 0
        events_engine = EventEngine(service)

        nodes = service.repo.nodes_by_project(project.id)
        node_ids = [n.id for n in nodes]

        dyn_rng = {
            nid: np.random.default_rng(dgp.derive_seed(chain_seed, nid, "dyn")) for nid in node_ids
        }
        op_rng = {
            nid: np.random.default_rng(dgp.derive_seed(chain_seed, nid, "op")) for nid in node_ids
        }
        bias_rng = np.random.default_rng(dgp.derive_seed(chain_seed, "bias"))
        bias = {nid: float(bias_rng.normal(0.0, 0.10)) for nid in node_ids}

        stress_kpi = dict.fromkeys(node_ids, 0.0)
        hidden = dict.fromkeys(node_ids, 0.0)
        baseline_kpis = {
            n.id: {path: _kpi_value(n.kpis, path) for path in dgp.KPI_PATHS} for n in nodes
        }
        active_effects: dict[str, list[tuple[int, int, float]]] = {nid: [] for nid in node_ids}
        event_fired_timeline: dict[str, dict[int, bool]] = {nid: {} for nid in node_ids}
        ur_local_timeline: dict[str, dict[int, float | None]] = {nid: {} for nid in node_ids}
        events_truth: dict[str, list[dict[str, str]]] = {}
        pending: list[tuple[dict[str, Any], Any]] = []

        catalogue = dgp.load_action_catalogue()

        write_snapshot(service, project, chain_dir, tour=0)
        for nid in node_ids:
            node0 = service.repo.get_node(nid)
            ur_local_timeline[nid][0] = node0.urgency.ur_local if node0 is not None else None

        for tour in range(1, weeks + 1):
            # a. decroissance bayesienne hebdomadaire ("rien a signaler").
            for nid in node_ids:
                events_engine.apply_weekly_decay(nid, operator_id="dgp")

            # b. derive KPI + tirage d'evenement (flux DYNAMIQUE, forme fixe -- cf. dgp.py).
            week_results: dict[str, dgp.DynStepResult] = {}
            for nid in node_ids:
                node = service.repo.get_node(nid)
                mitigation = _mitigation_now(active_effects[nid], tour)
                result = dgp.dynamics_week_step(
                    dyn_rng[nid], stress_kpi[nid], hidden[nid], regime, mitigation_active=mitigation
                )
                stress_kpi[nid] = result.stress_kpi
                hidden[nid] = result.hidden
                week_results[nid] = result

                changes: dict[str, float | None] = {}
                for path, eps in result.innovations.items():
                    old = _kpi_value(node.kpis, path)
                    if old is None or old <= 0.0:
                        continue
                    base = baseline_kpis[nid].get(path)
                    if base is None or base <= 0.0:
                        base = old
                    changes[path] = clamp_kpi_value(path, dgp.ar1_new_value(old, base, eps))
                if changes:
                    service.mutations.update_kpis(
                        nid, changes, source="dgp:drift", operator_id="dgp"
                    )

            # c. relance d'un jalon actif (regle HELIOS).
            for nid in node_ids:
                node = service.repo.get_node(nid)
                _nudge_milestone(service, node, op_rng[nid])

            # d. injection des evenements declenches + verite DGP.
            for nid in node_ids:
                result = week_results[nid]
                event_fired_timeline[nid][tour] = result.fires
                if result.fires:
                    events_engine.apply(
                        nid,
                        result.event_type,
                        result.event_params,
                        operator_id="dgp",
                        notes=f"dgp tour {tour}",
                    )
                    events_truth.setdefault(str(tour), []).append(
                        {"node": nid, "type": result.event_type, "gravite": result.gravite}
                    )

            # e. operateur synthetique confondu sur le stress LATENT (flux OPERATEUR).
            for nid in node_ids:
                node = service.repo.get_node(nid)
                milestones = service.registry.list_milestones(nid)
                ctx = _build_ctx(node, milestones)  # OBSERVABLE seul -- jamais week_results[nid].s
                p_decide = dgp.decide_probability(week_results[nid].s)
                if op_rng[nid].random() >= p_decide:
                    continue
                action = _choose_action(catalogue, ctx, op_rng[nid])
                record = _run_intervention(
                    service,
                    nid,
                    node,
                    action,
                    ctx,
                    tour,
                    op_rng[nid],
                    dyn_rng[nid],
                    stress_kpi[nid],
                    hidden[nid],
                    week_results[nid].s,  # verite-terrain journalisee, JAMAIS dans ctx/etat_avant
                    regime,
                    active_effects,
                )
                pending.append((record, action))

            # f. declarations hebdomadaires.
            for nid in node_ids:
                node = service.repo.get_node(nid)
                milestones = service.registry.list_milestones(nid)
                features = _build_ctx(node, milestones)
                if behavior_fn is not None:
                    response = behavior_fn(nid, tour, features, op_rng[nid])
                else:
                    response = dgp.synthetic_respond(
                        nid, tour, features, op_rng[nid], bias=bias[nid]
                    )
                try:
                    comparisons, criteria_scores = dgp.response_to_ahp_inputs(response)
                    assessment = service.build_assessment(
                        nid,
                        project.id,
                        "dgp",
                        comparisons,
                        criteria_scores,
                        notes=f"dgp tier{tier}",
                    )
                    service.submit_assessment(assessment)
                except (ValueError, KeyError):
                    pass  # declaration incoherente (CR >= 0.10) : semaine sans declaration

            # g. avance du temps de jeu + snapshot.
            service.advance_week(project.id, 1)
            write_snapshot(service, project, chain_dir, tour=tour)
            for nid in node_ids:
                node = service.repo.get_node(nid)
                ur_local_timeline[nid][tour] = node.urgency.ur_local if node is not None else None

        resolved = _resolve_interventions(pending, event_fired_timeline, ur_local_timeline, weeks)
        _write_jsonl(chain_dir / "interventions_truth.jsonl", resolved)
        _write_json(chain_dir / "dgp_manifest.json", dgp.dgp_manifest(regime, chain_seed))
        _write_json(
            chain_dir / "variant_manifest.json",
            {
                "seed": chain_seed,
                "params": {
                    "n_ranks": regime.n_ranks,
                    "a": regime.a,
                    "b": regime.b,
                    "p_choc": regime.p_choc,
                    "sigma": regime.sigma,
                },
                "beta_scale": 1.0,
                "gamma_scale": 1.0,
                "events_truth": events_truth,
            },
        )
        return chain_dir
    finally:
        service.close()


# CLI


def _load_behavior(spec: str) -> Callable[..., dict[str, list[int]]]:
    """Charge ``respond`` depuis ``module:fonction`` (contrat fige, paliers 1/2)."""
    module_name, sep, func_name = spec.partition(":")
    if not sep or not module_name or not func_name:
        raise SystemExit(f"--behavior doit être au format module:fonction, reçu {spec!r}")
    module = importlib.import_module(module_name)
    fn = getattr(module, func_name, None)
    if fn is None or not callable(fn):
        raise SystemExit(
            f"--behavior : {func_name!r} introuvable (ou non appelable) dans {module_name!r}"
        )
    return fn


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI -- echantillonne le plan QMC puis execute chaque chaine."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--chains", type=int, required=True, help="nombre de chaînes à générer")
    parser.add_argument("--weeks", type=int, required=True, help="nombre de tours par chaîne")
    parser.add_argument(
        "--seed", type=int, required=True, help="graine de base (plan QMC + chaînes)"
    )
    parser.add_argument(
        "--out", type=str, required=True, help="dossier de sortie (un sous-dossier par chaîne)"
    )
    parser.add_argument(
        "--tier", type=int, choices=(0, 1, 2), default=0, help="palier des déclarants (0 = local)"
    )
    parser.add_argument(
        "--behavior",
        type=str,
        default=None,
        help="module:fonction -- respond(node_id, tour, features, rng) -> "
        '{"bipolar": [6 int -8..8], "scores_ui": [4 int 1..6]} (requis pour --tier 1/2)',
    )
    parser.add_argument(
        "--rollout",
        action="store_true",
        help="tente d'intégrer ForecastService (U9) après chaque chaîne",
    )
    args = parser.parse_args(argv)

    if args.chains < 1:
        parser.error("--chains doit être >= 1")
    if args.weeks < 1:
        parser.error("--weeks doit être >= 1")

    if args.rollout:
        try:
            from supplyscore.services.forecast import ForecastService  # noqa: F401
        except ImportError as exc:
            print(
                "Erreur : --rollout nécessite supplyscore.services.forecast.ForecastService "
                f"(unité U9), introuvable dans cet environnement : {exc}",
                file=sys.stderr,
            )
            return 1

    behavior_fn: Callable[..., dict[str, list[int]]] | None = None
    if args.behavior:
        behavior_fn = _load_behavior(args.behavior)
    elif args.tier in (1, 2):
        print("Erreur : --behavior module:fonction est requis pour --tier 1 ou 2", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    regimes = dgp.sample_regimes(args.seed, args.chains)
    for i, regime in enumerate(regimes):
        chain_seed = args.seed + i
        chain_dir = run_chain(regime, chain_seed, args.weeks, out_dir, args.tier, behavior_fn)
        print(
            f"[chaîne {i + 1}/{args.chains}] seed={chain_seed} n_ranks={regime.n_ranks} "
            f"a={regime.a:.2f} b={regime.b:.2f} p_choc={regime.p_choc:.3f} -> {chain_dir}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
