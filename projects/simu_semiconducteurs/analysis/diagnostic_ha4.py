"""Diagnostic HA4 (U2) — balayage de seuil, existe-t-il un signal prédictif ?

EXPLORATOIRE — hors registre pré-enregistré (voir PROTOCOLE.md §5). Le test
HA4 gelé (H = max(Ur−Ud, 0) >= 0.5, horizon 4 tours) a échoué avec TP≈0 sur
les snapshots dry run — mais l'inspection des séries montre que H est
structurellement compressé en fin de campagne (nœuds saturés : Ur = 1.0 avec
Ud ≈ 0.98 → H ≈ 0.02). Le seuil pré-enregistré n'a peut-être jamais eu de
chance d'être franchi, indépendamment de l'existence d'un signal sous-jacent.

Ce script NE MODIFIE PAS et NE REJOUE PAS le verdict gelé de
``analyse_campagne.ha4()`` : il répond à une question différente — en
balayant TOUS les seuils possibles, existe-t-il un pouvoir discriminant DU
TOUT dans Ur/Ud/H ? Si oui, c'est le seuil pré-enregistré qui était mal
calibré ; si non, la métrique elle-même est vide de contenu prédictif à cet
horizon.

Consomme les DEUX jeux de snapshots (même logique de chargement que
``analyse_campagne.load()``) :
    - ``analysis/snapshots/``                  (dry run v6)
    - ``analysis/llm_pilot_run/snapshots/``    (pilote LLM)
Le second jeu peut être absent au moment de l'exécution (dépendance d'une
autre unité du plan HÉLIOS v7, en cours de fusion en parallèle) : le script
le signale explicitement et poursuit sur les données disponibles.

Produit :
    - ``analysis/diagnostic_ha4.md``                     : tables + verdict.
    - ``analysis/figures_diagnostic_ha4/*.png``          : ROC, AUC vs lag
      (best-effort si matplotlib est disponible).

Script AUTONOME (hors couverture, cf. pyproject.toml ``[tool.coverage.run]``
``source = ["supplyscore"]``) : toutes les statistiques sont recalculées à la
main (rangs avec correction d'ex-aequo, bootstrap, percentiles), sans
dépendre de ``supplyscore`` ni de ``CalibrationService``, à l'image du
``spearman`` hand-rolled de ``analyse_campagne.py``.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scenario"))
import scenario  # noqa: E402

SNAPSHOT_SETS: list[tuple[str, Path]] = [
    ("dry run v6", _HERE / "snapshots"),
    ("pilote LLM", _HERE / "llm_pilot_run" / "snapshots"),
]
FIGURES = _HERE / "figures_diagnostic_ha4"
OUT_MD = _HERE / "diagnostic_ha4.md"

NODE_IDS = [n["id"] for n in scenario.NODES]

HORIZON = 4
SEED = 42
N_BOOT = 1000
LAGS = (1, 2, 3, 4)

#: 5 signaux candidats évalués point par point (nœud, tour).
SIGNALS = ["hidden_risk", "H_local", "ur", "ur_local", "gap"]

Point = tuple[str, int, float]  # (node, tour, score)
Scored = tuple[float, bool]  # (score, label)


def load(snapshots_dir: Path) -> dict[int, dict]:
    """Charge les snapshots ``tour_NN.json`` d'un répertoire.

    Même logique que ``analyse_campagne.load()``, mais en tolérant un
    répertoire absent ou vide — au contraire de ``analyse_campagne.load()``,
    cette fonction ne lève pas d'exception : un jeu de snapshots manquant
    est une situation normale ici (dépendance d'une autre unité, pas encore
    fusionnée).
    """
    data: dict[int, dict] = {}
    if not snapshots_dir.exists():
        return data
    for path in sorted(snapshots_dir.glob("tour_*.json")):
        snap = json.loads(path.read_text(encoding="utf-8"))
        if snap.get("tour") is not None:
            data[snap["tour"]] = snap
    return data


def event_tours_by_node() -> dict[str, set[int]]:
    """{node_id: {tours où un événement scénario touche ce nœud}}."""
    out: dict[str, set[int]] = {}
    for t, evs in scenario.EVENTS.items():
        for ev in evs:
            out.setdefault(ev["node"], set()).add(t)
    return out


def signal_value(node: dict, signal: str) -> float:
    """Valeur d'un signal candidat pour un nœud à un tour donné."""
    if signal == "hidden_risk":
        return float(node["hidden_risk"])
    if signal == "H_local":
        return max(float(node["ur_local"]) - float(node["ud_local"]), 0.0)
    if signal == "ur":
        return float(node["ur"])
    if signal == "ur_local":
        return float(node["ur_local"])
    if signal == "gap":
        return float(node["ur"]) - float(node["ud"])
    raise ValueError(f"signal inconnu : {signal}")


