# 01_couverture

Bienvenue à cette soutenance consacrée à SupplyScore, un framework mathématique et logiciel qui réconcilie la perception subjective de l'urgence avec la réalité physique des chaînes logistiques. Dans les environnements industriels sous pression, la réaction par défaut face à un retard est souvent de déclarer tout comme critique, ce qui sature les capacités de transport premium et épuise la vigilance des équipes. SupplyScore propose la première couche mathématique qui compare, quantifie et distingue la fausse urgence du risque caché, plutôt que de simplement afficher des indicateurs. Nous allons parcourir en trois heures les fondations du modèle, six démonstrations mathématiques approfondies, huit fonctionnalités opérationnelles et les perspectives du projet.

---

# 02_contexte

Avant d'entrer dans les mathématiques, je me présente brièvement. Je suis John Hoarau, ingénieur industriel et data scientist supply chain, avec un parcours centré sur la recherche opérationnelle, la simulation stochastique et les facteurs humains en logistique. Ce projet est né d'un constat répété dans l'automobile et l'aéronautique : les systèmes de planification (MRP) sont mathématiquement optimaux mais opérationnellement fragiles, car ils ignorent l'état cognitif des personnes qui les pilotent. L'écran d'onboarding que vous voyez illustre déjà cette rencontre entre rigueur mathématique et réalité de terrain, avec un assistant en quatre étapes qui capture l'identité du nœud, son cahier des charges, ses indicateurs physiques initiaux, puis sa première évaluation AHP.

---

# 03_problematique

Voici le cœur du problème que nous adressons. D'un côté, la strate subjective : la perception humaine, sujette aux biais émotionnels, à l'optimisation locale et à la panique. De l'autre, la strate objective : les niveaux de stock, les délais de transit et la capacité physique du réseau. Quand la sur-déclaration devient systématique, le transport premium sature, les équipes s'épuisent, et les signaux vraiment critiques finissent par être ignorés. La contribution centrale de SupplyScore est de construire, entre ces deux strates, une couche de traduction mathématique capable de détecter à la fois la fausse urgence, c'est-à-dire la panique injustifiée, et le risque caché, c'est-à-dire le danger silencieux et sous-déclaré.

---

# 04_agenda

Pour naviguer ces trois heures, voici les quatre mouvements de la présentation. D'abord les fondations : les hypothèses de modélisation, l'architecture logicielle et un panorama des treize pages de l'application. Ensuite, six deep dives mathématiques qui couvrent l'AHP, la méthode F-BWM, PROMETHEE II, la simulation Monte Carlo, la propagation sur le graphe et le moteur d'adéquation asymétrique. Puis huit démonstrations opérationnelles qui montrent le logiciel en fonctionnement réel, du cycle hebdomadaire jusqu'aux exports. Nous terminerons par une synthèse autour d'un score unifié proposé, les perspectives d'agents de décision autonomes, et une rétrospective sur la gestion du temps dans le système.

---

# 05_hypotheses

Pour qu'un système aussi dense reste cohérent de bout en bout, il repose sur neuf hypothèses assumées et vérifiables dans le code. Le réseau est modélisé comme un graphe acyclique dirigé, ce qui garantit un tri topologique linéaire et interdit les boucles de rétroaction. Les revues suivent un cycle hebdomadaire ISO strict, ce qui simplifie toutes les comparaisons historiques. L'urgence déclarée s'amortit en descendant vers les fournisseurs, tandis que le risque réel s'amplifie en remontant vers les clients, chacun scalé par un facteur de lien dédié. Les six blocs de KPI sont supposés indépendants pour permettre une agrégation probabiliste de type Noisy-OR, les statuts de tâche pilotent des règles explicites, et surtout, la perte cognitive est volontairement asymétrique : sous-déclarer un risque coûte deux fois plus cher que paniquer.

---

# 06_architecture

Voyons maintenant l'architecture logicielle qui porte ce modèle. Une façade unique, SupplyScoreService, orchestre le cœur mathématique, le graphe en mémoire et la persistance. Pour garantir l'isolation et la scalabilité, le système repose sur une architecture multi-tenant : un registre global, registry.sqlite, stocke la topologie et les métadonnées, tandis que chaque nœud dispose de sa propre base privée pour son historique KPI et ses évaluations. Toutes les écritures passent obligatoirement par MutationService, qui effectue quatre actions dans une seule transaction : comparer les changements, valider les plages physiques, journaliser l'audit, puis synchroniser le graphe en mémoire. Cette discipline garantit qu'aucune donnée ne peut être modifiée sans laisser une trace vérifiable.

