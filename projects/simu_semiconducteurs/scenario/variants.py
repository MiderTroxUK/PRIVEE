"""Generateur de variantes du scenario HELIOS (U4) - perturbations reproductibles.

Objectif : produire, a partir du pack gele ``data/prepared/`` (source UNIQUE,
jamais modifiee), des copies perturbees avec verite terrain connue, pour
rejouer des centaines de campagnes HELIOS-like en usine de simulation.

Sortie par graine (dans ``--out/seed_NNN/``) : la mise en page EXACTE de
``data/prepared/`` - ``tour_NN.csv``, ``events_NN.json``, ``milestones_NN.json``
pour la meme plage de tours que la source (0..N_TOURS) - plus
``variant_manifest.json`` :

    {
      "seed": int,
      "params": {...hyperparametres FIXES des perturbations...},
      "beta_scale": float,
      "gamma_scale": float,
      "events_truth": {"<tour>": [{"node": str, "type": str, "gravite": str}]}
    }

``params`` documente les hyperparametres (constants pour toute graine non
nulle) - pas une trace de chaque tirage individuel : celle-ci est deja
integralement reproductible via (graine + algorithme ci-dessous), et une
trace complete (des centaines de tirages) n'apporterait rien de plus.
``events_truth`` reflete le calendrier RESULTANT (perturbe), jamais le
nominal ; seuls les tours avec au moins un evenement y figurent. ``gravite``
est lu dans ``params`` de chaque evenement ; les types sans champ ``gravite``
(cf. ``EVENT_CALIBRATION`` dans ``supplyscore/domain/events.py`` : seuls
``panne_machine``, ``accident``, ``alerte_financiere_fournisseur`` en ont un)
recoivent ``"n/a"`` - documente, jamais invente.

GRAINE 0 = IDENTITE STRICTE : aucun tirage, copie octet-a-octet du pack
source (memes fichiers, meme contenu). Voir ``--selftest``.

Usage :
    python variants.py --seeds 1..20 --out DIR
    python variants.py --seeds 1,4,7 --out DIR
    python variants.py --selftest

--- Ordre FIXE des tirages (un seul `random.Random(seed)`, jamais recree) ---

Toutes les perturbations puisent DANS CET ORDRE dans le meme generateur, pour
une reproductibilite bit-a-bit a graine fixee :

1. KPIs (``_perturb_kpis``) - tours 0..N_TOURS croissants, puis lignes de
   ``tour_NN.csv`` dans l'ordre du fichier source : 1 tirage
   ``rng.gauss(0, KPI_NOISE_SIGMA)`` par ligne (bruit multiplicatif
   log-normal ``exp(N(0, 0.1))``). Lissage EMA (rho=0.5) par cle
   ``(node_id, kpi_path)`` au fil de ses apparitions reelles (une serie qui
   saute des tours se lisse entre ses apparitions, pas tour a tour). Bornes
   physiques appliquees via ``supplyscore.domain.constraints.clamp_kpi_value``
   (source de verite unique des bornes - oee.*/risk.failure_probability dans
   [0,1], jamais negatif) - sur la valeur ECRITE ET sur l'etat EMA reporte,
   pour qu'aucun etat interne hors-bornes ne "contamine" les tours suivants.

2. Evenements (``_perturb_events``) - tours 1..N_TOURS croissants (T0 est le
   tour d'entrainement fictif, toujours sans evenement, jamais parcouru).
   Pour chaque tour, DANS CET ORDRE :
   a. les evenements SOURCE de ce tour, dans l'ordre du fichier ; pour
      chacun, DANS CET ORDRE : 1 tirage ``rng.randint(-1, 1)`` (jitter de
      tour, uniforme sur {-1,0,+1}) puis 1 tirage ``rng.random()`` (dropout,
      abandonne si < 0.1). Un evenement conserve est deplace au tour
      ``clamp(tour + jitter, 1, N_TOURS)`` avec ses ``params``/``note``
      inchanges (seule sa date bouge).
   b. 1 tirage ``rng.random()`` pour la probabilite d'evenement
      supplementaire ce tour ; si < 0.05 : 1 tirage ``rng.choice`` sur le
      pool trie des types presents dans le calendrier source, 1 tirage
      ``rng.choice`` sur les noeuds (ordre ``scenario.NODES``), 1 tirage
      ``rng.choice`` sur les occurrences source de ce type pour copier des
      ``params`` valides (gabarit).
   ``events_truth`` (manifeste) est derive de ce calendrier RESULTANT.

3. Arcs (``_perturb_arcs``) - 1 tirage ``rng.uniform(0.8, 1.2)`` pour
   ``beta_scale``, PUIS 1 tirage ``rng.uniform(0.8, 1.2)`` pour
   ``gamma_scale``. Ecrits SEULEMENT dans le manifeste (le moteur de
   campagne les applique ; les arcs ne vivent pas dans ``prepared/``).

4. Jalons (``_perturb_milestones``) - jalons dans l'ordre de premiere
   apparition dans le pack source (tour croissant, ordre du fichier - pour
   HELIOS, equivalent a l'ordre de ``scenario.MILESTONES`` puisque les 18
   jalons apparaissent tous des T0) ; pour chaque jalon, ses occurrences
   ACTIVES dans l'ordre croissant des tours : 1 tirage
   ``rng.uniform(0.7, 1.3)`` chacune, qui multiplie le DELTA de progression
   par rapport a l'occurrence active precedente (delta = progress_source(t) -
   progress_source(t-1)) ; la progression perturbee cumule ces deltas
   mis a l'echelle, bornee a [0, 0.999[ (jamais 1.0 avant la transition
   "done" reelle). Les occurrences "done" NE TIRENT RIEN : recopiees telles
   quelles du pack source (meme tour, meme progress=1.0) - un jalon ne
   redevient jamais actif apres avoir ete marque termine, et la transition
   elle-meme n'est jamais rejouee (regle explicite : "never un-finish a
   milestone"). Le champ ``deadline_wk`` (re-planification), quand present,
   est recopie inchange.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import random
import shutil
import sys
import tempfile
from pathlib import Path

import scenario  # module voisin (projects/.../scenario/scenario.py)

from supplyscore.domain.constraints import clamp_kpi_value

PREPARED = Path(__file__).resolve().parent.parent / "data" / "prepared"
N_TOURS = scenario.N_TOURS  # 18 (+ T0 d'entrainement = 19 tours au total)
NODE_IDS: list[str] = [n["id"] for n in scenario.NODES]  # ordre stable

# Hyperparametres des perturbations (constants, documentes au manifeste)

KPI_NOISE_SIGMA = 0.1
KPI_EMA_RHO = 0.5
EVENTS_JITTER_TOURS = 1
EVENTS_DROPOUT_P = 0.1
EVENTS_EXTRA_P = 0.05
MILESTONE_DRIFT_SCALE = (0.7, 1.3)
ARC_SCALE = (0.8, 1.2)


def _manifest_params() -> dict[str, float]:
    return {
        "kpi_noise_sigma": KPI_NOISE_SIGMA,
        "kpi_ema_rho": KPI_EMA_RHO,
        "events_jitter_tours": EVENTS_JITTER_TOURS,
        "events_dropout_p": EVENTS_DROPOUT_P,
        "events_extra_p": EVENTS_EXTRA_P,
        "milestone_drift_scale_min": MILESTONE_DRIFT_SCALE[0],
        "milestone_drift_scale_max": MILESTONE_DRIFT_SCALE[1],
        "arc_scale_min": ARC_SCALE[0],
        "arc_scale_max": ARC_SCALE[1],
    }


# Lecture du pack source (data/prepared/, lecture SEULE, jamais modifie)


def _read_tour_csv(tour: int) -> list[dict[str, str]]:
    with (PREPARED / f"tour_{tour:02d}.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_json(name: str) -> list[dict]:
    return json.loads((PREPARED / name).read_text(encoding="utf-8"))


def _load_all_sources() -> tuple[
    dict[int, list[dict[str, str]]], dict[int, list[dict]], dict[int, list[dict]]
]:
    """Charge une seule fois le pack source (reutilise pour toutes les graines)."""
    kpi_rows = {t: _read_tour_csv(t) for t in range(0, N_TOURS + 1)}
    events = {t: _read_json(f"events_{t:02d}.json") for t in range(0, N_TOURS + 1)}
    milestones = {t: _read_json(f"milestones_{t:02d}.json") for t in range(0, N_TOURS + 1)}
    return kpi_rows, events, milestones


# 1. KPIs


def _perturb_kpis(
    rng: random.Random, kpi_rows: dict[int, list[dict[str, str]]]
) -> dict[int, list[tuple[str, str, float]]]:
    """Bruit log-normal multiplicatif + lissage EMA (rho=0.5). Voir docstring module."""
    ema_state: dict[tuple[str, str], float] = {}
    out: dict[int, list[tuple[str, str, float]]] = {}
    for tour in range(0, N_TOURS + 1):
        written: list[tuple[str, str, float]] = []
        for row in kpi_rows[tour]:
            node_id, kpi_path = row["node_id"], row["kpi_path"]
            valeur = float(row["valeur"])
            noisy = valeur * math.exp(rng.gauss(0.0, KPI_NOISE_SIGMA))
            key = (node_id, kpi_path)
            prev = ema_state.get(key)
            smoothed = noisy if prev is None else (KPI_EMA_RHO * prev + (1.0 - KPI_EMA_RHO) * noisy)
            smoothed = clamp_kpi_value(kpi_path, smoothed)
            ema_state[key] = smoothed
            written.append((node_id, kpi_path, round(smoothed, 4)))
        out[tour] = written
    return out


# 2. Evenements


def _event_type_pool(source_events: dict[int, list[dict]]) -> list[str]:
    """Types distincts du calendrier source, tries (ordre deterministe)."""
    return sorted({ev["type"] for evs in source_events.values() for ev in evs})


def _event_templates_by_type(source_events: dict[int, list[dict]]) -> dict[str, list[dict]]:
    """Occurrences source par type, dans l'ordre tour croissant / fichier."""
    templates: dict[str, list[dict]] = {}
    for tour in sorted(source_events):
        for ev in source_events[tour]:
            templates.setdefault(ev["type"], []).append(ev)
    return templates


