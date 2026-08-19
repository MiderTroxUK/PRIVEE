# SupplyScore — Soutenance de thèse - Design Spec

> Support de présentation pour la soutenance de doctorat de John Hoarau, consacrée au framework SupplyScore (alignement de l'urgence perçue et de l'urgence réelle dans les chaînes logistiques multi-rangs). Contenu adapté en français à partir de `docs/Presentation script.md` (source de vérité technique) et vérifié contre le code source (`supplyscore/`) et `docs/*.md`.

## I. Project Information

| Item | Value |
| ---- | ----- |
| **Project Name** | SupplyScore — Soutenance de thèse |
| **Canvas Format** | PPT 16:9 (1280×720) |
| **Page Count** | 29 (28 + une annexe bibliographique) |
| **Design Style** | Académique rigoureux — mode `instructional`, style `swiss-minimal` |
| **Target Audience** | Jury de thèse (génie industriel / recherche opérationnelle / supply chain), chercheurs et ingénieurs techniques |
| **Use Case** | Soutenance de doctorat — masterclass technique de 3 heures, présentée puis projetée, avec notes de présentateur détaillées |
| **Delivery Purpose** | `balanced` — présenté ET lu de près (formules, tables, chemins de code scrutés par le jury) ; corps de texte 24px |
| **Content Strategy** | Proche de la source : le script (`Presentation script.md`, 21 sujets) est la référence technique faisant autorité — traduction et réorganisation en français, densité augmentée par endroits (28 pages) pour laisser respirer les formules et les captures d'écran, mais aucun fait, chiffre ou référence de code n'est inventé au-delà de ce que le script et le code vérifient. |
| **Created Date** | 2026-07-02 |

---

## II. Canvas Specification

| Property | Value |
| -------- | ----- |
| **Format** | PPT 16:9 |
| **Dimensions** | 1280×720 |
| **viewBox** | `0 0 1280 720` |
| **Margins** | 56px gauche/droite, 48px haut/bas |
| **Content Area** | 1168×624 (hors marges) |

---

## III. Visual Theme

### Theme Style

