"""Real PG16 custom-archive qualification with synthetic data only."""

import hashlib
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from benchmarks.catalogue import catalogue_restore as catalogue
from benchmarks.catalogue import restore_execution as execution
from benchmarks.catalogue.tests.test_catalogue import CataloguePostgresFixture, insert


class LocalPostgres:
    """Test transport; production requires the private runtime and immutable mount."""

    def __init__(self, fixture, archive):
        self.fixture = fixture
        self.archive = archive
        self.calls = []

    def run(self, program, arguments, stdin=None):
        self.calls.append((program, arguments, stdin))
        if program == "sha256sum":
            return hashlib.sha256(self.archive.read_bytes()).hexdigest() + "  /restore/backup.dump\n"
        args = [str(self.archive) if arg == "/restore/backup.dump" else arg for arg in arguments]
        if program == "psql" or (program == "pg_restore" and "--list" not in args):
            args = ["-h", str(self.fixture.root), "-p", "55439", *args]
        # Do not let an operator's PGHOST, PGDATABASE, PGSERVICE, etc. redirect tests.
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        return subprocess.run(
            [self.fixture.bin / program, *args],
            input=stdin,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
            env=env,
        ).stdout


class CatalogueExecutionTest(CataloguePostgresFixture):
    def setUp(self):
        super().setUp()
        self.sql(
            insert("auth_user", id=7, username="PRIVATE_SENTINEL")
            + insert("grow_song_search")
            + "CREATE SEQUENCE public.fixture_alias_seq OWNED BY public.grow_artist_alias.id;"
            + "ALTER TABLE public.grow_artist_alias ALTER COLUMN id "
            "SET DEFAULT nextval('public.fixture_alias_seq');"
            + "SELECT setval('public.fixture_alias_seq', 9000);"
            + "CREATE INDEX fixture_alias_artist_idx ON public.grow_artist_alias(artist_id);"
            + "ALTER TABLE public.grow_artist ADD PRIMARY KEY(uuid);"
            + "ALTER TABLE public.grow_artist_alias ADD CONSTRAINT fixture_alias_artist_fk "
            "FOREIGN KEY(artist_id) REFERENCES public.grow_artist(uuid);"
        )
        self.archive = self.root / "fixture.dump"
        self.transport = LocalPostgres(self, self.archive)
        self.transport.run(
            "pg_dump",
            [
                "-h",
                str(self.root),
                "-p",
                "55439",
                "-d",
                "postgres",
                "-Fc",
                "--no-owner",
                "--no-privileges",
                "-f",
                str(self.archive),
            ],
        )
        self.pre = self.extract("pre-data")
        self.post = self.extract("post-data")
        self.approval = self.approve()
        self.sql("DROP DATABASE IF EXISTS btmt_grow_perf WITH (FORCE);")
        self.sql("CREATE DATABASE btmt_grow_perf TEMPLATE template0;")
        self.addCleanup(self.sql, "DROP DATABASE IF EXISTS btmt_grow_perf WITH (FORCE);")
        self.transport.calls.clear()

    def extract(self, section):
        return self.transport.run(
            "pg_restore",
            [
                "--section=" + section,
                "--no-owner",
                "--no-privileges",
                "--restrict-key=FixtureQualification",
                "-f",
                "-",
                "/restore/backup.dump",
            ],
        ).encode()

    def approve(self):
        return execution.Approval.parse(
            {
                "version": 1,
                "backup_sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                "pre_data_sha256": hashlib.sha256(self.pre).hexdigest(),
                "post_data_sha256": hashlib.sha256(self.post).hexdigest(),
            }
        )

    def fixture_policy(self, tsv, schema):
        policy = catalogue.data_policy(tsv, schema)
        # Only this synthetic fixture lowers minima. Production parsing and
        # executor defaults continue to require the full 30M-song catalogue.
        return replace(policy, tables={name: replace(table, minimum_rows=0) for name, table in policy.tables.items()})

    def restore(self):
        with patch.object(execution, "data_policy", self.fixture_policy):
            return execution.restore(self.transport, self.approval, self.pre, self.post)

    def query(self, query):
        return execution.sql(self.transport, query)

    def test_real_dump_projection_and_sequence_repair(self):
        self.assertEqual(self.pre, self.extract("pre-data"))
        self.assertEqual(self.post, self.extract("post-data"))
        evidence = self.restore()
        self.assertEqual(evidence["status"], "projected")
        self.assertEqual(evidence["row_counts"]["auth_user"], 0)
        self.assertEqual(evidence["row_counts"]["grow_song_search"], 0)
        self.assertEqual(evidence["row_counts"]["grow_song"], 2)
        self.assertEqual(self.query("SELECT nextval('public.fixture_alias_seq');"), "2")
        self.assertEqual(
            self.query("SELECT convalidated FROM pg_constraint WHERE conname='fixture_alias_artist_fk';"), "t"
        )
        self.assertEqual(
            self.query("SELECT indisvalid FROM pg_index WHERE indexrelid='public.fixture_alias_artist_idx'::regclass;"),
            "t",
        )
        selected = next(
            stdin for program, args, stdin in self.transport.calls if program == "pg_restore" and "--data-only" in args
        )
        self.assertNotIn("auth_user", selected)
        self.assertNotIn("grow_song_search", selected)
        self.assertNotIn("SEQUENCE SET", selected)

    def test_production_minimum_rejects_tiny_catalogue(self):
        with self.assertRaisesRegex(ValueError, "catalogue is incomplete"):
            execution.restore(self.transport, self.approval, self.pre, self.post)

    def test_changed_artifacts_refused_before_database_commands(self):
        for field in ("backup_sha256", "pre_data_sha256", "post_data_sha256"):
            with self.subTest(field=field):
                self.transport.calls.clear()
                approval = replace(self.approval, **{field: "0" * 64})
                with self.assertRaises(ValueError):
                    execution.restore(self.transport, approval, self.pre, self.post)
                self.assertFalse(any(program in {"psql", "pg_restore"} for program, _, _ in self.transport.calls))

    def test_nonempty_database_refused(self):
        self.query("CREATE TABLE public.unexpected(id int);")
        with self.assertRaisesRegex(ValueError, "fresh, exclusive"):
            self.restore()

    def test_schema_drift_refused_before_loading_data(self):
        self.pre += b"\nALTER TABLE public.auth_group ADD COLUMN extra text;\n"
        self.approval = self.approve()
        with self.assertRaisesRegex(ValueError, "schema drift"):
            self.restore()
        self.assertEqual(self.query("SELECT count(*) FROM public.grow_song;"), "0")

    def test_partial_schema_failure_requires_fresh_database(self):
        self.pre += b"\nSELECT 1/0;\n"
        self.approval = self.approve()
        with self.assertRaises(subprocess.CalledProcessError):
            self.restore()
        with self.assertRaisesRegex(ValueError, "fresh, exclusive"):
            self.restore()

    def test_failed_data_load_rolls_back_all_selected_tables(self):
        self.pre += b"\nALTER TABLE public.grow_song ADD CHECK (false);\n"
        self.approval = self.approve()
        with self.assertRaises(subprocess.CalledProcessError):
            self.restore()
        self.assertEqual(self.query("SELECT count(*) FROM public.grow_artist;"), "0")
        self.assertEqual(self.query("SELECT count(*) FROM public.grow_song;"), "0")

    def test_post_data_failure_and_unvalidated_constraint_refused(self):
        self.post += b"\nALTER TABLE public.grow_song ADD CONSTRAINT fixture_not_valid CHECK (true) NOT VALID;\n"
        self.approval = self.approve()
        with self.assertRaisesRegex(ValueError, "unvalidated constraints"):
            self.restore()

    def test_post_data_injection_refused(self):
        self.post += ("\n" + insert("auth_user", id=7, username="FORBIDDEN") + "\n").encode()
        self.approval = self.approve()
        with self.assertRaisesRegex(ValueError, "unapproved table contains data"):
            self.restore()

    def test_post_data_sql_error_never_returns_evidence(self):
        self.post += b"\nSELECT 1/0;\n"
        self.approval = self.approve()
        with self.assertRaises(subprocess.CalledProcessError):
            self.restore()

    def test_post_data_layout_change_refused(self):
        self.post += b"\nALTER TABLE public.auth_group ADD COLUMN extra text;\n"
        self.approval = self.approve()
        with self.assertRaisesRegex(ValueError, "schema drift"):
            self.restore()

    def test_post_data_zero_column_table_refused(self):
        self.post += b"\nCREATE TABLE public.unexpected();\n"
        self.approval = self.approve()
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.restore()
        self.assertIn("catalogue relation inventory drift", failure.exception.stderr)

    def test_post_data_unlogged_zero_column_table_refused(self):
        self.post += b"\nCREATE UNLOGGED TABLE public.unexpected();\n"
        self.approval = self.approve()
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.restore()
        self.assertIn("catalogue relation inventory drift", failure.exception.stderr)

    def test_post_data_materialized_view_refused(self):
        self.post += b"\nCREATE MATERIALIZED VIEW public.unexpected AS SELECT 1 AS id;\n"
        self.approval = self.approve()
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.restore()
        self.assertIn("catalogue relation inventory drift", failure.exception.stderr)
