from the_music_tree_genre_kit.serializer.model.criteria.output.CriteriaOutputFieldKey import (
    CriteriaOutputFieldKey as KitCriteriaOutputFieldKey,
)

from grow.serializer.model.criteria.output.CriteriaOutputFieldKey import CriteriaOutputFieldKey
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    """
    Guard against grow's CriteriaOutputFieldKey silently drifting from the kit's base enum.

    grow's enum hand-copies the kit's base members instead of inheriting them (StrEnum can't
    be subclassed once it has members), so a field added to the kit's enum has no mechanism
    to propagate here automatically. This is exactly how `side` (genre-kit v0.8.0) went
    missing from the detailed output. This test fails as soon as it happens again.
    """

    def test_all_kit_members_are_mirrored_with_the_same_value(self):
        missing = []
        mismatched = []

        for kit_member in KitCriteriaOutputFieldKey:
            local_member = getattr(CriteriaOutputFieldKey, kit_member.name, None)
            if local_member is None:
                missing.append(kit_member.name)
            elif local_member.value != kit_member.value:
                mismatched.append(f"{kit_member.name}: kit={kit_member.value!r} local={local_member.value!r}")

        assert not missing, (
            f"CriteriaOutputFieldKey is missing member(s) present in the kit's base enum: {missing}. "
            "Add them to grow/serializer/model/criteria/output/CriteriaOutputFieldKey.py "
            "(and wire them into the relevant serializer's Meta.fields if the field should be exposed)."
        )
        assert not mismatched, f"CriteriaOutputFieldKey member value(s) diverge from the kit's base enum: {mismatched}"
