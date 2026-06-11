"""Export complet des données d'un projet — classeur Excel ou archive CSV (E7, Lot 7.1).

:class:`ExportService` agrège TOUT le matériau d'un projet pour l'analyse
post-serious-game : la fiche projet, les nœuds (état d'urgence courant et tags
inclus), les arcs, les jalons, puis — agrégées sur l'ensemble des nœuds du
projet, avec une colonne « nœud » — les séries des bases CLIENT : historique
d'urgences, évaluations AHP, snapshots KPI (colonnes aplaties « bloc.champ »),
événements, décisions, revues hebdomadaires et journal d'audit. Le journal
d'audit du REGISTRE (global, non filtré par projet) part dans une feuille
« audit_registre » séparée.

Deux formats :

- ``fmt="xlsx"`` : UN classeur ``openpyxl`` multi-feuilles ;
- ``fmt="csv"`` : un ZIP contenant un CSV par feuille — encodage ``utf-8-sig``
  (BOM) et séparateur « ; », les conventions d'Excel FR.

Les dates epoch sont rendues « JJ/MM/AAAA HH:MM » en heure locale. Le nom du
fichier embarque le nom du projet slugifié (alphanumérique et tirets, accents
translittérés) et l'horodatage de l'horloge du service :
``SupplyScore_<slug>_AAAAMMJJ_HHMMSS.xlsx|.zip``.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import re
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from openpyxl import Workbook  # type: ignore[import-untyped]

from supplyscore.core.clock import iso_week
from supplyscore.data.db import kpis_from_json
from supplyscore.domain.models import KPIBundle, Project, SupplyNode

if TYPE_CHECKING:
    from supplyscore.data.db import ClientDatabase
    from supplyscore.services.orchestrator import SupplyScoreService

#: Une feuille d'export : ``(nom, en-têtes, lignes)``.
_Sheet = tuple[str, list[str], list[list[Any]]]

#: Évaluations AHP d'un nœud, avec l'id de l'évaluation qui les remplace (NULL sinon).
_SQL_EVALUATIONS = """
    SELECT a.operator_id, a.iso_week, a.ud, a.consistency_ratio,
           a.is_consistent, a.notes,
           (SELECT MIN(b.id) FROM assessments b WHERE b.replaces_id = a.id) AS remplacee_par
    FROM assessments a
    WHERE a.node_id = ?
    ORDER BY a.timestamp, a.id
"""

#: Snapshots KPI d'un nœud, chronologiques.
_SQL_SNAPSHOTS = """
    SELECT kpis_json, timestamp FROM kpi_snapshots
    WHERE node_id = ?
    ORDER BY timestamp, id
"""

#: Revues hebdomadaires d'un nœud, par semaine ISO croissante.
_SQL_REVUES = """
    SELECT iso_week, volets_json, started_at, completed_at
    FROM weekly_reviews
    WHERE node_id = ?
    ORDER BY iso_week
"""

#: Journal d'audit complet d'une base (client ou registre), chronologique.
_SQL_AUDIT = """
    SELECT entity_type, entity_id, field, old_value, new_value,
           source, operator_id, iso_week, timestamp
    FROM audit_log
    ORDER BY timestamp, id
"""

#: En-têtes du journal d'audit (sans la colonne « nœud », propre aux bases client).
_AUDIT_HEADERS = [
    "type entité",
    "id entité",
    "champ",
    "avant",
    "après",
    "source",
    "opérateur",
    "semaine",
    "date",
]


def _slugify(name: str) -> str:
    """Slugifie un nom de projet pour un nom de fichier sûr.

    Les accents sont translittérés (décomposition NFKD puis encodage ASCII,
    les diacritiques tombent), tout caractère non alphanumérique devient un
    tiret et les tirets de bord sont retirés.

    Args:
        name: nom libre du projet (accents, espaces, « / »... tolérés).

    Returns:
        Le slug « alphanumérique + tirets » correspondant, ``"projet"`` si le
        nom ne contient aucun caractère translittérable.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-")
    return slug or "projet"


