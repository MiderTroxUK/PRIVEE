# Framework KPI pour la Prédiction de Rupture de Chaîne Logistique
## Justification, Définitions & Provenance dans le BST DISCO

**Document** : Explication détaillée des 6 indicateurs clés pour la modélisation du risque de rupture  
**Audience** : Référante d'innovation (R&D), équipe de doctorante  
**Date** : juillet 2026  
**Contexte** : R&D ALTEN-DIN sur le digital twin DISCO et la prédiction de rupture SC

---

## 1. Vue d'ensemble du framework

Le projet DISCO formule actuellement un problème **bipartite** :
- **U_r(t)** : urgence physiquement computable via deadline proximity
- **U_d** : urgence déclarée par l'opérateur
- **A(t)** : score d'adéquation mesure le décalage entre les deux

Pour **élargir** ce modèle vers une **prédiction de rupture de chaîne logistique**, nous proposons un framework de 6 KPIs orthogonaux qui capturent les dimensions essentielles d'une rupture.

**Définition opérationnelle d'une rupture (rupture risk)** : situation où l'un des 6 domaines dépasse un seuil critique, rendant impossible la livraison promised ou créant une défaillance en cascade.

---

## 2. Les 6 indicateurs KPI : provenance et justification

### 📌 KPI 1 : TEMPS (u_time)
**Définition courte** : Lead time (temps de livraison), délais, respect des échéances / deadlines

#### Provenance théorique
- **BST Section 2.Problem** : Le formalisme pose $t_c$ (deadline critique) comme point de départ de $U_r(t) = \tanh(K / (t_c - t))$
- **Lock 1 du BST** : "Real urgency can be modeled using slack, due-date pressure, delay risk, or shortage exposure" → Le temps est **le fondement physique** du modèle
- **Section 3 SoTA** : Deadline-sensitive scheduling theory établit que la valeur opérationnelle décroît non-linéairement près des deadlines (Time-Utility Functions)

#### Justification pour la rupture
Le **temps est le détonateur principal**. Une rupture commence par :
- **Slack shrinking** : marge temporelle qui diminue
- **Lateness risk onset** : première évidence qu'on risque d'être en retard
- **Hard deadline breach** : dépassement du deadline = rupture avérée

**Composantes mesurées** :
- $S_i(t)$ = slack restant (deadline − current time − effort buffer)
- TTD (Time To Deadline) = temps avant deadline critique
- Lateness probability = P(t_end > d_i | current state)

#### Lien au modèle DISCO
- L'équation de $U_r(t)$ place le temps au cœur : c'est l'**input dominant**
- LSTR utilise slack directement : $\text{Rate}_i(t) = \varepsilon_i / \max(d_i - t, \varepsilon_{\min})$

---

### 📌 KPI 2 : CAPACITÉ (u_cap)
**Définition courte** : Saturation des volumes/poids, déficit de flux, goulets d'étranglement

#### Provenance théorique
- **BST Section 1.Introduction** : "Physical Internet network where logistics capacity is mutualized across actors"
- **Section 2.Problem** : "Over-triage (declaring an urgency higher than physical warrants) **starves other network tenants**, whereas under-triage creates **invisible stock rupture risk**"
- **LSTR Implementation (Section 4.Operations)** : "LSTR stabilizes the scheduling queue across **parallel supplier lanes**, reducing scheduling overhead and **queue thrashing**"

#### Justification pour la rupture
Une rupture peut survenir **même avec temps suffisant** si :
- **Saturated transport network** : tous les slots de transport sont pleins (mutualized capacity exhausted)
- **Queue overflow** : accumulation de tâches crée des délais cachés
- **Flow deficit** : la capacité réelle < demand

**Composantes mesurées** :
- Queue occupancy rate = (current tasks in queue) / (max capacity)
- Volume saturation = (sum of order volumes) / (available transport volume)
- Transport lane availability = % of supplier lanes currently available
- Buffer usage = (allocated slack budget) / (total slack available)

