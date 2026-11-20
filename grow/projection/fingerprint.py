"""
A projection table is only as good as the definition that built it. The fingerprint hashes that definition (columns,
projection SQL and the SQL routines it calls, as stored in the database), so a stored table can be compared with the
code that is deployed. Postgres-only.
"""

import hashlib


def fingerprint(cursor, *, columns: str, projection: str, functions: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(columns.encode())
    digest.update(b"\0")
    digest.update(projection.encode())
    for function in functions:
        # Read from the database, so a migration that only redefines the routine changes the fingerprint.
        cursor.execute("SELECT pg_get_functiondef(%s::regprocedure)", [function])
        digest.update(b"\0")
        digest.update(cursor.fetchone()[0].encode())
    return digest.hexdigest()