def _fmt_date(ts: float | None) -> str:
    """Formate un epoch en « JJ/MM/AAAA HH:MM » (heure locale), ``""`` si None.

    Args:
        ts: instant en secondes epoch, ou ``None``.

    Returns:
        La date formatée en heure locale, ou la chaîne vide.
    """
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def _kpi_columns() -> list[str]:
    """Colonnes aplaties « bloc.champ » d'un :class:`KPIBundle`, ordre de déclaration.

    Returns:
        Les chemins qualifiés de tous les champs déclarés des blocs KPI
        (``network.product``, ``risk.failure_probability``...), dans l'ordre
        des dataclasses.
    """
    bundle = KPIBundle()
    columns: list[str] = []
    for block_field in dataclasses.fields(KPIBundle):
        block = getattr(bundle, block_field.name)
        columns.extend(f"{block_field.name}.{f.name}" for f in dataclasses.fields(block))
    return columns


def _kpi_values(kpis: KPIBundle, columns: list[str]) -> list[Any]:
    """Valeurs d'un bundle KPI dans l'ordre des colonnes aplaties.

    Args:
        kpis: bundle à aplatir.
        columns: chemins qualifiés « bloc.champ » (cf. :func:`_kpi_columns`).

    Returns:
        Les valeurs (``None`` pour un KPI non renseigné), alignées sur
        ``columns``.
    """
    values: list[Any] = []
    for path in columns:
        block_name, _, field_name = path.partition(".")
        values.append(getattr(getattr(kpis, block_name), field_name))
    return values


def _resume_impacts(impacts: list[dict[str, Any]]) -> str:
    """Résumé lisible des impacts d'un événement : « bloc.champ: avant → après ».

    Args:
        impacts: impacts désérialisés de ``events.impacts_json``.

    Returns:
        Les impacts joints par « ; », chaîne vide si l'événement n'en a aucun.
    """
    return "; ".join(
        f"{impact['kpi_path']}: {impact['old']} → {impact['new']}" for impact in impacts
    )


