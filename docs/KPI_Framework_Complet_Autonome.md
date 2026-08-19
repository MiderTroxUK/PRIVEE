# Framework KPI pour Prédire une Rupture de Chaîne Logistique
## Document Complet & Autonome

**Objectif** : Expliquer clairement pourquoi 6 indicateurs spécifiques, ce qu'ils mesurent, et comment ils permettent de prédire quand une livraison va échouer.

**Public** : Référante d'innovation (R&D, doctorante), sans supposer lecture du BST technique.

**Date** : Juillet 2026  
**Contexte** : Projet DISCO (simulation supply chain ALTEN) → Modèle de prédiction de rupture

---

## 🎯 Partie 1 : Comprendre le problème

### Qu'est-ce qu'une "rupture" en chaîne logistique?

Une **rupture** = impossibilité de livrer un produit à temps et en qualité attendue.

**Exemples concrets** :
- Vous commandez des pièces pour fabriquer demain → elles arrivent trop tard → ligne d'usine arrêtée
- Produit pharma réfrigéré : le transport dure 5h mais la chaîne du froid a bugué → produit détruit
- Black Friday : 1000 commandes à livrer en 48h → réseau transport 100% saturé → impossible

### Pourquoi c'est difficile à prédire?

Aujourd'hui, une rupture arrive souvent par **surprise** car :

1. **Les signaux sont fragmentés** : personne ne regarde TOUS les domaines ensemble
   - L'acheteur voit le deadline
   - Le logisticien voit la saturation du transport
   - Le fournisseur cache ses problèmes opérationnels
   - L'analyste financier voit les coûts mais pas les délais
   - L'équipe ESG voit les émissions carbone mais pas les risques opérations

2. **Les interactions entre domaines** : 
   - Exemple 1 : "On peut livrer à temps MAIS seulement par avion, qui dépasse le budget carbone de 200%"
   - Exemple 2 : "La machine du fournisseur tombe en panne → 10 tâches dépendantes s'effondrent"
   - Exemple 3 : "Le transport est saturé ET le fournisseur est fragile → double problème"

3. **Il faut agir AVANT que la rupture survienne**
   - Si on attend les signaux d'alerte classiques (deadline demain), il est trop tard
   - On doit détecter 1-2 semaines avant

### La solution : 6 KPIs qui couvrent TOUS les domaines

Au lieu de regarder juste "est-ce qu'on va arriver à temps?", on regarde **6 dimensions en même temps** :

```
          ┌─ TEMPS (deadline? slack restant?)
          │
          ├─ CAPACITÉ (transport saturé? files d'attente pleines?)
          │
          ├─ PERFORMANCE (machine du fournisseur OK? défauts? pannes?)
          │
    RUPTURE ─ RISQUE (probabilité d'événement adverse? peut-on récupérer?)
          │
          ├─ COÛT (solutions urgentes explosent les coûts? pas d'issue rentable?)
          │
          └─ CO₂ (dépassement budget carbone? conflit avec deadline?)
```

**Principe clé** : Une rupture survient quand **2+ domaines sont en rouge simultanément**.

---

## 🎯 Partie 2 : Les 6 KPIs expliqués en détail

### KPI #1 : TEMPS (u_time)
**Question clé** : "Y a-t-il assez de temps pour livrer?"

#### Qu'est-ce qu'on mesure?
- **Slack** = temps restant avant deadline, **MOINS** le temps de livraison estimé
- **Lead time** = temps physique pour fabriquer + transporter
- **Deadline** = quand le client a besoin du produit

**Formule simple** :
```
Slack restant = (Deadline - Aujourd'hui) - Temps de livraison estimé
```

**Exemples** :
- Slack = 10 jours, Temps livraison = 3 jours → OK, on a 7 jours de marge
- Slack = 3 jours, Temps livraison = 5 jours → PROBLÈME, on est déjà en retard!
- Slack = 5 jours, Temps livraison = 2 jours → OK mais serré

#### Zones de risque

| Slack restant | Statut | Couleur |
|---------------|--------|--------|
| > 5 jours | Confortable | 🟢 VERT |
| 1-5 jours | Serré | 🟠 ORANGE |
| ≤ 0 jours | Trop tard | 🔴 ROUGE |

