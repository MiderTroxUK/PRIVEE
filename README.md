# SupplyScore

Transforme des données supply chain en un **score d'alignement** entre le besoin déclaré et la réalité opérationnelle, sur une chaîne multi-rangs (client final rang 0 → fournisseurs profonds rang N).

- **Ud** — urgence déclarée : questionnaire humain hebdomadaire (AHP, Saaty 1977, CR < 0.10)
- **Ur** — urgence opérationnelle réelle : modélisée depuis les KPIs (temps, capacité, OEE, risque, coût, CO2)
- **A** — adéquation Ud/Ur : pénalité asymétrique Prospect Theory (Kahneman-Tversky), le **risque caché H** (sous-estimation) est pénalisé plus fort que la **fausse urgence F** (sur-estimation)
- **Propagation sur DAG** : le besoin déclaré descend (rang 0 → N), le risque réel remonte (rang N → 0) ; les statuts de tâche (terminée/abandonnée) propagent leur choc sur toute la chaîne

## Démarrage rapide

```powershell
# installer (une fois)
uv venv .venv
$env:UV_LINK_MODE='copy'; uv pip install -e ".[dev]" --python .venv\Scripts\python.exe

# lancer avec des données de démonstration (TEST uniquement, générées aléatoirement)
.venv\Scripts\python.exe run_app.py --demo

# -> http://127.0.0.1:8050
```

Options : `--db-dir` (dossier des bases SQLite, défaut `data_store`), `--port`, `--debug`.

## Pages de l'application

| Page | Rôle |
|---|---|
| **Projets** (`/`) | Créer/sélectionner un projet, ajouter un client/fournisseur de rang quelconque, changer le statut d'une tâche (le choc est propagé), générer une démo |
| **Questionnaire** (`/questionnaire`) | Évaluation hebdomadaire : comparaisons AHP par paires, notes des 4 critères, saisie des KPIs opérationnels — calcule Ud en direct avec contrôle de cohérence (CR) |
| **Dashboard** (`/dashboard`) | DAG coloré par adéquation A, tableau détaillé Ud/Ur/A/F/H par nœud, évolution temporelle |
| **Simulation** (`/simulation`) | Scénario catastrophe what-if : choc sur un nœud → ΔUr propagé visualisé, sans persistance ; ou application réelle d'un statut |

## Architecture (POO)

```
supplyscore/
  domain/    modèles partagés : SupplyNode, SupplyArc, KPIBundle, Project, AHPAssessment, UrgencyState
  core/      AHP -> Ud · UrModel (6 blocs KPI + OR probabiliste pondéré) -> Ur · AdequationEngine -> A, F, H
  graph/     GraphRepository (interface) · InMemoryGraphRepository (networkx) · Neo4jGraphRepository (option) · PropagationEngine
  data/      RegistryDatabase (graphe partagé) · ClientDatabase (une base SQLite PAR client) · RandomSupplyChainGenerator (test uniquement)
  services/  SupplyScoreService : façade orchestrant le pipeline complet
  web_ui/    application Dash (factory create_app, 4 pages, composants réutilisables)
run_app.py   point d'entrée
tests/       144 tests (unitaires + intégration + smoke UI)
```

### Modèle mathématique

1. **Ud local** : AHP 4 critères (impact opérationnel, fenêtre temporelle, dépendances aval, récupérabilité) ; Ud = (Σ wᵢ·sᵢ − 1)/8 ∈ [0,1] ; lissage EMA entre semaines (ρ = 0.3).
2. **Ur local** : u_time (probabilité de retard P(L > d−t), loi normale), u_cap, u_perf (1−OEE), u_risk (enrichi expositions env./politique), u_cost, u_co2 — agrégés par `Ur = 1 − Π(1−uₘ)^ωₘ`. Statut : terminée → 0, abandonnée → 1.
3. **Propagation** : `Ud_i = 1 − (1−Ud_loc)·Π(1−γ·Ud_client)` (descendante) ; `Ur_i = 1 − (1−Ur_loc)·Π(1−β·Ur_fournisseur)` (montante, ordre topologique).
4. **Adéquation** : A = 100·norm(exp(−λ₊·H^α − λ₋·F^α)) avec λ₊ = 2.25 > λ₋ = 1.0 (gouvernance : le danger invisible prime sur la panique).

## Neo4j (optionnel)

Par défaut le graphe vit en mémoire (networkx) et est persisté dans SQLite. Pour brancher Neo4j :

```powershell
uv pip install -e ".[neo4j]" --python .venv\Scripts\python.exe
```

puis instancier `Neo4jGraphRepository(uri, user, password)` et le passer à `SupplyScoreService(repo=...)`.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

## Avertissement données

`RandomSupplyChainGenerator` et l'option `--demo` produisent des données **simulées, destinées aux tests et démos uniquement** — jamais à des décisions de production.
