# Documentation SupplyScore

La documentation s'adresse à trois publics : l'animateur, qui prépare et pilote les
sessions de jeu ; l'exploitant, qui installe le poste et garde les données saines ;
le développeur, qui modifie le code ou le modèle. La table ci-dessous indique par où
commencer selon le besoin.

| Document | Public | Contenu |
|---|---|---|
| [manuel_utilisateur.md](manuel_utilisateur.md) | animateur | démarrage rapide, concepts, animation d'un serious game, guide illustré des pages, FAQ |
| [exploitation.md](exploitation.md) | exploitant | emplacement des données, sauvegarde, restauration, journaux, migration de schéma, CI locale |
| [modele_mathematique.md](modele_mathematique.md) | développeur | spécification formelle des scores Ud, Ur et A, propagation, événements, cas de référence |
| [reference_cli.md](reference_cli.md) | exploitant | la commande supplyscore, résolution des répertoires, lanceurs Windows, scripts, variables d'environnement |
| [reference_donnees.md](reference_donnees.md) | exploitant | architecture des données, exports, format de sauvegarde, schéma SQLite, journal d'audit |
| [guide_developpeur.md](guide_developpeur.md) | développeur | organisation du code et correspondance entre les formules du modèle et leur implémentation |
| [presentation/](presentation/) | animateur | déroulés de démonstration 6 et 20 minutes, captures d'écran, artefacts du scénario AERIS |
| [benchmarks/](benchmarks/) | développeur | rapports de performance archivés par les bancs de la CI locale |

Les liens internes entre documents sont relatifs : la documentation se lit aussi bien
dans le dépôt que dans une copie locale du dossier `docs/`.
