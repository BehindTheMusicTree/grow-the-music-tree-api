from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.serializer.model.criteria.output.detailed_tracks import (
    build_criteria_detailed_tracks_fields,
)

from grow.model.criteria.Criteria import Criteria
from grow.model.criteria.Fields import Fields as ModelFields
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.criteria_lineage_rel.without_ascendant import CriteriaLineageRelWithoutAscendantSerializer
from grow.serializer.model.criteria_lineage_rel.without_descendant import (
    CriteriaLineageRelWithoutDescendantSerializer,
)
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer
from grow.serializer.model.track.output.simple.simple_without_album_and_genre import (
    TrackWithoutAlbumPlaylistGenreSerializer,
)

from .CriteriaOutputFieldKey import CriteriaOutputFieldKey

_tracks_fields = build_criteria_detailed_tracks_fields(
    TrackWithoutAlbumPlaylistGenreSerializer,
    CriteriaOutputFieldKey.TRACKS_NOT_ARCHIVED_PUBLIC.value,
    CriteriaOutputFieldKey.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC.value,
    CriteriaOutputFieldKey.TRACKS_ARCHIVED_COUNT_PUBLIC.value,
)


class CriteriaDetailedSerializer(AppInputSerializer, serializers.ModelSerializer):
    tracks = _tracks_fields[CriteriaOutputFieldKey.TRACKS_NOT_ARCHIVED_PUBLIC.value]
    tracks_count = _tracks_fields[CriteriaOutputFieldKey.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC.value]
    tracks_archived_count = _tracks_fields[CriteriaOutputFieldKey.TRACKS_ARCHIVED_COUNT_PUBLIC.value]
    parent = CriteriaMinimumSerializer()
    ascendants = CriteriaLineageRelWithoutDescendantSerializer(source=ModelFields.ASCENDANTS_RELS, many=True)
    descendants = CriteriaLineageRelWithoutAscendantSerializer(source=ModelFields.DESCENDANTS_RELS, many=True)
    root = CriteriaMinimumSerializer()  # type: ignore
    children = CriteriaMinimumSerializer(many=True)
    criteria_playlist = CriteriaPlaylistMinimumSerializer()
    name = AppCharField(source=ModelFields.NAME_INTERNAL)
    # `side` lives only on the concrete `Genre` MTI subtype, not on `Meta.model` (`Criteria`,
    # shared by both `GenreViewSet` and `TagViewSet`) -- read it defensively rather than
    # relying on DRF's automatic model-field lookup, which would fail Criteria/Tag instances.
    side = serializers.SerializerMethodField()

    def get_side(self, obj) -> str | None:
        genre = getattr(obj, "genre", None)
        return genre.side if genre else None

    class Meta:
        model = Criteria
        fields = [
            CriteriaOutputFieldKey.UUID.value,
            CriteriaOutputFieldKey.NAME.value,
            CriteriaOutputFieldKey.PARENT.value,
            CriteriaOutputFieldKey.ASCENDANTS.value,
            CriteriaOutputFieldKey.DESCENDANTS.value,
            CriteriaOutputFieldKey.ROOT.value,
            CriteriaOutputFieldKey.CHILDREN.value,
            CriteriaOutputFieldKey.CRITERIA_PLAYLIST.value,
            CriteriaOutputFieldKey.TRACKS_NOT_ARCHIVED_PUBLIC.value,
            CriteriaOutputFieldKey.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC.value,
            CriteriaOutputFieldKey.TRACKS_ARCHIVED_COUNT_PUBLIC.value,
            CriteriaOutputFieldKey.SIDE.value,
            CriteriaOutputFieldKey.CREATED_ON.value,
            CriteriaOutputFieldKey.UPDATED_ON.value,
        ]
