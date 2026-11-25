from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from grow.genre_tree.bulk_import.merge import load_curation_export, parse_curation_exported_on
from grow.model.curation.CurationExport import CurationExport

pytestmark = pytest.mark.django_db


def test_record_keeps_snapshot_and_exposes_roots():
    now = timezone.now()
    export = CurationExport.record(now, {"canonical_roots": [{"item_id": "Q1"}, {"item_id": "Q2"}]}, None)
    assert export.canonical_roots == {"Q1", "Q2"}


def test_record_purges_exports_over_30_days_before_the_applied_one():
    applied = timezone.now()
    old = CurationExport.objects.create(exported_on=applied - timedelta(days=31), snapshot={})
    recent = CurationExport.objects.create(exported_on=applied - timedelta(days=29), snapshot={})
    CurationExport.record(applied, {"canonical_roots": []}, applied)
    assert not CurationExport.objects.filter(pk=old.pk).exists()
    assert CurationExport.objects.filter(pk=recent.pk).exists()


def test_export_without_snapshot_has_no_roots():
    export = CurationExport.objects.create(exported_on=timezone.now(), snapshot=None)
    with pytest.raises(ValueError, match="predates snapshots"):
        export.canonical_roots


def test_unknown_or_purged_date_is_rejected_exactly():
    when = timezone.now()
    CurationExport.objects.create(exported_on=when, snapshot={})
    assert parse_curation_exported_on(when.isoformat()) == when
    with pytest.raises(ValidationError, match="Unknown curation export"):
        load_curation_export((when + timedelta(seconds=1)).isoformat())
