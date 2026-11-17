"""Trusted privilege boundary applied after preparation, before API access.

The adapter restarts PostgreSQL with HBA below mounted read-only, then probes
fresh connections. Default transaction_read_only alone is not an access boundary:
an untrusted session can turn it off.
"""

APP_ROLE = "grow_perf_app"
OWNER_ROLE = "grow_perf_owner"
DATABASE = "btmt_grow_perf"
OWNER_HBA = "local btmt_grow_perf grow_perf_owner trust\nlocal all all reject\n"
PREPARATION_HBA = "local btmt_grow_perf postgres trust\nlocal all all reject\n"
CANDIDATE_HBA = "local btmt_grow_perf grow_perf_app trust\nlocal all all reject\n"

# Trusted preparation runs as postgres, but the candidate must neither inherit
# its privileges nor invoke a definer function that can recover private tuples.
HANDOFF_SQL = """
BEGIN;
SET LOCAL search_path = pg_catalog;
DO $handoff$
DECLARE item record;
BEGIN
    IF current_database() <> 'btmt_grow_perf' THEN
        RAISE EXCEPTION 'handoff requires the benchmark database';
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'grow_perf_app') THEN
        RAISE EXCEPTION 'application role must be newly created';
    END IF;
    IF EXISTS (
        SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ) THEN
        RAISE EXCEPTION 'unapproved security-definer routine';
    END IF;
    IF EXISTS (SELECT FROM pg_foreign_table) THEN
        RAISE EXCEPTION 'foreign tables are forbidden';
    END IF;
    CREATE ROLE grow_perf_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8;
    FOR item IN SELECT datname FROM pg_database LOOP
        EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', item.datname);
    END LOOP;
    FOR item IN SELECT nspname FROM pg_namespace
        WHERE nspname NOT IN ('pg_catalog', 'information_schema')
          AND nspname !~ '^pg_' LOOP
        EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', item.nspname);
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM PUBLIC', item.nspname);
        EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM PUBLIC', item.nspname);
        EXECUTE format('REVOKE ALL ON ALL ROUTINES IN SCHEMA %I FROM PUBLIC', item.nspname);
    END LOOP;
    FOR item IN SELECT oid FROM pg_largeobject_metadata LOOP
        EXECUTE format('REVOKE ALL ON LARGE OBJECT %s FROM PUBLIC', item.oid);
    END LOOP;
    -- Large-object creators need no table privileges; descriptor-based entry
    -- points and logical messages can also write after read_only is disabled.
    -- Match C implementations as well as names to cover alternate entry points.
    FOR item IN SELECT p.oid::regprocedure AS signature
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'pg_catalog' AND (
            p.proname ~ '^(lo_|loread$|lowrite$)'
            OR p.prosrc ~ '^be_lo'
            OR p.proname IN ('pg_logical_emit_message', 'pg_notify')
            OR p.prosrc ~ '^(pg_logical_emit_message|pg_notify)'
        ) LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', item.signature);
    END LOOP;
END
$handoff$;
GRANT CONNECT ON DATABASE btmt_grow_perf TO grow_perf_app;
GRANT USAGE ON SCHEMA public TO grow_perf_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grow_perf_app;
ALTER ROLE grow_perf_app SET search_path = pg_catalog, public;
ALTER ROLE grow_perf_app SET default_transaction_read_only = on;
COMMIT;
"""

ROLE_PROOF_SQL = """
SELECT current_database() = 'btmt_grow_perf'
   AND current_user = 'grow_perf_app'
   AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR rolinherit)
   AND NOT EXISTS (SELECT FROM pg_auth_members WHERE member = pg_roles.oid)
   AND (SELECT coalesce(array_agg(setting ORDER BY setting), '{}')
          FROM pg_db_role_setting s, unnest(s.setconfig) setting
          WHERE s.setrole = pg_roles.oid AND s.setdatabase = 0)
       = ARRAY['default_transaction_read_only=on', 'search_path=pg_catalog, public']
FROM pg_roles WHERE rolname = current_user;
"""

# Restore runs as postgres; the side's own preparation code must not. Ownership
# moves to a NOSUPERUSER role that is locked out again before the handoff.
OWNERSHIP_SQL = """
CREATE ROLE grow_perf_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8;
ALTER DATABASE btmt_grow_perf OWNER TO grow_perf_owner;
DO $ownership$
DECLARE item record;
BEGIN
    -- REASSIGN OWNED is refused for the bootstrap superuser (it owns system
    -- objects), so user objects are moved one by one; extension members stay.
    FOR item IN
        SELECT 'ALTER SCHEMA ' || quote_ident(nspname) || ' OWNER TO grow_perf_owner' AS command, 0 AS rank
          FROM pg_namespace
         WHERE nspowner = 'postgres'::regrole AND nspname NOT LIKE 'pg^_%' ESCAPE '^'
           AND nspname <> 'information_schema'
        UNION ALL
        SELECT 'ALTER ' || CASE c.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW'
                   WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END
               || ' ' || c.oid::regclass || ' OWNER TO grow_perf_owner', 1
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relowner = 'postgres'::regrole AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
           AND n.nspname <> 'information_schema'
           AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
           AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('e', 'a'))
        UNION ALL
        SELECT 'ALTER ' || CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END
               || ' ' || p.oid::regprocedure || ' OWNER TO grow_perf_owner', 2
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE p.proowner = 'postgres'::regrole AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
           AND n.nspname <> 'information_schema'
           AND p.prokind IN ('f', 'p')
           AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
        UNION ALL
        SELECT 'ALTER TYPE ' || t.oid::regtype || ' OWNER TO grow_perf_owner', 3
          FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE t.typowner = 'postgres'::regrole AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
           AND n.nspname <> 'information_schema'
           AND t.typtype IN ('e', 'd', 'r', 'm')
           AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = t.oid AND d.deptype = 'e')
        ORDER BY 2
    LOOP
        EXECUTE item.command;
    END LOOP;
END
$ownership$;
"""

OWNER_LOCK_SQL = "ALTER ROLE grow_perf_owner NOLOGIN;"
