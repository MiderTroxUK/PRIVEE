"""Prepare every image the web poster needs, into Poster/web/img/.

Run with the VOLUME_ENTREPOT venv (it owns Pillow and matplotlib):
  cd C:/PRIVEE/GIT/SMART_GREEN_SUPPLY_CHAIN/VOLUME_ENTREPOT
  ./.venv/Scripts/python.exe C:/PRIVEE/AZURE/docs/BST_DISCO_JH_2026/Poster/web/make_assets.py

Two jobs:
  1. crop the burnt-in title/legend bars off the VOLUME_ENTREPOT plates, so the poster
     can put its own English callouts on top in HTML, and downscale to poster size;
  2. re-render the YOLO26-seg fine-tuning curve in the ALTEN Brand Book palette.

Nothing is written outside web/img/.
"""
from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path

from PIL import Image

VE = Path("C:/PRIVEE/GIT/SMART_GREEN_SUPPLY_CHAIN/VOLUME_ENTREPOT")
BST = Path("C:/PRIVEE/AZURE/docs/BST_DISCO_JH_2026")
OUT = Path(__file__).resolve().parent / "img"
OUT.mkdir(parents=True, exist_ok=True)

# ALTEN Brand Book 2025 (EN), certified colours only
NAVY = "#043962"
AZURE = "#008BD2"
OCHRE = "#FFBA00"
BG_BLUE = "#EBF3F9"
LINE_GREY = "#CDCEDA"
CAPTION_GREY = "#8C8C9A"
NAVY_LIGHT = "#8D9CAD"
AZURE_DARK = "#176F98"


def plate(src: Path, dst: str, crop=None, width: int | None = None, quality=88):
    """Crop, downscale, write JPEG. `crop` is (left, top, right, bottom) in source px."""
    im = Image.open(src).convert("RGB")
    if crop:
        im = im.crop(crop)
    if width and im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(OUT / dst, quality=quality, optimize=True)
    print(f"{dst:34s} {im.size}")


def copy(src: Path, dst: str):
    shutil.copyfile(src, OUT / dst)
    print(f"{dst:34s} copied")


def trim(src: Path, dst: str, pad=6, thresh=248):
    """Copy a report figure with its white margin removed.

    The report's diagrams sit on a square canvas with a wide white border. On the poster
    that border is dead vertical budget, and the budget is what decides the layout.
    """
    from PIL import ImageChops
    im = Image.open(src).convert("RGB")
    mask = im.point(lambda v: 255 if v < thresh else 0).convert("L")
    box = mask.getbbox() or (0, 0, im.width, im.height)
    box = (max(0, box[0] - pad), max(0, box[1] - pad),
           min(im.width, box[2] + pad), min(im.height, box[3] + pad))
    out = im.crop(box)
    out.save(OUT / dst)
    print(f"{dst:34s} {im.size} -> {out.size}  ar={out.width / out.height:.2f}")


