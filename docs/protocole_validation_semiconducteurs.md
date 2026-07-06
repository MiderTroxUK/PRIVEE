# Protocole de validation empirique — Crise des semi-conducteurs (2021)

**Statut** : plan d'action proposé, en attente de confirmation sur les points ouverts (§7).
**Objectif** : faire tourner SupplyScore sur un vrai réseau fournisseur inspiré d'une crise
industrielle réellement documentée (la pénurie mondiale de semi-conducteurs), avec
un Ur alimenté par des données réelles (INSEE, Kaggle, WSTS/SIA) et un Ud déclaré
par 8 consultants humains via le questionnaire AHP existant, pour :
1. mesurer la corrélation entre urgence déclarée et urgence réelle sur un cas réel,
2. tester si le service de criticité identifie correctement le nœud qui a réellement
   été le goulot d'étranglement mondial,
3. faire tourner le service de calibration sur un échantillon réel (pas illustratif),
4. comparer a posteriori la dynamique simulée à la chronologie réelle de la crise.

Ceci répond directement au manque identifié dans le mémoire (BST) : les résultats actuels
sont des exemples numériques vérifiés à la main, pas une étude empirique. Ce protocole
produit le premier vrai jeu de données de validation.

---

## 1. Réseau simulé (8 nœuds ↔ 8 consultants)

| Rang | Nœud | Rôle réel | Bloc Ur dominant | Consultant |
|---|---|---|---|---|
| 0 | Assemblage final satellite | Client final | — (mesure l'impact aval) | C1 |
| 1 | Intégrateur sous-système avionique | Assemble les cartes en sous-système | u_time, u_perf | C2 |
| 2 | Assembleur de cartes électroniques (PCB) | Monte les composants sur cartes | u_perf, u_cap | C3 |
| 3 | Distributeur de composants électroniques | Répartit l'approvisionnement | u_cap, u_cost | C4 |
| 3bis | Transporteur / logistique (fret) | Achemine composants et cartes | u_time, u_cost | C5 |
| 4 | Fondeur de semi-conducteurs | Fabrique les puces (nœud critique attendu) | u_risk, u_cap | C6 |
| 4bis | Fondeur secondaire (arc backup) | Source alternative, arc `ArcKind.BACKUP` | u_risk | C7 |
| 5 | Fournisseur de plaquettes de silicium | Matière première amont | u_risk, u_cost | C8 |

Le nœud 4 (fondeur) est l'hypothèse à tester : c'est lui qui a réellement été le goulot
d'étranglement mondial documenté (délais Broadcom 12,2→22,2 semaines en 2021,
sécheresse à Taïwan). Le service de criticité doit le faire ressortir en tête du
classement sans qu'on le lui souffle.

---

## 2. Fenêtre temporelle et calendrier de jeu

**Recommandation révisée** (compte tenu du budget réel de 20 min/jour × 8 consultants) :
plutôt que de rejouer les 18 mois complets de la phase aiguë, se concentrer sur la
fenêtre la plus dense en signal — **T2 2021 à T4 2021** (~9 mois réels), qui couvre le
doublement des délais, la sécheresse taïwanaise, et les premiers arrêts de production
Toyota/GM. C'est la portion la plus riche pour tester si le modèle détecte une montée
d'urgence, pas seulement un état stable.

- Compression : 1 tour de jeu = 1 mois réel → **9 tours**.
- Cadence proposée : 1 tour/semaine calendaire → campagne de ~9-10 semaines.
  *Alternative si trop long : 2 tours/semaine → ~5 semaines, à valider avec les consultants.*
- Volumétrie attendue : 8 nœuds × 9 tours = **72 observations (nœud, tour)**, largement
  au-dessus du seuil de 30 déjà posé dans le service de calibration.

---

## 3. Déroulé d'un tour (budget : 20 min/consultant)

1. **Briefing (5 min)** : une fiche d'une page par nœud, contenant uniquement les données
   réelles disponibles jusqu'au tour courant (jamais de valeur future). Diffusion
   strictement incrémentale — le tour N+1 n'est envoyé qu'après validation du tour N.
2. **Questionnaire AHP (10 min)** : les 4 critères déjà en place (impact opérationnel,
   fenêtre temporelle, dépendances aval, récupérabilité), pré-rempli avec la valeur de
   la semaine précédente (mécanisme "confirmer à l'identique" déjà existant).
3. **Note qualitative courte (5 min, optionnelle)** : une phrase sur ce qui a motivé le
   jugement, pour l'analyse a posteriori en phase E.

**Anonymisation (par défaut, à confirmer)** : dates décalées d'un offset fixe et noms
d'entités remplacés par des rôles génériques ("Fondeur A", "Semaine 6 du scénario")
plutôt que les vrais noms/dates. Les valeurs et magnitudes réelles des séries sont
conservées à l'identique — seul l'habillage identifiant change. Objectif : limiter la
récitation d'un souvenir de presse plutôt que d'un jugement en aveugle, tout en gardant
la donnée sous-jacente authentique. Si transparence totale préférée, il suffit de retirer
cette étape (aucun impact sur le reste du protocole).