def scored_points(data: dict[int, dict], signal: str) -> list[Point]:
    """(node, tour, score) pour tous les (nœud, tour) valides.

    Même règle d'exclusion que ``analyse_campagne.ha4`` : on saute le
    dernier tour (``t + 1 > max(data)``) — sans lui, la fenêtre de vérité
    ``(t, t+horizon]`` n'a plus aucun sens de « futur ».
    """
    if not data:
        return []
    max_t = max(data)
    pts: list[Point] = []
    for node in NODE_IDS:
        for t in sorted(data):
            if t + 1 > max_t:
                continue
            n = data[t]["nodes"].get(node)
            if n is None:
                continue
            pts.append((node, t, signal_value(n, signal)))
    return pts


def label_horizon(ev_by_node: dict[str, set[int]], node: str, t: int, horizon: int) -> bool:
    """Vérité terrain HA4 : un événement sur ``node`` dans (t, t+horizon]."""
    return any(t < et <= t + horizon for et in ev_by_node.get(node, set()))


def label_lag_k(ev_by_node: dict[str, set[int]], node: str, t: int, k: int) -> bool:
    """Vérité terrain « fenêtre de lag k » : événement dans (t+k-1, t+k]."""
    return any(t + k - 1 < et <= t + k for et in ev_by_node.get(node, set()))


def with_labels(
    points: list[Point], ev_by_node: dict[str, set[int]], label_fn
) -> tuple[list[Scored], dict[str, list[Scored]]]:
    """Attache un label (booléen) à chaque point de score.

    Retourne la liste poolée (tous nœuds confondus) et le regroupement par
    nœud (nécessaire au bootstrap par grappe).
    """
    pooled: list[Scored] = []
    by_node: dict[str, list[Scored]] = {n: [] for n in NODE_IDS}
    for node, t, score in points:
        label = label_fn(ev_by_node, node, t)
        pooled.append((score, label))
        by_node[node].append((score, label))
    return pooled, by_node


# --- Statistiques hand-rolled (stdlib uniquement) ---------------------------------


