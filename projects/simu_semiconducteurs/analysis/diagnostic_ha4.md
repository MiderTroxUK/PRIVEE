# Diagnostic HA4 — balayage de seuil du signal prédictif

**EXPLORATOIRE — hors registre pré-enregistré** (voir PROTOCOLE.md §5). Ce document ne modifie ni ne réinterprète le verdict gelé de HA4 (`analyse_campagne.ha4()`, `rapport.md`) : il diagnostique, à seuil libre, si Ur/Ud/H portent un pouvoir discriminant quelconque à l'horizon 4 tours.

## Jeu de données : dry run v6

Tours analysés : 0-18 (19 tours, 8 nœuds) ; horizon HA4 = 4 tours.

| Signal | n (pos/neg) | AUC | IC95 (bootstrap cluster, 1000 tirages) | PR-AUC | Seuil F1 (F1) | Confusion @F1 | Seuil Youden (J) | Confusion @Youden |
|---|---|---|---|---|---|---|---|---|
| `hidden_risk` | 144 (37/107) | 0.322 | [0.196, 0.458] | 0.201 | 0.000 (F1=0.409) | TP=37 FP=107 TN=0 FN=0 | 1.686 (J=0.000) | TP=0 FP=0 TN=107 FN=37 |
| `H_local` | 144 (37/107) | 0.526 | [0.289, 0.777] | 0.269 | 0.006 (F1=0.418) | TP=28 FP=69 TN=38 FN=9 | 0.207 (J=0.127) | TP=13 FP=24 TN=83 FN=24 |
| `ur` | 144 (37/107) | 0.475 | [0.299, 0.614] | 0.244 | 0.192 (F1=0.426) | TP=33 FP=85 TN=22 FN=4 | 0.192 (J=0.097) | TP=33 FP=85 TN=22 FN=4 |
| `ur_local` | 144 (37/107) | 0.503 | [0.328, 0.625] | 0.251 | 0.192 (F1=0.478) | TP=33 FP=68 TN=39 FN=4 | 0.192 (J=0.256) | TP=33 FP=68 TN=39 FN=4 |
| `gap` | 144 (37/107) | 0.309 | [0.171, 0.468] | 0.184 | -0.451 (F1=0.423) | TP=37 FP=101 TN=6 FN=0 | -0.451 (J=0.056) | TP=37 FP=101 TN=6 FN=0 |

### Analyse de lag (signal retenu)

Signal retenu (AUC horizon 4 la plus élevée) : `H_local`.

| k (fenêtre (t+k-1, t+k]) | AUC |
|---|---|
| 1 | 0.512 |
| 2 | 0.536 |
| 3 | 0.551 |
| 4 | 0.523 |

**Interprétation** : AUC quasi stable selon k (0.512 → 0.523) : pas de gradient net.

### Baseline naïve (Ur_local >= 0.5, horizon 4, même grille que HA4)

TP=10 FP=53 TN=62 FN=27 précision=0.16 rappel=0.27

## Jeu de données : pilote LLM

Snapshots introuvables sous `simu_semiconducteurs\analysis\llm_pilot_run\snapshots` au moment de l'exécution — jeu ignoré (probable dépendance d'une autre unité du plan HÉLIOS v7, pas encore fusionnée). Le script est prêt à le traiter dès qu'il apparaîtra (relancer ce script suffit).

## Figures

- matplotlib indisponible : figures non générées (tables complètes dans ce rapport)

## VERDICT

VERDICT (zone grise) : AUC(meilleur signal) = AUC(`H_local`, dry run v6) = 0.526 (IC95 [0.289, 0.777]) — ni > 0.65 (signal net), ni dans [0.45, 0.55] partout (bruit pur). Ni GO franc ni pivot immédiat : cf. la table de lag et les IC95 par signal ci-dessus avant de trancher. Par défaut, traiter comme NON-GO (le seuil gelé n'est pas disqualifié à tort, mais le signal n'est pas assez net pour relancer HA4 tel quel).
Note : jeu(x) de snapshots indisponible(s) au moment de l'analyse : pilote LLM — verdict basé uniquement sur les données présentes.
