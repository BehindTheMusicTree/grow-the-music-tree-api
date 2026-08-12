from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager

from grow.model.trackable_play_count.Fields import Fields as TrackablePlayCountFields
from grow.model.trackable_play_count.TrackablePlayCount import TrackablePlayCount

from .Fields import Fields


class PlayManager(StandardResourceManager):
    def create(self, **kwargs):
        trackable_play_count_object: TrackablePlayCount = kwargs[Fields.CONTENT]
        trackable_play_count_object.play_count += 1
        trackable_play_count_object.save(update_fields=[TrackablePlayCountFields.PLAY_COUNT])
        return super().create(**kwargs)
