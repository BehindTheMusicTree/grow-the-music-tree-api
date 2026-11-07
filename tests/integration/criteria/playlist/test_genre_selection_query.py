import pytest
from django.db import connection
from django.db.models import F

from grow.genre_music.selection import SubgenreScope
from grow.genre_music.selection_query import selected_genres_query
from grow.model.criteria.children.genre.Genre import Genre
from grow.query_expressions import InSubquery
from tests.utils.ModelFixtureFactory import ModelFixtureFactory


@pytest.mark.django_db
def test_sql_selection_preserves_primary_paths_and_tree_boundaries(django_assert_num_queries):
    factory = ModelFixtureFactory(default_user=None)
    root = factory.create_genre("Selection root")
    canonical = factory.create_genre("Canonical child", parent=root)
    regional = factory.create_genre("Regional child", tree_name="regional")
    regional.additional_primary_parents.add(root)
    diamond = factory.create_genre("Diamond", tree_name="regional", parent=regional)
    diamond.additional_primary_parents.add(canonical)
    hidden = factory.create_genre("Canonical behind regional")
    Genre.objects.filter(pk=hidden.pk).update(parent_id=regional.pk)
    secondary = factory.create_genre("Secondary only")
    secondary.secondary_parents.add(root)
    expected = {
        SubgenreScope.CANONICAL: {root.pk, canonical.pk},
        SubgenreScope.REGIONAL: {root.pk, regional.pk, diamond.pk},
        SubgenreScope.ALL: {root.pk, canonical.pk, regional.pk, diamond.pk},
    }
    for scope, ids in expected.items():
        query = selected_genres_query(root.pk, "canonical", scope, using=connection.alias)
        with django_assert_num_queries(1):
            result = list(Genre.objects.filter(InSubquery(F("pk"), query)).values_list("pk", flat=True))
        assert set(result) == ids
        assert len(result) == len(ids)

    query = selected_genres_query(regional.pk, "regional", SubgenreScope.ALL, using=connection.alias)
    assert set(Genre.objects.filter(InSubquery(F("pk"), query)).values_list("pk", flat=True)) == {
        regional.pk,
        diamond.pk,
        hidden.pk,
    }
