import inspect
import re

import pytest

from grow.artist.bulk_import import merge as artist_merge
from grow.bulk_import.analyze import analyze_steps, tables
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.track.bulk_import import merge as song_merge

WRITE = re.compile(r"\b(?:INSERT INTO|UPDATE|DELETE FROM)\s+([a-z_]+)")


@pytest.mark.parametrize("module", [song_merge, artist_merge], ids=["songs", "artists"])
def test_merge_analyzes_every_table_it_writes(module):
    temp_tables = {name.strip() for name in module.TEMP_TABLES.split(",")}
    written = set(WRITE.findall(inspect.getsource(module))) - temp_tables
    analyzed = set(tables(module.WRITTEN_MODELS))

    assert written <= analyzed, f"add the models of {sorted(written - analyzed)} to WRITTEN_MODELS"


def test_analyze_steps_dedupe_models_sharing_a_table():
    assert analyze_steps([CriteriaPlaylist, GenrePlaylist]) == [
        ("analyze_grow_criteria_playlist", "ANALYZE grow_criteria_playlist")
    ]
