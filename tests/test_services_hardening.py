"""Tests du durcissement du service (Lot 10.2).

Couvre les faiblesses #9 et #10 du PLAN :
- ``submit_assessment`` refuse cote SERVEUR toute evaluation incoherente
  (CR >= 0.10) - rien n'est persiste ;
- ``remove_arc`` / ``remove_node`` : retrait registre + repo, base SQLite du
  client CONSERVEE en archive, cache LRU purge, rangs canoniques recalcules
  puis reevaluation ;
- ``add_node`` recale TOUS les rangs sur la definition canonique " plus
  longue distance vers un puits " (graphes en diamant).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from supplyscore.core.clock import FixedClock
from supplyscore.domain.models import Project, SupplyArc, SupplyNode
from supplyscore.graph import GraphRepository, InMemoryGraphRepository
from supplyscore.services import SupplyScoreService

#: Mercredi 2026-06-10 12:00 locale - semaine ISO " 2026-S24 ".
_NOW = datetime(2026, 6, 10, 12, 0).timestamp()

#: Jugements contradictoires (A >> B, B >> C mais C >> A) : CR tres au-dela de 0.10.
_INCOHERENT: dict[tuple[int, int], float] = {(0, 1): 9.0, (1, 2): 9.0, (0, 2): 1.0 / 9.0}

#: Jugements parfaitement coherents (tous egaux) : CR = 0.
_COHERENT: dict[tuple[int, int], float] = {
    (0, 1): 1.0,
    (0, 2): 1.0,
    (0, 3): 1.0,
    (1, 2): 1.0,
    (1, 3): 1.0,
    (2, 3): 1.0,
}


@pytest.fixture
def service(tmp_path: Path):
    svc = SupplyScoreService(db_dir=tmp_path / "store", clock=FixedClock(_NOW))
    yield svc
    svc.close()


def _node(node_id: str, rank: int = 0) -> SupplyNode:
    return SupplyNode(id=node_id, name=node_id.upper(), rank=rank, project_id="p1")


def _seed_chain(service: SupplyScoreService) -> None:
    """Chaine 3 noeuds a -> b -> c (source = fournisseur, c = client final)."""
    project = Project(id="p1", name="Chaîne", owner_node_id="c", created_at=_NOW, t0_ts=_NOW)
    nodes = [_node("c", 0), _node("b", 1), _node("a", 2)]
    arcs = [SupplyArc(source_id="b", target_id="c"), SupplyArc(source_id="a", target_id="b")]
    service.create_project(project, nodes, arcs)


# submit_assessment : CR refuse cote serveur (faiblesse #9)


class TestSubmitAssessmentRefuseLeCR:
    def test_cr_incoherent_leve_valueerror_francais(self, service):
        _seed_chain(service)
        assessment = SupplyScoreService.build_assessment(
            node_id="a",
            project_id="p1",
            operator_id="op",
            comparisons=_INCOHERENT,
            criteria_scores=[5.0, 5.0, 5.0],
        )
        assert assessment.consistency_ratio >= 0.10  # garde du scenario
        with pytest.raises(
            ValueError,
            match=r"Évaluation refusée : CR = \d+\.\d{3} >= 0\.10 — jugements incohérents",
        ):
            service.submit_assessment(assessment)

    def test_refus_ne_persiste_rien(self, service):
        _seed_chain(service)
        # Une premiere evaluation COHERENTE pose la reference (1 ligne, ud_local connu).
        ok = SupplyScoreService.build_assessment("a", "p1", "op", _COHERENT, [5.0, 5.0, 5.0, 5.0])
        service.submit_assessment(ok)
        ud_avant = service.repo.get_node("a").urgency.ud_local
        n_lignes = len(service.client_db("a").list_assessments("a"))
        assert n_lignes == 1

        bad = SupplyScoreService.build_assessment("a", "p1", "op", _INCOHERENT, [9.0, 9.0, 9.0])
        with pytest.raises(ValueError, match="révisez les comparaisons"):
            service.submit_assessment(bad)

        # AUCUNE ligne ajoutee dans assessments, ud_local inchange.
        assert len(service.client_db("a").list_assessments("a")) == n_lignes
        assert service.repo.get_node("a").urgency.ud_local == ud_avant
        assert service.registry.get_node("a").urgency.ud_local == ud_avant

    def test_refus_avant_toute_ouverture_de_base(self, service, tmp_path):
        _seed_chain(service)
        bad = SupplyScoreService.build_assessment("a", "p1", "op", _INCOHERENT, [9.0, 9.0, 9.0])
        with pytest.raises(ValueError, match="Évaluation refusée"):
            service.submit_assessment(bad)
        # Le refus intervient avant client_db : pas meme un fichier sqlite cree.
        assert not (tmp_path / "store" / "a.sqlite").exists()
        assert "a" not in service._client_dbs


# remove_arc


class TestRemoveArc:
    def test_retire_du_repo_et_du_registre(self, service):
        _seed_chain(service)
        service.remove_arc("a", "b")
        assert service.repo.get_arc("a", "b") is None
        assert service.registry.get_arc("a", "b") is None
        # L'autre arc de la chaine est intact.
        assert service.repo.get_arc("b", "c") is not None
        assert service.registry.get_arc("b", "c") is not None

    def test_recalcule_les_rangs(self, service):
        _seed_chain(service)
        service.remove_arc("a", "b")
        # a, fournisseur isole (plus aucun client aval), passe au rang 0.
        assert service.repo.get_node("a").rank == 0
        assert service.registry.get_node("a").rank == 0
        assert service.repo.get_node("b").rank == 1
        assert service.repo.get_node("c").rank == 0

    def test_reevalue_le_reseau(self, service):
        _seed_chain(service)
        assert service.repo.get_node("c").urgency.adequation is None
        service.remove_arc("b", "c")
        # evaluate_all(persist=True) a tourne : adequation posee et historisee.
        assert service.repo.get_node("c").urgency.adequation is not None
        assert len(service.client_db("c").urgency_series("c")) == 1

    def test_arc_inconnu_leve_keyerror_sans_rien_modifier(self, service):
        _seed_chain(service)
        with pytest.raises(KeyError, match="Arc inconnu"):
            service.remove_arc("c", "a")
        assert service.registry.get_arc("b", "c") is not None
        assert service.registry.get_arc("a", "b") is not None


# remove_node


class TestRemoveNode:
    def test_retire_noeud_et_arcs_mais_archive_le_sqlite(self, service, tmp_path):
        _seed_chain(service)
        db_file = service.client_db("b").db_path  # ouvre (et cree) la base du client
        assert db_file.exists()

        service.remove_node("b")

        # Noeud absent du repo ET du registre, arcs incidents retires.
        assert service.repo.get_node("b") is None
        assert service.registry.get_node("b") is None
        assert service.repo.get_arc("a", "b") is None
        assert service.repo.get_arc("b", "c") is None
        assert service.registry.get_arc("a", "b") is None
        assert service.registry.get_arc("b", "c") is None
        # La base SQLite du client est CONSERVEE en archive.
        assert db_file.exists()

    def test_ferme_et_evince_la_base_du_cache_lru(self, service):
        _seed_chain(service)
        db = service.client_db("b")
        assert "b" in service._client_dbs

        service.remove_node("b")

        assert "b" not in service._client_dbs
        assert db.conn is None  # connexion fermee proprement (plus de handle)
        # Le checkpoint WAL de close() a purge les fichiers annexes.
        assert not Path(str(db.db_path) + "-wal").exists()
        assert not Path(str(db.db_path) + "-shm").exists()

    def test_recalcule_les_rangs_et_reevalue(self, service):
        _seed_chain(service)
        service.remove_node("b")
        # a, prive de son client aval, passe au rang 0 (recalcul canonique).
        assert service.repo.get_node("a").rank == 0
        assert service.registry.get_node("a").rank == 0
        # Reevaluation persistee pour les noeuds restants.
        assert service.repo.get_node("c").urgency.adequation is not None

    def test_noeud_inconnu_leve_keyerror_sans_rien_modifier(self, service):
        _seed_chain(service)
        with pytest.raises(KeyError, match="Nœud inconnu"):
            service.remove_node("zz")
        assert service.registry.get_node("a") is not None
        assert service.repo.get_node("a") is not None


# add_node : rangs canoniques dans les graphes en diamant (faiblesse #10)


def _seed_diamond(service: SupplyScoreService) -> None:
    """Diamant a->b->d et a->c->d, PLUS b->c qui allonge le chemin de b.

    Rangs stockes facon UI (" 1 + max(cibles) " au moment de chaque ajout) :
    d=0, c=1, b=1 (deduit de b->d avant que b->c n'existe), a=2.
    Rangs canoniques (plus longue distance vers un puits) :
    d=0, c=1, b=2 (b->c->d), a=3 (a->b->c->d).
    """
    project = Project(id="p1", name="Diamant", owner_node_id="d", created_at=_NOW, t0_ts=_NOW)
    nodes = [_node("d", 0), _node("c", 1), _node("b", 1), _node("a", 2)]
    arcs = [
        SupplyArc(source_id="b", target_id="d"),
        SupplyArc(source_id="c", target_id="d"),
        SupplyArc(source_id="b", target_id="c"),  # allonge le chemin de b
        SupplyArc(source_id="a", target_id="b"),
        SupplyArc(source_id="a", target_id="c"),
    ]
    service.create_project(project, nodes, arcs)


class TestAddNodeRangsCanoniques:
    def test_add_node_recalcule_tous_les_rangs(self, service):
        _seed_diamond(service)
        # create_project ne recale pas : le rang UI divergent est en place.
        assert service.repo.get_node("b").rank == 1
        assert service.repo.get_node("a").rank == 2

        # L'ajout d'un noeud amont recale TOUT le graphe sur le canonique.
        service.add_node(_node("e", 0), supplies_to=["a"])

        assert {n.id: n.rank for n in service.repo.nodes()} == {
            "d": 0,
            "c": 1,
            "b": 2,
            "a": 3,
            "e": 4,
        }
        # ... et persiste les rangs corriges dans le registre.
        assert service.registry.get_node("b").rank == 2
        assert service.registry.get_node("a").rank == 3
        assert service.registry.get_node("e").rank == 4

    def test_add_node_isole_reste_rang_zero(self, service):
        _seed_chain(service)
        service.add_node(_node("seul", 7))  # rang fantaisiste fourni par l'appelant
        assert service.repo.get_node("seul").rank == 0
        assert service.registry.get_node("seul").rank == 0
        # Les rangs de la chaine, deja canoniques, n'ont pas bouge.
        assert service.repo.get_node("a").rank == 2


# _reassign_ranks : repli generique pour un depot sans assign_ranks


class _RepoSansAssignRanks(GraphRepository):
    """Doublure : delegue tout au depot memoire SANS exposer ``assign_ranks``."""

    def __init__(self) -> None:
        self._inner = InMemoryGraphRepository()

    def add_node(self, node):
        self._inner.add_node(node)

    def get_node(self, node_id):
        return self._inner.get_node(node_id)

    def update_node(self, node):
        self._inner.update_node(node)

    def remove_node(self, node_id):
        self._inner.remove_node(node_id)

    def add_arc(self, arc):
        self._inner.add_arc(arc)

    def get_arc(self, source_id, target_id):
        return self._inner.get_arc(source_id, target_id)

    def remove_arc(self, source_id, target_id):
        self._inner.remove_arc(source_id, target_id)

    def nodes(self):
        return self._inner.nodes()

    def arcs(self, kinds=None):
        return self._inner.arcs(kinds)

    def predecessors(self, node_id, *, kinds=("nominal",)):
        return self._inner.predecessors(node_id, kinds=kinds)

    def successors(self, node_id, *, kinds=("nominal",)):
        return self._inner.successors(node_id, kinds=kinds)

    def nodes_by_project(self, project_id):
        return self._inner.nodes_by_project(project_id)

    def topological_order(self):
        return self._inner.topological_order()

    def clear(self):
        self._inner.clear()


def test_reassign_ranks_repli_generique_sans_assign_ranks(tmp_path):
    """Le diamant est recale meme si le depot n'expose pas ``assign_ranks``."""
    svc = SupplyScoreService(
        db_dir=tmp_path / "store",
        repo=_RepoSansAssignRanks(),
        clock=FixedClock(_NOW),
    )
    try:
        _seed_diamond(svc)
        svc.add_node(_node("e", 0), supplies_to=["a"])
        assert {n.id: n.rank for n in svc.repo.nodes()} == {
            "d": 0,
            "c": 1,
            "b": 2,
            "a": 3,
            "e": 4,
        }
        assert svc.registry.get_node("b").rank == 2
    finally:
        svc.close()
