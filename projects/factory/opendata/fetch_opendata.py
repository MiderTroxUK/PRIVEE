"""Ingestion des séries data.gouv.fr épinglées (U13, plan HÉLIOS v7).

Contrairement à ``projects/simu_semiconducteurs/scripts/fetch_data.py`` (API
INSEE BDM directe, propre à la campagne close), ce module cible le catalogue
public **data.gouv.fr** (``https://www.data.gouv.fr/api/1/``) : chaque série
de ``MANIFEST.md`` fixe un dataset ID, une resource URL de téléchargement
direct et un sha256 constatés à une date donnée. Le serveur MCP data.gouv
(``https://mcp.data.gouv.fr/mcp``) est un outil de découverte interactive
utilisé en session par un humain ; il n'intervient jamais ici — ce script ne
fait que retélécharger et revérifier des ressources déjà épinglées.

Règle de gel (même discipline que ``HASHES.sha256`` de la campagne HÉLIOS) :
un sha256 qui ne correspond plus au MANIFEST est un échec dur, jamais une
mise à jour silencieuse. Une source dont le contenu a changé doit être
ré-examinée par un humain et ré-épinglée consciemment dans MANIFEST.md.

Produit, sous ``--out`` (défaut : ce dossier) :
    - ``raw/<serie>.<ext>``      fichier brut tel que téléchargé (zip ou csv) ;
    - ``prepared/<serie>.csv``   colonnes (semaine_iso, valeur, valeur_rebasee),
                                  séries mensuelles étalées (forward fill) sur
                                  les semaines ISO, rebasées min-max sur
                                  l'étendue publiée (même règle que le
                                  protocole HÉLIOS §6 pour WRI/WGI).

Usage :
    python fetch_opendata.py --serie insee_ipch_ensemble
    python fetch_opendata.py --all [--out projects/factory/opendata/]
    python fetch_opendata.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
MANIFEST_PATH = _HERE / "MANIFEST.md"

_SEPARATOR_RE = re.compile(r"^:?-+:?$")


class FreezeViolationError(RuntimeError):
    """Le sha256 d'une ressource téléchargée ne correspond plus au MANIFEST figé."""


# --------------------------------------------------------------------------
# Lecture résiliente du MANIFEST (table markdown « nom de série | ... »).
# --------------------------------------------------------------------------


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_RE.match(c) for c in cells)


def _unbacktick(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def parse_manifest(path: Path) -> list[dict[str, str]]:
    """Extrait la table des séries épinglées du MANIFEST.

    Repère, parmi toutes les tables markdown du fichier, celle dont l'en-tête
    contient à la fois « sha256 » et « resource url » (insensible à la
    casse) : c'est la table de gel, indépendamment de sa position et des
    autres tables informatives (ex. tailles de fichiers) qui peuvent
    l'entourer. Ignore les lignes de séparation ``|---|---|``.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, str]] = []
    header: list[str] | None = None
    in_target_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_target_table = False
            header = None
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if _is_separator_row(cells):
            continue
        if header is None:
            lowered = [c.lower() for c in cells]
            if any("sha256" in c for c in lowered) and any("resource url" in c for c in lowered):
                header = lowered
                in_target_table = True
            continue
        if not in_target_table or len(cells) != len(header):
            continue
        row = dict(zip(header, cells, strict=True))
        entries.append(
            {
                "nom": _unbacktick(row.get("nom de série", "")),
                "dataset_id": _unbacktick(row.get("dataset id data.gouv épinglé", "")),
                "resource_url": row.get("resource url", ""),
                "licence": row.get("licence", ""),
                "sha256": _unbacktick(row.get("sha256", "")),
                "usage": row.get("usage prévu", ""),
            }
        )
    return entries


# --------------------------------------------------------------------------
# Téléchargement + vérification.
# --------------------------------------------------------------------------


def _download(url: str, timeout: int = 30) -> bytes:
    """Télécharge une URL épinglée du MANIFEST (délai explicite, en octets bruts)."""
    req = urllib.request.Request(url, headers={"User-Agent": "supplyscore-opendata/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sha256_bytes(data: bytes) -> str:
    """Empreinte SHA256 hexadécimale d'un contenu binaire."""
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Analyseurs par série (schéma propre à chaque source, comme prepare_data.py).
# --------------------------------------------------------------------------


def _parse_insee_ipch_ensemble(raw: bytes) -> dict[str, float]:
    """DS_IPCH (Melodi INSEE, zip) : ensemble France, tous postes, mensuel.

    Filtre IDX_TYPE=HICP, IND_TYPE=IX, COICOP_2018=00 (tous postes), FREQ=M.
    """
    out: dict[str, float] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = next(n for n in zf.namelist() if n.endswith("_data.csv"))
        with zf.open(name) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"), delimiter=";")
            for row in reader:
                if (
                    row.get("IDX_TYPE") == "HICP"
                    and row.get("IND_TYPE") == "IX"
                    and row.get("COICOP_2018") == "00"
                    and row.get("FREQ") == "M"
                ):
                    period, value = row.get("TIME_PERIOD"), row.get("OBS_VALUE")
                    if period and value:
                        out[period] = float(value)
    return out


def _parse_sdes_prix_elec_industrie(raw: bytes) -> dict[str, float]:
    """SDES « Conjoncture mensuelle de l'énergie » — prix industriels électricité."""
    out: dict[str, float] = {}
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter=";")
    for row in reader:
        period = row.get("PERIODE")
        value = row.get("PX_ELE_I_TTES_TRANCHES")
        if period and value:
            out[period] = float(value)
    return out