- **Mode**: `instructional` — décomposition pédagogique, un concept par page, "montrer puis énoncer" (l'exemple numérique concret précède toujours le principe abstrait), structure parallèle pour les concepts frères (les 6 deep dives et les 8 showcases suivent chacun un gabarit constant). Correspond exactement à la nature du script fourni : "masterclass et parcours technique".
- **Visual style**: `swiss-minimal` — grille stricte, géométrie nette, quasi zéro décoration, contraste de graisse plutôt que de famille de police. Registre académique rigoureux (cabinets de conseil haut de gamme, architecture, décks type-driven) — cohérent avec le choix de style validé par l'auteur.
- **Theme**: Thème clair (fond quasi blanc, une seule zone de couleur dominante par page, jamais de dégradé).
- **Tone**: Rigoureux, précis, dense en formules et schémas, mais aéré par une grille modulaire généreuse — jamais décoratif pour décorer.

### Color Scheme

> Palette reprise directement de la charte réelle de l'application SupplyScore (`supplyscore/web_ui/components/layout.py::COLORS`), pour une cohérence visuelle totale entre les diapositives et les captures d'écran du logiciel montrées en direct.

| Role | HEX | Purpose |
| ---- | --- | ------- |
| **Background** | `#FFFFFF` | Fond de page (quasi blanc, discipline swiss-minimal) |
| **Secondary bg** | `#F4F6F8` | Fond de carte / zone de section / bandeau (identique au fond de l'app) |
| **Primary** | `#2C5F7C` | Titres, structure, icônes, la "zone dominante" de chaque page |
| **Primary dark** | `#1E4258` | Bandeaux profonds, fonds de section chapitre, texte sur fond clair à fort contraste |
| **Accent** | `#B06000` | Mise en évidence ponctuelle (insight, alerte "fausse urgence" — couleur `warn` de l'app) |
| **Secondary accent** | `#1D7A3E` | Validation, résultats positifs, cohérence AHP/FBWM confirmée (couleur `ok` de l'app) |
| **Critical** | `#B3261E` | Risque caché / pathologies critiques (couleur `alert` de l'app — réservé au message le plus grave : sous-déclaration du risque) |
| **Body text** | `#22313A` | Texte courant |
| **Secondary text** | `#6B7A85` | Légendes, annotations, texte muted |
| **Tertiary text** | `#9AA5AC` | Notes de bas de page, sources, numéros de page |
| **Border/divider** | `#D8DEE3` | Bordures de carte, séparateurs |
| **Grid (hairline)** | `#E8ECEF` | Grille de fond, lignes de repère de graphiques |
| **Success** | `#1D7A3E` | Indicateurs positifs |
| **Warning** | `#B06000` | Fausse urgence, avertissements |

> Aucune image `ai` n'est utilisée dans ce deck (voir §VIII) — la section AI Image Strategy est omise.

### Gradient Scheme

Aucun dégradé — discipline `swiss-minimal` stricte (surfaces plates uniquement).

---

## IV. Typography System

### Font Plan

**Typography direction**: Sans-serif unique, contraste de graisse (900/300) plutôt que de famille — discipline `swiss-minimal` §2. Police reprise de l'application elle-même (`FONT_FAMILY` dans `layout.py`) pour ancrer le deck dans l'identité visuelle réelle du logiciel montré en direct. Un stack monospace dédié porte les chemins de code et les identifiants techniques (très nombreux dans ce deck).

| Role | Chinese | English | Fallback tail |
| ---- | ------- | ------- | ------------- |
| **Title** | — | `Segoe UI` (Semibold/Bold via font-weight) | `Arial, sans-serif` |
| **Body** | — | `Segoe UI` | `Arial, sans-serif` |
| **Emphasis** | — | `Segoe UI` (weight 600, couleur primary/accent) | `Arial, sans-serif` |
| **Code** | — | `Consolas` | `"Courier New", monospace` |

**Per-role font stacks**:

- Title: `"Segoe UI", Arial, sans-serif` (weight 700-800)
- Body: `"Segoe UI", Arial, sans-serif` (weight 400) — identique à Title (concord, contraste par la graisse)
- Emphasis: identique à Body (weight 600)
- Code: `Consolas, "Courier New", monospace`

### Font Size Hierarchy

**Baseline (px)**: Body = **24px** (`balanced`).

| Rôle | Taille (px) | Poids |
| --- | ---: | --- |
| Cover title (hero, P01) | 96 | 800 |
| Chapter opener (P04 agenda) | 56 | 700 |
| Page title | 42 | 700 |
| Hero number (KPI, ex. "1614 tests") | 52 | 800 |
| Subtitle | 32 | 600 |
| Lead / message-clé de page | 28 | 500 |
| Subheading (en-tête de bloc / carte) | 26 | 600 |
| **Body** | **24** | 400 |
| Annotation / légende | 18 | 400 |
| Code inline / chemins de fichiers | 17 | 400 (mono) |
| Footnote / numéro de page / source | 16 | 400 |

---

## V. Layout Principles

### Page Structure

- **Header area**: 0-110px — bandeau titre + kicker (numéro de deep dive / catégorie) + petit repère de navigation (chapitre courant)
- **Content area**: 110-660px — grille modulaire (colonnes de 1168px / gouttière 32px)
- **Footer area**: 660-720px — filet fin `#D8DEE3`, numéro de page, `SupplyScore — Soutenance de thèse`, référence de fichier code le cas échéant

### Layout Pattern Library (utilisés dans ce deck)

- **Single column centered** — couverture, page de clôture
- **Asymmetric split (3:7 / 6:6)** — deep dives (équations à gauche, diagramme/exemple à droite ou l'inverse en alternance Z-pattern)
- **Top-bottom split** — pages showcases (bandeau capture d'écran en haut, analyse structurée en dessous)
- **Matrix grid (3×3)** — les 9 hypothèses de modélisation (P05), le panorama des 13 pages (P07, grille 4×4 incomplète)
- **Center-radiating** — schéma de propagation DAG, schéma des strates cognitives
- **Full-bleed + floating text** — P03 (schéma strates cognitives), P16 (comparaison panique / risque caché)
- **Negative-space-driven** — P02 (contexte auteur), P27 (rétrospective)

### Spacing Specification

| Element | Valeur retenue |
| ------- | ---------------- |
| Marge de sécurité | 56px (côtés), 48px (haut/bas) |
| Gap entre blocs de contenu | 32px |
| Gap icône-texte | 12px |
| Card gap | 24px |
| Card padding | 24px |
| Card border radius | 0-4px (discipline swiss-minimal : angles droits) |
| Largeur carte 3 colonnes | ~368px |
| Largeur carte 4 colonnes (grille 13 pages) | ~268px |

---

## VI. Icon Usage Specification

### Source

- **Bibliothèque**: `templates/icons/tabler-outline/` — trait fin, aéré, raffiné ; se marie avec la discipline swiss-minimal et reste lisible en projection.
- **Stroke width**: 2 (verrouillé pour tout le deck)
- **Usage method**: `<use data-icon="tabler-outline/<name>" .../>`

### Recommended Icon List

| Purpose | Icon Path |
| ------- | --------- |
| Cible / objectif | `tabler-outline/target` |
| Cerveau / cognition | `tabler-outline/brain` |
| Alerte / urgence | `tabler-outline/alert-triangle` |
| Graphe / DAG | `tabler-outline/sitemap` |
| Base de données | `tabler-outline/database` |
| Cadenas / audit | `tabler-outline/shield-check` |
| Calculatrice / maths | `tabler-outline/calculator` |
| Balance / arbitrage | `tabler-outline/scale` |
| Dé / stochastique | `tabler-outline/dice-5` |
| Horloge / temporalité | `tabler-outline/clock` |
| Calendrier | `tabler-outline/calendar` |
| Utilisateurs / opérateurs | `tabler-outline/users` |
| Flèche de tendance haussière | `tabler-outline/trending-up` |
| Flèche de tendance baissière | `tabler-outline/trending-down` |
| Coche validée | `tabler-outline/circle-check` |
| Croix / échec | `tabler-outline/circle-x` |
| Cloche / événement | `tabler-outline/bell` |
| Export / fichier | `tabler-outline/file-export` |
| Réglages | `tabler-outline/settings` |
| Œil / explicabilité | `tabler-outline/eye` |
| Serveur | `tabler-outline/server` |
| Sauvegarde | `tabler-outline/database-export` |
| Filtre / pondération | `tabler-outline/adjustments` |
| Robot / agent autonome | `tabler-outline/robot` |
| Carte / feuille de route | `tabler-outline/map` |
| Livre / documentation | `tabler-outline/book-2` |
| Flèche directionnelle | `tabler-outline/arrow-right` |
| Rapport / liste | `tabler-outline/report` |
| Réseau / propagation | `tabler-outline/topology-star-3` |
| Éprouvette / simulation | `tabler-outline/flask` |
| Engrenage / moteur | `tabler-outline/settings-automation` |

> Liste finalisée et vérifiée par `icon_sync.py` avant génération (§ exécution) ; seuls les noms confirmés existants seront copiés dans `icons/`.

---

## VII. Visualization Reference List

Aucune page de ce deck ne correspond à un template de `templates/charts/` (les visualisations sont toutes des diagrammes techniques sur mesure : DAG de propagation, matrices AHP, courbes de Prospect Theory, comparaisons de flux PROMETHEE, histogrammes Monte Carlo). Conception libre par l'Executor selon §III/§IV/§V. `no-template-match` pour l'ensemble du deck.

Runners-up considérés (aucun ne correspond à la nature du contenu) :
- `grouped_bar_chart` | écarté : nos comparaisons (Cas A vs Cas B, P16) ont seulement 2 catégories avec une asymétrie conceptuelle forte qui a besoin d'une mise en scène (courbes de pénalité), pas d'un simple histogramme groupé
- `quadrant_bubble_scatter` | écarté : aucune page ne classe des entités sur deux axes continus
- `timeline_horizontal` | écarté : la temporalité du projet (P27) est mieux servie par un diagramme d'état (3 horloges) que par une frise chronologique

---

## VIII. Image Resource List

Toutes les images sont des captures d'écran réelles de l'application, déjà fournies par l'utilisateur (`docs/presentation/screenshots/`, copiées dans `images/`). Aucune génération IA, aucune recherche web. `Acquire Via: user` pour toutes les lignes ; `Status: Existing`.

| Filename | Dimensions | Ratio | Purpose | Type | Layout pattern | Acquire Via | Status | page_role |
| -------- | --------- | ----- | ------- | ---- | -------------- | ----------- | ------ | --------- |
| 01-projets.png | 1898×926 | 2.05 | Écran d'accueil : création de projet, nœuds, horloge jeu/réel | Screenshot | Top-bottom split | user | Existing | local |
| 02-onboarding.png | 1898×926 | 2.05 | Wizard d'onboarding 4 étapes | Screenshot | Top-bottom split | user | Existing | local |
| 04-questionnaire-pleine-page.png | 1898×2776 | 0.68 | Questionnaire AHP pleine page (curseurs bipolaires) | Screenshot | Asymmetric split 6:6 | user | Existing | local |
| 08-ponderation-pleine-page.png | 1898×1200 | 1.58 | Interface F-BWM (Best/Worst) | Screenshot | Top-bottom split | user | Existing | local |
| 09-graphe-pleine-page.png | 1898×2227 | 0.85 | Éditeur de graphe (DAG, arcs γ/β) | Screenshot | Asymmetric split 6:6 | user | Existing | local |
| 06-simulation-pleine-page.png | 1898×2821 | 0.67 | Simulation Monte Carlo, distributions de délais | Screenshot | Asymmetric split 6:6 | user | Existing | local |
| 12-fiche-noeud-pleine-page.png | 1898×3124 | 0.61 | Fiche nœud 360° (classement PROMETHEE) | Screenshot | Asymmetric split | user | Existing | local |
| 13-explication-pleine-page.png | 1898×2139 | 0.89 | Page d'explication XAI | Screenshot | Top-bottom split | user | Existing | local |
| 14-hebdo-noeud-crise-pleine-page.png | 1898×4019 | 0.47 | Revue hebdomadaire, 4 volets | Screenshot | Top-bottom split | user | Existing | local |
| 17-rapport-session-pleine-page.png | 1898×5966 | 0.32 | Rapport de session / moteur d'événements | Screenshot | Top-bottom split | user | Existing | local |
| 15-simulation-choc-pleine-page.png | 1898×3062 | 0.62 | Scénarios what-if / chocs | Screenshot | Top-bottom split | user | Existing | local |
| 11-admin.png | 1898×926 | 2.05 | Page admin (bases SQLite, sauvegardes) | Screenshot | Top-bottom split | user | Existing | local |
| 16-simulation-criticite-pleine-page.png | 1898×3212 | 0.59 | Classement de criticité systématique | Screenshot | Top-bottom split | user | Existing | local |
| 10-rapport.png | 1898×926 | 2.05 | Rapport HTML de session (calibration) | Screenshot | Top-bottom split | user | Existing | local |
| 07-edition.png | 1898×926 | 2.05 | Édition KPI en masse | Screenshot | Top-bottom split | user | Existing | local |
| 05-dashboard-pleine-page.png | 1898×3254 | 0.58 | Dashboard principal, DAG coloré par adéquation | Screenshot | Top-bottom split | user | Existing | hero_page (P07) |
| 03-hebdo.png | 1898×926 | 2.05 | Aperçu revue hebdomadaire | Screenshot | Top-bottom split | user | Existing | local |

Formules rendues en PNG (voir `images/formula_manifest.json`, générées via `latex_render.py` avant l'Executor) — policy `mixed` : les expressions complexes (fractions, produits, sommes, exposants imbriqués) sont rendues en PNG ; les expressions courtes restent en texte SVG natif (`F=[Ud-Ur]₊`, `CR=CI/RI`, `φ(a)=φ⁺(a)-φ⁻(a)`, etc.).

---

## IX. Content Outline

> Rythme narratif du mode `instructional` : chaque deep dive suit le même gabarit (montrer l'exemple concret → énoncer le principe → équation), chaque showcase fonctionnel suit le même gabarit (capture d'écran → ce que ça résout → référence code). Cette régularité aide un jury à cartographier mentalement 21 sujets techniques sur 3 heures.

### Partie 0 — Ouverture : pourquoi ce projet compte

#### Slide 01 - Couverture
- **Cover impact**: Accroche par affirmation provocante + chiffre-clé : le "syndrome du village qui crie au loup" appliqué à la supply chain, chiffré par un hero-number (ex. "1614 tests, 94% couverture, un moteur mathématique inédit"). Composition : poster typographique pur (pas de photo), grand titre sur fond quasi blanc, une ligne d'accent bleu structurant la page en deux zones.
- **Layout**: Single column centered, poster typographique, bandeau inférieur avec 3 hero-numbers (Ud/Ur/A) discrets
- **Title**: SupplyScore
- **Subtitle**: Aligner la perception subjective de l'urgence et la réalité physique des chaînes logistiques
- **Info**: John Hoarau — Soutenance de thèse — 2026

#### Slide 02 - Contexte, porteur du projet & origine industrielle
- **Layout**: Asymmetric split 4:6 — portrait/bloc identité à gauche, capture d'écran onboarding à droite
- **Title**: Un ingénieur supply chain face à un problème non résolu
- **Core message**: SupplyScore naît d'un constat de terrain répété dans l'automobile et l'aéronautique — les MRP sont mathématiquement optimaux mais opérationnellement fragiles car ils ignorent l'état cognitif des humains qui les pilotent.
- **Content**:
  - John Hoarau, ingénieur industriel et data scientist supply chain — recherche opérationnelle, simulation stochastique, facteurs humains en logistique
  - L'onboarding d'un nœud (capture) formalise déjà cette rencontre entre discipline mathématique et réalité de terrain : identité & topologie → cahier des charges → KPIs → première évaluation AHP
  - Objectif du projet : formaliser les heuristiques subjectives des coordinateurs avec des outils MCDA et stochastiques robustes, puis les déployer dans un vrai logiciel — pas seulement un article

#### Slide 03 - La problématique : le biais cognitif de l'urgence déclarée
- **Layout**: Full-bleed + floating text — grand schéma en deux strates (subjectif / objectif) au centre, titre et légende flottants
- **Title**: Crier au loup coûte cher : le fossé entre perception et réalité
- **Core message**: Quand la déclaration d'urgence est gratuite et universelle, elle cesse d'être informative — les équipes se désensibilisent et ratent les vrais signaux critiques.
- **Content**:
  - Strate subjective (Ud) : perception humaine, biais émotionnel, optimisation locale, panique
  - Strate objective (Ur) : stocks, délais, capacité physique, contraintes réseau
  - Le cercle vicieux : sur-déclaration généralisée → saturation du transport premium → fatigue opérationnelle → signaux critiques ignorés
  - **Ce qui est nouveau** : SupplyScore est la première couche de traduction mathématique et comparative entre ces deux strates — pas un simple tableau de bord, mais un moteur d'adéquation asymétrique qui quantifie et distingue *fausse urgence* et *risque caché*

#### Slide 04 - Feuille de route de la présentation
- **Layout**: Single column, liste structurée en 4 blocs numérotés (chapitre opener)
- **Title**: Trois heures, quatre mouvements
- **Content**:
  - I. Fondations — hypothèses de modélisation, architecture logicielle, panorama fonctionnel (P05-P07)
  - II. Six deep dives mathématiques — AHP, F-BWM, PROMETHEE II, Monte Carlo, propagation DAG, adéquation asymétrique (P08-P16)
  - III. Huit démonstrations opérationnelles — du cycle hebdomadaire aux exports (P17-P24)
  - IV. Synthèse & perspectives — score unifié, agents de décision autonomes, rétrospective (P25-P28)

### Partie 1 — Fondations

#### Slide 05 - Fondements & invariants de modélisation
- **Layout**: Matrix grid 3×3 (9 cartes compactes)
- **Title**: Neuf hypothèses qui garantissent la cohérence du système
- **Core message**: Chaque hypothèse de modélisation est un choix assumé, documenté et vérifiable dans le code — pas une simplification cachée.
- **Content** (icône + libellé court + implication en une ligne, détail complet en notes) :
  - DAG acyclique (rang 0 = client final) → tri topologique O(V+E), cycles rejetés en base
  - Discrétisation hebdomadaire ISO → clés `iso_week`, comparaisons alignées
  - Damping descendant de Ud (facteur γ) → panique amortie en aval
  - Contamination ascendante de Ur (facteur β) → risque amplifié en amont
  - Indépendance Noisy-OR des 6 blocs KPI → agrégation probabiliste
  - Règles de statut (DONE/ABANDONED) → Ur local à 0 ou 1
  - Indépendance stochastique PERT → simulation Monte Carlo rapide O(N·n)
  - Perte cognitive asymétrique (λ_under=2.25 > λ_over=1.0) → la complaisance est punie plus fort que la panique
  - Isolation multi-tenant (une base SQLite par nœud) → pas de verrous concurrents, frontières de sécurité

#### Slide 06 - Architecture logicielle & schéma de données
- **Layout**: Asymmetric split 5:7 — schéma de flux à gauche, extrait de schéma SQL à droite
- **Title**: Une façade unique, deux niveaux de bases SQLite
- **Core message**: `SupplyScoreService` orchestre le cœur mathématique, le graphe en mémoire et la persistance ; `MutationService` est le seul point d'écriture, garantissant un audit complet.
- **Content**:
  - `registry.sqlite` : registre global (nœuds, arcs, projets, configuration réseau)
  - `<client_id>.sqlite` par nœud : historique KPI, évaluations AHP, revues hebdomadaires — isolation stricte
  - `MutationService` (`supplyscore/services/mutations.py`) : diff → validation des plages physiques → journal d'audit → synchronisation du graphe en mémoire, en une seule transaction
  - Graphe en mémoire : `InMemoryGraphRepository` (networkx) pour la propagation temps réel

#### Slide 07 - Panorama fonctionnel : les 13 pages de l'application
- **Layout**: Matrix grid 4×4 incomplète (13 tuiles + 1 hero screenshot en fond de bandeau supérieur)
- **Title**: Un logiciel complet, pas une preuve de concept
- **Core message**: Chacune des 6 méthodes mathématiques présentées ensuite est déjà en production dans une interface Dash utilisée pour animer des serious games industriels.
- **Content**: grille des 13 pages (Projets, Onboarding, Hebdo, Questionnaire, Dashboard, Simulation, Édition, Pondération, Graphe, Rapport, Admin, Fiche nœud, Explication) — icône + nom + rôle en une ligne chacune

### Partie 2 — Six deep dives mathématiques

#### Slide 08 - Deep dive 1a : AHP — élicitation de l'urgence déclarée Ud
- **Layout**: Asymmetric split 6:6 — capture d'écran questionnaire à gauche, équations à droite
- **Title**: Comparer plutôt que noter : le processus AHP de Saaty
- **Core message**: Un curseur bipolaire de -8 à +8, converti sur l'échelle de Saaty, produit une matrice de comparaisons dont on extrait un vecteur de priorité et un ratio de cohérence — pas un chiffre d'urgence arbitraire.
- **Content**:
  - 4 critères comparés deux à deux : impact opérationnel, fenêtre temporelle, dépendances aval, récupérabilité
  - Vecteur de priorité w, ratio de cohérence CR = CI/RI, seuil CR < 0.10
  - Lissage EMA (ρ=0.3) pour amortir les pics de stress ponctuels
  - Code : `supplyscore/core/ahp.py` — `build_matrix`, `priority_vector`, `consistency_ratio`, `compute_ud`

#### Slide 09 - Deep dive 1b : AHP — exemple numérique complet
- **Layout**: Dense, table de matrice à gauche + déroulé de calcul à droite (montrer avant énoncer)
- **Title**: De la matrice de comparaisons au Ud lissé, pas à pas
- **Core message**: Sur un cas réel à 4 critères, la cohérence est excellente (CR=0.0054) et le Ud lissé final vaut 0.3655.
- **Content**: matrice A → normalisation par colonne → vecteur w → λmax=4.0145 → CI=0.0048 → CR=0.0054 → score pondéré 4.1481 → Ud_actuel=0.3935 → EMA avec Ud_t-1=0.30 → **Ud_t = 0.3655**

#### Slide 10 - Deep dive 2 : F-BWM — pondération floue des blocs Ur
- **Layout**: Asymmetric split 6:6 — capture pondération à gauche, optimisation à droite
- **Title**: 2n-3 comparaisons au lieu de n(n-1)/2 : la méthode Best-Worst floue
- **Core message**: Le coordinateur désigne seulement le meilleur et le pire critère ; une optimisation SLSQP sous contrainte trouve les poids flous optimaux, défuzzifiés par GMIR.
- **Content**:
  - Nombres flous triangulaires (TFN) sur échelle linguistique 1-7
  - Minimisation de l'indicateur de cohérence ξ*
  - Défuzzification GMIR : R(wⱼ) = (lⱼ+4mⱼ+uⱼ)/6
  - Repli gracieux sur poids uniformes si la convergence échoue
  - Code : `supplyscore/mcda/fbwm.py` — `resoudre_fbwm`

#### Slide 11 - Deep dive 3 : PROMETHEE II — classement du réseau par surclassement
- **Layout**: Asymmetric split 6:6 — équations + exemple 3 nœuds à droite, principe à gauche
- **Title**: Comparer par paires plutôt que compenser
- **Core message**: Un score catastrophique sur un critère ne peut pas être compensé par un excellent score ailleurs — chaque paire de nœuds est comparée critère par critère, puis agrégée en flux net φ.
- **Content**:
  - Fonction de préférence par défaut : Type V linéaire avec indifférence (q=0.05, p=0.30)
  - φ⁺(a), φ⁻(a), flux net φ(a) = φ⁺(a) - φ⁻(a)
  - Valeur métier normalisée : BV = (φ+1)/2
  - Exemple 3 nœuds → classement A (0.60) > B (0.50) > C (0.40)
  - Code : `supplyscore/mcda/promethee.py` — `PrometheeII`

#### Slide 12 - Deep dive 4 : Monte Carlo — simulation stochastique des délais
- **Layout**: Asymmetric split 5:7 — capture simulation à gauche, distributions à droite
- **Title**: Le maximum de lois lognormales n'est pas lognormal : simuler plutôt qu'approximer
- **Core message**: 10 000 tirages en ordre topologique estiment directement la probabilité de dépassement de délai, sous un budget mémoire strict N×n ≤ 5×10⁷.
- **Content**:
  - Lois supportées : lognormale (moments), normale (tronquée à 0), triangulaire
  - Récurrence : Sᵢ = max(Cⱼ, j∈Pred(i)), Cᵢ = Sᵢ + Lᵢ
  - Estimateur : u_time = P(Cᵢ > dᵢ), intervalle de confiance à 95%
  - Code : `supplyscore/mc/lead_time.py` — `SimulateurLeadTime`

#### Slide 13 - Deep dive 5a : Moteur de propagation sur le DAG
- **Layout**: Center-radiating — DAG à 3 niveaux au centre, équations en marge
- **Title**: L'urgence descend, le risque remonte
- **Core message**: Ud se propage du client final vers les fournisseurs (produit qui fuit, facteur γ) ; Ur remonte des fournisseurs vers les clients (facteur β) — deux directions, une seule formulation "leaky product" bornée sur [0,1].
- **Content**:
  - Ud descendant : formule produit avec γᵢₖ, borné et monotone
  - Ur ascendant : formule produit avec βⱼᵢ
  - Règles de statut : `DONE` → Ur local = 0 mais Ud propage toujours ; `ABANDONED` → Ur local = 1
  - Arcs `BACKUP` : purement documentaires, aucune propagation
  - Code : `supplyscore/graph/propagation.py` — `PropagationEngine`

#### Slide 14 - Deep dive 5b : Propagation — exemple numérique
- **Layout**: Breathing — un seul diagramme DAG à 3 nœuds annoté avec les valeurs à chaque étape
- **Title**: Trois nœuds, deux vagues de calcul
- **Core message**: Un nœud `DONE` en amont continue de transmettre son Ud (0.50) mais plus son Ur (forcé à 0) — la structure demande survit, le risque physique s'éteint.
- **Content**: Nœud 3 (matières premières, DONE) → Nœud 2 (sous-ensemble) → Nœud 1 (assemblage final) ; Ud: 0.80→0.804→0.8216 ; Ur: 0.0→0.40→0.28

#### Slide 15 - Deep dive 6a : Moteur d'adéquation asymétrique
- **Layout**: Asymmetric split 6:6 — courbes de pénalité à droite
- **Title**: Sous-déclarer coûte plus cher que paniquer
- **Core message**: Inspiré de la théorie des perspectives de Kahneman-Tversky, le moteur pénalise le risque caché (λ_under=2.25) 2.25 fois plus fort que la fausse urgence (λ_over=1.0).
- **Content**:
  - Fausse urgence F = [Ud-Ur]₊, risque caché H = [Ur-Ud]₊
  - Pénalité = λ_under·H^α + λ_over·F^α, avec α=0.88 (courbure psychophysique)
  - Score d'adéquation A ∈ [0,100] via mise à l'échelle exponentielle
  - Code : `supplyscore/core/adequation.py` — `AdequationEngine`

#### Slide 16 - Deep dive 6b : Panique vs risque caché — un même écart, deux scores très différents
- **Layout**: Breathing — deux courbes/silhouettes côte à côte, un seul message fort
- **Title**: Même distance, verdicts opposés
- **Core message**: Pour un écart identique de 0.5 entre Ud et Ur, la fausse urgence obtient un score d'adéquation de 53%, le risque caché seulement 21% — la même erreur absolue n'est pas jugée pareil.
- **Content**: Cas A (Ud=0.8, Ur=0.3, panique) → A=53.14% ; Cas B (Ud=0.3, Ur=0.8, silence) → A=21.13%

### Partie 3 — Huit démonstrations opérationnelles

#### Slide 17 - Le cycle de revue hebdomadaire
- **Layout**: Top-bottom split — capture pleine page en haut, 4 volets en bandeau bas
- **Title**: Quatre volets, une transaction atomique
- **Core message**: Chaque nœud revit sa semaine en 4 étapes signées par l'opérateur : AHP pré-rempli, diff KPI, avancement des jalons, événements — tout ou rien, jamais de revue partielle ou anonyme.
- **Content**: Volet 1 (AHP, bouton "Confirmer à l'identique") · Volet 2 (diff KPI S-1 vs nouveau) · Volet 3 (avancement théorique p_th vs déclaré) · Volet 4 (événements + décision signée)

#### Slide 18 - Le moteur d'événements calibrés
- **Layout**: Top-bottom split
- **Title**: 14 événements, 3 opérateurs mathématiques, zéro calcul manuel
- **Core message**: Un planificateur déclare un événement du monde réel (grève, panne, rupture) ; le moteur traduit automatiquement son impact via mise à jour bayésienne, EMA ou mise à jour directe.
- **Content**: Beta-Bernoulli (probabilités de panne) · EMA (OEE, délais) · Direct (faits signés) · Aperçu avant confirmation, réversion complète

#### Slide 19 - Scénarios & simulations what-if
- **Layout**: Top-bottom split
- **Title**: Stress-tester la chaîne sans jamais toucher aux données réelles
- **Core message**: Un choc simulé (Ur local → 1.0) recalcule instantanément la propagation ascendante en mémoire, sans écrire dans les bases SQLite ni altérer l'historique.
- **Content**: Scénarios nommés (table `scenarios`) · ΔUr calculé pour chaque nœud · sandboxing total en mémoire

#### Slide 20 - Contrôles admin, durcissement SQLite & sauvegardes
- **Layout**: Top-bottom split
- **Title**: WAL, intégrité vérifiée, 20 sauvegardes en rotation
- **Core message**: Avant toute sauvegarde, `PRAGMA integrity_check` doit passer ; la copie native `sqlite3.backup` garantit une transaction cohérente sans verrouiller l'application.
- **Content**: `PRAGMA journal_mode=WAL` · sauvegarde auto toutes les 24h · rétention de 20 archives zip · migrations versionnées via `PRAGMA user_version`

#### Slide 21 - Explicabilité (XAI) : pourquoi ce score ?
- **Layout**: Top-bottom split
- **Title**: Chaque score se décompose jusqu'au dernier pourcent
- **Core message**: La contribution exacte de chaque critère AHP et de chaque bloc KPI est affichée, sans reliquat mathématique — panique ou silence, le coordinateur voit pourquoi.
- **Content**: κⱼ = wⱼ(sⱼ-1)/8 pour Ud · ℓₘ = -ωₘln(1-uₘ) pour Ur · séparation risque local / risque propagé

#### Slide 22 - L'indice de criticité systématique du réseau
- **Layout**: Top-bottom split
- **Title**: Quel fournisseur ferait le plus mal s'il tombait ?
- **Core message**: `ServiceCriticite` simule une défaillance totale sur chaque nœud actif et mesure l'impact propagé jusqu'au client final — un tri-classement objectif des points de fragilité.
- **Content**: Tri par `delta_ur_final` puis `delta_ur_max` · exemple : nœud 2 en panne → impact final +0.42

#### Slide 23 - Calibration & validation prédictive
- **Layout**: Top-bottom split
- **Title**: Le risque caché prédit-il vraiment les incidents futurs ?
- **Core message**: `CalibrationService` compare le risque caché historique à une fenêtre d'observation de 4 semaines et construit une matrice de confusion (précision, rappel, F1) — la preuve statistique que le modèle n'est pas arbitraire.
- **Content**: 3 critères d'issue négative (jalon manqué, abandon, événement critique) · seuil de significativité à 30 observations

#### Slide 24 - Exports & reporting
- **Layout**: Top-bottom split
- **Title**: Un classeur de 12 feuilles pour l'audit complet
- **Core message**: `ExportService` compile registre global et bases locales en un classeur Excel structuré, fuseaux horaires convertis — prêt pour l'analyse statistique post-session.
- **Content**: nœuds, arcs, jalons, historique d'urgence, évaluations, revues, KPIs, événements, décisions, 2 journaux d'audit

### Partie 4 — Synthèse & perspectives

#### Slide 25 - Vers un score unifié d'urgence US(t)
- **Layout**: Dense — équation centrale + 5 coefficients annotés
- **Title**: Un seul indicateur pour tout faire converger
- **Core message**: US(t) additionne l'adéquation, la volatilité Monte Carlo et les métadonnées opérationnelles, puis soustrait les facteurs de crise et de capacité macro-logistique — sous contrainte ωA+ωV+ωO=1.
- **Content**: équation complète + rôle de chaque terme (A, V_mc, O_meta, C_crise, L_macro)

#### Slide 26 - Perspectives : détection de patterns & agents de décision autonomes
- **Layout**: Asymmetric split 6:6 — deux boucles (détection / agent)
- **Title**: De la surveillance passive à la recommandation active
- **Core message**: Des réseaux temporels détecteraient les "coordinateurs paniqués" et "goulots silencieux" ; un agent formulé comme un processus de décision markovien (MDP) évaluerait l'espérance de A(t+1) pour chaque action corrective.
- **Content**: Δ_panic ≥ 0.50 sans retard réel · Δ_silent ≥ 0.50 avec glissement de jalon actif · MDP : états, actions, récompense R(s,a) = ΣAᵢ(s) - c(a)

#### Slide 27 - Rétrospective : trois horloges, un cycle hebdomadaire, une simulation what-if
- **Layout**: Breathing — 3 pictogrammes d'horloge, texte minimal
- **Title**: Le temps comme variable de première classe
- **Core message**: `SystemClock`, `FixedClock`, `GameClock` découplent proprement production, tests déterministes et serious game — la même mécanique qui rend `simulate_shock` possible sans jamais écrire en base.
- **Content**: `supplyscore/core/clock.py` · `weekly.py` (couverture AHP, statuts à jour/en retard/manquant) · `simulate_shock` (sandbox mémoire)

#### Slide 28 - Conclusion & remerciements
- **Closing impact**: Restituer la thèse en une phrase mémorable + appel à la discussion — pas un simple "merci" générique. Composition : citation centrale + contact, sur fond quasi blanc, une ligne d'accent.
- **Layout**: Single column centered
- **Content**: "SupplyScore ne remplace pas le jugement humain — il le rend mesurable, comparable, et digne de confiance." Merci — questions et discussion.

### Annexe — Ancrage bibliographique

#### Slide 29 (Annexe A) - Références citées
- **Layout**: Matrix grid 3 colonnes (18 références groupées par thème) + note de bas de page
- **Title**: Références citées : ancrage dans la revue de littérature BST
- **Core message**: Chaque formule et chaque affirmation forte présentée dans ce deck est traçable à une référence de la revue de littérature du document BST DISCO (John Hoarau, 2026) et de sa bibliographie de 161 entrées.
- **Content**: 3 colonnes thématiques (biais cognitifs & triage ; méthodes multicritères MCDM ; réseaux bayésiens & jumeau numérique), 6-7 références chacune, auteur/année en gras + titre court/revue en note. Bas de page : le score unifié US(t) et le cadre d'adéquation cognitive sont formalisés dans le document BST DISCO lui-même (auto-citation), section Opérations.
- **Provenance**: Citations extraites de `docs/BST_DISCO_JH_2026/Sections/{2.Problem,3.SoTA,4.Operations}.tex` et `Utilities/Bibliography.bib`. Chaque citation inline ajoutée sur les slides P02, P03, P05, P06, P08, P09, P10, P11, P12, P13, P14, P15, P16, P18, P19, P21, P25, P26 reprend ces mêmes références (texte en bas de page, 13px, `#9AA5AC`).

---

## X. Speaker Notes Requirements

Un fichier de notes par page dans `notes/`, nommé comme le SVG (ex. `01_couverture.md`). Les notes s'appuient sur le "Speaker Script" et les "Technical Notes" du script source (`docs/Presentation script.md`), traduits et adaptés en français, avec repères de timing pour une session de 3 heures (≈6-7 minutes par page en moyenne, plus long sur les deep dives denses).

---

## XI. Technical Constraints Reminder

Voir `references/shared-standards.md` — viewBox `0 0 1280 720`, pas de `foreignObject`/`rgba()`/`mask`/`<style>`, texte en Unicode brut, `clipPath` réservé aux `<image>`, `<g opacity>` interdit (opacité par élément).
