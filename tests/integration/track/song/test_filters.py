from urllib.parse import parse_qs, urlparse

from django.db import connection
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.track.YoutubeUnplayableReason import YoutubeUnplayableReason

from tests.utils.AppTestCase import AppTestCase
from tests.utils.song_graph import install_song_graph


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

    def _install_graph(self, extra=None, *, classifications=(), **kwargs):
        assignments = {self.rock: [self.matching_track], self.jazz: [self.other_track]}
        assignments.update(extra or {})
        return install_song_graph(assignments, classifications=classifications, **kwargs)

    def _list_uuids(self, **params):
        response = self.api_client.get(path=reverse(self.list_endpoint), data=params)
        assert response.status_code == status.HTTP_200_OK
        return {track["uuid"] for track in response.data["results"]}

    def test_filter_by_title(self):
        self._install_graph()
        assert self._list_uuids(title="comfortably") == {str(self.matching_track.uuid)}

    def test_filter_by_artists_name(self):
        self._install_graph()
        assert self._list_uuids(artists_name="pink floyd") == {str(self.matching_track.uuid)}

    def test_filter_by_artists_name_lists_a_song_once_when_several_artists_match(self):
        floyd_guest = self.model_fixture_factory.create_artist("Pink Floyd Guest")
        type(self.matching_track).objects.get(pk=self.matching_track.pk).artists.add(floyd_guest)
        self._install_graph()
        for params in ({}, {"withTotal": "true"}, {"page": 1}):
            response = self.api_client.get(
                path=reverse(self.list_endpoint), data={"artists_name": "pink floyd", **params}
            )
            assert response.status_code == status.HTTP_200_OK
            assert [t["uuid"] for t in response.data["results"]] == [str(self.matching_track.uuid)]
            if params:
                assert response.data["overallTotal"] == 1

    def test_filter_by_album_name(self):
        self._install_graph()
        assert self._list_uuids(album_name="the wall") == {str(self.matching_track.uuid)}

    def test_filter_by_genre_name(self):
        self._install_graph()
        type(self.matching_track).objects.filter(pk=self.matching_track.pk).update(genre=self.jazz)
        assert self._list_uuids(genre_name="rock") == {str(self.matching_track.uuid)}

    def test_filter_by_genre_covers_primary_descendants_regardless_of_video(self):
        self._install_graph()
        prog = self.model_fixture_factory.create_genre("Progressive Rock", parent=self.rock)
        prog_track = self.model_fixture_factory.create_song(title="Echoes", genre=prog, youtube_video_id=None)

        self._install_graph({prog: [prog_track]}, classifications=[(prog, self.rock)])

        assert self._list_uuids(genre=str(self.rock.uuid)) == {str(self.matching_track.uuid), str(prog_track.uuid)}
        assert self._list_uuids(genre=str(prog.uuid)) == {str(prog_track.uuid)}

    def test_filter_by_language(self):
        self._install_graph()
        assert self._list_uuids(language="en") == {str(self.matching_track.uuid)}

    def test_filter_with_no_match_then_empty(self):
        self._install_graph()
        assert self._list_uuids(title="nonexistent") == set()

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
        install_song_graph(
            {self.rock: list(type(self.matching_track).objects.filter(genre=self.rock)), self.jazz: [self.other_track]}
        )

    def test_ordering_by_title_and_album_year(self):
        self._install_graph()
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
        self._install_graph()
        self._with_years()
        Song = type(self.matching_track)

        for mode in ({}, {"page": 1}, {"page": 1, "withTotal": "false"}):
            for ordering in ("title", "-title", "albumYear", "-albumYear", None):
                params = {**mode, **({"ordering": ordering} if ordering else {})}
                full = self._titles(**params)
                for index, title in enumerate(full):
                    anchor = str(Song.objects.get(title=title).pk)
                    assert self._titles(**params, **{"from": anchor}) == full[index:], (mode, ordering, title)

    def test_without_total_defaults_to_pk_order(self):
        self._install_graph()
        self._with_years()
        Song = type(self.matching_track)
        expected = [song.title for song in Song.objects.order_by("pk")]

        for mode in ({}, {"page": 1, "withTotal": "false"}):
            assert self._titles(**mode) == expected
            assert self._titles(**mode, ordering="title") == sorted(expected)

    def _walk(self, **params):
        response = self.api_client.get(path=reverse(self.list_endpoint), data={**params, "pageSize": 2})
        seen = []
        while True:
            assert response.status_code == status.HTTP_200_OK, response.data
            seen += [track["title"] for track in response.data["results"]]
            if response.data["next"] is None:
                return seen
            assert "from=" not in response.data["next"]
            response = self.api_client.get(response.data["next"])

    def test_cursor_pages_walk_every_ordering_without_gaps_or_repeats(self):
        self._install_graph()
        self._with_years()
        Song = type(self.matching_track)

        for ordering in ("title", "-title", "albumYear", "-albumYear", None):
            params = {"ordering": ordering} if ordering else {}
            full = self._titles(**params)
            assert self._walk(**params) == full, ordering
            anchor = str(Song.objects.get(title=full[2]).pk)
            assert self._walk(**params, **{"from": anchor}) == full[2:], ordering

    def test_cursor_total_is_counted_only_on_request(self):
        self._install_graph()
        path = reverse(self.list_endpoint)

        statements: list[str] = []

        def record(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(record):
            uncounted = self.api_client.get(path=path, data={"pageSize": 1})
        uncounted_queries = len(statements)
        with connection.execute_wrapper(record):
            counted = self.api_client.get(path=path, data={"pageSize": 1, "withTotal": "true"})
        counted_queries = len(statements) - uncounted_queries
        second = self.api_client.get(counted.data["next"])

        assert uncounted.data["overallTotal"] is None
        assert counted.data["overallTotal"] == second.data["overallTotal"] == 2
        assert counted_queries == uncounted_queries + 1

    def test_invalid_total_then_400(self):
        self._install_graph()
        response = self.api_client.get(path=reverse(self.list_endpoint), data={"withTotal": "maybe"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cursor_with_from_or_another_ordering_then_400(self):
        self._install_graph()
        path = reverse(self.list_endpoint)
        first = self.api_client.get(path=path, data={"ordering": "title", "pageSize": 1})
        cursor = parse_qs(urlparse(first.data["next"]).query)["cursor"][0]

        for params in (
            {"ordering": "title", "cursor": cursor, "from": str(self.matching_track.pk)},
            {"ordering": "-albumYear", "cursor": cursor},
            {"cursor": cursor},
        ):
            response = self.api_client.get(path=path, data=params)
            assert response.status_code == status.HTTP_400_BAD_REQUEST, params

    def test_from_anchor_filtered_out_then_404(self):
        self._install_graph()
        unplayable = self.model_fixture_factory.create_song(title="Gone", genre=self.rock, youtube_video_id=None)

        self._install_graph({self.rock: [self.matching_track, unplayable]})
        response = self.api_client.get(
            path=reverse(self.list_endpoint), data={"playable": "true", "from": str(unplayable.pk)}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_from_not_a_uuid_then_400(self):
        self._install_graph()
        response = self.api_client.get(path=reverse(self.list_endpoint), data={"from": "nope"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_filter_playable(self):
        self._install_graph()
        factory = self.model_fixture_factory
        no_video = factory.create_song(title="No Video", genre=self.rock, youtube_video_id=None)
        unplayable = factory.create_song(
            title="Private", genre=self.rock, youtube_unplayable_reason=YoutubeUnplayableReason.values[0]
        )
        self._install_graph({self.rock: [self.matching_track, no_video, unplayable]})
        playable = {str(self.matching_track.uuid), str(self.other_track.uuid)}

        assert self._list_uuids(playable="true") == playable
        assert self._list_uuids(playable="false") == {str(no_video.uuid), str(unplayable.uuid)}

    def test_unknown_ordering_then_400(self):
        self._install_graph()
        response = self.api_client.get(path=reverse(self.list_endpoint), data={"ordering": "genre"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_genre_coverage_selects_exact_or_primary_descendants(self):
        self._install_graph()
        child = self.model_fixture_factory.create_genre("Progressive Rock", parent=self.rock)
        child_song = self.model_fixture_factory.create_song(title="Echoes", genre=child, youtube_video_id=None)
        self._install_graph({child: [child_song]}, classifications=[(child, self.rock)])
        genre = str(self.rock.uuid)
        assert self._list_uuids(genre=genre, coverage="genre_only") == {str(self.matching_track.uuid)}
        assert self._list_uuids(genre=genre, coverage="genre_and_subgenres") == {
            str(self.matching_track.uuid),
            str(child_song.uuid),
        }
        assert self.api_client.get(reverse(self.list_endpoint), {"coverage": "genre_only"}).status_code == 400
        assert self.api_client.get(reverse(self.list_endpoint), {"genre": genre, "coverage": "bad"}).status_code == 400
        assert self.api_client.get(reverse(self.list_endpoint), {"genre": genre, "coverage": ""}).status_code == 400

    def test_genre_subgenre_scopes_and_validation(self):
        self._install_graph()
        regional = self.model_fixture_factory.create_genre("Regional rock", tree_name="regional")
        regional_song = self.model_fixture_factory.create_song("Regional song", genre=regional)
        region = self.model_fixture_factory.create_genre("Region")
        self._install_graph(
            {regional: [regional_song], region: []},
            relations=[(regional, self.rock, "classification"), (regional, region, "regional_membership")],
            node_overrides={region: {"kind": "overview"}},
        )
        genre = str(self.rock.uuid)
        direct = str(self.matching_track.uuid)
        assert self._list_uuids(genre=genre) == {direct}
        assert self._list_uuids(genre=genre, subgenres="regional") == {direct, str(regional_song.uuid)}
        assert self._list_uuids(genre=genre, subgenres="all") == {direct, str(regional_song.uuid)}
        assert self._list_uuids(genre=genre, subgenres="restricted") == {direct}
        assert self._list_uuids(genre=genre, subgenres="expressions") == {str(regional_song.uuid)}
        assert self._list_uuids(genre=genre, subgenres="extended") == {direct, str(regional_song.uuid)}
        assert self._list_uuids(genre=str(regional.uuid)) == {str(regional_song.uuid)}
        for params in (
            {"subgenres": "all"},
            {"genre": genre, "coverage": "genre_only", "subgenres": "all"},
            {"genre": genre, "coverage": "genre_only", "subgenres": "expressions"},
            {"genre": genre, "subgenres": "invalid"},
            {"genre": str(regional.uuid), "subgenres": "canonical"},
        ):
            assert self.api_client.get(reverse(self.list_endpoint), params).status_code == 400
