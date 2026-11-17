"""PostgreSQL 16 proof that the handoff leaves the API role read-only (needs GROW_PERF_PG_BINDIR)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks.catalogue.database_handoff import HANDOFF_SQL, OWNER_LOCK_SQL, OWNERSHIP_SQL, ROLE_PROOF_SQL

PORT = "55441"


@unittest.skipUnless(os.environ.get("GROW_PERF_PG_BINDIR"), "set GROW_PERF_PG_BINDIR to qualify PostgreSQL 16")
class HandoffPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = Path(os.environ["GROW_PERF_PG_BINDIR"])
        if " 16." not in subprocess.check_output([cls.bin / "initdb", "--version"], text=True):
            raise RuntimeError("handoff qualification requires PostgreSQL 16")
        cls.temporary = tempfile.TemporaryDirectory(prefix="grow-pg-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.data = cls.root / "data"
        subprocess.run(
            [cls.bin / "initdb", "-D", cls.data, "--no-locale", "--encoding=UTF8", "--auth=trust", "-U", "postgres"],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.addClassCleanup(
            subprocess.run, [cls.bin / "pg_ctl", "-D", cls.data, "-m", "immediate", "-w", "stop"], capture_output=True
        )
        subprocess.run(
            [
                cls.bin / "pg_ctl",
                "-D",
                cls.data,
                "-l",
                cls.root / "postgres.log",
                "-w",
                "-t",
                "15",
                "-o",
                f"-F -h '' -k {cls.root} -p {PORT}",
                "start",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        cls.sql("postgres", "postgres", "CREATE DATABASE btmt_grow_perf TEMPLATE template0;")
        # Restore runs as postgres; the owner then takes the schema over and prepares it.
        cls.sql(
            "postgres",
            "btmt_grow_perf",
            "CREATE TABLE public.genre (id int PRIMARY KEY, name text NOT NULL);"
            "INSERT INTO public.genre VALUES (1, 'rock');"
            "CREATE SEQUENCE public.counter;",
        )
        cls.sql("postgres", "btmt_grow_perf", OWNERSHIP_SQL)
        cls.sql(
            "grow_perf_owner", "btmt_grow_perf", "CREATE TABLE public.derived (id int); INSERT INTO derived VALUES (1);"
        )
        cls.sql("postgres", "btmt_grow_perf", OWNER_LOCK_SQL)
        cls.sql("postgres", "btmt_grow_perf", HANDOFF_SQL)

    @classmethod
    def run_sql(cls, user, database, query):
        return subprocess.run(
            [
                cls.bin / "psql",
                "-X",
                "-h",
                cls.root,
                "-p",
                PORT,
                "-U",
                user,
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-Atq",
            ],
            input=query,
            text=True,
            check=False,
            capture_output=True,
            timeout=30,
        )

    @classmethod
    def sql(cls, user, database, query):
        result = cls.run_sql(user, database, query)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()

    def denied(self, query, user="grow_perf_app", database="btmt_grow_perf"):
        result = self.run_sql(user, database, query)
        self.assertNotEqual(result.returncode, 0, query)

    def test_ownership_moved_off_the_superuser(self):
        owners = self.sql(
            "postgres",
            "btmt_grow_perf",
            "SELECT DISTINCT pg_get_userbyid(relowner) FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'S')",
        )
        self.assertEqual(owners, "grow_perf_owner")

    def test_application_role_reads_but_has_no_privileged_attributes(self):
        self.assertEqual(self.sql("grow_perf_app", "btmt_grow_perf", "SELECT name FROM public.genre"), "rock")
        self.assertEqual(self.sql("grow_perf_app", "btmt_grow_perf", ROLE_PROOF_SQL), "t")

    def test_application_cannot_write_even_with_read_only_disabled(self):
        for statement in (
            "INSERT INTO public.genre VALUES (2, 'jazz')",
            "UPDATE public.genre SET name = 'x'",
            "DELETE FROM public.genre",
            "TRUNCATE public.genre",
            "SELECT nextval('public.counter')",
            "CREATE TABLE public.mine (id int)",
            "CREATE SCHEMA mine",
            "DROP TABLE public.genre",
            "ALTER TABLE public.genre RENAME TO other",
            "SELECT lo_create(0)",
            "SELECT pg_notify('c', 'x')",
            "SELECT pg_logical_emit_message(true, 'p', 'x')",
            "CREATE ROLE intruder",
        ):
            self.denied("SET default_transaction_read_only = off; SET transaction_read_only = off; " + statement)

    def test_grant_by_the_application_role_changes_nothing(self):
        self.sql(
            "grow_perf_app",
            "btmt_grow_perf",
            "SET default_transaction_read_only = off; SET transaction_read_only = off;"
            "GRANT ALL ON public.genre TO PUBLIC",
        )
        self.assertEqual(
            self.sql(
                "postgres",
                "btmt_grow_perf",
                "SELECT has_table_privilege('public', 'public.genre', 'INSERT, UPDATE, DELETE')",
            ),
            "f",
        )

    def test_role_settings_changed_by_the_application_are_detected(self):
        self.assertEqual(self.sql("grow_perf_app", "btmt_grow_perf", ROLE_PROOF_SQL), "t")
        self.sql("postgres", "btmt_grow_perf", "ALTER ROLE grow_perf_app SET work_mem = '64kB'")
        try:
            self.assertEqual(self.sql("grow_perf_app", "btmt_grow_perf", ROLE_PROOF_SQL), "f")
        finally:
            self.sql("postgres", "btmt_grow_perf", "ALTER ROLE grow_perf_app RESET work_mem")

    def test_owner_and_superuser_cannot_be_reached_through_the_owner_login(self):
        self.denied("SELECT 1", user="grow_perf_owner")
        self.denied("SET ROLE grow_perf_owner")
        self.denied("SET ROLE postgres")


if __name__ == "__main__":
    unittest.main()
