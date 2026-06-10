"""Point d'entrée local de l'interface web SupplyScore.

Usage :
    python run_app.py [--db-dir data_store] [--demo] [--port 8050] [--debug]

L'option ``--demo`` génère un projet de TEST aléatoire (seed_demo) uniquement
si la base est vide — données simulées, jamais pour la production.
"""

from __future__ import annotations

import argparse

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
    args = parser.parse_args()

    app = create_app(db_dir=args.db_dir)
    service = get_service()
    if args.demo and not service.registry.list_nodes():
        project = service.seed_demo(n_ranks=3, seed=42)
        print(f"Démo générée : « {project.name} » (données de TEST aléatoires).")

    app.run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
