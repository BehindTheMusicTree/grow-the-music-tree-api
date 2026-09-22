import pytest
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_create_tag_with_side_raises_type_error(self):
        # `side` (genre-kit v0.14.0) moved off the shared `Criteria` table onto the
        # `Genre` MTI subtype only -- `Tag` (a `Criteria` proxy) has no such column at
        # all, so passing it is now a plain unexpected-keyword-argument `TypeError`
        # rather than the old runtime `AppValidationException`/DEPENDENCY_MISSING check.
        # "side is genre-only" is enforced by the schema now, not by application code.
        with pytest.raises(TypeError):
            self.model_fixture_factory.create_tag("Instrumental", side=CriteriaSide.POP)
