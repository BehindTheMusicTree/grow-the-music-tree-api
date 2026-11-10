import pytest

from grow.region_map.bulk_import.merge import _check_boundary


def test_missing_boundary_preserves_identity_without_fabricated_coordinates():
    _check_boundary({"boundaryStatus": "missing", "bbox": None, "mainBbox": None, "centroid": None})
    _check_boundary({"bbox": [0, 0, 1, 1], "mainBbox": [0, 0, 1, 1], "centroid": [0.5, 0.5]})


def test_lean_index_omits_boundary_status_and_main_bbox():
    _check_boundary({"bbox": None, "centroid": None})
    _check_boundary({"bbox": [0, 0, 1, 1], "centroid": [0.5, 0.5]})
    _check_boundary({"boundaryStatus": "missing", "bbox": None, "centroid": None})
    _check_boundary({"boundaryStatus": "available", "bbox": [0, 0, 1, 1], "centroid": [0.5, 0.5]})


@pytest.mark.parametrize(
    "region",
    [
        {"boundaryStatus": "invalid"},
        {"boundaryStatus": []},
        {"boundaryStatus": "available"},
        {"boundaryStatus": "missing"},
        {"boundaryStatus": "missing", "bbox": None, "mainBbox": None, "centroid": [0, 0]},
        {"boundaryStatus": "available", "bbox": None},
        {"bbox": None},
        {"bbox": None, "centroid": [0, 0]},
        {"bbox": [0, 0, 1, 1], "centroid": None},
        {"bbox": None, "mainBbox": [0, 0, 1, 1], "centroid": None},
        {"boundaryStatus": "missing", "bbox": [0, 0, 1, 1], "centroid": [0.5, 0.5]},
        {"boundaryStatus": "available", "bbox": None, "centroid": None},
        {"centroid": None},
        {"mainBbox": None},
        {"bbox": [0, 0, 1, 1]},
    ],
)
def test_boundary_status_rejects_inconsistent_coordinates(region):
    with pytest.raises(ValueError, match=r"boundary|coordinates"):
        _check_boundary(region)
