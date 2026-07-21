# Modèle mathématique SupplyScore — spécification formelle

> **Phase E9, Lot 9.1.** Ce document est la spécification de référence du modèle
> mathématique de SupplyScore, **rédigée à partir du code réellement implémenté**
> (et non d'intentions). Chaque formule cite son fichier source ; chaque constante
> a été vérifiée contre le code ; la table des cas de référence (§10) croise les
> valeurs des tests existants et des lots de tests de propriétés (9.2–9.5).
>
> Modules couverts : `supplyscore/core/ahp.py`, `ur_model.py`, `adequation.py`,
> `status_rules.py`, `clock.py` ; `supplyscore/graph/propagation.py` ;
> `supplyscore/domain/milestones.py`, `events.py`, `models.py`, `constraints.py` ;
> `supplyscore/services/weekly.py`.

## Table des matières

1. [Vue d'ensemble du pipeline](#1-vue-densemble-du-pipeline)
2. [Urgence déclarée Ud_loc — questionnaire AHP (Saaty)](#2-urgence-déclarée-ud_loc--questionnaire-ahp-saaty)
3. [Urgence réelle locale Ur_loc — six blocs KPI](#3-urgence-réelle-locale-ur_loc--six-blocs-kpi)
4. [Propagation sur le graphe](#4-propagation-sur-le-graphe)
5. [Adéquation A, fausse urgence F, risque caché H](#5-adéquation-a-fausse-urgence-f-risque-caché-h)
6. [Statuts et jalons](#6-statuts-et-jalons)
7. [Événements calibrés](#7-événements-calibrés)
8. [Cycle hebdomadaire ISO et horloge](#8-cycle-hebdomadaire-iso-et-horloge)
9. [Décisions de modélisation](#9-décisions-de-modélisation)
10. [Table des cas de référence chiffrés](#10-table-des-cas-de-référence-chiffrés)
11. [Références](#11-références)
12. [Limites honnêtes du modèle](#12-limites-honnêtes-du-modèle)
13. [Définitions gelées : rupture, résultat opérationnel, état de risque](#13-définitions-gelées--rupture-résultat-opérationnel-état-de-risque)

La correspondance formule vers code (fichier, classe, fonction pour chaque équation) se
trouve dans [le guide développeur](guide_developpeur.md), sections 3 à 5.

---

## 1. Vue d'ensemble du pipeline

SupplyScore mesure, pour chaque nœud d'un réseau logistique (DAG orienté
fournisseur → client, rang 0 = client final, rang N = fournisseur profond),
l'écart entre deux urgences :

- **Ud — urgence déclarée** : la perception humaine, issue d'un questionnaire
  AHP hebdomadaire (4 critères, échelle de Saaty), lissée dans le temps (EMA) ;
- **Ur — urgence réelle** : la réalité opérationnelle, issue des KPIs du nœud
  (temps, capacité, performance, risque, coût, CO₂), agrégés par OU probabiliste.

Les deux urgences locales sont ensuite **propagées** sur le graphe (Ud descend du
client final vers les fournisseurs, Ur remonte des fournisseurs vers le client),
puis confrontées par le **score d'adéquation** A ∈ [0, 100], décomposé en deux
pathologies : fausse urgence F (panique injustifiée) et risque caché H (danger
invisible). Le pipeline complet (`SupplyScoreService.evaluate_all`) enchaîne :
Ur_local → propagation descendante (Ud) → propagation montante (Ur) → adéquation
→ persistance.

### Schéma des strates

```
STRATE 1 — SAISIE (hebdomadaire, manuelle)
  ┌─────────────────────────┐   ┌──────────────────────────┐   ┌────────────────────┐
  │ Questionnaire AHP       │   │ KPIs (6 blocs)           │   │ Événements (14     │
  │ 4 critères, Saaty 1..9  │   │ + jalons (avancement)    │   │ types calibrés)    │
  └───────────┬─────────────┘   └────────────┬─────────────┘   └─────────┬──────────┘
              │                              │      ▲ impacts BAYES/EMA/ │
              │                              │◄─────┴ DIRECT/CLIQUET ────┘
STRATE 2 — URGENCES LOCALES (par nœud)
  ┌───────────▼─────────────┐   ┌────────────▼─────────────┐
  │ Ud_loc ∈ [0,1]          │   │ Ur_loc ∈ [0,1]           │
  │ AHP → compute_ud        │   │ u_time,u_cap,u_perf,     │
  │ → lissage EMA (ρ=0.3)   │   │ u_risk,u_cost,u_co2      │
  │                         │   │ → OU probabiliste pondéré│
  └───────────┬─────────────┘   └────────────┬─────────────┘
              │        (règles de statut : DONE → Ur_loc^eff = 0, ABANDONED → 1)
STRATE 3 — PROPAGATION SUR LE DAG (ordre topologique)
  ┌───────────▼──────────────────────────────▼─────────────┐
  │ Ud_i = 1 − (1−Ud_loc_i)·Π_k (1 − γ_ik·Ud_k)  DESCENDANT │  rang 0 → rang N
  │ Ur_i = 1 − (1−Ur_loc_i)·Π_j (1 − β_ji·Ur_j)  MONTANT    │  rang N → rang 0
  └───────────────────────────┬────────────────────────────┘
STRATE 4 — ADÉQUATION (par nœud)
  ┌───────────────────────────▼────────────────────────────┐
  │ A(Ud, Ur) ∈ [0,100]  (Prospect Theory, asymétrique)     │
  │ F = [Ud − Ur]₊ (fausse urgence) ; H = [Ur − Ud]₊ (risque│
  │ caché) — gouvernance : λ_under = 2.25 > λ_over = 1.0    │
  └─────────────────────────────────────────────────────────┘
```

Le fondement conceptuel de la strate 3 est l'**effet ripple** (Ivanov et al.,
voir §11) : une perturbation locale se propage de proche en proche sur le réseau,
atténuée par les coefficients d'arc (γ pour le besoin descendant, β pour le
risque montant). Le différenciateur de SupplyScore n'est pas la propagation en
soi, mais la **confrontation déclaré/réel** (strate 4) : aucun des modèles de
ripple publiés ne mesure l'adéquation entre perception humaine et signal mesuré.

---

## 2. Urgence déclarée Ud_loc — questionnaire AHP (Saaty)

Code : `supplyscore/core/ahp.py`. Référence : Saaty (1977), *A scaling method
for priorities in hierarchical structures*.

Quatre critères figés (`CRITERIA`) : C1 Impact opérationnel, C2 Fenêtre
temporelle, C3 Dépendances aval, C4 Récupérabilité. L'AHP reste volontairement
limité à 4 critères : sa cohérence se dégrade au-delà de ~7 (cf. §12, limite 3 ;
la pondération des nombreux blocs KPI passera par FBWM au Jalon 2).

### 2.1 Matrice de comparaison réciproque (`build_matrix`)

L'opérateur fournit des jugements de Saaty par paire : `{(i, j): v}` signifie
« le critère i est v fois plus important que j », v ∈ [1/9, 9].

```
A ∈ ℝⁿˣⁿ,  A[i][i] = 1,  A[i][j] = v,  A[j][i] = 1/v
```

- **Domaine** : v > 0 ; indices dans [0, n−1] ; diagonale forcée à 1.
- **Validations (code)** : v ≤ 0 rejeté ; jugement diagonal ≠ 1 rejeté ;
  paire (i, j)/(j, i) contradictoire (à 1e-6 relatif près) rejetée.
- **Propriété** : A est une matrice réciproque positive ; elle est dite
  *parfaitement cohérente* si A[i][j]·A[j][k] = A[i][k] pour tous i, j, k
  (équivalent : A[i][j] = w_i/w_j pour un vecteur de poids w).

### 2.2 Vecteur de priorités (`priority_vector`) — approximation, PAS le vecteur propre exact

```
w_i = moyenne_j( A[i][j] / Σ_k A[k][j] ),   puis w ← w / Σ w
```

Chaque **colonne** de A est normalisée par sa somme, puis on prend la **moyenne
de chaque ligne** ; le résultat est renormalisé à somme 1.

**Ce que c'est — et ce que ce n'est pas.** La théorie de Saaty définit le
vecteur de priorités comme le vecteur propre principal de A (Perron-Frobenius).
Le code implémente l'**approximation classique « moyenne des lignes de la
matrice normalisée par colonnes »** (*normalized column mean*), pas une
itération de puissance ni une décomposition spectrale. Conséquences :

- pour une matrice **parfaitement cohérente**, l'approximation coïncide
  **exactement** avec le vecteur propre principal (toutes les colonnes
  normalisées sont identiques et égales à w) — cas de référence exact du lot
  9.4 : a_ij = w_i/w_j avec w = (0.4, 0.3, 0.2, 0.1) redonne w exactement,
  λmax = 4, CR = 0 ;
- pour une matrice admissible (CR < 0.10, cf. §2.3), l'écart par composante
  est de l'**ordre de 10⁻² au plus (quelques pour cent)** — c'est l'ordre de
  grandeur d'écart **accepté**, inférieur au bruit de quantification de
  l'échelle discrète de Saaty (jugements entiers 1..9 et leurs inverses) ;
- pour une matrice fortement incohérente, l'écart peut être plus grand — mais
  ces matrices sont précisément rejetées par le seuil CR < 0.10.

- **Domaine** : matrice réciproque positive. **Bornes** : w_i > 0, Σ w_i = 1.

### 2.3 Cohérence : λmax, CI, CR (`consistency_ratio`)

```
λmax ≈ moyenne_i( (A·w)_i / w_i )
CI   = (λmax − n) / (n − 1)
CR   = CI / RI(n)
```

λmax est lui-même une approximation de la valeur propre principale (moyenne du
quotient de Rayleigh par composante). Pour n ≤ 2, une matrice réciproque est
toujours cohérente : le code renvoie CR = 0.

Table des indices aléatoires RI de Saaty (`_RI`, n > 10 utilise RI(10)) :

| n | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|------|------|------|------|------|------|------|------|
| RI | 0.0 | 0.0 | 0.58 | 0.90 | 1.12 | 1.24 | 1.32 | 1.41 | 1.45 | 1.49 |

**Seuil de Saaty** : `CONSISTENCY_THRESHOLD = 0.10` — les jugements sont
exploitables si CR < 0.10 (`AHPResult.is_consistent`).

### 2.4 Échelle bipolaire UI → Saaty (`bipolar_to_saaty`)

L'UI expose un curseur bipolaire v ∈ {−8, …, +8} converti en jugement de Saaty :

```
v = 0  →  1            (importance égale)
v > 0  →  1 + v        (A plus important que B)
v < 0  →  1 / (1 + |v|) (B plus important que A)
```

- **Domaine** : v entier ∈ [−8, +8] (hors bornes → ValueError).
- **Bornes** : résultat ∈ [1/9, 9]. **Propriété** (lot 9.4) :
  `bipolar_to_saaty(−v) = 1 / bipolar_to_saaty(v)` — la réciprocité de Saaty est
  préservée par construction.

### 2.5 Note UI [1, 6] → échelle de Saaty [1, 9] (`score_6_to_9`)

```
s = 1 + (v − 1) · 8/5        (1 → 1, 6 → 9, linéaire)
```

- **Domaine** : v ∈ [1, 6] (hors bornes → ValueError). **Bornes** : s ∈ [1, 9].
- **Justification** : l'UI propose 6 niveaux de notation par critère ; la
  transformation affine les replace sur l'échelle [1, 9] attendue par
  `compute_ud` sans déformer les écarts relatifs.

### 2.6 Urgence déclarée (`compute_ud`)

```
Ud = ( Σ_j w_j·s_j  −  1 ) / 8,    puis clip sur [0, 1]
```

- **Domaine** : poids w (renormalisés défensivement à somme 1 par le code),
  notes s_j ∈ [1, 9] (hors bornes → ValueError).
- **Bornes** : Ud ∈ [0, 1] ; Ud = 0 ⟺ toutes les notes valent 1 ;
  Ud = 1 ⟺ toutes les notes valent 9 (lot 9.4).
- **Dérivation** : la moyenne pondérée Σ w_j·s_j vit dans [1, 9] (combinaison
  convexe de notes dans [1, 9]) ; la transformation affine (x − 1)/8 la ramène
  linéairement sur [0, 1]. **Décomposition exacte** (explicabilité, E8) :
  Ud = Σ_j κ_j avec κ_j = w_j·(s_j − 1)/8, additive sans résidu.

### 2.7 Lissage EMA du Ud (`ud_smoothed`)

```
Ud_t = ρ·Ud_{t−1} + (1 − ρ)·Ud_courant,     ρ = 0.3 (défaut)
```

- **Domaine** : ρ ∈ [0, 1] (sinon ValueError) ; si `prev` est None (premier
  questionnaire), Ud_t = Ud_courant sans lissage.
- **Bornes** : Ud_t ∈ [min(prev, courant), max(prev, courant)] (combinaison
  convexe — invariant du lot 9.4).
- **Justification** : amortit les variations brusques de perception d'une
  semaine à l'autre. **Convention d'écriture** : ici ρ est l'**inertie** (poids
  du passé) — le questionnaire courant pèse 1 − ρ = 0.7. À ne pas confondre avec
  l'EMA des événements (§7.1) où λ est la **réactivité** (poids de
  l'observation). ρ = 0.3 est un paramètre de gouvernance (PLAN §1) ; le service
  l'applique à chaque `submit_assessment` (orchestrateur, `rho_smoothing=0.3`).

---

## 3. Urgence réelle locale Ur_loc — six blocs KPI

Code : `supplyscore/core/ur_model.py` (`UrModel`). Chaque bloc produit une
urgence partielle u ∈ [0, 1] **ou None** quand les KPIs nécessaires manquent —
un bloc manquant est ignoré, jamais compté comme 0 ni comme 1.

Constantes du modèle (valeurs par défaut du dataclass, vérifiées) :

| Paramètre | Valeur | Rôle |
|---|---|---|
| `alpha_cap` | (0.4, 0.3, 0.3) | poids volume / poids / flux du bloc capacité |
| `beta_cost` | (0.5, 0.3, 0.2) | poids surcoût op / tarif / stockage du bloc coût |
| `t_ref_h` | 24.0 | horizon de référence (h) du bloc risque |
| `c_ref` | 1000.0 | coût de stockage de référence du bloc coût |
| `kappa_retard` | 0.5 | gain de pénalité de retard d'avancement (u_time v2) |
| `kappa_avance` | 0.2 | gain de bonus d'avance (u_time v2) |
| `omega` | tous à 1.0 | poids d'agrégation ω_m par bloc |
| `eps` | 1e-9 | garde-fou numérique des divisions |

### 3.1 u_time v1 — probabilité de retard (sans jalon actif)

Si le nœud n'a aucun jalon ACTIVE (liste None, vide, ou tous DONE/ABANDONED) :

```
u_time = P(L > d − t)        avec  L ~ Normale(μ, σ)
       = 1.0                 si t > d (deadline dépassée)
       = None                si d (deadline_h) ou μ (lead_time_h) manquent

P(L > x) = 0.5·(1 − erf( (x − μ) / (σ·√2) ))        (fonction de survie, via erf)
```

avec d = `time.deadline_h` (heures depuis t0 projet), μ = `time.lead_time_h`,
σ = `time.lead_time_std_h` si fourni, **sinon σ = 0.25·μ par défaut** ; si
σ ≤ 0, le lead time est déterministe : u = 1 si μ > d − t, sinon 0.

- **Domaine** : t en heures depuis t0 projet (cf. `project_hours`, §8.3).
- **Bornes** : u ∈ [0, 1] (survie d'une loi de probabilité, puis clip défensif).
- **Dérivation** : l'urgence temporelle est la probabilité que le délai
  d'approvisionnement L dépasse la marge restante (slack = d − t). À
  slack = μ, u = 0.5 exactement (médiane de la normale) ; à slack = μ + 1.96σ,
  u ≈ 0.025 (quantile classique).

### 3.2 u_time v2 — modulation par l'avancement du jalon actif

Si le nœud possède au moins un jalon ACTIVE, soit M* le **prochain jalon
actif** (jalon ACTIVE de `deadline_ts` minimale, §6.3), d* = (M*.deadline_ts −
t0_ts)/3600 et s* = (M*.start_ts − t0_ts)/3600 ses dates en heures projet :

```
si t > d* :   u_time = 1.0     (retard avéré)
sinon :
    u_base = P(L > d* − t)     (même loi normale qu'en v1 ;
                                u_base = 0.0 si lead_time_h est None)
    p_th   = clip01( (t − s*) / (d* − s*) )      (avancement théorique ;
                                                  1.0 si d* ≤ s*, cf. §6.4)
    r      = p_th − M*.progress                   ∈ [−1, 1]
    u_time = clip01( u_base + κ_retard·max(r, 0) − κ_avance·max(−r, 0) )
```

avec κ_retard = 0.5 et κ_avance = 0.2 (validés ≥ 0 au `__post_init__`).

- **Bornes** : u ∈ [0, 1] ; jamais None en v2 (le jalon fournit l'échéance).
- **Forme additive volontaire** : la contribution du glissement de planning
  κ_retard·max(r, 0) reste **isolable** du socle probabiliste u_base — choix
  d'explicabilité (E8) : la part du retard d'avancement se lit directement.
- **Asymétrie κ_retard > κ_avance** : un retard constaté (avancement déclaré
  sous le planning) est un signal plus fiable qu'une avance déclarée — l'avance
  est donc créditée plus prudemment (0.2 contre 0.5).
- **Choix documenté (code)** : si `lead_time_h` est None alors qu'un jalon est
  actif, u_base = 0.0 (et non None) — le jalon fournit l'échéance et
  l'avancement, la modulation planning s'applique quand même.
- **Limite** : u_time ne regarde que le prochain jalon actif ; un jalon
  lointain qui dérive reste invisible jusqu'à devenir le prochain (cf. §12).

### 3.3 u_cap — saturation capacitaire et déficit de flux

```
u_cap = clip01( Σ_disponibles α_k·terme_k / Σ_disponibles α_k )

terme_volume = 1 − volume_restant / volume_max     (si les deux KPIs présents, max > 0)
terme_poids  = 1 − poids_restant / poids_max       (idem)
terme_flux   = max( (demande − débit) / (demande + ε), 0 )   (si demande et débit présents)
```

avec α = (0.4, 0.3, 0.3) **renormalisés sur les termes effectivement
calculables** ; None si aucun terme n'est calculable. Les restes
(`remaining_volume_m3`, `remaining_weight_kg`, `domain/models.py`) sont déjà
bornés à ≥ 0 : un stock au-delà de la capacité donne un terme de saturation = 1.

- **Bornes** : chaque terme ∈ [0, 1] (le déficit de flux est ≤ 1 dès que le
  débit est ≥ 0), donc u_cap ∈ [0, 1] avant même le clip final.
- **Justification** : moyenne pondérée de trois signaux de saturation
  homogènes (ratios sans dimension) ; la renormalisation des α évite de diluer
  l'urgence quand un KPI manque.

### 3.4 u_perf — performance industrielle

```
u_perf = 1 − OEE,        OEE = disponibilité × performance × qualité
```

None si l'une des trois composantes OEE manque (`OEEKPIs.oee`,
`domain/models.py`). Chaque composante vit dans [0, 1]
(`domain/constraints.py`), donc u_perf ∈ [0, 1] (clip défensif au retour).
Le TRS (taux de rendement synthétique) est la mesure standard de l'efficacité
industrielle ; son complément à 1 est directement une urgence.

### 3.5 u_risk — exposition à la défaillance, enrichie

```
base   = 1 − exp( − p_défaillance · t_récup · sévérité / T_ref ),   T_ref = 24 h
u_risk = 1 − (1 − base)·(1 − env)·(1 − pol)        (composition OU probabiliste)
```

- **Valeurs neutres (code)** : composantes du noyau manquantes →
  p_défaillance → 0, t_récup → T_ref, sévérité → 1 ; None **seulement** si les
  trois composantes du noyau manquent **toutes** (les expositions env/pol
  seules ne déclenchent pas le bloc). Expositions manquantes → 0.
- **Bornes** : base ∈ [0, 1) (exponentielle d'un exposant ≤ 0) ; u ∈ [0, 1].
- **Dérivation** : l'exposant p·t_récup·sév/T_ref est une **espérance de temps
  d'indisponibilité pondérée par la gravité**, normalisée par l'horizon de
  référence T_ref = 24 h ; la forme 1 − e⁻ˣ est la probabilité qu'un processus
  de Poisson d'intensité x produise au moins un événement — saturation douce,
  croissante, sans dépassement. Les expositions environnementale et politique
  s'ajoutent en OU probabiliste : chaque exposition est une chance
  indépendante supplémentaire d'être en difficulté.

### 3.6 u_cost — dérive de coût, tarifs, stockage

```
u_cost = clip01( Σ_disponibles β_k·terme_k / Σ_disponibles β_k )

terme_op       = (coût_op − coût_nominal) / (coût_nominal + ε)    (PEUT ÊTRE NÉGATIF)
terme_tarif    = max(tarif − 1, 0)            (tarif = multiplicateur, 1 = neutre)
terme_stockage = coût_stockage / C_ref,        C_ref = 1000
```

avec β = (0.5, 0.3, 0.2) renormalisés sur les termes disponibles ; None si
aucun terme n'est calculable.

- **Bornes** : le terme_op vit dans [−1, +∞) (coûts ≥ 0,
  `domain/constraints.py`), les autres dans [0, +∞) ; la moyenne pondérée est
  ensuite **clippée sur [0, 1]**.
- **Décision n°2 (§9.2)** : la dérive négative (économie opérationnelle) est
  **autorisée à compenser** tarif et stockage avant le clip — comportement
  voulu et documenté.

### 3.7 u_co2 — dépassement de la cible carbone

```
u_co2 = clip01( (total − cible) / (max − cible + ε) )
total = op_emission_g_h + energy_mix_g_h     (somme des composantes présentes)
```

None si total, cible (`co2_target_g_h`) ou max (`co2_max_g_h`) manquent.

- **Bornes** : 0 sous la cible, 1 au-delà du plafond, interpolation linéaire
  entre les deux. Cas dégénéré max ≤ cible : le dénominateur tombe à ~ε et la
  formule devient un quasi-échelon (0 sous la cible, 1 dessus).

### 3.8 Agrégation — OU probabiliste pondéré (`ur_local`)

```
Ur_loc = 1 − Π_m (1 − u_m)^{ω_m}        sur les blocs m non-None de poids ω_m > 0
       = 0.0                            si tous les blocs sont None
```

puis application des règles de statut (§6.1) : la valeur retournée passe par
`effective_ur_local(status, agrégat)` — DONE → 0.0, ABANDONED → 1.0.

- **Domaine** : u_m ∈ [0, 1] (chaque u_m est re-clippé avant exponentiation),
  ω_m ≥ 0 (validés au `__post_init__` ; bloc inconnu rejeté).
- **Bornes** : Ur_loc ∈ [0, 1].
- **Dérivation** : si chaque bloc est lu comme une probabilité indépendante
  « ce bloc rend le nœud urgent », alors 1 − Π(1 − u_m) est la probabilité
  qu'**au moins un** bloc le rende urgent (OU probabiliste, *noisy-OR* des
  réseaux bayésiens — cf. revue BN, §11). L'exposant ω_m généralise : ω_m = 0
  éteint le bloc, ω_m > 1 l'amplifie ((1−u)^ω décroît), ω_m < 1 l'atténue.
- **Propriétés** (lot 9.2) : un seul bloc saturé (u_m = 1, ω_m > 0) suffit à
  rendre Ur_loc = 1 ; croissante en chaque u_m ;
  Ur_loc ≥ max_m(1 − (1 − u_m)^{ω_m}) (l'OU domine chaque contribution) ;
  blocs manquants ignorés (≠ pessimisme, ≠ optimisme : agnosticisme).
- **Décomposition exacte (E8)** : en posant ℓ_m = −ω_m·ln(1 − u_m) ≥ 0,
  Ur_loc = 1 − exp(−Σ ℓ_m) et la part exacte du bloc m est ℓ_m / Σ_k ℓ_k
  (additive dans l'espace log-survie, somme 1).

### 3.9 Fonctions auxiliaires (hors pipeline Ur_loc)

Trois fonctions de `ur_model.py` ne participent pas à l'agrégation mais font
partie du modèle :

- **`ur_singularity(t, tc, K=1, eps_min=1e-9)`** — urgence temporelle à
  singularité finie (Sornette & Johansen 2001, bulles à temps critique) :
  `tanh(K / max(tc − t, ε))` avant tc (divergence hyperbolique écrasée par tanh
  pour rester dans [0, 1]), `1 + K·(t − tc)` après tc (la tâche en retard
  dépasse 1 et croît linéairement). C'est la **seule** source possible de
  Ur > 1 du modèle ; le pipeline `ur_local` ne l'utilise pas (ses sorties sont
  clippées [0, 1]), mais `adequation_asym` et `effective_ur_local` acceptent
  Ur > 1 par contrat.
- **`ud_hyperbolic(t, tc, k=0.05)`** — urgence *perçue simulée* par
  actualisation hyperbolique (Mazur) : `1 / (1 + k·max(tc − t, 0))` — l'humain
  sous-pondère les échéances lointaines puis « se réveille » près de tc. Sert
  au générateur de données simulées, pas au calcul du Ud réel (qui vient du
  questionnaire AHP).
- **`filtered_error(ud, ur, eps_tol)`** — erreur Ud − Ur filtrée par zone
  morte : `sign(Ud−Ur)·max(|Ud−Ur| − eps_tol, 0)` — les écarts plus petits que
  eps_tol sont du bruit.

---

## 4. Propagation sur le graphe

Code : `supplyscore/graph/propagation.py` (`PropagationEngine`). Le réseau est
un DAG d'arcs orientés **fournisseur → client** (`SupplyArc.source_id` =
fournisseur de rang r+1, `target_id` = client de rang r). Coefficients par arc
(défauts, `domain/models.py`) : γ = 0.5 (intensité de dépendance Ud), β = 0.5
(propagation Ur), δ = 1.0 (criticité de choc — porté par le modèle mais
**inutilisé** par la propagation actuelle, réservé E15).

### 4.1 Ud — propagation DESCENDANTE (le besoin tire l'amont)

```
Ud_i = clip01( 1 − (1 − Ud_loc_i^eff) · Π_{k ∈ Succ(i)} (1 − γ_ik·Ud_k) )
```

Succ(i) = les **clients** de i. Calcul en ordre topologique **inverse** : le
client final (rang 0, aucun successeur, Ud = Ud_loc) est résolu d'abord, puis
le besoin descend vers les fournisseurs profonds. Ud_loc_i^eff =
`effective_ud_local(status, ud_local)` — le statut n'écrase PAS le besoin
déclaré (décision n°1, §9.1) ; None → 0.

### 4.2 Ur — propagation MONTANTE (le risque remonte l'aval)

```
Ur_i = clip01( 1 − (1 − Ur_loc_i^eff) · Π_{j ∈ Pred(i)} (1 − β_ji·Ur_j) )
```

Pred(i) = les **fournisseurs** de i. Calcul en ordre topologique direct : les
fournisseurs profonds (rang N, aucun prédécesseur, Ur = Ur_loc) sont résolus
d'abord, puis le risque remonte vers le client final. Ur_loc_i^eff =
`effective_ur_local(status, ur_local)` — DONE → 0.0, ABANDONED → 1.0 (§6.1),
appliqué AVANT la propagation.

### 4.3 Propriétés et mécanique

- **Même structure OU probabiliste** que l'agrégation des blocs (§3.8) : le
  nœud est urgent si son urgence locale OU au moins un voisin pondéré le rend
  urgent. β·Ur_j ∈ [0, 1] garantit chaque facteur dans [0, 1].
- **Bornes** : toutes les valeurs propagées sont clippées dans [0, 1].
- **Ordre topologique** : garanti par l'acyclicité du DAG ; chaque nœud est
  calculé après tous ses voisins requis (une seule passe par direction —
  pas de point fixe itératif). Stabilité : l'ordre d'insertion des nœuds ne
  change pas le résultat (lot 9.3).
- **Arcs backup (`ArcKind.BACKUP`) : INERTES.** Le moteur ne parcourt que les
  voisins nominaux (`predecessors`/`successors` du dépôt excluent les backup
  par défaut, `topological_order` les ignore aussi). Ils n'influencent ni Ud,
  ni Ur, ni `simulate_shock` — purement documentaires.
- **`simulate_shock(i, v)`** — what-if pur : recalcule Ur avec
  `ur_local(i)` remplacé par clip01(v), retourne {nœud: ΔUr} (choqué −
  référence), **ne persiste rien**. Choc à la valeur courante ⇒ deltas
  exactement nuls (lot 9.3). La non-additivité des chocs combinés est une
  propriété assumée du OU probabiliste (cf. cas E15 : chocs B et C sur la
  chaîne C→B→A, ΔUr_A(B∪C) ≠ ΔUr_A(B) + ΔUr_A(C)).
- **`apply_status`** pose un statut **sans** propager ; la propagation est
  re-déclenchée par l'orchestrateur (`evaluate_all`), unique point de
  propagation.
- **Décomposition explicative (spécifiée en E8)** : ℓ_loc = −ln(1 − Ur_loc_i),
  ℓ_j = −ln(1 − β_ji·Ur_j) ; part locale = ℓ_loc/Σ, part du fournisseur j =
  ℓ_j/Σ, part propagée totale = Σ_j ℓ_j / (ℓ_loc + Σ_j ℓ_j). Symétrique pour Ud
  avec γ_ik·Ud_k.

**Référence** : la propagation multi-rangs atténuée formalise l'effet ripple
(Ivanov et al., §11) ; la structure produit-de-survies est celle des modèles
Markov/DBN de disruption (§11), figée ici en une passe déterministe.

---

## 5. Adéquation A, fausse urgence F, risque caché H

Code : `supplyscore/core/adequation.py` (`AdequationEngine`). Référence :
Kahneman & Tversky (1979, Prospect Theory ; 1992, Cumulative Prospect Theory).

### 5.1 Pathologies élémentaires

```
F = [Ud − Ur]₊ = max(Ud − Ur, 0)      fausse urgence  (panique injustifiée)
H = [Ur − Ud]₊ = max(Ur − Ud, 0)      risque caché    (danger invisible)
```

**Propriétés** (lot 9.5) : F ≥ 0, H ≥ 0, F·H = 0 (jamais les deux à la fois),
F − H = Ud − Ur exactement. Mesure naïve associée :
`adequation_simple = 1 − min(|Ud − Ur|, 1)` ∈ [0, 1].

### 5.2 Score asymétrique (`adequation_asym`)

```
e_under = [Ur − Ud]₊        e_over = [Ud − Ur]₊
penalty = λ_under·e_under^α + λ_over·e_over^α
A = 100 · ( e^{−penalty} − e^{−max_penalty} ) / ( 1 − e^{−max_penalty} )
max_penalty = max(λ_under, λ_over)
A = 0.0  dès que  e^{−penalty} ≤ e^{−max_penalty}
```

Paramètres de gouvernance (constants, PLAN §1) : **λ_under = 2.25,
λ_over = 1.0, α = 0.88**. Validation (code) : λ > 0, α ∈ (0, 1], surcharges
ponctuelles re-validées.

- **Domaine** : Ud ∈ [0, 1] ; Ur ≥ 0, peut dépasser 1 (tâche très en retard,
  §3.9) — alors penalty > max_penalty et A = 0.
- **Bornes** : A ∈ [0, 100] ; A = 100 ⟺ Ud = Ur (penalty = 0) ; A = 0 atteint
  exactement pour un écart de 1 dans la direction la plus pénalisée
  (Ud = 0, Ur = 1).
- **Dérivation** : la pénalité est une **fonction de valeur de Prospect
  Theory** appliquée à l'écart |Ud − Ur| : courbure psychophysique x^α avec
  α = 0.88 (sensibilité décroissante — un écart qui passe de 0 à 0.1 pèse plus
  que de 0.8 à 0.9), et coefficient d'aversion à la perte λ = 2.25 — les deux
  valeurs **mesurées** par Tversky & Kahneman (1992). e^{−penalty} ramène la
  pénalité dans (0, 1] ; la normalisation affine (soustraction du plancher
  e^{−max_penalty}, division par 1 − e^{−max_penalty}) étire exactement
  l'image sur [0, 100].
- **Gouvernance — pourquoi λ_under > λ_over** : la sous-estimation (Ur > Ud,
  risque caché) doit coûter plus cher que la surestimation (fausse urgence).
  Une équipe qui sur-réagit gaspille des ressources ; une équipe qui
  sous-estime découvre la rupture quand il est trop tard. **Le danger
  invisible est pire que la panique.** Conséquence testée :
  A(Ud=0.2, Ur=0.8) < A(Ud=0.8, Ur=0.2).

`evaluate(ud, ur)` retourne un `UrgencyState` partiel (ud, ur, adequation,
false_urgency, hidden_risk) ; les champs propagés restent à la charge du
module graphe.

---

## 6. Statuts et jalons

### 6.1 Règles de statut — source de vérité unique (`core/status_rules.py`)

```
effective_ur_local(status, ur_local) :
    DONE       → 0.0    (une tâche finie n'est plus urgente ; contribution montante nulle)
    ABANDONED  → 1.0    (une tâche abandonnée est une urgence maximale pour tout l'aval)
    sinon      → ur_local si non-None, 0.0 sinon (pas de mesure = pas d'urgence connue)

effective_ud_local(status, ud_local) :
    → ud_local si non-None, 0.0 sinon — le statut N'ÉCRASE PAS le besoin déclaré
      (décision n°1, §9.1 : comportement conservé)
```

Fonctions **pures** : elles ne modifient jamais le `ur_local`/`ud_local` stocké,
elles calculent la valeur EFFECTIVE utilisée par les agrégations (§3.8) et la
propagation (§4). Cette centralisation remplace une triple duplication
historique (faiblesse #3 du registre v1). Note de contrat : `effective_ur_local`
laisse passer un ur_local > 1 (cas singularité, §3.9) — le clip relève de
l'appelant.

### 6.2 Statut du nœud dérivé des jalons — règle PESSIMISTE (`derive_node_status`)

Le cahier des charges d'un nœud définit N jalons datés (`Milestone` : kind
proto/série/livraison/custom, `start_ts` < `deadline_ts`, statut
ACTIVE/DONE/ABANDONED, avancement déclaré `progress` ∈ [0, 1]). Le statut
global du nœud DÉRIVE des jalons par la table de vérité **implémentée** :

```
liste vide                        → None        (statut manuel conservé, rétro-compatibilité)
≥ 1 jalon ACTIVE                  → ACTIVE
sinon, ≥ 1 jalon ABANDONED        → ABANDONED   (règle PESSIMISTE)
sinon (tous DONE)                 → DONE
```

**Justification de la règle pessimiste** : un jalon abandonné **teinte le
nœud** — le périmètre contractuel n'a pas été rempli, donc le risque transmis à
l'aval est maximal (ABANDONED → Ur_loc^eff = 1, §6.1), même si d'autres jalons
ont été livrés. C'est aussi ce qui rend l'action utilisateur « abandonner le
nœud » **cohérente** : abandonner les jalons restants d'un nœud dont un jalon
antérieur était déjà DONE doit produire un nœud ABANDONED, pas un nœud
faussement DONE.

### 6.3 Prochain jalon actif (`next_active_milestone`)

```
M* = argmin_{m ∈ jalons, m.status = ACTIVE} m.deadline_ts        (None si aucun ACTIVE)
```

Les jalons DONE/ABANDONED sont ignorés : seuls les jalons actifs portent une
échéance à venir. C'est sur M* que se calcule u_time v2 (§3.2).

### 6.4 Avancement théorique (`theoretical_progress`)

```
p_th = clip01( (now_ts − start_ts) / (deadline_ts − start_ts) )
p_th = 1.0   si deadline_ts ≤ start_ts   (fenêtre dégénérée : aurait déjà dû être fini)
```

Interpolation linéaire : 0 avant le début planifié, 1 après l'échéance. C'est
le planning de référence contre lequel l'avancement déclaré est comparé
(r = p_th − progress, §3.2).

---

## 7. Événements calibrés

Code : `supplyscore/domain/events.py` — module **pur** (les impacts sont
calculés et retournés, jamais appliqués ici). Chaque valeur produite est bornée
par `clamp_kpi_value` contre la table `KPI_CONSTRAINTS`
(`domain/constraints.py`).

### 7.1 Les opérateurs de calibration

**BAYES — révision Beta-Bernoulli** (`bayes_update`), pour
`risk.failure_probability` :

```
BAYES(p, k, n) = (p·N₀ + k) / (N₀ + n),       borné dans [1e-4, 0.99]
N₀ = 26 pseudo-observations
```

- **Dérivation** : prior conjugué Beta(α, β) avec α = p·N₀, β = (1−p)·N₀ ;
  l'événement = n observations de Bernoulli dont k défaillances ; la moyenne a
  posteriori est exactement (α + k)/(α + β + n) = (p·N₀ + k)/(N₀ + n).
- **Sémantique auditable** : « cet événement équivaut à observer k
  défaillances sur n essais ». k peut être fractionnaire (demi-défaillance).
- **N₀ = 26** : le prior pèse ~6 mois d'observations hebdomadaires — mémoire
  courte mais pas amnésique : un événement isolé déplace la probabilité sans
  l'écraser, et la décroissance hebdomadaire reste douce.
- **Propriétés** (lot 9.5) : résultat ∈ (0, 1) — les bornes [1e-4, 0.99]
  interdisent 0 et 1, car une probabilité certaine rendrait toute révision
  future impossible (verrou bayésien) ; croissante en k ; **point fixe** si
  k/n = p (l'événement confirme le prior sans le déplacer).
- **Prior par défaut** : si le KPI n'est pas renseigné, p = 0.02
  (`DEFAULT_FAILURE_PRIOR`, ≈ une défaillance toutes les ~50 semaines),
  documenté dans la règle d'audit.

**EMA — lissage exponentiel** (`ema_update`) :

```
EMA(old, obs, λ) = (1 − λ)·old + λ·obs ;     old = None → obs (initialisation)
```

λ est la **réactivité** (poids de l'observation), 0.3–0.5 selon le KPI —
convention inverse du ρ du lissage Ud (§2.7).

**DIRECT** : la valeur observée remplace ou ajuste l'ancienne (faits signés :
nouveau tarif, surcoût constaté, demande remplacée).

**CLIQUET** (variante de DIRECT) : `max(ancien ou 0, niveau)` — modélise les
expositions qui ne redescendent pas spontanément (risque politique, sévérité,
exposition environnementale).

### 7.2 Décroissance hebdomadaire (`weekly_decay`)

```
p ← BAYES(p, k=0, n=1)        (un impact par semaine ; [] si p est None)
```

Une semaine écoulée sans défaillance est une observation favorable qui érode
doucement la probabilité (jamais sous 1e-4). Exemple : p = 0.02 →
0.52/27 = 0.01926.

### 7.3 Table complète des 14 types (`EVENT_CALIBRATION`, vérifiée contre les handlers)

Constantes de gravité : panne/accident BAYES (k, n) — mineure (0.5, 1),
majeure (1, 1), critique (2, 2) ; alerte financière BAYES — surveillée
(0.5, 1), procédure (1, 1), défaut (3, 3) ; sévérité forfaitaire accident —
0.4/0.7/1.0 ; alerte financière — 0.3/0.6/0.9. `WEEK_HOURS = 168` (168 h
d'arrêt = semaine entièrement perdue). Champs strictement positifs :
durées, retards, nouvelle demande.

| Type | Champs de saisie | Impacts KPI (opérateur — formule) |
|---|---|---|
| `panne_machine` | durée d'arrêt (h), gravité | `risk.failure_probability` ← BAYES(k, n) gradué ; `risk.recovery_time_h` ← EMA(durée, λ=0.4) ; `oee.availability` ← EMA(max(0, 1 − durée/168), λ=0.3) |
| `retard_fournisseur` | retard constaté (h) | `time.lead_time_h` ← EMA(ancien + retard, λ=0.4) (obs = retard si ancien None) ; `time.lead_time_std_h` ← EMA(retard, λ=0.3) |
| `greve` | durée prévue (h), part de l'effectif ∈ [0, 1] | `oee.availability` ← DIRECT : ancien × (1 − part·min(durée/168, 1)) (ignoré si None) ; `risk.severity` ← CLIQUET(part) |
| `hausse_tarif` | variation % ∈ [−100, +500] | `cost.tariff` ← DIRECT : base × (1 + pct/100) (base 1 si None) ; `risk.cost_volatility` ← EMA(min(\|pct\|/100, 1), λ=0.3) |
| `rupture_matiere` | durée prévue (h), criticité ∈ [0, 1] | `inventory.flow_rate` ← DIRECT : ancien × (1 − criticité) (ignoré si None) ; `risk.failure_probability` ← BAYES(k=criticité, n=1) ; `risk.severity` ← CLIQUET(criticité) |
| `accident` | durée d'arrêt (h), gravité | BAYES(k, n) gradué ; `risk.recovery_time_h` ← EMA(durée, λ=0.5, réactif) ; `risk.severity` ← CLIQUET(0.4/0.7/1.0) |
| `non_conformite_qualite` | taux de rebut ∈ [0, 1] | `oee.quality` ← EMA(1 − taux, λ=0.4) |
| `perturbation_transport` | retard (h), surcoût (€) | `time.lead_time_h` ← EMA(ancien + retard, λ=0.4) ; `cost.op_cost` ← DIRECT : base + surcoût (base 0 si None) |
| `instabilite_politique` | niveau ∈ [0, 1] | `risk.political_risk` ← CLIQUET(niveau) |
| `cyber_incident` | durée d'arrêt (h) | BAYES(k=1, n=1) (défaillance franche) ; `oee.availability` ← EMA(max(0, 1 − durée/168), λ=0.3) |
| `hausse_energie` | variation % ∈ [−100, +500] | `cost.op_cost` ← DIRECT : ancien × (1 + pct/100) (ignoré si None) ; `risk.cost_volatility` ← EMA(min(\|pct\|/100, 1), λ=0.3) |
| `alerte_financiere_fournisseur` | gravité (surveillée/procédure/défaut) | BAYES gradué jusqu'à (3, 3) ; `risk.severity` ← CLIQUET(0.3/0.6/0.9) |
| `perte_capacite` | part de volume perdu ∈ [0, 1] | `inventory.max_volume_m3` ← DIRECT : ancien × (1 − pct) (ignoré si None) ; `risk.env_exposure` ← CLIQUET(pct) |
| `pic_demande` | nouvelle demande > 0 | `network.demand` ← DIRECT : remplacement (fait signé) |

Validation des paramètres (code) : champ inconnu/manquant rejeté, valeurs non
finies (NaN, ±inf) rejetées, bornes min/max des champs respectées, choix hors
liste rejetés. Chaque `KpiImpact` porte la règle appliquée en clair (chaîne
française avec les paramètres effectifs) — exigence d'auditabilité.

---

## 8. Cycle hebdomadaire ISO et horloge

### 8.1 Horloge bimodale (`core/clock.py`)

Trois implémentations du protocole `Clock` (epoch secondes) :

- `SystemClock` — temps réel (`time.time()`) ;
- `FixedClock` — temps figé pilotable (tests, scénarios déterministes) ;
- `GameClock` — mode « jeu » (serious game) : `now = start_ts +
  weeks_elapsed × 604 800` ; le temps avance par semaines entières
  (`advance_weeks`), état (start_ts, weeks_elapsed) sérialisable JSON.
  Chaque projet choisit son horloge (réelle ou de jeu) via le service.

### 8.2 Semaine ISO (`iso_week`)

```
iso_week(ts) = « AAAA-Sxx »   (isocalendar() en HEURE LOCALE du poste, zéro-paddé)
```

L'année affichée est l'**année ISO**, qui peut différer de l'année civile
(le 2021-01-01 appartient à « 2020-S53 »).

### 8.3 Temps projet (`project_hours`)

```
t = (ts − t0_ts) / 3600        (heures depuis l'origine du projet, négatif avant t0)
```

Pont entre l'horloge applicative (epoch s) et le « t » des formules du cœur
(§3), qui raisonnent en heures depuis t0. L'origine effective d'un projet est
`t0_ts` s'il est posé, sinon `created_at` (`Project.origin_ts`).

### 8.4 Écart entre semaines ISO (`services/weekly.py`, `semaines_ecart`)

```
semaines_ecart(a, b) = ( lundi(b) − lundi(a) ).days // 7        (signé, b − a)
lundi(« AAAA-Sxx ») = datetime.fromisocalendar(AAAA, xx, 1)
```

Exact aux bords d'année ISO : `("2020-S53", "2021-S01") → 1`.

### 8.5 Statut hebdomadaire d'un nœud (`CycleHebdomadaire`)

Définitions figées (Lot 4.1), la « semaine courante » étant celle de l'horloge
du **projet du nœud** :

- **à jour** : il existe une évaluation AHP dont `iso_week` = semaine courante
  (le code accepte aussi `retard ≤ 0`, garde-fou si l'horloge a reculé) ;
- **en retard** : la dernière évaluation date d'une semaine strictement
  antérieure ; `semaines_de_retard = semaines_ecart(dernière, courante) > 0` ;
- **manquant** : aucune évaluation.

La **couverture** d'un projet = (nœuds ACTIVE à jour, nœuds ACTIVE) — les
nœuds DONE/ABANDONED sont exclus du numérateur et du dénominateur, mais
`statut_noeud` répond quand même pour eux. Aucune dégradation automatique du
Ud, aucun e-mail : le cycle **constate**, il n'agit pas.

---

## 9. Décisions de modélisation

Section normative : les deux ambiguïtés sémantiques relevées par l'audit v1
(faiblesses #11 et #12 du PLAN §3) sont tranchées ici. Le code actuel
implémente déjà les deux comportements retenus — **aucune modification de code
n'est requise** par ces décisions.

### 9.1 Décision n°1 — nœud DONE et propagation : comportement CONSERVÉ

**Constat (code)** : un nœud DONE a `Ur_loc^eff = 0` (§6.1) mais la formule
montante (§4.2) reste `Ur_i = 1 − (1 − 0)·Π_j(1 − β_ji·Ur_j)` : le nœud
**transmet intégralement l'urgence de ses fournisseurs vers l'aval** (les
facteurs des prédécesseurs ne sont pas neutralisés). Symétriquement,
`effective_ud_local` ignore le statut : le `ud_local` d'un nœud DONE
**continue de se propager** vers ses fournisseurs.

**DÉCISION : comportement CONSERVÉ.** Justification :

- le **flux physique existe encore** : les pièces déjà livrées par ce nœud
  transitent dans le réseau ; marquer la tâche « terminée » n'efface ni les
  dépendances aval ni l'exposition de l'aval aux fournisseurs amont ;
- un nœud terminé **n'est pas un coupe-circuit** : si son fournisseur est en
  difficulté, le client aval reste exposé (reprises, garanties, lots
  suivants) — couper la transmission au premier DONE rendrait l'aval
  artificiellement aveugle ;
- côté Ud, le besoin déclaré historique reste une information de demande
  réelle pour l'amont tant que le nœud existe dans le graphe.

**Conséquence opérationnelle (à documenter partout où le statut s'édite)** :
pour **isoler** un nœud du calcul, il faut le **supprimer ou couper ses arcs**
— pas le marquer DONE. DONE signifie « ma tâche locale n'émet plus d'urgence
propre », pas « je déconnecte ma branche ».

### 9.2 Décision n°2 — u_cost : la dérive négative compense, COMPENSATION AUTORISÉE

**Constat (code)** : dans `u_cost` (§3.6), le terme de dérive
`(op_cost − nominal)/(nominal + ε)` peut être **négatif** (économie
opérationnelle : op_cost < nominal) et vient en déduction des termes tarif et
stockage dans la moyenne pondérée, **avant** le clip final [0, 1].

**DÉCISION : compensation AUTORISÉE et documentée.** Justification :

- une économie opérationnelle réelle **réduit légitimement la tension coût
  globale** du nœud : le bloc u_cost mesure une pression économique nette, pas
  une somme de pénalités indépendantes ;
- le **clip [0, 1] borne l'effet** : une économie ne peut pas rendre l'urgence
  coût négative, ni masquer autre chose que les termes du même bloc (les cinq
  autres blocs et l'agrégation OU restent intacts) ;
- l'alternative `max(drift, 0)` aurait ignoré une information vraie et
  signée — contraire au principe « documenter le réel » du modèle.

---

## 10. Table des cas de référence chiffrés

Traçabilité croisée : chaque ligne donne la formule instanciée et sa source de
vérification. « Test existant » = assertion déjà dans la suite ; « lot 9.x /
E8 » = cas chiffré du PLAN couvert par les tests de propriétés écrits en
parallèle de ce document — chaque valeur a été **recalculée à la main contre le
code** lors de la rédaction.

| # | Cas | Calcul instancié (code) | Valeur | Source |
|---|---|---|---|---|
| 1 | u_time v1, μ=100, σ=20, slack=100 | P(L > 100), L ~ N(100, 20) = survie à la moyenne | **0.5** (exact) | lot 9.2 (`tests/property/test_prop_ur_model.py`) |
| 2 | u_time v1, slack = μ + 1.96σ = 139.2 | P(L > 139.2), L ~ N(100, 20) | 0.0250 ± 5e-4 | lot 9.2 |
| 3 | u_time v2, d\*=100 h, s\*=0, lead 50, σ=10, t=40, progress = p_th = 0.4 | u_base = 1 − Φ(1) | 0.1587 | `tests/test_u_time_v2.py` (existant) |
| 4 | u_time v2, idem, **progress = 0.1** | r = 0.4 − 0.1 = 0.3 → 0.1587 + 0.5×0.3 | **0.3087** | `tests/test_u_time_v2.py::test_progress_en_retard_penalite` (existant) |
| 5 | u_time v2, idem, progress = 0.9 | r = −0.5 → 0.1587 − 0.2×0.5 | 0.0587 | `tests/test_u_time_v2.py` (existant) |
| 6 | u_perf, OEE = 0.9³ = 0.729 | 1 − 0.729 | **0.271** | lot 9.2 |
| 7 | u_risk, fp=0.1, rt=24, sev=1, T_ref=24 | 1 − e^{−0.1·24·1/24} = 1 − e^{−0.1} | **0.0951626** | lot 9.2 |
| 8 | u_risk idem + env = 0.2 | 1 − 0.9048374 × 0.8 | **0.2761301** | lot 9.2 |
| 9 | u_co2, total=900, cible=600, max=1000 | (900−600)/(1000−600) | **0.75** | lot 9.2 |
| 10 | OU probabiliste, deux blocs à 0.5, ω=1 | 1 − 0.5×0.5 | **0.75** | `tests/test_core_ur.py::test_or_probabiliste_combinaison` (existant) |
| 11 | A(Ud=1, Ur=0) — sur-déclaration maximale | 100·(e^{−1} − e^{−2.25})/(1 − e^{−2.25}) | **29.34** ± 0.01 | lot 9.5 (`tests/property/test_prop_adequation.py`) |
| 12 | A(Ud=0, Ur=1) — sous-estimation maximale | penalty = 2.25 = max_penalty → plancher | **0** (exact) | `tests/test_core_adequation.py::test_ecart_maximal_sous_estimation_0` (existant) |
| 13 | BAYES, p=0.02, panne **majeure** (k=1, n=1) | (0.02·26 + 1)/27 = 1.52/27 | **0.0563** | `tests/test_events_calibration.py` (existant) |
| 14 | BAYES, p=0.02, panne **critique** (k=2, n=2) | 2.52/28 | **0.09** | `tests/test_events_calibration.py` (existant) |
| 15 | BAYES, p=0.02, mineure (k=0.5, n=1) | 1.02/27 | 0.0378 | `tests/test_events_calibration.py` (existant) |
| 16 | Décroissance hebdo, p=0.02 | BAYES(0.02, 0, 1) = 0.52/27 | **0.01926** | `tests/test_events_calibration.py` (existant) |
| 17 | Hausse tarif +12 % sur tarif 1.05 | 1.05 × 1.12 | **1.176** | `tests/test_events_calibration.py::test_hausse_tarif_12_pct` (existant) |
| 18 | Chaîne C→B→A, β = (C→B : 0.5, B→A : 0.7), ur_loc = (A : 0.1, B : 0.3, C : 0.6) | Ur_B = 1 − 0.7·(1 − 0.5·0.6) = 0.51 ; Ur_A = 1 − 0.9·(1 − 0.7·0.51) | Ur_B = **0.51**, Ur_A = **0.4213** | `tests/test_graph_propagation.py` (existant) |
| 19 | Décomposition : Ur_loc = 0.2, un fournisseur Ur_j = 0.5, β = 0.8 | Ur_i = 1 − 0.8·0.6 = 0.52 ; part propagée = ln(0.6)/(ln(0.8) + ln(0.6)) | Ur_i = 0.52 ; part propagée = **0.696** | spec E8 (PLAN, `explain.py` à venir) — vérifiée contre la formule §4.2 |

---

## 11. Références

| Brique du modèle | Référence |
|---|---|
| AHP : matrice réciproque, vecteur de priorités, λmax/CI/CR, table RI | Saaty, T. L. (1977). *A scaling method for priorities in hierarchical structures*, J. Math. Psychology 15(3) ; Saaty (1980), *The Analytic Hierarchy Process*. |
| Adéquation asymétrique : λ = 2.25, α = 0.88, aversion à la perte | Kahneman, D. & Tversky, A. (1979). *Prospect Theory*, Econometrica 47(2) ; Tversky & Kahneman (1992). *Advances in Prospect Theory: Cumulative Representation of Uncertainty*, J. Risk and Uncertainty 5. |
| Urgence perçue simulée (actualisation hyperbolique, `ud_hyperbolic`) | Mazur, J. E. (1987). *An adjusting procedure for studying delayed reinforcement* (modèle hyperbolique 1/(1+kD)). |
| Urgence à singularité finie (`ur_singularity`) | Sornette, D. & Johansen, A. (2001). *Significance of log-periodic precursors to financial crashes* (singularités à temps fini). |
| Effet ripple / propagation multi-rangs (fonde Ud descendant / Ur montant) | Ivanov et al. — tandfonline.com/doi/full/10.1080/00207543.2025.2470348 ; pmc.ncbi.nlm.nih.gov/articles/PMC7546950 |
| Approche Markov + DBN de la disruption (structure produit-de-survies) | tandfonline.com/doi/abs/10.1080/00207543.2019.1661538 |
| Réseaux bayésiens pour le risque supply chain (revue ; noisy-OR §3.8) | pmc.ncbi.nlm.nih.gov/articles/PMC7305519 |
| BWM/FBWM + PROMETHEE (pondération des blocs Ur, Jalon 2 — meilleure cohérence que l'AHP au-delà de quelques critères, 2n−3 comparaisons) | link.springer.com/article/10.1007/s10668-023-04200-1 |
| Stress-test TTR/TTS (Simchi-Levi/MIT) — **écarté volontairement**, documenté comme extension future | sciencedirect.com/science/article/abs/pii/S0925527323001706 |
| Révision Beta-Bernoulli (événements, §7.1) | Conjugaison Beta-binomiale standard (voir p. ex. Gelman et al., *Bayesian Data Analysis*). |

Pratique commerciale (Everstream, Resilinc, Interos) : mapping multi-rangs et
scoring continu existent ; **aucune plateforme ne mesure l'adéquation
déclaré/réel (Ud vs Ur)** — c'est le différenciateur de SupplyScore.

## 12. Limites honnêtes du modèle

Condensé du PLAN §2 — ce que le système ne fera PAS :

1. **Pas de prédiction certaine** : probabilités, scores et intervalles — pas
   des prophéties. Un modèle reste une simplification du réel.
2. **Fraîcheur = cadence de saisie** : sans connecteur ERP (saisie manuelle
   assumée), un score n'est jamais plus à jour que le dernier questionnaire.
3. **L'AHP devient incohérent au-delà de ~7 critères** : il reste limité aux
   4 critères du Ud ; la pondération des blocs KPI (Ur) passera par FBWM
   (Jalon 2).
4. **Réversibilité d'un événement non garantie** si un autre processus a
   réécrit le KPI entre-temps : conflit explicite à résoudre manuellement,
   jamais de rebase « magique » des écritures postérieures.
5. **Les calibrations d'événements** (N₀ = 26, coefficients λ des EMA,
   pseudo-comptes k/n) sont défendables (conjugaison bayésienne standard) mais
   ne sont PAS des vérités mesurées : le serious game servira à les recaler.
6. **u_time ne regarde que le prochain jalon actif** : un jalon lointain qui
   dérive reste invisible jusqu'à devenir le prochain. L'interface (liste
   complète des jalons en entrée) permet une extension future (max pondéré),
   pas la formule v2 actuelle.
7. **« Jamais de perte de données » exige des tables d'audit inéditables**
   (`audit_log`, `urgency_history`, `kpi_snapshots`, `weekly_reviews`,
   `decisions`) — y compris dans la vue admin, sous peine d'effondrer la
   promesse d'audit.
8. **DataTable éditable limitée (~2 000 lignes visibles)** : le périmètre
   projet×bloc maintient < 600 lignes ; au-delà, plan B dash-ag-grid (E14).
9. **Double comptage possible** : un événement saisi ET une correction
   manuelle du même KPI la même semaine — garde-fou d'avertissement, pas
   d'interdiction (l'opérateur reste souverain).
10. **Le branchement du temps réel fait bouger les scores** : dès que
    l'horloge vit, les deadlines saisies deviennent « vraies » ; le mode par
    projet (réel/jeu) maîtrise la transition.

---

## 13. Définitions gelées : rupture, résultat opérationnel, état de risque

Section normative (HÉLIOS v7, journal des interventions — contrat n°9).
Code : `supplyscore/services/calibration.py` (fonction `issues_defavorables`,
extraite de `CalibrationService._causes`) et
`supplyscore/services/interventions.py` (`InterventionJournal`). Ces trois
définitions sont GELÉES : elles ne se redéfinissent nulle part ailleurs dans
le système — tout code qui a besoin de l'une d'elles importe la fonction ou
le module cité, il ne duplique jamais la logique.

**Rupture (« issue défavorable »)** : la définition EXISTANTE de
`CalibrationService` — jalon raté OU nœud abandonné OU événement
critique/défaut non annulé dans la fenêtre. Une seule définition dans tout
le système (le module fait référence, la logique n'est jamais dupliquée —
`CalibrationService._causes` délègue à la fonction pure
`issues_defavorables`, réutilisée telle quelle par
`InterventionJournal.proposer_resultat`).

**Résultat opérationnel** (label causal, model-free), fenêtre
`[date_effet, +4 sem.]` : `'resolu'` = aucune issue défavorable ET
l'objectif opérationnel déclaré à l'ouverture est atteint ; `'partiel'` =
amélioration du KPI cible sans atteinte ; `'echec'` = issue défavorable ou
aucune amélioration ; `'en_cours'`.

**État de risque** (sortie d'alerte, ΔP, ΔUr) : information d'interface,
JAMAIS un label d'apprentissage.

### 13.1 Implémentation — `issues_defavorables` (rupture, réutilisée telle quelle)

`issues_defavorables(node, debut_ts, fin_ts, milestones, now_ts, evenements)`
est la fonction PURE extraite de `CalibrationService._causes` (§7, §11.1) —
elle applique EXACTEMENT les trois critères figés du lot 11.1 sur une fenêtre
temporelle brute `[debut_ts, fin_ts[` (bornes en secondes epoch, pas
nécessairement alignées sur un lundi ISO) :

```
(a) jalon raté   : deadline_ts ∈ [debut_ts, fin_ts[ ET
                    (statut = ABANDONED OU (statut = ACTIVE ET deadline_ts < min(fin_ts, now_ts)))
(b) nœud abandonné : node.status = ABANDONED (statut COURANT, proxy — même
                      limite documentée qu'en §7/CalibrationService)
(c) événement       : occurred_at ∈ [debut_ts, fin_ts[, reverted_at = NULL,
                       gravité ∈ {"critique", "defaut"}
```

`CalibrationService._causes` calcule sa fenêtre ISO-semaine `[lundi(S+1),
lundi(S+horizon+1)[` puis délègue à `issues_defavorables` — comportement
INCHANGÉ (§7, §11.1). `InterventionJournal.proposer_resultat` calcule sa
fenêtre directement depuis `date_effet_ts` (§13.2) et délègue à la MÊME
fonction : la rupture d'une intervention et la rupture mesurée par la
calibration sont, au sens strict, LA MÊME définition appliquée à deux
fenêtres différentes.

### 13.2 Implémentation — résultat opérationnel de l'intervention

`InterventionJournal.proposer_resultat` calcule la fenêtre
`[date_effet_ts, date_effet_ts + 4 × 604 800[` (4 semaines pleines, ancrée
sur `date_effet_ts` — PAS sur un lundi ISO, à la différence de la
calibration) puis applique la table de décision suivante, dans l'ordre :

```
1. executee = False (explicite)              -> 'echec'
2. date_effet_ts = None                       -> 'en_cours' (fenêtre pas ouverte)
3. issues_defavorables(...) non vide           -> 'echec' (causes = la liste)
4. now_ts < fin_ts (fenêtre pas close)         -> 'en_cours'
5. sinon : jalons du nœud dont l'échéance ∈ fenêtre
     - au moins un DONE                        -> 'resolu'
     - sinon                                   -> 'partiel'
```

**Proxy model-free de l'atteinte de l'objectif (étape 5)** : le contrat n°9
ne fige pas de représentation structurée de l'objectif opérationnel
(`objectif_operationnel` est un texte libre saisi à l'ouverture) — il n'existe
donc pas d'oracle qui vérifie automatiquement qu'un texte libre est «
atteint ». `proposer_resultat` utilise le seul signal FACTUEL et model-free
disponible via les jalons/événements de la façade : un jalon du nœud livré
(DONE) dont l'échéance tombe DANS la fenêtre de l'intervention. C'est une
LIMITE ASSUMÉE, dans l'esprit de la limite (b) de `issues_defavorables` :
faute de mieux, un proxy explicite et documenté plutôt qu'un silence — un
nœud sans jalon exploitable dans la fenêtre ne peut jamais se voir proposer
`'resolu'` automatiquement, seulement `'partiel'` (avec une cause explicite
invitant l'opérateur à trancher). L'étape 5 ne peut structurellement PAS
laisser subsister de jalon ACTIVE dans la fenêtre une fois qu'elle est close
sans issue défavorable : un tel jalon aurait déjà déclenché la cause « jalon
non livré à son échéance » à l'étape 3 (même définition, §13.1) — seuls des
jalons DONE peuvent donc rester à l'étape 5.

**Ce que `proposer_resultat` NE fait JAMAIS** : lire `Ud`, `Ur`, `H`
(`hidden_risk`), `false_urgency` ou `adequation` — même indirectement. Le
résultat opérationnel est un label CAUSAL construit uniquement à partir de
faits vérifiables (jalons, événements, statut du nœud, déclaration explicite
`executee`). C'est la contrepartie directe de la définition suivante.

### 13.3 État de risque — séparation stricte de colonnes

Le contrat n°9 porte DEUX paires de colonnes distinctes sur la table
`interventions` :

- `etat_avant_json` / `etat_apres_json` — état OBSERVABLE (`ur_local`,
  `ud_local`, `hidden_risk`, `false_urgency`, et `p_issue` si fourni par
  l'appelant) capturé à l'ouverture et à la clôture ; c'est le contexte
  chiffré de l'intervention, jamais consulté par `proposer_resultat` ;
- `etat_risque_avant_json` / `etat_risque_apres_json` — snapshot COMPLET de
  `node.urgency` (`ud_local`, `ur_local`, `ud`, `ur`, `adequation`,
  `false_urgency`, `hidden_risk`), capturé AUTOMATIQUEMENT (jamais
  surchargeable par l'appelant), destiné à l'AFFICHAGE (sortie d'alerte,
  ΔP, ΔUr entre ouverture et clôture) — jamais lu pour calculer le résultat.

Ces deux paires peuvent porter des valeurs proches (les deux dérivent de
`node.urgency` à l'instant de la capture), mais leur RÔLE diffère
strictement : la première est le contexte de la décision, la seconde est une
mesure d'interface. Le stockage en colonnes séparées rend la séparation
vérifiable au niveau du schéma — et pas seulement d'une convention de code —
et empêche une évolution future de `proposer_resultat` de « glisser » vers
une lecture de l'état de risque par accident (`tests/test_services_interventions.py`
couvre explicitement ce garde-fou).
