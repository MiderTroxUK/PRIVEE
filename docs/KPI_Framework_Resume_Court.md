# KPI Framework — Résumé Court
## 6 indicateurs pour prédire une rupture de chaîne logistique

**Pour ta réunion** — version "cheat sheet" à lire en 3-4 minutes.

---

## Pourquoi ces 6 KPIs?

Une **rupture** n'a jamais UNE cause. Elle résulte du croisement de plusieurs facteurs:
- **Temps** : margé temporelle qui s'érode
- **Capacité** : transport saturé, files d'attente pleines  
- **Performance** : machines du fournisseur qui dysfonctionnent
- **Risque** : probabilités d'événements adverses + incapacité à se rétablir
- **Coût** : surcoûts qui explosent (pas d'issue économique)
- **CO₂** : carbon budget épuisé (rupture de compliance)

## Provenance : où est-ce qu'on les trouve dans le modèle DISCO?

| KPI | Equation/Concept BST | Où c'est? |
|-----|----------------------|-----------|
| **u_time** | $U_r(t) = \tanh(K / (t_c - t))$ | Fondation du modèle — deadline proximity |
| **u_cap** | LSTR Rate, queue thrashing prevention | Active Gantt scheduler, Physical Internet |
| **u_perf** | Supplier risk scorer $r_i$ | DISCO database, Kabouche 2025 |
| **u_risk** | $P_{\text{bayes}}$, Crisis Penalty $C_{\text{crise}}(t)$ | Bayesian model + LSTR |
| **u_cost** | Min-Max scoring (comme CO₂) | Analogie DISCO scoring engine |
| **u_co2** | $\text{CO}_2$ dans $V_{\text{mc}}$ | Business Value outranking, Cordova 2024 |

## Ce qu'ils mesurent précisément

### 🕐 **Temps** (u_time)
- Slack restant $S_i(t) = d_i - t - \varepsilon_i$
- Lead time vs deadline
- → **Signal de détection** : quand on court après le temps

### 📦 **Capacité** (u_cap)  
- % d'occupation des files d'attente
- Volume/poids transporté vs capacité disponible
- → **Signal de saturation** : quand on ne peut plus absorber

### ⚙️ **Performance** (u_perf)
- OEE du fournisseur = Availability × Performance × Quality
- MTBF, downtime, defect rate
- → **Signal opérationnel** : quand les machines dysfonctionnent

### ⚠️ **Risque** (u_risk)  
- Probabilité de délai $P_{\text{bayes}}$
- TTR (temps de récupération après défaillance)
- Sévérité (combien de tâches bloquées)
- → **Signal d'aléa** : quand la probabilité d'événement adverse augmente

### 💰 **Coût** (u_cost)
- Surcoûts de sourcing d'urgence
- Pénalités SLA si retard
- Coûts de stockage tampon
- → **Signal économique** : quand y'a aucune issue rentable

### 🌱 **CO₂** (u_co2)  
- Émissions mesurées vs budget carbone
- Mode de transport (air rapide/lourd, bateau lent/léger)
- → **Signal ESG** : quand on viole les cibles carbone

---

## Scénarios de rupture réelle : combinaisons critiques

**Rupture = 2+ KPIs franchissent le seuil ROUGE simultanément**

| Scénario | KPIs impliqués | Exemple |
|----------|----------------|---------|
| **Saturation + Urgence** | u_time + u_cap | Deadline demain, queue pleine à 90% |
| **Fournisseur fragile** | u_risk + u_perf | Probabilité délai 60%, machine downtime 30% |
| **Pas d'issue** | u_cost + u_co2 | Air transport résout timing mais double CO₂ |
| **Cascade défaillance** | u_risk + u_risk | Fournisseur A retard → bloque 5 tâches dépendantes |
| **Chaos complet** | u_time + u_cap + u_risk | Deadline in 2 days, suppliers all saturated, supplier in trouble |

---

## Comment on va l'utiliser?

### Phase 1 (calibration)
- Fixer les seuils VERT/ORANGE/ROUGE pour chaque KPI par industrie
- Exemple : u_time (Slack < 0 = rouge), u_cap (Queue > 80% = rouge)

### Phase 2 (historique)
- Récupérer cas historiques de ruptures réelles chez clients DISCO  
- Annoter chaque rupture avec les 6 KPIs au moment du risque
- → Voir les patterns

### Phase 3 (prédiction)
- Modèle ML : (u_time, u_cap, u_perf, u_risk, u_cost, u_co2) → **P(rupture)**  
- Fonctionne mieux que chaque KPI seul

---

## Réponses rapides à tes questions

### ❓ "Comment ont-ils été sélectionnés?"
→ Couverture **orthogonale** des domaines causant une rupture (chacun indépendant) + intégration dans le modèle DISCO existant (5/6 déjà là)

### ❓ "De quoi on parle précisément?"
→ Chaque KPI mesure **une dimension physique** (temporelle, flux, opérationnel, probabiliste, financière, environnementale)

### ❓ "D'où ils proviennent?"
→ **u_time** : fondation de U_r(t) BST  
→ **u_cap** : LSTR + Physical Internet  
→ **u_perf** : Supplier risk scorer DISCO  
→ **u_risk** : Bayesian + Crisis Penalty  
→ **u_cost** : Scoring engine analogue  
→ **u_co2** : Green supply chain pillar + GLEC

---

## Docs de référence

- 📄 **KPI_Framework_Explication.md** : Doc complète avec équations et justifications détaillées
- 📄 **BST_DISCO_JH_2026/main.pdf** : Modèle académique complet
- 📊 **Prochaine étape** : Mettre en place data collection pour calibrer les thresholds

---

**Créé le** : 2 juillet 2026  
**Pour qui** : Réunion avec ta référante d'innovation (R&D)  
**Durée de lecture** : ~4 minutes
