"""Point d'entrée local de l'interface web SupplyScore.

Usage :
    python run_app.py [--db-dir data_store] [--demo] [--port 8050] [--debug]
                      [--log-level INFO]

L'option ``--demo`` génère un projet de TEST aléatoire (seed_demo) uniquement
si la base est vide — données simulées, jamais pour la production.
"""

from __future__ import annotations

import argparse
import atexit

from supplyscore import __version__
from supplyscore.infra.logging import configure_logging
from supplyscore.web_ui import get_service
from supplyscore.web_ui.app import create_app


def main() -> None:
    """Analyse les arguments, construit l'application et lance le serveur."""
    parser = argparse.ArgumentParser(description="Lance l'interface web SupplyScore (Dash).")
    parser.add_argument(
        "--db-dir", default="data_store", help="Répertoire des bases SQLite (défaut : data_store)."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Si la base est vide, génère un projet de TEST aléatoire (n_ranks=3, seed=42).",
    )
    parser.add_argument(
        "--port", type=int, default=8050, help="Port d'écoute HTTP (défaut : 8050)."
    )
    parser.add_argument(
        "--debug", action="store_true", help="Active le mode debug de Dash (rechargement à chaud)."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Niveau de journalisation (DEBUG, INFO, WARNING... — défaut : INFO).",
    )
    args = parser.parse_args()

    logger = configure_logging(level=args.log_level)
    logger.info(
        "Démarrage de SupplyScore v%s — port %s, base : %s", __version__, args.port, args.db_dir
    )

    app = create_app(db_dir=args.db_dir)

    try:
        service = get_service()
    except RuntimeError:
        service = None
        logger.warning("Service SupplyScore non initialisé après create_app.")

    if service is not None:
        close = getattr(service, "close", None)
        if callable(close):
            atexit.register(close)

        if args.demo and not service.registry.list_nodes():
            project = service.seed_demo(n_ranks=3, seed=42)
            print(f"Démo générée : « {project.name} » (données de TEST aléatoires).")

    app.run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
