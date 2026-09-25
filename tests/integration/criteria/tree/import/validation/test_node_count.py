import time

import pytest
from django.conf import settings
from rest_framework import status
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestNodeCount(GenreTestCase):
    def test_no_data_then_400_bad_request(self):
        response = self._post_genres_tree_import(data={Fields.TREE: None})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["field"] == Fields.TREE
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.REQUIRED

    def test_empty_then_400_bad_request(self):
        response = self._post_genres_tree_import(data={Fields.TREE: []})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["field"] == Fields.TREE
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.REQUIRED

    @pytest.mark.slow
    def test_one_too_large_then_400_bad_request(self):
        root = {Fields.NAME_PUBLIC: "Root1", Fields.CHILDREN: []}
        for i in range(settings.CRITERIA_TREE_IMPORT_MAX_TOTAL_COUNT - 1):
            root[Fields.CHILDREN].append({Fields.NAME_PUBLIC: f"Child {i}", Fields.CHILDREN: []})

        data = [root, {Fields.NAME_PUBLIC: "Root2", Fields.CHILDREN: []}]
        response = self._post_genres_tree_import(data={Fields.TREE: data})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["field"] == Fields.TREE
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.TREE_TOO_LARGE

    @pytest.mark.slow
    def test_multiple_with_one_too_large_then_400_bad_request(self):
        data = [
            {
                Fields.NAME_PUBLIC: "Rock",
                Fields.CHILDREN: [
                    {Fields.NAME_PUBLIC: f"Child {i}", Fields.CHILDREN: []}
                    for i in range(settings.CRITERIA_TREE_IMPORT_MAX_TOTAL_COUNT - 1)
                ],
            }
        ]

        data[0][Fields.CHILDREN].append({Fields.NAME_PUBLIC: "Extra Child", Fields.CHILDREN: []})

        response = self._post_genres_tree_import(data={Fields.TREE: data})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["field"] == Fields.TREE
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.TREE_TOO_LARGE

    @pytest.mark.slow
    def test_largest_then_ok(self):
        root = {Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
        for i in range(3000):
            root[Fields.CHILDREN].append({Fields.NAME_PUBLIC: f"Child {i}", Fields.CHILDREN: []})

        data = [root]
        response = self._post_genres_tree_import(data={Fields.TREE: data})
        assert response.status_code == status.HTTP_201_CREATED
        genres_count = Genre.objects.filter(user=None).count()
        assert genres_count == 3001

    @pytest.mark.slow
    def test_deep_tree_completes_well_under_timeout(self):
        # Regression guard for the gunicorn worker timeout on deep (not just wide) genre trees --
        # test_largest_then_ok above is flat/shallow and wouldn't catch a depth-driven blowup in
        # tree-node validation. Shape mirrors the production genre taxonomy: real depth (60 levels)
        # with a couple of siblings at each level, totalling ~1700 nodes -- close to the actual
        # canonical tree's node count.
        depth = 60
        siblings_per_level = 2
        node = {Fields.NAME_PUBLIC: "leaf-0", Fields.CHILDREN: []}
        node_count = 1
        for level in range(1, depth):
            children = [node]
            for sibling in range(siblings_per_level - 1):
                children.append({Fields.NAME_PUBLIC: f"leaf-{level}-{sibling}", Fields.CHILDREN: []})
                node_count += 1
            node = {Fields.NAME_PUBLIC: f"node-{level}", Fields.CHILDREN: children}
            node_count += 1

        root = {Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: [node]}
        node_count += 1

        start = time.monotonic()
        response = self._post_genres_tree_import(data={Fields.TREE: [root]})
        elapsed = time.monotonic() - start

        assert response.status_code == status.HTTP_201_CREATED
        assert Genre.objects.filter(user=None).count() == node_count
        # Gunicorn's default worker timeout is 120s; this leaves generous headroom as the real
        # tree grows further while still catching a depth-driven regression.
        assert elapsed < 30
