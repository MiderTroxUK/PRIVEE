"""Lance analyse_campagne.py sur les snapshots du pilote LLM, sans toucher au
dossier partagé analysis/snapshots/ (celui du vrai dry run v6)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyse_campagne  # noqa: E402

analyse_campagne.SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"

if __name__ == "__main__":
    sys.exit(analyse_campagne.main())
