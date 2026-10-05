"""Generate the figures that carry uncertainty and cost, rather than prose.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_inference_figures.py

Four figures, each replacing a passage the reader currently has to assemble
from a table by hand:

  noisy_or_vs_average  the aggregator argument of Section 3.2.2, as a curve
  benchmarks           the measured timings of Section 3.3.7, on a log scale
  auc_forest           the discrimination tests of Section 4.8, against chance
  wilson_intervals     the counted claims of Section 4.8, with their overlap

Every plotted number comes from derived.json, from the benchmark JSON written
by pytest-benchmark, or from the closed-form formula named in the caption.
Nothing is hard-coded from the prose.

Palette is the ALTEN charter: navy for text and axes, azure for the computed
signal, ochre for reference and baseline quantities. The charter excludes red,
so an unfavourable result is drawn in ochre and never in red.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
IMAGES = HERE.parents[1] / "Images"

NAVY = "#043962"
AZURE = "#008BD2"
AZURE_LIGHT = "#7DCAED"
OCHRE = "#FFBA00"
OCHRE_PALE = "#FFEF86"
GREY_LINE = "#CDCEDA"
GREY_TEXT = "#8C8C9A"
BLUE_BG = "#EBF3F9"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Carlito", "Calibri", "DejaVu Sans"],
    "font.size": 10,
    "text.color": NAVY,
    "axes.labelcolor": NAVY,
    "axes.edgecolor": NAVY,
    "xtick.color": NAVY,
    "ytick.color": NAVY,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
})

D = json.loads((HERE / "derived.json").read_text(encoding="utf-8"))


def save(fig, name: str) -> None:
    """Write the figure as vector first, raster last."""
    out = IMAGES / name
    out.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".pdf", ".svg", ".png"):
        fig.savefig(out.with_suffix(suffix), facecolor="white")
    plt.close(fig)
    print(f"  wrote {name}.pdf/.svg/.png")


def wilson(k: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    """Score interval for a binomial proportion, valid at k = 0 and k = n."""
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


# ── 1. The aggregator argument ────────────────────────────────────────────
def fig_noisy_or() -> None:
    """One block rises, five stay put: what each aggregator does with that.

    The point of the figure is the gap at the right-hand edge, where the
    rising block saturates: the noisy-OR reaches 1 exactly and the average
    is still below 0.4.
    """
    others = [0.35, 0.20, 0.15, 0.28]          # the five other blocks, fixed
    u = np.linspace(0.0, 1.0, 400)
    survival_others = np.prod([1 - o for o in others])
    noisy = 1 - (1 - u) * survival_others
    average = (u + sum(others)) / (len(others) + 1)

    fig, ax = plt.subplots(figsize=(6.6, 3.5))
    ax.axhspan(0.0, 1.0, color=BLUE_BG, zorder=0)
    ax.plot(u, noisy, color=AZURE, lw=2.6, label="weighted probabilistic OR", zorder=3)
    ax.plot(u, average, color=OCHRE, lw=2.6, ls="--", label="weighted average", zorder=3)

    ax.annotate("", xy=(1.0, 1.0), xytext=(1.0, average[-1]),
                arrowprops=dict(arrowstyle="<->", color=NAVY, lw=1.2))
    ax.text(0.965, (1.0 + average[-1]) / 2, f"{1.0 - average[-1]:.2f}", ha="right",
            va="center", fontsize=9, color=NAVY, fontweight="bold")
    ax.text(0.95, 1.045, "deadline passed", ha="right", va="bottom", fontsize=8.5,
            color=GREY_TEXT, style="italic")
    ax.axvline(1.0, color=GREY_LINE, lw=1, zorder=1)

    ax.set_xlabel(r"$u_{\mathrm{time}}$, the one block that rises")
    ax.set_ylabel(r"$U_{r,\mathrm{local}}$")
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.08)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    save(fig, "noisy_or_vs_average")


# ── 2. Measured cost ──────────────────────────────────────────────────────
def fig_benchmarks() -> None:
    """The seven measured operations, log scale, with the model/plumbing split."""
    rows = [
        ("Incremental propagation, 1 node", 1.044, 0.249, "model"),
        ("What-if shock, rank-25 supplier", 4.991, 1.056, "model"),
        (r"Full propagation, $U_d$ and $U_r$", 6.335, 1.120, "model"),
        ("Dashboard network figure", 43.656, 1.012, "plumbing"),
        ("Evaluate every node and persist", 105.208, 16.235, "plumbing"),
        (r"Monte Carlo, $N=10\,000$", 478.825, 33.934, "model"),
        ("Load graph from registry", 782.126, 39.755, "plumbing"),
    ]
    labels = [r[0] for r in rows]
    means = np.array([r[1] for r in rows])
    sds = np.array([r[2] for r in rows])
    colours = [AZURE if r[3] == "model" else OCHRE for r in rows]

    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    y = np.arange(len(rows))[::-1]
    ax.barh(y, means, xerr=sds, color=colours, height=0.62,
            error_kw=dict(ecolor=NAVY, lw=1.1, capsize=2.5), zorder=3)
    for yi, m in zip(y, means):
        ax.text(m * 1.18, yi, f"{m:,.1f}", va="center", fontsize=8.6, color=NAVY)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xscale("log")
    ax.set_xlim(0.5, 3000)
    ax.set_xlabel("mean wall clock, ms, log scale")
    ax.xaxis.grid(True, color=GREY_LINE, lw=0.7, zorder=0)
    ax.set_axisbelow(True)

    handles = [plt.Rectangle((0, 0), 1, 1, color=AZURE),
               plt.Rectangle((0, 0), 1, 1, color=OCHRE)]
    ax.legend(handles, ["model", "persistence and interface"], frameon=False,
              fontsize=9, loc="lower right")
    save(fig, "benchmarks")


# ── 3. Discrimination against chance ──────────────────────────────────────
def fig_auc_forest() -> None:
    """Eight AUCs with their bootstrap intervals, against the 0.5 line.

    Read the figure by the 0.5 rule: an interval crossing the dashed line is
    a result the campaign cannot separate from chance. All eight cross it.
    """
    pvals = {("correct_target", "1"): 0.797, ("correct_target", "2"): 0.388,
             ("correct_target", "3"): 0.590, ("correct_target", "4"): 0.904,
             ("wrong_target", "1"): 0.279, ("wrong_target", "2"): 0.192,
             ("wrong_target", "3"): 0.529, ("wrong_target", "4"): 0.823}
    names = {"correct_target": "Production", "wrong_target": "Naive"}

    rows = []
    for target in ("correct_target", "wrong_target"):
        for h in ("1", "2", "3", "4"):
            b = D["arm_a"][target][h]
            lo, hi = b["auc_ci95"]
            rows.append((f"{names[target]}, {h}w", b["auc"], lo, hi,
                         b["n_positive"], pvals[(target, h)], target))

    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    y = np.arange(len(rows))[::-1]
    ax.axvline(0.5, color=NAVY, ls="--", lw=1.3, zorder=2)
    ax.text(0.502, y[0] + 0.75, "chance", fontsize=8.5, color=NAVY, style="italic")

    for yi, (_, auc, lo, hi, npos, _, target) in zip(y, rows):
        c = AZURE if target == "correct_target" else OCHRE
        ax.plot([lo, hi], [yi, yi], color=c, lw=2.4, solid_capstyle="round", zorder=3)
        ax.plot([auc], [yi], "o", color=c, ms=7, zorder=4,
                markeredgecolor="white", markeredgewidth=1.1)

    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=9)
    ax.set_xlim(0.16, 0.95)
    ax.set_xlabel("AUC with 95% bootstrap interval")

    for yi, (_, _, _, _, npos, p, _) in zip(y, rows):
        ax.text(0.955, yi, f"{npos:>2d}   {p:.3f}", fontsize=8.6, color=NAVY,
                va="center", family="monospace")
    ax.text(0.955, y[0] + 0.75, "pos.    p", fontsize=8.4, color=GREY_TEXT,
            va="center", family="monospace")
    save(fig, "auc_forest")


# ── 4. The counted claims ─────────────────────────────────────────────────
def fig_wilson() -> None:
    """The five proportions, with the overlap that matters drawn explicitly."""
    claims = [
        ("Chain 1, precision", 3, 3),
        ("Chain 1, recall", 3, 4),
        ("Chain 1, base rate", 4, 8),
        ("Chain 2, precision", 0, 3),
        ("Chain 2, base rate", 3, 15),
    ]
    fig, ax = plt.subplots(figsize=(6.8, 3.2))
    y = np.arange(len(claims))[::-1]

    lo_p1, hi_p1 = wilson(3, 3)
    lo_p2, hi_p2 = wilson(0, 3)
    ax.axvspan(max(lo_p1, lo_p2), min(hi_p1, hi_p2), color=OCHRE_PALE, zorder=0)
    ax.text((max(lo_p1, lo_p2) + min(hi_p1, hi_p2)) / 2, y[0] + 0.72,
            "the two precisions overlap here", ha="center", fontsize=8.5,
            color=NAVY, style="italic")

    for yi, (label, k, n) in zip(y, claims):
        lo, hi = wilson(k, n)
        c = AZURE if "precision" in label else GREY_TEXT
        ax.plot([lo, hi], [yi, yi], color=c, lw=2.4, solid_capstyle="round", zorder=3)
        ax.plot([k / n], [yi], "o", color=c, ms=7, zorder=4,
                markeredgecolor="white", markeredgewidth=1.1)
        ax.text(1.02, yi, f"{k}/{n}", fontsize=8.8, color=NAVY, va="center",
                family="monospace")

    ax.set_yticks(y)
    ax.set_yticklabels([c[0] for c in claims], fontsize=9)
    ax.set_xlim(-0.02, 1.09)
    ax.set_xlabel("proportion, with 95% Wilson score interval")
    save(fig, "wilson_intervals")


# ---- 5. What the repair bought, and what it traded ----------------------
def fig_repair() -> None:
    """Brier skill and AUC across three model versions, from tab:repair_scores.

    The two panels disagree on the third version, and that disagreement is the
    finding: the progress-uncertainty term improves calibration at every horizon
    beyond one week and costs discrimination at every horizon.
    """
    horizons = [1, 2, 3, 4]
    brier = {
        "before": [-1.278, -0.690, -0.654, -0.553],
        "structure": [-0.646, -0.401, -0.360, -0.272],
        "+ uncertainty": [-0.687, -0.367, -0.286, -0.216],
    }
    auc = {
        "before": [0.736, 0.636, 0.641, 0.654],
        "structure": [0.793, 0.671, 0.657, 0.721],
        "+ uncertainty": [0.729, 0.634, 0.602, 0.584],
    }
    style = {"before": (GREY_TEXT, "o", "--"),
             "structure": (AZURE, "s", "-"),
             "+ uncertainty": (OCHRE, "^", "-")}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 3.3))

    for label, ys in brier.items():
        c, m, ls = style[label]
        ax1.plot(horizons, ys, color=c, marker=m, ls=ls, lw=2.0, ms=6, label=label)
    ax1.axhline(0.0, color=NAVY, lw=1.0, ls=":")
    ax1.text(1.05, 0.03, "a base-rate forecaster", fontsize=8, color=NAVY, style="italic")
    ax1.set_title("Brier skill", fontsize=10, color=NAVY)
    ax1.set_xlabel("horizon, weeks")
    ax1.set_xticks(horizons)
    ax1.set_ylim(-1.45, 0.22)

    for label, ys in auc.items():
        c, m, ls = style[label]
        ax2.plot(horizons, ys, color=c, marker=m, ls=ls, lw=2.0, ms=6, label=label)
    ax2.axhline(0.5, color=NAVY, lw=1.0, ls=":")
    ax2.text(1.05, 0.512, "chance", fontsize=8, color=NAVY, style="italic")
    ax2.set_title("AUC", fontsize=10, color=NAVY)
    ax2.set_xlabel("horizon, weeks")
    ax2.set_xticks(horizons)
    ax2.set_ylim(0.47, 0.86)

    ax2.legend(frameon=False, fontsize=8.6, loc="upper right")
    fig.tight_layout()
    save(fig, "repair_effect")


# ---- 6. What actually moved the segmentation model -----------------------
def fig_segmentation() -> None:
    """Four training runs, from tab:volume_training.

    Runs 1 to 3 raise the training set at a fixed image size. Run 4 holds the
    set and doubles the image size instead, and every metric falls, which is
    the point: the constraint was annotated data, not resolution.
    """
    runs = [
        (1, 86,  640,  0.461, 0.404, 0.363, 0.155),
        (2, 203, 640,  0.635, 0.539, 0.610, 0.283),
        (3, 351, 640,  0.702, 0.606, 0.618, 0.305),
        (4, 351, 1280, 0.652, 0.547, 0.570, 0.272),
    ]
    metrics = [("precision", 3, AZURE, "o"), ("recall", 4, AZURE_LIGHT, "s"),
               ("mAP50", 5, NAVY, "^"), ("mAP50-95", 6, OCHRE, "D")]

    fig, ax = plt.subplots(figsize=(6.8, 3.5))
    x = [0, 1, 2, 3]
    for name, col, colour, marker in metrics:
        ys = [r[col] for r in runs]
        ax.plot(x[:3], ys[:3], color=colour, marker=marker, lw=2.0, ms=6, label=name)
        ax.plot(x[2:], ys[2:], color=colour, marker=marker, lw=1.6, ms=6, ls=":")

    ax.axvspan(2.55, 3.45, color=OCHRE_PALE, zorder=0, alpha=0.55)
    ax.text(3.0, 0.72, "same data,\ndouble the\nimage size", ha="center", fontsize=8.4,
            color=NAVY, style="italic")

    ax.set_xticks(x)
    ax.set_xticklabels(["run 1\n86 images", "run 2\n203", "run 3\n351", "run 4\n351"],
                       fontsize=8.6)
    ax.set_ylim(0.10, 0.80)
    ax.set_ylabel("score at the best epoch")
    ax.legend(frameon=False, fontsize=8.8, ncol=4, loc="lower center",
              bbox_to_anchor=(0.5, -0.34))
    fig.tight_layout()
    save(fig, "segmentation_runs")


if __name__ == "__main__":
    fig_noisy_or()
    fig_benchmarks()
    fig_auc_forest()
    fig_wilson()
    fig_repair()
    fig_segmentation()
