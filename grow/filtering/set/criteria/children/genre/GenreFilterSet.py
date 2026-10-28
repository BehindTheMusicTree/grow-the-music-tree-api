from django_filters import CharFilter, ChoiceFilter
from the_music_tree_api_kit.filtering.filter.StrictBooleanFilter import StrictBooleanFilter
from the_music_tree_genre_kit.criteria.children.genre.CriteriaScene import CriteriaScene
from the_music_tree_genre_kit.filtering.set.criteria.CriteriaFilterSet import CriteriaFilterSet


class GenreFilterSet(CriteriaFilterSet):
    wikidata_id = CharFilter(field_name="wikidata_id")
    has_name_conflict = StrictBooleanFilter(field_name="has_name_conflict")
    is_unaccepted_root = StrictBooleanFilter(field_name="is_unaccepted_root")
    is_umbrella = StrictBooleanFilter(field_name="is_umbrella")
    scene = ChoiceFilter(field_name="scene", choices=CriteriaScene.choices)

    class Meta(CriteriaFilterSet.Meta):
        fields = [
            *CriteriaFilterSet.Meta.fields,
            "wikidata_id",
            "has_name_conflict",
            "is_unaccepted_root",
            "is_umbrella",
            "scene",
        ]
