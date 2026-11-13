from rest_framework import serializers
from the_music_tree_api_kit.commons_image.helpers import commons_image_representation


class CriteriaGenreTextSerializerMixin:
    """
    `description`, `summary_source_url` and `image` live on the concrete `Genre` subtype, reached from a base
    `Criteria` instance via the reverse `genre` one-to-one accessor; `None` for non-genre criteria.
    """

    description = serializers.SerializerMethodField()
    summary_source_url = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    _declared_fields = {"description": description, "summary_source_url": summary_source_url, "image": image}

    def get_description(self, obj) -> str | None:
        return getattr(getattr(obj, "genre", None), "description", None)

    def get_summary_source_url(self, obj) -> str | None:
        return getattr(getattr(obj, "genre", None), "summary_source_url", None)

    def get_image(self, obj) -> dict | None:
        genre = getattr(obj, "genre", None)
        return None if genre is None else commons_image_representation(genre)
