import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from the_music_tree_grow_contracts.curation_lists import GENRE_ALIAS_LIST

from grow.curation.genre_aliases import AliasCatalogueUnavailable, alias_catalogue, alias_revision
from grow.curation.rows import lock_writes, parse_row
from grow.model.curation.CurationEntry import CurationEntry


class Command(BaseCommand):
    help = "Simulate or apply a backfill of exact, unique legacy genre alias targets."

    def add_arguments(self, parser):
        parser.add_argument("--apply-plan", type=Path, help="Apply the JSON printed by a previous simulation.")

    @transaction.atomic
    def handle(self, *args, **options):
        entries = CurationEntry.objects.filter(user=None, list_name=GENRE_ALIAS_LIST)
        lock_writes(entries)
        try:
            publication = alias_catalogue()
        except AliasCatalogueUnavailable as error:
            raise CommandError(str(error)) from error
        by_label = defaultdict(list)
        for target in publication["targets"]:
            by_label[target["label"]].append(target["id"])
        current = {str(entry.uuid): entry for entry in entries}
        exported_on = publication["curation_exported_on"]
        plan_path = options["apply_plan"]
        if not plan_path:
            rows = []
            for uuid, entry in current.items():
                row = entry.row
                label = row["wikidata_genre_name"]
                candidates = sorted(by_label[label])
                if row["target_item_id"]:
                    status = "already_migrated"
                elif len(candidates) == 1:
                    status = "convertible"
                else:
                    status = "ambiguous" if candidates else "missing"
                rows.append(
                    {
                        "uuid": uuid,
                        "key": entry.key,
                        "revision": alias_revision(entry),
                        "label": label,
                        "candidates": candidates,
                        "status": status,
                    }
                )
            self.stdout.write(json.dumps({"curation_exported_on": exported_on, "rows": rows}, indent=2))
            return

        try:
            plan = json.loads(plan_path.read_text())
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        if plan["curation_exported_on"] != exported_on:
            raise CommandError("The catalogue changed. Generate a new simulation.")
        results = {}
        for item in plan["rows"]:
            if item["status"] != "convertible":
                continue
            uuid = item["uuid"]
            entry = current.get(uuid)
            if entry and entry.row["target_item_id"] in item["candidates"]:
                results[uuid] = "already_migrated"
                continue
            if not entry or entry.key != item["key"] or alias_revision(entry) != item["revision"]:
                results[uuid] = "changed"
                continue
            row = entry.row
            candidates = by_label[row["wikidata_genre_name"]]
            if row["target_item_id"] or row["wikidata_genre_name"] != item["label"]:
                results[uuid] = "changed"
                continue
            if len(candidates) != 1 or candidates != item["candidates"]:
                raise CommandError(f"Simulation candidate does not match the catalogue for {uuid}")
            parsed = parse_row(GENRE_ALIAS_LIST, {**row, "target_item_id": candidates[0]})
            CurationEntry.objects.update_instance(entry, values=parsed.values)
            results[uuid] = "updated"
        self.stdout.write(json.dumps(results, indent=2))
