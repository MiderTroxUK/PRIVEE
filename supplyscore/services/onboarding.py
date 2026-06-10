"""Service d'onboarding — wizard 4 sections, brouillon persisté EN BASE.

Machine à états du wizard (source de vérité : table ``onboarding_progress``) :

- ``start_draft`` → le nœud est créé IMMÉDIATEMENT (``onboarding_state='draft'``,
  rang 0, aucun arc) et la progression est initialisée (sections à 0,
  brouillon vide, étape 1) ;
- ``save_section(k)`` → VALIDE puis écrit les entités réelles et pose
  ``sections_done[k] = 1`` ; en cas d'erreur de validation, RIEN n'est écrit
  et la liste des erreurs (messages français) est retournée ;
- ``save_draft(k)`` → écrit ``draft_json`` SANS valider (« enregistrer le
  brouillon et quitter ») ;
- ``complete()`` → exige les 4 sections faites, pose
  ``onboarding_state='complete'``, supprime la progression et relance
  ``evaluate_all(persist=True)``.

Sections : **1** identité + type + tags + connexions ; **2** cahier des
charges + jalons ; **3** KPIs initiaux ; **4** première évaluation AHP.
Toutes les écritures métier passent par :class:`MutationService`
(``source='onboarding'``) ; les entités sans mutation auditée (tags créés par
nom, jalons recréés en bloc) passent par le registre.
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

#: Clés des 4 sections du wizard, dans l'ordre des étapes (étape = index + 1).
SECTION_KEYS: tuple[str, str, str, str] = ("identity", "cdc", "kpis", "ahp")

#: Libellés français des sections (messages d'erreur de :meth:`OnboardingService.complete`).
_SECTION_LABELS: dict[str, str] = {
    "identity": "identité",
    "cdc": "cahier des charges",
    "kpis": "KPIs",
    "ahp": "évaluation AHP",
}

#: Origine posée sur toutes les mutations du wizard (journal d'audit).
_SOURCE = "onboarding"


@dataclass(frozen=True)
class OnboardingState:
    """État courant du wizard d'un nœud, tel que persisté en base."""

    #: Identifiant du nœud en cours d'onboarding.
    node_id: str
    #: Avancement par section : ``{"identity": 0|1, "cdc": 0|1, "kpis": 0|1, "ahp": 0|1}``.
    sections_done: dict[str, int]
    #: Réponses partielles NON validées, par section : ``{"identity": {...}, ...}``.
    draft: dict
    #: Étape courante du wizard, dans [1, 4].
    current_step: int


@dataclass(frozen=True)
class SectionResult:
    """Résultat d'une tentative d'écriture de section (ou de complétion)."""

    #: True si la section a été validée ET écrite.
    ok: bool
    #: Messages d'erreur en français ; liste vide si ``ok``.
    errors: list[str]


