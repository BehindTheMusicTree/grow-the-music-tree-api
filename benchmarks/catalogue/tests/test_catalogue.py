"""Catalogue policy contracts; real PostgreSQL tests require GROW_PERF_PG_BINDIR."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks.catalogue import catalogue_restore as catalogue

TSV = catalogue.SCHEMA.read_text()
TABLES = catalogue.verify_inventory(TSV)
SQL = catalogue.projection_sql(TSV)
TRACK = catalogue.TRACK
PLAYLIST = catalogue.PLAYLIST
REL = f"{TRACK}_playlist_rel"


def uid(number):
    return f"00000000-0000-0000-0000-{number:012d}"


def insert(table, **values):
    defaults = {
        "uuid": uid(0),
        "integer": 0,
        "bigint": 0,
        "smallint": 0,
        "boolean": False,
        "text": "fixture",
        "character varying": "fixture",
        "timestamp with time zone": "2026-01-01T00:00:00Z",
        "jsonb": "[]",
        "double precision": 0,
        "bytea": "",
        "tsvector": "",
    }
    row = {column: defaults[kind] for column, kind, nullable in TABLES[table] if nullable == "NO"}
    row.update(values)

    def literal(value):
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int):
            return str(value)
        return "'" + value.replace("'", "''") + "'"

    columns = ", ".join(f'"{column}"' for column in row)
    return f'INSERT INTO public."{table}" ({columns}) VALUES ({", ".join(map(literal, row.values()))});'


class CataloguePolicyTest(unittest.TestCase):
    def test_inventory_and_dispositions_are_exhaustive(self):
        self.assertEqual(len(TABLES), 58)
        self.assertEqual(sum(map(len, TABLES.values())), 385)
        self.assertEqual(TABLES.keys(), catalogue.RETAIN | catalogue.EMPTY | catalogue.REBUILD)

    def test_verifications_aggregate_instead_of_probing_for_a_first_row(self):
        # EXISTS plans for the first row; on tables restored without statistics that picks a
        # nested-loop anti join that never finishes at catalogue scale. count(*) hashes instead.
        checks = [
            line for line in SQL.splitlines() if line.startswith("DO $$ BEGIN") and "catalogue verification" in line
        ]
        self.assertTrue(checks)
        for check in checks:
            with self.subTest(check=check[:80]):
                self.assertNotIn("IF EXISTS", check)
                self.assertEqual(check.count("IF (SELECT count(*) FROM"), check.count("THEN RAISE EXCEPTION"))

    def test_inventory_drift_refused(self):
        for changed in (
            TSV + "new_table|id|bigint|NO\n",
            TSV.replace("auth_group|id|integer|NO\n", ""),
            TSV.replace("auth_group|id|integer|NO", "auth_group|id|bigint|NO"),
            TSV.replace("auth_group|id|integer|NO", "auth_group|id|integer|YES"),
            TSV + TSV.splitlines()[0] + "\n",
        ):
            with self.subTest(changed=changed[:80]), self.assertRaises(ValueError):
                catalogue.verify_inventory(changed)

    def test_complete_columns_and_counts_required(self):
        policy = catalogue.data_policy(TSV, b"fixture schema; not approved for restore")
        columns = {name: [column[0] for column in entries] for name, entries in TABLES.items()}
        policy.verify_schema(b"fixture schema; not approved for restore", columns)
        with self.assertRaises(ValueError):
            policy.verify_schema(b"fixture schema; not approved for restore", {**columns, "unknown": []})
        counts = {name: policy.tables[name].minimum_rows if name in policy.tables else 0 for name in TABLES}
        nonnull = {name: dict.fromkeys(table.null_columns, 0) for name, table in policy.tables.items()}
        policy.verify_rows(counts, nonnull)
        for changed in (
            {key: value for key, value in counts.items() if key != "auth_user"},
            {**counts, "unknown": 0},
            {**counts, "auth_user": 1},
            {**counts, "grow_song_search": 1},
            {**counts, "grow_song": 29_999_999},
        ):
            with self.subTest(counts=changed), self.assertRaises(ValueError):
                policy.verify_rows(changed, nonnull)


@unittest.skipUnless(os.environ.get("GROW_PERF_PG_BINDIR"), "set GROW_PERF_PG_BINDIR to qualify PostgreSQL 16")
class CataloguePostgresFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = Path(os.environ["GROW_PERF_PG_BINDIR"])
        version = subprocess.check_output([cls.bin / "initdb", "--version"], text=True)
        if " 16." not in version:
            raise RuntimeError("catalogue qualification requires PostgreSQL 16")
        # Unix socket paths need a short directory. All cluster files are
        # disposable and cleaned on success and failure, including startup errors.
        cls.temporary = tempfile.TemporaryDirectory(prefix="grow-pg-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.data = cls.root / "data"
        subprocess.run(
            [cls.bin / "initdb", "-D", cls.data, "--no-locale", "--encoding=UTF8", "--auth=trust"],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.addClassCleanup(
            subprocess.run,
            [cls.bin / "pg_ctl", "-D", cls.data, "-m", "immediate", "-w", "stop"],
            capture_output=True,
            timeout=20,
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
                f"-F -h '' -k {cls.root} -p 55439",
                "start",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def sql(self, query, *, success=True):
        result = subprocess.run(
            [
                self.bin / "psql",
                "-X",
                "-h",
                self.root,
                "-p",
                "55439",
                "-d",
                "postgres",
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
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout.strip() if success else result.stderr

    def setUp(self):
        # This fixture reproduces reviewed column types and nullability only.
        # It does not stand in for approval of production schema SQL/post-data.
        statements = ["DROP SCHEMA public CASCADE; CREATE SCHEMA public;"]
        for table, columns in TABLES.items():
            fields = ", ".join(
                f'"{name}" {kind}' + (" NOT NULL" if nullable == "NO" else "") for name, kind, nullable in columns
            )
            statements.append(f'CREATE TABLE public."{table}" ({fields});')
        for number, label in enumerate(("genre", "region", "tag"), 1):
            statements.append(insert(catalogue.TYPES, id=number, label=label))
        for number in (1, 2, 3):
            statements.append(insert("grow_artist", uuid=uid(number), user_id=7 if number == 3 else None))
            statements.append(insert("grow_album", uuid=uid(number), user_id=7 if number == 3 else None))
        for number in (1, 2, 3, 4):
            statements.append(
                insert(
                    "grow_criteria",
                    uuid=uid(number),
                    root_id=uid(1),
                    type_id=min(number, 3),
                    parent_id=uid(1) if number != 1 else None,
                    user_id=7 if number == 4 else None,
                    tree_name=f"tree-{number}",
                )
            )
            statements.append(insert("grow_genre", criteria_ptr_id=uid(number), last_seen_run_id=42))
        for number in (1, 2, 3):
            statements.append(
                insert(
                    TRACK,
                    uuid=uid(number),
                    genre_id=uid(1) if number == 1 else None,
                    album_id=uid(1),
                    user_id=7 if number == 3 else None,
                )
            )
            statements.append(insert("grow_song", track_id=uid(number)))
        # Track without a Grow song and song without any track.
        statements.extend([insert(TRACK, uuid=uid(99)), insert("grow_song", track_id=uid(99_999))])
        for number in (1, 2, 3, 4, 5, 6, 7):
            statements.append(insert(PLAYLIST, uuid=uid(number), user_id=7 if number == 7 else None))
            if number != 6:  # Manual playlist parent with no catalogue child.
                statements.append(
                    insert(
                        "grow_criteria_playlist",
                        playlist_id=uid(number),
                        criteria_id=uid(number) if number <= 4 else None,
                        type_id=1,
                    )
                )
            statements.append(insert(REL, id=number, track_id=uid(1), playlist_id=uid(number), genre_id=uid(1)))
        statements.extend(
            [
                insert(REL, id=8, track_id=uid(1), playlist_id=uid(1), genre_id=uid(1), user_id=7),
                insert(REL, id=9, track_id=uid(3), playlist_id=uid(1)),
                insert("grow_criteria_lineage_rel", id=1, ascendant_id=uid(1), descendant_id=uid(2)),
                insert("grow_criteria_lineage_rel", id=2, ascendant_id=uid(1), descendant_id=uid(4)),
                insert("grow_criteria_lineage_rel", id=3, ascendant_id=uid(1), descendant_id=uid(2), user_id=7),
            ]
        )
        for table, left, right in (
            ("grow_album_album_artists", "album_id", "artist_id"),
            (f"{TRACK}_artists", "track_id", "artist_id"),
            ("grow_artist_membership", "group_id", "member_id"),
            ("grow_criteria_additional_primary_parents", "from_criteria_id", "to_criteria_id"),
            ("grow_criteria_secondary_parents", "from_criteria_id", "to_criteria_id"),
            ("grow_genre_essential_songs", "genre_id", "song_id"),
        ):
            for number in (1, 3, 4):
                statements.append(insert(table, id=number, **{left: uid(1), right: uid(number)}))
        for table in ("grow_artist_alias", "grow_artist_link"):
            for number in (1, 3):
                statements.append(insert(table, id=number, artist_id=uid(number)))
        self.sql("\n".join(statements))

    def count(self, table):
        return int(self.sql(f'SELECT count(*) FROM public."{table}";'))


class CataloguePostgresTest(CataloguePostgresFixture):
    def test_public_projection_and_referential_closure(self):
        self.sql(SQL)
        for table, expected in {
            TRACK: 2,
            "grow_song": 2,
            "grow_criteria": 3,
            "grow_genre": 3,
            PLAYLIST: 4,
            "grow_criteria_playlist": 4,
            REL: 4,
            "grow_criteria_lineage_rel": 1,
            "grow_artist_alias": 1,
            "grow_artist_link": 1,
            "grow_album_album_artists": 1,
            f"{TRACK}_artists": 1,
            "grow_artist_membership": 1,
            "grow_criteria_additional_primary_parents": 2,
            "grow_criteria_secondary_parents": 2,
            "grow_genre_essential_songs": 1,
        }.items():
            self.assertEqual(self.count(table), expected, table)
        self.assertEqual(self.sql("SELECT count(*) FROM public.grow_genre WHERE last_seen_run_id IS NOT NULL"), "0")
        for table in catalogue.EMPTY | catalogue.REBUILD:
            self.assertEqual(self.count(table), 0, table)
        self.sql(SQL)  # Idempotent projection.
        self.assertEqual(self.count(TRACK), 2)

    def test_deletions_use_join_plans_without_repeated_subplans(self):
        for query in SQL.splitlines():
            if not query.startswith("DELETE"):
                continue
            with self.subTest(query=query):
                plan = self.sql("SET work_mem='64kB'; EXPLAIN (FORMAT JSON) " + query)
                json.loads(plan)
                self.assertNotIn("SubPlan", plan, "catalogue-scale pruning must use a spillable join")

    def test_public_objects_pointing_to_private_roots_refused(self):
        for mutation in (
            f"UPDATE public.grow_criteria SET parent_id='{uid(4)}' WHERE uuid='{uid(2)}';",
            f"UPDATE public.\"{TRACK}\" SET album_id='{uid(3)}' WHERE uuid='{uid(1)}';",
            f"UPDATE public.\"{TRACK}\" SET genre_id='{uid(4)}' WHERE uuid='{uid(1)}';",
        ):
            with self.subTest(mutation=mutation):
                self.sql(mutation)
                self.assertIn("catalogue verification failed", self.sql(SQL, success=False))
                self.assertEqual(self.count(TRACK), 4)
                self.setUp()

    def test_forbidden_and_derived_data_refused(self):
        for table in sorted(catalogue.EMPTY | catalogue.REBUILD):
            with self.subTest(table=table):
                self.sql(insert(table))
                self.assertIn("catalogue verification failed", self.sql(SQL, success=False))
                self.assertEqual(self.count(TRACK), 4)
                self.sql(f'TRUNCATE public."{table}";')

    def test_missing_public_references_roll_back_projection(self):
        for table, column, _target, _key in catalogue.REFERENCES:
            with self.subTest(table=table, column=column):
                kind = next(kind for name, kind, _ in TABLES[table] if name == column)
                bad = "999999" if kind == "bigint" else f"'{uid(999999)}'"
                self.sql(f'UPDATE public."{table}" SET "{column}" = {bad};')
                self.assertIn("catalogue verification failed", self.sql(SQL, success=False))
                self.assertEqual(self.count(TRACK), 4, "failed projection committed deletions")
                self.setUp()

    def test_denormalized_genre_mismatch_rolls_back(self):
        self.sql(f'UPDATE public."{REL}" SET genre_id = NULL WHERE id=1;')
        self.assertIn("catalogue verification failed", self.sql(SQL, success=False))
        self.assertEqual(self.count(TRACK), 4)

    def test_live_schema_drift_refused(self):
        for mutation in (
            "ALTER TABLE public.grow_song ADD COLUMN private_payload text;",
            "ALTER TABLE public.grow_song DROP COLUMN youtube_video_id;",
            "ALTER TABLE public.grow_song ALTER COLUMN youtube_view_count TYPE numeric;",
            "ALTER TABLE public.grow_song ALTER COLUMN track_id DROP NOT NULL;",
            "CREATE TABLE public.unknown (id bigint);",
            "DROP TABLE public.auth_user;",
        ):
            with self.subTest(mutation=mutation):
                self.sql(mutation)
                self.assertIn("schema drift", self.sql(SQL, success=False))
                self.assertEqual(self.count(TRACK), 4)
                self.setUp()

    def test_rls_and_triggers_refused(self):
        for mutation in (
            "ALTER TABLE public.grow_song ENABLE ROW LEVEL SECURITY;",
            "ALTER TABLE public.grow_song FORCE ROW LEVEL SECURITY;",
            "CREATE FUNCTION public.trap() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$; "
            "CREATE TRIGGER trap BEFORE DELETE ON public.grow_song FOR EACH ROW EXECUTE FUNCTION public.trap();",
        ):
            with self.subTest(mutation=mutation):
                self.sql(mutation)
                self.assertIn("without triggers or RLS", self.sql(SQL, success=False))
                self.assertEqual(self.count(TRACK), 4)
                self.setUp()

    def test_unlisted_relations_and_non_table_replacements_refused(self):
        for mutation in (
            "CREATE TABLE public.unknown ();",
            "CREATE MATERIALIZED VIEW public.private_snapshot AS SELECT 'private' AS payload;",
            "DROP TABLE public.grow_wikidata_item; "
            "CREATE VIEW public.grow_wikidata_item AS SELECT ''::varchar AS item_id, ''::text AS label;",
            "ALTER TABLE public.grow_wikidata_item SET UNLOGGED;",
        ):
            with self.subTest(mutation=mutation):
                self.sql(mutation)
                self.sql(SQL, success=False)
                self.assertEqual(self.count(TRACK), 4)
                self.setUp()

    def test_hostile_search_path_does_not_redirect_projection(self):
        self.sql("CREATE SCHEMA hostile; CREATE TABLE hostile.grow_song (private_payload text);")
        self.sql("SET search_path = hostile, public; CREATE TEMP TABLE grow_song (private_payload text);" + SQL)
        self.assertEqual(self.count(TRACK), 2)
        self.assertEqual(self.sql("SELECT count(*) FROM hostile.grow_song"), "0")


if __name__ == "__main__":
    unittest.main()
