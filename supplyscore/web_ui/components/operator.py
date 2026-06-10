"""Sélecteur d'opérateur global : « qui joue ? ».

Pendant le serious game, plusieurs joueurs se relaient sur le même poste :
ce composant compact, affiché à droite de la barre de navigation, mémorise
l'opérateur actif dans ``dcc.Store(id="store-operator")`` (session). Les
pages utilisent :func:`current_operator` pour estampiller leurs écritures.
"""

from __future__ import annotations

from dash import Input, Output, State, dcc, html

from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY

#: Nom d'opérateur par défaut quand aucun nom valide n'est saisi.
DEFAULT_OPERATOR = "anonyme"

_LABEL_STYLE = {
    "color": "#dfe9f0",
    "fontSize": "13px",
    "marginRight": "8px",
    "whiteSpace": "nowrap",
}

_INPUT_DARK_STYLE = {
    "backgroundColor": COLORS["primary"],
    "color": "#fff",
    "border": "1px solid rgba(255, 255, 255, 0.35)",
    "borderRadius": "5px",
    "padding": "5px 10px",
    "fontFamily": FONT_FAMILY,
    "fontSize": "13px",
    "width": "140px",
}

_BADGE_STYLE = {
    "backgroundColor": "rgba(255, 255, 255, 0.15)",
    "color": "#dfe9f0",
    "borderRadius": "10px",
    "padding": "3px 10px",
    "marginLeft": "10px",
    "fontSize": "12px",
    "fontWeight": "600",
    "whiteSpace": "nowrap",
}


def operator_selector() -> html.Div:
    """Élément compact pour la navbar : saisie du nom + badge de l'opérateur actif."""
    return html.Div(
        [
            html.Label("Opérateur :", htmlFor="operator-name-input", style=_LABEL_STYLE),
            dcc.Input(
                id="operator-name-input",
                type="text",
                placeholder=DEFAULT_OPERATOR,
                debounce=True,
                style=_INPUT_DARK_STYLE,
            ),
            html.Span(DEFAULT_OPERATOR, id="operator-badge", style=_BADGE_STYLE),
        ],
        style={"display": "flex", "alignItems": "center", "fontFamily": FONT_FAMILY},
    )


def current_operator(store_value) -> str:
    """Retourne le nom de l'opérateur actif (helper pur, sans état).

    Args:
        store_value: contenu de ``dcc.Store(id="store-operator")`` — un dict
            ``{"name": ...}``, ou None tant que rien n'a été saisi.

    Returns:
        Le nom saisi (sans espaces superflus, casse conservée), ou
        ``"anonyme"`` si le store est absent, invalide ou vide.
    """
    if isinstance(store_value, dict):
        name = str(store_value.get("name") or "").strip()
        if name:
            return name
    return DEFAULT_OPERATOR


# --- Callbacks (fonctions nommées, testables sans serveur) --------------------


def set_operator_callback(value, store):
    """Met à jour l'opérateur actif depuis le champ de saisie de la navbar.

    Au chargement initial (``value`` à None), l'opérateur mémorisé en session
    est conservé. Un nom vidé ou réduit à des espaces retombe sur
    ``"anonyme"`` ; le nom est sinon trimé, casse conservée.

    Args:
        value: contenu du champ ``operator-name-input`` (debounce).
        store: contenu courant de ``store-operator`` (clés annexes préservées).

    Returns:
        Le nouveau contenu du store et le texte du badge.
    """
    name = current_operator(store) if value is None else (str(value).strip() or DEFAULT_OPERATOR)
    data = dict(store) if isinstance(store, dict) else {}
    data["name"] = name
    return data, name


def register_callbacks(app) -> None:
    """Enregistre le callback du sélecteur d'opérateur sur l'application Dash."""
    app.callback(
        Output("store-operator", "data"),
        Output("operator-badge", "children"),
        Input("operator-name-input", "value"),
        State("store-operator", "data"),
    )(set_operator_callback)
