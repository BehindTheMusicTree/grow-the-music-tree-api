"""Execute approved catalogue restoration before granting candidate access.

The trusted controller supplies an isolated PostgreSQL transport and holds
admission, supervision and bounded storage for the entire operation. This stage
never grants database access or certifies migrations, derived data or a benchmark.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from .catalogue_restore import (
    SCHEMA,
    data_policy,
    inventory_sql,
    projection_sql,
    relation_inventory_sql,
    verify_inventory,
)
from .manifest import exact_keys, matching


class Postgres(Protocol):
    """Transport bound by the controller to one disposable database and archive.

    run() executes a trusted utility with argv and stdin, raises on any nonzero
    exit, and returns stdout. It must not select an endpoint from inherited PG*
    variables. The archive is immutable at /restore/backup.dump. Candidates must
    have no connection or filesystem access until all preparation is complete.
    """

    def run(self, program: str, arguments: list[str], stdin: str | None = None) -> str: ...


@dataclass(frozen=True)
class Approval:
    backup_sha256: str
    pre_data_sha256: str
    post_data_sha256: str

    @classmethod
    def parse(cls, raw: object) -> Approval:
        value = exact_keys(raw, {"version", "backup_sha256", "pre_data_sha256", "post_data_sha256"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported restore approval version")
        return cls(*(matching(value[name], r"[0-9a-f]{64}", name) for name in cls.__dataclass_fields__))

    def verify(self, pre_data: bytes, post_data: bytes) -> None:
        for name, content in (("pre_data", pre_data), ("post_data", post_data)):
            if not content or hashlib.sha256(content).hexdigest() != getattr(self, f"{name}_sha256"):
                raise ValueError(f"{name} SQL differs from independent operator approval")


def sql(database: Postgres, query: str) -> str:
    return database.run(
        "psql", ["-X", "--no-password", "--dbname=btmt_grow_perf", "-Atq", "--set=ON_ERROR_STOP=1"], query
    ).strip()


def observations(database: Postgres, policy) -> tuple[dict, dict]:
    counts = {}
    ownership = {}
    for name in sorted(verify_inventory(SCHEMA.read_text())):
        table = policy.tables.get(name)
        nulls = () if table is None else table.null_columns
        fields = ["count(*)"] + [f'count(*) FILTER (WHERE "{column}" IS NOT NULL)' for column in nulls]
        # Count ownership and total rows in one scan of each retained table.
        result = sql(database, "SELECT json_build_array(" + ", ".join(fields) + f') FROM public."{name}";')
        values = json.loads(result)
        if not isinstance(values, list) or len(values) != 1 + len(nulls):
            raise ValueError("invalid trusted catalogue observations")
        counts[name] = values[0]
        if table is not None:
            ownership[name] = dict(zip(nulls, values[1:], strict=True))
    return counts, ownership


def repair_sequences_sql() -> str:
    # Sequence ownership is recorded as a dependency for both serial and
    # identity columns. Never load a production SEQUENCE SET TOC entry.
    return """
DO $$ DECLARE item record; highest bigint; BEGIN
  FOR item IN
    SELECT s.oid AS sequence_id, n.nspname AS schema_name, t.relname AS table_name,
           a.attname AS column_name, q.seqstart, q.seqincrement, q.seqcycle
    FROM pg_catalog.pg_class s
    JOIN pg_catalog.pg_sequence q ON q.seqrelid=s.oid
    JOIN pg_catalog.pg_depend d ON d.classid='pg_catalog.pg_class'::regclass
      AND d.objid=s.oid AND d.refclassid='pg_catalog.pg_class'::regclass
      AND d.deptype IN ('a', 'i')
    JOIN pg_catalog.pg_class t ON t.oid=d.refobjid
    JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
    WHERE n.nspname='public' AND s.relkind='S'
  LOOP
    IF item.seqincrement <> 1 OR item.seqcycle THEN
      RAISE EXCEPTION 'unsupported catalogue sequence';
    END IF;
    EXECUTE format('SELECT max(%I) FROM %I.%I', item.column_name, item.schema_name, item.table_name)
      INTO highest;
    PERFORM pg_catalog.setval(item.sequence_id,
      greatest(coalesce(highest, item.seqstart), item.seqstart), highest IS NOT NULL);
  END LOOP;
END $$;
"""


def restore(database: Postgres, approval: Approval, pre_data: bytes, post_data: bytes) -> dict:
    """Return projected-data evidence; failures leave the database inaccessible.

    Approval must come from a separately reviewed root-owned configuration,
    never hashes generated from these artifacts by the restore invocation.
    Failures require discarding this database; retries always use a fresh one.
    """
    approval.verify(pre_data, post_data)
    # Verify the bytes at the transport's mounted path, not a different host copy.
    digest = database.run("sha256sum", ["/restore/backup.dump"]).split()
    if len(digest) != 2 or digest[0] != approval.backup_sha256 or digest[1] != "/restore/backup.dump":
        raise ValueError("restore archive differs from independent operator approval")
    identity = json.loads(
        sql(
            database,
            "SELECT json_build_array(current_database(), current_setting('server_version_num')::int, "
            "(SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_toast' "
            "AND c.relkind IN ('r','p','v','m','f','S')), "
            "(SELECT count(*) FROM pg_catalog.pg_stat_activity "
            "WHERE datname=current_database() AND pid<>pg_backend_pid()));",
        )
    )
    if (
        not isinstance(identity, list)
        or len(identity) != 4
        or identity[0] != "btmt_grow_perf"
        or type(identity[1]) is not int
        or not 160000 <= identity[1] < 170000
        or identity[2:] != [0, 0]
    ):
        raise ValueError("restore requires a fresh, exclusive PostgreSQL 16 scratch database")
    policy = data_policy(SCHEMA.read_text(), pre_data + post_data)
    toc = database.run("pg_restore", ["--list", "/restore/backup.dump"])
    selected = policy.data_toc(toc)
    sql(database, "REVOKE ALL ON DATABASE btmt_grow_perf FROM PUBLIC;")
    sql(database, pre_data.decode("utf-8"))
    observed = sql(database, inventory_sql())
    verify_inventory(observed)
    database.run(
        "pg_restore",
        [
            "--dbname=btmt_grow_perf",
            "--no-password",
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-privileges",
            "--data-only",
            "--use-list=/dev/stdin",
            "/restore/backup.dump",
        ],
        selected,
    )
    sql(database, projection_sql(observed))
    counts, ownership = observations(database, policy)
    policy.verify_rows(counts, ownership)
    sql(database, post_data.decode("utf-8"))
    # An approved post-data script must not silently replace the reviewed layout
    # or inject rows. Validate again before any downstream preparation.
    sql(database, relation_inventory_sql())
    verify_inventory(sql(database, inventory_sql()))
    counts, ownership = observations(database, policy)
    policy.verify_rows(counts, ownership)
    sql(database, repair_sequences_sql())
    invalid = sql(
        database,
        "SELECT (SELECT count(*) FROM pg_catalog.pg_index WHERE NOT indisvalid OR NOT indisready) + "
        "(SELECT count(*) FROM pg_catalog.pg_constraint WHERE NOT convalidated);",
    )
    if invalid != "0":
        raise ValueError("restore contains unvalidated constraints or invalid indexes")
    return {
        "version": 1,
        "status": "projected",
        "backup_sha256": approval.backup_sha256,
        "pre_data_sha256": approval.pre_data_sha256,
        "post_data_sha256": approval.post_data_sha256,
        "data_toc_sha256": hashlib.sha256(selected.encode()).hexdigest(),
        "row_counts": counts,
    }
