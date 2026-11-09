from dataclasses import dataclass, field
from uuid import UUID, uuid4

from django.db import connections, transaction
from django.db.models import Count
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

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
        .values_list("genre_id")
        .annotate(count=Count("pk"))
    )


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
    playlists = dict(
        CriteriaPlaylist.objects.using(using)
        .filter(user__isnull=True, type_id=CriteriaTypePks.GENRE)
        .values_list("criteria_id", "direct_songs_count")
    )
    return {
        "legacy": _report(expected, playlists, required, playlists.keys()),
        "shadow": _report(expected, stored_catalogue_bucket_counts(using=using), required, playlists.keys()),
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
            if any(report.missing_playlists for report in reports.values()) or reports["legacy"].unexpected:
                raise ValueError("Catalogue configuration is invalid; repair cannot create or remove playlists")
            expected = reports["shadow"].expected
            playlists = list(
                CriteriaPlaylist.objects.using(using).filter(user__isnull=True, type_id=CriteriaTypePks.GENRE)
            )
            for playlist in playlists:
                playlist.direct_songs_count = expected.get(playlist.criteria_id, 0)
            CriteriaPlaylist.objects.using(using).bulk_update(playlists, ["direct_songs_count"], batch_size=500)
            GenreCatalogueCount.objects.using(using).all().delete()
            GenreCatalogueCount.objects.using(using).bulk_create(
                GenreCatalogueCount(genre_id=genre, tracks_count=count) for genre, count in expected.items()
            )
            GenreTreeVersion.objects.using(using).filter(pk=1).update(token=uuid4())
            if any(not report.valid for report in _compare(using).values()):
                raise RuntimeError("Independent catalogue verification failed after repair; changes rolled back")
        return reports
