# Framework KPI : Partir du Risque de Rupture
## Mécaniques causales & Indicateurs non-redondants

**Approche** : Partir de la question centrale "Qu'est-ce qui cause une rupture?" et identifier les indicateurs qui captent ces mécaniques.

**Audience** : Référante innovation R&D, équipe doctorante  
**Date** : Juillet 2026  

---

## 🎯 Cadre conceptuel : Le risque de rupture comme point de départ

### Définition opérationnelle
**Rupture de chaîne logistique** = impossibilité de livrer un bien/service au moment, lieu, quantité et qualité convenus.

**Risque de rupture** = probabilité que cet événement se produise, pondérée par sa sévérité.

### La question centrale
**« Quels sont les mécanismes physiques/opérationnels qui font MONTER le risque de rupture ? »**

Réponse : Il y a exactement **4 mécaniques** directes qui augmentent le risque, plus **2 variables contextuelles** (coût, carbone) qui contraignent les solutions.

---

## 🔗 Les 4 mécaniques directes de rupture

### Mécanique #1 : Érosion du temps (u_time)
**Question** : "Reste-t-il assez de temps physique pour livrer?"

#### Le mécanisme causal
```
Slack diminue → Marge de manœuvre réduite → Incapacité à absorber tout problème
```

**Formule conceptuelle** :
```
Slack = (Deadline - Aujourd'hui) - Leadtime réel estimé

Si Slack < 0 → RUPTURE CERTAINE (trop tard)
Si Slack petit → RUPTURE PROBABLE (peu de buffer pour incidents)
```

#### Pourquoi c'est une cause DIRECTE?
- Le temps est **non-compressible** : même si tout est parfait ailleurs, si pas assez de temps → impossible
- C'est le **dénominateur commun** : toute rupture implique "pas assez eu le temps"
- Exemple : "Même si le fournisseur travaille 24/24, même s'il n'y a pas de panne, même si on paye le prix fort → impossible si deadline = demain et leadtime = 5 jours"

#### Qu'on mesure réellement?
- **Slack restant** = deadline - current_date - estimated_leadtime
- **Lead time** = fabrication + transport + buffers
- **Probabilité de retard** = P(actual_leadtime > estimated_leadtime)

**Provenance typique** : Client (deadline promise), Fournisseur (leadtime historique), Planification (estimation buffers)

**Non-redondance** : u_time est le SEUL indicateur qui mesure l'érosion temporelle. u_risk mesure "qu'est-ce qui peut mal tourner", pas "y a-t-il assez de temps".

---

### Mécanique #2 : Saturation du système (u_cap)
**Question** : "Le système logistique peut-il absorber cette commande?"

#### Le mécanisme causal
```
Capacité saturée → File d'attente → Délai supplémentaire avant traitement → Slack s'érode
```

**Formule conceptuelle** :
```
Charge actuelle = Σ(tâches en cours)
Capacité disponible = capacité_max - charge_actuelle

Si Charge > Capacité → Queue d'attente
Délai en queue = f(charge, capacité)
Slack_effectif = Slack_initial - Délai_queue
```

#### Pourquoi c'est une cause DIRECTE?
- La saturation crée un **délai caché** indépendant du leadtime estimé
- Exemple concret : "Leadtime annoncé 3 jours, mais transport 90% saturé → attente 7 jours avant de partir + 3 jours = 10 jours totaux"
- C'est un **goulot d'étranglement** : même si fournisseur rapide, même si pas de panne → si transport saturé, commande attend
- **Black Friday** est l'exemple type : tout le réseau saturé simultanément

#### Qu'on mesure réellement?
- **Taux d'occupation** = (charge en cours) / (capacité max) en %
- **Longueur de queue** = nombre de tâches en attente
- **Délai d'attente** = temps moyen avant traitement
- **Buffer disponible** = capacité inutilisée pour absorber pics

**Zones critiques** :
- < 60% occupation : capacité disponible, pas de queue
- 60-80% : files d'attente commencent
- > 80% : saturation, queues longues

**Provenance typique** : Fournisseur (capacité usine, charge actuelle), Transport (occupation véhicules), Planification (prévisions charge)

