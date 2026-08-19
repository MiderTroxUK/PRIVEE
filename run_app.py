"""Point d'entree local retro-compatible de l'interface web SupplyScore.

Depuis le Lot 17.3, TOUTE la logique vit dans :mod:`supplyscore.cli` :
la commande installee ``supplyscore`` (entry point ``supplyscore.cli:main``)
ou ``python -m supplyscore.cli`` sont les points d'entree de reference.

Ce mince wrapper conserve les usages historiques :

- ``python run_app.py [options]`` reste fonctionnel (memes options) ;
- ``from run_app import resolve_db_dir`` reste valable (reexport a
  signature identique - ``tests/test_infra_paths.py`` s'y appuie).
"""

from __future__ import annotations

import sys

from supplyscore.cli import main, resolve_db_dir

__all__ = ["main", "resolve_db_dir"]

if __name__ == "__main__":
    sys.exit(main())
