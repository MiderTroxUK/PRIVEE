# Protocole d'expérience — BRAS B (HÉLIOS)

*Déclaration assistée par prévision : la prédiction change-t-elle l'urgence
déclarée ?*

Ce document décrit le harnais `run_experiment.py` : ce qu'il mesure, comment
la fuite d'information est empêchée, et quels formats de fichiers circulent
entre le coordinateur, les personas et le moteur. Il complète — sans le
remplacer ni le modifier — `../PROTOCOLE.md`, qui reste la référence de la
campagne HÉLIOS elle-même.

---

## 1. Le design à trois bras

Les trois bras rejouent **le même scénario** : la crise mondiale des
semi-conducteurs 2020-2022, reconstituée sur 19 tours (T0 d'entraînement +
T1..T18). La **vérité terrain est gelée** : KPIs, jalons et événements
proviennent du pack figé `../data/prepared/` (lecture seule, empreintes dans
`HASHES.sha256`) et de `scenario.EVENTS`.

| Bras | Ce que voit le persona | Ce qu'il fait | Statut |
|---|---|---|---|
| **A** | sa fiche de tour | déclare son Ud (AHP) | **déjà joué** — `../analysis/llm_pilot_run/` |
| **B — `control`** | sa fiche de tour | déclare son Ud (AHP) | ce harnais |
| **B — `predict`** | sa fiche **+ l'analyse prédictive de SON nœud** | déclare son Ud (AHP) + `influence_prediction` | ce harnais |
| **C** | *(à définir)* | **agirait** sur la chaîne | **hors périmètre**, cf. §8 |

Les personas sont joués par des agents LLM pilotés par le coordinateur. **Le
harnais ne fait aucun appel LLM** : il lit et écrit des fichiers.

> **Plan de passage retenu** : c'est le **bras A**, déjà joué, qui sert de
> référence — ses prédictions sont reconstituées par rejeu. Seul le bras
> `predict` est donc à faire tourner. Le drapeau `--arm control` reste
> disponible et pleinement fonctionnel : il documente le design et permet de
> jouer le témoin interne si la référence par rejeu s'avérait insuffisante.

### Boucle ouverte : pourquoi les prédictions restent scorables

En bras B, les personas **déclarent seulement**. Aucune action, aucune
modification des KPIs, des jalons ni des événements. La vérité terrain ne
dépend donc **pas** des personas : ce qui arrive au tour N+1 est écrit
d'avance dans le pack gelé. Une prédiction émise au tour N peut par
conséquent être confrontée à ce qui s'est réellement produit — c'est ce que
le bras C, qui referme la boucle, rendra beaucoup plus délicat.

---

## 2. Ce qui est mesuré

**Question** : montrer au déclarant la prévision de son propre périmètre
change-t-il son urgence déclarée ?

Trois familles de mesures, toutes déjà produites par le harnais :

1. **Effet sur le Ud** — `Ud_raw` et `Ud_smoothed` par (nœud, tour), dans
   `results/<node>.jsonl`, au schéma EXACT du bras A. On compare les
   trajectoires `control` / `predict` / bras A.
2. **Effet déclaré par le persona** (mesure directe) — `influence_prediction`
   ∈ {`aucune`, `confirme`, `revise_a_la_hausse`, `revise_a_la_baisse`},
   présent uniquement en bras `predict`, plus une phrase de `note` disant si
   et comment l'analyse a changé la perception.
3. **Qualité des prédictions** — `predictions_log.jsonl` (cf. §5) permet de
   scorer les prédictions contre la vérité terrain gelée, **dans les deux
   bras**, donc de vérifier que le traitement n'a pas été « aidé » par des
   prédictions plus faciles.

### Ce qui, hors traitement, doit être identique

C'est la validité interne de l'A/B. Sont **identiques** entre `control` et
`predict`, et vérifiés par la recette E2E :

- le scénario et le pack gelé ;
- les 8 cartes de rôle — **byte-identiques à celles du pilote (bras A)**,
  produites par la voie officielle `make_briefings.role_card()` puis
  confrontées aux fichiers du pilote quand ils sont présents (en cas d'écart,
  la carte DU PILOTE l'emporte et l'écart est signalé) ;
- l'affectation nœud ↔ persona et les `operator_id` C1..C8 (`scenario.NODES`) ;
- le fichier `INSTRUCTIONS.md`, **au seul bloc prédictif près** ;
- le corps de la fiche de tour, **au seul bloc `## ANALYSE PRÉDICTIVE (outil)`
  près** — la fiche `predict` est littéralement la fiche `control` suivie de
  ce bloc ;
- le format de réponse et le schéma de sortie.