**Non-redondance** : u_cap est le SEUL indicateur qui mesure "le système peut-il m'absorber?". u_perf mesure "qualité de ma production", pas "espace disponible".

---

### Mécanique #3 : Dégradation de la performance (u_perf)
**Question** : "La ressource critique fonctionne-t-elle correctement?"

#### Le mécanisme causal
```
Performance dégradée → Sortie inférieure à l'attendu → Leadtime réel > leadtime estimé → Retard probable
```

**Formule conceptuelle** :
```
TRS = Disponibilité × Performance × Qualité

TRS élevé (> 85%) → Production conforme au planning
TRS dégradé (< 70%) → Production lente, défauts, pertes de capacité

Leadtime_réel = Leadtime_nominal / TRS
Exemple : Leadtime nominal = 10 jours, TRS = 50% → Leadtime_réel = 20 jours!
```

#### Pourquoi c'est une cause DIRECTE?
- La performance du fournisseur/usine est un **facteur d'incertitude sur la durée**
- Exemple : "Vous comptiez 5 jours de fabrication, mais machine = 60% uptime → 8 jours requis → dépasse deadline"
- C'est un **proxy de fiabilité** : une machine qui tombe souvent = leadtime imprévisible
- Impacts : retards, défauts, rework → tous augmentent le risque

#### Qu'on mesure réellement?
- **Disponibilité (A)** = % du temps où la machine est opérationnelle
  - Pannes imprévues, maintenance, setup
- **Performance (P)** = vitesse réelle vs vitesse nominale
  - Ralentissements, dégradations qualité
- **Qualité (Q)** = % de pièces conformes
  - Défauts, rework → augmente leadtime effectif

**TRS = A × P × Q** (indicateur composite)

**Zones critiques** :
- > 85% : BON (peu de risque leadtime)
- 70-85% : MOYEN (risque leadtime modéré)
- < 70% : MAUVAIS (haute imprévisibilité)

**Provenance typique** : Très rarement public (données internes fournisseur). Proies par : contrats SLA, historique de pannes, benchmark industrie

**Non-redondance** : u_perf est le SEUL indicateur mesurant "la ressource critique fonctionne-t-elle?". u_risk mesure "risque d'incident externe", pas "performance interne de la machine".

---

### Mécanique #4 : Exposition au risque / Événements adverses (u_risk)
**Question** : "Quel est le risque qu'un événement imprévu dégrade la situation?"

#### Le mécanisme causal
```
Incident adverse (panne, météo, incident géo-politique) → Défaillance → Délai
                     ↓ combiné avec
                Incapacité à récupérer rapidement
                     ↓
              Rupture probable
```

**Formule conceptuelle** :
```
Risque = P(incident) × Sévérité × Récupérabilité

Où:
- P(incident) : probabilité qu'un incident survienne
- Sévérité : impact downstream (combien de tâches bloquées?)
- Récupérabilité : pouvons-nous nous rétablir rapidement? (TTR)
```

#### Pourquoi c'est une cause DIRECTE?
- Le risque capture l'**aléa** : même si tout semble OK, des événements imprévisibles peuvent survenir
- Exemples d'incidents : panne fournisseur, accident transport, conditions météo, perturbation géopolitique
- C'est indépendant des 3 autres : un fournisseur peut être fast (u_time OK) + pas saturé (u_cap OK) + performant (u_perf OK) mais très fragile (u_risk HIGH)
- La **récupération** est aussi important : une panne de 24h vs une panne de 72h ce n'est pas pareil

#### Qu'on mesure réellement?
**A) Probabilité de survenue d'un incident** :
- Historique de pannes du fournisseur
- Vulnérabilité géographique (zone sismique, climatique instable)
- Exposure politique (sanctions, instabilité)
- Calcul Bayésien combinant : facteur supplier × facteur géo × facteur externe

**B) Time-To-Recovery (TTR)** :
- Si incident survient, combien de temps pour rebondir?
- Contrat SLA du fournisseur ("garantie 24h de repair")
- Capacité alternative (existe-t-il un backup supplier?)

