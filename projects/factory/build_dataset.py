"""Constructeur de dataset personne-periode (U8) + extraction du journal d'interventions.

Consomme les artefacts geles produits par les autres unites HELIOS v7 (voir
plan v7, unites U4/U5/U6) sous un dossier ``--runs`` parcouru recursivement :
tout dossier contenant des fichiers ``tour_NN.json`` est traite comme UN run
(``chain_id`` = nom de ce dossier), avec ses fichiers freres optionnels
``variant_manifest.json``, ``dgp_manifest.json`` et ``interventions_truth.jsonl``.

Deux sorties independantes :

OUTPUT 1 (dataset personne-periode, transferable)::

    python build_dataset.py --runs DIR --out dataset.csv [--horizon 4] [--append] [--validate]

Une ligne par ``(chain_id, node_id, t)``. AUCUNE feature d'identite :
``chain_id``/``node_id``/``dgp_params_id`` sont des colonnes de GROUPE
seulement, jamais des features de modele. Labels ``y1``/``y{horizon}``
censures a VIDE (jamais 0 silencieux) quand la fenetre d'observation depasse
le dernier tour connu de la chaine. Voir :func:`build_feature_schema` pour le
schema complet (colonnes, dtypes, semantique).

OUTPUT 2 (journal d'interventions agrege)::

    python build_dataset.py --runs DIR --interventions --out interventions.csv [--validate]

Agrege tous les ``interventions_truth.jsonl`` trouves sous ``--runs``. Les
colonnes ``stress_latent``, ``delta_u_vrai`` et ``effet_vrai_param`` sont de
la verite terrain de l'USINE synthetique - marquees VALIDATION_ONLY (ligne de
commentaire en tete de fichier + ``feature_schema.json``) : jamais des
features du modele d'effet (U17), utilisees uniquement pour le scorer.

Decisions de conception documentees (ambiguites du contrat gele tranchees ici) :

- ``dernier tour`` (pour la censure y1/y4) = le plus grand tour parmi les
  ``tour_NN.json`` REELLEMENT presents pour la chaine - jamais deduit de
  l'etendue d'``events_truth`` (qui peut decrire un calendrier plus long que
  ce que la campagne a effectivement joue). Choix conservateur : on ne
  declare jamais une fenetre " entierement observee " a tort.
- ``H`` dans ``d{k}_H`` = ``hidden_risk`` (risque cache), le seul autre champ
  de dynamique demande en plus de ``ur_local``.
- " evenement " (labels y1/y4, dynamique ``event_recent``/``weeks_since_event``,
  posterieur bayesien) = entree ``events_truth`` de gravite dans
  {"critique", "defaut"} - definition UNIQUE reutilisee partout dans ce module.
- ``arcs`` (pour ``in_deg``/``out_deg``/le voisinage) est un champ D'EXTENSION
  optionnel, absent des contrats geles listes : lu defensivement dans
  ``variant_manifest.json`` puis ``dgp_manifest.json`` (``[{"source","target"}]``),
  colonnes vides quand absent - jamais fabrique.
- ``--append`` fusionne par remplacement : les lignes des ``chain_id`` traites
  dans l'appel courant remplacent leurs anciennes lignes dans le fichier
  existant (les autres chaines deja presentes sont conservees telles quelles).
  Rejoue le meme ``--runs`` deux fois de suite => fichier final identique
  (idempotent), sans jamais dupliquer une ligne.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Constantes gelees

SCHEMA_VERSION = 1
N0_BETA = 26.0  # convention depot (supplyscore.domain.events.N0_PSEUDO_OBSERVATIONS)
EMA_RHO = 0.3
QUALIFYING_GRAVITES = frozenset({"critique", "defaut"})  # definition gelee d'un " evenement "
# Blocs KPI de ur_local, cf. supplyscore.core.ur_model.BLOCKS = ("time","cap",...,"co2").
U_BLOC_KEYS = ("u_time", "u_cap", "u_perf", "u_risk", "u_cost", "u_co2")
HIDDEN_RISK_ALIAS = "H"  # alias des colonnes dynamiques d{k}_H = hidden_risk
DEFAULT_HORIZON = 4
HELIOS_DGP_PARAMS_ID = "helios"
VALIDATION_ONLY_INTERVENTION_COLUMNS = ("stress_latent", "delta_u_vrai", "effet_vrai_param")
RESULTAT_TO_SUCCES = {"resolu": 1, "echec": 0}

TOUR_RE = re.compile(r"^tour_(\d+)\.json$")

Json = dict[str, Any]


# Chargement des runs


@dataclass
class RunData:
    """Un run charge : snapshots par tour + manifestes geles (contrats U4/U6)."""

    chain_id: str
    snapshots: dict[int, Json] = field(default_factory=dict)  # tour -> {"nodes", "criticite"}
    events_truth: dict[int, list[Json]] = field(default_factory=dict)  # tour -> [{"node",...}]
    dgp_params_id: str = HELIOS_DGP_PARAMS_ID
    arcs: list[tuple[str, str]] | None = None  # None = inconnus ; [] = connus, reseau sans arc


def _read_json(path: Path) -> Json:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl(path: Path) -> list[Json]:
    records: list[Json] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def discover_runs(runs_root: Path) -> dict[str, Path]:
    """Trouve chaque dossier de run sous ``runs_root`` (recursif).

    Un dossier de run = tout dossier contenant au moins un ``tour_NN.json``.
    ``chain_id`` = nom de ce dossier ; doit etre unique sous ``runs_root``.
    """
    found: dict[str, Path] = {}
    for path in sorted(runs_root.rglob("tour_*.json")):
        if not TOUR_RE.match(path.name):
            continue
        run_dir = path.parent
        chain_id = run_dir.name
        previous = found.get(chain_id)
        if previous is not None and previous != run_dir:
            raise ValueError(
                f"chain_id en collision : « {chain_id} » désigne à la fois {previous} et "
                f"{run_dir} — les identifiants de run doivent être uniques sous {runs_root}."
            )
        found[chain_id] = run_dir
    return found


def load_run(chain_id: str, run_dir: Path) -> RunData:
    """Charge un run : snapshots + manifestes optionnels, tolere les cles surnumeraires."""
    snapshots: dict[int, Json] = {}
    for path in sorted(run_dir.glob("tour_*.json")):
        m = TOUR_RE.match(path.name)
        if not m:
            continue
        n = int(m.group(1))
        data = _read_json(path)
        tour_field = data.get("tour")
        if tour_field is not None and int(tour_field) != n:
            raise ValueError(
                f"{path} : champ 'tour'={tour_field!r} incohérent avec le nom de fichier "
                f"(attendu {n})."
            )
        snapshots[n] = {"nodes": data.get("nodes", {}), "criticite": data.get("criticite", [])}

    variant_path = run_dir / "variant_manifest.json"
    variant = _read_json(variant_path) if variant_path.exists() else {}
    dgp_path = run_dir / "dgp_manifest.json"
    dgp = _read_json(dgp_path) if dgp_path.exists() else None

    events_truth: dict[int, list[Json]] = {
        int(tour_str): evs for tour_str, evs in variant.get("events_truth", {}).items()
    }

    dgp_params_id = HELIOS_DGP_PARAMS_ID
    if dgp is not None and dgp.get("dgp_params_id"):
        dgp_params_id = str(dgp["dgp_params_id"])

    arcs_raw = variant.get("arcs")
    if arcs_raw is None and dgp is not None:
        arcs_raw = dgp.get("arcs")
    arcs = [(a["source"], a["target"]) for a in arcs_raw] if arcs_raw is not None else None

    return RunData(
        chain_id=chain_id,
        snapshots=snapshots,
        events_truth=events_truth,
        dgp_params_id=dgp_params_id,
        arcs=arcs,
    )


def load_all_runs(runs_root: Path) -> dict[str, RunData]:
    """Decouvre et charge tous les runs sous ``runs_root`` (tries par chain_id)."""
    return {cid: load_run(cid, d) for cid, d in sorted(discover_runs(runs_root).items())}


# Definition d'un " evenement " (gelee, reutilisee partout)


def _has_qualifying_event(events_truth: dict[int, list[Json]], node_id: str, tour: int) -> bool:
    return any(
        ev.get("node") == node_id and ev.get("gravite") in QUALIFYING_GRAVITES
        for ev in events_truth.get(tour, [])
    )


def _any_qualifying_event_in_window(
    events_truth: dict[int, list[Json]], node_id: str, start: int, end: int
) -> bool:
    return any(_has_qualifying_event(events_truth, node_id, t) for t in range(start, end + 1))


def _weeks_since_event(events_truth: dict[int, list[Json]], node_id: str, t: int) -> int | None:
    seen = [
        tau
        for tau, evs in events_truth.items()
        if tau <= t
        and any(e.get("node") == node_id and e.get("gravite") in QUALIFYING_GRAVITES for e in evs)
    ]
    return (t - max(seen)) if seen else None


# Labels y1 / y{horizon} (censure explicite, jamais 0 silencieux)


def _label_y1(
    events_truth: dict[int, list[Json]], node_id: str, t: int, last_tour: int
) -> int | None:
    if t + 1 > last_tour:
        return None
    return 1 if _has_qualifying_event(events_truth, node_id, t + 1) else 0


def _label_censored_window(
    events_truth: dict[int, list[Json]], node_id: str, t: int, horizon: int, last_tour: int
) -> int | None:
    window_end = t + horizon
    observed_end = min(window_end, last_tour)
    if observed_end >= t + 1 and _any_qualifying_event_in_window(
        events_truth, node_id, t + 1, observed_end
    ):
        return 1
    if last_tour >= window_end:
        return 0
    return None  # censure : fenetre non entierement observee et aucun evenement trouve


# Criticite / structure par tour


def _criticite_by_node(snapshot: Json) -> dict[str, Json]:
    """Ignore les sentinelles d'erreur best-effort (ex. ``[{"erreur": "..."}]``)."""
    return {
        c["node_id"]: c
        for c in snapshot.get("criticite", [])
        if isinstance(c, dict) and "node_id" in c
    }


