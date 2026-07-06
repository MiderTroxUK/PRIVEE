# Rapport d'analyse — campagne HÉLIOS

Snapshots analysés : tours 0-18 (19 tours, 8 nœuds).

## Hypothèses pré-enregistrées

### HA1 — latence cognitive — NON CONFIRMÉE

lags par nœud : {'orbitalys': 1, 'aviosys': 0, 'electis': 0, 'compodis': 0, 'transglobal': 0, 'novafab': 0, 'meridian': 0, 'silpure': 0} — 1/8 à lag >= 1 (seuil : 5)

### HA2 — détection précoce (risque caché) — NON CONFIRMÉE

H(novafab) sur T6-T12 : max = 0.070 (seuil : 0.3) — {6: 0.0, 7: 0.011088270514588272, 8: 0.045720345592875855, 9: 0.06998624088520433, 10: 0.061836541730010186, 11: 0.0, 12: 0.0}

### HA3 — criticité structurelle — NON CONFIRMÉE

leader profond par tour : {0: 'novafab', 1: 'novafab', 2: 'novafab', 3: 'novafab', 4: 'novafab', 5: 'silpure', 6: 'novafab', 7: 'saturé', 8: 'saturé', 9: 'saturé', 10: 'saturé', 11: 'saturé', 12: 'saturé', 13: 'saturé', 14: 'silpure', 15: 'saturé', 16: 'novafab', 17: 'silpure', 18: 'saturé'} — novafab top-1 sur 70% des 10 tours informatifs (seuil : 80 % ; tours saturés exclus, dégénérescence documentée)

### HA4 — validité prédictive — NON CONFIRMÉE

TP=0 FP=5 TN=102 FN=37 précision=0.00 rappel=0.00 (seuils : 0.5)

### HA5 — effet de simple urgence (contagion) — NON CONFIRMÉE

ΔUd moyen nœuds non touchés aux tours de presse : -0.0067 ; tours calmes : +0.0312 (prédiction : presse > 0 et > calme)

### HA6 — hystérésis de la redescente — NON CONFIRMÉE

pente Ur moyenne +0.0097 >= 0 : pas de décrue mesurable du Ur sur T17-T18 — HA6 NON APPLICABLE (pente Ud -0.0049)

## Baseline nulle

baseline naïve (Ur_local >= 0.5) : précision=0.16 rappel=0.27

## Notes

- Analyses hors registre : à étiqueter EXPLORATOIRE.
- matplotlib indisponible : figures non générées (CSV complet dispo)
- Sur un dry run (Ud synthétique), HA1/HA5/HA6 ne sont PAS interprétables — seule la mécanique est validée.