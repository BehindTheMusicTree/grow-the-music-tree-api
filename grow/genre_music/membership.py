from uuid import uuid4

from django.db.models import Count, F, Q
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks


def exact_membership_counts() -> dict[int, int]:
    """Count actual canonical genre playlist memberships whose track has that exact genre.

    Missing playlist IDs have zero members. This deliberately queries membership rather than
    assuming that a song's eligibility or its position implies membership.
    """
    same_genre = Q(track__genre_id=F("playlist__criteria_playlist__criteria_id")) | Q(
        track__genre_id__isnull=True, playlist__criteria_playlist__criteria_id__isnull=True
    )
    rows = (
        TrackPlaylistRel.objects.filter(
            same_genre,
            user__isnull=True,
            track__user__isnull=True,
            playlist__user__isnull=True,
            playlist__criteria_playlist__type_id=int(CriteriaTypePks.GENRE),
        )
        .order_by()
        .values_list("playlist_id")
        .annotate(count=Count("pk"))
    )
    return dict(rows)


def membership_bucket_counts(*, using: str = "default") -> dict:
    """Independent source-of-truth aggregation for verification and explicit repair."""
    rows = (
        TrackPlaylistRel.objects.using(using)
        .filter(
            user__isnull=True,
            track__user__isnull=True,
            playlist__user__isnull=True,
            playlist__criteria_playlist__type_id=int(CriteriaTypePks.GENRE),
        )
        .order_by()
        .values_list("playlist_id", "track__genre_id")
        .annotate(count=Count("pk"))
    )
    return {(playlist, genre): count for playlist, genre, count in rows}


def stored_membership_bucket_counts(*, using: str = "default") -> dict:
    from grow.model.playlist.GenreMembershipCount import GenreMembershipCount

    return {
        (playlist, genre): count
        for playlist, genre, count in GenreMembershipCount.objects.using(using).values_list(
            "playlist_id", "genre_id", "tracks_count"
        )
    }


def verify_membership_counts(*, repair: bool = False, using: str = "default") -> tuple[dict, dict]:
    from django.db import connections, transaction

    from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
    from grow.model.playlist.GenreMembershipCount import GenreMembershipCount

    # The same gate as source triggers gives comparison and repair one consistent view.
    # Missing configuration is an error: never recreate the version singleton here.
    with transaction.atomic(using=using):
        if connections[using].vendor == "postgresql":
            with connections[using].cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                if cursor.fetchone()[0] != "read committed":
                    raise ValueError("Genre membership verification requires READ COMMITTED isolation")
                cursor.execute("SELECT pg_advisory_xact_lock(716731928417)")
        GenreTreeVersion.objects.using(using).select_for_update().get(pk=1)
        expected = membership_bucket_counts(using=using)
        actual = stored_membership_bucket_counts(using=using)
        if repair and expected != actual:
            GenreTreeVersion.objects.using(using).filter(pk=1).update(token=uuid4())
            GenreMembershipCount.objects.using(using).all().delete()
            GenreMembershipCount.objects.using(using).bulk_create(
                GenreMembershipCount(playlist_id=playlist, genre_id=genre, tracks_count=count)
                for (playlist, genre), count in expected.items()
            )
        return expected, actual
