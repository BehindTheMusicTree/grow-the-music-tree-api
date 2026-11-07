from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCriteriaDetail(GenreTestCase):
    def test_detail_queries_and_fields(self):
        root = self.model_fixture_factory.create_genre("Root")
        small = self.model_fixture_factory.create_genre("Small", parent=root)
        parent = self.model_fixture_factory.create_genre("Parent", parent=root)
        large = self.model_fixture_factory.create_genre("Large", parent=parent)
        self.model_fixture_factory.create_genre("Small child", parent=small)
        for index in range(4):
            child = self.model_fixture_factory.create_genre(f"Child {index}", parent=large)
            self.model_fixture_factory.create_genre(f"Grandchild {index}", parent=child)
        for genre, count in ((small, 1), (large, 4)):
            for index in range(count):
                song = self.model_fixture_factory.create_song(f"{genre.name} {index}", genre=genre)
                song.artists.add(self.model_fixture_factory.create_artist(f"{genre.name} artist {index}"))
                genre.essential_songs.add(song)

        def get(genre):
            return self.api_client.get(reverse("genre-detail", kwargs={"pk": genre.uuid}))

        with CaptureQueriesContext(connection) as small_queries:
            small_response = get(small)
        with CaptureQueriesContext(connection) as large_queries:
            response = get(large)
        assert small_response.status_code == response.status_code == 200
        assert len(small_queries) == len(large_queries)
        body = response.json()
        assert "tracks" not in body and "descendants" not in body
        assert body["tracksCount"] == 4
        assert {rel["ascendant"]["name"] for rel in body["ascendants"]} == {"Root", "Parent"}
        assert {child["name"] for child in body["children"]} == {f"Child {index}" for index in range(4)}
        assert len(body["essentialSongs"]) == 4

    def test_catalogue_pair_includes_primary_descendants(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        self.model_fixture_factory.create_song("Direct", genre=parent, youtube_video_id=None)
        self.model_fixture_factory.create_song("Child song", genre=child)

        response = self.api_client.get(reverse("genre-detail", kwargs={"pk": parent.uuid}))

        assert response.status_code == 200
        assert response.json()["catalogue"] == {
            "genreOnlyTracksCount": 1,
            "genreAndSubgenresTracksCount": {"canonical": 2, "regional": 1, "all": 2},
        }
        assert response.json()["tracksCount"] == 2

    def test_playlist_summary_counts_actual_members_by_scope(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        regional = self.model_fixture_factory.create_genre("Regional", tree_name="regional")
        regional.additional_primary_parents.add(parent)
        direct = self.model_fixture_factory.create_song("Direct", genre=parent)
        child_song = self.model_fixture_factory.create_song("Child song", genre=child)
        regional_song = self.model_fixture_factory.create_song("Regional song", genre=regional)
        playlist = GenrePlaylist.objects.get(criteria=parent)
        TrackPlaylistRel.objects.filter(playlist=playlist, track=child_song).delete()
        TrackPlaylistRel.objects.get_or_create(playlist=playlist, track=regional_song, defaults={"user": None})

        response = self.api_client.get(reverse("genre-detail", kwargs={"pk": parent.uuid}))

        assert response.status_code == 200
        summary = response.json()["criteriaPlaylist"]
        assert summary["uuid"] == str(playlist.uuid)
        assert summary["genreOnlyTracksCount"] == 1
        assert summary["genreAndSubgenresTracksCount"] == {"canonical": 1, "regional": 2, "all": 2}
        assert TrackPlaylistRel.objects.filter(playlist=playlist, track=direct).exists()

    def test_child_only_catalogue_matches_tree(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        self.model_fixture_factory.create_song("Child song", genre=child, youtube_video_id=None)

        detail = self.api_client.get(reverse("genre-detail", kwargs={"pk": parent.uuid})).json()
        tree = self.api_client.get(reverse("genre-playlist-list") + "tree/", {"tree_name": "canonical"}).json()
        tree_parent = next(row for row in tree if row["name"] == "Parent")
        assert (
            detail["catalogue"]
            == tree_parent["catalogue"]
            == {
                "genreOnlyTracksCount": 0,
                "genreAndSubgenresTracksCount": {"canonical": 1, "regional": 0, "all": 1},
            }
        )

    def test_catalogue_tree_includes_descendants_from_another_tree(self):
        parent = self.model_fixture_factory.create_genre("Canonical")
        regional = self.model_fixture_factory.create_genre("Regional", tree_name="regional")
        regional.additional_primary_parents.add(parent)
        CriteriaLineageRel.objects.create(descendant=regional, ascendant=parent, degree=1)
        self.model_fixture_factory.create_song("Song", genre=regional)

        detail = self.api_client.get(reverse("genre-detail", kwargs={"pk": parent.uuid})).json()
        tree = self.api_client.get(reverse("genre-playlist-list") + "tree/", {"tree_name": "canonical"}).json()
        tree_parent = next(row for row in tree if row["name"] == "Canonical")
        assert (
            detail["catalogue"]
            == tree_parent["catalogue"]
            == {
                "genreOnlyTracksCount": 0,
                "genreAndSubgenresTracksCount": {"canonical": 0, "regional": 1, "all": 1},
            }
        )

    def test_scoped_catalogue_includes_direct_and_regional_descendants(self):
        parent = self.model_fixture_factory.create_genre("Canonical parent")
        child = self.model_fixture_factory.create_genre("Canonical child", parent=parent)
        regional = self.model_fixture_factory.create_genre("Regional child", tree_name="regional")
        regional.additional_primary_parents.add(parent, child)
        regional_child = self.model_fixture_factory.create_genre(
            "Regional grandchild", parent=regional, tree_name="regional"
        )
        for genre in (parent, child, regional, regional_child):
            self.model_fixture_factory.create_song(f"Song {genre.name}", genre=genre)

        parent_counts = self.api_client.get(reverse("genre-detail", kwargs={"pk": parent.uuid})).json()["catalogue"]
        regional_counts = self.api_client.get(reverse("genre-detail", kwargs={"pk": regional.uuid})).json()["catalogue"]
        tree = self.api_client.get(reverse("genre-playlist-list") + "tree/", {"tree_name": "canonical"}).json()
        assert parent_counts == next(row for row in tree if row["name"] == parent.name)["catalogue"]
        assert parent_counts == {
            "genreOnlyTracksCount": 1,
            "genreAndSubgenresTracksCount": {"canonical": 2, "regional": 3, "all": 4},
        }
        assert regional_counts == {"genreOnlyTracksCount": 1, "genreAndSubgenresTracksCount": {"all": 2}}

    def test_tag_detail(self):
        tag = self.model_fixture_factory.create_tag("Live")
        response = self.api_client.get(reverse("tag-detail", kwargs={"pk": tag.uuid}))
        assert response.status_code == 200
        assert "catalogue" not in response.json()
        assert response.json()["essentialSongs"] == []
        assert response.json()["tracksCount"] == 0
        assert "tracks" not in response.json() and "descendants" not in response.json()

    def test_update_and_exclude_queries_do_not_depend_on_song_count(self):
        small = self.model_fixture_factory.create_genre("Small")
        large = self.model_fixture_factory.create_genre("Large")
        for genre, count in ((small, 1), (large, 4)):
            for index in range(count):
                song = self.model_fixture_factory.create_song(f"{genre.name} {index}", genre=genre)
                song.artists.add(self.model_fixture_factory.create_artist(f"{genre.name} artist {index}"))
                genre.essential_songs.add(song)
        with CaptureQueriesContext(connection) as small_queries:
            small_response = self._put_genre(small.uuid, {"summary": "Updated"})
        with CaptureQueriesContext(connection) as large_queries:
            large_response = self._put_genre(large.uuid, {"summary": "Updated"})
        assert small_response.status_code == large_response.status_code == 200
        assert len(small_queries) == len(large_queries)
        with CaptureQueriesContext(connection) as small_queries:
            small_response = self._post_genre_exclude(small.uuid)
        with CaptureQueriesContext(connection) as large_queries:
            large_response = self._post_genre_exclude(large.uuid)
        assert small_response.status_code == large_response.status_code == 200
        assert len(small_queries) == len(large_queries)
