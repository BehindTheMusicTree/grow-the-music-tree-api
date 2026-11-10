from django.db import models
from django.db.models.functions import Coalesce


class GenreCatalogueCount(models.Model):
    """Canonical Song/Track joins grouped by assigned genre, including unplayable songs."""

    # Scalar keys keep collector/FK cascade ordering out of projection maintenance.
    genre_id = models.UUIDField(null=True)
    tracks_count = models.PositiveBigIntegerField()

    class Meta:
        db_table = "grow_genre_catalogue_count"
        constraints = [
            models.UniqueConstraint(
                fields=["genre_id"], condition=models.Q(genre_id__isnull=False), name="genre_catalogue_nonnull_unique"
            ),
            models.UniqueConstraint(
                Coalesce(
                    "genre_id", models.Value("00000000-0000-0000-0000-000000000000", output_field=models.UUIDField())
                ),
                condition=models.Q(genre_id__isnull=True),
                name="genre_catalogue_null_unique",
            ),
        ]
