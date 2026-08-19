"""Pages de l'application Dash (projets, questionnaire, dashboard, simulation).

Chaque module expose :

- ``layout()`` : construit l'arbre de composants de la page (fonction et non
  constante, pour relire l'etat du service a chaque navigation) ;
- ``register_callbacks(app)`` : enregistre les callbacks (fonctions nommees
  au niveau module, testables sans serveur) - appele une fois par
  :func:`supplyscore.web_ui.app.create_app`.
"""

from supplyscore.web_ui.pages import dashboard, projects, questionnaire, simulation

__all__ = ["dashboard", "projects", "questionnaire", "simulation"]
