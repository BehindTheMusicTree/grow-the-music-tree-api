from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.schemas import load_gold_schema


def test_schema_reasons_then_equal_the_reasons_the_pipeline_can_report():
    schema_reasons = set(
        load_gold_schema("curation_resolutions")["properties"]["review"]["items"]["properties"]["reason"]["enum"]
    )

    synthetic = {str(reason) for reason in CurationReviewItem.SYNTHETIC_OVERVIEW_REASONS}
    assert schema_reasons == {str(reason) for reason in CurationReviewItem.Reason} - synthetic
