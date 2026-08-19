"""Service d'onboarding - wizard 4 sections, brouillon persiste EN BASE.

Machine a etats du wizard (source de verite : table ``onboarding_progress``) :

- ``start_draft`` -> le noeud est cree IMMEDIATEMENT (``onboarding_state='draft'``,
  rang 0, aucun arc) et la progression est initialisee (sections a 0,
  brouillon vide, etape 1) ;
- ``save_section(k)`` -> VALIDE puis ecrit les entites reelles et pose
  ``sections_done[k] = 1`` ; en cas d'erreur de validation, RIEN n'est ecrit
  et la liste des erreurs (messages francais) est retournee ;
- ``save_draft(k)`` -> ecrit ``draft_json`` SANS valider (" enregistrer le
  brouillon et quitter ") ;
- ``complete()`` -> exige les 4 sections faites, pose
  ``onboarding_state='complete'``, supprime la progression et relance
  ``evaluate_all(persist=True)``.

Sections : **1** identite + type + tags + connexions ; **2** cahier des
charges + jalons ; **3** KPIs initiaux ; **4** premiere evaluation AHP.
Toutes les ecritures metier passent par :class:`MutationService`
(``source='onboarding'``) ; les entites sans mutation auditee (tags crees par
nom, jalons recrees en bloc) passent par le registre.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from supplyscore.core.ahp import CONSISTENCY_THRESHOLD, CRITERIA
from supplyscore.domain.milestones import Milestone
from supplyscore.domain.models import ArcKind, SupplyArc, SupplyNode
from supplyscore.domain.specsheet import cdc_from_json, cdc_to_json
from supplyscore.domain.tags import Tag

if TYPE_CHECKING:
    from supplyscore.services.orchestrator import SupplyScoreService

#: Cles des 4 sections du wizard, dans l'ordre des etapes (etape = index + 1).
SECTION_KEYS: tuple[str, str, str, str] = ("identity", "cdc", "kpis", "ahp")

#: Libelles francais des sections (messages d'erreur de :meth:`OnboardingService.complete`).
_SECTION_LABELS: dict[str, str] = {
    "identity": "identité",
    "cdc": "cahier des charges",
    "kpis": "KPIs",
    "ahp": "évaluation AHP",
}

#: Origine posee sur toutes les mutations du wizard (journal d'audit).
_SOURCE = "onboarding"


@dataclass(frozen=True)
class OnboardingState:
    """Etat courant du wizard d'un noeud, tel que persiste en base."""

    #: Identifiant du noeud en cours d'onboarding.
    node_id: str
    #: Avancement par section : ``{"identity": 0|1, "cdc": 0|1, "kpis": 0|1, "ahp": 0|1}``.
    sections_done: dict[str, int]
    #: Reponses partielles NON validees, par section : ``{"identity": {...}, ...}``.
    draft: dict
    #: Etape courante du wizard, dans [1, 4].
    current_step: int


@dataclass(frozen=True)
class SectionResult:
    """Resultat d'une tentative d'ecriture de section (ou de completion)."""

    #: True si la section a ete validee ET ecrite.
    ok: bool
    #: Messages d'erreur en francais ; liste vide si ``ok``.
    errors: list[str]


def _as_float(value: Any, label: str, errors: list[str]) -> float | None:
    """Convertit ``value`` en float, ou ajoute une erreur francaise a ``errors``.

    Args:
        value: valeur brute issue du payload (None = manquante).
        label: prefixe francais du message d'erreur (ex. " Jalon 2 : debut ").
        errors: liste d'erreurs alimentee en place.

    Returns:
        La valeur convertie, ou None si elle est manquante ou non numerique.
    """
    if value is None:
        errors.append(f"{label} : valeur manquante.")
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} : valeur non numérique ({value!r}).")
        return None


def _as_float_01(value: Any, label: str, errors: list[str]) -> float | None:
    """Comme :func:`_as_float`, avec borne supplementaire [0, 1].

    Args:
        value: valeur brute issue du payload.
        label: prefixe francais du message d'erreur (ex. " Connexion 1 : gamma ").
        errors: liste d'erreurs alimentee en place.

    Returns:
        La valeur convertie si elle est dans [0, 1], None sinon.
    """
    number = _as_float(value, label, errors)
    if number is not None and not 0.0 <= number <= 1.0:
        errors.append(f"{label} : {number} hors [0, 1].")
        return None
    return number