def _perturb_events(
    rng: random.Random, source_events: dict[int, list[dict]]
) -> dict[int, list[dict]]:
    """Jitter +/-1 tour, dropout p=0.1, evenement supplementaire p=0.05/tour."""
    type_pool = _event_type_pool(source_events)
    templates = _event_templates_by_type(source_events)
    perturbed: dict[int, list[dict]] = {t: [] for t in range(0, N_TOURS + 1)}

    for tour in range(1, N_TOURS + 1):
        for ev in source_events.get(tour, []):
            jitter = rng.randint(-EVENTS_JITTER_TOURS, EVENTS_JITTER_TOURS)
            dropped = rng.random() < EVENTS_DROPOUT_P
            if dropped:
                continue
            new_tour = min(max(tour + jitter, 1), N_TOURS)
            perturbed[new_tour].append(copy.deepcopy(ev))

        if rng.random() < EVENTS_EXTRA_P and type_pool:
            ev_type = rng.choice(type_pool)
            node_id = rng.choice(NODE_IDS)
            template = rng.choice(templates[ev_type])
            perturbed[tour].append(
                {
                    "node": node_id,
                    "type": ev_type,
                    "params": copy.deepcopy(template["params"]),
                    "note": "Événement synthétique (variants.py) — paramètres "
                    "repris d'une occurrence source du même type.",
                }
            )
    return perturbed