def _write_xlsx(sheets: list[_Sheet], path: Path) -> None:
    """Écrit les feuilles dans UN classeur openpyxl (en-têtes en ligne 1).

    Args:
        sheets: feuilles ``(nom, en-têtes, lignes)`` dans l'ordre du classeur.
        path: chemin du fichier ``.xlsx`` à produire.
    """
    workbook = Workbook()
    default_sheet = workbook.active
    if default_sheet is not None:
        workbook.remove(default_sheet)
    for name, headers, rows in sheets:
        sheet = workbook.create_sheet(title=name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    workbook.save(path)


def _write_csv_zip(sheets: list[_Sheet], path: Path) -> None:
    """Écrit les feuilles dans un ZIP d'un CSV par feuille (Excel FR).

    Chaque ``<nom>.csv`` est encodé en ``utf-8-sig`` (BOM) avec « ; » comme
    séparateur ; les valeurs ``None`` deviennent des cellules vides.

    Args:
        sheets: feuilles ``(nom, en-têtes, lignes)``.
        path: chemin de l'archive ``.zip`` à produire.
    """
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, headers, rows in sheets:
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
            writer.writerow(headers)
            for row in rows:
                writer.writerow(["" if value is None else value for value in row])
            archive.writestr(f"{name}.csv", buffer.getvalue().encode("utf-8-sig"))


class ExportService:
    """Export des données complètes d'un projet (classeur xlsx ou ZIP de CSV).

    S'appuie sur la façade :class:`SupplyScoreService` : le registre fournit le
    projet, ses nœuds, arcs, jalons et tags ; chaque base CLIENT fournit les
    séries hebdomadaires de son nœud. Lecture seule — l'export n'écrit rien
    dans les bases.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service d'export au-dessus de la façade.

        Args:
            service: façade applicative (registre, bases client, horloge).
        """
        self._service = service

    # --- API publique -------------------------------------------------------------

    def export_project(
        self,
        project_id: str,
        fmt: Literal["csv", "xlsx"] = "xlsx",
        dest_dir: Path | str = "exports",
    ) -> Path:
        """Exporte toutes les données du projet dans ``dest_dir`` (créé au besoin).

        Produit ``SupplyScore_<slug>_AAAAMMJJ_HHMMSS.xlsx`` (un classeur
        multi-feuilles) ou ``....zip`` (un CSV par feuille, utf-8-sig, « ; »),
        l'horodatage venant de l'horloge du service en heure locale. Feuilles,
        dans l'ordre : ``projet``, ``noeuds``, ``arcs``, ``jalons``,
        ``historique_urgences``, ``evaluations``, ``snapshots_kpi``,
        ``evenements``, ``decisions``, ``revues_hebdo``, ``audit`` (bases
        CLIENT, colonne « nœud ») et ``audit_registre`` (journal global du
        registre).

        Args:
            project_id: identifiant du projet à exporter.
            fmt: ``"xlsx"`` (défaut) ou ``"csv"``.
            dest_dir: répertoire de destination, créé s'il n'existe pas.

        Returns:
            Le chemin du fichier produit.

        Raises:
            ValueError: si le projet est inconnu du registre, ou si ``fmt``
                n'est ni ``"csv"`` ni ``"xlsx"``.
        """
        project = self._service.registry.get_project(project_id)
        if project is None:
            raise ValueError(f"projet inconnu du registre : {project_id!r}")
        if fmt not in ("csv", "xlsx"):
            raise ValueError(f"format d'export inconnu : {fmt!r} (attendu 'csv' ou 'xlsx')")

        sheets = self._build_sheets(project)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(self._service.clock.now()).strftime("%Y%m%d_%H%M%S")
        stem = f"SupplyScore_{_slugify(project.name)}_{stamp}"
        if fmt == "xlsx":
            path = dest / f"{stem}.xlsx"
            _write_xlsx(sheets, path)
        else:
            path = dest / f"{stem}.zip"
            _write_csv_zip(sheets, path)
        return path

    # --- Construction des feuilles --------------------------------------------------

    def _build_sheets(self, project: Project) -> list[_Sheet]:
        """Construit toutes les feuilles de l'export, dans l'ordre du classeur.

        Args:
            project: projet à exporter (déjà validé).

        Returns:
            Les feuilles ``(nom, en-têtes, lignes)``.
        """
        nodes = self._service.registry.list_nodes(project.id)
        sheets: list[_Sheet] = [
            self._sheet_projet(project),
            self._sheet_noeuds(nodes),
            self._sheet_arcs(nodes),
            self._sheet_jalons(nodes),
        ]
        sheets.extend(self._sheets_clients(nodes))
        sheets.append(self._sheet_audit_registre())
        return sheets

    def _sheet_projet(self, project: Project) -> _Sheet:
        """Feuille « projet » : la fiche d'identité du projet (une ligne).

        Args:
            project: projet exporté.

        Returns:
            La feuille ``projet``.
        """
        headers = ["id", "nom", "description", "t0", "créé le", "mode horloge"]
        row = [
            project.id,
            project.name,
            project.description,
            _fmt_date(project.origin_ts),
            _fmt_date(project.created_at),
            self._service.clock_mode(project.id),
        ]
        return ("projet", headers, [row])

    def _sheet_noeuds(self, nodes: list[SupplyNode]) -> _Sheet:
        """Feuille « noeuds » : identité, tags et état d'urgence courant par nœud.

        Args:
            nodes: nœuds du projet (ordre registre : rang puis id).

        Returns:
            La feuille ``noeuds``.
        """
        headers = [
            "id",
            "nom",
            "label",
            "rang",
            "statut",
            "complétude onboarding",
            "tags",
            "localisation",
            "ud_local",
            "ur_local",
            "ud",
            "ur",
            "adequation",
            "false_urgency",
            "hidden_risk",
        ]
        rows: list[list[Any]] = []
        for node in nodes:
            tags = self._service.registry.tags_of_node(node.id)
            urgency = node.urgency
            rows.append(
                [
                    node.id,
                    node.name,
                    node.label,
                    node.rank,
                    str(node.status),
                    node.onboarding_state,
                    ", ".join(tag.name for tag in tags),
                    node.location,
                    urgency.ud_local,
                    urgency.ur_local,
                    urgency.ud,
                    urgency.ur,
                    urgency.adequation,
                    urgency.false_urgency,
                    urgency.hidden_risk,
                ]
            )
        return ("noeuds", headers, rows)

    def _sheet_arcs(self, nodes: list[SupplyNode]) -> _Sheet:
        """Feuille « arcs » : les arcs dont les DEUX extrémités sont dans le projet.

        Args:
            nodes: nœuds du projet (résolution des noms).

        Returns:
            La feuille ``arcs``.
        """
        names = {node.id: node.name for node in nodes}
        headers = ["source", "cible", "nature", "gamma", "beta", "delta"]
        rows = [
            [
                names[arc.source_id],
                names[arc.target_id],
                str(arc.kind_arc),
                arc.gamma,
                arc.beta,
                arc.delta,
            ]
            for arc in self._service.registry.list_arcs()
            if arc.source_id in names and arc.target_id in names
        ]
        return ("arcs", headers, rows)

    def _sheet_jalons(self, nodes: list[SupplyNode]) -> _Sheet:
        """Feuille « jalons » : tous les jalons des nœuds du projet.

        Args:
            nodes: nœuds du projet.

        Returns:
            La feuille ``jalons``.
        """
        headers = ["nœud", "nom", "type", "début", "échéance", "statut", "avancement"]
        rows: list[list[Any]] = []
        for node in nodes:
            for milestone in self._service.registry.list_milestones(node.id):
                rows.append(
                    [
                        node.name,
                        milestone.name,
                        milestone.kind,
                        _fmt_date(milestone.start_ts),
                        _fmt_date(milestone.deadline_ts),
                        str(milestone.status),
                        milestone.progress,
                    ]
                )
        return ("jalons", headers, rows)

    def _sheets_clients(self, nodes: list[SupplyNode]) -> list[_Sheet]:
        """Feuilles agrégées des bases CLIENT, une colonne « nœud » chacune.

        Un seul passage sur les nœuds du projet alimente les sept feuilles :
        ``historique_urgences``, ``evaluations``, ``snapshots_kpi``,
        ``evenements``, ``decisions``, ``revues_hebdo`` et ``audit``.

        Args:
            nodes: nœuds du projet.

        Returns:
            Les sept feuilles agrégées, dans l'ordre du classeur.
        """
        kpi_columns = _kpi_columns()
        urgences: list[list[Any]] = []
        evaluations: list[list[Any]] = []
        snapshots: list[list[Any]] = []
        evenements: list[list[Any]] = []
        decisions: list[list[Any]] = []
        revues: list[list[Any]] = []
        audits: list[list[Any]] = []
        for node in nodes:
            client = self._service.client_db(node.id)
            urgences.extend(self._rows_urgences(client, node))
            evaluations.extend(self._rows_evaluations(client, node))
            snapshots.extend(self._rows_snapshots(client, node, kpi_columns))
            evenements.extend(self._rows_evenements(client, node))
            decisions.extend(self._rows_decisions(client, node))
            revues.extend(self._rows_revues(client, node))
            audits.extend(self._rows_audit(client, node))
        return [
            (
                "historique_urgences",
                [
                    "nœud",
                    "semaine",
                    "date",
                    "ud_local",
                    "ur_local",
                    "ud",
                    "ur",
                    "adequation",
                    "false_urgency",
                    "hidden_risk",
                ],
                urgences,
            ),
            (
                "evaluations",
                ["nœud", "opérateur", "semaine", "ud", "CR", "cohérente", "notes", "remplacée par"],
                evaluations,
            ),
            ("snapshots_kpi", ["nœud", "date", "semaine", *kpi_columns], snapshots),
            (
                "evenements",
                [
                    "nœud",
                    "type",
                    "semaine",
                    "date",
                    "paramètres",
                    "impacts",
                    "annulé le",
                    "opérateur",
                    "notes",
                ],
                evenements,
            ),
            (
                "decisions",
                ["nœud", "semaine", "opérateur", "description", "ud", "ur", "a", "f", "h"],
                decisions,
            ),
            (
                "revues_hebdo",
                ["nœud", "semaine", "volets", "début", "fin", "durée (minutes)"],
                revues,
            ),
            ("audit", ["nœud", *_AUDIT_HEADERS], audits),
        ]

    # --- Lignes par nœud (bases client) -----------------------------------------------

    @staticmethod
    def _rows_urgences(client: ClientDatabase, node: SupplyNode) -> list[list[Any]]:
        """Lignes ``urgency_history`` du nœud, chronologiques.

        Args:
            client: base CLIENT du nœud.
            node: nœud exporté.

        Returns:
            Les lignes de la feuille ``historique_urgences``.
        """
        return [
            [
                node.name,
                iso_week(state.timestamp),
                _fmt_date(state.timestamp),
                state.ud_local,
                state.ur_local,
                state.ud,
                state.ur,
                state.adequation,
                state.false_urgency,
                state.hidden_risk,
            ]
            for state in client.urgency_series(node.id)
        ]

    @staticmethod
    def _rows_evaluations(client: ClientDatabase, node: SupplyNode) -> list[list[Any]]:
        """Lignes ``assessments`` du nœud (avec l'id de l'évaluation correctrice).

        Args:
            client: base CLIENT du nœud.
            node: nœud exporté.

        Returns:
            Les lignes de la feuille ``evaluations``.
        """
        with client.lock:
            rows = client.conn.execute(_SQL_EVALUATIONS, (node.id,)).fetchall()
        return [
            [
                node.name,
                row["operator_id"],
                row["iso_week"],
                row["ud"],
                row["consistency_ratio"],
                "oui" if row["is_consistent"] else "non",
                row["notes"],
                row["remplacee_par"],
            ]
            for row in rows
        ]

    @staticmethod
    def _rows_snapshots(
        client: ClientDatabase, node: SupplyNode, kpi_columns: list[str]
    ) -> list[list[Any]]:
        """Lignes ``kpi_snapshots`` du nœud, KPIs aplatis en colonnes « bloc.champ ».

        Args:
            client: base CLIENT du nœud.
            node: nœud exporté.
            kpi_columns: colonnes aplaties (cf. :func:`_kpi_columns`).

        Returns:
            Les lignes de la feuille ``snapshots_kpi``.
        """
        with client.lock:
            rows = client.conn.execute(_SQL_SNAPSHOTS, (node.id,)).fetchall()
        return [
            [
                node.name,
                _fmt_date(row["timestamp"]),
                iso_week(row["timestamp"]),
                *_kpi_values(kpis_from_json(row["kpis_json"]), kpi_columns),
            ]
            for row in rows
        ]

    @staticmethod
    def _rows_evenements(client: ClientDatabase, node: SupplyNode) -> list[list[Any]]:
        """Lignes ``events`` du nœud, paramètres et impacts résumés.

        Args:
            client: base CLIENT du nœud.
            node: nœud exporté.

        Returns:
            Les lignes de la feuille ``evenements``.
        """
        rows: list[list[Any]] = []
        for event in client.list_events(node.id):
            params = json.loads(event["params_json"])
            impacts = json.loads(event["impacts_json"])
            rows.append(
                [
                    node.name,
                    event["event_type"],
                    event["iso_week"],
                    _fmt_date(event["occurred_at"]),
                    json.dumps(params, ensure_ascii=False, sort_keys=True),
                    _resume_impacts(impacts),
                    _fmt_date(event["reverted_at"]),
                    event["operator_id"],
                    event["notes"],
                ]
            )
        return rows

    @staticmethod
    def _rows_decisions(client: ClientDatabase, node: SupplyNode) -> list[list[Any]]:
        """Lignes ``decisions`` du nœud, chronologiques, scores du snapshot dépliés.

        Args:
            client: base CLIENT du nœud.
            node: nœud exporté.

        Returns:
            Les lignes de la feuille ``decisions``.
        """
        return [
            [
                node.name,
                decision["iso_week"],
                decision["operator_id"],
                decision["description"],
                decision["scores"].get("ud"),
                decision["scores"].get("ur"),
                decision["scores"].get("a"),
                decision["scores"].get("f"),
                decision["scores"].get("h"),
            ]
            for decision in reversed(client.list_decisions(node.id))
        ]

    @staticmethod
    def _rows_revues(client: ClientDatabase, node: SupplyNode) -> list[list[Any]]:
        """Lignes ``weekly_reviews`` du nœud, durée en minutes si la revue est bornée.

        Args:
            client: base CLIENT du nœud.
            node: nœud exporté.

        Returns:
            Les lignes de la feuille ``revues_hebdo``.
        """
        with client.lock:
            rows = client.conn.execute(_SQL_REVUES, (node.id,)).fetchall()
        result: list[list[Any]] = []
        for row in rows:
            started, completed = row["started_at"], row["completed_at"]
            duree: float | str = ""
            if started is not None and completed is not None:
                duree = round((completed - started) / 60.0, 1)
            result.append(
                [
                    node.name,
                    row["iso_week"],
                    row["volets_json"],
                    _fmt_date(started),
                    _fmt_date(completed),
                    duree,
                ]
            )
        return result

    @staticmethod
    def _rows_audit(client: ClientDatabase, node: SupplyNode) -> list[list[Any]]:
        """Lignes ``audit_log`` de la base CLIENT du nœud, chronologiques.

        Args:
            client: base CLIENT du nœud.
            node: nœud exporté.

        Returns:
            Les lignes de la feuille ``audit`` (préfixées du nom du nœud).
        """
        with client.lock:
            rows = client.conn.execute(_SQL_AUDIT).fetchall()
        return [[node.name, *_audit_row(row)] for row in rows]

    def _sheet_audit_registre(self) -> _Sheet:
        """Feuille « audit_registre » : le journal d'audit GLOBAL du registre.

        Le registre est partagé entre projets : son journal n'est pas filtré
        (les entités auditées — nœuds, arcs, jalons — n'y portent pas toutes
        leur projet).

        Returns:
            La feuille ``audit_registre``.
        """
        registry = self._service.registry
        with registry.lock:
            rows = registry.conn.execute(_SQL_AUDIT).fetchall()
        return ("audit_registre", list(_AUDIT_HEADERS), [_audit_row(row) for row in rows])


def _audit_row(row: Any) -> list[Any]:
    """Ligne d'export d'une entrée ``audit_log`` (colonnes de :data:`_AUDIT_HEADERS`).

    Args:
        row: ligne SQLite de la table ``audit_log``.

    Returns:
        Les valeurs dans l'ordre de :data:`_AUDIT_HEADERS`, date formatée.
    """
    return [
        row["entity_type"],
        row["entity_id"],
        row["field"],
        row["old_value"],
        row["new_value"],
        row["source"],
        row["operator_id"],
        row["iso_week"],
        _fmt_date(row["timestamp"]),
    ]
