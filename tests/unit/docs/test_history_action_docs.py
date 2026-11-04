import re
from pathlib import Path

from grow.model.history.HistoryAction import HistoryAction

GENRES_DOC = Path(__file__).resolve().parents[3] / "docs" / "api" / "genres.md"


def test_genre_history_docs_list_every_history_action():
    """Clients validate `action` against this list, so a value missing here breaks them."""
    sentence = re.search(r"`action` is one of (.+?)\(", GENRES_DOC.read_text(), re.DOTALL)
    assert sentence is not None
    assert set(re.findall(r"`(\w+)`", sentence.group(1))) == set(HistoryAction.values)
