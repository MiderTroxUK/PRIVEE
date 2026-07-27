# Rapport de validation causale (U17, batterie D32)

Banc synthétique déterministe : la politique de l'opérateur dépend d'un **stress latent** partiellement inobservé (rho ≈ 0.6). L'IPW/AIPW corrige la part observable de la confusion ; l'E-value chiffre la sensibilité au résidu non observé. Aucune colonne de vérité-terrain n'entre dans un estimateur — elles ne servent qu'ici, à noter les estimateurs.

Réplications par DGP : **10** — bootstrap par cellule : **200**.

## DGP1

- Cellules scorées : 320 ; segments décidés : 7
- (i) Couverture IC80 : **65.6%** → FAIL (cible 70–90 %)
- (ii) Biais moyen IPW : -0.0590 ; biais absolu : 0.0896 (informatif)
- (iii) Reco correcte (agrégée) : **85.7%** → PASS (cible ≥ 70 %) ; par réplication : 53.7% (informatif)
- (iv) Regret décisionnel : **0.0117** → PASS (cible ≤ 0.02)
- (v) Biais absolu NAÏF 0.1558 vs IPW 0.0896 → PASS — le naïf est plus biaisé (confusion démontrée)
- Verdict DGP1 : **FAIL**

## DGP2

- Cellules scorées : 333 ; segments décidés : 8
- (i) Couverture IC80 : **56.8%** → FAIL (cible 70–90 %)
- (ii) Biais moyen IPW : -0.0723 ; biais absolu : 0.0959 (informatif)
- (iii) Reco correcte (agrégée) : **100.0%** → PASS (cible ≥ 70 %) ; par réplication : 58.8% (informatif)
- (iv) Regret décisionnel : **0.0000** → PASS (cible ≤ 0.02)
- (v) Biais absolu NAÏF 0.1695 vs IPW 0.0959 → PASS — le naïf est plus biaisé (confusion démontrée)
- Verdict DGP2 : **FAIL**

---

Lecture honnête : (v) démontre chiffres à l'appui que l'ajustement causal réduit fortement le biais du naïf, mais (i) montre que sous confusion **partiellement non observée** (rho ≈ 0.6), l'IC80 de l'IPW peut sous-couvrir — l'effet causal reste ESTIMÉ, jamais réel, et l'E-value en chiffre la sensibilité. Un verdict FAIL déclenche la rétention de l'artefact par la porte U14 : c'est le comportement recherché.

**VALIDATION CAUSALE : FAIL**
