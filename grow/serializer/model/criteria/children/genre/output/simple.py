from the_music_tree_genre_kit.serializer.model.criteria.output.simple import build_criteria_simple_serializer

from grow.model.criteria.children.genre.Genre import Genre

# Built for `Genre`, not `Criteria`: `side` is then read from the row itself rather than a per-row `genre` lookup.
_GenreBaseSimpleSerializer = build_criteria_simple_serializer(Genre)


class GenreSimpleSerializer(_GenreBaseSimpleSerializer):  # type: ignore[valid-type,misc]
    class Meta(_GenreBaseSimpleSerializer.Meta):  # type: ignore[name-defined]
        fields = [*_GenreBaseSimpleSerializer.Meta.fields, "has_name_conflict"]  # type: ignore[name-defined]
