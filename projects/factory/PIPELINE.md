# PIPELINE.md — Orchestrateur bout-en-bout HÉLIOS v7 (U14)

`run_pipeline.py` enchaîne, dans un seul dossier de travail, toutes les étapes de
la campagne HÉLIOS v7 (prévision par rollouts Monte Carlo + prescription
contrefactuelle honnête) en appelant les CLI FIGÉES des unités sœurs U4-U13 et
U15-U18 comme sous-processus. Il n'importe jamais leur code : il ne connaît que
leurs contrats de ligne de commande. Ce document décrit le flux, les 32
décisions du plan, les coûts mesurés et ce qu'il reste à faire manuellement.

Ce worktree ne contient AUCUNE des unités sœurs (U14 est l'orchestrateur, codé
contre leurs contrats gelés avant qu'elles n'existent ici) : toute exécution
réelle s'arrêtera à la première étape dont le script est absent, avec un
message du type `maillon manquant : U4 — projects/simu_semiconducteurs/scenario/variants.py`.
C'est le comportement ATTENDU et testé (voir « Recette e2e » plus bas) — pas un
bug de ce module.

## 1. Schéma de flux

```
opendata (U13, optionnelle — sautée si opendata/MANIFEST.md absent)
   │
   ▼
variants (U4) ────────────────────────────┐
   │                                       │
   ▼                                       ▼
helios_runs (U5, // par variante)    random_chains (U6, // par chaîne)
   │                                       │
   └──────────────────┬────────────────────┘
                       ▼
              llm_traces (U7, optionnelle — sautée si --llm-runs 0)
                       │
                       ▼
                 t1_refit (U7 behavior_model.py)
                       │
         verdict RETENU │ NON RETENU → amplified_runs sautée (repli T1 compté)
                       ▼
        amplified_runs (U5 + déclarant RidgeDeclarant, // par variante)
                       │
                       ▼
                  dataset (U8 build_dataset.py)
                       │
                       ▼
        interventions_extract (U8 build_dataset.py --interventions)
                       │
                       ▼
        action_effects (U17 fit_action_effects.py --validate)
                       │
              PORTE CAUSALE (D32) : --out pointe un dossier de STAGING
                       │
          PASS ────────┼──────── FAIL / indéterminé
           │                              │
   copié dans <work>/models/       reste en staging, PAS publié
           │                              │
           └──────────────┬───────────────┘
                           ▼
                   train (U10, TOUJOURS publié dans <work>/models/)
                           │
                           ▼
        smoke : chaîne fraîche (U6, graine réservée) + predict (U11)
                + insights (U12) — absence tolérée, statut "partiel"
```

## 2. Étapes, unité responsable, contrat CLI exact

| Étape | Unité | Commande (contrat gelé) |
|---|---|---|
| `opendata` | U13 | `opendata/fetch_opendata.py --all` (sautée si `opendata/MANIFEST.md` absent) |
| `variants` | U4 | `scenario/variants.py --seeds 1..N --out <work>/prepared_variants/` |
| `helios_runs` | U5 | `scripts/run_campaign.py --prepared <variant_dir> --out <work>/runs/ --seed S [--rollout]` |
| `random_chains` | U6 | `run_random_campaign.py --chains 1 --weeks 18 --seed S --out <work>/runs/ --tier T [--rollout]` |
| `llm_traces` | U7 | `llm_farm.py --runs-dir <work>/runs_llm/ --out <work>/traces_t2.jsonl --model haiku --max-calls N` |
| `t1_refit` | U7 | `analysis/behavior_model.py` (verdict RETENU/NON RETENU imprimé, sans argument) |
| `amplified_runs` | U5+U7 | idem `helios_runs` + `--behavior projects.factory.declarants:RidgeDeclarant` |
| `dataset` | U8 | `build_dataset.py --runs <work>/runs/ --out <work>/dataset.csv --append` |
| `interventions_extract` | U8 | `build_dataset.py --runs <work>/runs/ --interventions --out <work>/interventions.csv` |
| `action_effects` | U17 | `fit_action_effects.py --interventions <work>/interventions.csv --out <staging> --validate` |
| `train` | U10 | `train_predictor.py --dataset <work>/dataset.csv --out <work>/models/ [--fast]` |
| `smoke` | U6+U11+U12 | `run_random_campaign.py --chains 1 --weeks 6 --seed 9000000 ...` puis `-m supplyscore.tools.predict` / `.insights` |

