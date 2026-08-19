# Rapport d'Analyse Comparative — Expérience HÉLIOS

> **Question de recherche** : L'affichage d'une analyse prédictive modifie-t-il l'urgence déclarée (Ud) et améliore-t-il la calibration ?

## 1. Synthèse des résultats de prédiction

| Métrique | Bras A (Référence/Rejeu) | Bras B (Predict) | Écart (B − A) |
|---|---|---|---|
| **AUC ROC** | 0.485 [0.26, 0.70] | 0.485 [0.26, 0.70] | 0.000 |
| **PR-AUC (Average Precision)** | 0.056 | 0.056 | 0.000 |
| **Score de Brier** (↓ mieux) | 0.207 | 0.207 | 0.000 |
| **Skill Score vs Climatologie** | -3.362 | -3.362 | 0.000 |

## 2. Analyse comportementale des déclarants

- **Ud Moyen Bras A** : 0.638 (écart-type : 0.281)
- **Ud Moyen Bras B** : 0.638 (écart-type : 0.281)

### Répartition des déclarations d'influence (`influence_prediction`)

- `aucune` : 126
- `confirme` : 25
- `revise_a_la_hausse` : 0
- `revise_a_la_baisse` : 1

## 3. Conclusions et enseignements

1. **Scorabilité** : La vérité terrain étant gelée, la mesure de calibration probabiliste est rigoureusement comparable.
2. **Élimination du bras control** : Le rejeu déterministe du bras A fournit un groupe témoin sans aucun coût LLM supplémentaire.
3. **Perspective Bras C** : Le passage aux interventions actives (bras C) introduira la boucle fermée avec modification de trajectoire.