"""Trusted catalogue-only restore planning and verification.

Never restore a complete production dump and then attach a candidate. Select
data before restore; verify an operator-reviewed schema and an exact column
allowlist before loading rows, then verify ownership and denied-table emptiness.
"""

import hashlib
import re
from dataclasses import dataclass

from .manifest import exact_keys, matching, positive_integer

IDENTIFIER = r"[a-z][a-z0-9_]{0,62}"
FORBIDDEN_DATA = re.compile(
    r"(?:^|_)(?:auth|user|history|session|task|schedule|ormq|curation|staging|payload|attempt|receipt|part)(?:_|$)"
)


@dataclass(frozen=True)
class TablePolicy:
    columns: tuple[str, ...]
    null_columns: tuple[str, ...]
    minimum_rows: int

    @classmethod
    def parse(cls, raw: object) -> TablePolicy:
        value = exact_keys(raw, {"columns", "null_columns", "minimum_rows"})
        columns = value["columns"]
        null_columns = value["null_columns"]
        for names in (columns, null_columns):
            if not isinstance(names, list) or len(names) != len(set(names)):
                raise ValueError("column lists must contain unique identifiers")
            for name in names:
                matching(name, IDENTIFIER, "column")
        if not columns or not set(null_columns) <= set(columns):
            raise ValueError("invalid column allowlist")
        if "user_id" in columns and "user_id" not in null_columns:
            raise ValueError("user ownership must be verified absent")
        return cls(
            tuple(columns),
            tuple(null_columns),
            positive_integer(value["minimum_rows"], "minimum row count", 0, 2**63 - 1),
        )


@dataclass(frozen=True)
class Policy:
    schema_sha256: str
    tables: dict[str, TablePolicy]
    all_columns: dict[str, tuple[str, ...]] | None = None

    @classmethod
    def parse(cls, raw: object) -> Policy:
        value = exact_keys(raw, {"version", "schema_sha256", "tables"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported sanitization version")
        if not isinstance(value["tables"], dict) or not value["tables"]:
            raise ValueError("nonempty catalogue table allowlist required")
        tables = {}
        for name, raw_table in value["tables"].items():
            matching(name, IDENTIFIER, "table")
            if FORBIDDEN_DATA.search(name):
                raise ValueError("private or operational table cannot be allowlisted")
            tables[name] = TablePolicy.parse(raw_table)
        if "grow_song" not in tables or tables["grow_song"].minimum_rows < 30_000_000:
            raise ValueError("full catalogue qualification requires at least 30 million songs")
        return cls(matching(value["schema_sha256"], r"[0-9a-f]{64}", "schema digest"), tables)

    def verify_schema(self, schema_sql: bytes, columns: dict[str, list[str]]) -> None:
        if hashlib.sha256(schema_sql).hexdigest() != self.schema_sha256:
            raise ValueError("schema SQL differs from the operator-reviewed schema")
        if self.all_columns is not None and columns != {name: list(names) for name, names in self.all_columns.items()}:
            raise ValueError("complete database column inventory differs from review")
        for name, table in self.tables.items():
            if columns.get(name) != list(table.columns):
                raise ValueError(f"schema drift in allowlisted table {name}")

    def data_toc(self, toc: str) -> str:
        """Select only reviewed TABLE DATA entries, never blobs or materialized data.

        Schema and migration-history compatibility are separate trusted phases.
        The returned list is for pg_restore --data-only --use-list, not a schema
        restore. Sequence counters must be reset by a trusted phase afterwards.
        """
        selected = []
        seen = set()
        for line in toc.splitlines():
            if not line or line.startswith(";"):
                continue
            match = re.fullmatch(r"[0-9]+; [0-9]+ [0-9]+ TABLE DATA public (\S+) \S+", line)
            if match is None:
                if " TABLE DATA " in line and any(f" {name} " in line for name in self.tables):
                    raise ValueError("unsupported catalogue TOC entry")
                continue
            name = match[1]
            if name in self.tables:
                if name in seen:
                    raise ValueError("duplicate catalogue TOC entry")
                seen.add(name)
                selected.append(line)
        if seen != self.tables.keys():
            raise ValueError("backup does not contain the exact approved catalogue table set")
        return "\n".join(selected) + "\n"

    def verify_rows(self, counts: dict[str, int], nonnull: dict[str, dict[str, int]]) -> None:
        """Called by trusted code after restore, before any candidate is created."""
        if self.all_columns is not None and counts.keys() != self.all_columns.keys():
            raise ValueError("complete database row inventory differs from review")
        if not set(self.tables) <= counts.keys():
            raise ValueError("catalogue row inventory is incomplete")
        for name, count in counts.items():
            positive_integer(count, "row count", 0, 2**63 - 1)
            if name not in self.tables:
                if count:
                    raise ValueError(f"unapproved table contains data: {name}")
                continue
            policy = self.tables[name]
            if count < policy.minimum_rows:
                raise ValueError(f"catalogue is incomplete: {name}")
            observed = nonnull.get(name)
            if not isinstance(observed, dict) or observed.keys() != set(policy.null_columns):
                raise ValueError(f"ownership inventory is incomplete: {name}")
            if any(type(number) is not int or number != 0 for number in observed.values()):
                raise ValueError(f"private ownership or data found in {name}")

    def ownership_queries(self) -> dict[str, str]:
        return {
            name: "SELECT "
            + ", ".join(
                f'count(*) FILTER (WHERE "{column}" IS NOT NULL) AS "{column}"' for column in table.null_columns
            )
            + f' FROM public."{name}"'
            for name, table in self.tables.items()
            if table.null_columns
        }
