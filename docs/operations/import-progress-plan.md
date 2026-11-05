# Plan — visibilité des fusions d’import

Statut : implémentation locale en cours de validation ; mesure de charge représentative à effectuer. Le run staging et les trois PR en brouillon restent hors de cette intervention.

## Problème et constats vérifiés

Le défaut se situe dans le contrat de suivi : l’API répond seulement `pending` tant que django-q n’a pas enregistré le résultat. Elle masque donc la file d’attente, l’étape SQL courante et l’attente éventuelle d’un verrou.

Sources lues après `git fetch origin`, le 5 novembre 2026 :

| Dépôt | Référence examinée | Responsabilité |
| --- | --- | --- |
| grow-the-music-tree-api | origin/develop, c05f5522 | Fusion, transaction, verrou, statut et historique |
| infrastructure | origin/main, 6aad9278 | Upload, polling, journal, métriques et Discord |
| the-music-tree-pipelines | origin/develop, f84d89eb | Production des exports ; aucun changement nécessaire prévu |

Dans grow, `grow/bulk_import/run_steps.py` chronomètre déjà chaque étape et journalise son nombre de lignes **après** exécution. Les fusions songs et artists passent par ce helper, dans une transaction unique. `ImportRun.step_timings` conserve les durées des imports enregistrés réussis. Le run temporaire est supprimé dans le `finally`, même en cas d’échec.

Le verrou de session dans `merge_lock.py` et `claim_lost_merge` permettent déjà de reprendre une fusion perdue après disparition du worker. Le suivi devra préserver cette logique et distinguer ses tentatives.

Dans infrastructure, `music-tree-pipelines/scripts/run-music-tree-pipelines.sh` interroge le statut toutes les 15 secondes et attend au maximum 16 200 secondes (4 h 30 ; 30 minutes pour la carte). Le worker grow a un timeout de 14 400 secondes (4 h). Les durées SQL sont déjà récupérées à la fin et transmises à `record_timing`. Le commentaire du runner estime une fusion complète à environ 95 minutes ; ce n’est pas une mesure du run staging actuel. Le heartbeat du poller concerne la demande de pipeline, pas la fusion SQL.

## Décision d’architecture

Conserver la transaction métier et les requêtes ensemblistes. Découper en lots uniquement pour obtenir un pourcentage augmenterait le risque de données partiellement publiées et modifierait les performances avant de les avoir mesurées.

Publier des étapes réelles : préparation, comparaison, écritures songs, crédits artistes, suppressions, playlists, projection de recherche, compteurs, commit et nettoyage, dans leur ordre effectif. Ces groupes résument les labels SQL existants ; ils ne créent pas de nouvelles opérations. La fusion des fiches artists reste un import distinct, après songs.

Afficher l’étape, son âge, les étapes terminées et leurs durées. Un `rowcount` est une mesure propre à une instruction, parfois indisponible (`-1`) ; plusieurs instructions touchent les mêmes chansons ou des relations. Aucun pourcentage de chansons fusionnées ni ETA dans la première version. Le nombre d’étapes terminées n’est pas un pourcentage de temps écoulé.

## Lot 1 — grow : contrat de progression fiable

