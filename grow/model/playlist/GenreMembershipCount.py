from django.db import models
from the_music_tree_genre_kit.playlist.Playlist import Playlist


class GenreMembershipCount(models.Model):
    """Actual canonical genre-playlist members, partitioned by the track's exact genre."""

    # Source deletion triggers remove buckets; Django must not collect them ahead of
    # membership rows and make the subsequent negative deltas underflow.
    playlist = models.ForeignKey(Playlist, on_delete=models.DO_NOTHING)
    # A bucket key rather than a relation: track genre changes maintain the partition,
    # including genre deletion, without an independent FK cascade deleting statistics.
    genre_id = models.UUIDField(null=True)
    tracks_count = models.PositiveBigIntegerField()

    class Meta:
        db_table = "grow_genre_membership_count"
        constraints = [
            models.UniqueConstraint(
                fields=["playlist", "genre_id"],
                condition=models.Q(genre_id__isnull=False),
                name="genre_membership_nonnull_unique",
            ),
            models.UniqueConstraint(
                fields=["playlist"],
                condition=models.Q(genre_id__isnull=True),
                name="genre_membership_null_unique",
            ),
        ]
