# SupplyScore — Démo éclair 6 min (Programme AERIS)

Version condensée de [DEMO_20MIN.md](DEMO_20MIN.md) — même pré-vol (§2),
mêmes chiffres (§5), même FAQ (§6). On garde 4 temps forts : le problème,
le dashboard, l'explication, le tour de jeu live. On SACRIFIE : la slide
modèle détaillée, la simulation, le rapport (à montrer seulement si question).

## Règle d'or

6 minutes = zéro navigation hésitante. Onglets pré-ouverts (`/dashboard`,
`/hebdo`), projet AERIS déjà sélectionné, horloge en mode jeu, opérateur
prérempli. Une phrase d'annonce : *« données simulées, 8 semaines de jeu
déjà jouées par 10 acteurs nommés »*.

## Déroulé minuté

### 0:00–1:00 — Le problème (1 slide, pas d'app)
Toute supply chain souffre de deux maladies invisibles dans les tableaux de
bord : la **fausse urgence F** (on crie au loup, on paie des stocks pour
rien) et le **risque caché H** (les capteurs hurlent, personne ne déclare).
Aucun outil du marché ne mesure l'écart entre ce que les humains *déclarent*
et ce que les données *montrent*. C'est ce que fait SupplyScore.
Le chiffre choc : même écart, **A = 29,3** si on panique pour rien,
**A = 0** si on ne voit pas le danger — parce que sous-estimer coûte
**2,25×** plus cher (Prospect Theory, Kahneman-Tversky).

### 1:00–2:30 — Dashboard : « où ça fait mal » (`/dashboard`)
Le modèle se raconte EN montrant, pas avant :
1. Les cartes : A moyen 68,7, **pire nœud PowerChip A = 46,5**, 1 risque
   caché, 6 fausses urgences.
2. Le **DAG coloré** : la chaîne entière d'un coup d'œil (Toulouse → lithium
   du Chili), le besoin descend, le risque remonte.
3. Tableau des nœuds, colonnes **A/F/H** : PowerChip est le SEUL avec H > 0
   pendant que cinq autres ont F > 0 — *« tout le monde panique, sauf celui
   qui devrait »*. (Ud = l'urgence déclarée au questionnaire ; Ur = 6
   détecteurs de fumée KPI ; A = leur confrontation.)

### 2:30–3:30 — « Pourquoi 46,5 ? » : l'anti-boîte noire
Cliquer « **Expliquer** » sur PowerChip :
- l'alerte rouge « retard avéré, u_time forcé à 1 » ;
- **l'équation instanciée** `pénalité = 2.25×0.24^0.88` → A = 46,5 ;
- le journal d'audit : chaque chiffre est traçable (qui, quand, quelle
  source). Message : **l'outil se défend tout seul.**

### 3:30–5:15 — Le tour de jeu EN DIRECT (le moment fort)
On joue la semaine 9 devant le public :
1. Opérateur = **Mei** ; page Projets → « **Avancer d'une semaine** » —
   *un clic = un tour de jeu pour toute la chaîne*.
2. `/hebdo` → « PowerChip Semiconducteurs » : **monter les notes AHP**
   (Mei « avoue » enfin), passer le jalon « Proto » à **terminé**,
   « Clôturer la revue ». (On saute le volet décision si ça dépasse.)
3. Retour `/dashboard` : **le H fond, A remonte ~46 → 75+**, la carte
   « Risques cachés » passe à 0. *« Le score ne récompense pas la bonne
   nouvelle : il récompense la déclaration honnête ET le jalon réellement
   clôturé. »*

### 5:15–6:00 — La preuve & la suite (1 slide)
- 18 phases livrées, **1 607 tests**, couverture 94,1 %, 13 pages,
  budgets perf tenus à 1 000 nœuds.
- Des scores, pas des prophéties ; saisie manuelle assumée.
- **Prochaine étape : le serious game réel** — le banc d'essai qui servira
  à recalibrer le modèle sur des données constatées.

## Si on vous donne 2 min de plus (questions)
- « Et si un fournisseur tombe ? » → `/simulation` : choc « Défaillance
  totale » sur Lithium Andes, la contamination remonte jusqu'au client ;
  « Analyser la criticité » = le plan de continuité qui s'écrit tout seul.
- Toute question piège : réponses en 1 phrase dans DEMO_20MIN.md §6.

## Coupes de secours si vous dérapez
- À 3:30 vous n'avez pas fini le dashboard → sautez l'explication, le tour
  de jeu live est non négociable.
- Le live plante → captures `docs/presentation/screenshots/` (scènes 14 et
  suivantes = le tour de jeu déjà capturé).