class OnboardingService:
    """Wizard d'onboarding d'un noeud en 4 sections, brouillon persiste en base.

    S'appuie sur la facade :class:`SupplyScoreService` : le registre porte la
    table ``onboarding_progress`` (source de verite de la machine a etats),
    les ecritures metier passent par :class:`MutationService`
    (``source='onboarding'``) et la completion relance le pipeline complet
    (``evaluate_all(persist=True)``).

    Thread-safety : les methodes mutantes prennent ``self._lock`` (RLock) pour
    serialiser les cycles lecture-validation-ecriture du wizard.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service d'onboarding au-dessus de la facade.

        Args:
            service: facade applicative (registre, mutations, horloges, pipeline).
        """
        self._service = service
        self._lock = threading.RLock()

    # cycle de vie du brouillon

    def start_draft(self, project_id: str, name: str, label: str = "Supplier") -> str:
        """Cree IMMEDIATEMENT le noeud en brouillon et initialise sa progression.

        Le noeud nait avec ``onboarding_state='draft'``, rang 0 et aucun arc ;
        la ligne ``onboarding_progress`` demarre a l'etape 1, sections a 0,
        brouillon vide.

        Args:
            project_id: projet de rattachement du noeud.
            name: nom du noeud (modifiable en section 1).
            label: type du noeud (Supplier, Factory, Workshop...).

        Returns:
            L'identifiant (uuid4) du noeud cree.
        """
        with self._lock:
            node_id = str(uuid.uuid4())
            node = SupplyNode(
                id=node_id,
                name=name,
                label=label,
                rank=0,
                project_id=project_id,
                onboarding_state="draft",
            )
            self._service.add_node(node)
            self._service.registry.save_onboarding(node_id, dict.fromkeys(SECTION_KEYS, 0), {}, 1)
            return node_id

    def load(self, node_id: str) -> OnboardingState:
        """Restitue l'etat du wizard depuis la table ``onboarding_progress``.

        Si la progression a ete supprimee (onboarding termine) mais que le
        noeud existe, un etat synthetique est reconstruit : 4 sections faites
        si le noeud est ``complete``, 0 sinon.

        Args:
            node_id: identifiant du noeud.

        Returns:
            L'etat courant du wizard (sections faites, brouillon, etape).

        Raises:
            KeyError: si AUCUN brouillon NI noeud n'existe pour cet id.
        """
        registry = self._service.registry
        progress = registry.get_onboarding(node_id)
        if progress is not None:
            done = progress["sections_done"]
            return OnboardingState(
                node_id=node_id,
                sections_done={key: int(done.get(key, 0)) for key in SECTION_KEYS},
                draft=dict(progress["draft"]),
                current_step=int(progress["current_step"]),
            )
        node = registry.get_node(node_id)
        if node is None:
            raise KeyError(f"Aucun brouillon d'onboarding ni nœud pour l'id : {node_id!r}")
        done = 1 if node.onboarding_state == "complete" else 0
        return OnboardingState(
            node_id=node_id,
            sections_done=dict.fromkeys(SECTION_KEYS, done),
            draft={},
            current_step=len(SECTION_KEYS),
        )

    def list_drafts(self, project_id: str | None = None) -> list[SupplyNode]:
        """Liste les noeuds encore en brouillon (``onboarding_state='draft'``).

        Args:
            project_id: si fourni, restreint au projet donne.

        Returns:
            Les noeuds brouillon, ordonnes par rang puis id (ordre du registre).
        """
        return [
            node
            for node in self._service.registry.list_nodes(project_id)
            if node.onboarding_state == "draft"
        ]

    def save_draft(self, node_id: str, step: int, payload: dict) -> None:
        """Ecrit le brouillon d'une section SANS valider (" enregistrer et quitter ").

        Seuls ``draft_json`` (section ``step``) et ``current_step`` bougent ;
        les sections validees restent intactes.

        Args:
            node_id: identifiant du noeud en cours d'onboarding.
            step: etape du wizard, dans [1, 4].
            payload: reponses partielles de la section, telles quelles.

        Raises:
            ValueError: si ``step`` sort de [1, 4].
            KeyError: si le noeud n'a pas de brouillon d'onboarding en base.
        """
        key = self._section_key(step)
        with self._lock:
            progress = self._progress_or_raise(node_id)
            draft = dict(progress["draft"])
            draft[key] = payload
            self._service.registry.save_onboarding(node_id, progress["sections_done"], draft, step)

    # ecriture des sections

    def save_section(
        self, node_id: str, step: int, payload: dict, operator_id: str = ""
    ) -> SectionResult:
        """Valide PUIS ecrit les entites reelles d'une section du wizard.

        En cas d'erreur de validation, RIEN n'est ecrit et les messages
        (francais) sont retournes. En cas de succes, ``sections_done[k]``
        passe a 1, le payload est conserve dans le brouillon (reprise) et
        l'etape courante avance d'un cran.

        Args:
            node_id: identifiant du noeud en cours d'onboarding.
            step: etape du wizard, dans [1, 4].
            payload: reponses de la section (formats du wizard UI).
            operator_id: operateur a l'origine de la saisie (audit).

        Returns:
            ``SectionResult(ok=True, errors=[])`` si tout est ecrit, sinon
            ``SectionResult(ok=False, errors=[...])`` sans aucune ecriture.

        Raises:
            ValueError: si ``step`` sort de [1, 4].
            KeyError: si le noeud est inconnu du registre.
        """
        key = self._section_key(step)
        with self._lock:
            node = self._service.registry.get_node(node_id)
            if node is None:
                raise KeyError(f"Nœud inconnu : {node_id!r}")
            if key == "identity":
                errors = self._apply_identity(node, payload, operator_id)
            elif key == "cdc":
                errors = self._apply_cdc(node, payload, operator_id)
            elif key == "kpis":
                errors = self._apply_kpis(node, payload, operator_id)
            else:
                errors = self._apply_ahp(node, payload, operator_id)
            if errors:
                return SectionResult(ok=False, errors=errors)
            progress = self._service.registry.get_onboarding(node_id)
            if progress is not None:
                sections_done = dict(progress["sections_done"])
                sections_done[key] = 1
                draft = dict(progress["draft"])
                draft[key] = payload
                next_step = min(step + 1, len(SECTION_KEYS))
                self._service.registry.save_onboarding(node_id, sections_done, draft, next_step)
            return SectionResult(ok=True, errors=[])

    # completion

    def completeness(self, node_id: str) -> tuple[int, int]:
        """Avancement de l'onboarding du noeud : ``(sections faites, 4)``.

        Un noeud ``complete`` (progression supprimee) repond ``(4, 4)``.

        Args:
            node_id: identifiant du noeud.

        Returns:
            Le couple ``(nombre de sections validees, nombre total de sections)``.

        Raises:
            KeyError: si AUCUN brouillon NI noeud n'existe pour cet id.
        """
        state = self.load(node_id)
        done = sum(1 for key in SECTION_KEYS if state.sections_done.get(key))
        return (done, len(SECTION_KEYS))

    def complete(self, node_id: str, operator_id: str = "") -> SectionResult:
        """Termine l'onboarding : exige les 4 sections faites, puis bascule le noeud.

        En cas de succes : ``onboarding_state='complete'`` (mutation auditee),
        suppression de la ligne ``onboarding_progress`` et reevaluation
        complete du reseau (``evaluate_all(persist=True)``). Idempotent : un
        noeud deja ``complete`` (sans progression) repond ``ok=True``.

        Args:
            node_id: identifiant du noeud en cours d'onboarding.
            operator_id: operateur a l'origine de la completion (audit).

        Returns:
            ``SectionResult(ok=True, errors=[])`` si le noeud est complete,
            sinon ``ok=False`` avec la liste francaise des sections restantes.

        Raises:
            KeyError: si le noeud est inconnu du registre, ou s'il n'a ni
                progression ni etat ``complete``.
        """
        with self._lock:
            registry = self._service.registry
            node = registry.get_node(node_id)
            if node is None:
                raise KeyError(f"Nœud inconnu : {node_id!r}")
            progress = registry.get_onboarding(node_id)
            if progress is None:
                if node.onboarding_state == "complete":
                    return SectionResult(ok=True, errors=[])
                raise KeyError(f"Aucun brouillon d'onboarding pour le nœud : {node_id!r}")
            missing = [
                _SECTION_LABELS[key]
                for key in SECTION_KEYS
                if not progress["sections_done"].get(key)
            ]
            if missing:
                return SectionResult(
                    ok=False,
                    errors=[
                        "Onboarding incomplet — sections restantes : " + ", ".join(missing) + "."
                    ],
                )
            self._service.mutations.update_node_fields(
                node_id,
                {"onboarding_state": "complete"},
                source=_SOURCE,
                operator_id=operator_id,
            )
            registry.delete_onboarding(node_id)
            self._service.evaluate_all(persist=True)
            return SectionResult(ok=True, errors=[])

    # sections (validation PUIS ecriture, jamais l'inverse)

    def _apply_identity(
        self, node: SupplyNode, payload: dict[str, Any], operator_id: str
    ) -> list[str]:
        """Section 1 : identite, type, tags (crees par nom) et connexions (arcs).

        Validations : nom non vide, gamma/beta dans [0, 1], cibles existantes,
        pas d'auto-connexion, type d'arc nominal/backup. Le rang du noeud
        devient ``1 + max(rang des cibles nominales)`` (0 sans cible nominale).

        Args:
            node: noeud en cours d'onboarding (etat registre).
            payload: ``{"name", "label", "location", "tag_names", "connections"}``.
            operator_id: operateur (audit).

        Returns:
            Liste des erreurs francaises ; vide si tout a ete ecrit.
        """
        registry = self._service.registry
        errors: list[str] = []
        name = str(payload.get("name") or "").strip()
        if not name:
            errors.append("Le nom du nœud est obligatoire.")
        connections: list[tuple[SupplyNode, float, float, ArcKind]] = []
        for position, raw in enumerate(payload.get("connections") or [], start=1):
            prefix = f"Connexion {position}"
            if not isinstance(raw, dict):
                errors.append(f"{prefix} : format invalide (objet attendu).")
                continue
            target_id = str(raw.get("target_id") or "")
            target = registry.get_node(target_id) if target_id else None
            if target_id == node.id:
                errors.append(f"{prefix} : auto-connexion interdite ({target_id!r}).")
                target = None
            elif target is None:
                errors.append(f"{prefix} : nœud cible inconnu ({target_id!r}).")
            gamma = _as_float_01(raw.get("gamma"), f"{prefix} : gamma", errors)
            beta = _as_float_01(raw.get("beta"), f"{prefix} : beta", errors)
            kind_raw = str(raw.get("kind") or "nominal")
            try:
                kind = ArcKind(kind_raw)
            except ValueError:
                errors.append(
                    f"{prefix} : type d'arc inconnu ({kind_raw!r}) —"
                    " « nominal » ou « backup » attendu."
                )
                continue
            if target is not None and gamma is not None and beta is not None:
                connections.append((target, gamma, beta, kind))
        if errors:
            return errors

        mutations = self._service.mutations
        mutations.update_node_fields(
            node.id,
            {
                "name": name,
                "label": str(payload.get("label") or node.label),
                "location": payload.get("location"),
            },
            source=_SOURCE,
            operator_id=operator_id,
        )
        mutations.set_node_tags(
            node.id,
            self._tag_ids_for(node.project_id or "", payload.get("tag_names") or []),
            source=_SOURCE,
            operator_id=operator_id,
        )
        for target, gamma, beta, kind in connections:
            arc = SupplyArc(
                source_id=node.id,
                target_id=target.id,
                gamma=gamma,
                beta=beta,
                kind_arc=kind,
            )
            mutations.upsert_arc(arc, source=_SOURCE, operator_id=operator_id)

        nominal_ranks = [
            target.rank for target, _g, _b, kind in connections if kind is ArcKind.NOMINAL
        ]
        rank = (1 + max(nominal_ranks)) if nominal_ranks else 0
        fresh = registry.get_node(node.id)
        if fresh is not None and fresh.rank != rank:
            fresh.rank = rank
            registry.save_node(fresh)
        cached = self._service.repo.get_node(node.id)
        if cached is not None and cached.rank != rank:
            cached.rank = rank
            self._service.repo.update_node(cached)
        return []

    def _tag_ids_for(self, project_id: str, tag_names: list[Any]) -> list[str]:
        """Resout des noms de tags en ids, en creant les tags manquants (uuid4).

        Les noms sont nettoyes (strip), dedoublonnes en conservant l'ordre,
        et apparies aux tags existants du projet par nom exact.

        Args:
            project_id: projet porteur de la taxonomie.
            tag_names: noms de tags saisis par l'operateur.

        Returns:
            Les ids de tags, dans l'ordre de saisie.
        """
        registry = self._service.registry
        existing = {tag.name: tag.id for tag in registry.list_tags(project_id)}
        tag_ids: list[str] = []
        cleaned = [str(name).strip() for name in tag_names]
        for tag_name in dict.fromkeys(name for name in cleaned if name):
            tag_id = existing.get(tag_name)
            if tag_id is None:
                tag = Tag(id=str(uuid.uuid4()), project_id=project_id, name=tag_name)
                registry.save_tag(tag)
                tag_id = tag.id
            tag_ids.append(tag_id)
        return tag_ids

    def _apply_cdc(self, node: SupplyNode, payload: dict[str, Any], operator_id: str) -> list[str]:
        """Section 2 : cahier des charges versionne + jalons dates.

        Validations : cdc compatible ``cdc_from_json``, au moins un jalon,
        noms non vides, ``deadline_ts > start_ts``. Ecritures : nouvelle
        version de ``spec_sheet`` (mutation auditee) et REMPLACEMENT des
        jalons du noeud (delete puis recreate - idempotent si on resauve).

        Args:
            node: noeud en cours d'onboarding.
            payload: ``{"cdc": dict, "milestones": [{name, kind, start_ts, deadline_ts}]}``.
            operator_id: operateur (audit).

        Returns:
            Liste des erreurs francaises ; vide si tout a ete ecrit.
        """
        errors: list[str] = []
        payload_json: str | None = None
        raw_cdc = payload.get("cdc")
        if not isinstance(raw_cdc, dict):
            errors.append("Cahier des charges invalide : objet JSON attendu.")
        else:
            try:
                payload_json = cdc_to_json(cdc_from_json(json.dumps(raw_cdc)))
            except (TypeError, ValueError) as exc:
                errors.append(f"Cahier des charges invalide : {exc}")

        raw_milestones = payload.get("milestones") or []
        if not raw_milestones:
            errors.append("Au moins un jalon est requis.")
        parsed: list[tuple[str, str, float, float]] = []
        for position, raw in enumerate(raw_milestones, start=1):
            prefix = f"Jalon {position}"
            if not isinstance(raw, dict):
                errors.append(f"{prefix} : format invalide (objet attendu).")
                continue
            milestone_name = str(raw.get("name") or "").strip()
            if not milestone_name:
                errors.append(f"{prefix} : le nom est obligatoire.")
            kind = str(raw.get("kind") or "livraison")
            start_ts = _as_float(raw.get("start_ts"), f"{prefix} : début (start_ts)", errors)
            deadline_ts = _as_float(
                raw.get("deadline_ts"), f"{prefix} : échéance (deadline_ts)", errors
            )
            if start_ts is not None and deadline_ts is not None and deadline_ts <= start_ts:
                errors.append(
                    f"{prefix} (« {milestone_name} ») : l'échéance doit être strictement"
                    f" postérieure au début (deadline_ts {deadline_ts} <= start_ts {start_ts})."
                )
                continue
            if milestone_name and start_ts is not None and deadline_ts is not None:
                parsed.append((milestone_name, kind, start_ts, deadline_ts))
        if errors or payload_json is None:
            return errors

        self._service.mutations.save_spec_sheet(
            node.id, payload_json, source=_SOURCE, operator_id=operator_id
        )
        registry = self._service.registry
        for old in registry.list_milestones(node.id):
            registry.delete_milestone(old.id)
        for position, (milestone_name, kind, start_ts, deadline_ts) in enumerate(parsed):
            registry.save_milestone(
                Milestone(
                    id=str(uuid.uuid4()),
                    node_id=node.id,
                    name=milestone_name,
                    kind=kind,
                    start_ts=start_ts,
                    deadline_ts=deadline_ts,
                    position=position,
                )
            )
        return []

    def _apply_kpis(self, node: SupplyNode, payload: dict[str, Any], operator_id: str) -> list[str]:
        """Section 3 : KPIs initiaux, via :meth:`MutationService.update_kpis`.

        La validation des bornes est celle de :class:`MutationService`
        (table ``KPI_CONSTRAINTS``) : son ``ValueError`` - qui liste TOUTES
        les valeurs invalides, rien n'etant alors ecrit - est restitue tel
        quel dans les erreurs.

        Args:
            node: noeud en cours d'onboarding.
            payload: ``{"bloc.champ": valeur}`` (None efface le champ).
            operator_id: operateur (audit).

        Returns:
            Liste des erreurs francaises ; vide si tout a ete ecrit.
        """
        try:
            self._service.mutations.update_kpis(
                node.id, dict(payload), source=_SOURCE, operator_id=operator_id
            )
        except ValueError as exc:
            return [str(exc)]
        return []

    def _apply_ahp(self, node: SupplyNode, payload: dict[str, Any], operator_id: str) -> list[str]:
        """Section 4 : premiere evaluation AHP du noeud.

        Construit l'evaluation via ``build_assessment`` puis REFUSE tout
        questionnaire incoherent (CR >= 0.10, seuil de Saaty) ; sinon
        l'evaluation est soumise (``submit_assessment``), qui pose la semaine
        ISO depuis l'horloge du projet et met a jour le Ud_local lisse.

        Args:
            node: noeud en cours d'onboarding.
            payload: ``{"comparisons": {"i-j": saaty}, "scores": [4 notes 1..9], "notes": str}``.
            operator_id: operateur (audit).

        Returns:
            Liste des erreurs francaises ; vide si l'evaluation est persistee.
        """
        errors: list[str] = []
        comparisons: dict[tuple[int, int], float] = {}
        raw_comparisons = payload.get("comparisons") or {}
        if not isinstance(raw_comparisons, dict):
            errors.append("Comparaisons AHP invalides : objet « i-j » -> jugement attendu.")
            raw_comparisons = {}
        for key, value in raw_comparisons.items():
            try:
                i_str, _, j_str = str(key).partition("-")
                comparisons[(int(i_str), int(j_str))] = float(value)
            except (TypeError, ValueError):
                errors.append(
                    f"Comparaison invalide : {key!r} -> {value!r}"
                    " (attendu « i-j » : jugement de Saaty)."
                )

        # " scores " et " criteria_scores " acceptes (parse_ahp des form-builders emet " criteria_scores " ; le contrat historique disait " scores ").
        raw_scores = payload.get("scores") or payload.get("criteria_scores") or []
        scores: list[float] = []
        for position, value in enumerate(raw_scores, start=1):
            number = _as_float(value, f"Note {position}", errors)
            if number is None:
                continue
            if not 1.0 <= number <= 9.0:
                errors.append(f"Note {position} hors [1, 9] : {number}.")
                continue
            scores.append(number)
        if len(raw_scores) != len(CRITERIA):
            errors.append(f"{len(CRITERIA)} notes de critères attendues (reçu {len(raw_scores)}).")
        if errors:
            return errors

        try:
            assessment = self._service.build_assessment(
                node_id=node.id,
                project_id=node.project_id or "",
                operator_id=operator_id,
                comparisons=comparisons,
                criteria_scores=scores,
                notes=str(payload.get("notes") or ""),
            )
        except ValueError as exc:
            return [f"Évaluation AHP invalide : {exc}"]
        if assessment.consistency_ratio >= CONSISTENCY_THRESHOLD:
            return [
                f"Jugements AHP incohérents : ratio de cohérence"
                f" {assessment.consistency_ratio:.3f} >= seuil {CONSISTENCY_THRESHOLD:.2f}"
                " — révisez vos comparaisons."
            ]
        self._service.submit_assessment(assessment)
        return []

    # aides internes

    @staticmethod
    def _section_key(step: int) -> str:
        """Cle de section correspondant a une etape du wizard.

        Args:
            step: etape, dans [1, 4].

        Returns:
            La cle de :data:`SECTION_KEYS` correspondante.

        Raises:
            ValueError: si ``step`` sort de [1, 4].
        """
        if not 1 <= step <= len(SECTION_KEYS):
            raise ValueError(f"Étape de wizard hors [1, {len(SECTION_KEYS)}] : {step}")
        return SECTION_KEYS[step - 1]

    def _progress_or_raise(self, node_id: str) -> dict[str, Any]:
        """Progression d'onboarding du noeud, ou KeyError francaise si absente.

        Args:
            node_id: identifiant du noeud.

        Returns:
            La ligne ``onboarding_progress`` deserialisee (dict de la couche db).

        Raises:
            KeyError: si le noeud n'a pas de brouillon d'onboarding en base.
        """
        progress = self._service.registry.get_onboarding(node_id)
        if progress is None:
            raise KeyError(f"Aucun brouillon d'onboarding pour le nœud : {node_id!r}")
        return progress