#### Pourquoi c'est important?
Le **temps est le détonateur** : si on n'a pas assez de temps, rien ne peut sauver la livraison. Même si le fournisseur est excellent, même si le transport est dispo, même si ça coûte cher → trop tard = rupture.

**Analogue du BST** : Le modèle DISCO calcule une "urgence réelle" basée sur le temps (deadline proximity). C'est le fondement.

---

### KPI #2 : CAPACITÉ (u_cap)
**Question clé** : "Le réseau de transport peut-il absorber cette livraison?"

#### Qu'est-ce qu'on mesure?
- **Occupation des files d'attente** : combien de camions/avions attendent?
- **Volume saturé** : total des marchandises à transporter vs capacité dispo
- **Disponibilité de transport** : y a-t-il un slot de transport disponible?
- **Goulets d'étranglement** : certaines routes/corridors sont-elles bloquées?

**Exemples** :
- 10 commandes attendent de partir; transport dispo pour 3 → 7 resteront bloquées
- Poids total à transporter = 200 tonnes; capacité = 150 tonnes → 50 tonnes en attente
- Tous les vols vers ce pays la semaine prochaine sont pleins → pas de slot

#### Zones de risque

| Queue occupancy | Statut | Couleur |
|-----------------|--------|--------|
| < 60% | Dégagé | 🟢 VERT |
| 60-80% | Encombré | 🟠 ORANGE |
| > 80% | Saturé | 🔴 ROUGE |

#### Pourquoi c'est important?
Même si vous avez du temps et un bon fournisseur, si **le réseau transport est 100% saturé**, votre commande attendra. Et pendant qu'elle attend, le slack (KPI #1) diminue.

**Exemple réel** : Black Friday en e-commerce. Tous les colis partent la même semaine. Même les plus urgents doivent attendre parce qu'il n'y a pas de place.

**Analogue du BST** : Le modèle parle de "mutualized capacity" dans un Physical Internet. Si plusieurs acteurs partagent les mêmes camions, la saturation d'un affecte les autres.

---

### KPI #3 : PERFORMANCE (u_perf)
**Question clé** : "La machine/usine du fournisseur fonctionne-t-elle correctement?"

#### Qu'est-ce qu'on mesure?
- **Disponibilité** : % du temps que la machine est active (pas en panne)
- **Performance** : vitesse réelle / vitesse attendue
- **Qualité** : % de pièces sans défaut

Indicateur classique en industrie : **TRS (Taux de Rendement Synthétique) = Disponibilité × Performance × Qualité**

**Exemples numériques** :
- Machine 95% disponible, 100% en vitesse, 98% qualité → TRS = 93% ✅ BON
- Machine 70% disponible (30% en panne), 90% en vitesse, 95% qualité → TRS = 60% ❌ MAUVAIS

#### Zones de risque

| TRS | Statut | Couleur |
|-----|--------|--------|
| > 85% | Bon | 🟢 VERT |
| 70-85% | Dégradé | 🟠 ORANGE |
| < 70% | Mauvais | 🔴 ROUGE |

#### Pourquoi c'est important?
Un fournisseur avec une machine qui fonctionne mal = **risque que la commande soit retardée ou défectueuse**.

**Exemple** : 
- Vous commandez 1000 pièces
- La machine a un TRS de 60% (beaucoup de pannes, beaucoup de défauts)
- Même si le fournisseur travaille 24/24h, il produira moins que prévu
- Votre commande sera incomplète ou en retard

**Données** : Ces infos viennent des bases de données du fournisseur (historique de pannes, SLA de performance).

---

### KPI #4 : RISQUE (u_risk)
**Question clé** : "Quel est le risque qu'un événement adverse survienne? Si ça survient, peut-on s'en rétablir?"

#### Qu'est-ce qu'on mesure? (4 sous-parties)

**A) Probabilité de défaillance**
- Quelle est la probabilité que la livraison échoue?
- Calculée à partir des historiques du fournisseur, conditions transport, météo, etc.
- Exemple : "Ce fournisseur a 20% de risque de retard basé sur ses données historiques"

**B) Time-To-Recovery (TTR)**
- Si quelque chose tourne mal, combien de temps pour récupérer?
- Exemple : "La machine tombe en panne → 4h pour réparer" vs "8h pour réparer"
- Plus TTR est court, mieux c'est

