"""Runner de campagne HELIOS headless, en-process (U5).

Usage :
    python run_campaign.py --out DIR [--prepared DIR] [--seed S] [--tours N]
                            [--behavior module:fonction] [--rollout]

Joue une campagne HELIOS complete (T0..N) sans serveur ni saisie humaine, en
un seul process Python. A chaque tour : decroissance hebdomadaire (t > 0),
injection KPIs/jalons/evenements, puis une declaration AHP par noeud - soit
les profils synthetiques historiques (defaut, identique a
``inject_tour.py --dry-run-ahp``), soit un callback " declarant " fourni via
``--behavior module:fonction`` (contrat 2 du plan v7 : voir
``inject_tour._submit_synthetic_ahp``). Un snapshot ``tour_NN.json`` est
ecrit par tour dans ``OUT/run_<seed>/`` (reutilise ``export_state.snapshot``).

Base de donnees : creee dans un dossier temporaire propre a ce run et purgee
a la fin - la campagne ne touche jamais ``data/prepared`` (lecture seule, cf.
``--prepared``) ni un db-dir partage avec d'autres campagnes.

Variantes : si ``--prepared`` contient un ``variant_manifest.json``
(``{"beta_scale": ..., "gamma_scale": ...}``), les coefficients de TOUS les
arcs du scenario sont mis a l'echelle en consequence avant le tour 0 ; le
manifeste est recopie tel quel dans le dossier de sortie du run (provenance).

``--rollout`` : active le rattachement des previsions (U9,
``supplyscore.services.forecast.ForecastService``, optionnel) a chaque
snapshot. Si l'unite U9 n'est pas fusionnee dans cette worktree, la commande
echoue proprement (message en francais) avant toute ecriture.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import _common
import export_state
import inject_tour
import setup_scenario
from _common import FACILITATOR, PROJECT_ID, scenario


def _import_behavior(spec: str):
    """Resout ``--behavior module:fonction`` en callable ``respond`` (contrat 2).

    Raises:
        ValueError: specification malformee, module ou fonction introuvable
            (message en francais ; ``main`` la traduit en REFUS + code 2 -
            convention de ce script, cf. ``setup_scenario``/``inject_tour``).
    """
    module_name, sep, func_name = spec.partition(":")
    if not sep or not module_name or not func_name:
        raise ValueError(f"--behavior invalide (attendu 'module:fonction'), reçu {spec!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"--behavior : module {module_name!r} introuvable ({exc})") from exc
    try:
        return getattr(module, func_name)
    except AttributeError as exc:
        raise ValueError(
            f"--behavior : {func_name!r} introuvable dans le module {module_name!r}"
        ) from exc


def _apply_variant(service, prepared_dir: Path) -> dict | None:
    """Met a l'echelle beta/gamma de tous les arcs depuis ``variant_manifest.json``.

    No-op silencieux si le fichier est absent (scenario nominal, cas de loin
    le plus frequent). Ecrit via ``upsert_arc`` (audit + validation des
    bornes [0, 1] incluses).
    """
    manifest_path = Path(prepared_dir) / "variant_manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    beta_scale = float(manifest.get("beta_scale", 1.0))
    gamma_scale = float(manifest.get("gamma_scale", 1.0))
    arcs = list(service.registry.list_arcs())
    for arc in arcs:
        service.mutations.upsert_arc(
            dataclasses.replace(arc, beta=arc.beta * beta_scale, gamma=arc.gamma * gamma_scale),
            source="scenario",
            operator_id=FACILITATOR,
        )
    print(f"  [variant] beta x{beta_scale}, gamma x{gamma_scale} ({len(arcs)} arcs)")
    return manifest


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


#: Horizon des previsions rattachees aux snapshots, en semaines. Aligne sur ``experiment/run_experiment.py`` pour que les campagnes synthetiques et les bras LLM soient scorables avec le meme outil. Balayable via ``SUPPLYSCORE_HORIZON_PREVISION``.
HORIZON_PREVISION: int = _horizon_env(4)

#: Budget de trajectoires du rollout (arrondi a K-floor(n/K) par le service).
N_DRAWS_PREVISION: int = 500


def _augment_forecast(service, forecast_cls, data: dict, run_dir: Path, tour: int) -> None:
    """Ajoute ``forecast`` par noeud au snapshot, et une ligne au journal.

    Ecrit exactement les memes champs que ``experiment/run_experiment.py``
    (``p_issue`` par horizon, ``p_jalon_rate``, ``p_impact_client``, ``spread``,
    ``ur_local``, ``d1_ur_local``), pour que les snapshots d'une campagne
    synthetique se scorent avec le meme outil que ceux des bras LLM.

    Deux natures d'echec, traitees differemment :

    - ``ValueError`` - historique hebdomadaire trop court. C'est le cas
      NORMAL des premiers tours : journalise, la campagne continue.
    - toute autre exception - l'API du service ne correspond plus a cet
      appel. C'est un defaut de programmation, pas une condition de terrain :
      il interrompt, parce que ``--rollout`` a ete demande explicitement et
      qu'une campagne sans previsions ne repond alors pas a la demande.

    La version precedente attrapait les deux, et un renommage d'API a produit
    dix-neuf tours sans une seule prevision sans que rien n'echoue.
    """
    forecast_service = forecast_cls(service)
    try:
        resultat = forecast_service.rollout(
            PROJECT_ID,
            horizon_weeks=HORIZON_PREVISION,
            n_draws=N_DRAWS_PREVISION,
            seed=0,
        )
    except ValueError as exc:  # historique insuffisant : normal aux premiers tours
        print(f"  [forecast indisponible] {exc}")
        return

    journal = run_dir / "predictions_log.jsonl"
    lignes: list[str] = []
    for node_id, par_horizon in resultat.previsions.items():
        if node_id not in data["nodes"]:
            continue
        reference = par_horizon[HORIZON_PREVISION]
        _, valeurs = forecast_service._serie_hebdo(node_id)
        delta = float(valeurs[-1] - valeurs[-2]) if valeurs.size >= 2 else None
        champs = {
            "p_issue": {str(k): p.p_issue for k, p in par_horizon.items()},
            "ic80_h4": [reference.ic80.bas, reference.ic80.haut],
            "se_mc": reference.se_mc,
            "spread": reference.spread,
            "p_jalon_rate": reference.p_jalon_rate,
            "p_impact_client": reference.p_impact_client,
            "ur_local": float(valeurs[-1]) if valeurs.size else None,
            "d1_ur_local": delta,
        }
        data["nodes"][node_id]["forecast"] = champs
        entree = {"arm": "synthetique", "tour": tour, "node_id": node_id,
                  "spread": champs["spread"], "p_jalon_rate": champs["p_jalon_rate"],
                  "p_impact_client": champs["p_impact_client"],
                  "ur_local": champs["ur_local"], "d1_ur_local": champs["d1_ur_local"]}
        for k, proba in champs["p_issue"].items():
            entree[f"p_issue_h{k}"] = proba
        lignes.append(json.dumps(entree, ensure_ascii=False))

    path = run_dir / f"tour_{tour:02d}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with journal.open("a", encoding="utf-8") as flux:
        flux.write("\n".join(lignes) + "\n")
    print(f"  [forecast] {len(lignes)} nœuds rattachés à {path}")


def _check_rollout(rollout: bool):
    """``--rollout`` : importe ``ForecastService`` (U9) ou echoue proprement.

    Returns:
        La classe ``ForecastService`` si ``--rollout`` et disponible ; None
        si ``--rollout`` n'est pas demande ; ``"MISSING"`` si demande mais
        l'unite U9 n'est pas fusionnee (l'appelant doit alors sortir en
        erreur SANS rien ecrire).
    """
    if not rollout:
        return None
    try:
        from supplyscore.services.forecast import ForecastService
    except ImportError:
        print(
            "REFUS : --rollout demandé mais supplyscore.services.forecast est "
            "introuvable — l'unité U9 (prévision) n'est pas fusionnée dans "
            "cette worktree."
        )
        return "MISSING"
    return ForecastService


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI : joue la campagne T0..``--tours`` et retourne un code de sortie."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--prepared",
        type=Path,
        default=_common.PREPARED,
        help="Dossier de données préparées, LECTURE SEULE (défaut : data/prepared)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Dossier de sortie de la campagne (créé au besoin)",
    )
    parser.add_argument("--seed", type=int, default=0, help="Graine de la campagne (défaut 0)")
    parser.add_argument(
        "--tours",
        type=int,
        default=scenario.N_TOURS,
        help=f"Dernier tour joué, inclus (défaut {scenario.N_TOURS})",
    )
    parser.add_argument(
        "--behavior",
        default=None,
        help="Callback déclarant 'module:fonction' (défaut : profils synthétiques)",
    )
    parser.add_argument(
        "--rollout",
        action="store_true",
        help="Rattache les prévisions (U9) à chaque snapshot",
    )
    parser.add_argument(
        "--db-dir",
        type=Path,
        default=None,
        help="Conserve la base de campagne ici au lieu d'un dossier temporaire purgé. "
             "Sans elle, la campagne ne laisse que des fichiers : le projet n'est pas "
             "réouvrable dans l'application, donc ni l'explication par nœud, ni la "
             "criticité, ni l'export ne sont accessibles après coup.",
    )
    args = parser.parse_args(argv)

    if not (0 <= args.tours <= scenario.N_TOURS):
        print(f"REFUS : --tours doit être dans [0, {scenario.N_TOURS}], reçu {args.tours}.")
        return 2

    forecast_cls = _check_rollout(args.rollout)
    if forecast_cls == "MISSING":
        return 2

    try:
        respond = _import_behavior(args.behavior) if args.behavior else None
    except ValueError as exc:
        print(f"REFUS : {exc}")
        return 2

    if not Path(args.prepared).is_dir():
        print(f"REFUS : dossier --prepared introuvable : {args.prepared}")
        return 2

    # ``run_<seed>/`` est un dossier ENTIEREMENT possede par ce script : purge avant chaque run pour qu'un ``--tours`` plus petit qu'un run precedent ne laisse pas de tour_NN.json perimes (faux air de campagne plus longue).
    run_dir = Path(args.out) / f"run_{args.seed}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(args.prepared) / "variant_manifest.json"
    if manifest_path.exists():
        shutil.copy2(manifest_path, run_dir / "variant_manifest.json")

    # Base persistante si --db-dir : le projet reste ouvrable dans l'application
    # (explication par noeud, criticite, export). Sinon dossier temporaire purge,
    # comportement historique.
    persistante = args.db_dir is not None
    if persistante:
        args.db_dir.mkdir(parents=True, exist_ok=True)
        db_dir = str(args.db_dir)
    else:
        db_dir = tempfile.mkdtemp(prefix="campaign_")
    try:
        rc = setup_scenario.main(["--db-dir", db_dir])
        if rc != 0:
            print("REFUS : setup_scenario.py a échoué — campagne non jouée.")
            return rc

        service = _common.open_service(db_dir)
        try:
            _apply_variant(service, args.prepared)
            service.set_lead_time_mode(PROJECT_ID, "monte_carlo", graine=args.seed)

            for tour in range(0, args.tours + 1):
                print(f"--- Tour {tour} ---")
                if tour > 0:
                    from supplyscore.services.events import EventEngine

                    engine = EventEngine(service)
                    for spec in scenario.NODES:
                        engine.apply_weekly_decay(spec["id"], operator_id=FACILITATOR)

                kpi_rows, events, milestones = inject_tour._load_tour_files(
                    tour, prepared_dir=args.prepared
                )
                inject_tour._inject_kpis(service, kpi_rows)
                inject_tour._inject_milestones(service, milestones)
                inject_tour._inject_events(service, events)
                inject_tour._submit_synthetic_ahp(
                    service,
                    tour,
                    respond=respond,
                    prepared_dir=args.prepared,
                    seed=args.seed,
                )
                service.advance_week(PROJECT_ID, n=1)

                data = export_state.snapshot(db_dir, service, tour, out_dir=run_dir)
                if forecast_cls is not None:
                    _augment_forecast(service, forecast_cls, data, run_dir, tour)
        finally:
            service.close()
    finally:
        if persistante:
            print(f"Base de campagne conservée : {db_dir}")
        else:
            shutil.rmtree(db_dir, ignore_errors=True)

    print(f"Campagne terminée : {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
