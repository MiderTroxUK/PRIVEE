"""Restauration en ligne de commande d'une archive de sauvegarde SupplyScore.

Usage::

    python -m supplyscore.tools.restore <zip> [--db-dir data_store] [--force]

Code retour : 0 si la restauration aboutit, 1 sinon (message d'erreur en
francais sur la sortie d'erreur). Les bases existantes ne sont jamais
detruites : ``--force`` les deplace dans ``avant_restauration_*`` avant de
restaurer.
"""

from __future__ import annotations

import argparse
import sys
import zipfile

from supplyscore.data.backup import IntegriteError, restore_backup


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de l'outil de restauration.

    Returns:
        Le :class:`argparse.ArgumentParser` configure (``zip_path``,
        ``--db-dir``, ``--force``).
    """
    parser = argparse.ArgumentParser(
        prog="python -m supplyscore.tools.restore",
        description=(
            "Restaure les bases SQLite SupplyScore depuis une archive de "
            "sauvegarde SupplyScore_AAAAMMJJ_HHMMSS.zip."
        ),
    )
    parser.add_argument("zip_path", help="archive de sauvegarde (.zip) à restaurer")
    parser.add_argument(
        "--db-dir",
        default="data_store",
        help="répertoire cible des bases SQLite (défaut : data_store)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="met les bases existantes à l'abri (avant_restauration_*) avant de restaurer",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entree : restaure l'archive et affiche la liste des bases restaurees.

    Args:
        argv: arguments de la ligne de commande (``sys.argv[1:]`` si None).

    Returns:
        0 si la restauration aboutit, 1 en cas d'erreur (message francais
        sur la sortie d'erreur).
    """
    args = build_parser().parse_args(argv)
    try:
        restaurees = restore_backup(args.zip_path, args.db_dir, force=args.force)
    except (OSError, ValueError, zipfile.BadZipFile, IntegriteError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    print(f"{len(restaurees)} base(s) restaurée(s) dans {args.db_dir} :")
    for nom in restaurees:
        print(f"  - {nom}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
