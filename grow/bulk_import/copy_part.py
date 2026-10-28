import gzip
from collections.abc import Callable
from typing import IO

from django.db import connection, models, transaction
from psycopg import generators
from psycopg.abc import Buffer
from psycopg.copy import LibpqWriter
from rest_framework.exceptions import ValidationError

# psycopg's own cap on one `put_copy_data` call (larger ones can loop forever in libpq).
CHUNK_SIZE = 128 * 1024


class FlushingWriter(LibpqWriter):
    """
    Waits for each chunk to reach the server. psycopg only flushes COPY data on macOS: elsewhere the nonblocking
    libpq connection grows its output buffer with whatever the server has not consumed yet, so a server slower than
    the client buffers up to the whole part in the API worker.
    """

    def write(self, data: Buffer) -> None:
        for start in range(0, len(data), CHUNK_SIZE):
            self.connection.wait(
                generators.copy_to(self.connection.pgconn, data[start : start + CHUNK_SIZE], flush=True)
            )


@transaction.atomic
def copy_part(
    staging_model: type[models.Model],
    columns: tuple[str, ...],
    row: Callable[[int, bytes], tuple],
    run_id: int,
    part: int,
    body: IO[bytes],
) -> int:
    """Replaces part `part` of run `run_id` with the gzip NDJSON `body`, each line validated by `row` and streamed
    into `staging_model`'s `columns` with `COPY`."""
    staging_model._default_manager.filter(run_id=run_id, part=part).delete()
    count = 0
    with (
        connection.cursor() as cursor,
        cursor.copy(  # type: ignore[attr-defined]
            f"COPY {staging_model._meta.db_table} (run_id, part, {', '.join(columns)}) FROM STDIN",
            writer=FlushingWriter(cursor.cursor),
        ) as copy,
    ):
        try:
            for line_number, line in enumerate(gzip.GzipFile(fileobj=body, mode="rb"), 1):
                if line.strip():
                    copy.write_row((run_id, part, *row(line_number, line)))
                    count += 1
        except (OSError, EOFError) as e:
            raise ValidationError(f"body is not valid gzip ({e})") from e
    return count