def _as_float(value: Any, label: str, errors: list[str]) -> float | None:
    """Convertit ``value`` en float, ou ajoute une erreur française à ``errors``.

    Args:
        value: valeur brute issue du payload (None = manquante).
        label: préfixe français du message d'erreur (ex. « Jalon 2 : début »).
        errors: liste d'erreurs alimentée en place.

    Returns:
        La valeur convertie, ou None si elle est manquante ou non numérique.
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
    """Comme :func:`_as_float`, avec borne supplémentaire [0, 1].

    Args:
        value: valeur brute issue du payload.
        label: préfixe français du message d'erreur (ex. « Connexion 1 : gamma »).
        errors: liste d'erreurs alimentée en place.

    Returns:
        La valeur convertie si elle est dans [0, 1], None sinon.
    """
    number = _as_float(value, label, errors)
    if number is not None and not 0.0 <= number <= 1.0:
        errors.append(f"{label} : {number} hors [0, 1].")
        return None
    return number


class OnboardingService:
    """Wizard d'onboarding d'un nœud en 4 sections, brouillon persisté en base.

    S'appuie sur la façade :class:`SupplyScoreService` : le registre porte la
    table ``onboarding_progress`` (source de vérité de la machine à états),
    les écritures métier passent par :class:`MutationService`
    (``source='onboarding'``) et la complétion relance le pipeline complet
    (``evaluate_all(persist=True)``).

    Thread-safety : les méthodes mutantes prennent ``self._lock`` (RLock) pour
    sérialiser les cycles lecture-validation-écriture du wizard.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service d'onboarding au-dessus de la façade.

        Args:
            service: façade applicative (registre, mutations, horloges, pipeline).
        """
        self._service = service
        self._lock = threading.RLock()

    # --- cycle de vie du brouillon -----------------------------------------------

    def start_draft(self, project_id: str, name: str, label: str = "Supplier") -> str:
        """Crée IMMÉDIATEMENT le nœud en brouillon et initialise sa progression.

        Le nœud naît avec ``onboarding_state='draft'``, rang 0 et aucun arc ;
        la ligne ``onboarding_progress`` démarre à l'étape 1, sections à 0,
        brouillon vide.

        Args:
            project_id: projet de rattachement du nœud.
            name: nom du nœud (modifiable en section 1).
            label: type du nœud (Supplier, Factory, Workshop...).

        Returns:
            L'identifiant (uuid4) du nœud créé.
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
        """Restitue l'état du wizard depuis la table ``onboarding_progress``.

        Si la progression a été supprimée (onboarding terminé) mais que le
        nœud existe, un état synthétique est reconstruit : 4 sections faites
        si le nœud est ``complete``, 0 sinon.

        Args:
            node_id: identifiant du nœud.

        Returns:
            L'état courant du wizard (sections faites, brouillon, étape).

        Raises:
            KeyError: si AUCUN brouillon NI nœud n'existe pour cet id.
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
        """Liste les nœuds encore en brouillon (``onboarding_state='draft'``).

        Args:
            project_id: si fourni, restreint au projet donné.

        Returns:
            Les nœuds brouillon, ordonnés par rang puis id (ordre du registre).
        """
        return [
            node
            for node in self._service.registry.list_nodes(project_id)
            if node.onboarding_state == "draft"
        ]

    def save_draft(self, node_id: str, step: int, payload: dict) -> None:
        """Écrit le brouillon d'une section SANS valider (« enregistrer et quitter »).

        Seuls ``draft_json`` (section ``step``) et ``current_step`` bougent ;
        les sections validées restent intactes.

        Args:
            node_id: identifiant du nœud en cours d'onboarding.
            step: étape du wizard, dans [1, 4].
            payload: réponses partielles de la section, telles quelles.

        Raises:
            ValueError: si ``step`` sort de [1, 4].
            KeyError: si le nœud n'a pas de brouillon d'onboarding en base.
        """
        key = self._section_key(step)
        with self._lock:
            progress = self._progress_or_raise(node_id)
            draft = dict(progress["draft"])
            draft[key] = payload
            self._service.registry.save_onboarding(node_id, progress["sections_done"], draft, step)

    # --- écriture des sections ------------------------------------------------------

    def save_section(
        self, node_id: str, step: int, payload: dict, operator_id: str = ""
    ) -> SectionResult:
        """Valide PUIS écrit les entités réelles d'une section du wizard.

        En cas d'erreur de validation, RIEN n'est écrit et les messages
        (français) sont retournés. En cas de succès, ``sections_done[k]``
        passe à 1, le payload est conservé dans le brouillon (reprise) et
        l'étape courante avance d'un cran.

        Args:
            node_id: identifiant du nœud en cours d'onboarding.
            step: étape du wizard, dans [1, 4].
            payload: réponses de la section (formats du wizard UI).
            operator_id: opérateur à l'origine de la saisie (audit).

        Returns:
            ``SectionResult(ok=True, errors=[])`` si tout est écrit, sinon
            ``SectionResult(ok=False, errors=[...])`` sans aucune écriture.

        Raises:
            ValueError: si ``step`` sort de [1, 4].
            KeyError: si le nœud est inconnu du registre.
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

    # --- complétion ----------------------------------------------------------------

    def completeness(self, node_id: str) -> tuple[int, int]:
        """Avancement de l'onboarding du nœud : ``(sections faites, 4)``.

        Un nœud ``complete`` (progression supprimée) répond ``(4, 4)``.

        Args:
            node_id: identifiant du nœud.

        Returns:
            Le couple ``(nombre de sections validées, nombre total de sections)``.

        Raises:
            KeyError: si AUCUN brouillon NI nœud n'existe pour cet id.
        """
        state = self.load(node_id)
        done = sum(1 for key in SECTION_KEYS if state.sections_done.get(key))
        return (done, len(SECTION_KEYS))

    def complete(self, node_id: str, operator_id: str = "") -> SectionResult:
        """Termine l'onboarding : exige les 4 sections faites, puis bascule le nœud.

        En cas de succès : ``onboarding_state='complete'`` (mutation auditée),
        suppression de la ligne ``onboarding_progress`` et réévaluation
        complète du réseau (``evaluate_all(persist=True)``). Idempotent : un
        nœud déjà ``complete`` (sans progression) répond ``ok=True``.

        Args:
            node_id: identifiant du nœud en cours d'onboarding.
            operator_id: opérateur à l'origine de la complétion (audit).

        Returns:
            ``SectionResult(ok=True, errors=[])`` si le nœud est complété,
            sinon ``ok=False`` avec la liste française des sections restantes.

        Raises:
            KeyError: si le nœud est inconnu du registre, ou s'il n'a ni
                progression ni état ``complete``.
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

    # --- sections (validation PUIS écriture, jamais l'inverse) -----------------------

    def _apply_identity(
        self, node: SupplyNode, payload: dict[str, Any], operator_id: str
    ) -> list[str]:
        """Section 1 : identité, type, tags (créés par nom) et connexions (arcs).

        Validations : nom non vide, gamma/beta dans [0, 1], cibles existantes,
        pas d'auto-connexion, type d'arc nominal/backup. Le rang du nœud
        devient ``1 + max(rang des cibles nominales)`` (0 sans cible nominale).

        Args:
            node: nœud en cours d'onboarding (état registre).
            payload: ``{"name", "label", "location", "tag_names", "connections"}``.
            operator_id: opérateur (audit).

        Returns:
            Liste des erreurs françaises ; vide si tout a été écrit.
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
        """Résout des noms de tags en ids, en créant les tags manquants (uuid4).

        Les noms sont nettoyés (strip), dédoublonnés en conservant l'ordre,
        et appariés aux tags existants du projet par nom exact.

        Args:
            project_id: projet porteur de la taxonomie.
            tag_names: noms de tags saisis par l'opérateur.

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
        """Section 2 : cahier des charges versionné + jalons datés.

        Validations : cdc compatible ``cdc_from_json``, au moins un jalon,
        noms non vides, ``deadline_ts > start_ts``. Écritures : nouvelle
        version de ``spec_sheet`` (mutation auditée) et REMPLACEMENT des
        jalons du nœud (delete puis recreate — idempotent si on resauve).

        Args:
            node: nœud en cours d'onboarding.
            payload: ``{"cdc": dict, "milestones": [{name, kind, start_ts, deadline_ts}]}``.
            operator_id: opérateur (audit).

        Returns:
            Liste des erreurs françaises ; vide si tout a été écrit.
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
        (table ``KPI_CONSTRAINTS``) : son ``ValueError`` — qui liste TOUTES
        les valeurs invalides, rien n'étant alors écrit — est restitué tel
        quel dans les erreurs.

        Args:
            node: nœud en cours d'onboarding.
            payload: ``{"bloc.champ": valeur}`` (None efface le champ).
            operator_id: opérateur (audit).

        Returns:
            Liste des erreurs françaises ; vide si tout a été écrit.
        """
        try:
            self._service.mutations.update_kpis(
                node.id, dict(payload), source=_SOURCE, operator_id=operator_id
            )
        except ValueError as exc:
            return [str(exc)]
        return []

    def _apply_ahp(self, node: SupplyNode, payload: dict[str, Any], operator_id: str) -> list[str]:
        """Section 4 : première évaluation AHP du nœud.

        Construit l'évaluation via ``build_assessment`` puis REFUSE tout
        questionnaire incohérent (CR >= 0.10, seuil de Saaty) ; sinon
        l'évaluation est soumise (``submit_assessment``), qui pose la semaine
        ISO depuis l'horloge du projet et met à jour le Ud_local lissé.

        Args:
            node: nœud en cours d'onboarding.
            payload: ``{"comparisons": {"i-j": saaty}, "scores": [4 notes 1..9], "notes": str}``.
            operator_id: opérateur (audit).

        Returns:
            Liste des erreurs françaises ; vide si l'évaluation est persistée.
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

        # « scores » et « criteria_scores » acceptés (parse_ahp des form-builders
        # émet « criteria_scores » ; le contrat historique disait « scores »).
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

    # --- aides internes ---------------------------------------------------------------

    @staticmethod
    def _section_key(step: int) -> str:
        """Clé de section correspondant à une étape du wizard.

        Args:
            step: étape, dans [1, 4].

        Returns:
            La clé de :data:`SECTION_KEYS` correspondante.

        Raises:
            ValueError: si ``step`` sort de [1, 4].
        """
        if not 1 <= step <= len(SECTION_KEYS):
            raise ValueError(f"Étape de wizard hors [1, {len(SECTION_KEYS)}] : {step}")
        return SECTION_KEYS[step - 1]

    def _progress_or_raise(self, node_id: str) -> dict[str, Any]:
        """Progression d'onboarding du nœud, ou KeyError française si absente.

        Args:
            node_id: identifiant du nœud.

        Returns:
            La ligne ``onboarding_progress`` désérialisée (dict de la couche db).

        Raises:
            KeyError: si le nœud n'a pas de brouillon d'onboarding en base.
        """
        progress = self._service.registry.get_onboarding(node_id)
        if progress is None:
            raise KeyError(f"Aucun brouillon d'onboarding pour le nœud : {node_id!r}")
        return progress