def _parse_sdes_conso_elec_france(raw: bytes) -> dict[str, float]:
    """SDES « Conjoncture mensuelle de l'énergie » — synthèse électricité (conso)."""
    out: dict[str, float] = {}
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter=";")
    for row in reader:
        period = row.get("PERIODE")
        value = row.get("CONSO_ELE_SYNT")
        if period and value:
            out[period] = float(value)
    return out


SERIES_PARSERS = {
    "insee_ipch_ensemble": _parse_insee_ipch_ensemble,
    "sdes_prix_elec_industrie": _parse_sdes_prix_elec_industrie,
    "sdes_conso_elec_france": _parse_sdes_conso_elec_france,
}


# --------------------------------------------------------------------------
# Normalisation mensuel -> hebdomadaire (forward fill) + rebasage min-max.
# --------------------------------------------------------------------------


def _thursday_weeks_of_month(year: int, month: int) -> list[str]:
    """Semaines ISO (AAAA-Wnn) dont le jeudi tombe dans le mois AAAA-MM.

    Règle ISO 8601 : une semaine appartient à l'année (et, par extension ici,
    au mois) de son jeudi. Chaque semaine n'a qu'un seul jeudi : aucun mois
    ne se recouvre, et une série mensuelle continue ne laisse aucune semaine
    orpheline.
    """
    first = dt.date(year, month, 1)
    next_month = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    weeks: list[str] = []
    day = first
    while day < next_month:
        if day.weekday() == 3:  # jeudi
            iso_year, iso_week, _ = day.isocalendar()
            weeks.append(f"{iso_year:04d}-W{iso_week:02d}")
        day += dt.timedelta(days=1)
    return weeks


def forward_fill_weekly(monthly: dict[str, float]) -> list[tuple[str, float]]:
    """Étale une série mensuelle (clé « AAAA-MM ») sur les semaines ISO.

    Chaque valeur mensuelle est recopiée (forward fill) sur toutes les
    semaines ISO dont le jeudi tombe dans ce mois. Un mois absent de la
    source n'est jamais comblé par invention : il est simplement absent en
    sortie (pas de « saut » de la dernière valeur au-delà de son propre
    mois) — même éthique que le reste du pipeline HÉLIOS.
    """
    out: list[tuple[str, float]] = []
    for period in sorted(monthly):
        year_s, month_s = period.split("-")
        value = monthly[period]
        out.extend((week, value) for week in _thursday_weeks_of_month(int(year_s), int(month_s)))
    out.sort(key=lambda t: t[0])
    return out


def rebase_min_max(rows: list[tuple[str, float]]) -> list[tuple[str, float, float]]:
    """Rebase min-max sur toute l'étendue publiée -> valeur_rebasee dans [0,1].

    Même règle que le protocole HÉLIOS §6 pour les indices WRI/WGI : un
    indice brut peut saturer un usage probabiliste en aval, on rebase donc
    sur [min, max] réellement observés dans la série téléchargée (jamais sur
    des bornes théoriques inventées).
    """
    values = [v for _, v in rows]
    lo, hi = min(values), max(values)
    span = hi - lo
    return [
        (period, value, 0.5 if span == 0 else round((value - lo) / span, 6))
        for period, value in rows
    ]


def normalize_series(nom: str, raw: bytes) -> list[tuple[str, float, float]]:
    """Applique l'analyseur de la série puis le pipeline forward fill + rebasage."""
    parser = SERIES_PARSERS.get(nom)
    if parser is None:
        raise ValueError(f"Aucun analyseur connu pour la série « {nom} » (voir SERIES_PARSERS).")
    monthly = parser(raw)
    if not monthly:
        raise ValueError(
            f"{nom} : aucune observation extraite du fichier brut (filtre trop strict ?)."
        )
    return rebase_min_max(forward_fill_weekly(monthly))


# --------------------------------------------------------------------------
# Orchestration CLI.
# --------------------------------------------------------------------------


