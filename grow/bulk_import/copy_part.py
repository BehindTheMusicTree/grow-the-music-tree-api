import gzip
from collections.abc import Callable
from typing import IO

from django.db import connection, models, transaction
from rest_framework.exceptions import ValidationError


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
            f"COPY {staging_model._meta.db_table} (run_id, part, {', '.join(columns)}) FROM STDIN"
        ) as copy,
    ):
        try:
            for line_number, line in enumerate(gzip.GzipFile(fileobj=body), 1):
                if line.strip():
                    copy.write_row((run_id, part, *row(line_number, line)))
                    count += 1
        except (OSError, EOFError) as e:
            raise ValidationError(f"body is not valid gzip ({e})") from e
    return count
