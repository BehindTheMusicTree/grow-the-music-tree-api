from django.db.models import F
from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager

from grow.model.trackable_play_count.Fields import Fields as TrackablePlayCountFields
from grow.model.trackable_play_count.TrackablePlayCount import TrackablePlayCount

from .Fields import Fields


class PlayManager(StandardResourceManager):
    def create(self, **kwargs):
        trackable_play_count_object: TrackablePlayCount = kwargs[Fields.CONTENT]
        # Queryset update, not save(): save() also bumps updated_on, which would invalidate the cached genre tree.
        type(trackable_play_count_object)._default_manager.filter(pk=trackable_play_count_object.pk).update(
            **{TrackablePlayCountFields.PLAY_COUNT: F(TrackablePlayCountFields.PLAY_COUNT) + 1}
        )
        trackable_play_count_object.play_count += 1
        return super().create(**kwargs)
