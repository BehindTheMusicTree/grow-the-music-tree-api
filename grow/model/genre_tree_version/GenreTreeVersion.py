from uuid import UUID

from django.db import models


class GenreTreeVersion(models.Model):
    """Singleton whose token DB triggers regenerate on every write to a table the genre tree serializes."""

    token = models.UUIDField()

    class Meta:
        db_table = "grow_genre_tree_version"

    @classmethod
    def current_token(cls) -> UUID:
        return cls.objects.values_list("token", flat=True).get(pk=1)
