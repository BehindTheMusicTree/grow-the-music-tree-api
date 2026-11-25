"""Run the approved benchmark preparation script against a scratch PostgreSQL 16 database (#511)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import dj_database_url
import psycopg
import pytest
from psycopg import sql

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[3]
APPROVED = ROOT / "benchmarks" / "catalogue"


@pytest.fixture
def scratch_database():
    admin = dj_database_url.parse(os.environ["POSTGRES_TEST_DATABASE_URL"])
    name = f"prepare_{uuid.uuid4().hex[:12]}"
    connection = psycopg.connect(
        dbname=admin["NAME"],
        user=admin["USER"],
        password=admin["PASSWORD"],
        host=admin["HOST"],
        port=admin["PORT"],
        autocommit=True,
    )
    connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = os.environ["POSTGRES_TEST_DATABASE_URL"].rsplit("/", 1)[0] + f"/{name}"
    try:
        yield url
    finally:
        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        connection.close()


def run_prepare(url: str) -> subprocess.CompletedProcess:
    environment = {
        **os.environ,
        "PYTHONPATH": f"{APPROVED}:{ROOT}",
        "DJANGO_SETTINGS_MODULE": "grow_perf_settings",
        "DATABASE_URL": url,
    }
    return subprocess.run(
        [sys.executable, str(APPROVED / "prepare.py")],
        env=environment,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def query(url: str, statement: str):
    with psycopg.connect(url, autocommit=True) as connection:
        return connection.execute(statement).fetchall()


def test_prepare_migrates_fingerprints_projections_and_analyzes_every_table(scratch_database):
    result = run_prepare(scratch_database)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "preparation complete" in result.stdout
    assert query(scratch_database, "SELECT count(*) FROM grow_genre_tree_version") == [(1,)]
    assert query(
        scratch_database,
        "SELECT count(*) FROM pg_stat_user_tables WHERE schemaname = 'public' AND last_analyze IS NULL",
    ) == [(0,)]