def _predecessors(arcs: list[tuple[str, str]], node_id: str) -> set[str]:
    return {s for s, t in arcs if t == node_id}


def _successors(arcs: list[tuple[str, str]], node_id: str) -> set[str]:
    return {t for s, t in arcs if s == node_id}


def _diff(curr: float | None, prev: float | None) -> float | None:
    return None if curr is None or prev is None else curr - prev


# Posterieur Beta-Bernoulli (prior partage, force N0=26)


def compute_global_base_rate(runs: dict[str, RunData]) -> float:
    """Taux de base d'evenement (noeud-tour) sur l'ensemble des runs - prior partage."""
    total_obs = 0
    total_events = 0
    for run in runs.values():
        for t, snap in run.snapshots.items():
            for node_id in snap["nodes"]:
                total_obs += 1
                if _has_qualifying_event(run.events_truth, node_id, t):
                    total_events += 1
    return (total_events / total_obs) if total_obs else 0.0


def _beta_posterior(alpha0: float, beta0: float, successes: int, n_obs: int) -> tuple[float, float]:
    """Retourne (moyenne, variance) du posterieur Beta(alpha0+succes, beta0+echecs)."""
    a_post = alpha0 + successes
    b_post = beta0 + (n_obs - successes)
    mean = a_post / (a_post + b_post)
    var = (a_post * b_post) / (((a_post + b_post) ** 2) * (a_post + b_post + 1))
    return mean, var


