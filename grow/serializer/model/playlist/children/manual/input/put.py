from django.conf import settings
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_api_kit.serializer.PutSerializer import PutSerializer

from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist

from .Fields import Fields


class ManualPlaylistPutSerializer(PutSerializer):
    name = AppCharField(max_length=settings.MANUAL_PLAYLIST_NAME_LEN_MAX, required=False)

    class Meta:
        model = ManualPlaylist
        fields = [Fields.NAME_PUBLIC]
