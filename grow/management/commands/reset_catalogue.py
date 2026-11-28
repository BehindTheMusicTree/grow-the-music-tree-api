from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.pipeline_run.artists_recovery import lock_recovery_admission

CATALOGUE_APPS = ("grow", "the_music_tree_genre_kit")

# Everything else in CATALOGUE_APPS is wiped: a new model is emptied by default, and a unit test fails until it is
# classified here or left to the default on purpose.
KEEP_TABLES = frozenset(
    {
        "grow_user_profile",
        "grow_curation_entry",
        "grow_genre_edge_rule",
        "grow_curation_export",
        "grow_wikidata_item",
        "grow_pipeline_run_request",
        "grow_genre_tree_version",
        "the_music_tree_genre_kit_criteriatype",
    }
)
# Truncated and then restored, in part (history) or as a reset singleton (sync state).
PARTIAL_TABLES = frozenset({"grow_history_entry", "grow_curation_sync_state"})
KEPT_HISTORY_MODELS = ("curationentry", "genreedgerule")

TERMINAL_ATTEMPT_STATES = (
    ImportAttempt.State.SUCCEEDED,
    ImportAttempt.State.FAILED,
    ImportAttempt.State.INTERRUPTED,
)

# Rows owned by a user: the reset refuses to drop them silently.
USER_DATA_CHECKS = {
    "tracks owned by a user": "SELECT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_track WHERE user_id IS NOT NULL)",
    "playlists owned by a user": "SELECT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_playlist WHERE user_id IS NOT NULL)",
    "criteria owned by a user": "SELECT EXISTS (SELECT 1 FROM grow_criteria WHERE user_id IS NOT NULL)",
    "artists owned by a user": "SELECT EXISTS (SELECT 1 FROM grow_artist WHERE user_id IS NOT NULL)",
    "albums owned by a user": "SELECT EXISTS (SELECT 1 FROM grow_album WHERE user_id IS NOT NULL)",
    "manual playlists": "SELECT EXISTS (SELECT 1 FROM grow_manual_playlist)",
    "plays": "SELECT EXISTS (SELECT 1 FROM grow_play)",
}


def catalogue_tables() -> list[str]:
    """Every table of the catalogue apps, deduplicated (multi-table inheritance and proxies share tables)."""
    models = [
        model for app in CATALOGUE_APPS for model in apps.get_app_config(app).get_models(include_auto_created=True)
    ]
    return sorted(dict.fromkeys(model._meta.db_table for model in models))


def wiped_tables() -> list[str]:
    return [table for table in catalogue_tables() if table not in KEEP_TABLES]


class Command(BaseCommand):
    help = (
        "Empty the catalogue (songs, artists, genres, playlists, graph, imports) and keep the curation, users and "
        "run history, so the next import starts from an empty base."
    )

    def add_arguments(self, parser):
        parser.add_argument("--confirm", required=True, help="Name of the database to empty")
        parser.add_argument("--dry-run", action="store_true", help="List the tables and estimated rows, then exit")
        parser.add_argument(
            "--include-user-data", action="store_true", help="Also wipe tracks, playlists and plays owned by users"
        )

    def handle(self, *args, confirm, dry_run, include_user_data, **options):
        if connection.vendor != "postgresql":
            raise CommandError("reset_catalogue needs PostgreSQL")
        name = connection.settings_dict["NAME"]
        if confirm != name:
            raise CommandError(f"--confirm must be the database name ({name!r}), got {confirm!r}")
        self._check_idle()
        if not include_user_data:
            self._check_no_user_data()
        tables = wiped_tables()
        estimates = self._estimates(tables)
        for table in tables:
            self.stdout.write(f"{table}: ~{estimates.get(table, 0)} rows")
        if dry_run:
            self.stdout.write("Dry run: nothing changed.")
            return
        with transaction.atomic():
            lock_recovery_admission()
            self._check_idle()
            self._wipe(tables)
        self._analyze(tables)
        self.stdout.write(f"Emptied {len(tables)} tables.")

    def _check_idle(self) -> None:
        # Any non-terminal attempt blocks, lock held or not: a freshly queued merge has no lock and no receipt yet
        # and waits in the broker (Redis in prod), so it cannot be seen from the database otherwise.
        pending = ImportAttempt.objects.exclude(state__in=TERMINAL_ATTEMPT_STATES).order_by("run_id", "attempt")
        if pending:
            raise CommandError(
                f"imports still pending: {[f'run={a.run_id} kind={a.kind} state={a.state}' for a in pending]}"
            )
        active = PipelineRunRequest.objects.filter(
            status__in=[PipelineRunRequest.Status.QUEUED, PipelineRunRequest.Status.RUNNING]
        ).count()
        if active:
            raise CommandError(f"{active} pipeline run request(s) queued or running")

    def _check_no_user_data(self) -> None:
        found = []
        with connection.cursor() as cursor:
            for label, sql in USER_DATA_CHECKS.items():
                cursor.execute(sql)
                if cursor.fetchone()[0]:
                    found.append(label)
        if found:
            raise CommandError(f"user data present ({', '.join(found)}); pass --include-user-data to wipe it")

    def _estimates(self, tables: list[str]) -> dict[str, int]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relname, GREATEST(reltuples, 0)::bigint FROM pg_class "
                "WHERE relkind = 'r' AND relnamespace = current_schema()::regnamespace AND relname = ANY(%s)",
                [tables],
            )
            return dict(cursor.fetchall())

    def _wipe(self, tables: list[str]) -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """CREATE TEMP TABLE kept_history ON COMMIT DROP AS
                SELECT h.* FROM grow_history_entry h
                JOIN django_content_type ct ON ct.id = h.content_type_id
                WHERE ct.app_label = 'grow' AND ct.model = ANY(%s)""",
                [list(KEPT_HISTORY_MODELS)],
            )
            # One statement and no CASCADE: Postgres refuses when a kept table references a wiped one.
            cursor.execute("TRUNCATE " + ", ".join(tables))
            cursor.execute("INSERT INTO grow_history_entry SELECT * FROM kept_history")
            CurationSyncState.load()

    def _analyze(self, tables: list[str]) -> None:
        # Outside the transaction (and VACUUM-free): the first import must not plan on pre-wipe statistics.
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f"ANALYZE {table}")
