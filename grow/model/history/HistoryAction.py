from django.db import models


class HistoryAction(models.TextChoices):
    CREATED = "created", "Created"
    PARENT_CHANGED = "parent_changed", "Parent changed"
    RENAMED = "renamed", "Renamed"
    EXCLUDED = "excluded", "Excluded"
    GENRE_CHANGED = "genre_changed", "Genre changed"
    DELETED = "deleted", "Deleted"
    NAME_CONFLICT_RESOLVED = "name_conflict_resolved", "Name conflict resolved"
