from django.db import models
from the_music_tree_api_kit.private_unique_resource.PrivateUniqueResource import PrivateUniqueResource

from .Fields import Fields


class TrackablePlayCount(PrivateUniqueResource):
    play_count = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