---

# 07_panorama

Avant de plonger dans les mathématiques, il est important de montrer que chacune des méthodes que nous allons présenter est déjà déployée dans un vrai logiciel, pas seulement dans un article de recherche. Voici les treize pages de l'application, de la création de projet jusqu'à la page d'explication détaillée d'un score. Au centre de cet écosystème se trouve le dashboard, qui affiche le graphe coloré par adéquation, les priorités calculées par PROMETHEE II et l'évolution temporelle des scores. Cette interface Dash est celle que des animateurs utilisent aujourd'hui pour piloter des serious games industriels.

---

# 08_ahp_concept

Notre premier deep dive porte sur l'élicitation de l'urgence déclarée, Ud. Plutôt que de laisser un utilisateur saisir un chiffre arbitraire, nous appliquons le processus AHP de Saaty : quatre critères sont comparés deux à deux via un curseur bipolaire, converti sur l'échelle de Saaty. Ces comparaisons forment une matrice réciproque positive, dont on extrait un vecteur de priorité par normalisation des colonnes, puis on calcule un ratio de cohérence pour détecter des jugements incohérents. Un lissage par moyenne mobile exponentielle, avec un facteur de 0,3, empêche enfin qu'un pic de stress ponctuel ne déstabilise tout le réseau en aval.

---

# 09_ahp_exemple

Prenons un cas réel pour voir ce calcul se dérouler. À partir d'une matrice de comparaisons à quatre critères, la normalisation des colonnes puis la moyenne des lignes donnent un vecteur de priorité. Le calcul de cohérence donne un ratio de 0,0054, largement sous le seuil de 0,10 : les jugements humains sont exploitables tels quels. En appliquant ces poids aux scores locaux déclarés, on obtient un Ud instantané de 0,3935, que le lissage exponentiel avec la valeur précédente de 0,30 ramène finalement à 0,3655.

---

# 10_fbwm

Passons maintenant à la pondération des six blocs qui composent l'urgence réelle, Ur. Plutôt que l'AHP, qui exigerait quinze comparaisons pour six critères, nous utilisons la méthode Best-Worst floue, qui n'en nécessite que neuf. Le coordinateur désigne simplement le critère le plus important et le moins important, puis compare chacun des deux à tous les autres via une échelle linguistique convertie en nombres flous triangulaires. Une optimisation sous contrainte résout les poids flous optimaux, ensuite défuzzifiés par la formule GMIR, avec un repli automatique sur des poids uniformes si l'optimisation ne converge pas.

---

# 11_promethee

Notre troisième deep dive concerne le classement des nœuds actifs par PROMETHEE II. Contrairement à une simple moyenne pondérée, qui laisserait un excellent score compenser un score catastrophique, PROMETHEE II compare chaque paire de nœuds critère par critère avant d'agréger. Avec la fonction de préférence linéaire par défaut, on calcule un flux positif et un flux négatif pour chaque nœud, dont la différence donne le flux net, normalisé ensuite en une valeur métier entre zéro et un. Sur notre exemple à trois nœuds, le nœud A domine largement sur le premier critère malgré un second critère faible, et cette réalité ressort clairement du classement final sans qu'aucune moyenne ne vienne la masquer.

---

# 12_montecarlo

Le quatrième deep dive nous fait entrer dans la simulation stochastique des délais. Le maximum de plusieurs distributions lognormales n'est pas lui-même lognormal, ce qui rend les approximations PERT classiques peu fiables : nous simulons donc directement, nœud par nœud, en tirant des lois lognormales, normales tronquées ou triangulaires selon le contexte. La simulation avance en ordre topologique sur le graphe, dix mille fois par défaut, et estime la probabilité de dépassement de délai comme la proportion de tirages où le nœud dépasse son échéance. Un budget mémoire strict, produit du nombre de tirages par le nombre de nœuds, protège le système contre les graphes trop larges.

---

# 13_propagation_concept

Voyons maintenant comment l'urgence se propage sur l'ensemble du réseau. L'urgence déclarée descend du client final vers les fournisseurs, amortie à chaque lien par un facteur gamma, tandis que le risque réel remonte des fournisseurs vers les clients, amplifié par un facteur bêta. Ces deux propagations suivent une même formulation en produit qui reste toujours bornée entre zéro et un. Les règles de statut s'appliquent avant toute propagation : un nœud terminé voit son risque local ramené à zéro mais continue de transmettre son urgence déclarée, tandis qu'un nœud abandonné propage un risque maximal à tout son aval.

---

# 14_propagation_exemple

