"""Re-derive every HELIOS number quoted in the thesis, from raw artifacts only.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe derive.py

Writes ``derived.json`` next to this file. Both the figure scripts and the LaTeX
text read that file, so no number is ever typed twice.

Why this script exists
----------------------
``projects/simu_semiconducteurs/analysis/rapport_experience.md`` and
``resultats_experience.json`` hold a stale run and are NOT used: they report an
identical AUC for arms A and B (impossible, the arms carry different
declarations), influence counts of 126/25/0/1 where the raw ``results_*.jsonl``
give 39/27/15/16, and they score against the wrong outcome definition.

Everything below comes from:
  experiment/db_arm_a, db_arm_b          the campaign databases (ground truth)
  .../mesures_avant_reparation/bras_a_rejeu/predictions_log.jsonl   120 forecasts
  .../mesures_avant_reparation/bras_b/predictions_log.jsonl          72 forecasts
  .../mesures_avant_reparation/bras_b/results_<node>.jsonl           declarations

The outcome labels are produced by the PRODUCTION ``CalibrationService``, so the
thesis scores the model against the same target definition the system itself
uses: a milestone missed, a node abandoned, or an event of gravity "critique" or
"defaut", observed in the window [S+1, S+horizon].
"""

from __future__ import annotations

import collections
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]  # C:\PRIVEE\AZURE
CAMPAIGN = REPO / "projects" / "simu_semiconducteurs"
EXPERIMENT = CAMPAIGN / "experiment"
RAW = EXPERIMENT / "mesures_avant_reparation"

