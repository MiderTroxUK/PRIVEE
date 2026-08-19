# Model card — Prédicteur de risque HÉLIOS v7 (U10, EMOS)

Généré le 2026-08-19 11:11:17 à partir de `projects\factory\fixtures\predictor_dataset.csv` (mode --fast, 9.8 s).

## 1. Définition des labels

- **y1** : 1 si un événement vérité (gravité critique|défaut) touche le nœud exactement à t+1, 0 sinon, VIDE si t+1 dépasse le dernier tour observé de la chaîne (censure explicite, jamais 0 silencieux).
- **y4** : 1 si un événement vérité touche le nœud dans (t, t+4], 0 si la fenêtre est entièrement observée sans événement, VIDE si la fenêtre dépasse le dernier tour observé sans qu'aucun événement n'y ait été trouvé.
- L'entraînement et les 3 axes d'évaluation utilisent **y1** (lignes censurées retirées) ; **y4** sert uniquement à la comparabilité HA4 (précision/rappel au seuil de Youden appris sur y1 du même pli).

Dataset : 4800 lignes chargées, 4480 utilisables (y1 non censuré), 40 chaînes, 5 régimes `dgp_params_id`. Colonnes manquantes-quelque-part (indicatrice ajoutée) : u_time, u_cap, u_perf, u_risk, u_cost, u_co2, d1_ur_local, d2_ur_local, d3_ur_local, d4_ur_local, d1_H, d2_H, d3_H, d4_H, weeks_since_event, p_retard_jalon, p_impact_final, delta_ell_final, delta_ell_max, p_rollout, spread, impact_frac, mean_ur_pred, max_ur_pred, frac_pred_satures, mean_beta_in. `p_rollout` présent (au moins une valeur non manquante).

## 2. Les trois axes d'évaluation

