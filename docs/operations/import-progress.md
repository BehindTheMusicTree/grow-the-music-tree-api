# Suivi des fusions d’import

Les fusions songs, artists et region_map conservent une transaction métier unique.
Le suivi technique est indépendant des tables de staging et des résultats django-q.

## Contrat HTTP

Les endpoints existants `…/import/<taskId>/status/` conservent `status`
(`pending`, `success`, `failed`), `result` et `error`. Pour les appels admin et
pipeline, un objet `progress` optionnel décrit la dernière tentative du bon kind,
pour les données canoniques. Les autres lecteurs conservent le statut historique,
sans diagnostic ni déclenchement de reprise.

Champs de `progress` :

- `runId`, `taskId`, `kind`, `mode`, `attempt` : identité de la tentative.
- `state` : `queued`, `running`, `committing`, `cleaning_up`, `succeeded`, `failed`
  ou `interrupted`.
- `queuedAt`, `startedAt`, `finishedAt` : dates UTC, null si non atteintes.
- `step`, `stepStartedAt`, `lastProgressAt` : instruction ou opération courante,
  son début et le dernier changement de progression.
- `heartbeatAt` : dernier événement ou heartbeat du reporter, toutes les 30 secondes
  pendant une instruction longue. `observabilityStale` devient vrai après 90 secondes
  sans heartbeat. Cela ne prouve pas la mort du worker.
- `completedSteps` : étapes terminées, avec `label`, `ms`, `rowcount`. Une valeur
  `rowcount` nulle ou négative signifie qu’aucun nombre de lignes n’est disponible.
  Plusieurs étapes peuvent toucher les mêmes lignes. Il n’y a ni pourcentage ni ETA.
- `dataApplied` : vrai après commit confirmé. Une erreur de nettoyage peut donc
  produire `status=failed` et `dataApplied=true` ; ne pas relancer cet import.
- `workerAbsentSince` : date à laquelle un statut authentifié a vu, pour la première
  fois, une tentative `queued` sans aucun cluster django-q vivant (null sinon). Elle est
  effacée dès qu’un cluster réapparaît ou que la tentative démarre.
- `sql` : `availability=available|unavailable`, puis, si accessible,
  `sessionPresent`, `state`, `queryAgeSeconds`, `waitEventType`, `blockerCount`.
  Le PID et le début de session sont comparés pour éviter la réutilisation d’un PID.
  Aucun SQL brut, paramètre ou identifiant de bloqueur n’est retourné.

Une ancienne tâche ou un identifiant inconnu peut répondre `pending` sans `progress`.
Le client doit conserver son timeout. Une étape SQL longue avec heartbeat frais peut
attendre un verrou ; consulter `sql` avant de conclure à un worker perdu.

## Commit et reprise

`ImportAttempt` est créé avant l’enqueue, puis le worker prend le verrou de session
existant avant de démarrer le reporter. Une connexion psycopg dédiée en autocommit,
possédée par un thread, sérialise les événements et les heartbeats. Elle ne touche
jamais les lignes métier ou `BulkImportRun`. Ses instructions sont bornées à 5 secondes,
avec 2 secondes d’attente de verrou et une file de 128 événements. Une erreur de
connexion initiale empêche la fusion ; une panne ultérieure conserve la transaction
métier et laisse le suivi devenir périmé. Le reporter est joint avant de quitter le worker.

`ImportReceipt` est écrit dans la transaction métier. Il rend le commit vérifiable
même si le worker disparaît avant son résultat django-q ou pendant le nettoyage.
Une livraison en double retrouve le reçu et ne fusionne pas une seconde fois.

Un statut authentifié peut réconcilier une tentative perdue uniquement après avoir
obtenu son verrou de session. Sans reçu ni résultat, un run encore présent permet
une nouvelle tentative ; l’ancienne devient `interrupted`. Avec reçu, les données
sont appliquées : le statut signale le traitement post-commit interrompu sans réenqueue.
Une ancienne tentative ne peut plus être modifiée par un reporter retardataire.

Une tentative `queued` sans cluster django-q vivant (`Stat.get_all()` vide, sans tâche
django-q de cette tentative) est suivie par `workerAbsentSince`. Après 10 minutes
(`WORKER_ABSENT_GRACE_SECONDS`, de quoi couvrir un redéploiement), le statut authentifié
la passe en `failed` avec l’erreur « No import worker running for 600 s; the queued
import was abandoned », sans la relancer : l’opérateur redémarre le run quand un worker
est revenu ; un import de graphe abandonné supprime aussi son run et sa charge utile, sinon un nouvel import répondrait 409. Une tentative dont les données sont déjà commitées (reçu présent) n’est jamais abandonnée : elle attend un worker pour finaliser. Si Redis est injoignable, l’absence est inconnue : ni marquage ni abandon. Les mises à jour sont conditionnelles et sans verrou.

Le worker prend la tentative par un `UPDATE … WHERE state='queued'` atomique
(`queued` → `running`). Si la réconciliation l’a déjà passée en `failed`, la prise
touche 0 ligne et `execute_merge` lève `ValueError` sans rien fusionner.

La session de fusion fixe `client_connection_check_interval = '10s'` avant de prendre
le verrou advisory : Postgres détecte alors un worker tué (timeout django-q) même pendant
une longue instruction, abandonne la requête et libère le verrou, au lieu de la laisser
tourner jusqu’à sa fin. Le réglage est remis à zéro à la libération du verrou, la connexion du worker survivant à la fusion.

La fenêtre de 10 minutes n’est pas garantie continue : `workerAbsentSince` n’est effacé que par un statut qui voit un cluster, donc une absence brève après un long intervalle sans lecture peut échouer la tentative aussitôt.

Limite connue : une tâche perdue dans Redis alors que le worker vit reste `queued`,
car un cluster vivant efface `workerAbsentSince`.

L’erreur exposée est bornée et générique ; le détail reste dans les logs du worker.
Les tentatives terminées et reçus de plus de 30 jours sont purgés à la création
d’une tentative, si leur run temporaire a été supprimé. Les traces d’un run encore
présent restent disponibles pour son diagnostic. `ImportRun.step_timings` conserve
l’historique métier des succès du pipeline.

## Validation

`uv run pytest` garde les tests SQLite. Les tests avec transaction externe utilisent
`IMPORT_PROGRESS_THREADED=False` dans `tests/settings.py` ; la production utilise
`True`. Les tests PostgreSQL de concurrence activent le reporter réel et vérifient
la visibilité avant commit, le heartbeat pendant une attente de verrou, le rollback,
les pertes du reporter et les interruptions SIGKILL avant et après commit.

```bash
POSTGRES_TEST_DATABASE_URL=postgres://... uv run pytest -m postgres --ds=tests.postgres_settings --no-cov
```

La mesure full sur environ 32 millions de songs et la comparaison delta à export,
matériel et charge identiques restent nécessaires pour valider un surcoût inférieur
à 2 %. Ne pas lancer cette charge en parallèle d’un import staging déjà actif.