# Construction des lignes du dataset


def _dataset_columns(horizon: int) -> list[str]:
    cols = ["chain_id", "node_id", "dgp_params_id", "y1", f"y{horizon}"]
    cols += ["ud", "ur", "ud_local", "ur_local", "hidden_risk", "false_urgency", "adequation"]
    cols += list(U_BLOC_KEYS)
    cols += [f"d{k}_ur_local" for k in range(1, horizon + 1)]
    cols += [f"d{k}_{HIDDEN_RISK_ALIAS}" for k in range(1, horizon + 1)]
    cols += ["ema_ur_local", "event_recent", "weeks_since_event"]
    cols += ["beta_mean", "beta_var", "beta_n"]
    cols += [
        "p_retard_jalon",
        "p_impact_final",
        "delta_ell_final",
        "delta_ell_max",
        "p_rollout",
        "spread",
    ]
    cols += ["depth_frac", "in_deg", "out_deg", "log_n_nodes", "impact_frac"]
    cols += ["mean_ur_pred", "max_ur_pred", "frac_pred_satures", "mean_beta_in"]
    return cols


def build_rows(run: RunData, alpha0: float, beta0: float, horizon: int) -> list[dict[str, Any]]:
    """Construit toutes les lignes ``(node_id, t)`` d'un run (voisinage NON rempli)."""
    tours_sorted = sorted(run.snapshots)
    if not tours_sorted:
        return []
    last_tour = tours_sorted[-1]

    # Historique par noeud (acces direct par tour, pour les differences arriere indexees).
    node_history: dict[str, dict[int, Json]] = defaultdict(dict)
    for t in tours_sorted:
        for node_id, n in run.snapshots[t]["nodes"].items():
            node_history[node_id][t] = n

    running_ema: dict[str, float] = {}
    running_successes: dict[str, int] = defaultdict(int)
    running_n_obs: dict[str, int] = defaultdict(int)

    rows: list[dict[str, Any]] = []
    for t in tours_sorted:
        snap = run.snapshots[t]
        nodes = snap["nodes"]
        crit = _criticite_by_node(snap)
        n_nodes = len(nodes)
        max_rank = max((n.get("rank", 0) or 0) for n in nodes.values()) if nodes else 0

        for node_id, n in nodes.items():
            row: dict[str, Any] = {
                "chain_id": run.chain_id,
                "node_id": node_id,
                "dgp_params_id": run.dgp_params_id,
                "_tour": t,  # colonne interne, retiree avant ecriture (utile au voisinage)
            }

            row["y1"] = _label_y1(run.events_truth, node_id, t, last_tour)
            row[f"y{horizon}"] = _label_censored_window(
                run.events_truth, node_id, t, horizon, last_tour
            )

            local_keys = (
                "ud", "ur", "ud_local", "ur_local", "hidden_risk", "false_urgency", "adequation",
            )
            for key in local_keys:
                row[key] = n.get(key)

            blocs = n.get("blocs") or {}
            for bk in U_BLOC_KEYS:
                row[bk] = blocs.get(bk)

            hist = node_history[node_id]
            for k in range(1, horizon + 1):
                prev = hist.get(t - k)
                prev_ur_local = prev.get("ur_local") if prev else None
                prev_hidden_risk = prev.get("hidden_risk") if prev else None
                row[f"d{k}_ur_local"] = _diff(n.get("ur_local"), prev_ur_local)
                row[f"d{k}_{HIDDEN_RISK_ALIAS}"] = _diff(n.get("hidden_risk"), prev_hidden_risk)

            ur_local = n.get("ur_local")
            prev_ema = running_ema.get(node_id)
            if ur_local is None:
                ema = None  # jamais impute : l'EMA reste gelee a sa derniere valeur connue
            elif prev_ema is None:
                ema = ur_local
            else:
                ema = EMA_RHO * ur_local + (1.0 - EMA_RHO) * prev_ema
            if ema is not None:
                running_ema[node_id] = ema
            row["ema_ur_local"] = ema

            row["event_recent"] = int(
                _any_qualifying_event_in_window(run.events_truth, node_id, t - 2, t)
            )
            row["weeks_since_event"] = _weeks_since_event(run.events_truth, node_id, t)

            running_n_obs[node_id] += 1
            if _has_qualifying_event(run.events_truth, node_id, t):
                running_successes[node_id] += 1
            beta_mean, beta_var = _beta_posterior(
                alpha0, beta0, running_successes[node_id], running_n_obs[node_id]
            )
            row["beta_mean"] = beta_mean
            row["beta_var"] = beta_var
            row["beta_n"] = running_n_obs[node_id]

            row["p_retard_jalon"] = None  # reservee : aucune unite ne la produit encore
            c = crit.get(node_id)
            row["p_impact_final"] = c.get("p_impact_final") if c else None
            row["delta_ell_final"] = c.get("delta_ell_final") if c else None
            row["delta_ell_max"] = c.get("delta_ell_max") if c else None
            forecast = n.get("forecast") or {}
            fh = forecast.get(str(horizon)) or {}
            row["p_rollout"] = fh.get("p_issue")
            row["spread"] = fh.get("spread")

            rank = n.get("rank", 0) or 0
            row["depth_frac"] = (rank / max_rank) if max_rank else 0.0
            if run.arcs is not None:
                row["in_deg"] = len(_predecessors(run.arcs, node_id))
                row["out_deg"] = len(_successors(run.arcs, node_id))
            else:
                row["in_deg"] = None
                row["out_deg"] = None
            row["log_n_nodes"] = math.log(n_nodes) if n_nodes > 0 else None
            nb_impactes = c.get("nb_impactes") if c else None
            row["impact_frac"] = (
                (nb_impactes / n_nodes) if (nb_impactes is not None and n_nodes > 0) else None
            )

            rows.append(row)

    return rows


