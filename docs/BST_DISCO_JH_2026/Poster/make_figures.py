"""Poster-only variant of the HELIOS adequacy chart.

Re-renders the LLM-pilot adequacy curve using the ALTEN Brand Book 2025 palette
and English labels, for the A1 poster. Writes into this Poster/img/ folder only:
the BST report keeps its own figures in Images/4.Operations/ untouched.

Run:  .venv/Scripts/python.exe docs/BST_DISCO_JH_2026/Poster/make_figures.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
LLM_CSV = (
    ROOT / "projects" / "simu_semiconducteurs" / "analysis" / "llm_pilot_run"
    / "resultats_pilot.csv"
)
OUT_DIR = Path(__file__).resolve().parent / "img"

# ALTEN Brand Book 2025 (EN), certified colours only
NAVY = "#043962"  # main - navy blue, all text
AZURE = "#008BD2"  # main - azure blue, the data series
OCHRE_SHADE = "#FFBA00"  # secondary shade, p.28: "to differentiate data"
BG_BLUE = "#EBF3F9"  # tertiary, background bands
LINE_GREY = "#CDCEDA"  # tertiary, grid lines
CAPTION_GREY = "#8C8C9A"  # tertiary, secondary text
NAVY_LIGHT = "#8D9CAD"  # navy shade, axis spines

# Event labels in English (the report's figure keeps the French wording).
EVENTS = [
    (3, "demand spike", -5),
    (5, "allocation", -6),
    # Offsets alternate between two rows so neighbouring labels never collide.
    (6, "Texas freeze", -5),
    (7, "fire + Suez", -11),
    (10, "drought", -5),
    (12, "backend", -5),
    (13, "bullwhip", -11),
    (14, "congestion", -5),
    (16, "polysilicon", -5),
]

PERIODS = [
    (0.5, 4.5, "P1 Baseline"),
    (4.5, 8.5, "P2 Tipping point"),
    (8.5, 12.5, "P3 Squeeze"),
    (12.5, 16.5, "P4 Rupture"),
    (16.5, 18.5, "P5 Recovery"),
]


def load_avg_adequacy(csv_path: Path) -> dict[int, float]:
    """Average adequacy A per turn."""
    by_tour: dict[int, list[float]] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_tour.setdefault(int(row["tour"]), []).append(float(row["adequation"]))
    return {t: sum(v) / len(v) for t, v in sorted(by_tour.items())}


def generate(llm_avg: dict[int, float]) -> Path:
    fig, ax = plt.subplots(figsize=(15, 4.2), dpi=180)

    for idx, (x1, x2, label) in enumerate(PERIODS):
        if idx % 2 == 0:
            ax.axvspan(x1, x2, color=BG_BLUE, zorder=0)
        ax.text((x1 + x2) / 2, 97, label, ha="center", va="top",
                fontsize=11, color=CAPTION_GREY)

    tours = sorted(llm_avg)
    ax.plot(tours, [llm_avg[t] for t in tours], color=AZURE, lw=2.8,
            marker="o", ms=6, zorder=3)

    for t_ev, label_ev, offset in EVENTS:
        if t_ev in llm_avg:
            val = llm_avg[t_ev]
            ax.plot(t_ev, val, marker="v", color=OCHRE_SHADE, ms=10,
                    markeredgecolor=NAVY, markeredgewidth=0.8, zorder=4)
            # Brand rule p.33: never set text in yellow - labels stay navy.
            ax.text(t_ev, val + offset, label_ev, ha="center",
                    va="top" if offset < 0 else "bottom",
                    fontsize=9.5, color=NAVY)

    ax.set_ylabel("Network-average adequacy A", fontsize=12, color=NAVY, labelpad=10)
    ax.set_ylim(35, 100)
    ax.set_xlim(-0.5, 18.5)
    ax.set_xticks(tours)
    ax.set_xticklabels([f"T{t}" for t in tours], fontsize=10.5)
    ax.set_yticks([40, 50, 60, 70, 80, 90, 100])
    ax.tick_params(axis="both", which="major", labelsize=10, colors=NAVY)
    ax.grid(True, linestyle=":", alpha=0.7, color=LINE_GREY)

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(NAVY_LIGHT)

    plt.tight_layout()
    out_path = OUT_DIR / "helios_llm_pilot_adequacy.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    print(f"written: {generate(load_avg_adequacy(LLM_CSV))}")
