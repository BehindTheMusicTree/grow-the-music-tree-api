import pytest

from grow.curation.rows import InvalidRow, parse_row, to_csv_row


def test_cultural_role_round_trips():
    row = {"entity_id": "Q30", "is_cultural": True, "reason": "approved"}
    parsed = parse_row("entity_cultural_roles", row)
    assert to_csv_row("entity_cultural_roles", parsed.key, parsed.values, parsed.reason) == {
        **row,
        "is_cultural": "true",
    }


def test_cultural_membership_rejects_self_link():
    with pytest.raises(InvalidRow):
        parse_row(
            "cultural_membership_overrides",
            {"child_entity_id": "Q30", "parent_entity_id": "Q30", "action": "add", "reason": "invalid"},
        )
