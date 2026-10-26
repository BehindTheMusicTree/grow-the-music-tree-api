from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.track.YoutubeUnplayableReason import YoutubeUnplayableReason

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "song-list"

    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock")
        self.jazz = self.model_fixture_factory.create_genre("Jazz")
        self.pink_floyd = self.model_fixture_factory.create_artist("Pink Floyd")
        self.album = self.model_fixture_factory.create_album("The Wall")
        self.matching_track = self.model_fixture_factory.create_song(
            title="Comfortably Numb",
            genre=self.rock,
            artists=[self.pink_floyd],
            album=self.album,
            language="en",
        )
        self.other_track = self.model_fixture_factory.create_song(
            title="So What",
            genre=self.jazz,
            language="fr",
        )

    def _list_uuids(self, **params):
        response = self.api_client.get(path=reverse(self.list_endpoint), data=params)
        assert response.status_code == status.HTTP_200_OK
        return {track["uuid"] for track in response.data["results"]}

    def test_filter_by_title(self):
        assert self._list_uuids(title="comfortably") == {str(self.matching_track.uuid)}

    def test_filter_by_artists_name(self):
        assert self._list_uuids(artists_name="pink floyd") == {str(self.matching_track.uuid)}

    def test_filter_by_album_name(self):
        assert self._list_uuids(album_name="the wall") == {str(self.matching_track.uuid)}

    def test_filter_by_genre_name(self):
        assert self._list_uuids(genre_name="rock") == {str(self.matching_track.uuid)}

    def test_filter_by_genre_covers_primary_descendants_regardless_of_video(self):
        prog = self.model_fixture_factory.create_genre("Progressive Rock", parent=self.rock)
        prog_track = self.model_fixture_factory.create_song(title="Echoes", genre=prog, youtube_video_id=None)

        assert self._list_uuids(genre=str(self.rock.uuid)) == {str(self.matching_track.uuid), str(prog_track.uuid)}
        assert self._list_uuids(genre=str(prog.uuid)) == {str(prog_track.uuid)}

    def test_filter_by_language(self):
        assert self._list_uuids(language="en") == {str(self.matching_track.uuid)}

    def test_filter_with_no_match_then_empty(self):
        assert self._list_uuids(title="nonexistent") == set()

    def test_filter_by_artist_uuid(self):
        assert self._list_uuids(artist=str(self.pink_floyd.uuid)) == {str(self.matching_track.uuid)}

    def _titles(self, **params):
        response = self.api_client.get(path=reverse(self.list_endpoint), data=params)
        assert response.status_code == status.HTTP_200_OK, response.data
        return [track["title"] for track in response.data["results"]]

    def _with_years(self):
        """Echoes 1971 (album), Wish You Were Here 1975 (first release over its album's 2001), Comfortably Numb and
        Money tied on 1979; So What (no album), Bootleg (non-numeric album year) and Demo (non-four-digit "70") have none."""
        factory = self.model_fixture_factory
        type(self.album).objects.filter(pk=self.album.pk).update(year="1979")
        factory.create_song(title="Echoes", genre=self.rock, album=factory.create_album("Meddle", year="1971"))
        factory.create_song(
            title="Wish You Were Here",
            genre=self.rock,
            album=factory.create_album("Best Of", year="2001"),
            first_release_year=1975,
        )
        factory.create_song(title="Bootleg", genre=self.rock, album=factory.create_album("Live", year="c.70"))
        factory.create_song(title="Demo", genre=self.rock, album=factory.create_album("Demos", year="70"))
        factory.create_song(title="Money", genre=self.rock, album=self.album, first_release_year=1979)

    def test_ordering_by_title_and_album_year(self):
        self._with_years()
        Song = type(self.matching_track)

        def by_pk(*titles):  # pk tie-breaker
            return sorted(titles, key=lambda title: Song.objects.get(title=title).pk)

        tied_titles = by_pk("Comfortably Numb", "Money")
        no_year = by_pk("So What", "Bootleg", "Demo")

        assert self._titles(ordering="title") == [
            "Bootleg",
            "Comfortably Numb",
            "Demo",
            "Echoes",
            "Money",
            "So What",
            "Wish You Were Here",
        ]
        assert self._titles(ordering="-title")[0] == "Wish You Were Here"
        assert self._titles(ordering="albumYear") == ["Echoes", "Wish You Were Here", *tied_titles, *no_year]
        assert self._titles(ordering="-albumYear") == [
            *reversed(tied_titles),
            "Wish You Were Here",
            "Echoes",
            *reversed(no_year),
        ]

    def test_from_starts_at_the_anchor_in_the_active_ordering(self):
        self._with_years()
        Song = type(self.matching_track)

        for ordering in ("title", "-title", "albumYear", "-albumYear", None):
            params = {"ordering": ordering} if ordering else {}
            full = self._titles(**params)
            for index, title in enumerate(full):
                anchor = str(Song.objects.get(title=title).pk)
                assert self._titles(**params, **{"from": anchor}) == full[index:], (ordering, title)

    def test_from_anchor_filtered_out_then_404(self):
        unplayable = self.model_fixture_factory.create_song(title="Gone", genre=self.rock, youtube_video_id=None)

        response = self.api_client.get(
            path=reverse(self.list_endpoint), data={"playable": "true", "from": str(unplayable.pk)}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_from_not_a_uuid_then_400(self):
        response = self.api_client.get(path=reverse(self.list_endpoint), data={"from": "nope"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_filter_playable(self):
        factory = self.model_fixture_factory
        no_video = factory.create_song(title="No Video", genre=self.rock, youtube_video_id=None)
        unplayable = factory.create_song(
            title="Private", genre=self.rock, youtube_unplayable_reason=YoutubeUnplayableReason.values[0]
        )
        playable = {str(self.matching_track.uuid), str(self.other_track.uuid)}

        assert self._list_uuids(playable="true") == playable
        assert self._list_uuids(playable="false") == {str(no_video.uuid), str(unplayable.uuid)}

    def test_unknown_ordering_then_400(self):
        response = self.api_client.get(path=reverse(self.list_endpoint), data={"ordering": "genre"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
