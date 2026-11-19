"""Account for data work separately from the exact snapshot protocol."""

from dataclasses import dataclass

SNAPSHOT_ISOLATION = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"


@dataclass(frozen=True)
class QueryCounts:
    statements: tuple[str, ...]
    data: tuple[str, ...]
    control: tuple[str, ...]

    @classmethod
    def from_queries(cls, queries):
        data, control, statements = [], [], []
        for query in queries:
            sql = query["sql"].strip().rstrip(";")
            normalized = " ".join(sql.upper().split())
            statements.append(normalized)
            if normalized in {"BEGIN", "COMMIT", "ROLLBACK", SNAPSHOT_ISOLATION} or normalized.startswith(
                ("SAVEPOINT ", "RELEASE SAVEPOINT ", "ROLLBACK TO SAVEPOINT ")
            ):
                control.append(normalized)
            else:
                data.append(sql)
        return cls(tuple(statements), tuple(data), tuple(control))

    def without_preamble(self, count: int) -> QueryCounts:
        """Drop `count` data statements issued before the snapshot opens (e.g. the reference-graph presence check)."""
        first_control = next((i for i, statement in enumerate(self.statements) if statement in self.control), 0)
        assert first_control >= count, self
        return QueryCounts(self.statements[count:], self.data[count:], self.control)

    def assert_protocol(self, *, snapshot: bool, vendor: str, transaction: bool = False):
        expected = ()
        if snapshot or transaction:
            expected = ("BEGIN", "COMMIT")
            if snapshot and vendor == "postgresql":
                expected = ("BEGIN", SNAPSHOT_ISOLATION, "COMMIT")
        assert self.control == expected, self
        assert len(self.statements) == len(self.data) + len(self.control)
        if snapshot:
            assert self.statements[: len(expected) - 1] == expected[:-1], self
            assert self.statements[-1] == "COMMIT", self
        return len(self.data)