Regardons ce mécanisme sur un cas concret à trois nœuds. Le nœud le plus en amont, marqué terminé, voit son risque réel tomber à zéro tout en continuant de transmettre son urgence déclarée de 0,50 vers le sous-ensemble. Cette urgence se propage ensuite jusqu'à l'assemblage final, atteignant 0,82 après les deux étapes de descente. En parallèle, le risque réel remonte depuis les fournisseurs actifs pour atteindre 0,28 chez le client final, illustrant bien la coexistence des deux vagues de calcul sur un même graphe.

---

# 15_adequation_concept

Notre sixième et dernier deep dive porte sur le moteur d'adéquation, qui compare directement Ud et Ur. Nous définissons la fausse urgence comme l'excès de Ud sur Ur, et le risque caché comme l'excès inverse. Notre position de gouvernance est claire : sous-déclarer un risque est bien plus dangereux que paniquer, car une équipe qui panique gaspille des ressources tandis qu'une équipe qui se tait rate la fenêtre pour éviter un arrêt de ligne. C'est pourquoi la pénalité applique un poids de 2,25 au risque caché contre seulement 1,0 à la fausse urgence, avec un exposant de 0,88 qui modélise la sensibilité décroissante aux erreurs extrêmes, avant une mise à l'échelle exponentielle vers un score entre zéro et cent.

---

# 16_adequation_comparaison

Pour rendre cette asymétrie tangible, comparons deux situations avec exactement le même écart absolu de 0,5 entre Ud et Ur. Dans le cas A, un coordinateur panique en déclarant 0,8 alors que la réalité n'est que de 0,3 : son score d'adéquation atteint tout de même 53%. Dans le cas B, un coordinateur reste silencieux en déclarant 0,3 alors que la réalité est de 0,8 : son score chute à seulement 21%. Le même écart produit donc des verdicts radicalement différents, ce qui valide concrètement le choix de conception asymétrique.

---

# 17_hebdo

Passons maintenant aux huit démonstrations opérationnelles, en commençant par le cycle de revue hebdomadaire. Chaque nœud revit sa semaine à travers quatre volets successifs, signés par l'opérateur : d'abord l'AHP, pré-rempli avec un bouton pour confirmer à l'identique si rien n'a changé, puis les KPIs avec un tableau de différences, ensuite l'avancement des jalons comparé à la progression théorique, et enfin les événements et la décision. L'ensemble est enregistré dans une seule transaction atomique, ce qui interdit toute revue partielle ou anonyme.

---

# 18_evenements

L'une des fonctionnalités les plus puissantes de SupplyScore est son moteur d'événements calibrés. Plutôt que de calculer manuellement l'impact d'une panne ou d'une grève, un planificateur déclare simplement l'événement parmi quatorze types, et le moteur traduit automatiquement son effet sur les KPIs via trois opérateurs mathématiques : des mises à jour bayésiennes pour les probabilités de panne, des moyennes mobiles exponentielles pour les variables continues, et des mises à jour directes pour les faits signés. L'opérateur peut prévisualiser l'impact avant de confirmer, et chaque événement reste réversible.

---

# 19_simulation

Voici maintenant les scénarios et simulations what-if. Un coordinateur peut charger un scénario nommé, sélectionner un nœud critique et simuler un choc, par exemple en forçant son risque local à 1,0. Le service recalcule instantanément la propagation ascendante en mémoire et affiche le delta de risque propagé à chaque nœud du réseau, sans jamais écrire dans les bases de données ni altérer l'historique. Cela permet de tester des plans de mitigation, comme l'activation d'un arc de secours, avant qu'une vraie crise ne survienne.

---

# 20_admin

La robustesse opérationnelle du logiciel repose sur un durcissement SQLite sérieux. Le mode d'écriture différée, WAL, garantit des commits atomiques même dans des dossiers synchronisés dans le cloud, et chaque sauvegarde commence par une vérification d'intégrité complète avant toute copie. La copie native de SQLite crée une image cohérente sans jamais verrouiller l'application, les sauvegardes automatiques tournent toutes les vingt-quatre heures avec une rétention de vingt archives, et les migrations de schéma sont versionnées de façon transactionnelle.

---

# 21_xai

La transparence est un pilier central de SupplyScore. Quand un score paraît bas, un coordinateur ne devrait jamais avoir à deviner pourquoi : la page d'explication décompose exactement la contribution de chaque critère AHP dans Ud, sans aucun reliquat mathématique. Du côté du risque réel, la décomposition Noisy-OR affiche la part exacte de chaque bloc de KPI, en séparant clairement le risque local du risque propagé depuis l'amont. Sur cet exemple, le bloc temps explique près de la moitié du risque, loin devant la capacité et le risque pur.