#### Lien au modèle DISCO
- La métrique **Crisis Penalty** $C_{\text{crise}}(t)$ inclut : $\eta_1 \max(-S_i, 0)$ = pénalité sur dépassement de slack → perte de capacité
- Le dashboard DISCO V-B affiche "warehouse occupancy graph" = vision directe de saturation

---

### 📌 KPI 3 : PERFORMANCE (u_perf)
**Définition courte** : TRS (Taux de Rendement Synthétique) = disponibilité × performance × qualité

#### Provenance théorique
- **BST Section 1.Introduction** : "Operational Performance Indicators relevant to supply reliability"
- **Section 4.Operations Table 46** : Five scenarios tested, including **DRAGONFLY AEROSPACE** where "Machine breakdown at critical supplier, precision parts affected"
- **Lock 5** : "Disruption-aware scheduling and supplier selection are mature, well-studied fields. The contribution is constructing a **credible** $U_d$ input and computing a **physically-grounded** $U_r(t)$"

#### Justification pour la rupture
L'indicateur de **performance de la machine/processus du fournisseur** est un proxy pour :
- **Disponibilité (A)** = % uptime de la machine / ligne de production
- **Performance (P)** = vitesse réelle / vitesse nominale
- **Qualité (Q)** = % de pièces conformes / rejetées
- **Défaillance cascadée** : une machine qui tombe en panne crée une rupture immédiate

