from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.schemas import load_gold_schema


def test_schema_reasons_match_the_wikidata_resolution_review_reasons():
    schema_reasons = set(
        load_gold_schema("curation_resolutions")["properties"]["review"]["items"]["properties"]["reason"]["enum"]
    )

    other_reports = {*CurationReviewItem.SYNTHETIC_OVERVIEW_REASONS, *CurationReviewItem.GENRE_ALIAS_REASONS}
    assert schema_reasons == {str(reason) for reason in CurationReviewItem.Reason if reason not in other_reports}
