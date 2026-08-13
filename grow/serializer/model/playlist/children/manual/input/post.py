from django.conf import settings
from rest_framework.serializers import ModelSerializer
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist
from grow.serializer.field.UniquePerUserNameField import UniquePerUserNameField

from .Fields import Fields


class ManualPlaylistPostSerializer(ModelSerializer, AppInputSerializer):
    name = UniquePerUserNameField(
        max_length=settings.MANUAL_PLAYLIST_NAME_LEN_MAX, allow_blank=False, required=True, model=ManualPlaylist
    )

    class Meta:
        model = ManualPlaylist
        fields = [Fields.NAME_PUBLIC]
