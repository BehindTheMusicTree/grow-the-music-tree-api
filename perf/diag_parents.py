"""TEMPORARY diagnostic for PR #468 (coverage+subgenres regression). Run explicitly by scripts/perf_ab.sh; remove before merge."""

import os
import time
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from grow.genre_music.selection import SubgenreScope, genre_graph, selected_genres
from grow.genre_music.selection_query import selected_genres_query
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from perf.conftest import largest_genre_playlist
from tests.utils.AppApiClient import AppApiClient

VIEWER_TOKEN = "perf-viewer-token"
HEADERS = {"HTTP_X_VIEWER_CONTEXT_TOKEN": VIEWER_TOKEN, "HTTP_X_VIEWER_COUNTRY": "FR"}


def _scalar(sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


def _explain(sql: str, params=()) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", params)
        return "\n".join(row[0] for row in cursor.fetchall())


@pytest.mark.django_db
def test_diag_parents(settings):
    settings.VIEWER_CONTEXT_TOKEN = VIEWER_TOKEN
    out: list[str] = []
    additional = Criteria.additional_primary_parents.through._meta.db_table
    secondary = Criteria.secondary_parents.through._meta.db_table
    playlist = largest_genre_playlist()
    genre = playlist.criteria
    out.append(f"genres={Genre.objects.filter(user__isnull=True).count()}")
    out.append(f"direct_edges={Genre.objects.filter(user__isnull=True, parent__isnull=False).count()}")
    out.append(f"additional_primary_edges={_scalar(f'SELECT count(*) FROM {additional}')}")
    out.append(f"secondary_edges={_scalar(f'SELECT count(*) FROM {secondary}')}")
    out.append(f"largest_genre={genre.name} tree={genre.tree_name} wikidata={getattr(genre, 'wikidata_id', None)}")

    trees, edges = genre_graph()
    selection = selected_genres(genre.pk, trees, edges, SubgenreScope.ALL)
    out.append(f"python_selection_size={len(selection)} snapshot_edges={len(edges)}")

    closure = selected_genres_query(genre.pk, genre.tree_name, SubgenreScope.ALL, using=connection.alias)
    closure_sql, closure_params = closure.sql, closure.params
    out.append(f"sql_selection_size={_scalar(f'SELECT count(*) FROM ({closure_sql}) s', closure_params)}")
    out.append(f"sql_selection_distinct={_scalar(f'SELECT count(DISTINCT id) FROM ({closure_sql}) s', closure_params)}")
    out.append("\n=== EXPLAIN closure alone ===")
    out.append(_explain(f"SELECT count(*) FROM ({closure_sql}) s", closure_params))

    client = AppApiClient()
    path = reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid})
    params = {"page_size": 100, "coverage": "genre_and_subgenres", "subgenres": "all"}
    client.get(path, params, **HEADERS)
    start = time.perf_counter()
    with CaptureQueriesContext(connection) as queries:
        response = client.get(path, params, **HEADERS)
    out.append(f"\nrequest status={response.status_code} total_ms={(time.perf_counter() - start) * 1000:.1f}")
    for index, query in enumerate(queries.captured_queries):
        out.append(f"\n=== query {index} ({query['time']}s) ===\n{query['sql']}\n--- plan ---")
        out.append(_explain(query["sql"]))

    text = "\n".join(out)
    print(text)
    target = os.environ.get("PERF_DIAG_OUT")
    if target:
        Path(target).write_text(text)
