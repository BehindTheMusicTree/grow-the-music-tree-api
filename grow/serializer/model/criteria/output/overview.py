from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.serializer.model.criteria.output.side import CriteriaSideSerializerMixin

from grow.model.criteria.Criteria import Criteria
from grow.model.criteria.Fields import Fields as ModelFields

from .CriteriaOutputFieldKey import CriteriaOutputFieldKey
from .essential_tracks import CriteriaEssentialTracksSerializerMixin


class CriteriaOverviewSerializer(
    CriteriaSideSerializerMixin, CriteriaEssentialTracksSerializerMixin, AppInputSerializer, serializers.ModelSerializer
):
    name = AppCharField(source=ModelFields.NAME_INTERNAL)

    class Meta:
        model = Criteria
        fields = [
            CriteriaOutputFieldKey.UUID.value,
            CriteriaOutputFieldKey.NAME.value,
            CriteriaOutputFieldKey.SUMMARY.value,
            CriteriaOutputFieldKey.SIDE.value,
            CriteriaOutputFieldKey.ESSENTIAL_TRACKS.value,
        ]