def _midranks(values: list[float]) -> list[float]:
    """Rangs moyens (ex-aequo).

    Même construction que ``spearman.ranks`` dans ``analyse_campagne.py``.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def auc_mannwhitney(scored: list[Scored]) -> float | None:
    """AUC = P(score positif > score négatif).

    Calculée via la statistique U de Mann-Whitney (rangs moyens = correction
    d'ex-aequo intégrée). Équivalent à l'aire sous la ROC construite par
    balayage de seuils.
    """
    pos = [s for s, label in scored if label]
    neg = [s for s, label in scored if not label]
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = _midranks(pos + neg)
    rank_sum_pos = sum(ranks[:n_pos])
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2
    return u / (n_pos * n_neg)


def percentile(sorted_values: list[float], pct: float) -> float | None:
    """Percentile par interpolation linéaire (convention numpy ``'linear'``).

    ``sorted_values`` DOIT déjà être trié.
    """
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    d = k - f
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * d


def auc_bootstrap_ci(
    by_node: dict[str, list[Scored]], seed: int = SEED, n_boot: int = N_BOOT
) -> tuple[float | None, float | None]:
    """IC95 de l'AUC par bootstrap CLUSTER sur les 8 node_ids.

    À chaque tirage, on rééchantillonne les NŒUDS (avec remise), pas les
    points — les points d'un même nœud sont corrélés dans le temps (une
    seule trajectoire), donc rééchantillonner les points directement
    sous-estimerait la variance.
    """
    nodes = sorted(n for n in by_node if by_node[n])
    if not nodes:
        return None, None
    rng = random.Random(seed)
    aucs: list[float] = []
    for _ in range(n_boot):
        drawn = [rng.choice(nodes) for _ in nodes]
        pooled = [pt for nd in drawn for pt in by_node[nd]]
        a = auc_mannwhitney(pooled)
        if a is not None:
            aucs.append(a)
    if not aucs:
        return None, None
    aucs.sort()
    return percentile(aucs, 2.5), percentile(aucs, 97.5)


def roc_curve(scored: list[Scored]) -> list[dict]:
    """ROC complète.

    Balaie TOUTES les valeurs distinctes observées comme seuils
    (``prédit = score >= seuil``), en ordre décroissant, plus un point de
    départ « rien prédit positif » (seuil > max).
    """
    n_pos = sum(1 for _, label in scored if label)
    n_neg = len(scored) - n_pos
    distinct = sorted({s for s, _ in scored}, reverse=True)
    incr: dict[float, list[int]] = {}
    for s, label in scored:
        d_tp, d_fp = incr.get(s, [0, 0])
        if label:
            d_tp += 1
        else:
            d_fp += 1
        incr[s] = [d_tp, d_fp]

    points = [
        {
            "threshold": (distinct[0] + 1.0) if distinct else 1.0,
            "tp": 0,
            "fp": 0,
            "tn": n_neg,
            "fn": n_pos,
            "tpr": 0.0,
            "fpr": 0.0,
        }
    ]
    tp = fp = 0
    for s in distinct:
        d_tp, d_fp = incr[s]
        tp += d_tp
        fp += d_fp
        tn, fn = n_neg - fp, n_pos - tp
        points.append(
            {
                "threshold": s,
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "tpr": tp / n_pos if n_pos else 0.0,
                "fpr": fp / n_neg if n_neg else 0.0,
            }
        )
    return points


def average_precision(scored: list[Scored]) -> float | None:
    """PR-AUC (average precision).

    Intégrale en escalier sur les seuils distincts — même convention de
    regroupement d'ex-aequo que ``roc_curve``.
    """
    pos_total = sum(1 for _, label in scored if label)
    if pos_total == 0:
        return None
    by_score: dict[float, list[bool]] = {}
    for s, label in scored:
        by_score.setdefault(s, []).append(label)
    tp = fp = 0
    prev_recall = 0.0
    ap = 0.0
    for s in sorted(by_score, reverse=True):
        labels = by_score[s]
        tp += sum(1 for label in labels if label)
        fp += sum(1 for label in labels if not label)
        precision = tp / (tp + fp)
        recall = tp / pos_total
        ap += (recall - prev_recall) * precision
        prev_recall = recall
    return ap


def _f1(p: dict) -> float:
    tp, fp, fn = p["tp"], p["fp"], p["fn"]
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0


def best_thresholds(roc_points: list[dict]) -> tuple[dict, dict]:
    """Meilleur seuil au sens F1 et au sens Youden (J = TPR − FPR).

    Chaque résultat inclut sa matrice de confusion complète.
    """
    best_f1 = max(roc_points, key=_f1)
    best_youden = max(roc_points, key=lambda p: p["tpr"] - p["fpr"])
    return best_f1, best_youden


def baseline_naive_detector(
    data: dict[int, dict], horizon: int = HORIZON, seuil: float = 0.5
) -> str:
    """Détecteur nul : « Ur_local >= 0.5 ».

    Même grille que ``analyse_campagne.baseline_naive`` (recalculé ici pour
    rester autonome ; AUCUN import de ``analyse_campagne``).
    """
    ev_by_node = event_tours_by_node()
    tp = fp = tn = fn = 0
    for node in NODE_IDS:
        for t in sorted(data):
            n = data[t]["nodes"].get(node)
            if n is None:
                continue
            predicted = float(n["ur_local"]) >= seuil
            actual = label_horizon(ev_by_node, node, t, horizon)
            tp += predicted and actual
            fp += predicted and not actual
            tn += (not predicted) and not actual
            fn += (not predicted) and actual
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return f"TP={tp} FP={fp} TN={tn} FN={fn} précision={prec:.2f} rappel={rec:.2f}"


def analyze_signal(data: dict[int, dict], signal: str) -> dict:
    """Batterie complète pour un signal sur un jeu de snapshots.

    ROC, AUC, IC95, PR-AUC, meilleurs seuils F1 et Youden.
    """
    ev_by_node = event_tours_by_node()
    points = scored_points(data, signal)
    pooled, by_node = with_labels(
        points, ev_by_node, lambda ev, n, t: label_horizon(ev, n, t, HORIZON)
    )
    auc = auc_mannwhitney(pooled)
    ci_lo, ci_hi = auc_bootstrap_ci(by_node) if auc is not None else (None, None)
    prauc = average_precision(pooled)
    roc = roc_curve(pooled)
    best_f1, best_youden = best_thresholds(roc)
    return {
        "signal": signal,
        "n": len(pooled),
        "n_pos": sum(1 for _, label in pooled if label),
        "auc": auc,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "prauc": prauc,
        "roc": roc,
        "best_f1": best_f1,
        "best_youden": best_youden,
    }


def lag_analysis(
    data: dict[int, dict], signal: str, ks: tuple[int, ...] = LAGS
) -> dict[int, float | None]:
    """AUC(signal) contre une vérité terrain resserrée à la fenêtre (t+k-1, t+k].

    Pour k=1..4 — décide si le signal est un vrai PRÉCURSEUR (AUC stable ou
    en hausse quand k augmente, i.e. il « voit venir ») ou un simple
    NOWCAST (AUC en hausse quand k DIMINUE, i.e. il ne fait que confirmer un
    événement en cours).
    """
    ev_by_node = event_tours_by_node()
    points = scored_points(data, signal)
    out: dict[int, float | None] = {}
    for k in ks:
        pooled, _ = with_labels(points, ev_by_node, lambda ev, n, t, k=k: label_lag_k(ev, n, t, k))
        out[k] = auc_mannwhitney(pooled)
    return out


def _fmt(x: float | None, spec: str = ".3f") -> str:
    return format(x, spec) if x is not None else "n/a"


def _fmt_ci(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "n/a"
    return f"[{lo:.3f}, {hi:.3f}]"


def _fmt_confusion(p: dict) -> str:
    return f"TP={p['tp']} FP={p['fp']} TN={p['tn']} FN={p['fn']}"


def render_signal_table(results: dict[str, dict]) -> list[str]:
    """Table markdown signal x AUC/IC95/PR-AUC/meilleurs seuils."""
    lines = [
        "| Signal | n (pos/neg) | AUC | IC95 (bootstrap cluster, 1000 tirages) | PR-AUC | "
        "Seuil F1 (F1) | Confusion @F1 | Seuil Youden (J) | Confusion @Youden |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for signal in SIGNALS:
        r = results[signal]
        n_pos, n_neg = r["n_pos"], r["n"] - r["n_pos"]
        bf1, by = r["best_f1"], r["best_youden"]
        lines.append(
            f"| `{signal}` | {r['n']} ({n_pos}/{n_neg}) | {_fmt(r['auc'])} | "
            f"{_fmt_ci(r['ci_lo'], r['ci_hi'])} | {_fmt(r['prauc'])} | "
            f"{bf1['threshold']:.3f} (F1={_f1(bf1):.3f}) | {_fmt_confusion(bf1)} | "
            f"{by['threshold']:.3f} (J={by['tpr'] - by['fpr']:.3f}) | {_fmt_confusion(by)} |"
        )
    return lines


def render_lag_table(lag: dict[int, float | None], signal: str) -> list[str]:
    """Table markdown k -> AUC, plus une phrase d'interprétation nowcast/précurseur."""
    lines = [
        f"Signal retenu (AUC horizon 4 la plus élevée) : `{signal}`.",
        "",
        "| k (fenêtre (t+k-1, t+k]) | AUC |",
        "|---|---|",
    ]
    for k in LAGS:
        lines.append(f"| {k} | {_fmt(lag[k])} |")
    lines.append("")
    valid = {k: v for k, v in lag.items() if v is not None}
    if len(valid) >= 2:
        ks_sorted = sorted(valid)
        first, last = valid[ks_sorted[0]], valid[ks_sorted[-1]]
        if first > last + 0.02:
            interp = (
                f"AUC décroît quand k augmente ({first:.3f} à k={ks_sorted[0]} → "
                f"{last:.3f} à k={ks_sorted[-1]}) : le signal est plus fort PRÈS de "
                "l'événement — c'est un effet de NOWCAST (contemporanéité), pas un "
                "vrai signal précurseur à 4 tours."
            )
        elif last > first + 0.02:
            interp = (
                f"AUC stable ou en hausse avec k ({first:.3f} à k={ks_sorted[0]} → "
                f"{last:.3f} à k={ks_sorted[-1]}) : pas de dégradation en s'éloignant "
                "de l'événement — cohérent avec un signal réellement PRÉCURSEUR."
            )
        else:
            interp = f"AUC quasi stable selon k ({first:.3f} → {last:.3f}) : pas de gradient net."
    else:
        interp = (
            "IC95/AUC non calculables sur au moins un k (classe manquante) — "
            "interprétation non concluante."
        )
    lines.append(f"**Interprétation** : {interp}")
    return lines


