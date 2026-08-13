from grow.filtering.filter.char.NonEmptiableCharFilter import NonEmptiableCharFilter
from grow.filtering.filter.char.RelatedObjectCharFilter import RelatedObjectCharFilter
from grow.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import PrivateUniqueResourceFilterSet
from grow.model.album.Album import Album
from grow.model.album.Fields import Fields as ModelFields
from grow.model.artist.Fields import Fields as ArtistModelFields

from .Fields import Fields


class AlbumFilterSet(PrivateUniqueResourceFilterSet):
    name = NonEmptiableCharFilter(
        field_name=ModelFields.NAME_INTERNAL, field_name_public=ModelFields.NAME_PUBLIC, lookup_expr="icontains"
    )
    album_artist_name = RelatedObjectCharFilter(
        primary_field=ArtistModelFields.NAME_INTERNAL,
        field_name=ModelFields.ALBUM_ARTISTS,
        field_name_public=Fields.ALBUM_ARTIST_NAME,
        lookup_expr="icontains",
    )

    class Meta:
        model = Album
        fields = [Fields.NAME_PUBLIC, Fields.ALBUM_ARTIST_NAME, *PrivateUniqueResourceFilterSet.get_date_fields()]
