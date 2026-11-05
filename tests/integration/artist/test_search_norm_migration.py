import hashlib
import importlib
import os
import subprocess
import uuid

import psycopg
import pytest
from django.db import connection, transaction
from psycopg import sql

from grow.model.artist.Artist import Artist


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_search_norm_migration_preserves_results_and_dependencies():
    migration = importlib.import_module("grow.migrations.0101_qualify_search_norm")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_userbyid(proowner), proacl FROM pg_proc WHERE oid = 'public.grow_search_norm(text)'::regprocedure"
        )
        before = cursor.fetchone()
        cursor.execute("SELECT public.grow_search_norm(value) FROM unnest(ARRAY['Björk', 'ÉCOLE', '', NULL]) AS value")
        expected = cursor.fetchall()
        cursor.execute("SELECT count(*) FROM pg_depend WHERE refobjid = 'public.grow_search_norm(text)'::regprocedure")
        dependencies = cursor.fetchone()
    with connection.schema_editor() as editor:
        migration.reverse(None, editor)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT public.grow_search_norm(value) FROM unnest(ARRAY['Björk', 'ÉCOLE', '', NULL]) AS value"
            )
            assert cursor.fetchall() == expected
        migration.replace(None, editor)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_userbyid(proowner), proacl FROM pg_proc WHERE oid = 'public.grow_search_norm(text)'::regprocedure"
        )
        assert cursor.fetchone() == before
        cursor.execute("SELECT count(*) FROM pg_depend WHERE refobjid = 'public.grow_search_norm(text)'::regprocedure")
        assert cursor.fetchone() == dependencies
        cursor.execute("SET LOCAL search_path = ''")
        cursor.execute(
            "SELECT public.grow_search_norm(value) FROM pg_catalog.unnest(ARRAY['Björk', 'ÉCOLE', '', NULL]) AS value"
        )
        assert cursor.fetchall() == expected == [("bjork",), ("ecole",), ("",), (None,)]


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_custom_archive_restores_generated_artist_columns(tmp_path):
    artist = Artist.objects.create(name="Björk")
    artist.aliases.create(name="ÉCOLE")
    settings = connection.settings_dict
    env = os.environ.copy()
    env.update(
        PGHOST=settings["HOST"],
        PGPORT=str(settings["PORT"]),
        PGUSER=settings["USER"],
        PGPASSWORD=settings["PASSWORD"],
    )
    source = settings["NAME"]
    destination = "grow_restore_" + uuid.uuid4().hex
    archive = tmp_path / "backup.dump"
    admin = psycopg.connect(
        dbname=source,
        host=settings["HOST"],
        port=settings["PORT"],
        user=settings["USER"],
        password=settings["PASSWORD"],
        autocommit=True,
    )
    try:
        admin.execute(sql.SQL("CREATE DATABASE {} ").format(sql.Identifier(destination)))
        subprocess.run(["pg_dump", "-Fc", "-f", str(archive), source], env=env, check=True, capture_output=True)
        subprocess.run(
            ["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "-d", destination, str(archive)],
            env=env,
            check=True,
            capture_output=True,
        )
        with psycopg.connect(
            dbname=destination,
            host=settings["HOST"],
            port=settings["PORT"],
            user=settings["USER"],
            password=settings["PASSWORD"],
        ) as restored:
            assert restored.execute("SELECT name, folded_name FROM grow_artist WHERE name = 'Björk'").fetchall() == [
                ("Björk", "bjork")
            ]
            assert restored.execute("SELECT name, folded_name FROM grow_artist_alias").fetchall() == [
                ("ÉCOLE", "ecole")
            ]
            assert (
                restored.execute(
                    "SELECT count(*) FROM pg_index WHERE indexrelid IN "
                    "(SELECT oid FROM pg_class WHERE relname IN ('grow_artist_folded_name_trgm', 'grow_artist_alias_folded_name_trgm')) "
                    "AND indisvalid"
                ).fetchone()[0]
                == 2
            )
        migration = importlib.import_module("grow.migrations.0101_qualify_search_norm")
        try:
            with connection.schema_editor() as editor:
                migration.reverse(None, editor)
            subprocess.run(["pg_dump", "-Fc", "-f", str(archive), source], env=env, check=True, capture_output=True)
        finally:
            with connection.schema_editor() as editor:
                migration.replace(None, editor)
        digest = hashlib.sha256(archive.read_bytes()).digest()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(destination)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(destination)))
        command = ["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "-d", destination]
        failed = subprocess.run([*command, str(archive)], env=env, capture_output=True, check=False)
        assert failed.returncode != 0
        assert b"dictionary" in failed.stderr and b"unaccent" in failed.stderr
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(destination)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(destination)))
        toc = subprocess.run(["pg_restore", "--list", str(archive)], check=True, capture_output=True, text=True).stdout
        entries = [line for line in toc.splitlines() if line and not line.startswith(";")]
        matches = [i for i, line in enumerate(entries) if " FUNCTION public grow_search_norm(text) " in line]
        assert len(matches) == 1
        split = matches[0] + 1
        assert any(" EXTENSION - unaccent " in line for line in entries[:split])
        assert any(" TABLE public grow_artist " in line for line in entries[split:])
        prefix, remainder = tmp_path / "prefix.toc", tmp_path / "remainder.toc"
        prefix.write_text("\n".join(entries[:split]) + "\n")
        remainder.write_text("\n".join(entries[split:]) + "\n")
        subprocess.run([*command, "--use-list", str(prefix), str(archive)], env=env, check=True, capture_output=True)
        with psycopg.connect(
            dbname=destination,
            host=settings["HOST"],
            port=settings["PORT"],
            user=settings["USER"],
            password=settings["PASSWORD"],
        ) as restored:
            restored.execute(migration.QUALIFIED)
        subprocess.run([*command, "--use-list", str(remainder), str(archive)], env=env, check=True, capture_output=True)
        with psycopg.connect(
            dbname=destination,
            host=settings["HOST"],
            port=settings["PORT"],
            user=settings["USER"],
            password=settings["PASSWORD"],
        ) as restored:
            assert restored.execute("SELECT name, folded_name FROM grow_artist").fetchall() == [("Björk", "bjork")]
            assert restored.execute("SELECT name, folded_name FROM grow_artist_alias").fetchall() == [
                ("ÉCOLE", "ecole")
            ]
        assert hashlib.sha256(archive.read_bytes()).digest() == digest
    finally:
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(destination)))
        admin.close()
