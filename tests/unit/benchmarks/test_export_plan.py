import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from benchmarks.catalogue import catalogue_restore as catalogue
from benchmarks.catalogue.export_plan import PROJECTION_STATES, build_plan

FINGERPRINTS = {table: f"{index:064x}" for index, table in enumerate(sorted(PROJECTION_STATES))}


def test_plan_reads_the_classification_not_a_copy():
    tsv = catalogue.SCHEMA.read_text()
    plan = build_plan(tsv, FINGERPRINTS)
    assert plan["data_tables"] == sorted(catalogue.RETAIN | catalogue.DERIVED)
    assert plan["schema_only_tables"] == sorted(catalogue.EMPTY | catalogue.REBUILD)
    assert not set(plan["data_tables"]) & set(plan["schema_only_tables"])
    assert plan["projections"]["grow_song_search"] == {
        "state_table": "grow_song_search_state",
        "fingerprint": FINGERPRINTS["grow_song_search"],
    }
    json.dumps(plan)


def test_plan_is_deterministic_and_binds_the_schema():
    tsv = catalogue.SCHEMA.read_text()
    assert build_plan(tsv, FINGERPRINTS) == build_plan(tsv, FINGERPRINTS)
    assert len(build_plan(tsv, FINGERPRINTS)["inventory_sha256"]) == 64


def test_plan_refuses_schema_drift():
    drifted = catalogue.SCHEMA.read_text() + "grow_new_table|id|integer|NO\n"
    with pytest.raises(ValueError, match="schema drift"):
        build_plan(drifted, FINGERPRINTS)


@pytest.mark.parametrize(
    "fingerprints", [{}, {"grow_song_search": "a" * 64}, {**FINGERPRINTS, "grow_song_search": None}]
)
def test_plan_refuses_unstamped_projections(fingerprints):
    with pytest.raises(ValueError, match="stamped fingerprint"):
        build_plan(catalogue.SCHEMA.read_text(), fingerprints)


def test_command_requires_the_plan_flag():
    with pytest.raises(CommandError, match="--plan"):
        call_command("export_perf_catalogue")


@pytest.mark.django_db
def test_command_refuses_a_non_postgres_database():
    with pytest.raises(CommandError, match="PostgreSQL"):
        call_command("export_perf_catalogue", plan=True)