Les scripts eux-mêmes ne sont jamais importés — uniquement appelés en
sous-processus via `.venv\Scripts\python.exe` (résolu par `sys.executable`, donc
toujours le même interpréteur que celui qui a lancé l'orchestrateur).

## 3. Étapes optionnelles et repli

- **opendata (U13)** : la SEULE étape dont l'unité entière peut manquer sans
  bloquer le pipeline. Condition de saut : `projects/factory/opendata/MANIFEST.md`
  absent (le manifeste épinglé est livré AVEC le script par U13 — son absence
  vaut absence de U13). Toutes les autres étapes appliquent la règle stricte :
  script absent = échec propre nommant l'unité, pipeline interrompu.
- **llm_traces (U7 farm)** : sautée si `--llm-runs` résout à 0 (défaut du
  profil `default`). `--full`/`--xl` mettent 20 par défaut, surchageable.
- **t1_refit** : sautée (« repli T1 compté ») si `llm_traces` n'a pas terminé
  en `ok` — sans traces T2, il n'y a rien à refitter.
- **amplified_runs** : sautée si le verdict de `t1_refit` n'est pas exactement
  `"RETENU"`. Aucun découplage supplémentaire n'est proposé : soit le
  déclarant ridge est jugé fidèle et amplifie le dataset, soit le pipeline
  s'en passe entièrement.
- **smoke (predict/insights)** : U11/U12 absents (ou code de sortie non nul
  contenant `No module named`) sont TOLÉRÉS — l'étape se termine en statut
  `"partiel"`, jamais en échec bloquant, puisque tous les artefacts utiles ont
  déjà été publiés par les étapes précédentes.

## 4. Porte de validation causale (D32)

`fit_action_effects.py --validate` (U17) ne reçoit JAMAIS `<work>/models/`
directement comme `--out` : l'orchestrateur pointe un dossier
`staging_action_effects/` et lit le verdict global PASS/FAIL dans sa sortie
(ligne contenant « global », ou à défaut la dernière occurrence PASS/FAIL —
heuristique documentée en §7, à vérifier contre la sortie réelle de U17).

- **PASS** : le contenu du staging est copié (fusion, `shutil.copytree(...,
  dirs_exist_ok=True)`) dans `<work>/models/` — l'artefact d'effets causaux
  devient disponible à côté de l'artefact prédictif.
- **FAIL ou indéterminé** : RIEN n'est copié. L'artefact reste dans
  `staging_action_effects/`, jamais publié. Un message FR explicite la
  raison. **L'artefact prédictif (U10) est TOUJOURS publié** à l'étape
  suivante, indépendamment du verdict — seule la couche prescriptive causale
  est conditionnée, jamais la prévision.

C'est l'implémentation directe de D32 : une recommandation d'action ne doit
jamais s'appuyer sur un estimateur causal qui a échoué sa propre batterie de
validation (couverture des IC, biais, taux de reco correcte, regret
décisionnel, écart au naïf, confusion latente — cf. §6, D32).

## 5. Reprise sur panne — `pipeline_state.json`

Écrit dans `<work>/pipeline_state.json` (écriture atomique : fichier temporaire
puis remplacement, jamais de JSON tronqué en cas d'interruption). Schéma :

```json
{
  "schema_version": 1,
  "profile": "default|full|xl",
  "created_at": "...", "updated_at": "...",
  "blocked_stage": "variants",
  "stages": {
    "<nom_étape>": {
      "status": "ok|sautee|echec|bloque|partiel",
      "detail": "...",
      "done_items": ["1", "2", "..."],
      "total": 5,
      "duration_s": 12.3,
      "finished_at": "..."
    }
  }
}
```

- Statuts : `ok` (réussie, saute au relancement) ; `sautee` (condition
  optionnelle non remplie — réévaluée à CHAQUE lancement, pas figée) ;
  `echec` (a échoué, posé par l'étape avant de lever) ; `bloque` (posé par le
  point d'entrée quand une étape interrompt le pipeline — nom de l'étape
  aussi dans `blocked_stage`) ; `partiel` (smoke uniquement — cœur fait,
  sous-partie tolérée manquante).
- Étapes parallélisées (`helios_runs`, `random_chains`, `amplified_runs`) :
  `done_items` liste les clés déjà terminées (numéro de graine / index de
  chaîne) ; l'état est réécrit après CHAQUE item réussi — un pool tué en
  cours de route ne refait, au relancement, que ce qui manque encore. Un item
  qui échoue n'arrête pas les autres déjà soumis ; l'étape n'est déclarée en
  échec qu'après que le lot entier ait fini.
- `--reset` supprime le fichier avant de démarrer (repart de zéro).
- Changer de profil (`default`→`--full`→`--xl`) sur un `--work` existant SANS
  `--reset` déclenche un avertissement (état conservé, mais les étapes déjà
  `ok` ne sont PAS rejouées aux nouveaux volumes) — `--reset` est la seule
  manière propre de changer de profil.
- Étapes non parallélisées (`dataset`, `interventions_extract`,
  `action_effects`, `train`, `opendata`, `llm_traces`, `t1_refit`) : reprise
  au niveau de l'étape entière (`ok` → sautée intégralement au relancement).
  `build_dataset.py --append` : en cas d'échec PARTIEL (processus tué en plein
  écriture), l'orchestrateur ne tente pas de déduplication — c'est la
  responsabilité de U8 de rendre `--append` idempotent ou de documenter le
  contraire.

## 6. Les 32 décisions du plan (une ligne chacune)

- D1 AUC Mann-Whitney numpy cœur
- D2 bootstrap par grappes
- D3 Δℓ jumeau ε log-survie
- D4 compute_ur_batch vectorisé
- D5 criticité probabiliste
- D6 DGP versionné + QMC Sobol
- D7 déclarants 3 tiers via claude -p
- D8 rollouts d'ensemble + EMOS primaire
- D9 issue = définition CalibrationService
- D10 éval 3 axes
- D11 artefact JSON numpy
- D12 MIN_HISTORY_WEEKS=4
- D13 labels = événements injectés
- D14 protocole gelé intouchable
- D15 une seule unité pyproject
- D16 data.gouv découverte MCP / ingestion API épinglée
- D17 insights à règles sans LLM
- D18′ CRN = effet selon le modèle, trois effets étiquetés
- D19 ActionSpec double application sim/réel
- D20′ Beta-Binomial + propensity/IPW-DR/E-value
- D21 opérateur synthétique confondu sur le latent
- D22 valeur = perte évitée − coût − risque secondaire
- D23 niveau de preuve obligatoire
- D24 relance en vagues, modèles mixtes
- D25 label = résultat opérationnel, jamais l'état de risque
- D26 p0/p1/ΔU/P(Δ>0)/P(résolution) séparés
- D27 trois posteriors + badge robustesse
- D28 coûts structurés sinon « classement heuristique »
- D29 P(exécution) facteur explicite
- D30 portefeuille global sous contraintes
- D31 incertitude décomposée mc/param/action/modèle
- D32 batterie de validation causale

U14 met concrètement en œuvre D32 (porte causale, §4) et D24 (relance en
vagues — ce pipeline EST l'outil qui exécute les vagues une fois toutes les
unités intégrées).

## 7. Hypothèses d'intégration à vérifier

U14 a été codé AVANT que les scripts réels de U4-U13/U15-U18 n'existent dans
ce worktree, contre leurs seuls contrats de ligne de commande. Certains
détails ne sont PAS couverts par ces contrats et ont demandé une convention
côté orchestrateur — à confirmer/ajuster une fois les unités réelles
intégrées :

1. **Découverte des dossiers de variantes** : chaque sous-dossier immédiat de
   `<work>/prepared_variants/` est traité comme une variante, triés par nom,
   appariés aux graines HÉLIOS 1..N dans cet ordre (`_variant_dirs` dans
   `run_pipeline.py`). Si U4 nomme ses dossiers autrement qu'un tri stable
   1..N, revoir cette fonction.
2. **Plages de graines** (choisies pour ne jamais se chevaucher) : variantes
   et `helios_runs` = 1..N ; `random_chains` = `--base-seed`..+M-1 (défaut
   1000) ; `amplified_runs` = 500 000+i ; `smoke` = 9 000 000 (réservée,
   jamais utilisée à l'entraînement, même au profil `--xl` à 2000 chaînes).
3. **Verdict T1** (`_parse_t1_verdict`) : recherche ligne par ligne de « NON
   RETENU » puis « RETENU » dans stdout+stderr de `behavior_model.py`.
4. **Verdict global U17** (`_parse_global_verdict`) : ligne contenant
   « global » (insensible à la casse) portant PASS/FAIL ; à défaut, dernière
   occurrence de PASS/FAIL dans la sortie complète.
5. **Découverte db-dir/projet du smoke** (`_discover_db_project`) : cherche
   un `*.json` sous `runs_smoke/` avec une clé de dossier
   (`db_dir`|`db_path`|`database`) et une clé de projet
   (`project_id`|`project`) ; à défaut, un fichier `.sqlite` UNIQUE interrogé
   via `SELECT id FROM projects ORDER BY rowid DESC LIMIT 1` (schéma registre
   SupplyScore standard).
6. **`amplified_runs`** n'est pas un contrat gelé nommé comme tel dans le
   plan : c'est la ré-exécution de U5 sur les MÊMES dossiers de variantes
   que `helios_runs`, avec `--behavior projects.factory.declarants:RidgeDeclarant`
   (le seul point du contrat U5 qui s'y prête), gardée par le verdict T1.

Aucune de ces hypothèses n'affecte les CONTRATS eux-mêmes (arguments,
chemins) : elles ne portent que sur la manière dont l'orchestrateur DÉCOUVRE
des artefacts produits par des scripts dont l'interface de sortie n'est pas
figée dans le plan.

## 8. Profils

| Profil | Variantes | Chaînes | Tier | Rollout | LLM | Entraînement |
|---|---|---|---|---|---|---|
| `default` | 5 | 5 | 0 | non | 0 | `--fast` |
| `--full` | 60 | 150 | 0 | oui | 20 | complet |
| `--xl` | 60 | 2000 | 0 | oui | 20 | complet |

`--llm-runs`, `--tier`, `--max-workers`, `--base-seed` surchargent
individuellement la valeur du profil actif.

## 9. Table de coûts (mesures empiriques du plan)

| Volume | Temps séquentiel | Note |
|---|---|---|
| 1 campagne (HÉLIOS ou chaîne) | ~30 s | mesure empirique du plan v7 |
| 350 campagnes | ~3 h | ordre de grandeur du profil `--full` |
| 2000 campagnes | ~18 h | profil `--xl` (chaînes) |
| Rollouts d'ensemble activés | +0.5 à 1 jour | surcoût documenté, non recalculé par le pipeline |

Avec W travailleurs parallèles (défaut `os.cpu_count() - 1`), le temps mesuré
se rapproche de `temps_séquentiel / W` pour `helios_runs`/`random_chains`/
`amplified_runs` (I/O et contention SQLite non modélisées — mesure réelle
prioritaire sur l'estimation). `run_pipeline.py` imprime l'estimation avant
lancement et la durée mesurée après CHAQUE étape.

## 10. Étapes opérationnelles restant à John (hors code)

- `claude mcp add --transport http datagouv https://mcp.data.gouv.fr/mcp` —
  découverte interactive de nouvelles séries data.gouv (session John, hors
  pipeline — U13 consomme ensuite des IDs déjà épinglés dans son MANIFEST).
- La campagne humaine (consultants, `PROTOCOLE.md`) reste un jalon de
  VALIDATION uniquement (T3/T4 de l'échelle de preuve) — ce pipeline ne
  l'orchestre pas et n'écrit JAMAIS dans `data/prepared/` ni ne modifie
  `PROTOCOLE.md` (protocole gelé, D14).
- Le journal d'interventions RÉEL (au sens opérationnel du terme, pas
  synthétique) démarre seulement au déploiement en mode observation. Tant que
  ce mode n'est pas activé, `interventions.csv` provient exclusivement de
  `interventions_truth.jsonl` produit par l'usine synthétique U6.

## 11. Recette de bout en bout

```powershell
$env:UV_LINK_MODE='copy'; uv sync
.venv\Scripts\python.exe projects\factory\run_pipeline.py
```

Dans un worktree où les unités sœurs sont absentes (comme celui-ci) :
interruption propre au premier maillon manquant réel (`opendata` est
optionnelle et se saute d'elle-même), message FR nommant l'unité, code de
sortie 1, `pipeline_state.json` écrit avec `blocked_stage`. `--reset` efface
l'état. Relancer sans `--reset` relit l'état et retente exactement à l'étape
bloquée (reprise), sans repasser par les étapes déjà `ok`/`sautee`.
