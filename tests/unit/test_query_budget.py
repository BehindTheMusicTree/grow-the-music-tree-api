import pytest

from tests.utils.query_budget import SNAPSHOT_ISOLATION, QueryCounts


def test_only_explicit_transaction_commands_are_excluded():
    statements = ["BEGIN", "SELECT 1", "SET statement_timeout = 10", "EXPLAIN SELECT 1", "COMMIT"]
    counts = QueryCounts.from_queries([{"sql": sql} for sql in statements])
    assert counts.assert_protocol(snapshot=True, vendor="sqlite") == 3
    assert len(counts.data) + len(counts.control) == len(statements)


@pytest.mark.parametrize("command", ['SAVEPOINT "s1"', 'RELEASE SAVEPOINT "s1"', "ROLLBACK"])
def test_unexpected_transaction_control_fails(command):
    counts = QueryCounts.from_queries([{"sql": sql} for sql in ("BEGIN", command, "COMMIT")])
    with pytest.raises(AssertionError):
        counts.assert_protocol(snapshot=True, vendor="sqlite")


def test_postgres_requires_isolation_statement():
    counts = QueryCounts.from_queries([{"sql": sql} for sql in ("BEGIN", SNAPSHOT_ISOLATION, "COMMIT")])
    assert counts.assert_protocol(snapshot=True, vendor="postgresql") == 0
    with pytest.raises(AssertionError):
        counts.assert_protocol(snapshot=False, vendor="postgresql")