**Le nom du bras n'apparaît nulle part dans le bac à sable d'un persona.** Un
persona qui se saurait « en groupe témoin » ne déclarerait plus la même chose.

### La carte de rôle donne une voix, jamais un niveau d'inquiétude

Chaque carte décrit **comment l'entreprise parle et ce qu'elle craint** —
jamais combien il faut s'inquiéter à un tour donné. C'est écrit noir sur blanc
en bas de chaque carte, et c'est la condition pour que le Ud mesure quelque
chose. **Rien ne doit être ajouté**, ni dans les cartes ni dans les
instructions, qui suggérerait un niveau d'alarme, une tendance attendue, ou
l'idée que la prédiction serait « la bonne réponse ». Les instructions du bras
`predict` disent explicitement que l'analyse peut se tromper, qu'elle n'est
pas une consigne, et que les quatre valeurs d'`influence_prediction` se
valent : répondre `aucune` n'est pas un échec.

---

## 3. La garantie anti-fuite

Elle est **structurelle**, pas une consigne.

1. **Fiche de tour** — produite par `make_briefings.briefing()`, qui ne lit
   que les fichiers préparés des tours ≤ N et ne retient que les lignes du
   nœud concerné. Aucune donnée future n'est jamais chargée en mémoire au
   moment de produire une fiche ; aucun mois ni millésime réel n'apparaît.
2. **Ordre des tours** — les fiches arrivent **une par une** : le harnais ne
   produit `tour_(N+1)` qu'après la clôture du tour N. Contrairement au bras A,
   où les 19 fiches étaient toutes présentes dès le départ et où la discipline
   d'ordre reposait sur la seule consigne, l'anticipation est ici
   matériellement impossible. C'est le **seul renforcement** assumé par
   rapport au bras A (cf. §7).
3. **Bloc prédictif** — ne contient QUE des nombres calculés sur le nœud de la
   fiche. Vérifié automatiquement : aucun autre nom ni identifiant de nœud n'y
   figure, et le nœud de la fiche y figure bien.
4. **Pas de chiffre inventé** — si la prévision échoue ou si l'historique est
   insuffisant, le bloc affiche « analyse prédictive indisponible ce tour ».
   Jamais de valeur de repli, jamais de valeur d'un autre nœud.
5. **Pack gelé en lecture seule** — le harnais n'écrit jamais dans
   `../data/prepared/` ni dans `../PROTOCOLE.md`. Toute écriture en base passe
   par la façade `SupplyScoreService` / `MutationService` (validation + audit).

### Une frontière examinée : `impact_frac`

Le bloc prédictif s'appuie sur `InsightService`, dont la règle de sévérité
« alerte » utilise `impact_frac` = *fraction des nœuds du projet touchés par
le pire choc local de CE nœud* (criticité systématique, même formule que
`PredictionService`).

C'est une propriété **du nœud lui-même** — jusqu'où sa propre défaillance se
propage — et non l'état d'un autre nœud : aucun KPI, aucune urgence, aucun
jalon d'un tiers n'est divulgué. Le choix est néanmoins **assumé et
révocable** : `impact_frac` révèle indirectement la taille du réseau. Le
retirer se fait en une ligne (`impact_frac=None` dans `_PointPrevision`), au
prix de la sévérité « alerte », qui ne pourrait alors plus être atteinte.

### Ce qui n'est PAS montré

`InsightService` produit aussi un champ `action` (catalogue dégradé : promouvoir
un arc de secours, revoir un jalon...). **Il n'est jamais rendu dans la fiche** :
en bras B les personas ne peuvent agir sur rien, et suggérer une action
contaminerait le traitement. Ce champ est réservé au bras C.

---

## 4. Le déroulé d'un tour

Une base SQLite **persistée par sous-bras**, jamais mélangées.

```
init          --arm predict --db-dir D
prepare-tour  --arm predict --db-dir D --out O --tour N   [--n-draws 500] [--seed 0]
   -> le coordinateur fait jouer les 8 personas sur O/sandbox_*/
collect-tour  --arm predict --db-dir D --out O --tour N --answers F.jsonl
close-tour    --arm predict --db-dir D --out O --tour N
status        --db-dir D
make-sandboxes --arm predict --out O
```

`prepare-tour N` enchaîne : décroissance hebdomadaire (N > 0) →
KPIs → jalons → événements → **réévaluation explicite** → prévision (N ≥ 4) →
journal → fiches.

