import hashlib
from typing import IO

from django.db import models
from rest_framework.exceptions import ValidationError

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportPart import ImportPart


def record_part(*, run: BulkImportRun, stream: str, part: int, count: int, body: IO[bytes]) -> None:
    """Call under the run lock, in the transaction that replaced this staging part."""
    body.seek(0)
    digest = hashlib.file_digest(body, "sha256").hexdigest()
    ImportPart.objects.update_or_create(
        run=run, stream=stream, part=part, defaults={"row_count": count, "sha256": digest}
    )


def require_complete_parts(run: BulkImportRun, streams: dict[str, tuple[type[models.Model], int]]) -> None:
    """Validate both the logged upload receipt and current staging contents before publication.

    A PostgreSQL crash truncates unlogged tables, while the receipts remain. An empty uploaded
    part is valid; a part whose nonempty staging rows disappeared must be uploaded again.
    """
    receipts: dict[str, dict[int, int]] = {stream: {} for stream in streams}
    for receipt in run.parts.all():
        if receipt.stream not in streams or not 0 <= receipt.part < streams[receipt.stream][1]:
            raise ValidationError("Import parts are incomplete; upload every declared part before committing")
        receipts[receipt.stream][receipt.part] = receipt.row_count
    if any(len(receipts[stream]) != count for stream, (_, count) in streams.items()):
        raise ValidationError("Import parts are incomplete; upload every declared part before committing")
    for stream, (model, _) in streams.items():
        staged = dict(
            model._default_manager.filter(run_id=run.pk)
            .values("part")
            .annotate(count=models.Count("pk"))
            .values_list("part", "count")
        )
        if any(staged.get(part, 0) != count for part, count in receipts[stream].items()) or (
            staged.keys() - receipts[stream].keys()
        ):
            raise ValidationError({stream: "Staged parts were lost or changed; upload the declared parts again"})
