import pytest

from grow.curation.rows import InvalidRow, parse_row

LIST = "synthetic_overview_resolutions"


def _row(**overrides):
    return {
        "item_id": "LOCAL:region-q1",
        "action": "replace",
        "replacement_item_id": "Q5",
        "reason": "r",
        **overrides,
    }


def test_replace_and_remove_rows_are_valid():
    assert parse_row(LIST, _row()).values == {"action": "replace", "replacement_item_id": "Q5"}
    assert parse_row(LIST, _row(action="remove", replacement_item_id="")).values["replacement_item_id"] == ""


@pytest.mark.parametrize(
    "overrides, column",
    [
        ({"item_id": "Q1"}, "item_id"),
        ({"replacement_item_id": ""}, "replacement_item_id"),
        ({"action": "remove"}, "replacement_item_id"),
        ({"replacement_item_id": "LOCAL:region-q1"}, "replacement_item_id"),
        ({"action": "drop"}, "action"),
    ],
)
def test_invalid_rows(overrides, column):
    with pytest.raises(InvalidRow) as error:
        parse_row(LIST, _row(**overrides))
    assert column in error.value.args[0]