def write_figures(
    results_by_set: dict[str, dict[str, dict]],
    lag_by_set: dict[str, tuple[str, dict]],
) -> str:
    """Écrit les figures ROC et AUC-vs-lag (best-effort, matplotlib optionnel)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        FIGURES.mkdir(exist_ok=True)

        for set_name, results in results_by_set.items():
            fig, ax = plt.subplots(figsize=(6, 6))
            for signal in SIGNALS:
                roc = results[signal]["roc"]
                ax.plot(
                    [p["fpr"] for p in roc],
                    [p["tpr"] for p in roc],
                    label=f"{signal} (AUC={_fmt(results[signal]['auc'])})",
                    lw=1.8,
                )
            ax.plot([0, 1], [0, 1], ls=":", color="grey", lw=1, label="hasard (AUC=0.5)")
            ax.set_xlabel("Taux de faux positifs")
            ax.set_ylabel("Taux de vrais positifs")
            ax.set_title(f"ROC — {set_name}")
            ax.legend(fontsize=8, loc="lower right")
            safe = set_name.replace(" ", "_")
            fig.savefig(FIGURES / f"roc_{safe}.png", dpi=120, bbox_inches="tight")
            plt.close(fig)

        for set_name, (signal, lag) in lag_by_set.items():
            ks = [k for k in LAGS if lag[k] is not None]
            if not ks:
                continue
            fig, ax = plt.subplots(figsize=(5, 4))
            ax.plot(ks, [lag[k] for k in ks], marker="o")
            ax.axhline(0.5, ls=":", color="grey", lw=1)
            ax.set_xlabel("k — fenêtre (t+k-1, t+k]")
            ax.set_ylabel("AUC")
            ax.set_title(f"AUC vs lag — {signal} ({set_name})")
            ax.set_xticks(ks)
            safe = set_name.replace(" ", "_")
            fig.savefig(FIGURES / f"lag_{safe}.png", dpi=120, bbox_inches="tight")
            plt.close(fig)
        return f"figures écrites sous {FIGURES.relative_to(_HERE.parent.parent)}/"
    except ImportError:
        return "matplotlib indisponible : figures non générées (tables complètes dans ce rapport)"


def compute_verdict(results_by_set: dict[str, dict[str, dict]]) -> list[str]:
    """VERDICT explicite GO / pivot.

    Basé sur la meilleure AUC observée tous signaux et tous jeux de
    snapshots confondus.
    """
    candidates: list[tuple[str, str, float, float | None, float | None]] = []
    for set_name, results in results_by_set.items():
        for signal in SIGNALS:
            r = results[signal]
            if r["auc"] is not None:
                candidates.append((set_name, signal, r["auc"], r["ci_lo"], r["ci_hi"]))
    lines = []
    if not candidates:
        lines.append("VERDICT : aucune AUC calculable (pas de données) — diagnostic non concluant.")
        return lines

    set_name, signal, auc, lo, hi = max(candidates, key=lambda c: c[2])
    all_in_noise_band = all(0.45 <= c[2] <= 0.55 for c in candidates)

    if auc > 0.65:
        lines.append(
            f"VERDICT : AUC(meilleur signal) = AUC(`{signal}`, {set_name}) = {auc:.3f} "
            f"(IC95 {_fmt_ci(lo, hi)}) > 0.65 → le signal existe, le seuil pré-enregistré "
            "était mal placé — GO pour la suite."
        )
    elif all_in_noise_band:
        lines.append(
            f"VERDICT : AUC ∈ [0.45, 0.55] partout (meilleur : `{signal}`, {set_name} = "
            f"{auc:.3f}) → pas de contenu prédictif avant ; le pipeline bascule sur "
            "rollouts + features brutes (pivot prévu, coût nul)."
        )
    else:
        lines.append(
            f"VERDICT (zone grise) : AUC(meilleur signal) = AUC(`{signal}`, {set_name}) = "
            f"{auc:.3f} (IC95 {_fmt_ci(lo, hi)}) — ni > 0.65 (signal net), ni dans "
            "[0.45, 0.55] partout (bruit pur). Ni GO franc ni pivot immédiat : cf. la "
            "table de lag et les IC95 par signal ci-dessus avant de trancher. Par défaut, "
            "traiter comme NON-GO (le seuil gelé n'est pas disqualifié à tort, mais le "
            "signal n'est pas assez net pour relancer HA4 tel quel)."
        )

    if len(results_by_set) < len(SNAPSHOT_SETS):
        missing = [name for name, path in SNAPSHOT_SETS if name not in results_by_set]
        lines.append(
            f"Note : jeu(x) de snapshots indisponible(s) au moment de l'analyse : "
            f"{', '.join(missing)} — verdict basé uniquement sur les données présentes."
        )
    return lines


def main() -> int:
    """Analyse les deux jeux de snapshots, écrit diagnostic_ha4.md et imprime le verdict."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows cp1252

    md_lines = [
        "# Diagnostic HA4 — balayage de seuil du signal prédictif",
        "",
        "**EXPLORATOIRE — hors registre pré-enregistré** (voir PROTOCOLE.md §5). "
        "Ce document ne modifie ni ne réinterprète le verdict gelé de HA4 "
        "(`analyse_campagne.ha4()`, `rapport.md`) : il diagnostique, à seuil "
        "libre, si Ur/Ud/H portent un pouvoir discriminant quelconque à "
        "l'horizon 4 tours.",
        "",
    ]

    results_by_set: dict[str, dict[str, dict]] = {}
    lag_by_set: dict[str, tuple[str, dict]] = {}

    for set_name, snapshots_dir in SNAPSHOT_SETS:
        data = load(snapshots_dir)
        md_lines.append(f"## Jeu de données : {set_name}")
        md_lines.append("")
        if not data:
            md_lines += [
                f"Snapshots introuvables sous `{snapshots_dir.relative_to(_HERE.parent.parent)}` "
                "au moment de l'exécution — jeu ignoré (probable dépendance d'une autre "
                "unité du plan HÉLIOS v7, pas encore fusionnée). Le script est prêt à le "
                "traiter dès qu'il apparaîtra (relancer ce script suffit).",
                "",
            ]
            print(f"[SKIP] {set_name} : aucun snapshot sous {snapshots_dir}")
            continue

        max_t = max(data)
        md_lines.append(
            f"Tours analysés : {min(data)}-{max_t} ({len(data)} tours, {len(NODE_IDS)} "
            "nœuds) ; horizon HA4 = 4 tours."
        )
        md_lines.append("")

        results = {signal: analyze_signal(data, signal) for signal in SIGNALS}
        results_by_set[set_name] = results
        md_lines += render_signal_table(results)
        md_lines.append("")

        best_signal = max(
            SIGNALS, key=lambda s: results[s]["auc"] if results[s]["auc"] is not None else -1.0
        )
        lag = lag_analysis(data, best_signal)
        lag_by_set[set_name] = (best_signal, lag)
        md_lines.append("### Analyse de lag (signal retenu)")
        md_lines.append("")
        md_lines += render_lag_table(lag, best_signal)
        md_lines.append("")

        md_lines.append("### Baseline naïve (Ur_local >= 0.5, horizon 4, même grille que HA4)")
        md_lines.append("")
        md_lines.append(baseline_naive_detector(data))
        md_lines.append("")

        print(
            f"[OK ] {set_name} : {len(data)} tours — meilleur signal = {best_signal} "
            f"(AUC={_fmt(results[best_signal]['auc'])})"
        )
        for signal in SIGNALS:
            r = results[signal]
            print(
                f"      {signal:<12} AUC={_fmt(r['auc'])} IC95={_fmt_ci(r['ci_lo'], r['ci_hi'])} "
                f"PR-AUC={_fmt(r['prauc'])}"
            )

    fig_note = write_figures(results_by_set, lag_by_set)
    md_lines.append("## Figures")
    md_lines.append("")
    md_lines.append(f"- {fig_note}")
    md_lines.append("")

    md_lines.append("## VERDICT")
    md_lines.append("")
    verdict_lines = compute_verdict(results_by_set)
    md_lines += verdict_lines
    md_lines.append("")

    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")

    print()
    for line in verdict_lines:
        print(line)
    print(f"\nRapport : {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