def training_curve():
    """mAP50 (mask) per epoch for the four fine-tuning runs, ALTEN palette."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # quai2 is a resume of an intermediate dataset and was validated on a different 50-image split: not comparable on the same axes, so it is left out.
    runs = [
        ("quai",  "86 chips · 640 px",           NAVY_LIGHT, "--", 2.0),
        ("quai4", "351 chips · 1280 px",         OCHRE,      "-",  2.2),
        ("quai3", "351 chips · 640 px  (kept)",  AZURE,      "-",  3.2),
    ]
    fig, ax = plt.subplots(figsize=(9.2, 4.0), dpi=200)
    for name, label, colour, style, lw in runs:
        rows = list(csv.DictReader(open(VE / "runs" / name / "results.csv")))
        ax.plot([int(r["epoch"]) for r in rows],
                [float(r["metrics/mAP50(M)"]) for r in rows],
                color=colour, ls=style, lw=lw, label=label, zorder=3)

    ax.set_xlabel("epoch", fontsize=12, color=NAVY)
    ax.set_ylabel("mAP50 (mask)", fontsize=12, color=NAVY, labelpad=8)
    ax.set_xlim(0, 152)
    ax.set_ylim(0, 0.70)
    ax.grid(True, ls=":", alpha=0.8, color=LINE_GREY)
    ax.tick_params(labelsize=11, colors=NAVY)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(NAVY_LIGHT)
    leg = ax.legend(loc="lower right", fontsize=12, frameon=True, framealpha=1,
                    edgecolor=LINE_GREY, facecolor="white")
    for t in leg.get_texts():
        t.set_color(NAVY)
    # 1280 px costs 4x the compute and lands lower: worth stating on the plot itself.
    ax.annotate("1280 px: 4× the compute,\nlower score", xy=(122, 0.545), xytext=(52, 0.655),
                fontsize=11.5, color=NAVY, va="top",
                arrowprops=dict(arrowstyle="-", color=NAVY_LIGHT, lw=1.2,
                                connectionstyle="arc3,rad=-0.15"))
    fig.tight_layout()
    fig.savefig(OUT / "yolo_training.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"{'yolo_training.png':34s} rendered")


def helios_dryrun_vs_llm():
    """Network-average adequacy per turn, synthetic dry run against the LLM pilot.

    The report's own figure exists but is in French and off-palette; this re-renders it
    from the two result files so the poster can stay English and on-brand.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def avg(path):
        by = {}
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                by.setdefault(int(row["tour"]), []).append(float(row["adequation"]))
        return {t: sum(v) / len(v) for t, v in sorted(by.items())}

    base = BST.parents[1] / "projects" / "simu_semiconducteurs" / "analysis"
    dry = avg(base / "resultats.csv")
    llm = avg(base / "llm_pilot_run" / "resultats_pilot.csv")

    periods = [(0.5, 4.5, "P1 Baseline"), (4.5, 8.5, "P2 Tipping point"),
               (8.5, 12.5, "P3 Squeeze"), (12.5, 16.5, "P4 Rupture"),
               (16.5, 18.5, "P5 Recovery")]

    fig, ax = plt.subplots(figsize=(15, 4.0), dpi=180)
    for i, (x1, x2, lab) in enumerate(periods):
        if i % 2 == 0:
            ax.axvspan(x1, x2, color=BG_BLUE, zorder=0)
        ax.text((x1 + x2) / 2, 99, lab, ha="center", va="top", fontsize=12,
                color=CAPTION_GREY)

    t = sorted(dry)
    ax.plot(t, [dry[k] for k in t], color=NAVY_LIGHT, lw=2.4, ls="--", marker="s", ms=5,
            label="Synthetic dry run — $U_d$ anchored on $U_r$ by construction", zorder=3)
    ax.plot(t, [llm[k] for k in t], color=AZURE, lw=3.2, marker="o", ms=6.5,
            label="LLM pilot — eight isolated reasoning agents", zorder=4)

    ax.set_ylabel("Network-average adequacy A", fontsize=13, color=NAVY, labelpad=8)
    ax.set_ylim(35, 102)
    ax.set_xlim(-0.5, 18.5)
    ax.set_xticks(t)
    ax.set_xticklabels([f"T{k}" for k in t], fontsize=11.5)
    ax.set_yticks([40, 50, 60, 70, 80, 90, 100])
    ax.tick_params(labelsize=11.5, colors=NAVY)
    ax.grid(True, ls=":", alpha=.7, color=LINE_GREY)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(NAVY_LIGHT)
    leg = ax.legend(loc="lower right", fontsize=12.5, frameon=True, framealpha=1,
                    edgecolor=LINE_GREY, facecolor="white")
    for x in leg.get_texts():
        x.set_color(NAVY)
    fig.tight_layout()
    fig.savefig(OUT / "helios_dryrun_vs_llm.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"{'helios_dryrun_vs_llm.png':34s} rendered")


def business_metric():
    """Dock-count error, first model vs kept model. Measured with evaluer.py."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    labels = ["median error\non dock count", "images within\n±25 %", "negatives left\ncorrectly empty"]
    first = [62, 22, 89]  # runs/quai   - 86 chips,  50 val images
    kept = [53, 28, 87]  # runs/quai3  - 351 chips, 91 val images
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(6.6, 3.2), dpi=200)
    ax.bar(x - 0.19, first, 0.36, color=LINE_GREY, label="first model · 86 chips", zorder=3)
    ax.bar(x + 0.19, kept, 0.36, color=AZURE, label="kept model · 351 chips", zorder=3)
    for xi, (a, b) in enumerate(zip(first, kept)):
        ax.text(xi - 0.19, a + 2, f"{a} %", ha="center", fontsize=11, color=NAVY)
        ax.text(xi + 0.19, b + 2, f"{b} %", ha="center", fontsize=11.5, color=NAVY,
                fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, color=NAVY)
    ax.set_ylim(0, 105)
    ax.set_yticks([])
    ax.grid(axis="y", ls=":", alpha=0.6, color=LINE_GREY)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(NAVY_LIGHT)
    ax.tick_params(axis="x", length=0)
    leg = ax.legend(loc="upper center", ncol=2, fontsize=10.5, frameon=False,
                    bbox_to_anchor=(0.5, 1.16))
    for t in leg.get_texts():
        t.set_color(NAVY)
    fig.tight_layout()
    fig.savefig(OUT / "yolo_business.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"{'yolo_business.png':34s} rendered")


# logos & brick 1
for name in ("LogoALTEN.png", "LogoESTIA.png", "LogoCranfield.png"):
    copy(BST / "Poster" / "img" / name, name)
for name in ("helios_llm_pilot_adequacy.png", "campaign_network.png", "urgency_gap.png"):
    copy(BST / "Poster" / "img" / name, name)
for name in ("explainability_waterfall.png", "three_layer_architecture.png"):
    trim(BST / "Images" / "2.Problem" / name if name.startswith("three")
         else BST / "Images" / "4.Operations" / name, name)

# brick 2 plates The annotated logic plate: drop the 132 px French legend bar, keep the imagery.
plate(VE / "data/EXPLICATION_aire_manoeuvre.png", "ve_logic.jpg",
      crop=(0, 132, 1150, 932), width=1150)
# Same plate, zoomed on the dock apron: footprint edge, canopy bays, trailers.
plate(VE / "data/EXPLICATION_aire_manoeuvre.png", "ve_logic_zoom.jpg",
      crop=(690, 130, 960, 300), width=1080)

# Docks legible with no truck at all - the two panels that justify segmentation. Cropped tight on the canopy band: the empty yard below carries no information.
plate(VE / "data/PREUVE_aire_visible_sans_camion.png", "ve_proof_deret.jpg",
      crop=(0, 22, 675, 132), width=1000)
plate(VE / "data/PREUVE_aire_visible_sans_camion.png", "ve_proof_clesud.jpg",
      crop=(0, 276, 675, 400), width=1000)

# Inference plates: the 10 px black caption strip goes, the callout is done in HTML.
plate(VE / "test_inedit/9515fccae54f871c.png", "ve_case_ok.jpg",
      crop=(0, 12, 714, 1000), width=760)
plate(VE / "test_inedit/71214df692ced694.png", "ve_case_fp.jpg",
      crop=(0, 12, 1000, 812), width=900)
plate(VE / "zone_toulouse/site_01.png", "ve_zone.jpg",
      crop=(0, 12, 578, 1200), width=620)
# The 221 docks/ha site: BD TOPO split one warehouse, so a 435 m apron landed on a 5 149 m2 fragment. The quality gate caught it - this is the error-analysis plate.
plate(VE / "zone_toulouse/site_02.png", "ve_zone_bad.jpg",
      crop=(0, 12, 744, 1200), width=760)
plate(VE / "runs/quai3/val_batch1_pred.jpg", "ve_val_grid.jpg",
      crop=(0, 0, 1920, 916), width=1400)

# Stratified survey strips: the five categories the training set had to cover.
for tag, src in (("xxl", "survey_XXL-megaDC.png"), ("frigo", "survey_frigo.png"),
                 ("aero", "survey_aerospace.png"), ("retail", "survey_retailDC.png"),
                 ("pme", "survey_small.png")):
    plate(VE / "data" / src, f"ve_survey_{tag}.jpg", width=900)

# Resolution: 8 cm changes nothing an empty dock door would reveal.
plate(VE / "data/thr_cmp_HR20.png", "ve_hr20.jpg", width=520)
plate(VE / "data/thr_cmp_THR8.png", "ve_thr8.jpg", width=520)

# ve_gt_*.jpg and ve_pr_*.jpg are produced by make_pairs.py, not here: the ultralytics validation grids bleed class labels across cell borders, so those plates are redrawn.

# Which KPI blocks feed real urgency, straight from the report.
trim(BST / "Images" / "4.Operations" / "causal_tree_blocks.png", "causal_tree_blocks.png")

# How the twin updates itself, report figures rather than app screenshots: they read at poster distance, the Dash screenshots do not.
trim(BST / "Images" / "4.Operations" / "event_pipeline.png", "ss_pipeline.png")
trim(BST / "Images" / "4.Operations" / "weekly_cycle.png", "ss_cycle.png")
trim(BST / "Images" / "4.Operations" / "urgency_propagation.png", "ss_propagation.png")
trim(BST / "Images" / "4.Operations" / "ahp_criteria_mapping.png", "ss_criteria.png")
trim(BST / "Images" / "4.Operations" / "helios_network_coefficients.png", "ss_network.png")
trim(BST / "Images" / "4.Operations" / "explainability_waterfall.png", "ss_waterfall.png")
plate(BST / "Images/4.Operations/questionnaire_screenshot.png", "ss_ahp.jpg",
      crop=(300, 320, 1180, 912), width=1000)

# Real application screenshots, HELIOS project, from the tutorial walkthrough.
TUTO = Path(r"c:/Users/jhoarau/.gemini/antigravity/brain"
            r"/bb32e20c-e021-4f4c-922e-dd4a580d7cf5/scratch")
if TUTO.exists():
    plate(TUTO / "dashboard.png", "ss_dashboard.jpg", crop=(0, 30, 1624, 700), width=1100)
    plate(TUTO / "questionnaire_loaded.png", "ss_questionnaire.jpg",
          crop=(0, 30, 1624, 840), width=1100)
    plate(TUTO / "graphe.png", "ss_graphe.jpg", crop=(0, 30, 1624, 700), width=1100)
else:
    print(f"{'ss_dashboard.jpg etc.':34s} SKIPPED, {TUTO} not found")

# V4 zone-sweep plates, produced by make_sweep.py. SWEEP points at that run's output folder; the poster reads these four filenames, so a new sweep only overwrites files.
SWEEP = Path(os.environ.get("SWEEP_DIR", Path(__file__).resolve().parent / "sweep"))
_OV = Path(__file__).resolve().parent / "samyolo" / "samyolo_overview.jpg"
if not _OV.exists():
    _OV = SWEEP / "sweep_overview.jpg"  # footprint-only fallback
if _OV.exists():
    # No side crop: the caption band starts at the left edge, so trimming there would eat the first words of it.
    plate(_OV, "ve_sweep.jpg", width=1500)
else:
    print(f"{'ve_sweep.jpg':34s} SKIPPED, no overview plate found")

# The three per-site plates come from make_sam_yolo.py: SAM3 roof, then shape and area, then the YOLO aprons, all on one frame. Their burnt-in panel is cropped off because at poster width its type would fall under 2 mm; the figcaptions carry the numbers instead.
SY = Path(__file__).resolve().parent / "samyolo"
for tag in ("best", "mid", "flop"):
    p = SY / f"samyolo_{tag}.jpg"
    if p.exists():
        im = Image.open(p)
        h_img = int(im.height * 0.866)  # imagery, panel dropped
        cx, cy = im.width / 2, h_img / 2  # the site sits at the centre by construction
        half = 0.30 * im.width  # zoom in so the building fills the cell
        plate(p, f"ve_case_{tag}.jpg", width=820,
              crop=(int(cx - half), int(cy - half), int(cx + half), int(cy + half)))
    else:
        print(f"{'ve_case_' + tag + '.jpg':34s} SKIPPED, {p} not found")

training_curve()
business_metric()
helios_dryrun_vs_llm()
print(f"\n-> {OUT}")