1. Ajouter un enregistrement de suivi par tentative, indépendant des tables temporaires et conservé après leur nettoyage : run/task, kind, mode, attempt, état, dates de mise en file/début/fin, étape courante, début d’étape, dernier événement de progression, heartbeat, étapes terminées et erreur bornée. Conserver les résultats finaux et les durées, y compris pour les imports admin non enregistrés dans `ImportRun`. Prévoir une rétention de 30 jours pour ce suivi technique. Réutiliser `ImportRun.step_timings` pour l’historique métier des succès.
2. Créer le suivi avant l’enqueue. Donner une identité à chaque tentative sous le verrou existant ; empêcher une ancienne tentative ou son heartbeat d’écraser le suivi d’une nouvelle. Définir explicitement `queued`, `running`, `committing`, `cleaning_up`, `succeeded`, `failed` et `interrupted`. Un échec de nettoyage après commit doit signaler que les données ont été appliquées, sans déclencher leur réimport automatique.
3. Étendre `run_steps` pour publier début, fin, durée et lignes de chaque instruction avec run, kind, mode et attempt dans les logs. Instrumenter aussi les opérations autour du helper : validations, compte final, commit, invalidation et nettoyage. Ne déclarer les données appliquées qu’après sortie réussie de `transaction.atomic()`.
4. Écrire le suivi via une connexion PostgreSQL dédiée en autocommit, hors transaction métier. Un petit reporter possède cette connexion et sérialise événements et heartbeat toutes les 30 secondes. Il ne modifie jamais les lignes métier ni la ligne `BulkImportRun` verrouillée/utilisée par la fusion. Garder les écritures d’événements ordonnées et bornées ; joindre le reporter avant la clôture de tentative. Des tests PostgreSQL devront prouver visibilité et absence d’auto-blocage.
5. Définir séparément `lastProgressAt` et `heartbeatAt` : un worker vivant peut attendre indéfiniment un verrou. En cas de panne du suivi après démarrage, journaliser l’erreur et exposer l’observabilité comme périmée ; ne pas annuler une transaction métier saine pour une perte de télémétrie. Les erreurs de configuration du reporter doivent être détectées avant le démarrage de la fusion.
6. Associer le backend SQL à la tentative (PID et identité de session pour éviter la réutilisation d’un PID). Ajouter au statut un diagnostic borné de `pg_stat_activity` et `pg_blocking_pids` : présence de session, état, âge de requête, type d’attente et nombre de bloqueurs. Vérifier les droits du rôle applicatif ; une information inaccessible est `unavailable`, jamais « worker mort ». Ne retourner ni texte SQL ni secrets. Ce diagnostic indique activité/attente, pas le pourcentage interne d’un INSERT/UPDATE.
7. Étendre la réponse existante de `…/import/<taskId>/status/` avec un objet `progress` optionnel, en conservant `pending|success|failed`, `result` et `error`. Appliquer les permissions et le filtrage par kind/owner adaptés ; vérifier les anciens statuts et les accès admin/pipeline/public. Ne pas élargir l’accès aux données de diagnostic.
8. Intégrer les reprises existantes : disparition réelle du verrou/session → tentative interrompue et reprise selon `claim_lost_merge`. Un heartbeat ancien seul n’autorise aucune reprise. Après SIGKILL, le prochain statut doit réconcilier la tentative avec le résultat django-q, le verrou et la présence du run. Couvrir la fenêtre entre suppression du run et enregistrement du résultat django-q.

Fichiers principaux : `grow/bulk_import/`, `grow/track/bulk_import/merge.py`, `grow/artist/bulk_import/merge.py`, `grow/region_map/bulk_import/merge.py`, `grow/view/viewset/mixin/BulkImportRunMixin.py`, migrations et tests associés. Faire participer region_map au contrat commun sans lui inventer des étapes SQL. Mirrorer toute nouvelle configuration dans `grow/settings.py` et `tests/settings.py`.

## Lot 2 — infrastructure : rendre le suivi exploitable

1. Garder le polling HTTP à 15 secondes. Journaliser tout changement d’étape/tentative immédiatement, puis un état toutes les 60 secondes : environnement, run, tâche, kind, mode, étape, durée, heartbeat et attente SQL. Exemple : `staging run=75 attempt=1 songs/full step=insert_songs elapsed=17m heartbeat_age=8s wait=IO`.
2. Distinguer file d’attente, travail SQL, verrou, reporter périmé et API injoignable. Une même étape longue produit un avertissement, pas une conclusion de blocage. Alerter après trois heartbeats manqués (90 secondes), avec déduplication et notification de rétablissement ; ne pas tuer la fusion sur ce seul signal.
3. Conserver les délais globaux existants dans ce lot. À leur expiration, signaler explicitement que l’attente client est terminée et que la fusion serveur peut continuer ; inclure run/task, dernière étape connue et dernière erreur HTTP. Ne pas lancer automatiquement une nouvelle fusion. Documenter la vérification du verrou serveur avant toute relance ; le verrou global du pipeline n’arrête pas une fusion déjà envoyée à grow.
4. Réutiliser `record_timing` et les métriques existantes. Ajouter kind, mode et tentative aux mesures ; séparer durée de file, exécution SQL et nettoyage. Conserver les étapes déjà accomplies lors d’un échec. Mettre dans Discord la durée totale et les trois étapes les plus longues, avec liens/identifiants de diagnostic ; garder le détail dans le journal et l’historique.
5. Ajouter une alerte de lenteur seulement après constitution d’une référence : au moins cinq succès comparables, même environnement/kind/mode et volume du même ordre. Seuil proposé : maximum de 2× la médiane et médiane + 10 minutes. Sans référence, afficher « référence insuffisante ». Ne pas ajouter de requête d’historique coûteuse à chaque poll.
6. Documenter les paramètres et les rendre explicites dans Ansible si de nouveaux réglages sont introduits. Les valeurs invalides doivent échouer au démarrage. Conserver la compatibilité avec une API ancienne : `pending` sans `progress` est affiché comme suivi indisponible et reste borné par le timeout existant.

