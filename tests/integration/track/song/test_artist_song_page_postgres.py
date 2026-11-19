import uuid

import pytest

from grow.artist_song import page as artist_song_page
from grow.model.artist_song.ArtistSong import ArtistSong

TITLES = ["b", "B", "a", "A", "é", "e", "Z", "z", "same", "same", "same", "10", "2", "_x", "", "ß"]


def seed(rows):
    artist = uuid.uuid4()
    ArtistSong.objects.bulk_create(
        ArtistSong(artist_id=artist, song_id=uuid.uuid4(), title=title, album_year=year) for title, year in rows
    )
    return artist


def walk(artist, ordering, size):
    seen, cursor = [], None
    while True:
        found = artist_song_page.page(artist, ordering, cursor, size + 1)
        seen += found[:size]
        if len(found) <= size:
            return seen
        cursor = found[size - 1][1]


@pytest.mark.postgres
@pytest.mark.django_db
@pytest.mark.parametrize("size", [1, 3, 100])
def test_title_walk_matches_the_index_order_exactly(size):
    artist = seed([(title, None) for title in TITLES])
    expected = list(
        ArtistSong.objects.filter(artist_id=artist).order_by("title", "song_id").values_list("song_id", flat=True)
    )

    assert [song_id for song_id, _ in walk(artist, "title", size)] == expected


@pytest.mark.postgres
@pytest.mark.django_db
@pytest.mark.parametrize("size", [1, 2, 100])
def test_year_walk_is_descending_years_then_undated_without_gaps_or_repeats(size):
    years = [2010, 1990, None, 2000, 1990, None, 2010, 1985]
    artist = seed([(f"t{i}", year) for i, year in enumerate(years)])

    seen = walk(artist, "-albumYear", size)

    ids = [song_id for song_id, _ in seen]
    assert len(ids) == len(set(ids)) == len(years)
    keys = [cursor.key for _, cursor in seen]
    assert keys == [2010, 2010, 2000, 1990, 1990, 1985, None, None]
    expected_ties = list(
        ArtistSong.objects.filter(artist_id=artist, album_year=1990)
        .order_by("-song_id")
        .values_list("song_id", flat=True)
    )
    assert [song_id for song_id, cursor in seen if cursor.key == 1990] == expected_ties
