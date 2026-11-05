from django.db import migrations

QUALIFIED = """CREATE OR REPLACE FUNCTION public.grow_search_norm(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT pg_catalog.lower(public.unaccent('public.unaccent'::pg_catalog.regdictionary, $1)) $$"""
LEGACY = """CREATE OR REPLACE FUNCTION public.grow_search_norm(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT lower(unaccent('unaccent'::regdictionary, $1)) $$"""


def replace(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regprocedure('public.grow_search_norm(text)'), "
            "to_regprocedure('public.unaccent(regdictionary,text)'), "
            "(SELECT d.oid FROM pg_catalog.pg_ts_dict d JOIN pg_catalog.pg_namespace n ON n.oid = d.dictnamespace "
            "WHERE n.nspname = 'public' AND d.dictname = 'unaccent')"
        )
        if any(value is None for value in cursor.fetchone()):
            raise RuntimeError("Expected public.grow_search_norm(text) and public.unaccent function and dictionary")
    schema_editor.execute(QUALIFIED)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(LEGACY)


class Migration(migrations.Migration):
    dependencies = [("grow", "0100_forced_canonical_genres_list")]
    operations = [migrations.RunPython(replace, reverse)]