> **Pourquoi la réévaluation explicite.** Des trois injecteurs, seul
> `EventEngine.apply` réévalue et persiste l'état d'urgence. Sans appel
> explicite à `evaluate_all(persist=True)`, la prévision serait donc « fraîche »
> aux tours porteurs d'un événement (3, 5, 6, 7, 10, 12, 13, 14, 16) et
> « périmée » d'un tour aux autres (**4, 8, 9, 11, 15, 17, 18**). Un traitement
> inégal d'un tour à l'autre ruinerait la comparabilité des prédictions.

**Idempotence et reprise.** Chaque sous-commande refuse un tour hors séquence
avec un message français, sur la même discipline qu'`inject_tour.py` : machine
à états `last_tour` → `pending_tour` + `phase` (`injecte` → `collecte` →
clos), un seul tour ouvert à la fois. `predictions_log.jsonl` et
`results/<node>.jsonl` remplacent les lignes du même tour au lieu de les
dupliquer. `close-tour` réaligne `campaign_state.json` sur l'état
d'expérience, pour que les deux fichiers d'état ne racontent jamais deux
histoires différentes.

**Verrou sur `--out`.** Le dossier de sortie est enregistré par `prepare-tour`
et les étapes suivantes s'y raccrochent : `collect-tour` peut l'omettre, mais
un dossier *discordant* est refusé. Sans ce verrou, changer de `--out` en
cours de campagne casserait **silencieusement** la chaîne du Ud lissé (le Ud
du tour précédent se lit dans `results/<node>.jsonl`) et éparpillerait le
journal de prédictions.

`make-sandboxes` peut être lancé à tout moment : les fiches des tours déjà
préparés sont recopiées dans `sandbox_<node>/tours/` (rattrapage).

