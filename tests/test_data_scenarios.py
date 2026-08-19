"""Tests de la persistance des scenarios nommes (Lot 15.3).

Couvre : round-trip complet d'un payload JSON arbitraire, upsert (rename,
``updated_at`` rafraichi, ``created_at`` preserve), unicite du nom PAR projet
(ValueError francais), tri de ``list_scenarios``, suppression, validation du
JSON avant ecriture, reouverture de fichier et migration registre v4 -> v5
(idempotente, sur base reelle peuplee).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from supplyscore.data.db import RegistryDatabase
from supplyscore.data.migrations import (
    _registry_v1,
    _registry_v2,
    _registry_v3,
    _registry_v4,
    apply_migrations,
)

# Payload arbitraire : dicts imbriques, listes, types JSON varies.
_PAYLOAD = {
    "criticite": {"seuils": [0.2, 0.5, 0.8], "mode": "strict"},
    "noeuds_geles": ["n1", "n7"],
    "facteur": 1.5,
    "actif": True,
    "commentaire": None,
}


# CRUD des scenarios


class TestScenarioRoundTrip:
    def test_round_trip_payload_arbitraire(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Référence hiver", json.dumps(_PAYLOAD), now=1000.0)
            scenario = db.get_scenario("s1")

        assert scenario == {
            "id": "s1",
            "project_id": "p1",
            "nom": "Référence hiver",
            "payload": _PAYLOAD,
            "created_at": 1000.0,
            "updated_at": 1000.0,
        }

    def test_get_scenario_inconnu_retourne_none(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            assert db.get_scenario("fantome") is None

    def test_reouverture_de_fichier(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Persistant", json.dumps(_PAYLOAD), now=42.0)

        with RegistryDatabase(tmp_path) as db:
            scenario = db.get_scenario("s1")
            assert scenario is not None
            assert scenario["nom"] == "Persistant"
            assert scenario["payload"] == _PAYLOAD
            assert scenario["created_at"] == 42.0


class TestScenarioUpsert:
    def test_upsert_rename_rafraichit_updated_at_preserve_created_at(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Avant", json.dumps({"v": 1}), now=1000.0)
            db.save_scenario("s1", "p1", "Après", json.dumps({"v": 2}), now=2000.0)

            scenario = db.get_scenario("s1")
            assert scenario is not None
            assert scenario["nom"] == "Après"
            assert scenario["payload"] == {"v": 2}
            assert scenario["created_at"] == 1000.0  # preserve
            assert scenario["updated_at"] == 2000.0  # rafraichi
            # Pas de doublon : l'upsert a mis a jour la MEME ligne.
            assert len(db.list_scenarios("p1")) == 1

    def test_upsert_meme_nom_meme_id_ok(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Stable", json.dumps({"v": 1}), now=1000.0)
            # Reecriture sous le meme nom et le meme id : pas de conflit.
            db.save_scenario("s1", "p1", "Stable", json.dumps({"v": 2}), now=2000.0)

            scenario = db.get_scenario("s1")
            assert scenario is not None
            assert scenario["payload"] == {"v": 2}
            assert scenario["created_at"] == 1000.0
            assert scenario["updated_at"] == 2000.0


class TestScenarioUniciteNom:
    def test_doublon_de_nom_meme_projet_autre_id_leve_valueerror(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Hiver", json.dumps({"v": 1}), now=1000.0)

            with pytest.raises(ValueError, match="un scénario de ce nom existe déjà"):
                db.save_scenario("s2", "p1", "Hiver", json.dumps({"v": 2}), now=2000.0)

            # La ligne existante est intacte, la nouvelle n'a pas ete ecrite.
            scenario = db.get_scenario("s1")
            assert scenario is not None and scenario["payload"] == {"v": 1}
            assert db.get_scenario("s2") is None

    def test_doublon_via_rename_dun_autre_scenario_leve_valueerror(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Hiver", json.dumps({"v": 1}), now=1000.0)
            db.save_scenario("s2", "p1", "Été", json.dumps({"v": 2}), now=1100.0)

            # Renommer s2 vers le nom deja porte par s1 : refuse.
            with pytest.raises(ValueError, match="un scénario de ce nom existe déjà"):
                db.save_scenario("s2", "p1", "Hiver", json.dumps({"v": 3}), now=2000.0)

            # s2 est reste tel quel (transaction annulee).
            scenario = db.get_scenario("s2")
            assert scenario is not None
            assert scenario["nom"] == "Été"
            assert scenario["payload"] == {"v": 2}
            assert scenario["updated_at"] == 1100.0

    def test_meme_nom_sur_autre_projet_ok(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Hiver", json.dumps({"v": 1}), now=1000.0)
            db.save_scenario("s2", "p2", "Hiver", json.dumps({"v": 2}), now=2000.0)

            assert [s["id"] for s in db.list_scenarios("p1")] == ["s1"]
            assert [s["id"] for s in db.list_scenarios("p2")] == ["s2"]


class TestScenarioListEtDelete:
    def test_list_trie_par_updated_at_desc(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Un", json.dumps({}), now=1000.0)
            db.save_scenario("s2", "p1", "Deux", json.dumps({}), now=2000.0)
            db.save_scenario("s3", "p1", "Trois", json.dumps({}), now=3000.0)
            # s1 mis a jour en dernier : il remonte en tete.
            db.save_scenario("s1", "p1", "Un", json.dumps({"maj": True}), now=4000.0)

            assert [s["id"] for s in db.list_scenarios("p1")] == ["s1", "s3", "s2"]
            # Un projet sans scenario : liste vide (pas d'erreur).
            assert db.list_scenarios("projet-vide") == []

    def test_delete_scenario(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Éphémère", json.dumps(_PAYLOAD), now=1000.0)
            db.delete_scenario("s1")

            assert db.get_scenario("s1") is None
            assert db.list_scenarios("p1") == []
            # Suppression d'un id inconnu : silencieuse.
            db.delete_scenario("fantome")

    def test_delete_libere_le_nom(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Hiver", json.dumps({}), now=1000.0)
            db.delete_scenario("s1")
            # Le nom redevient disponible pour un autre id.
            db.save_scenario("s2", "p1", "Hiver", json.dumps({}), now=2000.0)
            assert [s["id"] for s in db.list_scenarios("p1")] == ["s2"]


class TestScenarioPayloadInvalide:
    def test_payload_json_invalide_leve_valueerror_sans_ecrire(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            with pytest.raises(ValueError, match="JSON valide"):
                db.save_scenario("s1", "p1", "Cassé", "{ pas du json", now=1000.0)

            # Rien n'a ete ecrit (validation AVANT l'INSERT).
            assert db.get_scenario("s1") is None
            assert db.list_scenarios("p1") == []

    def test_payload_invalide_sur_id_existant_ne_modifie_rien(self, tmp_path: Path) -> None:
        with RegistryDatabase(tmp_path) as db:
            db.save_scenario("s1", "p1", "Sain", json.dumps({"v": 1}), now=1000.0)

            with pytest.raises(ValueError, match="JSON valide"):
                db.save_scenario("s1", "p1", "Sain", "[1, 2,", now=2000.0)

            scenario = db.get_scenario("s1")
            assert scenario is not None
            assert scenario["payload"] == {"v": 1}
            assert scenario["updated_at"] == 1000.0


# Migration registre v4 -> v5


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row[0] for row in rows}


def _build_v4_registry_with_data(db_file: Path) -> None:
    """Construit une vraie base registre v4 peuplee (projet + noeud + audit)."""
    conn = sqlite3.connect(str(db_file))
    _registry_v1(conn)
    _registry_v2(conn)
    _registry_v3(conn)
    _registry_v4(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    conn.execute(
        "INSERT INTO projects (id, name, owner_node_id, description, created_at, t0_ts) "
        "VALUES ('p1', 'Projet', 'n1', 'desc', 1000.0, 900.0)"
    )
    conn.execute(
        """
        INSERT INTO nodes (id, name, label, kind, rank, project_id, location,
                           latitude, longitude, status, kpis_json, onboarding_state)
        VALUES ('n1', 'Client', 'Client', 'node', 0, 'p1', 'Lyon',
                45.7, 4.8, 'active', '{}', 'complete')
        """
    )
    conn.execute(
        """
        INSERT INTO audit_log (entity_type, entity_id, field, old_value, new_value,
                               source, operator_id, iso_week, timestamp)
        VALUES ('node', 'n1', 'status', 'idle', 'active', 'ui', 'op-7', '2026-S24', 1234.0)
        """
    )
    conn.commit()
    conn.close()


class TestRegistryV5Migration:
    def test_v4_to_v5_cree_scenarios_et_preserve_les_donnees(self, tmp_path: Path) -> None:
        db_file = tmp_path / "registry.sqlite"
        _build_v4_registry_with_data(db_file)

        conn = sqlite3.connect(str(db_file))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert apply_migrations(conn, "registry") == 5
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5

        # Nouvelle table et son index presents.
        assert "scenarios" in _table_names(conn)
        assert "idx_scenarios_project" in _index_names(conn)

        # Donnees preservees.
        row = conn.execute("SELECT name, created_at, t0_ts FROM projects").fetchone()
        assert row == ("Projet", 1000.0, 900.0)
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()

    def test_v5_est_idempotente(self, tmp_path: Path) -> None:
        db_file = tmp_path / "registry.sqlite"
        _build_v4_registry_with_data(db_file)
        conn = sqlite3.connect(str(db_file))

        assert apply_migrations(conn, "registry") == 5
        # Un scenario ecrit APRES la premiere migration survit a la re-application.
        conn.execute(
            "INSERT INTO scenarios (id, project_id, nom, payload_json, created_at, updated_at) "
            "VALUES ('s1', 'p1', 'Référence', '{}', 1.0, 1.0)"
        )
        conn.commit()

        # Re-application : no-op, donnees intactes.
        assert apply_migrations(conn, "registry") == 5
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        conn.close()

    def test_registre_neuf_atteint_v5(self, tmp_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_path / "registry.sqlite"))
        assert apply_migrations(conn, "registry") == 5
        assert "scenarios" in _table_names(conn)
        assert "idx_scenarios_project" in _index_names(conn)
        conn.close()

    def test_unicite_nom_par_projet_au_niveau_sql(self, tmp_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_path / "registry.sqlite"))
        apply_migrations(conn, "registry")
        conn.execute(
            "INSERT INTO scenarios (id, project_id, nom, payload_json, created_at, updated_at) "
            "VALUES ('s1', 'p1', 'Hiver', '{}', 1.0, 1.0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scenarios (id, project_id, nom, payload_json, created_at, "
                "updated_at) VALUES ('s2', 'p1', 'Hiver', '{}', 2.0, 2.0)"
            )
        conn.close()
