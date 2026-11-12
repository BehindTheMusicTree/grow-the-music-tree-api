from collections import defaultdict
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from grow.curation.edges import edge_field, find_rule_by_legacy
from grow.curation.lists import EDGE_PROJECTION_LISTS
from grow.curation.rows import InvalidRow, RowConflict, check_edit, lock_writes
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.curation.GenreEdgeRule import GenreEdgeRule

LEGACY_EDGE_LISTS = frozenset(EDGE_PROJECTION_LISTS)


def _is_edge_item(item: dict[str, Any]) -> bool:
    return item.get("rule_id") is not None or item.get("list") in LEGACY_EDGE_LISTS


def _rule_of(item: dict[str, Any]) -> GenreEdgeRule | None:
    """The edge rule a reported item designates, by id or by legacy `(list, key)`; none once an admin removed it."""
    if item.get("rule_id") is not None:
        return GenreEdgeRule.objects.filter(user=None, uuid=item["rule_id"]).first()
    return find_rule_by_legacy(item["list"], item["key"])


def _remap_edges(remaps: list[dict[str, Any]], review: list[dict[str, Any]]) -> int:
    """Rewrites the redirected ids of edge rules; a remap clashing with another rule goes to `review`."""
    by_rule: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for remap in remaps:
        rule = _rule_of(remap)
        if rule is not None:
            by_rule[rule.pk].append({**remap, "rule": rule})
    remapped = 0
    for rule_remaps in by_rule.values():
        rule = GenreEdgeRule.objects.get(pk=rule_remaps[0]["rule"].pk)
        applied = [r for r in rule_remaps if getattr(rule, edge_field(r["column"])) == r["from"]]
        if not applied:
            continue
        changes = {edge_field(r["column"]): r["to"] for r in applied}
        try:
            with transaction.atomic():
                GenreEdgeRule.objects.update_instance(rule, actor=None, **changes)
        except ValidationError, InvalidRow:
            review += [
                {
                    "rule": rule,
                    "column": r["column"],
                    "item_id": r["from"],
                    "reason": CurationReviewItem.Reason.REDIRECT_CONFLICT,
                    "target": r["to"],
                }
                for r in applied
            ]
            continue
        remapped += len(applied)
    return remapped


@transaction.atomic
def apply_wikidata_resolutions(remaps: list[dict[str, Any]], review: list[dict[str, Any]]) -> dict[str, int]:
    """Rewrites each entry's redirected item ids (history actor null: the pipeline), then replaces the review items
    with `review` plus the remaps clashing with another entry (the region map's synthetic overview alerts are left alone). A remap whose entry or `from` id is gone is skipped:
    an admin already fixed it."""
    entries = CurationEntry.objects.filter(user=None)
    lock_writes(entries)
    review = list(review)
    edge_remaps = [r for r in remaps if _is_edge_item(r)]
    remaps = [r for r in remaps if not _is_edge_item(r)]
    by_entry: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for remap in remaps:
        by_entry[remap["list"], remap["key"]].append(remap)
    remapped = _remap_edges(edge_remaps, review)
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
    CurationReviewItem.objects.exclude(reason__in=CurationReviewItem.SYNTHETIC_OVERVIEW_REASONS).delete()
    review_items = [item for item in map(_review_item, review) if item is not None]
    CurationReviewItem.objects.bulk_create(review_items)
    return {"remapped_count": remapped, "review_count": len(review_items)}


def _review_item(item: dict[str, Any]) -> CurationReviewItem | None:
    if "rule" in item or _is_edge_item(item):
        rule = item.get("rule") or _rule_of(item)
        if rule is None:
            return None
        return CurationReviewItem(
            rule=rule,
            column=item["column"],
            item_id=item["item_id"],
            reason=item["reason"],
            target_item_id=item.get("target"),
            evidence=item.get("evidence"),
        )
    return CurationReviewItem(
        list_name=item["list"],
        key=item["key"],
        column=item["column"],
        item_id=item["item_id"],
        reason=item["reason"],
        target_item_id=item.get("target"),
        evidence=item.get("evidence"),
    )
