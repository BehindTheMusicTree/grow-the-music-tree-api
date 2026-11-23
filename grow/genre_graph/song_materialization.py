from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from django.db import connection, transaction
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphNode

from grow.bulk_import.progress import report_step
from grow.model.criteria.Criteria import Criteria
from grow.model.song.Song import Song

MAINTENANCE = "grow.membership_maintenance"


@contextmanager
def membership_maintenance() -> Iterator[None]:
    if connection.vendor != "postgresql":
        yield
        return
    if not connection.in_atomic_block:
        raise RuntimeError("Song membership maintenance requires an outer transaction")
    # Rolling back to this savepoint also restores SET LOCAL on failure.
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [MAINTENANCE])
        previous = cursor.fetchone()[0]
        cursor.execute("SELECT set_config(%s, 'on', true)", [MAINTENANCE])
        yield
        cursor.execute("SELECT set_config(%s, %s, true)", [MAINTENANCE, previous or ""])


class SongMaterialization:
    def __init__(self, *, dataset_key: str, initial: bool):
        self.dataset_key = dataset_key
        self.initial = initial
        self.candidate_table = connection.ops.quote_name(f"grow_affected_song_{uuid4().hex}")
        self.candidate_count = 0
        self.table_created = False

    def _bindings(self) -> dict[int, UUID]:
        return dict(
            Criteria.objects.filter(graph_node__dataset_id=self.dataset_key, graph_node__is_active=True).values_list(
                "graph_node_id", "uuid"
            )
        )

    def capture(self, retired: Iterable[str]) -> None:
        if connection.vendor != "postgresql" or self.initial:
            return
        with report_step("capture_retired_song_candidates") as step:
            self.before = self._bindings()
            if retired:
                self._add_candidates(
                    GenreGraphNode.objects.filter(
                        dataset_id=self.dataset_key, is_active=True, identity__in=retired
                    ).values_list("pk", flat=True)
                )
            step["rowcount"] = self.candidate_count

    def _add_candidates(self, node_ids: Iterable[int]) -> None:
        ids = list(node_ids)
        if not ids:
            return
        with connection.cursor() as cursor:
            if not self.table_created:
                cursor.execute(f"CREATE TEMP TABLE {self.candidate_table} (track_id uuid PRIMARY KEY) ON COMMIT DROP")
                self.table_created = True
            cursor.execute(
                f"""INSERT INTO {self.candidate_table} (track_id)
                SELECT track_id FROM {GenreGraphAttribution._meta.db_table}
                WHERE dataset_id = %s AND node_id = ANY(%s::bigint[])
                ON CONFLICT (track_id) DO NOTHING""",
                [self.dataset_key, ids],
            )
            self.candidate_count += cursor.rowcount

    def finish(self) -> int:
        if connection.vendor != "postgresql":
            return 0
        if not self.initial:
            with report_step("capture_changed_binding_song_candidates") as step:
                after = self._bindings()
                self._add_candidates(
                    node for node in self.before.keys() | after.keys() if self.before.get(node) != after.get(node)
                )
                step["rowcount"] = self.candidate_count
        with report_step("materialize_song_genres") as step:
            changed = self._update() if self.initial or self.candidate_count else 0
            step["rowcount"] = changed
        self.discard()
        return changed

    def discard(self) -> None:
        if self.table_created:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE {self.candidate_table}")
            self.table_created = False

    def _update(self) -> int:
        song = Song._meta.db_table
        attribution = GenreGraphAttribution._meta.db_table
        node = GenreGraphNode._meta.db_table
        criteria = Criteria._meta.db_table
        population = song if self.initial else self.candidate_table
        candidate_join = "" if self.initial else f"JOIN {population} AS scope ON scope.track_id = a.track_id"
        with connection.cursor() as cursor:
            if not self.initial:
                cursor.execute(f"ANALYZE {population}")
            cursor.execute(
                f"""UPDATE {song} AS s SET genre_id = effective.genre_uuid
                FROM {population} AS candidate
                LEFT JOIN (
                    SELECT a.track_id, c.uuid AS genre_uuid
                    FROM {attribution} AS a
                    {candidate_join}
                    JOIN {node} AS n ON n.id = a.node_id AND n.dataset_id = %s AND n.is_active
                    JOIN {criteria} AS c ON c.graph_node_id = n.id
                    WHERE a.dataset_id = %s
                ) AS effective ON effective.track_id = candidate.track_id
                WHERE s.track_id = candidate.track_id
                  AND s.genre_id IS DISTINCT FROM effective.genre_uuid""",
                [self.dataset_key, self.dataset_key],
            )
            return cursor.rowcount