- **Chaînes tenues** : GroupKFold par `chain_id` — généralisation à des chaînes inédites.
- **Régime DGP tenu** : hold-out par `dgp_params_id` — généralisation à un régime de paramètres inédit (jamais vu, ni dans le train du pli, ni dans le prior).
- **Coupure temporelle** : train `t<=12` / test `t>=13`. **Décision de conception** : le contrat 4 gelé (`build_dataset.py`) ne conserve PAS de colonne de tour brute — elle est supprimée avant écriture. Cet axe utilise donc `beta_n` (nombre de tours réellement observés pour le nœud jusqu'à t inclus) comme proxy de l'ordinal temporel : `beta_n` est strictement croissant avec t et vaut t+1 en l'absence de trou d'historique. Hypothèse documentée, à vérifier si le dataset réel présente des trous d'historique fréquents (auquel cas `beta_n` sous-estime légèrement t).

Hyperparamètres (grille de C du ML pur, sélection L1 d'EMOS, C de calibration) réglés UNIQUEMENT sur le pli d'entraînement de chaque axe (jamais sur le pli de test).

## 3. Comparaison des modèles (3 axes × 4 modèles)

| Axe | Modèle | n | Brier | Skill vs climatologie | ROC-AUC | PR-AUC | Précision HA4 | Rappel HA4 (n) |
|---|---|---|---|---|---|---|---|---|
| Chaînes tenues (GroupKFold(5) par chain_id) | EMOS | 4480 | 0.1101 | 30.8% | 0.850 | 0.634 | 0.817 | 0.379 (3854) |
| Chaînes tenues (GroupKFold(5) par chain_id) | Rollout brut | 4480 | 0.1269 | 20.3% | 0.792 | 0.517 | 0.735 | 0.460 (3854) |
| Chaînes tenues (GroupKFold(5) par chain_id) | ML pur (L2) | 4480 | 0.1080 | 32.1% | 0.852 | 0.636 | 0.793 | 0.407 (3854) |
| Chaînes tenues (GroupKFold(5) par chain_id) | HistGradientBoosting | 4480 | 0.1107 | 30.4% | 0.842 | 0.614 | 0.759 | 0.473 (3854) |
| Régime DGP tenu (hold-out par dgp_params_id) | EMOS | 4480 | 0.1111 | 30.3% | 0.848 | 0.630 | 0.769 | 0.459 (3854) |
| Régime DGP tenu (hold-out par dgp_params_id) | Rollout brut | 4480 | 0.1269 | 20.4% | 0.792 | 0.517 | 0.735 | 0.460 (3854) |
| Régime DGP tenu (hold-out par dgp_params_id) | ML pur (L2) | 4480 | 0.1093 | 31.4% | 0.848 | 0.626 | 0.783 | 0.414 (3854) |
| Régime DGP tenu (hold-out par dgp_params_id) | HistGradientBoosting | 4480 | 0.1123 | 29.5% | 0.838 | 0.607 | 0.760 | 0.463 (3854) |
| Coupure temporelle (train t<=12 / test t>=13, proxy beta_n) | EMOS | 640 | 0.1171 | 28.5% | 0.850 | 0.621 | 1.000 | 0.753 (182) |
| Coupure temporelle (train t<=12 / test t>=13, proxy beta_n) | Rollout brut | 640 | 0.1309 | 20.1% | 0.802 | 0.528 | 1.000 | 0.742 (182) |
| Coupure temporelle (train t<=12 / test t>=13, proxy beta_n) | ML pur (L2) | 640 | 0.1144 | 30.1% | 0.849 | 0.622 | 1.000 | 0.610 (182) |
| Coupure temporelle (train t<=12 / test t>=13, proxy beta_n) | HistGradientBoosting | 640 | 0.1199 | 26.8% | 0.838 | 0.595 | 1.000 | 0.637 (182) |

(Skill = 1 − Brier(modèle)/Brier(climatologie du train du pli). Seul EMOS est calibré ; les 3 challengers utilisent leur `predict_proba` natif.)

## 4. Règle de décision (exportée)

Règle de décision : EMOS (Brier=0.1101) conserve l'avantage sur le rollout brut (Brier=0.1269) sur l'axe « chaînes tenues » -> EMOS exporté.

**Artefact exporté** : EMOS — 5 feature(s) de design : `logit_p_rollout, spread, ur_local, d1_ur_local, p_impact_final`.

## 5. Échelle de preuve (définition gelée, plan v7)

- **T1 — fonctionnement** (synthétique) : le pipeline tourne, se calibre et
  reproduit ses propres prédictions en numpy — niveau atteint par CE run (fixture
  synthétique).
- **T2 — généralisation** : tenue sur des chaînes et des régimes DGP inédits
  (axes « chaînes tenues » et « régime DGP tenu » ci-dessous).
- **T3 — rejeu historique** : campagne HÉLIOS (crise des semi-conducteurs) ou
  extension énergie 2022 — nécessite le dataset réel produit par U8 sur les runs
  de la campagne, pas cette fixture.
- **T4 — utilité** : observation puis intervention contrôlée (terrain, hors code).

## 6. Avertissement sim2real

Ce model card a été généré sur une **fixture synthétique** (`fixtures/make_predictor_fixture.py`) à DGP logistique connu, utilisée pour valider le pipeline (T1). Les coefficients, odds-ratios et métriques ci-dessus NE reflètent PAS la réalité opérationnelle — ils décrivent le comportement du simulateur. Avant tout usage en production, ré-entraîner sur le dataset réel produit par `build_dataset.py` (U8) sur les runs de la campagne HÉLIOS (T2/T3), et ne jamais présenter ces chiffres comme une mesure de risque réelle.

## 7. Odds-ratios par écart-type (modèle exporté)

| Feature (unité standardisée) | Odds-ratio / ET | IC80 |
|---|---|---|
| logit_p_rollout | 1.039 | [0.956, 1.111] |
| spread | 0.951 | [0.903, 0.964] |
| ur_local | 2.027 | [1.850, 2.423] |
| d1_ur_local | 1.370 | [1.251, 1.512] |
| p_impact_final | 1.785 | [1.590, 1.909] |

(IC80 = 10ᵉ-90ᵉ centile de `coef_boot`, K réplicats bootstrap par ré-échantillonnage des chaînes avec remise — convention IC80 du plan v7.)

## 8. Importance par permutation (HistGradientBoostingClassifier, challenger)

| Feature | Importance (perte de Brier, moyenne ± ET) |
|---|---|
| p_impact_final | 0.0305 ± 0.0010 |
| d1_ur_local | 0.0033 ± 0.0005 |
| ur_local | 0.0014 ± 0.0003 |
| p_rollout | 0.0009 ± 0.0001 |
| u_co2 | 0.0008 ± 0.0008 |
| impact_frac | 0.0006 ± 0.0003 |
| ur | 0.0006 ± 0.0003 |
| mean_beta_in | 0.0005 ± 0.0003 |
| delta_ell_max | 0.0005 ± 0.0002 |
| d1_H | 0.0004 ± 0.0001 |
| spread | 0.0004 ± 0.0003 |
| d3_H | 0.0003 ± 0.0003 |
| u_perf | 0.0003 ± 0.0002 |
| d3_ur_local | 0.0003 ± 0.0005 |
| mean_ur_pred | 0.0003 ± 0.0006 |

(Calculée sur le pli 0 de l'axe « chaînes tenues », hors-échantillon d'entraînement du HGB — `scoring='neg_brier_score'`, 5 répétitions.)