**Composantes mesurées** :
- Equipment downtime (heures d'arrêt non prévu)
- MTBF (Mean Time Between Failures) du fournisseur
- Defect rate de la production
- Recovery time (TTR = Time To Recovery)

#### Lien au modèle DISCO
- **DISCO Database** (Table 47) : "The expert calibration questionnaire defines five supplier evaluation criteria" → Operational effort (OE) dans V_mc
- **Risk scorer** (Section 1.Capitalisation) : "Kabouche developed the supplier risk scorer combining **delay history**, geographic vulnerability, and **financial fragility**"
- La fragmentation opérationnelle d'un supplier se traduit en hausse de $r_i$ (raw risk score)

---

### 📌 KPI 4 : RISQUE (u_risk)
**Définition courte** : Probabilité de défaillance, TTR (time to recovery), sévérité, exposition environnementale & politique

#### Provenance théorique (Complexe — plusieurs sous-composantes)
- **BST Section 2.Problem** : "Over-triage ... whereas **under-triage creates invisible stock rupture risk that cascades downstream**"
- **Lock 3** : "Computing $\Delta U(t)$ is necessary but not sufficient. The decisive test is whether this adequacy signal improves planning outcomes beyond standard variables... **tardiness cost, and disruption-risk exposure**"
- **Section 4.Operations Crisis Penalty** : $P_{\text{bayes}} = 0.3$ = Causal Bayesian probability of delivery delay

#### Sous-composantes du risque
1. **Probabilité de défaillance** ($P_f$) : 
   - Bayesian delay probability : $P_{\text{bayes}} = P(T_i^{resp} > d_i | \text{supply state})$
   - Supplier fragility score : $r_i \in [1, 10]$ (DISCO)

2. **Time-To-Recovery (TTR)**:
   - Après une défaillance, combien de temps pour rebondir?
   - Formalisé dans Crisis Penalty : $\eta_2 \gamma \max(t - d_i, 0)^2$ = pénalité quadratique pour tardiness hard

3. **Sévérité** :
   - Impact downstream : nombre de tâches bloquées par une défaillance
   - Formulé en Phase 5 : "downstream topological depth ($b=0.60$) dominates the physical predictive power"
   - Business criticality : $w_1 = 0.30$ dans $V_{\text{mc}}$ scoring

4. **Exposition environnementale & politique** :
   - **Environnementale** : vulnérabilité géographique (zones climatiques, zones sismiques)
   - **Politique** : sanctions, tarifs, embargos, instabilité géopolitique
   - Integrated in "geographic vulnerability" of supplier risk scorer (Kabouche 2025)

#### Justification pour la rupture
- Une rupture n'est **pas seulement un event** mais une **chaîne causale** : événement → défaillance → non-recovery
- Le **risque intègre** : what can go wrong × how bad × how long to fix

**Composantes mesurées** :
- $P(\text{delay})$ via Bayesian graph
- TTR : estimated recovery time from historical data ou supplier SLA
- Sévérité : downstream blocked count (topological depth)
- Environmental risk score
- Political risk index (sourced from external databases)

#### Lien au modèle DISCO
- **LSTR Implementation** : $r_i \in [1, 10]$ is embedded directly in effort buffer: $\varepsilon_i = T_{\text{HERE}} \times (1 + \beta \cdot \text{Norm}(r_i))$
- **Business Value Score** : "Supplier rupture risk score" = $\text{RR}$ → $w_2 = 0.30$ dans $V_{\text{mc}}$
- **Crisis Penalty formula** : Bayesian alert $P_{\text{bayes}}$ + hard tardiness penalty formalize the rupture cascade

---

### 📌 KPI 5 : COÛT (u_cost)
**Définition courte** : Coût opérationnel, tarifs, coûts de stockage, surcoûts d'urgence

#### Provenance théorique
- **BST Section 2.Problem (Table 1, Motivating Observations)** : Supply chain face "multi-dimensional decisions (cost, deadline, risk, carbon)"
- **Lock 5** : "Disruption-aware scheduling is mature. The contribution is making urgency architecture defensible"
- **Unified Urgency Score** : Composite framework designed to avoid "obscuring trade-offs" via "maintaining individual component visibility" (Lock 4)

#### Justification pour la rupture
Le coût capture les **conséquences opérationnelles** :
- **Over-triage cost** : "Excess expediting, avoidable cost, possible delay for other flows" (Table in Section 2)
- **Under-triage cost** : Emergency sourcing (rush order premium), expedited transport (air freight), penalties
- **Inventory holding** : stockage tampon pour absorber volatilité
- **Opportunity cost** : ressources allouées à l'urgente au détriment du profitable

**Composantes mesurées** :
- Transport cost (standard vs expedited)
- Rush order premium (% surcoût si on commande en urgence)
- Inventory holding cost (h × quantity)
- Expediting surcharge (% du total if task flagged urgent)
- Penalty cost if late (contractual SLA breaches)

#### Lien au modèle DISCO
- **DISCO Scoring Engine** (Section 1.Introduction, Equation 36) : 
  ```
  ScoreCost = 1 + 9 × (realCost - cost_min) / (cost_max - cost_min)
  ```
  → Min-Max normalization [1, 10] scale
- **Unified Urgency Score weights** : Coût n'est pas un poids direct, mais est intégré dans **Business Value** via operational effort + carbon trade-off
- **Adequacy Score asymmetry** : $\lambda_{\text{under}} > \lambda_{\text{over}}$ justement parce que "under-triage" crée des coûts cachés massifs

---

### 📌 KPI 6 : CO₂ (u_co2)
**Définition courte** : Dépassement des cibles carbone (émissions mesurées vs plafond)

#### Provenance théorique
- **BST Section 1.Introduction** : Smart Green Supply Chain programme articulates three pillars: "**Green**: Minimisation of carbon footprint per transport leg, aligned with GLEC Framework v3.2 and ISO 14083:2023"
- **Cordova 2024** (cited in Capitalisation) : "developed the CO₂ quantification module per route using GLEC/VECTO methodology with log-normalised output $\hat{x}_{\text{CO}_2}$"
- **Unified Urgency Score** : CO₂ explicitly included in Business Value sub-component:
  ```
  V_mc(t) = w_1·BV + w_2·RR + w_3·OE + w_4·CO₂
  ```
  with $w_4 = 0.15$

#### Justification pour la rupture
Le carbone est **à la fois une métrique ESG et une contrainte opérationnelle** :
- **Rupture de compliance** : dépassement du plafond carbone = violation réglementaire
- **Reputational risk** : breach du target ESG affecte le coût du capital, l'image client
- **Mode sélection** : transports bas-carbone (train, bateau) sont lents vs haut-carbone (avion) rapides → trade-off temporel
- **Scopage** : CO₂ Scope 3 (transport) est major chez les donneurs d'ordres

**Composantes mesurées** :
- Actual CO₂ per shipment (kg CO₂eq, computed via GLEC)
- CO₂ target/budget per period (annual cap)
- Overage ratio = (actual - budget) / budget × 100%
- Mode carbon intensity (kg CO₂/ton-km)
- Offsetting cost if exceeding

#### Lien au modèle DISCO
- **DISCO Scoring Engine** (analogue formula to Cost):
  ```
  ScoreCO₂ = 1 + 9 × (realCO₂ - co₂_min) / (co₂_max - co₂_min)
  ```
- **Scenario Testing** (Table 46, Section 4.Operations) : DRAGONFLY, PHARMA, AUTO, INDUSTRIE, ECOM all tested with CO₂ visibility
- **Dashboard V-B** includes "CO₂ comparative bar" for scenario comparison
- **Unified Urgency Score component** : Explicit weight in US(t) composition for future multi-criteria integration

---

## 3. Architecture de liaison : des 6 KPIs au score unifié US(t)

### Mapping vers le modèle DISCO existant

| KPI | Composante DISCO | Variable(s) BST | Poids dans US(t) |
|-----|------------------|-----------------|------------------|
| **Temps** | Deadline pressure, Slack dynamics | $U_r(t)$, $S_i(t)$ | Fondation de $A(t)$ (40%) |
| **Capacité** | Queue load, Gantt occupancy | LSTR $\text{Rate}_i(t)$, $\text{busy\_until}$ | Implicite dans $C_{\text{crise}}(t)$ |
| **Performance** | Supplier operational health | $r_i$ (risk score), MTBF proxy | Intégré dans $V_{\text{mc}}$ (OE) |
| **Risque** | Bayesian disruption model, Supplier fragility | $P_{\text{bayes}}$, $r_i$, depth | Explicite dans $C_{\text{crise}}$ et $V_{\text{mc}}$ (RR) |
| **Coût** | Min-Max normalized operational cost | Not yet in core model | Future: could weight $V_{\text{mc}}$ |
| **CO₂** | GLEC-computed transport emissions | Explicit in $V_{\text{mc}}$ | $w_4 = 0.15$ dans $V_{\text{mc}}$ |

### Flux de données conceptuel

```
┌─────────────────────────────────────────────────────┐
│         Raw Operational State x_i(t)                │
│  [deadlines, slack, risk_i, CO₂, cost, perf...]   │
└──────────────────┬──────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
┌─────────┐ ┌────────────┐ ┌──────────────┐
│ Temps   │ │ Risque +   │ │ Coût + CO₂   │
│ Capacité│ │ Performance│ │ + Capacité   │
│(u_time, │ │ (u_risk,   │ │ (multi)      │
│u_cap)   │ │  u_perf)   │ │              │
└────┬────┘ └──────┬─────┘ └──────┬───────┘
     │             │              │
     └─────────────┼──────────────┘
                   ▼
        ┌──────────────────────────┐
        │ A(t) : Cognitive Adequacy│
        │ V_mc: Business Value     │
        │ C_crise: Crisis Penalty  │
        │ L_macro: Macro Risk      │
        └────────────┬─────────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ US(t) : Unified     │
          │ Urgency Score [0-100]
          │ → Scheduler action  │
          └─────────────────────┘
```

---

## 4. Questions ouvertes & lien à la rupture prévisionnelle

### 4.1 Comment ces 6 KPIs alimentent une prédiction de rupture?

**Hypothèse de recherche** : Une rupture est prévisible si **au moins deux KPIs** franchissent un seuil critique **simultanément ou dans une fenêtre temporelle rapprochée**.

Exemples de scénarios de rupture prévisionnelle :
1. **Temps + Capacité** : "Slack diminue ET queue est pleine" → impossible d'injecter plus de priorité
2. **Risque + Performance** : "Supplier a 60% probablité de delay AND sa machine a uptime < 85%" → cumul des facteurs
3. **Coût + CO₂** : "Mode rapide (air) explose le budget carbone, mode lent (bateau) explose le deadline" → pas d'issue
4. **Temps + Risque** : "Deadline in 2 days AND supplier in financial distress" → scénario PHARMA Table 46

### 4.2 Thresholds critiques à calibrer

Pour chaque KPI, il faut définir des **zones de criticité** :

| KPI | Zone Verte | Zone Orange | Zone Rouge |
|-----|-----------|-----------|-----------|
| **Temps (u_time)** | Slack > 5 days | Slack 1-5 days | Slack < 0 (late) |
| **Capacité (u_cap)** | Queue < 60% | Queue 60-80% | Queue > 80% |
| **Performance (u_perf)** | TRS > 90% | TRS 70-90% | TRS < 70% |
| **Risque (u_risk)** | $P_f$ < 10% | $P_f$ 10-30% | $P_f$ > 30% |
| **Coût (u_cost)** | Δcost < 10% | Δcost 10-30% | Δcost > 30% |
| **CO₂ (u_co2)** | Usage < 80% budget | Usage 80-100% | Usage > 100% |

---

## 5. Synthèse pour présentation à la référante

### ✅ Réponses aux 3 questions posées

#### Q1 : "Comment ont-ils été sélectionnés?"
**Réponse structurée** :
- **Fondation théorique** : Chaque KPI provient du BST ou de la littérature supply chain (voir Section 2 plus haut)
- **Orthogonalité** : Les 6 KPIs couvrent 6 dimensions indépendantes de rupture (temps, flux, opérations, aléa, finance, environnement)
- **Couverture du modèle DISCO** : 5 des 6 KPIs sont **déjà partiellement** dans le modèle DISCO ou US(t) proposé; u_cost est le seul "nouveau"
- **Justification rupture** : Une rupture réelle demande rarement une seule cause; ces 6 domaines couvrent les causes principales documentées en littérature

#### Q2 : "De quoi parle-t-on précisément? Quel est leur lien à la rupture?"
**Réponse** : Voir **Section 3** (Mapping table) et **Section 4.1** (Scénarios de rupture prévisionnelle)
- Chaque KPI opérationnalise une **dimension physique de rupture**
- Leur **combinaison** prédit l'occurrence d'une rupture avec probabilité plus haute que chacun isolé
- L'exemple PHARMA (Table 46, Section 4) illustre 2-3 KPIs en simultané

#### Q3 : "D'où proviennent-ils? Leur provenance?"
**Réponse** : Voir **Section 2** (Provenance théorique & justification pour chaque KPI)
- **Temps** : Fondation du modèle $U_r(t)$ BST
- **Capacité** : Critère LSTR + Physical Internet (mutualized capacity)
- **Performance** : Supplier risk scorer (Kabouche) + scenario data DISCO
- **Risque** : Bayesian modeling + supplier fragility (DISCO database)
- **Coût** : Multi-dimensional decision literature + DISCO scoring engine analogue
- **CO₂** : Green supply chain pillar + GLEC/VECTO module (Cordova)

---

## 6. Prochaines étapes de validation

1. **Calibration des thresholds** : Pour chaque KPI et industrie (AERO, PHARMA, AUTO, INDUSTRIE, ECOM), déterminer les seuils critiques
2. **Correlation analysis** : Mesurer les corrélations entre KPIs (certains sont peut-être redondants)
3. **Rupture event labeling** : Collecter des cas historiques de ruptures réelles chez clients DISCO et labéliser chaque KPI
4. **ML prediction model** : Formule (KPI1, KPI2, ...) → P(rupture) via supervised learning
5. **Sensitivity analysis** : Tester la robustesse du modèle si un capteur de KPI est défaillant

---

## Références & crédits

- **BST DISCO JH 2026** : Adequacy Score Between Declared and Real Urgency (Sections 1-4)
- **Baxas 2025** : DISCO Software Architecture
- **Kabouche 2025** : Supplier Risk Scoring
- **Cordova 2024** : Green Supply Chain CO₂ Quantification
- **Montreuil 2011** : Physical Internet Framework
- **Ivanov & Dolgui 2020** : Digital Twin in Supply Chains
- **Cheng 2025** : Survey on Deadline-Sensitive Scheduling

---

**Préparé par** : Système Claude Code  
**Date de préparation** : 2 juillet 2026  
**Statut** : Document de travail — À réviser après réunion avec référante
