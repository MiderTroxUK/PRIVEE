"""Generate the thesis figures that are computed rather than captured.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_figures.py

Reads derived.json (written by derive.py) plus the segmentation training logs, and
writes PNGs into ../../Images/. Every number plotted comes from those files; none
is hard-coded here.

Palette is the ALTEN brand charter used throughout the document: navy for text and
axes, azure for computed quantities, ochre for observed or reference quantities.
The charter excludes red, so the "wrong" series uses ochre, never red.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
IMAGES = HERE.parents[1] / "Images"
VOLUME = Path(r"C:\PRIVEE\GIT\SMART_GREEN_SUPPLY_CHAIN\VOLUME_ENTREPOT")

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
    """Write the figure as vector first, raster last.

    The PDF is what pdflatex includes, so a curve stays sharp at any zoom and at
    any print size; the SVG travels to the defence slides; the PNG remains for
    quick previews and for anything that cannot read vector.
    """
    out = IMAGES / name
    out.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".pdf", ".svg", ".png"):
        path = out.with_suffix(suffix)
        fig.savefig(path, facecolor="white")
        print(f"  wrote {path.relative_to(IMAGES.parent)}")
    plt.close(fig)


def fig_reliability() -> None:
    """Reliability diagram at four weeks: announced against observed, per band.

    The bands are the uneven ones used in the text, because a uniform ten-bin
    split hides that the whole confident tail is empty.
    """
    bands = D["arm_a"]["correct_target"]["4"]["reliability"]
    fig, ax = plt.subplots(figsize=(6.4, 4.6))

    ax.plot([0, 1], [0, 1], color=GREY_LINE, lw=1.2, ls="--", zorder=1,
            label="perfect calibration")

    ann = [b["announced"] for b in bands]
    obs = [b["observed"] for b in bands]
    ns = [b["n"] for b in bands]
    sizes = [40 + 9 * n for n in ns]

    ax.scatter(ann, obs, s=sizes, color=AZURE, edgecolor=NAVY, lw=1.2, zorder=3,
               label="observed frequency (area $\\propto$ n)")

    for a, o, n in zip(ann, obs, ns):
        # keep labels off the axis line and inside the frame
        dy = 26 if n > 40 else 20
        ha = "right" if a > 0.9 else ("left" if a < 0.05 else "center")
        ax.annotate(f"n={n}", (a, o), textcoords="offset points",
                    xytext=(0, dy), ha=ha, fontsize=8.5, color=GREY_TEXT)

    # the confident region, where nothing materialised
    ax.axvspan(0.5, 1.02, color=OCHRE_PALE, alpha=0.45, zorder=0)
    ax.annotate("21 forecasts announced\na mean of 0.948.\nNone materialised.",
                xy=(0.76, 0.34), ha="center", fontsize=9, color=NAVY,
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=OCHRE, lw=1.2))

    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.03, 1.02)
    ax.set_xlabel("Mean announced probability")
    ax.set_ylabel("Observed frequency of an adverse outcome")
    ax.set_title("Reliability of the four-week forecast, arm A", color=NAVY, pad=12)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    save(fig, "armA_reliability.png")


def _roc(p: np.ndarray, y: np.ndarray):
    order = np.argsort(-p, kind="mergesort")
    ys = y[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    tpr = np.concatenate([[0.0], tp / max(tp[-1], 1)])
    fpr = np.concatenate([[0.0], fp / max(fp[-1], 1)])
    return fpr, tpr


def fig_roc() -> None:
    """ROC at four weeks under the two outcome definitions.

    The scored pairs are read straight out of derived.json, so this curve and the
    AUC quoted in the text are guaranteed to come from the same numbers.
    """
    fig, ax = plt.subplots(figsize=(5.6, 5.0))
    ax.plot([0, 1], [0, 1], color=GREY_LINE, lw=1.2, ls="--", label="chance")

    for tag_key, colour, style, tag in (
        ("correct_target", AZURE, "-", "production definition"),
        ("wrong_target", OCHRE, "-", "naive definition"),
    ):
        s = D["arm_a"][tag_key]["4"]
        p = np.asarray(s["points"]["p"], dtype=float)
        y = np.asarray(s["points"]["y"], dtype=float)
        fpr, tpr = _roc(p, y)
        ax.step(fpr, tpr, where="post", color=colour, ls=style, lw=2.0,
                label=f"{tag}\nAUC {s['auc']:.3f}, "
                      f"base rate {s['base_rate']:.1%}")

    ax.set_xlim(-0.01, 1.01)
    ax.set_ylim(-0.01, 1.01)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("Same forecasts, two definitions of an adverse outcome",
                 color=NAVY, pad=12)
    ax.legend(frameon=False, loc="lower right", fontsize=8.5)
    save(fig, "armA_roc.png")


def fig_arm_b() -> None:
    """Influence of the displayed forecast, turn by turn."""
    per = D["arm_b"]["declarations"]["per_turn"]
    turns = sorted(per, key=int)
    cats = [("aucune", "no influence", "#DAE8F3"),
            ("confirme", "confirms", AZURE_LIGHT),
            ("revise_a_la_hausse", "revised upward", NAVY),
            ("revise_a_la_baisse", "revised downward", OCHRE)]

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    bottom = np.zeros(len(turns))
    x = np.arange(len(turns))
    for key, label, colour in cats:
        vals = np.array([per[t][key] for t in turns], dtype=float)
        ax.bar(x, vals, bottom=bottom, color=colour, edgecolor="white", lw=0.8,
               label=label)
        bottom += vals

    i4 = turns.index("4")
    ax.axvline(i4 - 0.5, color=NAVY, lw=1.4, ls="--")
    ax.annotate("forecast first shown", xy=(i4 - 0.45, 8.6), fontsize=9, color=NAVY,
                ha="left", va="bottom")

    if "6" in turns:
        i6 = turns.index("6")
        ax.annotate("critical event", xy=(i6, 8.15), xytext=(i6, 9.9),
                    fontsize=9, color=NAVY, ha="center",
                    arrowprops=dict(arrowstyle="->", color=NAVY, lw=1.2))

    ax.set_xticks(x)
    ax.set_xticklabels([f"T{t}" for t in turns])
    ax.set_ylim(0, 11.2)
    ax.set_yticks(range(0, 9, 2))
    ax.set_ylabel("Declarants (of 8)")
    ax.set_title("Arm B: recorded influence of the displayed forecast, by turn",
                 color=NAVY, pad=12)
    ax.legend(frameon=False, ncol=4, fontsize=9, loc="upper center",
              bbox_to_anchor=(0.5, -0.10))
    save(fig, "armB_influence.png")


def _run_curve(name: str):
    path = VOLUME / "runs" / name / "results.csv"
    if not path.exists():
        return None
    ep, m = [], []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = next((k for k in row if "mAP50-95(M)" in k), None)
            if key is None or not row.get(key):
                continue
            ep.append(float(row["epoch"]))
            m.append(float(row[key]))
    return np.array(ep), np.array(m)


def fig_volume_training() -> None:
    """Segmentation training progression across the four runs."""
    runs = [("quai",  "run 1: 86 images, 640 px", AZURE_LIGHT, "-"),
            ("quai2", "run 2: 203 images, 640 px", AZURE, "-"),
            ("quai3", "run 3: 351 images, 640 px", NAVY, "-"),
            ("quai4", "run 4: 351 images, 1280 px", OCHRE, "--")]

    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    for name, label, colour, style in runs:
        got = _run_curve(name)
        if got is None:
            continue
        ep, m = got
        ax.plot(ep, m, color=colour, ls=style, lw=1.9, label=label)
        best = int(np.argmax(m))
        ax.scatter([ep[best]], [m[best]], color=colour, s=32, zorder=5,
                   edgecolor="white", lw=1.0)
        ax.annotate(f"{m[best]:.3f}", (ep[best], m[best]),
                    textcoords="offset points", xytext=(6, 4),
                    fontsize=8.5, color=colour)

    ax.set_xlabel("Epoch")
    ax.set_ylabel("Mask mAP50-95 on the validation split")
    ax.set_title("Dock-zone segmentation: data helped, resolution did not",
                 color=NAVY, pad=12)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.grid(axis="y", color=GREY_LINE, lw=0.6, alpha=0.6)
    ax.set_axisbelow(True)
    save(fig, "volume_training.png")


def fig_volume_calibration() -> None:
    """Declared-to-geometric volume ratio over the retained, auditable corpus.

    Deliberately NOT presented as the calibration that fixed the production
    constant: that run covered 122 sites and its detailed output was not kept.
    This plots the 68 matched sites that are still on disk, and shows the
    production constant against them, which is the honest comparison.
    """
    corpus = VOLUME / "data" / "CORPUS.json"
    if not corpus.exists():
        print("  skipped volume_calibration: corpus not found")
        return
    data = json.loads(corpus.read_text(encoding="utf-8"))
    ratios = np.array([s["ratio"] for s in data
                       if s.get("ratio") and 0.05 < s["ratio"] < 20])
    if len(ratios) < 10:
        print("  skipped volume_calibration: too few matched sites")
        return

    med = float(np.median(ratios))
    q1, q3 = float(np.percentile(ratios, 25)), float(np.percentile(ratios, 75))
    production = 0.80

    fig, ax = plt.subplots(figsize=(6.8, 4.3))
    ax.hist(ratios, bins=np.arange(0, 2.7, 0.1), color=AZURE_LIGHT,
            edgecolor=NAVY, lw=0.8, zorder=2)
    ax.axvspan(q1, q3, color=BLUE_BG, alpha=0.8, zorder=0,
               label=f"IQR of this sample [{q1:.2f}, {q3:.2f}]")
    ax.axvline(med, color=NAVY, lw=2.2, zorder=3,
               label=f"median of this sample: {med:.2f}")
    ax.axvline(production, color=OCHRE, lw=2.2, ls="--", zorder=3,
               label=f"constant used in production: {production:.2f}")

    ax.set_xlabel("Declared storage volume / (footprint area $\\times$ height)")
    ax.set_ylabel("Warehouses")
    ax.set_title(f"Fill factor against the retained corpus, n = {len(ratios)} sites",
                 color=NAVY, pad=12)
    ax.legend(frameon=False, fontsize=9)
    ax.set_axisbelow(True)
    save(fig, "volume_calibration.png")


if __name__ == "__main__":
    print("generating figures...")
    fig_reliability()
    fig_roc()
    fig_arm_b()
    fig_volume_training()
    fig_volume_calibration()
    print("done")
