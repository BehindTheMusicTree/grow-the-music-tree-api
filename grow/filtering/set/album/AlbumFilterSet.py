from the_music_tree_api_kit.filtering.filter.char.NonEmptiableCharFilter import NonEmptiableCharFilter
from the_music_tree_api_kit.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import (
    PrivateUniqueResourceFilterSet,
)

from grow.filtering.filter.ArtistNameFilter import ArtistNameFilter
from grow.model.album.Album import Album
from grow.model.album.Fields import Fields as ModelFields

from .Fields import Fields


class AlbumFilterSet(PrivateUniqueResourceFilterSet):
    name = NonEmptiableCharFilter(
        field_name=ModelFields.NAME_INTERNAL, field_name_public=ModelFields.NAME_PUBLIC, lookup_expr="icontains"
    )
    album_artist_name = ArtistNameFilter(
        field_name=ModelFields.ALBUM_ARTISTS, field_name_public=Fields.ALBUM_ARTIST_NAME
    )

    class Meta:
        model = Album
        fields = [Fields.NAME_PUBLIC, Fields.ALBUM_ARTIST_NAME, *PrivateUniqueResourceFilterSet.get_date_fields()]