---

## 4. Sourcing des données Ur — statut honnête par nœud

| Nœud | Source proposée | Statut |
|---|---|---|
| Fondeur (4) | WSTS/SIA Historical Billings Report (mensuel, gratuit, sans compte) | Vérifié public |
| Fondeur (4) | Kaggle *Semiconductor shortage 1985-2021* (PPI, emploi, prod. industrielle) | À vérifier (couverture exacte 2021, provenance) |
| Fondeur (4) | INSEE, Indice production NAF 26.1/26.11 composants électroniques (série 010768009) | Vérifiée existante (portée France, à croiser avec données mondiales ci-dessus) |
| Distributeur (3) | INSEE, Défaillances d'entreprises (001656157/001656101) | Vérifiée existante, série longue |
| Assembleur cartes (2) | INSEE, Indice production NAF 26.1 | Vérifiée existante |
| Transporteur (3bis) | Kaggle *Logistics and Supply Chain Dataset* (Sud Californie, 2021-2024, champ Lead Time) | À vérifier (authenticité collecte réelle vs simulée) |
| Transporteur (3bis) | Indice de fret (Baltic Dry Index ou équivalent) | Non recherché — à faire si retenu |
| Silicium (5) | Indice matières premières / polysilicium | Non identifié — à rechercher |
| Intégrateur avionique (1), Assemblage final (0) | Pas de source externe directe identifiable à ce niveau (spécifique satellite) | Assumé : urgence largement déclarative/projet, pas de série externe réelle attendue |
| u_co2 (tous nœuds) | — | Assumé plat/faible pour ce scénario, comme observé pour l'analogie médicale — ne pas forcer un signal artificiel |

Ce tableau assume explicitement un mélange : certains nœuds auront un Ur presque
entièrement piloté par des séries réelles, d'autres resteront partiellement déclaratifs.
C'est un choix documenté, pas un point aveugle — cohérent avec la limite déjà actée
dans le BST ("la fraîcheur des scores = la cadence de saisie").

---

## 5. Plan d'analyse

- **Phase A — Collecte** : 9 tours, Ud(t) déclaré par les 8 consultants, Ur(t) calculé
  automatiquement depuis les séries chargées.
- **Phase B — Corrélation Ud/Ur** : par nœud et par tour, calculer $\Delta U$, $F$
  (fausse urgence), $H$ (risque caché) et $A(t)$. Question centrale : le nœud fondeur
  affiche-t-il un $H$ élevé (risque caché, sous-déclaré) avant que la crise ne soit
  visible dans les déclarations des autres nœuds ? C'est le test direct de la thèse de
  détection précoce du mémoire.
- **Phase C — Criticité réseau** : faire tourner `ServiceCriticite` à chaque tour ;
  vérifier si le fondeur ressort structurellement en tête du classement de criticité,
  et à partir de quel tour.
- **Phase D — Calibration réelle** : une fois les 9 tours complétés, lancer le service
  de calibration avec, comme incidents réels de référence, les événements documentés
  (arrêts de production Toyota -40%, arrêts GM) plutôt qu'un exemple jouet — premier F1/
  précision/rappel réel du mémoire.
- **Phase E — Confrontation à la réalité** : comparer qualitativement le tour où le
  modèle a "vu" la criticité monter à la date réelle où la presse spécialisée a identifié
  la même montée (chronologie déjà sourcée : délais Broadcom, sécheresse Taïwan).

---

## 6. Ce que ça apporte au mémoire (BST)

- Remplace l'exemple numérique illustratif de la section Operations par une vraie étude
  empirique (72 observations réelles au lieu d'un exemple à la main).
- Répond à Lock 3 (valeur ajoutée du signal d'adéquation) avec des données réelles.
- Fournit le premier résultat quantitatif exploitable pour un futur papier scientifique
  (le manque identifié précédemment : pas de résultats chiffrés sur données réelles).

---

## 7. Points ouverts à trancher avant de lancer la collecte

1. Anonymat par défaut (§3) ou transparence totale ? *(proposition par défaut : anonymat)*
2. Cadence 1 tour/semaine (~9-10 semaines) ou 2 tours/semaine (~5 semaines) ?
3. Qui prend en charge le sourcing/nettoyage des séries retenues (script de collecte
   automatisable si utile) ?
4. Sources encore à identifier : fret (transporteur), silicium (nœud 5) — recherche à
   poursuivre si ces nœuds sont conservés tels quels.
5. Fenêtre T2-T4 2021 confirmée, ou préférence pour une autre sous-fenêtre ?
