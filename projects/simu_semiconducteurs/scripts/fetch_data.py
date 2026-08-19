"""Acquisition des series publiques de la campagne HELIOS (U2-U4).

Telecharge les series INSEE (API BDM, SDMX-ML, sans authentification) et les
ecrit en CSV bruts sous ``data/raw/``, avec un MANIFEST.md de provenance.
Le rapport WSTS (xls) est telecharge si l'URL directe repond ; sinon le
MANIFEST consigne l'etape manuelle.

Usage :
    python fetch_data.py [--out DIR]

Fenetre de campagne : 2020-09 -> 2022-02 (+ marge baseline 2020-07/08).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_BDM = "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/{idbank}"

#: Series INSEE de la campagne : idbank -> (slug, description, granularite).
INSEE_SERIES: dict[str, tuple[str, str, str]] = {
    "010768009": (
        "insee_ipi_naf261",
        "Indice brut de la production industrielle (base 100 en 2021) — "
        "Fabrication de composants et cartes électroniques (NAF 26.1)",
        "mensuelle",
    ),
    "001656157": (
        "insee_defaillances_ensemble",
        "Défaillances d'entreprises — ensemble (données CVS)",
        "trimestrielle",
    ),
    "001656101": (
        "insee_defaillances_industrie",
        "Défaillances d'entreprises — industrie",
        "mensuelle",
    ),
    "010764313": (
        "insee_ipp_industrie",
        "Indice de prix de production de l'industrie française — ensemble",
        "mensuelle",
    ),
    "001586738": (
        "insee_tuc_manuf",
        "Taux d'utilisation des capacités de production — industrie manufacturière",
        "trimestrielle",
    ),
    "010764217": (
        "insee_ipp_composants",
        "Indice de prix de production — CPF 26.1 composants et cartes "
        "électroniques (marché français)",
        "mensuelle",
    ),
}

#: Fenetre utile (bornes incluses, format AAAA-MM).
WINDOW_START = "2020-07"
WINDOW_END = "2022-02"

WSTS_PAGE = "https://www.wsts.org/67/Historical-Billings-Report"


def _fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "supplyscore-helios/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_insee_series(idbank: str) -> list[tuple[str, float]]:
    """Telecharge une serie BDM et renvoie [(periode, valeur)] trie croissant."""
    raw = _fetch(BASE_BDM.format(idbank=idbank))
    root = ET.fromstring(raw)
    obs: list[tuple[str, float]] = []
    for el in root.iter():
        if el.tag.endswith("Obs"):
            period = el.attrib.get("TIME_PERIOD")
            value = el.attrib.get("OBS_VALUE")
            if period and value not in (None, "", "NaN"):
                try:
                    obs.append((period, float(value)))
                except ValueError:
                    continue
    obs.sort(key=lambda t: t[0])
    return obs


def in_window(period: str) -> bool:
    """Vrai si la periode (AAAA-MM ou AAAA-QN) touche la fenetre de campagne."""
    if re.fullmatch(r"\d{4}-Q\d", period):
        year, q = int(period[:4]), int(period[-1])
        month = 3 * q - 2  # premier mois du trimestre
        period = f"{year:04d}-{month:02d}"
    return WINDOW_START <= period <= WINDOW_END


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "data" / "raw"),
        help="Dossier de sortie des CSV bruts",
    )
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    failures: list[str] = []

    for idbank, (slug, desc, gran) in INSEE_SERIES.items():
        try:
            obs = fetch_insee_series(idbank)
        except Exception as exc:  # noqa: BLE001 - on consigne et on continue
            failures.append(f"{slug} ({idbank}) : {type(exc).__name__}: {exc}")
            continue
        window = [o for o in obs if in_window(o[0])]
        path = out / f"{slug}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["periode", "valeur"])
            writer.writerows(obs)
        manifest.append(
            {
                "slug": slug,
                "idbank": idbank,
                "description": desc,
                "granularite": gran,
                "url": BASE_BDM.format(idbank=idbank),
                "points_total": len(obs),
                "points_fenetre": len(window),
                "premiere": obs[0][0] if obs else "-",
                "derniere": obs[-1][0] if obs else "-",
                "sha256": sha256(path),
                "statut": (
                    "OK" if len(window) >= (5 if gran == "trimestrielle" else 18)
                    else "COUVERTURE INSUFFISANTE"
                ),
            }
        )
        print(f"[ok] {slug}: {len(obs)} points, {len(window)} dans la fenêtre")

    # WSTS : tentative de decouverte du lien xls sur la page publique
    wsts_note = "Téléchargement manuel requis (page consultée)."
    try:
        page = _fetch(WSTS_PAGE).decode("utf-8", errors="ignore")
        links = re.findall(r'href="([^"]+\.xlsx?)"', page, flags=re.I)
        if links:
            url = links[0]
            if url.startswith("/"):
                url = "https://www.wsts.org" + url
            data = _fetch(url, timeout=60)
            ext = ".xlsx" if url.lower().endswith("xlsx") else ".xls"
            wsts_path = out / f"wsts_historical_billings{ext}"
            wsts_path.write_bytes(data)
            wsts_note = f"Téléchargé automatiquement depuis {url} (sha256 {sha256(wsts_path)[:16]}…)."
            print(f"[ok] WSTS: {wsts_path.name} ({len(data)} octets)")
        else:
            print("[!] WSTS: aucun lien xls détecté sur la page — étape manuelle.")
    except Exception as exc:  # noqa: BLE001
        wsts_note = f"Échec automatique ({type(exc).__name__}) — étape manuelle."
        print(f"[!] WSTS: {exc}")

    # MANIFEST
    lines = [
        "# MANIFEST des données brutes — campagne HÉLIOS",
        "",
        f"Généré par fetch_data.py le {dt.date.today().isoformat()}. "
        f"Fenêtre de campagne : {WINDOW_START} -> {WINDOW_END}.",
        "",
        "## Séries INSEE (API BDM, licence ouverte Etalab)",
        "",
        "| Slug | idbank | Description | Granularité | Points fenêtre | Première | Dernière | Statut | SHA256 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in manifest:
        lines.append(
            f"| {m['slug']} | {m['idbank']} | {m['description'][:60]}… | "
            f"{m['granularite']} | {m['points_fenetre']} | {m['premiere']} | "
            f"{m['derniere']} | {m['statut']} | {m['sha256'][:16]}… |"
        )
    lines += [
        "",
        "## WSTS Historical Billings Report",
        "",
        f"- Page : {WSTS_PAGE}",
        f"- Statut : {wsts_note}",
        "",
        "## Datasets Kaggle (déposés manuellement — verdicts du contrôle HD5)",
        "",
        "1. **`Semiconductor shortage affects.csv`** (semiconductor-shortages19852021) —",
        "   **AUTHENTIQUE, UTILISÉ.** Séries mensuelles US de type FRED/BLS (PPI",
        "   semi-conducteurs, indices export/import, emploi sectoriel), 1985-01 ->",
        "   2021-11. Signatures de réalité : déclin séculaire du PPI (100.5 -> 55.3),",
        "   inflexion HAUSSIÈRE en 2021 (l'anomalie documentée de la crise), emploi",
        "   cohérent avec les séries officielles. Usage : contexte coût de novafab",
        "   (cost.op_cost normalisé baseline juil-août 2020). Limite : série arrêtée",
        "   nov. 2021 -> T16-T18 sans écriture (dernière valeur persiste)."
        + (f" SHA256 : {sha256(out / 'Semiconductor shortage affects.csv')[:16]}…"
           if (out / "Semiconductor shortage affects.csv").exists() else " (absent)"),
        "2. **`dynamic_supply_chain_logistics_dataset.csv`** (logistics-and-supply-chain-",
        "   dataset) — **ÉCARTÉ (HD5).** Marqueurs de données synthétiques générées pour",
        "   l'entraînement ML : colonnes cibles pré-calculées (delay_probability,",
        "   risk_classification, disruption_likelihood_score), coordonnées GPS",
        "   éparpillées sur tout le territoire US alors que la description annonce la",
        "   Californie du Sud, distributions uniformément moyennes. Conservé dans raw/",
        "   pour trace, jamais chargé par le pipeline. TransGlobal reste piloté par",
        "   les événements calibrés, comme prévu au plan.",
        "",
        "## Séries écartées / non trouvées (documenté, jamais inventé)",
        "",
        "- Dataset logistique Kaggle : écarté (synthétique, voir section Kaggle).",
        "- Indice de fret public couvrant 2020-2022 sans licence : non identifié à ce",
        "  stade -> le bloc cost de TransGlobal reste piloté par les événements",
        "  calibrés (surcoûts documentés) + IPP industrie en contexte.",
        "- Série silicium/polysilicium publique : non identifiée en accès libre ->",
        "  bloc cost de SilPure piloté par l'événement hausse_tarif (T16, +18 %",
        "  documenté) et l'IPP en contexte.",
        "- env_exposure / political_risk : valeurs U5bis posées depuis WorldRiskIndex",
        "  2021 et WGI (constantes gelées, sensibilité ±50 % en U10) — pas de série",
        "  temporelle nécessaire (baseline lente).",
    ]
    if failures:
        lines += ["", "## Échecs de téléchargement", ""]
        lines += [f"- {f}" for f in failures]
    (out / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nMANIFEST écrit : {out / 'MANIFEST.md'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
