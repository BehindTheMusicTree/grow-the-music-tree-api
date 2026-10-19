from collections import defaultdict
from typing import Any

from django.db import transaction

from grow.curation.rows import InvalidRow, RowConflict, check_edit, lock_writes
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationReviewItem import CurationReviewItem


@transaction.atomic
def apply_wikidata_resolutions(remaps: list[dict[str, Any]], review: list[dict[str, Any]]) -> dict[str, int]:
    """Rewrites each entry's redirected item ids (history actor null: the pipeline), then replaces the review items
    with `review` plus the remaps clashing with another entry. A remap whose entry or `from` id is gone is skipped:
    an admin already fixed it."""
    entries = CurationEntry.objects.filter(user=None)
    lock_writes(entries)
    review = list(review)
    by_entry: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for remap in remaps:
        by_entry[remap["list"], remap["key"]].append(remap)
    remapped = 0
    for (list_name, key), entry_remaps in by_entry.items():
        entry = entries.filter(list_name=list_name, key=key).first()
        if entry is None:
            continue
        row = entry.row
        applied = [r for r in entry_remaps if row[r["column"]] == r["from"]]
        if not applied:
            continue
        row.update({r["column"]: r["to"] for r in applied})
        try:
            parsed = check_edit(entries, list_name, row, exclude_pk=entry.pk)
        except InvalidRow, RowConflict:
            review += [
                {
                    "list": list_name,
                    "key": key,
                    "column": r["column"],
                    "item_id": r["from"],
                    "reason": CurationReviewItem.Reason.REDIRECT_CONFLICT,
                    "target": r["to"],
                }
                for r in applied
            ]
            continue
        CurationEntry.objects.update_instance(entry, actor=None, key=parsed.key, values=parsed.values)
        remapped += len(applied)
    CurationReviewItem.objects.all().delete()
    CurationReviewItem.objects.bulk_create(
        CurationReviewItem(
            list_name=item["list"],
            key=item["key"],
            column=item["column"],
            item_id=item["item_id"],
            reason=item["reason"],
            target_item_id=item.get("target"),
        )
        for item in review
    )
    return {"remapped_count": remapped, "review_count": len(review)}