def _events_truth(perturbed_events: dict[int, list[dict]]) -> dict[str, list[dict]]:
    """Verite terrain derivee du calendrier RESULTANT (jamais le nominal)."""
    truth: dict[str, list[dict]] = {}
    for tour in sorted(perturbed_events):
        evs = perturbed_events[tour]
        if not evs:
            continue
        truth[str(tour)] = [
            {"node": ev["node"], "type": ev["type"], "gravite": ev["params"].get("gravite", "n/a")}
            for ev in evs
        ]
    return truth


# 3. Arcs


def _perturb_arcs(rng: random.Random) -> tuple[float, float]:
    beta_scale = round(rng.uniform(*ARC_SCALE), 4)
    gamma_scale = round(rng.uniform(*ARC_SCALE), 4)
    return beta_scale, gamma_scale


# 4. Jalons


def _milestone_identity_order(source_milestones: dict[int, list[dict]]) -> list[tuple[str, str]]:
    """Ordre de premiere apparition (tour croissant, ordre fichier) - deterministe."""
    seen: dict[tuple[str, str], None] = {}
    for tour in sorted(source_milestones):
        for m in source_milestones[tour]:
            seen.setdefault((m["node"], m["name"]), None)
    return list(seen.keys())


def _perturb_milestones(
    rng: random.Random, source_milestones: dict[int, list[dict]]
) -> dict[int, list[dict]]:
    """Delta de progression mis a l'echelle x U(0.7, 1.3), jalon par jalon."""
    identity_order = _milestone_identity_order(source_milestones)

    trajectories: dict[tuple[str, str], list[tuple[int, dict]]] = {k: [] for k in identity_order}
    for tour in sorted(source_milestones):
        for m in source_milestones[tour]:
            trajectories[(m["node"], m["name"])].append((tour, m))

    perturbed_by_key: dict[tuple[str, str], dict[int, dict]] = {}
    for key in identity_order:
        prev_orig = 0.0
        prev_pert = 0.0
        by_tour: dict[int, dict] = {}
        for tour, entry in trajectories[key]:
            if entry.get("status") == "done":
                by_tour[tour] = dict(entry)  # transition recopiee, jamais rejouee
                continue
            orig_progress = float(entry["progress"])
            delta = orig_progress - prev_orig
            scale = rng.uniform(*MILESTONE_DRIFT_SCALE)
            pert_progress = min(max(prev_pert + delta * scale, 0.0), 0.999)
            new_entry = dict(entry)
            new_entry["progress"] = round(pert_progress, 3)
            by_tour[tour] = new_entry
            prev_orig = orig_progress
            prev_pert = pert_progress
        perturbed_by_key[key] = by_tour

    out: dict[int, list[dict]] = {t: [] for t in range(0, N_TOURS + 1)}
    for tour in range(0, N_TOURS + 1):
        for key in identity_order:
            entry = perturbed_by_key[key].get(tour)
            if entry is not None:
                out[tour].append(entry)
    return out