---

# 22_criticite

Voici maintenant l'indice de criticité systématique du réseau. Là où les simulations what-if testent des scénarios choisis manuellement, ServiceCriticite répond systématiquement à une question : quel fournisseur ferait le plus de dégâts s'il tombait en panne totale ? Le service simule cette défaillance sur chaque nœud actif, mesure l'impact propagé jusqu'au client final, puis trie les résultats pour prioriser les audits de résilience. Sur notre exemple, la défaillance simulée du nœud deux propage un impact de 0,42 jusqu'au client, ce qui en fait une priorité claire.

---

# 23_calibration

Un défi majeur des modèles prédictifs est de prouver leur fiabilité. CalibrationService compare le risque caché historique enregistré une semaine donnée aux issues négatives réellement observées dans les quatre semaines suivantes, qu'il s'agisse de jalons manqués, d'abandons ou d'événements critiques. En construisant une matrice de confusion sur ces observations, le service calcule précision, rappel et score F1, ce qui permet de démontrer statistiquement que les nœuds signalés à haut risque caché échouent effectivement plus souvent.

---

# 24_exports

Pour l'analyse post-session, ExportService compile l'ensemble du registre global et des bases locales en un classeur Excel structuré en douze feuilles distinctes, couvrant les nœuds, les arcs, les jalons, l'historique d'urgence, les évaluations, les revues, les KPIs, les événements, les décisions et deux journaux d'audit complets. Tous les horodatages sont automatiquement convertis dans le fuseau horaire local du coordinateur, ce qui permet de charger directement les données dans Excel ou dans pandas pour une revue statistique complète.

---

# 25_score_unifie

Après avoir couvert les six deep dives et les huit démonstrations, voyons comment ces éléments pourraient converger en un seul indicateur. Nous proposons un score d'urgence unifié qui additionne l'adéquation, la volatilité issue de la simulation Monte Carlo et les métadonnées opérationnelles, puis soustrait un facteur d'amortissement de crise et un indice de capacité macro-logistique, sous la contrainte que les trois premiers coefficients somment à un. Ce score unique combinerait ainsi le sentiment humain, le risque physique, la variance stochastique et la capacité macro-environnementale dans un seul chiffre lisible sur le tableau de bord principal.

---

# 26_perspectives

Regardons maintenant vers l'avenir du projet. Nous envisageons de transformer le système d'un outil de suivi passif vers un agent actif de détection et de recommandation. Des réseaux temporels pourraient automatiquement classifier des comportements, comme un coordinateur paniqué qui déclare une urgence élevée sans retard réel, ou un goulot silencieux où le risque reste systématiquement sous-déclaré. À plus long terme, un agent formulé comme un processus de décision markovien pourrait simuler en mémoire différentes actions correctives et recommander celle qui maximise l'adéquation attendue du réseau.

---

# 27_retrospective

Pour conclure sur le plan technique, revenons sur la gestion du temps dans SupplyScore. Le code découple proprement trois horloges : une horloge système pour la production réelle, une horloge figée pour les tests déterministes, et une horloge de jeu qui avance semaine par semaine pour les serious games. Le service hebdomadaire s'appuie sur cette horloge pour calculer la couverture des évaluations AHP et signaler chaque nœud comme à jour, en retard ou manquant, tandis que simulate_shock permet de tester la résilience du réseau à tout moment sans jamais écrire en base.

---

# 28_conclusion

SupplyScore ne remplace pas le jugement humain : il le rend mesurable, comparable et digne de confiance. En unifiant l'AHP, la méthode Best-Worst floue, PROMETHEE II, la simulation Monte Carlo, la propagation sur graphe et la théorie des perspectives dans un seul moteur cohérent, ce travail transforme un signal d'alarme souvent bruité en une décision quantifiée et auditable. Je vous remercie de votre attention, et je suis maintenant à votre disposition pour vos questions.

---

# 29_references

Cette annexe rassemble, pour mémoire, les références citées tout au long de la présentation : les biais cognitifs et la littérature sur le triage, les méthodes multicritères qui fondent l'AHP, la méthode Best-Worst et PROMETHEE II, ainsi que les réseaux bayésiens et la littérature sur le jumeau numérique. Chacune ancre une formule ou une affirmation précise montrée plus tôt, et le score unifié proposé provient directement de mes propres travaux de recherche doctorale. Je reste bien sûr disponible pour détailler n'importe laquelle de ces sources durant les questions.
