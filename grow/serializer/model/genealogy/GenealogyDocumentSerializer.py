from rest_framework import serializers


class TraditionSerializer(serializers.Serializer):
    wikidata_id = serializers.CharField()
    label = serializers.CharField()
    start = serializers.IntegerField(allow_null=True)
    end = serializers.IntegerField(allow_null=True)
    anchor_id = serializers.CharField(allow_null=True)
    in_canonical_tree = serializers.BooleanField()


class GenealogyDocumentSerializer(serializers.Serializer):
    """Shape check of the pipeline's `4_genealogy.json`, in snake_case; the stored document keeps its own keys."""

    columns = serializers.ListField(child=serializers.DictField())
    bands = serializers.ListField(child=serializers.DictField())
    successions = serializers.ListField(child=serializers.DictField())
    traditions = TraditionSerializer(many=True)
    tradition_links = serializers.ListField(child=serializers.DictField())