**C) Sévérité (impact downstream)**
- Combien d'autres tâches dépendent de celle-ci?
- "Si cette pièce n'arrive pas, 10 tâches suivantes sont bloquées" → sévérité = HIGH
- "Si cette pièce n'arrive pas, c'est un problème isolé" → sévérité = LOW

**D) Exposition à des risques externes**
- Géographique : Zone sismique? Pays tropical (cyclones)? Zone de conflit?
- Politique : Sanctions? Embargos? Instabilité gouvernementale?
- Financière : Fournisseur en risque de faillite?

#### Zones de risque

| P(défaillance) | TTR | Sévérité | Verdict | Couleur |
|----------------|-----|----------|---------|--------|
| < 10% | Court | Basse | Acceptable | 🟢 VERT |
| 10-30% | Moyen | Moyenne | À monitorer | 🟠 ORANGE |
| > 30% | Long | Haute | Critique | 🔴 ROUGE |

#### Pourquoi c'est important?
Le risque capture l'**aléa et l'incertitude**. Même si tout semble OK aujourd'hui, il peut y avoir :
- Un événement météo
- Une panne fournisseur
- Un problème transport
- Une grève

**Exemple** :
- Fournisseur A : 5% risque de retard, TTR 24h, sévérité basse → SAFE
- Fournisseur B : 40% risque de retard, TTR 72h, sévérité haute → RISKY

**Données** : Bayesian networks (réseaux causaux) qui combinent historique + conditions actuelles.

---

### KPI #5 : COÛT (u_cost)
**Question clé** : "Quelle est la solution si quelque chose tourne mal? Peut-on se la permettre?"

