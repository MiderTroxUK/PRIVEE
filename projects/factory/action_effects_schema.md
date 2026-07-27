# `action_effects.json` — schéma et méthode (U17)

Artefact produit par `fit_action_effects.py`. **Contrat gelé n°10 v7** (`schema_version = 2`).
Ce document décrit *précisément* la segmentation, les estimateurs, le format JSON, la
batterie de validation et — surtout — les garde-fous d'intégrité scientifique.

> **Étiquetage honnête (D18'/D20').** Toute sortie causale porte la mention
> « **effet causal ESTIMÉ sous hypothèse de confusion observable ; sensibilité : e_value** ».
> Jamais « effet réel ». Un `delta_causal_ipw` est un effet *estimé sous l'hypothèse
> — invérifiable — que toute la confusion passe par les features observées*. L'E-value
> chiffre la robustesse à une violation de cette hypothèse.

---

## 1. Entrée — `interventions.csv` (contrat 9)

Colonnes lues : `chain_id, node_id, tour, action_id, decidee, executee, date_effet,
resultat_operationnel (resolu|partiel|echec|en_cours|vide), succes`, plus les features
observables d'état-avant préfixées **`ea_`** (au minimum `ea_ur_local, ea_ud_local,
ea_hidden_risk, ea_false_urgency` + composantes KPI `ea_u_time, ea_u_cost, ea_u_quality,
ea_u_risk, ea_depth`).

### Colonnes de VÉRITÉ-TERRAIN (VALIDATION_ONLY) — jamais estimateur

`effet_vrai_param`, `delta_u_vrai`, `stress_latent` ne sont lues **que** par `--validate`
pour *noter* les estimateurs. Garantie mécanique : les estimateurs ne consomment que les
colonnes de préfixe `ea_` (`Table.feature_names`), lequel exclut par construction les trois
colonnes de vérité (aucune ne porte `ea_`), doublé d'une assertion `set(features) ∩
COLONNES_VERITE == ∅`. Le `stress_latent`, moteur réel de la confusion, n'est donc **jamais**
visible du modèle — c'est tout l'intérêt du banc.

---

## 2. Segmentation — 8 cellules d'état-avant

Trois axes binaires (2 × 2 × 2 = 8) :

| Axe | Valeur | Définition (seuil figé) |
|-----|--------|--------------------------|
| Profondeur | `profond` / `proche` | `ea_depth ≥ 2` (tier aval) ; à défaut, proxy `ea_ur_local ≥ médiane` |
| Saturation | `sature` / `nonsat` | `ea_ur_local ≥ 0.90` |
| Dominante | `utime` / `autre` | `ea_u_time` domine les composantes d'urgence ; à défaut, `ea_hidden_risk ≥ médiane` (`hirisk`/`lorisk`) |

Identifiant : `profondeur__saturation__dominante` (ex. `profond__sature__utime`). Les
définitions et seuils effectifs sont recopiés dans le champ `segments` de l'artefact.

---

## 3. Base bayésienne (D27)

Pour chaque (action × segment), sur les interventions **exécutées uniquement** :
succès = `resultat_operationnel == 'resolu'` (résultat OPÉRATIONNEL, jamais l'état de
risque — D25). `k` succès sur `n` exécutées. Trois posteriors Beta-Binomial conjugués :

| Posterior | a priori | α₀, β₀ | rôle |
|-----------|----------|--------|------|
| `prior_sim` | n₀ = 8, moyenne = simulée (`--prior-sim`) ou taux global | `m·8, (1−m)·8` | a priori informatif |
| `prior_faible` | n₀ = 1, moyenne 0.5 | `0.5, 0.5` | a priori faible |
| `donnees_seules` | Jeffreys | `0.5, 0.5` | référence sans a priori |

Posterior : `Beta(α₀+k, β₀+n−k)`, résumé `{mean, lo80, hi80}` (quantiles Beta 0.1 / 0.9).

> **Coïncidence assumée.** `prior_faible` (n₀=1, moy. 0.5) et `donnees_seules` (Jeffreys)
> valent tous deux `Beta(0.5+k, 0.5+n−k)` : ils sont numériquement identiques. Les deux
> restent exposés séparément car le contrat 10 les énumère ; la robustesse « aux trois
> priors » revient donc à : *la recommandation tient-elle avec ou sans l'a priori simulé ?*

**P(exécution) par action** (D29) : `Beta(0.5 + exécutées, 0.5 + décidées−exécutées)` sur la
transition décidée → exécutée (prior de Jeffreys). Champ `p_execution: {alpha, beta, n}`.

---

## 4. Garde-fous causaux (D20') — par (action ≠ ne_rien_faire × segment)

Contraste : **action exécutée** (`T=1`) vs **bras `ne_rien_faire`** (`T=0`) DANS le segment,
exécutés seulement. Issue défavorable `Y = 1` si `resultat_operationnel == 'echec'`.

1. **Propension** `P(T=1 | ea_features)` par **régression logistique IRLS** (numpy) :
   features standardisées, ridge L2 = 1e-3 sur les coefficients (jitter de stabilité,
   intercept non pénalisé), Newton-Raphson, contrôle de convergence.
2. **Overlap** : part des propensions hors `[0.05, 0.95]` ; **trimming** de ces lignes ;
   `overlap_ok = (part_hors < 0.10) ∧ (≥ 12 par bras après trimming)`. Le champ
   `part_hors_overlap` est publié.
3. **IPW stabilisé** : poids `p_T/e` (traités) et `(1−p_T)/(1−e)` (contrôles) ;
   `Δ = risque_non_traité − risque_traité` (réduction de risque, > 0 = bénéfique) ;
   `n_eff = (Σw)² / Σw²`. IC80 par **bootstrap pondéré stratifié par bras** (ré-ajuste la
   propension à chaque tirage — capture l'incertitude d'estimation ; graine déterministe).
4. **Doublement robuste (AIPW)** : modèle d'issue logistique (traitement en covariable) +
   correction IPW ; publié sous `delta_causal_aipw` (est/lo80/hi80).
5. **E-value (VanderWeele)** : `RR = p1/p0` de l'issue défavorable ; `E = RR* + √(RR*(RR*−1))`
   avec `RR* = RR` si `RR > 1`, sinon `1/RR` ; `None` si l'effet est nul/indéfini.

---

## 5. Format JSON (contrat 10)

```jsonc
{
  "schema_version": 2,
  "label_causal": "effet causal ESTIMÉ sous hypothèse de confusion observable ; sensibilité : e_value",
  "base_rate_resolution": 0.47,
  "actions": {
    "<action_id>": {
      "p_execution": { "alpha": .., "beta": .., "n": .. },
      "segments": {
        "<segment_id>": {
          "posteriors": {
            "prior_sim":      { "alpha", "beta", "n", "p_resolution": {"mean","lo80","hi80"} },
            "prior_faible":   { ... },
            "donnees_seules": { ... }
          },
          "delta_causal_ipw":  { "est", "lo80", "hi80", "n_eff" } | null,
          "delta_causal_aipw": { "est", "lo80", "hi80" },   // extension, robustesse
          "p0_risque_non_traite": .., "p1_risque_traite": ..,
          "e_value": <float> | null,
          "overlap_ok": <bool>, "part_hors_overlap": <float>,
          "propensity_converged": <bool>,
          "label": "effet causal ESTIMÉ ..."
        }
      }
    }
  },
  "segments": { "<segment_id>": { "profondeur", "saturation", "dominante" } },
  "validation": { /* résumé de la batterie D32, ou null si --validate non demandé */ }
}
```

`ne_rien_faire` : posteriors de base + `p_execution` présents ; champs causaux `null`
(pas de contraste contre soi-même). Le mode `--check` recharge le JSON et *assère* ce
contrat (ordre des IC, présence des clés, 8 segments).

---

## 6. Batterie de validation D32 (`--validate`, PORTE du pipeline)

Banc synthétique **déterministe** mimant l'usine (`N ≈ 4000`, réplications multiples,
second jeu de paramètres DGP2 tenu hors a priori). **La politique de l'opérateur dépend du
`stress_latent`** : `P(traiter) = σ(c0 + c_x·x_obs + c1·stress)`, avec
`stress = rho·x_obs2 + √(1−rho²)·bruit`, `rho ≈ 0.6`. Deux confondeurs superposés : un
**observé** (`x_obs`, dans les features → l'IPW le neutralise) et le **stress latent**
(majoritairement NON observé → confusion résiduelle irréductible).

Critères (par DGP), verdict imprimé ligne à ligne puis ligne globale parsable
`VALIDATION CAUSALE : PASS|FAIL` :

| # | Critère | Cible | Nature |
|---|---------|-------|--------|
| (i) | Couverture IC80 vs `delta_u_vrai` | ∈ [70 %, 90 %] | **bloquant** |
| (ii) | Biais moyen / absolu IPW | — | informatif |
| (iii) | Taux de recommandation correcte (argmax) | ≥ 0.70 | **bloquant** |
| (iv) | Regret décisionnel moyen | ≤ 0.02 | **bloquant** |
| (v) | Biais absolu NAÏF > biais absolu IPW | vrai | **bloquant** |
| (vi) | Rerun sur DGP2 (hors a priori) | idem | **bloquant** |

Reco/regret sont calculés sur l'estimateur **agrégé sur les réplications** (question :
qualité de la *décision* au volume de preuve de la campagne, pas le bruit d'une cellule de
~40 lignes) ; couverture/biais/naïf restent **par cellule**. Le taux de reco par réplication
est aussi publié (informatif — il montre le bruit fini).

### Intégrité : paramètres figés A PRIORI, résultat rapporté honnêtement

Les magnitudes du DGP (`rho`, `b_x ≫ b_stress`, `c_x`, `c1`, `b_stress = 0.10`) sont
choisies pour être **réalistes** et **figées avant** de regarder le résultat — jamais
ajustées pour faire passer un critère (ce serait sur-ajuster le banc à l'estimateur). La
machinerie est validée à part : sur un DGP **sans confusion**, la couverture est ≈ 80 % et
le biais ≈ 0 (l'estimateur et l'IC sont corrects).

**Résultat honnête constaté** (fixture livrée) : **VALIDATION CAUSALE : FAIL**.

- (v) **PASS et net** : biais naïf ≈ 0.16 vs IPW ≈ 0.09 — la confusion est réelle et
  l'ajustement la réduit fortement (contribution scientifique du banc).
- (iii)/(iv) **PASS** : la reco reste correcte (≈ 86 %) et le regret bas (≈ 0.011), car le
  biais de confusion est ~commun aux actions d'un même segment et s'annule dans l'argmax.
- (i) **FAIL** : couverture ≈ 66 % (DGP1) / 57 % (DGP2) < 70 %. Sous confusion
  **partiellement non observée**, l'IPW reste biaisé (≈ −0.06) et son IC80 est trop
  optimiste. C'est précisément ce que la porte doit détecter.

**Conséquence.** Le verdict FAIL est le comportement recherché : la porte causale (U14)
**retient l'artefact** plutôt que de publier un effet dont l'incertitude déclarée est
sous-estimée. L'E-value publiée par cellule chiffre la sensibilité à cette confusion
résiduelle. Un « PASS » obtenu en rétrécissant le confondeur serait sans valeur ; un FAIL
honnête, la confusion démontrée à l'appui, est le livrable.

---

## 7. CLI

```
python fit_action_effects.py --make-fixture F.csv            # fixture déterministe (contrat 9)
python fit_action_effects.py --interventions F --out DIR     # ajuste → action_effects.json
python fit_action_effects.py --interventions F --out DIR --check    # + assertion du schéma
python fit_action_effects.py --validate --out DIR            # batterie D32 (+ rapport_validation.md)
```

Code de sortie : `1` si `--validate` conclut FAIL (parsable par l'orchestrateur), `0` sinon.
Dépendances : **numpy + scipy** uniquement ; le cœur `supplyscore` n'est pas touché.
