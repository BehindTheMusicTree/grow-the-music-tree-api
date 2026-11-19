import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

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


def explain_page_queries(artist, ordering, cursor, size):
    """EXPLAIN every grow_artist_song SELECT that `page` runs, with sequential scans and sorts discouraged.

    On a handful of rows the planner legitimately prefers a bitmap scan plus a sort on cost. Disabling sorts keeps one
    only when no index delivers the requested order, so a `Sort` left in the plan means the query and the index disagree.
    """
    with CaptureQueriesContext(connection) as queries:
        artist_song_page.page(artist, ordering, cursor, size)
    plans = []
    with connection.cursor() as db:
        db.execute("SET LOCAL enable_seqscan = off")
        db.execute("SET LOCAL enable_sort = off")
        for query in queries.captured_queries:
            if query["sql"].lstrip().upper().startswith("SELECT") and "grow_artist_song" in query["sql"]:
                db.execute(f"EXPLAIN (COSTS OFF) {query['sql']}")
                plans.append("\n".join(row[0] for row in db.fetchall()))
    return plans


@pytest.mark.postgres
@pytest.mark.django_db
@pytest.mark.parametrize("from_cursor", [False, True])
def test_year_pages_are_ordered_scans_of_the_year_index_without_a_sort(from_cursor):
    years = [2010, 1990, None, 2000, 1990, None, 2010, 1985]
    artist = seed([(f"t{i}", year) for i, year in enumerate(years)])
    cursor = artist_song_page.page(artist, "-albumYear", None, 2)[-1][1] if from_cursor else None

    # A size larger than the dated rows left makes the undated tail query run too.
    plans = explain_page_queries(artist, "-albumYear", cursor, 50)

    dated, undated = plans if len(plans) == 2 else (None, None)
    assert dated, plans
    assert "grow_artist_song_year_idx" in dated, dated
    # The undated tail may be served by the primary key on a table this small; it only has to need no sort.
    for plan in (dated, undated):
        assert "Sort" not in plan, plan


@pytest.mark.postgres
@pytest.mark.django_db
def test_title_page_is_an_ordered_scan_of_the_title_index_without_a_sort():
    artist = seed([(title, None) for title in TITLES])
    cursor = artist_song_page.page(artist, "title", None, 2)[-1][1]

    plans = explain_page_queries(artist, "title", cursor, 50)

    assert len(plans) == 1, plans
    assert "grow_artist_song_title_idx" in plans[0], plans[0]
    assert "Sort" not in plans[0], plans[0]
