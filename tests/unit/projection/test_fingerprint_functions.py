import re

import pytest

from grow.artist_song import projection as artist_song
from grow.song_search import projection as song_search


@pytest.mark.parametrize("module", [song_search, artist_song])
def test_every_routine_a_projection_calls_is_fingerprinted(module):
    called = set(re.findall(r"\b(grow_\w+)\(", module.PROJECTION))
    listed = {re.search(r"\.(\w+)\(", function).group(1) for function in module.FUNCTIONS}
    assert called == listed