#### Qu'est-ce qu'on mesure?
- **Coût standard** : prix normal de la livraison
- **Surcoûts si urgent** : 
  - Rush order premium (payer plus cher si on commande d'urgence)
  - Transport expédié (avion au lieu de bateau = 5× plus cher)
  - Expediting charges (frais supplémentaires pour priorité)
- **Pénalités SLA** : Si on livre en retard, client nous pénalise (contractuel)
- **Coûts de stockage** : Si on veut stocker plus pour amortir la volatilité

**Exemples de surcoûts** :
- Livraison normale : 100 €
- Livraison en 48h : 250 € (+150%)
- Livraison par avion : 500 € (+400%)
- Pénalité retard = 1000 € par jour

#### Zones de risque

| Surcoût vs budget | Statut | Couleur |
|------------------|--------|--------|
| < 10% | Acceptable | 🟢 VERT |
| 10-30% | Élevé | 🟠 ORANGE |
| > 30% | Insoutenable | 🔴 ROUGE |

#### Pourquoi c'est important?
Le coût mesure : "Avons-nous UNE solution même en cas de problème? Et pouvons-nous nous la permettre?"

**Scénario critique** :
- Deadline demain
- Slack = 0, transport saturé, fournisseur fragile → triple problème
- Seule solution = avion (+400% de coût)
- Mais le client ne paiera pas 400% de surcoût
- → PAS D'ISSUE → RUPTURE

**Données** : Tarifs de transport, pricing urgence, contrats SLA.

---

### KPI #6 : CO₂ (u_co2)
**Question clé** : "Respectons-nous nos cibles carbone? Ou un mode de transport rapide viole-t-il nos engagements ESG?"

#### Qu'est-ce qu'on mesure?
- **Émissions CO₂ par transport** : combien de kg CO₂eq par expédition?
- **Budget carbone annuel** : combien on a le droit d'émettre?
- **Overage** : sommes-nous au-dessus du plafond?
- **Trade-off temps/carbone** : transport rapide (avion) = plus de CO₂

**Exemples** :
- Transport bateau : 10 tonnes → 50 kg CO₂eq (bas carbone)
- Transport camion : 10 tonnes → 200 kg CO₂eq (moyen)
- Transport avion : 10 tonnes → 800 kg CO₂eq (très haut carbone)
- Mais avion = 2 jours vs bateau = 30 jours

#### Zones de risque

| % du budget CO₂ | Statut | Couleur |
|-----------------|--------|--------|
| < 80% | OK | 🟢 VERT |
| 80-100% | Serrée | 🟠 ORANGE |
| > 100% | Dépassée | 🔴 ROUGE |

#### Pourquoi c'est important?
C'est le **conflit moderne** : urgence vs durabilité.

**Scénario critique** :
- Deadline serré → besoin d'avion (très rapide)
- Avion consomme 8× plus de CO₂ que bateau
- Budget carbone déjà à 90% pour l'année
- Si on prend l'avion, on dépasse la cible ESG → breach de compliance → risque réputationnel
- Mais bateau prend 30 jours → manque le deadline → rupture de service

**Aucune bonne réponse** → DILEMME → besoin de prendre une décision en connaissance de cause.

**Données** : Méthodologies GLEC Framework (calcul d'émissions standardisé), targets ESG du groupe.

---

## 🎯 Partie 3 : Comment les 6 KPIs prédisent une rupture

### Principe : Rupture = combinaison de domaines critiques

**Une rupture ne survient JAMAIS d'une seule cause** — c'est toujours une combinaison.

#### Scénario 1 : "Temps + Capacité" → Rupture de saturation

```
Situation :
- Deadline dans 5 jours (Slack = 5 jours)
- Temps de livraison = 3 jours
- Slack VERT = OK pour le temps

MAIS:
- Transport 90% saturé (Capacité ROUGE)
- Queue d'attente actuelle = 7 jours
- Votre commande devra attendre 7 jours avant de partir

Résultat:
- 5 jours - 3 jours livraison = 2 jours de marge
- Mais on attend 7 jours avant même de partir
- Total réel = 2 + 7 = 9 jours
- Deadline = 5 jours
- RETARD DE 4 JOURS → RUPTURE
```

**C'est un cas RÉEL** : Black Friday, pics saisonniers, crises

---

#### Scénario 2 : "Risque + Performance" → Rupture de fragilité

```
Situation:
- Fournisseur A : TRS = 50% (machine fragile)
- Probabilité de défaillance = 40%
- TTR si panne = 72h
- Votre deadline = 8 jours

Calcul:
- Vous comptez sur 8 jours
- Probabilité 40% qu'il y ait un problème
- S'il y a un problème, 72h de récupération = 3 jours
- Temps efficace = 8 - 3 = 5 jours pour fabriquer
- Mais avec TRS 50%, la production est lente
- Risque : ne pas finir à temps

Résultat:
- Même si deadline technique "OK"
- Probabilité d'échec = très haute
- RUPTURE PROBABLE
```

---

#### Scénario 3 : "Coût + CO₂" → Rupture sans issue

```
Situation:
- Deadline in 3 days (urgent)
- Budget carbone : 90% utilisé

Options:
1. Transport bateau : 20 jours → respecte CO₂ MAIS rate deadline → RUPTURE SERVICE
2. Transport avion : 2 jours → respecte deadline MAIS dépasse CO₂ de 50% → RUPTURE ESG/COMPLIANCE
3. Route intermédiaire : n'existe pas

Résultat:
- Aucune solution viable
- Prendre bateau = rupture de livraison
- Prendre avion = rupture de cible carbone
- IMPASSE → RUPTURE
```

---

#### Scénario 4 : "Temps + Risque + Coût" → Rupture en cascade

```
Situation (PHARMA, critique):
- Patient en attente de médicament
- Deadline : demain (strict)
- Slack = 0 jours
- Fournisseur fragile : P(fail) = 30%, TTR = 24h
- Seule solution si panne : transport d'urgence = +300% coût

Calcul:
- Probabilité 30% que fournisseur échoue
- Si échoue, +300% coût
- Deadline ne peut pas être reporté (patient attend)
- Pas d'alternative fournisseur

Résultat:
- Situation irrésoluble
- Peu importe le choix, rupture probable
- RUPTURE CRITIQUE
```

---

### Règle de détection d'alerte

**ALERTE ROUGE = Au moins 2 KPIs simultanément en zone ROUGE**

| Scénario | KPI1 | KPI2 | KPI3 | Verdict |
|----------|------|------|------|---------|
| Temps + Capacité | 🔴 | 🔴 | 🟢 | ⚠️ ALERTE |
| Risque + Performance | 🔴 | 🔴 | 🟢 | ⚠️ ALERTE |
| Coût + CO₂ | 🔴 | 🔴 | 🟢 | ⚠️ ALERTE |
| Tous les feux verts | 🟢 | 🟢 | 🟢 | ✅ OK |

---

## 🎯 Partie 4 : Comment on calibre les seuils?

Les valeurs "VERT/ORANGE/ROUGE" que j'ai données sont des **exemples génériques**. Pour chaque industrie, il faut affiner.

### Exemple d'ajustement par industrie

#### AERO (Aerospace) — tolérance très basse
| KPI | VERT | ORANGE | ROUGE |
|-----|------|--------|-------|
| Temps | > 7 jours | 2-7 jours | < 2 jours |
| Capacité | < 50% | 50-70% | > 70% |
| Performance (TRS) | > 90% | 80-90% | < 80% |
| Risque (P_fail) | < 5% | 5-15% | > 15% |

**Raison** : Aerospace a zéro tolérance pour les défauts, délais, saturations.

#### ECOM (E-commerce) — tolérance plus haute
| KPI | VERT | ORANGE | ROUGE |
|-----|------|--------|-------|
| Temps | > 3 jours | 1-3 jours | < 1 jour |
| Capacité | < 75% | 75-90% | > 90% |
| Performance (TRS) | > 75% | 60-75% | < 60% |
| Risque (P_fail) | < 20% | 20-40% | > 40% |

**Raison** : E-commerce clients plus tolérants (30 jours shipping acceptable), mais beaucoup de volume.

---

## 🎯 Partie 5 : Comment on utilise ça pour prédire une rupture?

### Phase 1 : Collecte des données (historique)

Prendre tous les cas de **ruptures réelles** qui se sont produites chez les clients DISCO (exemple : "Livraison qui a échoué").

Pour chaque rupture, annoter rétrospectivement les 6 KPIs **au moment du risque** (1-2 semaines avant la rupture):

```
Rupture #1 (PHARMA, retard médicament):
- u_time : 2 jours (ROUGE)
- u_cap : 65% (ORANGE)
- u_perf : TRS 72% (ORANGE)
- u_risk : P_fail 35% (ROUGE)
- u_cost : +150% surcoût (ORANGE)
- u_co2 : 95% budget (ORANGE)
→ 2 domaines ROUGE + 4 ORANGE = HIGH RISK

Rupture #2 (AUTO, replenishment standard):
- u_time : 8 jours (VERT)
- u_cap : 55% (VERT)
- u_perf : TRS 88% (VERT)
- u_risk : P_fail 8% (VERT)
- u_cost : +5% surcoût (VERT)
- u_co2 : 60% budget (VERT)
→ Tous VERT = LOW RISK (rupture due à événement exceptionnel, pas détectable)
```

### Phase 2 : Machine Learning

Avec suffisamment de cas historiques, entraîner un modèle :

```
Input:  (u_time, u_cap, u_perf, u_risk, u_cost, u_co2)
Output: P(rupture) ∈ [0%, 100%]
```

Le modèle apprend les **patterns** :
- "Si u_time = ROUGE + u_capacity = ROUGE → 85% rupture"
- "Si u_risk = ROUGE + u_perf = ROUGE → 90% rupture"
- Etc.

### Phase 3 : Déploiement en production

Chaque jour, calculer les 6 KPIs pour **toutes les commandes en cours**.

Afficher un **dashboard** :
- Commandes en zone verte → pas de souci
- Commandes en zone orange → à monitorer (possible action préventive)
- Commandes en zone rouge → alerte active → intervention management

---

## 🎯 Partie 6 : Exemple concret de bout en bout

### Cas réel : Scenario PHARMA (Table 46 du BST original)

```
Situation:
- Produit : Vaccin réfrigéré
- Patient en attente : 47 personnes
- Temps de destruction si rupture chaîne froid : 2h
- Deadline : D+0 (aujourd'hui, urgent!)
- Lead time livraison : 4h (complexe logistics)

Day 0 (Aujourd'hui) :
u_time : Deadline = NOW → Slack = -4h → ROUGE (déjà en retard!)
u_cap : Transport ultra-saturé → 95% → ROUGE
u_perf : Supplier TRS = 92% (bon) → VERT
u_risk : P_fail = 15% (low-med) → ORANGE (mais refrig risk = HIGH extra)
u_cost : Emergency air → +400% → ROUGE
u_co2 : Air transport → +600% vs budget → ROUGE

Score combiné:
- 4 ROUGE (time, capacity, cost, co2)
- 1 ORANGE (risk)
- 1 VERT (perf)
→ CRITICAL ALERT

Prédiction du modèle ML : P(rupture) = 92%

Action required: 
- Escalate to CEO/EMRG management
- Prepare Plan B (partial delivery / product substitute)
- Accept cost/carbon overage for life-critical delivery
```

---

## 📊 Partie 7 : Résumé des 6 KPIs

| # | KPI | Mesure | Signal | Zones |
|---|-----|--------|--------|-------|
| 1 | **Temps** | Slack, deadline proximity | "On court après le temps" | Slack < 0 = ROUGE |
| 2 | **Capacité** | Queue occupancy, saturation | "Réseau transport saturé" | Occupation > 80% = ROUGE |
| 3 | **Performance** | TRS (Availability × Performance × Quality) | "Machine fournisseur fonctionne mal" | TRS < 70% = ROUGE |
| 4 | **Risque** | P(failure), TTR, sévérité, expo externe | "Aléa et événements adverses" | P > 30% ou sévérité HIGH = ROUGE |
| 5 | **Coût** | Surcoûts urgence, pénalités, stockage | "Aucune solution rentable" | Surcoût > 30% = ROUGE |
| 6 | **CO₂** | Émissions vs budget, mode transport | "Conflit urgence vs durabilité" | Budget > 100% = ROUGE |

---

## ❓ Réponses directes à tes questions

### Q1 : "Comment ont-ils été sélectionnés?"

**Réponse** : 
Ces 6 KPIs couvrent les **6 domaines indépendants** qui causent une rupture réelle :
1. **Temps** : si pas assez de temps physique → impossible
2. **Capacité** : si réseau saturé → attente → le slack diminue
3. **Performance** : si fournisseur fragile → non-conformité probable
4. **Risque** : si aléa (météo, panne) → événement adverse
5. **Coût** : si pas de solution financièrement viable → pas d'issue
6. **CO₂** : si conflit urgence/durabilité → dilemme sans échappatoire

Ce sont les 6 causes ROOT d'une rupture en supply chain. Aucune n'est redondante.

---

### Q2 : "De quoi on parle précisément?"

**Réponse** :
- **u_time** = Slack restant (deadline - today - leadtime)
- **u_cap** = % d'occupation des files de transport (0-100%)
- **u_perf** = TRS du fournisseur = Dispo × Perf × Qualité
- **u_risk** = Probabilité de défaillance + TTR + Sévérité
- **u_cost** = Surcoûts pour contourner un problème
- **u_co2** = Émissions mesurées vs plafond carbone

Chacun mesure une **réalité physique/opérationnelle précise**.

---

### Q3 : "Quel est leur lien au risque de rupture?"

**Réponse** :
- Une rupture arrive quand **2+ KPIs sont critiques simultanément**
- Exemples donnés section 3 (Scénarios 1-4)
- Le modèle ML apprend les patterns : (KPI1, KPI2, KPI3...) → P(rupture)
- Permet de **prédire 1-2 semaines avant** qu'une rupture ne survienne

---

## 📚 Prochaines étapes

1. **Valider les seuils** avec domaine expertise (fournisseur, logisticien, financier)
2. **Collecter données historiques** de ruptures réelles
3. **Labéliser chaque rupture** avec les 6 KPIs
4. **Entraîner modèle ML** (Random Forest, XGBoost, ou Neural Net)
5. **Déployer dashboard** pour monitoring en temps réel
6. **Optimiser alertes** (tuner sensibilité, éviter faux positifs)

---

## Glossaire rapide

- **Slack** : Marge temporelle (deadline - today - leadtime)
- **TRS** : Taux Rendement Synthétique (indicateur performance machine)
- **TTR** : Time To Recovery (temps pour réparer après panne)
- **P(fail)** : Probabilité d'échec
- **Sévérité** : Nombre de tâches dépendantes impactées
- **Surcoûts** : Différence entre prix standard et prix urgence
- **Budget carbone** : Plafond d'émissions CO₂ annuel
- **Compliance** : Respect des règles/cibles

---

**Document autonome, complet**  
**Créé** : 2 juillet 2026  
**Pour** : Réunion avec référante innovation  
**Lisible par** : Quelqu'un sans connaissance technique du BST
