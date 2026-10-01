import csv
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from grow.curation.lists import CURATION_LISTS
from grow.curation.rows import SEED_DIR
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.utils.AppTestCase import AppTestCase


def _read_csv(list_name: str, directory=SEED_DIR) -> list[dict[str, str]]:
    with (directory / f"manual_{list_name}.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _key(list_name: str, row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row[c] for c in CURATION_LISTS[list_name].key)


class TestCase(AppTestCase):
    def test_seed_csv_headers_match_registry(self):
        for list_name, curation_list in CURATION_LISTS.items():
            with (SEED_DIR / f"manual_{list_name}.csv").open(newline="", encoding="utf-8") as f:
                assert tuple(next(csv.reader(f))) == curation_list.columns, list_name

    def test_migration_seed_then_export_equals_csvs(self):
        export = self.api_client.get(path=reverse("curation-export")).json()

        for list_name in CURATION_LISTS:
            expected = sorted(_read_csv(list_name), key=lambda r: _key(list_name, r))
            actual = sorted(export[list_name], key=lambda r: _key(list_name, r))
            assert actual == expected, list_name

    def test_import_command_then_idempotent_upsert(self):
        total = CurationEntry.objects.count()
        out = StringIO()

        call_command("import_curation_csvs", str(SEED_DIR), stdout=out)

        assert out.getvalue().strip() == f"0 created, 0 updated, {total} unchanged"
        assert CurationEntry.objects.count() == total

    def test_import_command_changed_row_then_updated_with_history(self):
        entry = CurationEntry.objects.filter(list_name="theme_genres").first()
        old_updated_on = entry.updated_on
        CurationEntry.objects.filter(pk=entry.pk).update(reason="stale reason")
        out = StringIO()

        call_command("import_curation_csvs", str(SEED_DIR), stdout=out)

        assert out.getvalue().strip().startswith("0 created, 1 updated, ")
        entry.refresh_from_db()
        assert entry.reason != "stale reason"
        assert entry.updated_on is not None and entry.updated_on != old_updated_on
        history = HistoryEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(CurationEntry), content_uuid=entry.uuid
        )
        assert [h.action for h in history] == [HistoryAction.UPDATED]

    def test_import_command_bad_row_then_error_and_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            for path in SEED_DIR.glob("manual_*.csv"):
                shutil.copy(path, directory)
            with (directory / "manual_theme_genres.csv").open("a", encoding="utf-8") as f:
                f.write("bad-id,label,reason\n")
            total = CurationEntry.objects.count()

            try:
                call_command("import_curation_csvs", str(directory), stdout=StringIO())
            except CommandError as e:
                assert "manual_theme_genres.csv" in str(e)
            else:
                raise AssertionError("expected CommandError")

        assert CurationEntry.objects.count() == total
