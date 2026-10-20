from rest_framework import serializers


class CriteriaGenreTextSerializerMixin:
    """
    `description` and `summary_source_url` live on the concrete `Genre` subtype, reached from a base
    `Criteria` instance via the reverse `genre` one-to-one accessor; `None` for non-genre criteria.
    """

    description = serializers.SerializerMethodField()
    summary_source_url = serializers.SerializerMethodField()
    _declared_fields = {"description": description, "summary_source_url": summary_source_url}

    def get_description(self, obj) -> str | None:
        return getattr(getattr(obj, "genre", None), "description", None)

    def get_summary_source_url(self, obj) -> str | None:
        return getattr(getattr(obj, "genre", None), "summary_source_url", None)
