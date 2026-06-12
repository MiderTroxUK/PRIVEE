"""Cohérence entre la documentation (README, docs/) et le code source."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from supplyscore import __version__
from supplyscore.cli import build_parser

RACINE = Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs"
README = RACINE / "README.md"

#: Lien ou image markdown : capture la cible entre parenthèses.
_LIEN_MD = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")

#: Motif d'option longue dans un texte (un tiret double suivi d'une lettre).
_FLAG = re.compile(r"--[a-z][a-z-]*")


def _flags_du_parser() -> set[str]:
    flags: set[str] = set()
    for action in build_parser()._actions:
        flags.update(s for s in action.option_strings if s.startswith("--"))
    return flags


def test_options_cli_toutes_documentees():
    """Chaque option longue de build_parser apparaît dans docs/reference_cli.md."""
    texte = (DOCS / "reference_cli.md").read_text(encoding="utf-8")
    manquantes = sorted(f for f in _flags_du_parser() - {"--help"} if f not in texte)
    assert not manquantes, f"options absentes de reference_cli.md : {manquantes}"


def test_flags_du_readme_existent_dans_le_parser():
    """Chaque motif --option du README correspond à une option réelle de la CLI."""
    flags_readme = set(_FLAG.findall(README.read_text(encoding="utf-8")))
    inconnus = sorted(flags_readme - _flags_du_parser())
    assert not inconnus, f"flags cités dans README.md mais absents du parser : {inconnus}"


def _noms_feuilles_export() -> set[str]:
    """Noms de feuilles extraits des tuples _Sheet (nom, en-têtes, lignes) d'exports.py."""
    source = (RACINE / "supplyscore" / "services" / "exports.py").read_text(encoding="utf-8")
    noms: set[str] = set()
    for noeud in ast.walk(ast.parse(source)):
        if (
            isinstance(noeud, ast.Tuple)
            and len(noeud.elts) == 3
            and isinstance(noeud.elts[0], ast.Constant)
            and isinstance(noeud.elts[0].value, str)
        ):
            noms.add(noeud.elts[0].value)
    return noms


def test_feuilles_export_documentees():
    """Chaque nom de feuille d'export apparaît dans docs/reference_donnees.md."""
    noms = _noms_feuilles_export()
    assert len(noms) >= 10, f"extraction des feuilles suspecte : {sorted(noms)}"
    texte = (DOCS / "reference_donnees.md").read_text(encoding="utf-8")
    manquants = sorted(n for n in noms if n not in texte)
    assert not manquants, f"feuilles absentes de reference_donnees.md : {manquants}"


def test_versions_schema_documentees():
    """Les versions de schéma maximales (registre, client) sont citées dans le doc."""
    source = (RACINE / "supplyscore" / "data" / "migrations.py").read_text(encoding="utf-8")
    v_registre = max(int(v) for v in re.findall(r"def _registry_v(\d+)\(", source))
    v_client = max(int(v) for v in re.findall(r"def _client_v(\d+)\(", source))
    pragmas = [int(v) for v in re.findall(r"PRAGMA user_version = (\d+)", source)]
    assert max(pragmas) == max(v_registre, v_client)
    texte = (DOCS / "reference_donnees.md").read_text(encoding="utf-8")
    assert f"schéma final v{v_registre}" in texte, f"registre v{v_registre} non cité"
    assert f"schéma final v{v_client}" in texte, f"client v{v_client} non cité"


def test_nombre_de_pages_dans_le_readme():
    """La table des pages du README compte une ligne par module de web_ui/pages/."""
    dossier = RACINE / "supplyscore" / "web_ui" / "pages"
    modules = [p for p in dossier.glob("*.py") if p.name != "__init__.py"]
    lignes_table = [
        ligne
        for ligne in README.read_text(encoding="utf-8").splitlines()
        if ligne.startswith("|") and re.search(r"`/[^`]*`", ligne)
    ]
    assert len(lignes_table) == len(modules), (
        f"{len(modules)} modules de pages mais {len(lignes_table)} lignes de table dans README.md"
    )


def test_liens_relatifs_existent():
    """Chaque cible relative de lien ou d'image markdown existe sur disque."""
    fichiers = [README, *sorted(DOCS.rglob("*.md"))]
    casses: list[str] = []
    for fichier in fichiers:
        for cible in _LIEN_MD.findall(fichier.read_text(encoding="utf-8")):
            if cible.startswith(("http://", "https://", "mailto:", "#")):
                continue
            chemin = cible.split("#", 1)[0]
            if chemin and not (fichier.parent / chemin).exists():
                casses.append(f"{fichier.relative_to(RACINE)} -> {cible}")
    assert not casses, "liens cassés : " + ", ".join(casses)


def test_version_paquet_alignee_sur_le_changelog():
    """supplyscore.__version__ égale la première entrée versionnée du CHANGELOG."""
    texte = (RACINE / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", texte, flags=re.MULTILINE)
    assert versions, "aucune entrée versionnée dans CHANGELOG.md"
    assert versions[0] == __version__