**C) Gravité / Sévérité** :
- Impact downstream : combien de tâches bloquées par celle-ci?
- Exemple : "Si cette pièce échoue, 10 tâches suivantes s'effondrent" → sévérité HAUTE
- Mesurable via : graphe de dépendances, criticité du produit

**D) Exposition à facteurs externes** :
- Géographiques : zones à risque (tremblements, inondations)
- Politiques : sanctions, embargos, instabilité
- Environnementales : conditions extrêmes saisonnières

**Zones critiques** :
- P(incident) < 10% : LOW
- P(incident) 10-30% : MEDIUM
- P(incident) > 30% : HIGH

**Provenance typique** : Fournisseur (historique pannes), données géopolitiques, supplier risk database (Achraf's work), contrats SLA

**Non-redondance** : u_risk est le SEUL indicateur mesurant "quels aléas et perturbations peuvent survenir?". Les 3 autres mesurent l'état actuel (time, capacity, performance), pas l'aléa futur.

---

## 📊 Synthèse des 4 mécaniques directes

| Mécanique | Cause racine | Mesurée par | Signal d'alerte |
|-----------|-------------|-----------|-----------------|
| **u_time** | Temps non-compressible | Slack, leadtime | Slack → 0 |
| **u_cap** | Système saturé | Queue, occupation | Occupation > 80% |
| **u_perf** | Performance dégradée | TRS | TRS < 70% |
| **u_risk** | Événement adverse | P(incident), TTR, sévérité | P > 30% ou TTR long |

**Principe clé** : Une rupture survient quand **au moins 2 de ces 4 mécaniques activent simultanément**.

---

## 🎚️ Les 2 variables contextuelles (non directes, mais cruciales)

### Variable #5 : Flexibilité financière (u_cost)
**Question** : "Si un problème survient, avons-nous les moyens de le résoudre?"

#### Ce qu'on mesure (PAS le risque lui-même, mais la réponse au risque)
- **Coûts d'urgence** : transport expédié, rush order premium, expediting charges
- **Pénalités** : contrats SLA qui pénalisent retard
- **Flexibilité** : possibilité de déroutage, multi-sourcing, stockage tampon

**Formule conceptuelle** :
```
Flexibilité = (Coûts standard - Coûts urgence réels) / Coûts standard

Si Flexibilité élevée → solutions disponibles même en crise (on peut payer plus)
Si Flexibilité nulle → pas de solution économique viable
```

#### Le rôle dans la rupture
- **Ne CAUSE pas directement la rupture**, mais détermine "peut-on l'éviter?"
- Exemple : "Vous avez un problème → seule solution = avion (+400%) → client ne paiera pas → rupture inévitable"
- **Contrainte la prise de décision** : même si physiquement possible, si trop cher → pas viable

**Provenance typique** : Achats (tarifs urgence), Logistique (options transport), Finance (budget dispo), Contrats clients (penalty terms)

**Non-redondance** : u_cost est ORTHOGONAL à u_time/u_cap/u_perf/u_risk. On peut avoir u_time VERT mais u_cost ROUGE (solution existe mais inabordable financièrement).

---

### Variable #6 : Arbitrage durabilité (u_co2)
**Question** : "Peut-on résoudre le problème sans violer nos cibles carbone?"

#### Ce qu'on mesure (arbitrage, pas risque direct)
- **Budget carbone** : plafond d'émissions annuel
- **Mode transport** : bateau (lent, bas carbone) vs avion (rapide, très haut carbone)
- **Trade-off** : urgence souvent équivaut à "prendre l'avion" → dépassement CO₂

**Formule conceptuelle** :
```
Chemin 1 (durable) : bateau, 20 jours, 50 kg CO₂
Chemin 2 (urgent) : avion, 2 jours, 400 kg CO₂

Deadline = 5 jours → IMPOSSIBLE chemin 1 → force chemin 2
Mais budget CO₂ déjà 95% utilisé → dépassement probable

Résultat: DILEMME (rupture service vs rupture compliance)
```

#### Le rôle dans la rupture
- **Ne CAUSE pas la rupture**, mais crée un **conflit de contraintes**
- "Peut-on livrer à temps? OUI, mais ça brise notre cible ESG"
- "Peut-on rester dans budget carbone? OUI, mais on manque le deadline"

**Provenance typique** : Transport (CO₂ par mode), Finance/ESG (budget annuel), Réglementation (cibles mandatées)

**Non-redondance** : u_co2 est ORTHOGONAL aux autres. C'est un critère d'arbitrage entre solutions, pas un facteur direct de rupture.

---

## 🔄 Comment les 6 indicateurs interagissent

### Graphe causal complet

```
┌─────────────────────────────────────────────────────────────┐
│                 RISQUE DE RUPTURE (Central)                  │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
   
┌──────────────┐        ┌──────────────┐    ┌──────────────┐
│  4 FACTEURS  │        │   2 VARIABLES│    │              │
│   DIRECTS    │        │ CONTEXTUELLES│    │              │
└──────────────┘        └──────────────┘    │              │
        │                     │              │              │
     ┌──┴──┬────────┬────┐    │              │              │
     ▼     ▼        ▼    ▼    ▼              ▼              ▼
   u_time u_cap  u_perf u_risk u_cost      u_co2       (autres facteurs)
     │     │        │     │     │           │
     │     │        │     │     └─→ (flexibilité pour résoudre)
     │     │        │     │
     └─────┴────────┴─────┘
       (4 mécaniques causales)
```

### Exemple : Scénario critique (PHARMA)

```
SITUATION :
- Deadline : demain (u_time = ROUGE, Slack = 0)
- Transport saturé (u_cap = ROUGE, 95% occupation)
- Fournisseur fragile (u_risk = ROUGE, P_fail = 30%, TTR = 24h)
- Performance OK (u_perf = VERT, TRS = 92%)
- Coûts explosent (u_cost = ROUGE, +350% pour avion)
- Budget CO₂ épuisé (u_co2 = ROUGE, 105% budget)

ANALYSE :
- 3 facteurs directs en ROUGE (u_time + u_cap + u_risk) → Risque très haut
- u_perf VERT ne suffit pas à compenser
- u_cost ROUGE → pas de solution financière viable
- u_co2 ROUGE → avion (seule solution) viole cible ESG

VERDICT : RUPTURE INÉVITABLE
- Livrer à temps? Impossible (avion est saturé, risque fournisseur)
- Respecter deadline + ESG? Impossible (conflit direct)
- Option : accepter retard OU accepter dépassement CO₂
```

---

## ✅ Justification de non-redondance

### Pourquoi ces 6, pas 4 ou 8?

**Dimension 1 : Temps (u_time)**
- **Unique** : c'est la seule variable mesurant "y a-t-il assez de temps physique?"
- **Remplaçable par?** Non. u_cap mesure queues (pas vraiment "temps"), u_perf mesure vitesse (pas "deadline")
- **Essentiel** : oui, toute rupture implique temps insuffisant

**Dimension 2 : Capacité (u_cap)**
- **Unique** : c'est la seule variable mesurant "le système peut-il m'absorber?"
- **Remplaçable par?** Non. u_perf mesure qualité (pas capacité globale), u_time mesure deadline (pas occupation)
- **Essentiel** : oui, la saturation crée des délais cachés

**Dimension 3 : Performance (u_perf)**
- **Unique** : c'est la seule variable mesurant "la ressource fonctionne-t-elle?"
- **Remplaçable par?** Non. u_risk mesure incidents (pas performance nominale), u_cap mesure globalement (pas spécifiquement fournisseur)
- **Essentiel** : oui, une machine lente = leadtime imprévisible

**Dimension 4 : Risque (u_risk)**
- **Unique** : c'est la seule variable mesurant "l'aléa et événements adverses"
- **Remplaçable par?** Non. u_perf mesure nominalement (pas incidents), u_time mesure deadline (pas événements)
- **Essentiel** : oui, les ruptures sont souvent déclenchées par incidents

**Dimension 5 : Coût (u_cost)**
- **Unique** : c'est la seule variable mesurant "avons-nous les moyens financiers?"
- **Remplaçable par?** Non. Ce n'est pas une cause directe, c'est la "réponse" possible aux problèmes
- **Essentiel** : oui, beaucoup de ruptures surviennent parce que la solution était impossible économiquement

**Dimension 6 : CO₂ (u_co2)**
- **Unique** : c'est la seule variable capturant "conflit urgence vs durabilité"
- **Remplaçable par?** Non. Ce n'est pas une cause de rupture, c'est un critère d'arbitrage entre solutions
- **Essentiel** : oui, de plus en plus de clients refusent de breaker cibles ESG même pour urgence

### Qu'on pouvait ajouter / supprimer

**Qu'on pourrait ajouter** :
- Qualité des données (data reliability) → non, c'est "meta" (affecte tous les KPIs)
- Flexibilité supplier (multi-sourcing possible?) → captée partiellement par u_risk (TTR, backup)
- Fiabilité transport → captée par u_cap (saturation) + u_risk (incidents)

**Qu'on devrait SUPPRIMER** :
- Rien. Chacun des 6 apporte une dimension unique et non-redondante.

---

## 📋 Résumé : Les 6 KPIs et leurs rôles

| # | KPI | Type | Mesure | Provenance | Signal d'alerte |
|---|-----|------|--------|-----------|-----------------|
| 1 | **u_time** | DIRECT | Slack / Deadline proximity | Client, planification | Slack ≤ 0 |
| 2 | **u_cap** | DIRECT | Saturation système | Fournisseur, transport | Occupation > 80% |
| 3 | **u_perf** | DIRECT | TRS (Dispo × Perf × Qualité) | Fournisseur (rare) | TRS < 70% |
| 4 | **u_risk** | DIRECT | P(incident) × TTR × Sévérité | Historique, geo, externe | P > 30% |
| 5 | **u_cost** | CONTEXTE | Flexibilité financière | Achats, finance | Surcoût > 30% |
| 6 | **u_co2** | CONTEXTE | Arbitrage durabilité | ESG, transport | Usage > 100% budget |

---

## 🎯 Comment utiliser ce framework avec votre référante

### Points clés à présenter

1. **Partir du risque**
   - "Je n'ai pas d'abord choisi 6 KPIs au hasard. Je suis parti de: 'Qu'est-ce qui cause une rupture?'"
   - "Réponse: 4 mécaniques physiques directes + 2 variables contextuelles"

2. **4 causes directes vs 2 variables contextuelles**
   - "u_time, u_cap, u_perf, u_risk sont des FACTEURS DE RISQUE (ils causent réellement la rupture)"
   - "u_cost, u_co2 sont des VARIABLES D'ARBITRAGE (ils contraignent la solution, pas la cause)"

3. **Non-redondance**
   - "Chaque KPI mesure une dimension unique"
   - "Vous ne pouvez pas réduire à 4 ou 5 sans perdre une information critique"
   - Exemple : "u_time seul ne suffit pas → vous pouvez avoir slack OK mais système saturé"

4. **Données provenance**
   - "u_time, u_cap, u_perf, u_risk ont des provenances différentes"
   - "u_time vient du client (deadline), u_cap du fournisseur/transport, u_perf du fournisseur, u_risk d'historiques"

### Tableau synthétique à montrer

Affichage simple:
```
RISQUE DE RUPTURE
├─ 4 Facteurs directs
│  ├─ u_time : Temps insuffisant?
│  ├─ u_cap : Système saturé?
│  ├─ u_perf : Machine dégrade?
│  └─ u_risk : Événement adverse?
│
└─ 2 Variables d'arbitrage
   ├─ u_cost : Flexibilité financière?
   └─ u_co2 : Conflit urgence/durabilité?
```

---

## Glossaire rapide

- **Slack** : Marge temporelle (deadline - aujourd'hui - leadtime)
- **TRS** : Taux Rendement Synthétique = Disponibilité × Performance × Qualité
- **TTR** : Time To Recovery (temps pour rebondir après incident)
- **Sévérité** : Impact downstream (combien de tâches bloquées)
- **P(incident)** : Probabilité qu'un événement adverse survienne
- **Flexibilité financière** : Capacité à payer surcoûts pour résoudre
- **Budget carbone** : Plafond d'émissions CO₂ annuel

---

**Document créé** : 2 juillet 2026  
**Pour** : Réunion avec référante innovation  
**Approche** : Partir du risque de rupture → mécaniques causales → KPIs non-redondants
