import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from rest_framework import status
from the_music_tree_genre_kit.view.viewset.genre.GenreSeedTreeMixin import GenreSeedTreeMixin

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestLoadSeedMainstreamPopRoot(GenreTestCase):
    def test_load_seed_fails_when_fixture_has_no_mainstream_pop_root(self):
        with open(settings.DATA_DIR / "prototype_genre_tree.json") as f:
            data = json.load(f)
        data["tree"] = [node for node in data["tree"] if node["name"] != "Mainstream Pop"]

        with TemporaryDirectory() as tmp_dir:
            tree_path = Path(tmp_dir) / "tree_without_mainstream_pop.json"
            tree_path.write_text(json.dumps(data))

            with patch.object(GenreSeedTreeMixin, "get_seed_tree_data_path", return_value=tree_path):
                response = self._post_genres_tree_load_seed()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Genre.objects.filter(user=None).exists()
        assert not YoutubeTrack.objects.filter(user=None).exists()