Fichiers principaux : `music-tree-pipelines/scripts/run-music-tree-pipelines.sh`, éventuellement `grow-api.sh`, rôle `ansible/roles/music_tree_pipelines/`, documentation et tests du runner. Aucun changement des transformations ou exports dans the-music-tree-pipelines.

## Validation et critères d’acceptation

- PostgreSQL, avec connexions distinctes : le début d’une étape est lisible pendant une instruction lente et avant commit ; heartbeat visible ; rollback métier intégral avec trace d’échec conservée ; aucune écriture de suivi bloquée par les verrous métier.
- Simuler un verrou SQL : le statut indique les bloqueurs, le heartbeat continue et aucune reprise n’est déclenchée. Simuler SIGKILL et redémarrage : nouvelle tentative distincte, pas de double fusion ni de heartbeat ancien réactivant une tentative terminée.
- Tester succès, échec SQL, échec de commit, échec de nettoyage après commit, indisponibilité du reporter, API inaccessible, attente en file, tâche inconnue, timeout client et fenêtre avant persistance du résultat django-q.
- Vérifier les permissions, le camelCase HTTP, la compatibilité du poller ancien et l’absence de SQL brut dans les réponses. Garder les tests SQLite existants ; réserver les garanties transactionnelles au marqueur `postgres`.
- Tester le runner avec réponses HTTP contrôlées et horloge simulée : changement d’étape, journal toutes les 60 secondes, ancien contrat, seuil de heartbeat, reprise, déduplication et timeout n’annonçant pas l’arrêt serveur.
- Vérifier en environnement de test un import full de volume représentatif (~32 M de songs) et un delta. Comparer à export, matériel et charge comparables ; viser un surcoût inférieur à 2 %, avec répétition si le bruit de mesure empêche de conclure. Observer la fraîcheur des événements, les connexions et les écritures ajoutées. Aucun test volumineux concurrent avec le run staging actuel.
- grow : Ruff check/format, mypy avec la configuration documentée, pytest avec couverture, migration check et tests PostgreSQL ciblés. Infrastructure : tests du runner, `scripts/lint.sh`, puis `pre-commit run --all-files`. Mettre à jour les changelogs et la documentation du contrat lors de l’implémentation.

## Découpage et estimation

Deux PR dédiées, séparées des trois brouillons actuels : grow pour le contrat et les garanties transactionnelles ; infrastructure pour l’affichage, les alertes et les tests. L’extension additive permet de préparer les deux indépendamment. Aucune release, fusion de PR ou modification de production n’est autorisée par ce plan.

Estimation indicative : 2–3 jours pour grow (cycle de vie, reporter et concurrence), 1–2 jours pour infrastructure et les tests d’intégration, puis 0,5–1 jour d’analyse sur un essai représentatif, hors temps machine. Total : 3,5–6 jours. La référence historique nécessaire aux alertes de lenteur se constitue ensuite au fil des runs.

Une solution minimale limitée aux logs avant/après chaque SQL coûterait environ une demi-journée et améliorerait le journal worker, mais laisserait le poller aveugle et ne distinguerait toujours pas worker perdu et attente de verrou. Elle ne couvre donc pas le besoin exprimé. Une optimisation SQL ou un découpage en lots sera une décision ultérieure, fondée sur les étapes effectivement coûteuses.

Le statut actuel du run staging n’a pas été revérifié dans ce travail de planification. Ce plan ne peut pas instrumenter rétroactivement une fusion déjà en cours.
