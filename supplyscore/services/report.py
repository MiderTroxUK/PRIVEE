"""Rapport de session HTML imprimable - livrable du serious game (E11, Lot 11.2).

:class:`SessionReport` agrege tout le materiau d'une partie dans UN fichier
HTML autonome et imprimable (``Rapport_<slug>_AAAAMMJJ_HHMMSS.html``) :

1. en-tete (projet, periode couverte, mode horloge, nombre de noeuds) ;
2. synthese des scores courants par noeud (Ud/Ur/A/F/H) ;
3. evolution temporelle Ud/Ur/A par noeud (figures Plotly reutilisees de
   :mod:`supplyscore.web_ui.components.figures`) ;
4. chronologie fusionnee des evenements et des decisions, par semaine ISO ;
5. calibration prediction/realite (:class:`~supplyscore.services.calibration.CalibrationService`),
   effectifs TOUJOURS affiches a cote des taux ;
6. graphe final de la chaine (``dashboard_dag_figure``).

Le JavaScript Plotly est inclus UNE seule fois via CDN dans le ``<head>`` :
l'ouverture du rapport necessite donc une connexion internet - acceptable pour
un rapport d'analyse. Les figures elles-memes sont embarquees via
``fig.to_html(full_html=False, include_plotlyjs=False)``.

Lecture seule - le rapport n'ecrit rien dans les bases. Les helpers de nom de
fichier (``_slugify``) et de date (``_fmt_date``) sont RECOPIES de
:mod:`supplyscore.services.exports` ou ils sont prives (non exposes).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Template
from markupsafe import Markup
from plotly.offline import get_plotlyjs_version

from supplyscore.core.clock import iso_week
from supplyscore.domain.events import EVENT_CALIBRATION
from supplyscore.services.calibration import CalibrationService
from supplyscore.web_ui.components.figures import dashboard_dag_figure, urgency_history_figure
from supplyscore.web_ui.components.layout import STATUS_FR

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from supplyscore.domain.models import Project, SupplyNode, UrgencyState
    from supplyscore.services.orchestrator import SupplyScoreService

#: URL CDN du JavaScript Plotly correspondant a la version embarquee par plotly.py.
_PLOTLY_CDN_URL = f"https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js"

#: En deca de cet effectif de points noeud-semaine, un avertissement d'echantillon reduit est affiche dans la section calibration (PLAN E11 : jamais un taux seul).
_SEUIL_PETIT_ECHANTILLON = 30

#: Seuil H de la matrice de confusion affichee dans le rapport.
_SEUIL_H = 0.5

#: Gabarit Jinja2 inline du rapport - autonome, en francais, print-friendly.
_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Rapport de session — {{ nom_projet }}</title>
<!-- Plotly chargé UNE fois via CDN : l'ouverture du rapport nécessite internet. -->
<script src="{{ plotly_cdn }}" charset="utf-8"></script>
<style>
  body { font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
         color: #22313a; margin: 24px auto; max-width: 960px; padding: 0 16px; }
  h1 { font-size: 22px; border-bottom: 2px solid #2c5f7c; padding-bottom: 8px; }
  h2 { font-size: 17px; color: #2c5f7c; margin: 30px 0 8px; }
  h3 { font-size: 14px; margin: 18px 0 6px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px;
          margin: 8px 0 16px; break-inside: avoid; }
  th, td { border: 1px solid #d8dee3; padding: 5px 8px; text-align: left; }
  th { background: #eef2f5; }
  .meta th { width: 220px; }
  .muted { color: #6b7a85; font-size: 13px; }
  .warn { color: #b06000; font-weight: 600; font-size: 13px; }
  .figure { margin: 10px 0 22px; break-inside: avoid; }
  footer { margin-top: 36px; color: #6b7a85; font-size: 12px;
           border-top: 1px solid #d8dee3; padding-top: 8px; }
  @media print { body { margin: 0; max-width: none; } }
</style>
</head>
<body>
<h1>Rapport de session — {{ nom_projet }}</h1>
<table class="meta">
  <tr><th>Période couverte</th><td>{{ periode }}</td></tr>
  <tr><th>Mode horloge</th><td>{{ mode_horloge }}</td></tr>
  <tr><th>Nombre de nœuds</th><td>{{ synthese|length }}</td></tr>
  <tr><th>Généré le</th><td>{{ genere_le }}</td></tr>
</table>

<h2>1. Synthèse des scores</h2>
{% if synthese %}
<table>
  <thead><tr><th>Nœud</th><th>Rang</th><th>Statut</th><th>Ud</th><th>Ur</th>
             <th>A</th><th>F</th><th>H</th></tr></thead>
  <tbody>
  {% for ligne in synthese %}
    <tr><td>{{ ligne.nom }}</td><td>{{ ligne.rang }}</td><td>{{ ligne.statut }}</td>
        <td>{{ ligne.ud }}</td><td>{{ ligne.ur }}</td><td>{{ ligne.a }}</td>
        <td>{{ ligne.f }}</td><td>{{ ligne.h }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% else %}<p class="muted">Le projet ne contient aucun nœud.</p>{% endif %}

<h2>2. Évolution temporelle</h2>
{% for evolution in evolutions %}
<div class="figure">{{ evolution }}</div>
{% else %}
<p class="muted">Aucun nœud ne possède encore d'historique d'urgence.</p>
{% endfor %}

<h2>3. Chronologie des événements et décisions</h2>
{% for semaine in chronologie %}
<h3>Semaine {{ semaine.semaine }}</h3>
<table>
  <thead><tr><th>Type</th><th>Nœud</th><th>Intitulé</th><th>Détail</th>
             <th>Opérateur</th><th>Statut</th></tr></thead>
  <tbody>
  {% for entree in semaine.entrees %}
    <tr><td>{{ entree.genre }}</td><td>{{ entree.noeud }}</td>
        <td>{{ entree.titre }}</td><td>{{ entree.detail }}</td>
        <td>{{ entree.operateur }}</td><td>{{ entree.statut }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p class="muted">Aucun événement ni décision consignés pendant la session.</p>
{% endfor %}

<h2>4. Calibration prédiction / réalité</h2>
<p>{{ calibration.synthese }}</p>
{% if calibration.avertissement %}
<p class="warn">{{ calibration.avertissement }}</p>
{% endif %}
{% if calibration.matrice %}
<table>
  <thead><tr><th>Seuil H = {{ calibration.matrice.seuil }}</th>
             <th>Issue défavorable observée</th><th>Pas d'issue défavorable</th></tr></thead>
  <tbody>
    <tr><th>H ≥ seuil (alerte)</th><td>VP = {{ calibration.matrice.vp }}</td>
        <td>FP = {{ calibration.matrice.fp }}</td></tr>
    <tr><th>H &lt; seuil</th><td>FN = {{ calibration.matrice.fn }}</td>
        <td>VN = {{ calibration.matrice.vn }}</td></tr>
  </tbody>
</table>
<p>Précision : {{ calibration.matrice.precision }} — Rappel : {{ calibration.matrice.rappel }}</p>
<table>
  <thead><tr><th>H moyen du segment</th><th>Taux d'issues défavorables (effectif)</th></tr></thead>
  <tbody>
  {% for segment in calibration.courbe %}
    <tr><td>{{ segment.h_moyen }}</td><td>{{ segment.taux }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p class="muted">Aucun point de calibration : pas encore assez d'historique pour
apparier les prédictions (H) et les issues observées.</p>
{% endif %}

<h2>5. Graphe final</h2>
<div class="figure">{{ graphe_final }}</div>

<footer>SupplyScore — rapport de session généré automatiquement.</footer>
</body>
</html>
""",
    autoescape=True,
)


