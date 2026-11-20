"""Keep the catalogue benchmark schema contract in step with the migrations (#511)."""

import difflib

import pytest
from django.db import connection

from benchmarks.catalogue import catalogue_restore as catalogue
from benchmarks.catalogue.restore_execution import inventory_sql

pytestmark = [pytest.mark.postgres, pytest.mark.django_db]

HOW_TO_FIX = (
    "benchmarks/catalogue/catalogue-schema.tsv no longer matches the migrated schema. "
    "Apply the diff above to the tsv, then classify every added or removed table in "
    "benchmarks/catalogue/catalogue_restore.py (RETAIN, EMPTY or REBUILD) and update "
    "benchmarks/catalogue/tests/test_catalogue.py counts and fixtures."
)


def _observed_inventory() -> str:
    with connection.cursor() as cursor:
        cursor.execute(inventory_sql())
        return "\n".join(row[0] for row in cursor.fetchall()) + "\n"


def test_catalogue_schema_tsv_matches_migrated_schema():
    expected = catalogue.SCHEMA.read_text()
    observed = _observed_inventory()
    if observed != expected:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(), observed.splitlines(), "catalogue-schema.tsv", "migrated schema", lineterm=""
            )
        )
        pytest.fail(f"{diff}\n\n{HOW_TO_FIX}")
    # Every table must also have exactly one disposition.
    catalogue.verify_inventory(observed)


def test_catalogue_relation_inventory_accepts_migrated_schema():
    with connection.cursor() as cursor:
        cursor.execute(catalogue.relation_inventory_sql())