def _write_prepared(nom: str, rows: list[tuple[str, float, float]], prepared_dir: Path) -> Path:
    prepared_dir.mkdir(parents=True, exist_ok=True)
    path = prepared_dir / f"{nom}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["semaine_iso", "valeur", "valeur_rebasee"])
        writer.writerows(rows)
    return path


def fetch_one(entry: dict[str, str], out: Path) -> None:
    """Télécharge une série épinglée, vérifie son sha256 puis écrit raw/ et prepared/.

    Échec dur (``FreezeViolationError``) sur toute divergence de sha256 —
    rien n'est écrit dans ce cas, ``raw/`` garde son dernier état vérifié.
    """
    nom = entry["nom"]
    raw_dir, prepared_dir = out / "raw", out / "prepared"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"[..] {nom} : téléchargement depuis {entry['resource_url']}")
    data = _download(entry["resource_url"])
    digest = sha256_bytes(data)
    attendu = entry["sha256"]
    if digest != attendu:
        raise FreezeViolationError(
            f"{nom} : le SHA256 téléchargé ({digest}) ne correspond pas au "
            f"MANIFEST figé ({attendu}). Règle de gel : une ressource épinglée "
            "dont le contenu a changé doit être examinée par un humain et "
            "ré-épinglée consciemment (sha256 mis à jour dans MANIFEST.md) — "
            "jamais acceptée silencieusement, même discipline que "
            "data/prepared/HASHES.sha256 de la campagne HÉLIOS. "
            "Téléchargement rejeté, rien n'a été écrit."
        )

    ext = ".zip" if zipfile.is_zipfile(io.BytesIO(data)) else ".csv"
    raw_path = raw_dir / f"{nom}{ext}"
    for stale in raw_dir.glob(f"{nom}.*"):  # nettoie une extension d'un gel antérieur
        if stale != raw_path:
            stale.unlink()
    raw_path.write_bytes(data)
    print(f"[ok] {nom} : sha256 vérifié ({digest[:16]}…), {len(data)} octets -> {raw_path}")

    rows = normalize_series(nom, data)
    prepared_path = _write_prepared(nom, rows, prepared_dir)
    print(f"[ok] {nom} : {len(rows)} semaines écrites -> {prepared_path}")


def _selftest(entries: list[dict[str, str]], out: Path) -> int:
    """Revérifie les sha256 des fichiers déjà présents sous raw/, sans réseau."""
    raw_dir = out / "raw"
    problems = 0
    for entry in entries:
        nom, attendu = entry["nom"], entry["sha256"]
        candidates = sorted(raw_dir.glob(f"{nom}.*"))
        if not candidates:
            print(f"[!] {nom} : absent de {raw_dir} (lancer --serie {nom} pour le télécharger).")
            problems += 1
            continue
        path = candidates[0]
        digest = sha256_bytes(path.read_bytes())
        if digest == attendu:
            print(f"[ok] {nom} : sha256 conforme au MANIFEST ({path.name}).")
        else:
            print(
                f"[!] {nom} : sha256 NON conforme ({path.name}) — "
                f"attendu {attendu}, obtenu {digest}."
            )
            problems += 1
    total = len(entries)
    print(f"\n--selftest : {total - problems}/{total} conformes.")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI : ``--serie NAME``, ``--all`` ou ``--selftest``."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--serie", metavar="NAME", help="Nom de la série à traiter (voir MANIFEST.md)"
    )
    mode.add_argument(
        "--all", action="store_true", help="Traite toutes les séries épinglées du MANIFEST"
    )
    mode.add_argument(
        "--selftest",
        action="store_true",
        help="Revérifie hors ligne les sha256 des fichiers déjà présents sous raw/",
    )
    parser.add_argument(
        "--out",
        default=str(_HERE),
        help="Dossier contenant raw/ et prepared/ (défaut : projects/factory/opendata/)",
    )
    args = parser.parse_args(argv)
    out = Path(args.out)

    entries = parse_manifest(MANIFEST_PATH)
    if not entries:
        print(
            f"[!] {MANIFEST_PATH} : aucune série épinglée trouvée (table de gel introuvable).",
            file=sys.stderr,
        )
        return 1

    if args.selftest:
        return _selftest(entries, out)

    if args.serie:
        selected = [e for e in entries if e["nom"] == args.serie]
        if not selected:
            noms = ", ".join(e["nom"] for e in entries)
            print(
                f"[!] Série inconnue : « {args.serie} ». Séries épinglées : {noms}",
                file=sys.stderr,
            )
            return 1
    else:
        selected = entries

    failures = 0
    for entry in selected:
        try:
            fetch_one(entry, out)
        except FreezeViolationError as exc:
            print(f"[!] {exc}", file=sys.stderr)
            failures += 1
        except Exception as exc:  # on consigne et on continue les autres séries du lot
            print(f"[!] {entry['nom']} : {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
