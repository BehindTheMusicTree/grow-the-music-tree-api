from django.db.models import Prefetch
from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.criteria.lineage_rel.Fields import Fields as LineageFields
from the_music_tree_genre_kit.serializer.model.criteria.output.side import CriteriaSideSerializerMixin
from the_music_tree_genre_kit.track.Fields import Fields as TrackFields

from grow.model.criteria.Criteria import Criteria
from grow.model.criteria.Fields import Fields as ModelFields
from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.criteria_lineage_rel.without_descendant import (
    CriteriaLineageRelWithoutDescendantSerializer,
)
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer

from .CriteriaOutputFieldKey import CriteriaOutputFieldKey
from .essential_songs import CriteriaEssentialSongsSerializerMixin


class CriteriaDetailedSerializer(
    EagerLoadingMixin,
    CriteriaSideSerializerMixin,
    CriteriaEssentialSongsSerializerMixin,
    AppInputSerializer,
    serializers.ModelSerializer,
):
    tracks_count = serializers.IntegerField()
    parent = CriteriaMinimumSerializer()
    ascendants = CriteriaLineageRelWithoutDescendantSerializer(source=ModelFields.ASCENDANTS_RELS, many=True)
    root = CriteriaMinimumSerializer()  # type: ignore
    children = CriteriaMinimumSerializer(many=True)
    criteria_playlist = CriteriaPlaylistMinimumSerializer()
    name = AppCharField(source=ModelFields.NAME_INTERNAL)
    wikidata_id = serializers.SerializerMethodField()

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        queryset = queryset.select_related(f"{prefix}{ModelFields.PARENT}", f"{prefix}{ModelFields.ROOT}")
        queryset = CriteriaPlaylistMinimumSerializer.setup_queryset(
            queryset, prefix=f"{prefix}{ModelFields.CRITERIA_PLAYLIST}__"
        )
        return queryset.prefetch_related(
            Prefetch(
                f"{prefix}{ModelFields.ASCENDANTS_RELS}",
                CriteriaLineageRel.objects.select_related(LineageFields.ASCENDANT),
            ),
            f"{prefix}{ModelFields.CHILDREN}",
            f"{prefix}{TrackFields.GENRE}__{CriteriaOutputFieldKey.ESSENTIAL_SONGS}__{TrackFields.ARTISTS}",
        )

    def get_wikidata_id(self, obj) -> str | None:
        # `wikidata_id` lives on the `Genre` subtype; `obj` may be the base `Criteria` row, and a tag has no genre.
        genre = getattr(obj, "genre", None)
        return genre.wikidata_id if genre else None

    class Meta:
        model = Criteria
        fields = [
            CriteriaOutputFieldKey.UUID.value,
            CriteriaOutputFieldKey.NAME.value,
            CriteriaOutputFieldKey.WIKIDATA_ID.value,
            CriteriaOutputFieldKey.SUMMARY.value,
            CriteriaOutputFieldKey.PARENT.value,
            CriteriaOutputFieldKey.ASCENDANTS.value,
            CriteriaOutputFieldKey.ROOT.value,
            CriteriaOutputFieldKey.CHILDREN.value,
            CriteriaOutputFieldKey.CRITERIA_PLAYLIST.value,
            CriteriaOutputFieldKey.TRACKS_COUNT_PUBLIC.value,
            CriteriaOutputFieldKey.SIDE.value,
            CriteriaOutputFieldKey.ESSENTIAL_SONGS.value,
            CriteriaOutputFieldKey.CREATED_ON.value,
            CriteriaOutputFieldKey.UPDATED_ON.value,
        ]
