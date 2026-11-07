import inspect
import re

import pytest

from grow.artist.bulk_import import merge as artist_merge
from grow.bulk_import.analyze import analyze_steps, tables
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.song_search import projection
from grow.track.bulk_import import merge as song_merge

WRITE = re.compile(r"\b(?:INSERT INTO|UPDATE|DELETE FROM)\s+(?!SET\b)(\w+)")


@pytest.mark.parametrize("module", [song_merge, artist_merge], ids=["songs", "artists"])
def test_merge_analyzes_every_table_it_writes(module):
    temp_tables = {name.strip() for name in module.TEMP_TABLES.split(",")}
    # The grow_song_search writes live in projection, which both merges call.
    source = inspect.getsource(module) + inspect.getsource(projection)
    written = set(WRITE.findall(source)) - temp_tables
    analyzed = set(tables(module.WRITTEN_MODELS))

    # projection interpolates its table names, which the regex can't see.
    written.add(projection.TABLE)
    assert written <= analyzed, f"add the models of {sorted(written - analyzed)} to WRITTEN_MODELS"


def test_analyze_steps_dedupe_models_sharing_a_table():
    assert analyze_steps([CriteriaPlaylist, GenrePlaylist]) == [
        ("analyze_grow_criteria_playlist", "ANALYZE grow_criteria_playlist")
    ]
