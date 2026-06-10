"""Badges de statut hebdomadaire et de complétude d'onboarding.

Les statuts hebdo arrivent en chaînes (``"a_jour"`` / ``"en_retard"`` /
``"manquant"``) : côté services c'est un ``StrEnum``, volontairement PAS
importé ici (duck-typing — toute chaîne, y compris un membre de StrEnum,
convient ; une valeur inconnue donne le badge gris « — »).

Piège Dash documenté : une cellule de ``dash_table.DataTable`` n'accepte PAS
de composant (le rendu afficherait la représentation texte du composant).
Pour les tableaux, utiliser :func:`texte_hebdo` (libellé brut dans la cellule)
combiné à :func:`style_hebdo_conditionnel` (``style_data_conditional`` qui
colore la cellule selon ce texte). Le badge riche :func:`badge_hebdo` est
réservé aux cartes et listes.
"""

from __future__ import annotations

from dash import html

from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY

#: Style commun des pilules : fond pâle, texte foncé, coins arrondis.
_PILL_BASE: dict[str, str] = {
    "display": "inline-block",
    "padding": "2px 10px",
    "borderRadius": "10px",
    "fontSize": "12px",
    "fontWeight": "600",
    "fontFamily": FONT_FAMILY,
    "whiteSpace": "nowrap",
}

#: Couples (fond pâle, texte foncé) par teinte — les textes reprennent COLORS.
_HUES: dict[str, dict[str, str]] = {
    "ok": {"backgroundColor": "#e2f2e7", "color": COLORS["ok"]},
    "warn": {"backgroundColor": "#f8ecdb", "color": COLORS["warn"]},
    "alert": {"backgroundColor": "#fae5e3", "color": COLORS["alert"]},
    "muted": {"backgroundColor": "#ebeef1", "color": COLORS["muted"]},
}

#: Teinte associée à chaque statut hebdo connu (inconnu → « muted »).
_STATUT_HUE: dict[str, str] = {
    "a_jour": "ok",
    "en_retard": "warn",
    "manquant": "alert",
}


def _pill(label: str, hue: str) -> html.Span:
    """Pilule colorée : libellé sur fond pâle, texte foncé de la même teinte."""
    return html.Span(label, style={**_PILL_BASE, **_HUES[hue]})


def texte_hebdo(statut: str, semaines_de_retard: int = 0) -> str:
    """Libellé texte brut d'un statut hebdo (cellules de DataTable).

    Une cellule de DataTable n'accepte pas de composant : ce texte y est
    inscrit tel quel, et :func:`style_hebdo_conditionnel` colore la cellule
    selon sa valeur. Même libellé que :func:`badge_hebdo`.

    Args:
        statut: ``"a_jour"`` / ``"en_retard"`` / ``"manquant"`` (chaîne ou
            membre de StrEnum) ; toute autre valeur donne « — ».
        semaines_de_retard: nombre de semaines de retard, repris dans le
            libellé « En retard (n sem.) ».
    """
    if statut == "a_jour":
        return "À jour"
    if statut == "en_retard":
        return f"En retard ({semaines_de_retard} sem.)"
    if statut == "manquant":
        return "Manquant"
    return "—"


def badge_hebdo(statut: str, semaines_de_retard: int = 0) -> html.Span:
    """Badge pilule d'un statut hebdo (cartes et listes, PAS les DataTable).

    Vert « À jour », orange « En retard (n sem.) », rouge « Manquant » ;
    statut inconnu → badge gris « — ».

    Args:
        statut: ``"a_jour"`` / ``"en_retard"`` / ``"manquant"`` (chaîne ou
            membre de StrEnum).
        semaines_de_retard: nombre de semaines de retard (statut
            ``"en_retard"``).
    """
    return _pill(texte_hebdo(statut, semaines_de_retard), _STATUT_HUE.get(statut, "muted"))


def completeness_badge(done: int, total: int) -> html.Span:
    """Badge « x/4 sections » : vert si complet, orange sinon (wizard E5).

    Args:
        done: nombre de sections validées.
        total: nombre total de sections attendues.
    """
    return _pill(f"{done}/{total} sections", "ok" if done >= total else "warn")


def draft_badge() -> html.Span:
    """Badge gris « Incomplet » (nœud en cours d'onboarding)."""
    return _pill("Incomplet", "muted")


def style_hebdo_conditionnel(column_id: str) -> list[dict]:
    """Règles ``style_data_conditional`` pour une colonne de statuts hebdo.

    Trois règles colorent la cellule selon le texte produit par
    :func:`texte_hebdo` : vert si le libellé commence par « À jour », orange
    par « En retard », rouge par « Manquant ». La grammaire ``filter_query``
    de Dash n'a pas d'opérateur « commence par » générique : on utilise
    ``contains``, sans risque de collision (aucun libellé n'en contient un
    autre).

    Args:
        column_id: identifiant de la colonne DataTable contenant les libellés.
    """
    prefixes = [("À jour", "ok"), ("En retard", "warn"), ("Manquant", "alert")]
    return [
        {
            "if": {
                "column_id": column_id,
                "filter_query": f'{{{column_id}}} contains "{prefix}"',
            },
            "backgroundColor": _HUES[hue]["backgroundColor"],
            "color": _HUES[hue]["color"],
            "fontWeight": "600",
        }
        for prefix, hue in prefixes
    ]
