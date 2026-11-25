from dataclasses import dataclass, field
from uuid import UUID, uuid4

from django.db import connections, transaction
from django.db.models import Count
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphDataset, GenreGraphNode
from the_music_tree_genre_kit.track.Track import Track as KitTrack

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount
from grow.model.song.Song import Song

Bucket = UUID | None


def catalogue_bucket_counts(*, using: str = "default") -> dict[Bucket, int]:
    """Independent aggregation of actual Song/Track joins, never stored counters."""
    return dict(
        Song.objects.using(using)
        .filter(user__isnull=True)
        .order_by()
        .values_list("membership_genre_id")
        .annotate(count=Count("pk"))
    )


def derived_song_genres(*, using: str = "default") -> dict[UUID, UUID | None]:
    """Effective genre of every song, derived from its sources in Python, never from the stored column."""
    songs = Song.objects.using(using).order_by().values_list("track_id", "genre_id")
    if not GenreGraphDataset.objects.using(using).filter(key="grow").exists():
        return dict(songs)
    attributed = dict(
        GenreGraphAttribution.objects.using(using)
        .filter(node__dataset_id="grow", node__is_active=True)
        .values_list("track_id", "node__id")
    )
    genre_by_node = dict(Genre.objects.using(using).filter(graph_node__isnull=False).values_list("graph_node_id", "pk"))
    return {track: genre_by_node.get(attributed.get(track)) for track, _ in songs}


def song_membership_drift(*, using: str = "default") -> dict[UUID, tuple[UUID | None, UUID | None]]:
    """Songs whose trigger-maintained `membership_genre` differs from the derived genre, as (derived, stored)."""
    stored = dict(Song.objects.using(using).order_by().values_list("track_id", "membership_genre_id"))
    return {
        track: (genre, stored[track])
        for track, genre in derived_song_genres(using=using).items()
        if stored[track] != genre
    }


def song_membership_drift_summary(*, using: str = "default", sample: int = 20) -> tuple[int, list[UUID]]:
    """Set-based `song_membership_drift`: the drift count and a sample of track ids, in two cursor reads.

    The Python oracle loads about 32 M songs into dicts, which does not fit the memory of a benchmark container.
    The two must agree (parity tests): change the derivation in both.
    """
    song, track, node = Song._meta.db_table, KitTrack._meta.db_table, GenreGraphNode._meta.db_table
    attribution, genre = GenreGraphAttribution._meta.db_table, Genre._meta.db_table
    criteria = Genre._meta.get_field("graph_node").model._meta.db_table
    with connections[using].cursor() as cursor:
        cursor.execute(f'SELECT EXISTS (SELECT 1 FROM "{GenreGraphDataset._meta.db_table}" WHERE "key" = %s)', ["grow"])
        graph = cursor.fetchone()[0]
        derived = "g.criteria_ptr_id" if graph else "t.genre_id"
        joins = (
            f'LEFT JOIN "{attribution}" a ON a.track_id = s.track_id AND a.dataset_id = %s '
            f'LEFT JOIN "{node}" n ON n.id = a.node_id AND n.is_active '
            f'LEFT JOIN "{criteria}" c ON c.graph_node_id = n.id '
            f'LEFT JOIN "{genre}" g ON g.criteria_ptr_id = c.uuid'
            if graph
            else f'JOIN "{track}" t ON t.uuid = s.track_id'
        )
        params = ["grow"] if graph else []
        body = f'FROM "{song}" s {joins} WHERE s.genre_id IS DISTINCT FROM {derived}'
        cursor.execute(f"SELECT count(*) {body}", params)
        count = cursor.fetchone()[0]
        cursor.execute(f"SELECT s.track_id {body} ORDER BY s.track_id LIMIT %s", [*params, sample])
        return count, [row[0] for row in cursor.fetchall()]


def stored_catalogue_bucket_counts(*, using: str = "default") -> dict[Bucket, int]:
    return dict(GenreCatalogueCount.objects.using(using).values_list("genre_id", "tracks_count"))


@dataclass(frozen=True)
class CatalogueReport:
    expected: dict[Bucket, int]
    stored: dict[Bucket, int]
    mismatches: dict[Bucket, tuple[int, int]] = field(default_factory=dict)
    negatives: dict[Bucket, int] = field(default_factory=dict)
    unexpected: set[Bucket] = field(default_factory=set)
    missing_playlists: set[Bucket] = field(default_factory=set)

    @property
    def valid(self) -> bool:
        return not (self.mismatches or self.negatives or self.unexpected or self.missing_playlists)


def _report(expected, actual, required, playlists):
    # Sparse absent buckets and explicit zero buckets both mean zero.
    return CatalogueReport(
        expected=expected,
        stored=actual,
        mismatches={
            key: (expected.get(key, 0), actual.get(key, 0))
            for key in expected.keys() | actual.keys()
            if expected.get(key, 0) != actual.get(key, 0)
        },
        negatives={key: count for key, count in actual.items() if count < 0},
        unexpected=actual.keys() - required,
        missing_playlists=required - playlists,
    )


def _compare(using):
    expected = catalogue_bucket_counts(using=using)
    required = set(Genre.objects.using(using).filter(user__isnull=True).values_list("pk", flat=True)) | {None}
    playlists = set(
        CriteriaPlaylist.objects.using(using)
        .filter(user__isnull=True, type_id=CriteriaTypePks.GENRE)
        .values_list("criteria_id", flat=True)
    )
    return {
        "catalogue": _report(expected, stored_catalogue_bucket_counts(using=using), required, playlists),
    }


def verify_catalogue_counts(*, repair: bool = False, using: str = "default") -> dict[str, CatalogueReport]:
    """Return pre-repair findings; a successful repair is independently rechecked before commit."""
    with transaction.atomic(using=using):
        if connections[using].vendor == "postgresql":
            with connections[using].cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                if cursor.fetchone()[0] != "read committed":
                    raise ValueError("Genre catalogue verification requires READ COMMITTED isolation")
                cursor.execute("SELECT pg_advisory_xact_lock(716731928417)")
        # Same gate -> version-row order as membership verification and source triggers.
        GenreTreeVersion.objects.using(using).select_for_update().get(pk=1)
        reports = _compare(using)
        if repair and any(not report.valid for report in reports.values()):
            if any(report.missing_playlists for report in reports.values()):
                raise ValueError("Catalogue configuration is invalid; repair cannot create or remove playlists")
            expected = reports["catalogue"].expected
            GenreCatalogueCount.objects.using(using).all().delete()
            GenreCatalogueCount.objects.using(using).bulk_create(
                GenreCatalogueCount(genre_id=genre, tracks_count=count) for genre, count in expected.items()
            )
            GenreTreeVersion.objects.using(using).filter(pk=1).update(token=uuid4())
            if any(not report.valid for report in _compare(using).values()):
                raise RuntimeError("Independent catalogue verification failed after repair; changes rolled back")
        return reports