def enrich_neighborhood(
    rows_by_chain: dict[str, list[dict[str, Any]]], runs: dict[str, RunData]
) -> None:
    """Remplit les colonnes de voisinage en place (necessite beta_mean deja calcule)."""
    for chain_id, rows in rows_by_chain.items():
        run = runs[chain_id]
        if run.arcs is None:
            for row in rows:
                row["mean_ur_pred"] = None
                row["max_ur_pred"] = None
                row["frac_pred_satures"] = None
                row["mean_beta_in"] = None
            continue

        by_tour_node = {(row["_tour"], row["node_id"]): row for row in rows}
        for row in rows:
            preds = _predecessors(run.arcs, row["node_id"])
            t = row["_tour"]
            pred_rows = [by_tour_node[(t, p)] for p in preds if (t, p) in by_tour_node]
            ur_values = [r["ur"] for r in pred_rows if r["ur"] is not None]
            beta_values = [r["beta_mean"] for r in pred_rows if r["beta_mean"] is not None]
            row["mean_ur_pred"] = statistics.fmean(ur_values) if ur_values else None
            row["max_ur_pred"] = max(ur_values) if ur_values else None
            row["frac_pred_satures"] = (
                sum(1 for v in ur_values if v >= 0.999) / len(ur_values) if ur_values else None
            )
            row["mean_beta_in"] = statistics.fmean(beta_values) if beta_values else None


def build_dataset(runs_root: Path, horizon: int) -> list[dict[str, Any]]:
    """Pipeline complet OUTPUT 1 : decouverte -> chargement -> lignes -> voisinage."""
    runs = load_all_runs(runs_root)
    base_rate = compute_global_base_rate(runs)
    alpha0, beta0 = base_rate * N0_BETA, (1.0 - base_rate) * N0_BETA

    rows_by_chain = {cid: build_rows(run, alpha0, beta0, horizon) for cid, run in runs.items()}
    enrich_neighborhood(rows_by_chain, runs)

    all_rows = [row for rows in rows_by_chain.values() for row in rows]
    for row in all_rows:
        del row["_tour"]
    return all_rows


# Ecriture / lecture CSV (dataset)