> **Limite connue** (héritée d'`inject_tour.py`) : si `prepare-tour` échoue
> *pendant* l'injection en base, l'état n'est pas avancé et une relance
> ré-injecterait le tour. En cas d'échec à cette étape, repartir de la
> sauvegarde zip du tour précédent (`export_state` en produit une à chaque
> clôture) plutôt que de relancer `prepare-tour`.

### Arborescence de sortie (`--out`)

```
O/
  tour_NN/<node>.md          fiches de référence du tour
  sandbox_<node>/            bac à sable persona (make-sandboxes)
      INSTRUCTIONS.md        protocole (identique hors bloc prédictif)
      role_card.md           carte de rôle du pilote (bras A)
      ahp_tool.py            copie exacte de supplyscore/core/ahp.py
      tours/tour_NN.md       fiche déposée par prepare-tour, une par une
  predictions_log.jsonl      prédictions des DEUX bras (cf. §5)
  results/<node>.jsonl       résultats canoniques, schéma bras A (cf. §6)
  snapshots/tour_NN.json     snapshot d'état par tour (close-tour)
```

---

## 5. `predictions_log.jsonl` — le cœur scientifique

**Le bras `control` calcule et journalise exactement les mêmes prédictions que
le bras `predict`. Il ne les montre simplement jamais.**

C'est ce qui rend l'A/B interprétable : les deux bras produisent des
prédictions prospectives comparables, et la **seule** chose qui diffère est
leur visibilité — le champ `montre_au_persona`. Sans cela, on ne pourrait pas
distinguer « la prédiction a changé la déclaration » de « les deux bras
n'avaient pas la même situation à prédire ».

Une ligne par (tour, nœud), dès le tour 4 (`ForecastService.MIN_HISTORY_WEEKS`) :

```json
{"arm": "control", "tour": 4, "node_id": "orbitalys",
 "p_issue_h1": 0.030, "p_issue_h2": 0.056, "p_issue_h3": 0.080, "p_issue_h4": 0.118,
 "ic80_h4": [0.0, 0.2496], "se_mc": 0.0137, "spread": 0.2496,
 "p_jalon_rate": 0.0, "p_impact_client": 0.066,
 "montre_au_persona": false, "n_draws": 500, "seed": 0}
```

- `p_issue_hk` — P(issue défavorable d'ici k semaines) : jalon raté **ou**
  événement critique/défaut (équivalence figée avec `CalibrationService`) ;
- `ic80_h4` / `se_mc` / `spread` — incertitude à 4 semaines (Monte Carlo
  imbriqué : composantes MC et paramétrique) ;
- `p_jalon_rate`, `p_impact_client` — à 4 semaines ;
- `montre_au_persona` — `true` uniquement en bras `predict` **et** quand une
  prévision exploitable a été produite ;
- `n_draws`, `seed` — reproductibilité (même graine, mêmes chiffres) ;
- `erreur` — présent uniquement si la prévision a échoué ; toutes les valeurs
  numériques sont alors `null` (jamais un chiffre de repli).

---

## 6. Formats d'échange

### Entrée — `answers.jsonl` (un tour, une ligne JSON par nœud, 8 lignes)

```json
{"node_id": "novafab", "bipolar": [2,3,1,1,-1,-2], "scores_ui": [3,2,2,2],
 "attempts": 1, "note": "…", "influence_prediction": "confirme"}
```

| Clé | Obligatoire | Contrainte |
|---|---|---|
| `node_id` | oui | l'un des 8 nœuds, une seule fois |
| `bipolar` | oui | 6 entiers dans [-8, 8], ordre figé des paires AHP |
| `scores_ui` | oui | 4 entiers dans [1, 6] |
| `note` | oui | phrase du persona, à la première personne |
| `attempts` | non (défaut 1) | 1 ou 2 |
| `influence_prediction` | **bras `predict` seulement** | l'une des 4 valeurs |

**Toute autre clé est ignorée** : le coordinateur peut donc recopier telle
quelle la ligne `results.jsonl` écrite par le persona, en y ajoutant
`node_id`. La couverture doit être **8/8** — sinon la collecte est refusée, et
**rien** n'est écrit (validation intégrale avant toute soumission).

`influence_prediction` est **refusé** en bras `control` : un persona du groupe
témoin n'a vu aucune prédiction, sa présence signale un bac à sable mal servi.

### Sortie — `results/<node>.jsonl` (schéma EXACT du bras A)

```
tour, bipolar, scores_ui, weights, lambda_max, ci, cr, is_consistent,
attempts, cr_echec, ud_raw, ud_smoothed, note [, influence_prediction]
```

Mêmes clés, même ordre que `analysis/llm_pilot_run/sandbox_*/results.jsonl`,
plus `influence_prediction` en fin de ligne **en bras `predict` uniquement**.
Les grandeurs AHP sont **recalculées par le harnais** (`run_ahp`,
`compute_ud`, `ud_smoothed` avec ρ = 0.3, `ud_smoothed_0 = ud_raw_0`) :
c'est le moteur qui fait foi, pas l'arithmétique du persona.

### Règle de report (CR ≥ 0.10)

Le persona dispose de 2 tentatives dans son bac à sable. Si la déclaration
soumise reste incohérente, le harnais applique la règle de report de
`../PROTOCOLE.md` :

- la **déclaration du tour précédent** est reconduite auprès du moteur
  (`latest_assessment`), ou une déclaration neutre s'il n'y a pas d'historique ;
- `cr_echec: true`, `is_consistent: false` ;
- `bipolar`, `scores_ui`, `note` conservent la déclaration **brute** du
  persona (elle reste analysable) ;
- `weights`, `lambda_max`, `ci`, `cr` sont ceux de la matrice **rejetée**
  (traçabilité du refus) ;
- `ud_raw` et `ud_smoothed` reprennent **tels quels** ceux du tour précédent —
  aucun Ud n'est recalculé, conformément au protocole du bras A.

---

## 7. Écarts assumés par rapport au bras A

| Écart | Raison | Effet sur la comparabilité |
|---|---|---|
| Les fiches arrivent une par une au lieu d'être toutes présentes | le tour N+1 n'existe pas tant que le tour N n'est pas clos | **renforce** la garantie anti-anticipation ; aucune information supplémentaire |
| Les grandeurs AHP sont recalculées par le harnais | le moteur fait foi ; supprime toute divergence d'arithmétique entre personas | **renforce** la comparabilité |
| Bloc `## ANALYSE PRÉDICTIVE (outil)` | **c'est le traitement mesuré** | bras `predict` uniquement |

Rien d'autre ne diffère : mêmes personas, mêmes cartes, mêmes règles, même
format de réponse.

---

## 8. Couture pour le bras C (non implémentée)

Le point d'accroche unique est `appliquer_actions_bras_c()` dans
`run_experiment.py`, appelé à chaque déclaration et **volontairement inerte**.
Sa docstring décrit la marche à suivre : lire l'action choisie dans la
réponse → la résoudre dans `supplyscore.domain.actions.CATALOGUE_V1` après
vérification de sa précondition (`contexte_pour`) → l'appliquer via
`ActionSpec.apply_to_project` (donc par la façade / `MutationService`) →
journaliser l'intervention avec `InterventionJournal.record` puis
`marquer_executee`, ce journal alimentant ensuite les effets causaux et le
moteur de décision.

**Avertissement de validité** : dès que cette fonction agit, la vérité terrain
dépend des personas. La boucle se referme, et les prédictions du bras C ne
sont plus directement comparables à celles du bras B sans appariement
explicite. Rien du bras C n'est implémenté aujourd'hui.