def _slugify(name: str) -> str:
    """Slugifie un nom de projet pour un nom de fichier sur.

    Recopie de :mod:`supplyscore.services.exports` (helper prive non expose) :
    accents translitteres (NFKD puis ASCII), tout caractere non alphanumerique
    devient un tiret, tirets de bord retires.

    Args:
        name: nom libre du projet (accents, espaces, " / "... toleres).

    Returns:
        Le slug " alphanumerique + tirets ", ``"projet"`` si le nom ne
        contient aucun caractere translitterable.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-")
    return slug or "projet"


def _fmt_date(ts: float | None) -> str:
    """Formate un epoch en " JJ/MM/AAAA HH:MM " (heure locale), ``""`` si None.

    Recopie de :mod:`supplyscore.services.exports` (helper prive non expose).

    Args:
        ts: instant en secondes epoch, ou ``None``.

    Returns:
        La date formatee en heure locale, ou la chaine vide.
    """
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def _fmt(value: float | None, digits: int = 2) -> str:
    """Formate une valeur numerique optionnelle (" - " si None).

    Args:
        value: valeur a formater, ou ``None`` (score jamais calcule).
        digits: nombre de decimales affichees.

    Returns:
        La valeur formatee, ou " - ".
    """
    return "—" if value is None else f"{value:.{digits}f}"


def _fig_html(fig: go.Figure) -> Markup:
    """Fragment HTML d'une figure Plotly, SANS le JavaScript Plotly.

    Le JS est inclus une seule fois via CDN dans le ``<head>`` du rapport ;
    chaque figure n'embarque que son ``<div class="plotly-graph-div">`` et son
    script d'instanciation.

    Args:
        fig: figure Plotly a embarquer.

    Returns:
        Le fragment HTML, marque sur pour le gabarit (non re-echappe).
    """
    return Markup(fig.to_html(full_html=False, include_plotlyjs=False))


class SessionReport:
    """Genere le rapport de session HTML autonome et imprimable d'un projet.

    S'appuie sur la facade :class:`~supplyscore.services.orchestrator.SupplyScoreService` :
    le registre fournit le projet, ses noeuds et ses arcs ; chaque base CLIENT
    fournit l'historique d'urgence, les evenements et les decisions de son
    noeud ; :class:`~supplyscore.services.calibration.CalibrationService`
    fournit la section calibration. Lecture seule.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le generateur de rapport au-dessus de la facade.

        Args:
            service: facade applicative (registre, bases client, horloge).
        """
        self._service = service

    # API publique

    def build(
        self,
        project_id: str,
        horizon_weeks: int = 4,
        dest_dir: Path | str = "exports",
    ) -> Path:
        """Genere le rapport HTML du projet dans ``dest_dir`` (cree au besoin).

        Produit ``Rapport_<slug>_AAAAMMJJ_HHMMSS.html``, l'horodatage venant de
        l'horloge du service en heure locale. Le fichier est autonome (CSS
        inline) ; seul le JavaScript Plotly est charge via CDN a l'ouverture
        (connexion internet requise - acceptable pour un rapport).

        Args:
            project_id: identifiant du projet a rapporter.
            horizon_weeks: horizon (en semaines) de l'appariement
                prediction/realite de la section calibration.
            dest_dir: repertoire de destination, cree s'il n'existe pas.

        Returns:
            Le chemin du fichier HTML produit.

        Raises:
            ValueError: si le projet est inconnu du registre.
        """
        project = self._service.registry.get_project(project_id)
        if project is None:
            raise ValueError(f"projet inconnu du registre : {project_id!r}")

        html = self._render(project, horizon_weeks)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(self._service.clock.now()).strftime("%Y%m%d_%H%M%S")
        path = dest / f"Rapport_{_slugify(project.name)}_{stamp}.html"
        path.write_text(html, encoding="utf-8")
        return path

    # Rendu

    def _render(self, project: Project, horizon_weeks: int) -> str:
        """Assemble le contexte des six sections et rend le gabarit Jinja2.

        Args:
            project: projet a rapporter (deja valide).
            horizon_weeks: horizon de la section calibration.

        Returns:
            Le document HTML complet.
        """
        nodes = self._service.registry.list_nodes(project.id)
        series_by_node = {node.id: self._series(node.id) for node in nodes}
        mode = self._service.clock_mode(project.id)
        return _TEMPLATE.render(
            nom_projet=project.name,
            plotly_cdn=_PLOTLY_CDN_URL,
            periode=self._periode(series_by_node),
            mode_horloge="temps de jeu" if mode == "game" else "temps réel",
            genere_le=_fmt_date(self._service.clock.now()),
            synthese=self._synthese(nodes),
            evolutions=self._evolutions(nodes, series_by_node),
            chronologie=self._chronologie(nodes),
            calibration=self._calibration(project.id, horizon_weeks),
            graphe_final=self._graphe_final(nodes),
        )

    def _series(self, node_id: str) -> list[UrgencyState]:
        """Historique d'urgence du noeud (base CLIENT), chronologique.

        Args:
            node_id: identifiant du noeud.

        Returns:
            La serie temporelle des etats d'urgence du noeud.
        """
        return self._service.client_db(node_id).urgency_series(node_id)

    @staticmethod
    def _periode(series_by_node: dict[str, list[UrgencyState]]) -> str:
        """Periode couverte : premiere -> derniere semaine ISO de l'historique.

        Args:
            series_by_node: historiques d'urgence par noeud.

        Returns:
            " AAAA-Sxx -> AAAA-Sxx ", ou " aucun historique " si aucune serie.
        """
        timestamps = [state.timestamp for series in series_by_node.values() for state in series]
        if not timestamps:
            return "aucun historique"
        return f"{iso_week(min(timestamps))} → {iso_week(max(timestamps))}"

    @staticmethod
    def _synthese(nodes: list[SupplyNode]) -> list[dict[str, Any]]:
        """Lignes du tableau de synthese : scores courants par noeud.

        Args:
            nodes: noeuds du projet (ordre registre : rang puis id).

        Returns:
            Une ligne par noeud : nom, rang, statut FR, Ud/Ur/A/F/H formates.
        """
        return [
            {
                "nom": node.name,
                "rang": node.rank,
                "statut": STATUS_FR.get(node.status, str(node.status)),
                "ud": _fmt(node.urgency.ud),
                "ur": _fmt(node.urgency.ur),
                "a": _fmt(node.urgency.adequation, 1),
                "f": _fmt(node.urgency.false_urgency),
                "h": _fmt(node.urgency.hidden_risk),
            }
            for node in nodes
        ]

    @staticmethod
    def _evolutions(
        nodes: list[SupplyNode], series_by_node: dict[str, list[UrgencyState]]
    ) -> list[Markup]:
        """Figures d'evolution Ud/Ur/A, une par noeud AVEC historique.

        Args:
            nodes: noeuds du projet.
            series_by_node: historiques d'urgence par noeud.

        Returns:
            Les fragments HTML des figures (noeuds sans historique omis).
        """
        return [
            _fig_html(urgency_history_figure(series_by_node[node.id], node.name))
            for node in nodes
            if series_by_node[node.id]
        ]

    # Chronologie

    def _chronologie(self, nodes: list[SupplyNode]) -> list[dict[str, Any]]:
        """Evenements et decisions fusionnes par semaine ISO, en ordre chronologique.

        Args:
            nodes: noeuds du projet.

        Returns:
            Une entree par semaine : ``{"semaine", "entrees"}``, les semaines
            et les entrees en ordre chronologique.
        """
        entries: list[dict[str, Any]] = []
        for node in nodes:
            client = self._service.client_db(node.id)
            for event in client.list_events(node.id):
                entries.append(self._entree_evenement(node, event))
            for decision in client.list_decisions(node.id):
                entries.append(self._entree_decision(node, decision))
        entries.sort(key=lambda entry: entry["ts"])
        by_week: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_week.setdefault(entry["semaine"], []).append(entry)
        return [{"semaine": week, "entrees": rows} for week, rows in by_week.items()]

    @staticmethod
    def _entree_evenement(node: SupplyNode, event: dict[str, Any]) -> dict[str, Any]:
        """Entree de chronologie d'un evenement : type FR, parametres, annule ou non.

        Args:
            node: noeud declarant.
            event: ligne ``events`` de la base CLIENT (dict).

        Returns:
            L'entree normalisee pour le gabarit (cle ``ts`` pour le tri).
        """
        spec = EVENT_CALIBRATION.get(event["event_type"])
        labels = {field.name: field.label_fr for field in spec.fields} if spec else {}
        units = {field.name: field.unit for field in spec.fields} if spec else {}
        params: dict[str, Any] = json.loads(event["params_json"])
        detail = " ; ".join(
            f"{labels.get(key, key)} : {value}" + (f" {units[key]}" if units.get(key) else "")
            for key, value in sorted(params.items())
        )
        reverted = event["reverted_at"]
        return {
            "ts": event["occurred_at"],
            "semaine": event["iso_week"],
            "genre": "Événement",
            "noeud": node.name,
            "titre": spec.label_fr if spec else event["event_type"],
            "detail": detail,
            "operateur": event["operator_id"],
            "statut": f"annulé le {_fmt_date(reverted)}" if reverted is not None else "actif",
        }

    @staticmethod
    def _entree_decision(node: SupplyNode, decision: dict[str, Any]) -> dict[str, Any]:
        """Entree de chronologie d'une decision : operateur et scores au moment T.

        Args:
            node: noeud concerne.
            decision: ligne ``decisions`` deserialisee de la base CLIENT.

        Returns:
            L'entree normalisee pour le gabarit (cle ``ts`` pour le tri).
        """
        scores: dict[str, float | None] = decision["scores"]
        detail = (
            f"Scores au moment T : Ud = {_fmt(scores.get('ud'))} · "
            f"Ur = {_fmt(scores.get('ur'))} · A = {_fmt(scores.get('a'), 1)} · "
            f"F = {_fmt(scores.get('f'))} · H = {_fmt(scores.get('h'))}"
        )
        return {
            "ts": decision["created_at"],
            "semaine": decision["iso_week"],
            "genre": "Décision",
            "noeud": node.name,
            "titre": decision["description"],
            "detail": detail,
            "operateur": decision["operator_id"],
            "statut": "",
        }

    # Calibration

    def _calibration(self, project_id: str, horizon_weeks: int) -> dict[str, Any]:
        """Contexte de la section calibration : synthese, matrice, courbe, avertissement.

        Les EFFECTIFS sont toujours rendus a cote des taux (precision, rappel
        et chaque segment de la courbe) - jamais un pourcentage seul (PLAN E11).

        Args:
            project_id: identifiant du projet.
            horizon_weeks: horizon de l'appariement prediction/realite.

        Returns:
            ``{"synthese", "avertissement", "matrice", "courbe"}`` ; matrice a
            ``None`` et courbe vide s'il n'existe aucun point de calibration.
        """
        calibration = CalibrationService(self._service)
        points = calibration.outcomes(project_id, horizon_weeks=horizon_weeks)
        avertissement = ""
        if len(points) < _SEUIL_PETIT_ECHANTILLON:
            avertissement = (
                f"Échantillon réduit ({len(points)} point(s) nœud-semaine) : interpréter "
                "les taux avec prudence — l'effectif est affiché à côté de chaque taux."
            )
        if not points:
            return {
                "synthese": (
                    "Aucun point de calibration : pas encore assez d'historique pour "
                    "apparier les prédictions (H) et les issues observées."
                ),
                "avertissement": avertissement,
                "matrice": None,
                "courbe": [],
            }
        matrix = calibration.confusion(points, seuil=_SEUIL_H)
        curve = calibration.calibration_curve(points, n_bins=5)
        return {
            "synthese": calibration.summary(
                project_id, horizon_weeks=horizon_weeks, seuil=_SEUIL_H
            ),
            "avertissement": avertissement,
            "matrice": {
                "seuil": _fmt(matrix.seuil),
                "vp": matrix.vp,
                "fp": matrix.fp,
                "fn": matrix.fn,
                "vn": matrix.vn,
                # Taux TOUJOURS accompagnes de leur effectif (numerateur/denominateur).
                "precision": f"{_fmt(matrix.precision)} ({matrix.vp}/{matrix.vp + matrix.fp})",
                "rappel": f"{_fmt(matrix.rappel)} ({matrix.vp}/{matrix.vp + matrix.fn})",
            },
            "courbe": [
                {
                    "h_moyen": _fmt(h_moyen),
                    "taux": f"{_fmt(taux)} (effectif : {effectif})",
                }
                for h_moyen, taux, effectif in curve
            ],
        }

    # Graphe final

    def _graphe_final(self, nodes: list[SupplyNode]) -> Markup:
        """Figure du DAG final du projet (arcs internes au projet uniquement).

        Args:
            nodes: noeuds du projet.

        Returns:
            Le fragment HTML de la figure ``dashboard_dag_figure``.
        """
        ids = {node.id for node in nodes}
        arcs = [
            arc
            for arc in self._service.registry.list_arcs()
            if arc.source_id in ids and arc.target_id in ids
        ]
        return _fig_html(dashboard_dag_figure(nodes, arcs))