def _row_to_csv_dict(row: dict[str, Any], columns: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for col in columns:
        v = row.get(col)
        if v is None:
            out[col] = ""
        elif isinstance(v, bool):
            out[col] = "1" if v else "0"
        else:
            out[col] = str(v)
    return out


def write_dataset_csv(
    rows: list[dict[str, Any]], out_path: Path, horizon: int, append: bool
) -> None:
    """Ecrit ``dataset.csv``. En mode ``--append``, remplace les lignes des chaines traitees."""
    columns = _dataset_columns(horizon)
    chains_written = {row["chain_id"] for row in rows}

    existing_rows: list[dict[str, str]] = []
    if append and out_path.exists():
        with out_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            existing_fields = list(reader.fieldnames or [])
            if existing_fields != columns:
                raise ValueError(
                    "--append : le schéma du fichier existant ne correspond pas aux colonnes "
                    f"attendues pour horizon={horizon} — fusion refusée pour éviter toute perte "
                    f"silencieuse.\nExistant : {existing_fields}\nAttendu  : {columns}"
                )
            existing_rows = [r for r in reader if r.get("chain_id") not in chains_written]

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in existing_rows:
            writer.writerow(r)
        for row in rows:
            writer.writerow(_row_to_csv_dict(row, columns))


def _summarize_dataset_csv(out_path: Path, horizon: int) -> None:
    """Relit le fichier ECRIT (reflete l'etat final, y compris apres --append) et resume en FR."""
    y1_col, yh_col = "y1", f"y{horizon}"
    chains: set[str] = set()
    n = 0
    y1_vals: list[int] = []
    yh_vals: list[int] = []
    with out_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            n += 1
            chains.add(r["chain_id"])
            if r[y1_col] != "":
                y1_vals.append(int(r[y1_col]))
            if r[yh_col] != "":
                yh_vals.append(int(r[yh_col]))

    def _report(label: str, vals: list[int]) -> None:
        n_obs = len(vals)
        n_censored = n - n_obs
        if n_obs:
            rate = sum(vals) / n_obs
            print(
                f"  Taux de base {label} : {rate:.1%} "
                f"(n={n_obs} non censuré, {n_censored} censuré/absent)."
            )
        else:
            print(f"  Taux de base {label} : indéfini (aucune ligne non censurée).")
        if n:
            print(f"  Taux de censure {label} : {n_censored / n:.1%}")

    print(f"Dataset écrit : {out_path} — {n} ligne(s), {len(chains)} chaîne(s).")
    _report(y1_col, y1_vals)
    _report(yh_col, yh_vals)


def validate_dataset_csv(out_path: Path, horizon: int) -> None:
    """Relit le fichier ecrit et verifie le schema (echoue fort en cas d'anomalie)."""
    columns = _dataset_columns(horizon)
    label_cols = ("y1", f"y{horizon}")
    int_cols = {"beta_n", "in_deg", "out_deg", "weeks_since_event", "event_recent", *label_cols}
    group_cols = ("chain_id", "node_id", "dgp_params_id")

    with out_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if fieldnames != columns:
            raise AssertionError(
                f"--validate : en-tête inattendu.\nAttendu : {columns}\nObtenu  : {fieldnames}"
            )
        n = 0
        for i, r in enumerate(reader, start=2):  # ligne 1 = en-tete
            n += 1
            for g in group_cols:
                if not r[g]:
                    raise AssertionError(f"--validate : ligne {i} — colonne groupe « {g} » vide.")
            for lbl in label_cols:
                if r[lbl] not in ("", "0", "1"):
                    raise AssertionError(
                        f"--validate : ligne {i} — label « {lbl} »={r[lbl]!r} hors domaine "
                        "{'', '0', '1'}."
                    )
            for col in columns:
                if col in group_cols:
                    continue
                v = r[col]
                if v == "":
                    continue
                try:
                    int(v) if col in int_cols else float(v)
                except ValueError as exc:
                    raise AssertionError(
                        f"--validate : ligne {i}, colonne « {col} »={v!r} — {exc}"
                    ) from exc

    print(f"Validation OK : {out_path} ({n} ligne(s), {len(columns)} colonnes, schéma conforme).")


# OUTPUT 2 : extraction du journal d'interventions


def _interventions_columns(ea_columns: list[str]) -> list[str]:
    cols = ["chain_id", "node_id", "tour", "action_id", "decidee", "executee", "date_effet"]
    cols += ["resultat_operationnel", "succes"]
    cols += [f"ea_{k}" for k in ea_columns]
    cols += list(VALIDATION_ONLY_INTERVENTION_COLUMNS)
    return cols


def extract_interventions(runs_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Agrege tous les ``interventions_truth.jsonl`` trouves sous ``runs_root``."""
    run_dirs = discover_runs(runs_root)
    raw_records: list[tuple[str, Json]] = []
    ea_keys: set[str] = set()

    for chain_id, run_dir in sorted(run_dirs.items()):
        jsonl_path = run_dir / "interventions_truth.jsonl"
        if not jsonl_path.exists():
            continue
        for entry in _read_jsonl(jsonl_path):
            etat_avant = entry.get("etat_avant") or {}
            ea_keys.update(etat_avant.keys())
            raw_records.append((chain_id, entry))

    ea_columns = sorted(ea_keys)
    records: list[dict[str, Any]] = []
    for chain_id, entry in raw_records:
        resultat = entry.get("resultat_operationnel")
        succes = RESULTAT_TO_SUCCES.get(resultat) if isinstance(resultat, str) else None
        etat_avant = entry.get("etat_avant") or {}
        record: dict[str, Any] = {
            "chain_id": chain_id,
            "node_id": entry.get("node"),
            "tour": entry.get("tour"),
            "action_id": entry.get("action_id"),
            "decidee": bool(entry.get("decidee")),
            "executee": bool(entry.get("executee")),
            "date_effet": entry.get("date_effet"),
            "resultat_operationnel": resultat,
            "succes": succes,
            "stress_latent": entry.get("stress_latent"),
            "delta_u_vrai": entry.get("delta_u_vrai"),
            "effet_vrai_param": entry.get("effet_vrai_param"),
        }
        for k in ea_columns:
            v = etat_avant.get(k)
            is_nested = isinstance(v, (dict, list))
            record[f"ea_{k}"] = json.dumps(v, ensure_ascii=False) if is_nested else v
        records.append(record)

    return records, ea_columns


def write_interventions_csv(
    records: list[dict[str, Any]], ea_columns: list[str], out_path: Path
) -> None:
    """Ecrit ``interventions.csv`` (ligne de commentaire VALIDATION_ONLY en tete)."""
    columns = _interventions_columns(ea_columns)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        f.write(
            "# VALIDATION_ONLY (vérité terrain de l'usine, jamais des features du modèle "
            "d'effet — utilisées uniquement pour le scorer) : "
            + ", ".join(VALIDATION_ONLY_INTERVENTION_COLUMNS)
            + "\r\n"  # coherent avec le \r\n par defaut de csv.writer (fichier ouvert newline="")
        )
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in records:
            writer.writerow(_row_to_csv_dict(r, columns))


def validate_interventions_csv(out_path: Path) -> None:
    """Relit le fichier ecrit et verifie le schema + le marquage VALIDATION_ONLY."""
    with out_path.open(encoding="utf-8", newline="") as f:
        first_line = f.readline()
        if not first_line.startswith("#") or "VALIDATION_ONLY" not in first_line:
            raise AssertionError(
                "--validate : interventions.csv doit commencer par une ligne de commentaire "
                "VALIDATION_ONLY."
            )
        for marker in VALIDATION_ONLY_INTERVENTION_COLUMNS:
            if marker not in first_line:
                raise AssertionError(
                    f"--validate : la ligne VALIDATION_ONLY ne mentionne pas « {marker} »."
                )

        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        required = (
            "chain_id",
            "node_id",
            "tour",
            "action_id",
            "decidee",
            "executee",
            "succes",
            *VALIDATION_ONLY_INTERVENTION_COLUMNS,
        )
        for col in required:
            if col not in fieldnames:
                raise AssertionError(
                    f"--validate : colonne manquante « {col} » dans interventions.csv."
                )

        n = 0
        for i, r in enumerate(reader, start=3):  # ligne 1 = commentaire, ligne 2 = en-tete
            n += 1
            for g in ("chain_id", "node_id", "action_id"):
                if not r[g]:
                    raise AssertionError(f"--validate : ligne {i} — colonne « {g} » vide.")
            for b in ("decidee", "executee"):
                if r[b] not in ("0", "1"):
                    raise AssertionError(
                        f"--validate : ligne {i} — « {b} »={r[b]!r} hors domaine {{'0','1'}}."
                    )
            if r["succes"] not in ("", "0", "1"):
                raise AssertionError(
                    f"--validate : ligne {i} — « succes »={r['succes']!r} hors domaine."
                )
            if r["tour"] != "":
                try:
                    int(r["tour"])
                except ValueError as exc:
                    raise AssertionError(
                        f"--validate : ligne {i} — « tour »={r['tour']!r} non entier."
                    ) from exc

    print(
        f"Validation OK : {out_path} ({n} ligne(s), schéma conforme, "
        "marquage VALIDATION_ONLY présent)."
    )


# feature_schema.json (v1)


def build_feature_schema(horizon: int = DEFAULT_HORIZON) -> Json:
    """Construit le schema de features versionne (dataset + interventions)."""
    if horizon < 2:
        raise ValueError(
            "horizon doit être >= 2 (y1 est toujours l'horizon à 1 tour, distinct de "
            "y{horizon} — horizon=1 collisionnerait les deux colonnes de label)."
        )
    y1_col, yh_col = "y1", f"y{horizon}"
    columns: list[Json] = []

    def col(name: str, dtype: str, nullable: bool, role: str, semantics: str) -> None:
        columns.append(
            {
                "name": name,
                "dtype": dtype,
                "nullable": nullable,
                "role": role,
                "semantics": semantics,
            }
        )

    col(
        "chain_id",
        "string",
        False,
        "group",
        "Identifiant de la chaîne/run (nom du dossier) — jamais une feature.",
    )
    col("node_id", "string", False, "group", "Identifiant du nœud — jamais une feature.")
    col(
        "dgp_params_id",
        "string",
        False,
        "group",
        f"Identifiant des paramètres du DGP (« {HELIOS_DGP_PARAMS_ID} » si le run ne fournit "
        "pas de dgp_manifest.json) — jamais une feature.",
    )
    col(
        y1_col,
        "int",
        True,
        "label",
        "1 si un événement vérité (gravité critique|defaut) touche le nœud exactement à t+1, "
        "sinon 0 ; vide si t+1 dépasse le dernier tour observé de la chaîne (censure "
        "explicite, jamais 0 silencieux).",
    )
    col(
        yh_col,
        "int",
        True,
        "label",
        f"1 si un événement vérité touche le nœud dans (t, t+{horizon}], 0 si la fenêtre est "
        "entièrement observée sans événement, vide (censuré) si la fenêtre dépasse le dernier "
        "tour observé sans qu'aucun événement n'y ait été trouvé — jamais mis à 0 silencieusement.",
    )

    local_semantics = {
        "ud": "Urgence déclarée globale du nœud (Ud, propagée).",
        "ur": "Urgence réelle globale du nœud (Ur, propagée).",
        "ud_local": "Composante locale d'Ud (hors propagation amont/aval).",
        "ur_local": "Composante locale d'Ur (hors propagation amont/aval).",
        "hidden_risk": "Risque caché : Ur excède Ud (besoin sous-déclaré).",
        "false_urgency": "Fausse urgence : Ud excède Ur (besoin sur-déclaré).",
        "adequation": "Score d'adéquation Ud/Ur du nœud (0-100).",
    }
    for name, semantics in local_semantics.items():
        col(name, "float", True, "feature", semantics)
    for name in U_BLOC_KEYS:
        col(
            name,
            "float",
            True,
            "feature",
            f"Bloc KPI « {name[2:]} » de la décomposition log-survie de ur_local "
            "(explain_ur_local) ; vide si bloc inactif ou décomposition indisponible pour ce tour.",
        )

    for k in range(1, horizon + 1):
        col(
            f"d{k}_ur_local",
            "float",
            True,
            "feature",
            f"Différence arrière à {k} tour(s) de ur_local : ur_local(t) − ur_local(t−{k}) ; "
            "vide si l'historique est insuffisant.",
        )
    for k in range(1, horizon + 1):
        col(
            f"d{k}_{HIDDEN_RISK_ALIAS}",
            "float",
            True,
            "feature",
            f"Différence arrière à {k} tour(s) de hidden_risk (« H ») ; vide si l'historique "
            "est insuffisant.",
        )
    col(
        "ema_ur_local",
        "float",
        False,
        "feature",
        f"Moyenne mobile exponentielle de ur_local (rho={EMA_RHO}), lissée sur les tours "
        "réellement observés pour ce nœud (les tours manquants ne comptent pas comme des zéros).",
    )
    col(
        "event_recent",
        "int",
        False,
        "feature",
        "1 si un événement vérité (gravité critique|defaut) a touché ce nœud dans [t−2, t], "
        "sinon 0.",
    )
    col(
        "weeks_since_event",
        "int",
        True,
        "feature",
        "Nombre de tours depuis le dernier événement vérité sur ce nœud, jusqu'à t inclus ; "
        "vide si aucun événement observé.",
    )
    col(
        "beta_mean",
        "float",
        False,
        "feature",
        "Moyenne du postérieur Beta-Bernoulli du taux d'événement hebdomadaire du nœud "
        f"(prior partagé sur tout le dossier --runs, force N0={N0_BETA:g}).",
    )
    col("beta_var", "float", False, "feature", "Variance du postérieur Beta-Bernoulli.")
    col(
        "beta_n",
        "int",
        False,
        "feature",
        "Nombre de tours réellement observés pour ce nœud jusqu'à t inclus (hors "
        "pseudo-observations du prior).",
    )
    col(
        "p_retard_jalon",
        "float",
        True,
        "feature",
        "Réservée (aucune unité ne la produit encore) — toujours vide dans ce schéma v1.",
    )
    col(
        "p_impact_final",
        "float",
        True,
        "feature",
        "P(impact final) de la criticité probabiliste ; vide si non calculée pour ce tour.",
    )
    col(
        "delta_ell_final",
        "float",
        True,
        "feature",
        "Δℓ final (log-survie) de la criticité probabiliste ; vide si non calculé.",
    )
    col(
        "delta_ell_max",
        "float",
        True,
        "feature",
        "Δℓ maximal observé de la criticité probabiliste ; vide si non calculé.",
    )
    col(
        "p_rollout",
        "float",
        True,
        "feature",
        f"p_issue du rollout Monte Carlo à l'horizon {horizon} "
        f"(forecast['{horizon}']['p_issue']) ; vide si absent.",
    )
    col(
        "spread",
        "float",
        True,
        "feature",
        f"Étalement (spread) du rollout Monte Carlo à l'horizon {horizon} ; vide si absent.",
    )
    col(
        "depth_frac",
        "float",
        False,
        "feature",
        "rank / max(rank) parmi les nœuds du même tour ; 0.0 si tous les rangs sont à 0.",
    )
    col(
        "in_deg",
        "int",
        True,
        "feature",
        "Degré entrant (nombre de prédécesseurs), déduit d'une liste d'arcs optionnelle du "
        "manifeste ; vide si les arcs sont inconnus.",
    )
    col("out_deg", "int", True, "feature", "Degré sortant ; vide si les arcs sont inconnus.")
    col(
        "log_n_nodes",
        "float",
        False,
        "feature",
        "Logarithme népérien du nombre de nœuds présents dans le tour.",
    )
    col(
        "impact_frac",
        "float",
        True,
        "feature",
        "nb_impactes / n_nodes (criticité) ; vide si la criticité n'a pas pu être calculée "
        "pour ce tour.",
    )
    col(
        "mean_ur_pred",
        "float",
        True,
        "feature",
        "Moyenne de 'ur' des prédécesseurs directs (arcs connus) au même tour ; vide si arcs "
        "inconnus ou aucun prédécesseur.",
    )
    col(
        "max_ur_pred",
        "float",
        True,
        "feature",
        "Maximum de 'ur' des prédécesseurs directs ; vide si arcs inconnus ou aucun prédécesseur.",
    )
    col(
        "frac_pred_satures",
        "float",
        True,
        "feature",
        "Fraction des prédécesseurs directs saturés (ur >= 0.999) ; vide si arcs inconnus ou "
        "aucun prédécesseur.",
    )
    col(
        "mean_beta_in",
        "float",
        True,
        "feature",
        "Moyenne de beta_mean des prédécesseurs directs (même tour) ; vide si arcs inconnus ou "
        "aucun prédécesseur.",
    )

    dataset_schema = {
        "group_columns": ["chain_id", "node_id", "dgp_params_id"],
        "label_columns": [y1_col, yh_col],
        "horizon": horizon,
        "columns": columns,
        "excluded": {
            "stress_latent": (
                "Confondeur latent de l'usine synthétique (U6), définition gelée D32 : jamais "
                "une feature. Absent par construction de ce schéma (n'apparaît que dans "
                "interventions.csv, marqué VALIDATION_ONLY)."
            )
        },
    }

    intervention_columns = [
        {
            "name": "chain_id",
            "dtype": "string",
            "nullable": False,
            "semantics": "Identifiant de la chaîne/run.",
        },
        {
            "name": "node_id",
            "dtype": "string",
            "nullable": False,
            "semantics": "Nœud ciblé par l'intervention.",
        },
        {
            "name": "tour",
            "dtype": "int",
            "nullable": True,
            "semantics": "Tour d'ouverture de l'intervention.",
        },
        {
            "name": "action_id",
            "dtype": "string",
            "nullable": False,
            "semantics": "Identifiant de l'action du catalogue (U15).",
        },
        {
            "name": "decidee",
            "dtype": "int",
            "nullable": False,
            "semantics": "1 si l'action a été décidée, 0 sinon.",
        },
        {
            "name": "executee",
            "dtype": "int",
            "nullable": False,
            "semantics": "1 si l'action décidée a effectivement été exécutée, 0 sinon.",
        },
        {
            "name": "date_effet",
            "dtype": "int",
            "nullable": True,
            "semantics": "Tour d'effet, vide si non défini.",
        },
        {
            "name": "resultat_operationnel",
            "dtype": "string",
            "nullable": True,
            "semantics": (
                "resolu|partiel|echec|en_cours (label causal opérationnel, définition gelée) "
                "— vide si non renseigné."
            ),
        },
        {
            "name": "succes",
            "dtype": "int",
            "nullable": True,
            "semantics": (
                "1 si resultat_operationnel=resolu, 0 si echec, vide sinon "
                "(partiel/en_cours/absent)."
            ),
        },
        {
            "name": "ea_*",
            "dtype": "mixed",
            "nullable": True,
            "semantics": (
                "Features observables de etat_avant, aplaties avec le préfixe 'ea_' — union "
                "triée des clés vues sur l'ensemble des runs ingérés ; vide quand une "
                "intervention ne renseigne pas la clé."
            ),
        },
        {
            "name": "effet_vrai_param",
            "dtype": "float",
            "nullable": True,
            "semantics": (
                "VALIDATION_ONLY — effet vrai paramétrique de l'usine, jamais une feature du "
                "modèle d'effet."
            ),
        },
        {
            "name": "delta_u_vrai",
            "dtype": "float",
            "nullable": True,
            "semantics": (
                "VALIDATION_ONLY — delta_u vrai (paire CRN de l'usine), jamais une feature du "
                "modèle d'effet."
            ),
        },
        {
            "name": "stress_latent",
            "dtype": "float",
            "nullable": True,
            "semantics": (
                "VALIDATION_ONLY — confondeur latent (définition gelée D32), jamais une "
                "feature du modèle d'effet ; sert uniquement à scorer/valider ce modèle."
            ),
        },
    ]

    interventions_schema = {
        "columns": intervention_columns,
        "ea_prefix": "ea_",
        "validation_only": list(VALIDATION_ONLY_INTERVENTION_COLUMNS),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "projects/factory/build_dataset.py:build_feature_schema",
        "dataset": dataset_schema,
        "interventions": interventions_schema,
        "notes": {
            "csv_empty": (
                "Toute cellule CSV vide signifie 'nullable=true' et non calculable — jamais "
                "imputée à 0."
            ),
            "event_definition": (
                "« événement » = entrée events_truth de gravité dans {critique, defaut} ; "
                "définition unique réutilisée pour les labels, la dynamique et le postérieur "
                "bayésien."
            ),
            "last_tour": (
                "La censure des labels utilise le dernier tour_NN.json RÉELLEMENT présent "
                "pour la chaîne, jamais l'étendue déclarée d'events_truth."
            ),
        },
    }


# CLI


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI : construction du dataset ou extraction des interventions."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows cp1252

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--runs", required=True, help="Dossier racine des runs (parcouru récursivement)"
    )
    parser.add_argument("--out", help="Fichier CSV de sortie")
    parser.add_argument(
        "--horizon",
        type=int,
        default=DEFAULT_HORIZON,
        help=f"Horizon censuré y{{H}} / dynamiques d{{1..H}} (défaut {DEFAULT_HORIZON})",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Fusionne avec un dataset existant (remplace par chain_id)",
    )
    parser.add_argument(
        "--interventions", action="store_true", help="Mode extraction du journal d'interventions"
    )
    parser.add_argument(
        "--validate", action="store_true", help="Relit le fichier écrit et vérifie le schéma"
    )
    parser.add_argument(
        "--emit-schema",
        metavar="PATH",
        help="Écrit feature_schema.json (horizon courant) au chemin donné et quitte",
    )
    args = parser.parse_args(argv)

    # Valide AVANT --emit-schema : horizon=1 collisionnerait avec la colonne fixe y1 (y{horizon} redeviendrait "y1"), y compris en mode --emit-schema seul.
    if args.horizon < 2:
        parser.error(
            "--horizon doit être >= 2 (y1 est toujours l'horizon à 1 tour, distinct de y{horizon})."
        )

    if args.emit_schema:
        Path(args.emit_schema).write_text(
            json.dumps(build_feature_schema(args.horizon), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Schéma écrit : {args.emit_schema}")
        return 0

    if not args.out:
        parser.error("--out est requis (sauf avec --emit-schema).")

    runs_root = Path(args.runs)
    out_path = Path(args.out)

    if args.interventions:
        if args.append:
            print(
                "Avertissement : --append est ignoré en mode --interventions "
                "(réécriture complète, déjà idempotente)."
            )
        records, ea_columns = extract_interventions(runs_root)
        write_interventions_csv(records, ea_columns, out_path)
        print(f"interventions.csv écrit : {out_path} ({len(records)} intervention(s)).")
        if args.validate:
            validate_interventions_csv(out_path)
        return 0

    rows = build_dataset(runs_root, args.horizon)
    write_dataset_csv(rows, out_path, args.horizon, args.append)
    _summarize_dataset_csv(out_path, args.horizon)
    if args.validate:
        validate_dataset_csv(out_path, args.horizon)
    return 0


if __name__ == "__main__":
    sys.exit(main())
