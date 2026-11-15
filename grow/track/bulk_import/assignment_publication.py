"""Validate and publish complete staged assignment sets inside the song merge transaction."""

from contextlib import contextmanager
from uuid import UUID, uuid4

from django.db import connection, transaction
from rest_framework.exceptions import ValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphEvidence, GenreGraphNode
from the_music_tree_genre_kit.genre_graph.publication import publish_staged_attributions
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict, graph_write_transaction

from grow.genre_graph.service import DATASET_KEY
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging


@contextmanager
def assignment_write_transaction(*, expected_graph: UUID, expected_membership: UUID):
    """Enter before song writes: source gate, reviewed dataset, then the caller's track locks."""
    with transaction.atomic():
        lock_catalogue_sources()
        with graph_write_transaction(key=DATASET_KEY, expected_revision=expected_graph) as dataset:
            if dataset.membership_revision != expected_membership:
                raise GraphRevisionConflict("Reference memberships changed; reload before importing")
            yield dataset


def publish_assignments(*, run_id: int, dataset) -> None:
    """Publish against song_import(mbid, track_id, is_locked), already created by the song merge.

    The caller enters assignment_write_transaction before all song and projection writes. A staged row is required for
    every uploaded song, including locked songs and explicitly empty assignments.
    """
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise RuntimeError("Assignment publication requires an outer PostgreSQL transaction")
    quote = connection.ops.quote_name
    suffix = uuid4().hex
    population = f"song_assign_population_{suffix}"
    flat = f"song_assign_flat_{suffix}"
    desired = f"song_assign_desired_{suffix}"
    p, f, d = (quote(name) for name in (population, flat, desired))
    staging, nodes, evidence = (
        quote(model._meta.db_table) for model in (SongAssignmentStaging, GenreGraphNode, GenreGraphEvidence)
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT EXISTS (
                SELECT musicbrainz_recording_id FROM {staging} WHERE run_id = %s
                GROUP BY musicbrainz_recording_id HAVING count(*) <> 1
                UNION ALL SELECT s.mbid FROM song_import s LEFT JOIN {staging} a
                  ON a.run_id = %s AND a.musicbrainz_recording_id = s.mbid
                  WHERE a.id IS NULL
                UNION ALL SELECT a.musicbrainz_recording_id FROM {staging} a LEFT JOIN song_import s
                  ON s.mbid = a.musicbrainz_recording_id WHERE a.run_id = %s AND s.mbid IS NULL
                UNION ALL SELECT a.musicbrainz_recording_id FROM {staging} a WHERE a.run_id = %s
                  AND (SELECT count(*) FROM jsonb_object_keys(a.assignments)) > 1
            )""",
            [run_id, run_id, run_id, run_id],
        )
        if cursor.fetchone()[0]:
            raise ValidationError(
                "Every imported song must have exactly one staged row with at most one directly assigned genre"
            )
        cursor.execute(f"CREATE TEMP TABLE {p} ON COMMIT DROP AS SELECT track_id FROM song_import WHERE NOT is_locked")
        cursor.execute(f"CREATE UNIQUE INDEX ON {p} (track_id)")
        cursor.execute(
            f"""CREATE TEMP TABLE {f} ON COMMIT DROP AS
            SELECT s.track_id, s.is_locked, entry.key AS identity, decision.value->>'decisionId' AS decision_id,
                decision.value->>'source' AS source, decision.value->>'rationale' AS rationale
            FROM {staging} a JOIN song_import s ON s.mbid = a.musicbrainz_recording_id
            CROSS JOIN LATERAL jsonb_each(a.assignments) entry
            CROSS JOIN LATERAL jsonb_array_elements(entry.value) decision
            WHERE a.run_id = %s""",
            [run_id],
        )
        cursor.execute(f"ANALYZE {p}")
        cursor.execute(f"ANALYZE {f}")
        cursor.execute(
            f"""SELECT EXISTS (
                SELECT 1 FROM {f} f LEFT JOIN {nodes} n
                  ON n.dataset_id = %s AND n.identity = f.identity AND n.is_active
                  WHERE n.id IS NULL
                UNION ALL SELECT 1 FROM {f} GROUP BY decision_id
                  HAVING count(DISTINCT (source, rationale)) > 1
                UNION ALL SELECT 1 FROM {f} f JOIN {evidence} e
                  ON e.dataset_id = %s AND e.decision_id = f.decision_id
                  WHERE (e.source, e.rationale) IS DISTINCT FROM (f.source, f.rationale)
            )""",
            [dataset.pk, dataset.pk],
        )
        if cursor.fetchone()[0]:
            raise ValidationError("Assignment identities or evidence are invalid for the reviewed graph")
        cursor.execute(
            f"""INSERT INTO {evidence} (dataset_id, decision_id, source, rationale)
            SELECT DISTINCT %s, f.decision_id, f.source, f.rationale FROM {f} f
            WHERE NOT f.is_locked AND NOT EXISTS (
                SELECT 1 FROM {evidence} e WHERE e.dataset_id = %s AND e.decision_id = f.decision_id)""",
            [dataset.pk, dataset.pk],
        )
        cursor.execute(
            f"""CREATE TEMP TABLE {d} ON COMMIT DROP AS
            SELECT f.track_id, n.id AS node_id, e.id AS evidence_id FROM {f} f
            JOIN {nodes} n ON n.dataset_id = %s AND n.identity = f.identity
            JOIN {evidence} e ON e.dataset_id = %s AND e.decision_id = f.decision_id
            WHERE NOT f.is_locked""",
            [dataset.pk, dataset.pk],
        )
        # The kit compares complete sets through correlated lookups for each track.
        cursor.execute(f"CREATE INDEX ON {d} (track_id, node_id, evidence_id)")
        cursor.execute(f"ANALYZE {d}")
        publish_staged_attributions(dataset=dataset, population=population, assignments=desired)
        cursor.execute(f"DROP TABLE {d}, {f}, {p}")
