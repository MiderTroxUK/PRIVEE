"""Runner de campagne HÉLIOS headless, en-process (U5).

Usage :
    python run_campaign.py --out DIR [--prepared DIR] [--seed S] [--tours N]
                            [--behavior module:fonction] [--rollout]

Joue une campagne HÉLIOS complète (T0..N) sans serveur ni saisie humaine, en
un seul process Python. À chaque tour : décroissance hebdomadaire (t > 0),
injection KPIs/jalons/événements, puis une déclaration AHP par nœud — soit
les profils synthétiques historiques (défaut, identique à
``inject_tour.py --dry-run-ahp``), soit un callback « déclarant » fourni via
``--behavior module:fonction`` (contrat 2 du plan v7 : voir
``inject_tour._submit_synthetic_ahp``). Un snapshot ``tour_NN.json`` est
écrit par tour dans ``OUT/run_<seed>/`` (réutilise ``export_state.snapshot``).

Base de données : créée dans un dossier temporaire propre à ce run et purgée
à la fin — la campagne ne touche jamais ``data/prepared`` (lecture seule, cf.
``--prepared``) ni un db-dir partagé avec d'autres campagnes.

Variantes : si ``--prepared`` contient un ``variant_manifest.json``
(``{"beta_scale": ..., "gamma_scale": ...}``), les coefficients de TOUS les
arcs du scénario sont mis à l'échelle en conséquence avant le tour 0 ; le
manifeste est recopié tel quel dans le dossier de sortie du run (provenance).

``--rollout`` : active le rattachement des prévisions (U9,
``supplyscore.services.forecast.ForecastService``, optionnel) à chaque
snapshot. Si l'unité U9 n'est pas fusionnée dans cette worktree, la commande
échoue proprement (message en français) avant toute écriture.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
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
    """Résout ``--behavior module:fonction`` en callable ``respond`` (contrat 2).

    Raises:
        ValueError: spécification malformée, module ou fonction introuvable
            (message en français ; ``main`` la traduit en REFUS + code 2 —
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
    """Met à l'échelle beta/gamma de tous les arcs depuis ``variant_manifest.json``.

    No-op silencieux si le fichier est absent (scénario nominal, cas de loin
    le plus fréquent). Écrit via ``upsert_arc`` (audit + validation des
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


def _augment_forecast(service, forecast_cls, data: dict, run_dir: Path, tour: int) -> None:
    """Ajoute ``forecast`` par nœud au snapshot déjà écrit (contrat 7, U9, best effort).

    L'API de ``ForecastService`` n'est pas stabilisée au moment où U5 est
    écrite (U9 non fusionnée dans cette worktree) : cet appel est protégé —
    un échec (signature différente une fois U9 réellement disponible) laisse
    le tour exporté SANS le champ ``forecast`` plutôt que de faire échouer
    toute la campagne, et journalise la cause.
    """
    try:
        forecast_service = forecast_cls(service)
        for node_id in data["nodes"]:
            result = forecast_service.forecast_node(PROJECT_ID, node_id)
            data["nodes"][node_id]["forecast"] = {
                str(horizon): dict(values) for horizon, values in result.items()
            }
        path = run_dir / f"tour_{tour:02d}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [forecast] ajouté à {path}")
    except Exception as exc:  # best effort : API U9 non figée, ne bloque jamais la campagne
        print(f"  [forecast ÉCHEC] {type(exc).__name__}: {exc}")


def _check_rollout(rollout: bool):
    """``--rollout`` : importe ``ForecastService`` (U9) ou échoue proprement.

    Returns:
        La classe ``ForecastService`` si ``--rollout`` et disponible ; None
        si ``--rollout`` n'est pas demandé ; ``"MISSING"`` si demandé mais
        l'unité U9 n'est pas fusionnée (l'appelant doit alors sortir en
        erreur SANS rien écrire).
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
    """Point d'entrée CLI : joue la campagne T0..``--tours`` et retourne un code de sortie."""
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

    # ``run_<seed>/`` est un dossier ENTIÈREMENT possédé par ce script : purgé
    # avant chaque run pour qu'un ``--tours`` plus petit qu'un run précédent
    # ne laisse pas de tour_NN.json périmés (faux air de campagne plus longue).
    run_dir = Path(args.out) / f"run_{args.seed}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(args.prepared) / "variant_manifest.json"
    if manifest_path.exists():
        shutil.copy2(manifest_path, run_dir / "variant_manifest.json")

    db_dir = tempfile.mkdtemp(prefix="helios_campaign_")
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
        shutil.rmtree(db_dir, ignore_errors=True)

    print(f"Campagne terminée : {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
