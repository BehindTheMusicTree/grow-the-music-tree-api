from django_filters import CharFilter

from grow.filtering.filter.char.EmptiableCharFilter import EmptiableCharFilter
from grow.filtering.filter.char.RelatedObjectCharFilter import RelatedObjectCharFilter
from grow.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import PrivateUniqueResourceFilterSet
from grow.model.album.Fields import Fields as AlbumFields
from grow.model.artist.Fields import Fields as ArtistFields
from grow.model.criteria.Criteria import Fields as CriteriaFields
from grow.model.uploaded_track.Fields import Fields as ModelFields
from grow.model.uploaded_track.UploadedTrack import UploadedTrack

from .Fields import Fields


class UploadedTrackFilterSet(PrivateUniqueResourceFilterSet):
    title = CharFilter(field_name=ModelFields.TITLE, lookup_expr="icontains")
    artists_name = RelatedObjectCharFilter(
        primary_field=ArtistFields.NAME_INTERNAL,
        field_name=ModelFields.ARTISTS,
        field_name_public=Fields.ARTISTS_NAME,
        lookup_expr="icontains",
    )
    album_name = RelatedObjectCharFilter(
        primary_field=AlbumFields.NAME_INTERNAL,
        field_name=ModelFields.ALBUM,
        field_name_public=Fields.ALBUM_NAME,
        lookup_expr="icontains",
    )
    genre_name = RelatedObjectCharFilter(
        primary_field=CriteriaFields.NAME_INTERNAL,
        field_name=ModelFields.GENRE,
        field_name_public=Fields.GENRE_NAME,
        lookup_expr="icontains",
    )
    language = EmptiableCharFilter(
        field_name_public=ModelFields.LANGUAGE, field_name=ModelFields.LANGUAGE, lookup_expr="icontains"
    )

    class Meta:
        model = UploadedTrack
        fields = [Fields.TITLE, Fields.LANGUAGE, *PrivateUniqueResourceFilterSet.get_date_fields()]