for p in (str(REPO), str(CAMPAIGN / "scenario"), str(CAMPAIGN / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

PROJECT_ID = "helios"
HORIZONS = (1, 2, 3, 4)

#: Event gravities that the production CalibrationService counts as an adverse
#: outcome. Reproduced here only to build the deliberately WRONG target for the
#: contrast of Section "the target-definition trap".
GRAVITES_DEFAVORABLES = frozenset({"critique", "defaut"})


# ─────────────────────────────────────────────────────────────────────────────
#  Metrics. scikit-learn is not installed in this environment, and these are
#  short enough that a dependency would not be justified.
# ─────────────────────────────────────────────────────────────────────────────

def auc(p: np.ndarray, y: np.ndarray) -> float | None:
    """Area under the ROC curve, by mean ranks so that ties are handled."""
    pos, neg = int(y.sum()), int((1 - y).sum())
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    sorted_p = p[order]
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def auc_ci(p: np.ndarray, y: np.ndarray, n_boot: int = 2000, seed: int = 0):
    """Percentile bootstrap 95% interval on the AUC. None if a class is absent."""
    if auc(p, y) is None:
        return None
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(p), len(p))
        a = auc(p[idx], y[idx])
        if a is not None:
            vals.append(a)
    if len(vals) < n_boot // 10:
        return None
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def pr_auc(p: np.ndarray, y: np.ndarray) -> float | None:
    """Average precision, the step-wise area under the precision-recall curve."""
    if y.sum() == 0:
        return None
    order = np.argsort(-p, kind="mergesort")
    ys = y[order]
    tp = np.cumsum(ys)
    precision = tp / np.arange(1, len(ys) + 1)
    return float((precision * ys).sum() / ys.sum())


def brier(p: np.ndarray, y: np.ndarray) -> dict:
    """Brier score and its skill against the climatological forecast.

    Climatology predicts the base rate for every point, so a negative skill
    means the model is worse calibrated than always announcing the base rate.
    """
    bs = float(np.mean((p - y) ** 2))
    base = float(y.mean())
    bs_ref = float(np.mean((base - y) ** 2))
    skill = None if bs_ref == 0 else float(1.0 - bs / bs_ref)
    return {"brier": bs, "brier_climatology": bs_ref, "brier_skill": skill,
            "base_rate": base}


def reliability(p: np.ndarray, y: np.ndarray, edges=(0.0, 0.1, 0.2, 0.5, 0.9, 1.01)):
    """Reliability table: announced mean vs observed frequency, per band.

    The bands are deliberately uneven. A uniform 10-bin split hides the two
    failures that matter here, because almost every forecast falls either very
    low or saturated at one.
    """
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        n = int(m.sum())
        if n == 0:
            continue
        announced, observed = float(p[m].mean()), float(y[m].mean())
        ratio = None
        if announced > 0 and observed > 0:
            ratio = float(observed / announced)
        out.append({"lo": lo, "hi": min(hi, 1.0), "n": n,
                    "announced": announced, "observed": observed,
                    "ratio_observed_over_announced": ratio})
    return out


def confusion(p: np.ndarray, y: np.ndarray, seuil: float = 0.5) -> dict:
    pred = p >= seuil
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    return {"seuil": seuil, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": (tp / (tp + fp)) if tp + fp else 0.0,
            "recall": (tp / (tp + fn)) if tp + fn else 0.0}


# ─────────────────────────────────────────────────────────────────────────────
#  Ground truth
# ─────────────────────────────────────────────────────────────────────────────

def labels_correct_target(db_dir: Path) -> tuple[dict, list[str]]:
    """Adverse-outcome labels from the production CalibrationService.

    Returns ``{horizon: {(node_id, iso_week): bool}}`` and the ordered list of
    campaign weeks, whose index is the turn number.
    """
    from _common import open_service  # noqa: PLC0415 - path set above
    from supplyscore.services.calibration import CalibrationService

    service = open_service(str(db_dir))
    cal = CalibrationService(service)
    per_h, weeks = {}, None
    for h in HORIZONS:
        pts = cal.outcomes(PROJECT_ID, horizon_weeks=h)
        per_h[h] = {(pt.node_id, pt.iso_week): pt.issue_defavorable for pt in pts}
        if weeks is None:
            weeks = sorted({pt.iso_week for pt in pts})
    return per_h, weeks


def _decale(week: str, n: int) -> str:
    from supplyscore.services.weekly import _lundi  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415
    iso = (_lundi(week) + timedelta(weeks=n)).isocalendar()
    return f"{iso.year:04d}-S{iso.week:02d}"


def labels_wrong_target(db_dir: Path, weeks: list[str]) -> dict:
    """Deliberately WRONG labels: any non-reverted event on the node.

    This is the plausible-looking mistake the thesis contrasts against: it drops
    the gravity filter and the milestone criterion, and counts any logged event.
    Same model, same forecasts, only the definition of truth changes.
    """
    ev = collections.defaultdict(set)
    for db in sorted(glob.glob(str(db_dir / "*.sqlite"))):
        if os.path.basename(db) == "registry.sqlite":
            continue
        con = sqlite3.connect(db)
        for node_id, wk in con.execute(
            "SELECT node_id, iso_week FROM events WHERE reverted_at IS NULL"
        ):
            ev[node_id].add(wk)
        con.close()
    per_h = {}
    for h in HORIZONS:
        lab = {}
        for node_id, wks in ev.items():
            pass
        nodes = sorted(ev) or []
        for w in weeks:
            window = {_decale(w, k) for k in range(1, h + 1)}
            for node_id in nodes:
                lab[(node_id, w)] = bool(ev[node_id] & window)
        per_h[h] = lab
    return per_h


def read_predictions(path: Path, weeks: list[str]) -> list[dict]:
    """Forecast log, with the campaign turn resolved to its ISO week."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        t = int(r["tour"])
        if t >= len(weeks):
            continue
        r["iso_week"] = weeks[t]
        rows.append(r)
    return rows


def score(rows: list[dict], labels: dict, h: int, max_turn: int | None = None) -> dict | None:
    """Score the horizon-h forecasts of ``rows`` against ``labels``.

    ``max_turn`` drops forecasts whose observation window would run past the end
    of the campaign, which is the right-censoring sensitivity check.
    """
    p, y = [], []
    for r in rows:
        if max_turn is not None and r["tour"] > max_turn:
            continue
        key = (r["node_id"], r["iso_week"])
        if key not in labels:
            continue
        p.append(float(r[f"p_issue_h{h}"]))
        y.append(1.0 if labels[key] else 0.0)
    if not p:
        return None
    p, y = np.asarray(p), np.asarray(y)
    out = {"n": int(len(p)), "n_positive": int(y.sum()),
           "auc": auc(p, y), "auc_ci95": auc_ci(p, y), "pr_auc": pr_auc(p, y),
           "confusion_at_0.5": confusion(p, y, 0.5),
           "reliability": reliability(p, y),
           # the scored pairs themselves, so a figure cannot disagree with a table
           "points": {"p": [float(v) for v in p], "y": [int(v) for v in y]}}
    out.update(brier(p, y))
    return out


def confident_forecasts(rows: list[dict], labels: dict, h: int = 4,
                        seuil: float = 0.5) -> dict:
    """Anatomy of the confident tail: where it comes from and what became of it.

    Every forecast at or above ``seuil`` is listed with the milestone-miss
    probability that drives it, so the text can show that the confident tail is
    the milestone channel and nothing else.
    """
    items = []
    for r in rows:
        p = float(r[f"p_issue_h{h}"])
        if p < seuil:
            continue
        key = (r["node_id"], r["iso_week"])
        items.append({
            "tour": r["tour"], "node_id": r["node_id"], "iso_week": r["iso_week"],
            "p_issue": p, "p_jalon_rate": float(r["p_jalon_rate"]),
            "issue_observed": bool(labels.get(key, False)),
        })
    items.sort(key=lambda it: (it["tour"], it["node_id"]))
    if items:
        gap = max(abs(it["p_issue"] - it["p_jalon_rate"]) for it in items)
        by_node = collections.Counter(it["node_id"] for it in items)
    else:
        gap, by_node = None, collections.Counter()
    return {
        "seuil": seuil, "horizon": h, "n": len(items),
        "n_materialised": sum(it["issue_observed"] for it in items),
        "mean_announced": float(np.mean([it["p_issue"] for it in items])) if items else None,
        "turn_range": [items[0]["tour"], items[-1]["tour"]] if items else None,
        "nodes": dict(by_node),
        "max_gap_to_p_jalon_rate": gap,
        "items": items,
    }


def milestone_outcomes(db_dir: Path) -> dict:
    """Final status of every milestone in the registry.

    The counterpart of the confident tail: the forecast layer announced near
    certain misses, and this is what actually happened to those milestones.
    """
    con = sqlite3.connect(str(db_dir / "registry.sqlite"))
    rows = list(con.execute("SELECT node_id, name, status FROM milestones"))
    con.close()
    counts = collections.Counter(s for _, _, s in rows)
    return {"n": len(rows), "by_status": dict(counts),
            "not_done": [{"node_id": n, "name": m, "status": s}
                         for n, m, s in rows if s != "done"]}


# ─────────────────────────────────────────────────────────────────────────────
#  Arm B: what the personas did when the forecast was shown
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIES = ("aucune", "confirme", "revise_a_la_hausse", "revise_a_la_baisse")


def arm_b_declarations() -> dict:
    per_turn = collections.defaultdict(collections.Counter)
    per_node_turn, totals = {}, collections.Counter()
    ud_by_turn = collections.defaultdict(list)
    n_records = 0
    for path in sorted(RAW.glob("bras_b/results_*.jsonl")):
        node = path.stem.replace("results_", "")
        seen = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            t = int(r["tour"])
            if t in seen:  # one node re-submitted a turn; keep the first answer
                continue
            seen.add(t)
            n_records += 1
            inf = r.get("influence_prediction")
            if inf:
                per_turn[t][inf] += 1
                totals[inf] += 1
                per_node_turn[f"{node}|{t}"] = inf
            if r.get("ud_smoothed") is not None:
                ud_by_turn[t].append(float(r["ud_smoothed"]))
    turns = sorted(per_turn)
    return {
        "n_records": n_records,
        "n_with_influence": int(sum(totals.values())),
        "totals": {c: int(totals[c]) for c in CATEGORIES},
        "per_turn": {str(t): {c: int(per_turn[t][c]) for c in CATEGORIES}
                     for t in turns},
        "per_node_turn": per_node_turn,
        "mean_ud_by_turn": {str(t): float(np.mean(v))
                            for t, v in sorted(ud_by_turn.items()) if v},
        "first_exposure_turn": next(
            (t for t in turns if any(per_turn[t][c] for c in CATEGORIES[1:])), None),
    }


def scenario_events(db_dir: Path, weeks: list[str]) -> list[dict]:
    """Every logged event, with its turn, so the text can name the shock turns."""
    idx = {w: i for i, w in enumerate(weeks)}
    out = []
    for db in sorted(glob.glob(str(db_dir / "*.sqlite"))):
        if os.path.basename(db) == "registry.sqlite":
            continue
        con = sqlite3.connect(db)
        for node_id, wk, typ in con.execute(
            "SELECT node_id, iso_week, event_type FROM events WHERE reverted_at IS NULL"
        ):
            out.append({"node_id": node_id, "iso_week": wk,
                        "tour": idx.get(wk), "event_type": typ})
        con.close()
    return sorted(out, key=lambda e: (e["tour"] if e["tour"] is not None else 99,
                                      e["node_id"]))


def u_time_blindness() -> dict:
    """The u_time block read straight out of the mid-crisis turn snapshot."""
    out = {}
    for arm, folder in (("A", "bras_a_rejeu"), ("B", "bras_b")):
        path = RAW / folder / "tour_06.json"
        if not path.exists():
            continue
        snap = json.loads(path.read_text(encoding="utf-8"))
        out[arm] = {nid: n["blocs"].get("u_time")
                    for nid, n in snap["nodes"].items()
                    if n.get("blocs") is not None}
    return out


def _same_forecasts(rows_a: list[dict], rows_b: list[dict]) -> dict:
    """Do the two arms carry the same prediction-layer output?

    They should: the replay is deterministic, so only the personas' declarations
    differ between arms. Confirming it matters, because it means any difference
    in behaviour between the arms cannot come from a different forecast.
    """
    key = lambda r: (r["tour"], r["node_id"])  # noqa: E731
    vec = lambda r: tuple(round(float(r[f"p_issue_h{h}"]), 9) for h in HORIZONS)  # noqa: E731
    a = {key(r): vec(r) for r in rows_a}
    b = {key(r): vec(r) for r in rows_b}
    shared = set(a) & set(b)
    identical = sum(1 for k in shared if a[k] == b[k])
    return {"n_shared": len(shared), "n_identical": identical,
            "all_identical": identical == len(shared) and bool(shared)}


def main() -> int:
    db_a, db_b = EXPERIMENT / "db_arm_a", EXPERIMENT / "db_arm_b"
    correct, weeks = labels_correct_target(db_a)
    wrong = labels_wrong_target(db_a, weeks)

    rows_a = read_predictions(RAW / "bras_a_rejeu" / "predictions_log.jsonl", weeks)
    rows_b = read_predictions(RAW / "bras_b" / "predictions_log.jsonl", weeks)

    result = {
        "provenance": {
            "labels": "supplyscore.services.calibration.CalibrationService.outcomes",
            "db_arm_a": str(db_a), "db_arm_b": str(db_b),
            "forecasts_arm_a": str(RAW / "bras_a_rejeu" / "predictions_log.jsonl"),
            "forecasts_arm_b": str(RAW / "bras_b" / "predictions_log.jsonl"),
            "excluded": ["analysis/rapport_experience.md",
                         "analysis/resultats_experience.json"],
        },
        "campaign": {
            "weeks": weeks, "n_turns": len(weeks),
            "turn_of_week": {w: i for i, w in enumerate(weeks)},
            "events": scenario_events(db_a, weeks),
        },
        "arm_a": {
            "n_forecasts": len(rows_a),
            "turns": sorted({r["tour"] for r in rows_a}),
            "correct_target": {str(h): score(rows_a, correct[h], h) for h in HORIZONS},
            "wrong_target": {str(h): score(rows_a, wrong[h], h) for h in HORIZONS},
            # right-censoring check: forecasts whose window would run past the
            # last campaign turn are dropped and the scoring is repeated.
            "correct_target_uncensored": {
                str(h): score(rows_a, correct[h], h, max_turn=len(weeks) - 1 - h)
                for h in HORIZONS},
            "confident_tail": confident_forecasts(rows_a, correct[4], h=4),
        },
        "arm_b": {
            "n_forecasts": len(rows_b),
            "turns": sorted({r["tour"] for r in rows_b}),
            "shares_forecasts_with_arm_a": _same_forecasts(rows_a, rows_b),
            "declarations": arm_b_declarations(),
        },
        "milestones": milestone_outcomes(db_a),
        "u_time_at_turn_6": u_time_blindness(),
    }

    (HERE / "derived.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    # console summary, so a run is self-checking
    print(f"campaign: {len(weeks)} turns, {weeks[0]} to {weeks[-1]}")
    print(f"arm A: {len(rows_a)} forecasts | arm B: {len(rows_b)} forecasts\n")
    print(f"{'h':>2} {'n':>5} {'pos':>4} {'base':>7} {'AUC':>7} {'Brier':>7} {'skill':>8}")
    for tag in ("correct_target", "wrong_target"):
        print(f"  -- {tag} --")
        for h in HORIZONS:
            s = result["arm_a"][tag][str(h)]
            if s is None:
                continue
            a = "  n/a  " if s["auc"] is None else f"{s['auc']:7.3f}"
            k = "   n/a  " if s["brier_skill"] is None else f"{s['brier_skill']:8.3f}"
            print(f"{h:>2} {s['n']:>5} {s['n_positive']:>4} {s['base_rate']:7.3f}"
                  f" {a} {s['brier']:7.3f} {k}")
    ct = result["arm_a"]["confident_tail"]
    ms = result["milestones"]
    print(f"\nconfident tail (p_h4 >= {ct['seuil']}): {ct['n']} forecasts, "
          f"mean announced {ct['mean_announced']:.3f}, turns {ct['turn_range']}, "
          f"{ct['n_materialised']} materialised")
    print(f"  max gap to p_jalon_rate: {ct['max_gap_to_p_jalon_rate']:.3f} "
          f"(the tail is the milestone channel)")
    print(f"  milestones: {ms['n']} total, by status {ms['by_status']}")

    d = result["arm_b"]["declarations"]
    print(f"\narm B: forecasts shared with arm A: "
          f"{result['arm_b']['shares_forecasts_with_arm_a']}")
    print(f"  {d['n_with_influence']} declarations with an influence field")
    print("  totals:", d["totals"])
    print(f"  first exposure at turn {d['first_exposure_turn']}:",
          d["per_turn"][str(d["first_exposure_turn"])])
    print(f"\n-> {HERE / 'derived.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