# Ecriture de la mise en page data/prepared/


def _write_layout(
    out_dir: Path,
    kpi_by_tour: dict[int, list[tuple[str, str, float]]],
    events_by_tour: dict[int, list[dict]],
    milestones_by_tour: dict[int, list[dict]],
) -> None:
    for tour in range(0, N_TOURS + 1):
        csv_path = out_dir / f"tour_{tour:02d}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["node_id", "kpi_path", "valeur"])
            writer.writerows(kpi_by_tour.get(tour, []))

        (out_dir / f"events_{tour:02d}.json").write_text(
            json.dumps(events_by_tour.get(tour, []), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / f"milestones_{tour:02d}.json").write_text(
            json.dumps(milestones_by_tour.get(tour, []), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _write_manifest(
    out_dir: Path, seed: int, beta_scale: float, gamma_scale: float, events_truth: dict
) -> None:
    manifest = {
        "seed": seed,
        "params": _manifest_params(),
        "beta_scale": beta_scale,
        "gamma_scale": gamma_scale,
        "events_truth": events_truth,
    }
    (out_dir / "variant_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# Generation par graine


def _generate_identity(out_dir: Path, source_events: dict[int, list[dict]]) -> None:
    """Graine 0 : copie octet-a-octet du pack source, AUCUN tirage."""
    for tour in range(0, N_TOURS + 1):
        for name in (
            f"tour_{tour:02d}.csv",
            f"events_{tour:02d}.json",
            f"milestones_{tour:02d}.json",
        ):
            shutil.copyfile(PREPARED / name, out_dir / name)
    _write_manifest(
        out_dir, seed=0, beta_scale=1.0, gamma_scale=1.0, events_truth=_events_truth(source_events)
    )


def generate_seed(
    seed: int,
    out_dir: Path,
    kpi_rows: dict[int, list[dict[str, str]]],
    source_events: dict[int, list[dict]],
    source_milestones: dict[int, list[dict]],
) -> None:
    """Genere une graine complete sous ``out_dir`` (cree si absent)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if seed == 0:
        _generate_identity(out_dir, source_events)
        return

    rng = random.Random(seed)
    kpi_by_tour = _perturb_kpis(rng, kpi_rows)  # 1. KPIs
    events_by_tour = _perturb_events(rng, source_events)  # 2. Evenements
    beta_scale, gamma_scale = _perturb_arcs(rng)  # 3. Arcs
    milestones_by_tour = _perturb_milestones(rng, source_milestones)  # 4. Jalons

    _write_layout(out_dir, kpi_by_tour, events_by_tour, milestones_by_tour)
    _write_manifest(out_dir, seed, beta_scale, gamma_scale, _events_truth(events_by_tour))


# CLI


def _parse_seeds(spec: str) -> list[int]:
    """Parse ``"a..b"`` (plage incluse), ``"1,2,5"`` (liste) ou un entier seul."""
    spec = spec.strip()
    if ".." in spec:
        a_str, b_str = spec.split("..", 1)
        a, b = int(a_str.strip()), int(b_str.strip())
        if a > b:
            raise ValueError(f"plage vide : {a}..{b} (borne basse > borne haute)")
        return list(range(a, b + 1))
    if "," in spec:
        return [int(s.strip()) for s in spec.split(",") if s.strip()]
    return [int(spec)]


def _selftest() -> int:
    """Verifie la graine 0 contre le pack source.

    Genere la graine 0 dans un dossier temporaire et diffe octet-a-octet
    contre ``data/prepared/``. Message en francais, code de sortie 0 (OK)
    ou 1 (echec).
    """
    kpi_rows, source_events, source_milestones = _load_all_sources()
    with tempfile.TemporaryDirectory(prefix="helios_variants_selftest_") as tmp:
        tmp_path = Path(tmp)
        generate_seed(0, tmp_path, kpi_rows, source_events, source_milestones)

        mismatches: list[str] = []
        checked = 0
        for tour in range(0, N_TOURS + 1):
            for name in (
                f"tour_{tour:02d}.csv",
                f"events_{tour:02d}.json",
                f"milestones_{tour:02d}.json",
            ):
                checked += 1
                if (PREPARED / name).read_bytes() != (tmp_path / name).read_bytes():
                    mismatches.append(name)

        if mismatches:
            print("ÉCHEC --selftest : fichiers différents de data/prepared/ (graine 0) :")
            for name in mismatches:
                print(f"  - {name}")
            return 1
        print(
            f"OK --selftest : graine 0 identique octet-à-octet à data/prepared/ "
            f"({checked} fichiers vérifiés)."
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI : ``--seeds``/``--out`` pour generer, ou ``--selftest``."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows cp1252

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", help='Graines à générer : "1..20", "1,2,5" ou "3"')
    parser.add_argument("--out", help="Dossier de sortie (un sous-dossier seed_NNN par graine)")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Vérifie que la graine 0 est identique octet-à-octet à data/prepared/",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.seeds or not args.out:
        parser.error("--seeds et --out sont requis (sauf avec --selftest)")

    try:
        seeds = _parse_seeds(args.seeds)
    except ValueError:
        parser.error(f'--seeds invalide : {args.seeds!r} (attendu "a..b", "1,2,5" ou "3")')

    kpi_rows, source_events, source_milestones = _load_all_sources()
    out_root = Path(args.out)
    for seed in seeds:
        seed_dir = out_root / f"seed_{seed:03d}"
        generate_seed(seed, seed_dir, kpi_rows, source_events, source_milestones)
        print(f"graine {seed} -> {seed_dir}")
    print(f"{len(seeds)} variante(s) écrite(s) sous {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
