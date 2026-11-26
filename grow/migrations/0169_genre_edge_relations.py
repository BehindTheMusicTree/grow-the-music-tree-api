from django.db import connection, migrations, models

import grow.model.curation.GenreEdgeRule

KEY_SEPARATOR = "\t"
FOLDED_LISTS = {
    "regional_memberships": ("child_item_id", "parent_item_id"),
    "genre_derivations": ("item_id", "origin_item_id"),
}
REVIEW_COLUMNS = {"child_item_id": "item_id", "parent_item_id": "target_item_id", "origin_item_id": "target_item_id"}


def _folded_relation(entry):
    """The `(relation, action)` a folded curation entry stands for."""
    if entry.list_name == "genre_derivations":
        return "derivation", "assert"
    return "classification", {"add": "assert", "prohibit": "prohibit"}[entry.values["action"]]


def _convert_rules(GenreEdgeRule):
    """Maps the former relations onto the typed triplets. `exclude_other_parents` is dropped: the parents it evicted
    come back until they are prohibited explicitly."""
    for rule in GenreEdgeRule.objects.all():
        action = {"remove": "prohibit", "add": "assert", None: "assert"}[rule.action]
        GenreEdgeRule.objects.filter(pk=rule.pk).update(
            relation="classification", action=action, decision_id=str(rule.uuid)
        )


def _fold_entry(entry, GenreEdgeRule):
    item_id, target_item_id = entry.key.split(KEY_SEPARATOR)
    relation, action = _folded_relation(entry)
    triplet = f"({item_id}, {relation}, {target_item_id})"
    if item_id == target_item_id:
        raise RuntimeError(f"{entry.list_name} {triplet}: an item can't be its own parent")
    same = GenreEdgeRule.objects.filter(item_id=item_id, relation=relation, target_item_id=target_item_id).first()
    if same is not None:
        if same.action != action:
            raise RuntimeError(
                f"{entry.list_name} {triplet} is {action} but an edge rule says {same.action}: "
                "resolve it before migrating"
            )
        if not same.reason and entry.reason:
            GenreEdgeRule.objects.filter(pk=same.pk).update(reason=entry.reason)
        return same.pk
    decision_id = entry.values.get("decision_id") or str(entry.uuid)
    if GenreEdgeRule.objects.filter(decision_id=decision_id).exists():
        raise RuntimeError(f"{entry.list_name} {triplet}: decision_id {decision_id!r} is already used by another rule")
    rule = GenreEdgeRule.objects.create(
        uuid=entry.uuid,
        user_id=entry.user_id,
        decision_id=decision_id,
        relation=relation,
        item_id=item_id,
        target_item_id=target_item_id,
        action=action,
        reason=entry.reason,
    )
    GenreEdgeRule.objects.filter(pk=rule.pk).update(created_on=entry.created_on, updated_on=entry.updated_on)
    return rule.pk


def convert_to_typed_edges(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    CurationReviewItem = apps.get_model("grow", "CurationReviewItem")
    GenreEdgeRule = apps.get_model("grow", "GenreEdgeRule")

    _convert_rules(GenreEdgeRule)
    CurationReviewItem.objects.filter(rule__isnull=False, column="parent_item_id").update(column="target_item_id")

    entries = CurationEntry.objects.filter(list_name__in=FOLDED_LISTS)
    rule_by_entry = {
        (entry.list_name, entry.key): _fold_entry(entry, GenreEdgeRule)
        for entry in entries.order_by("list_name", "key")
    }
    for review_item in CurationReviewItem.objects.filter(list_name__in=FOLDED_LISTS):
        rule_id = rule_by_entry.get((review_item.list_name, review_item.key))
        if rule_id is None:
            review_item.delete()
            continue
        review_item.rule_id = rule_id
        review_item.list_name = None
        review_item.key = None
        review_item.column = REVIEW_COLUMNS.get(review_item.column, review_item.column)
        review_item.save(update_fields=["rule", "list_name", "key", "column"])
    entries.delete()
    if connection.vendor == "postgresql":
        # Deferred FK checks queued by these writes would block the table alterations that follow in this transaction.
        connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")


def restore_untyped_edges(apps, schema_editor):
    """Schema-level reverse: classification edges become `secondary_parent` rules (the only old relation that carries
    an action); derivation and influence edges have no old shape and are dropped."""
    GenreEdgeRule = apps.get_model("grow", "GenreEdgeRule")
    GenreEdgeRule.objects.exclude(relation="classification").delete()
    for rule in GenreEdgeRule.objects.all():
        GenreEdgeRule.objects.filter(pk=rule.pk).update(
            relation="secondary_parent", action={"assert": "add", "prohibit": "remove"}[rule.action]
        )


OLD_CONSTRAINTS = (
    "genre_edge_rule_primary_unique",
    "genre_edge_rule_pair_unique",
    "genre_edge_rule_no_self_edge",
    "genre_edge_rule_parent_required",
    "genre_edge_rule_action_iff_secondary",
    "genre_edge_rule_exclude_iff_not_secondary",
)


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0168_criteria_tree_name_global"),
    ]

    operations = [
        *(migrations.RemoveConstraint(model_name="genreedgerule", name=name) for name in OLD_CONSTRAINTS),
        migrations.RenameField(model_name="genreedgerule", old_name="parent_item_id", new_name="target_item_id"),
        migrations.AddField(
            model_name="genreedgerule",
            name="decision_id",
            field=models.CharField(max_length=255, null=True),
        ),
        # Lossy reverse (schema only): the dropped `exclude_other_parents` and the folded lists are not rebuilt.
        migrations.RunPython(convert_to_typed_edges, restore_untyped_edges),
        migrations.AlterField(
            model_name="genreedgerule",
            name="decision_id",
            field=models.CharField(default=grow.model.curation.GenreEdgeRule.new_decision_id, max_length=255),
        ),
        migrations.AlterField(
            model_name="genreedgerule",
            name="relation",
            field=models.CharField(
                choices=[
                    ("classification", "Classification"),
                    ("derivation", "Derivation"),
                    ("influence", "Influence"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="genreedgerule",
            name="target_item_id",
            field=models.CharField(max_length=512),
        ),
        migrations.AlterField(
            model_name="genreedgerule",
            name="action",
            field=models.CharField(choices=[("assert", "Assert"), ("prohibit", "Prohibit")], max_length=8),
        ),
        migrations.RemoveField(
            model_name="genreedgerule",
            name="exclude_other_parents",
        ),
        migrations.AddConstraint(
            model_name="genreedgerule",
            constraint=models.UniqueConstraint(
                fields=("item_id", "relation", "target_item_id"),
                name="genre_edge_rule_triplet_unique",
                violation_error_message="A rule already exists for this item, relation and target",
            ),
        ),
        migrations.AddConstraint(
            model_name="genreedgerule",
            constraint=models.UniqueConstraint(
                fields=("decision_id",),
                name="genre_edge_rule_decision_unique",
                violation_error_message="A rule already carries this decision_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="genreedgerule",
            constraint=models.CheckConstraint(
                condition=models.Q(("item_id", models.F("target_item_id")), _negated=True),
                name="genre_edge_rule_no_self_edge",
                violation_error_message="An item can't be its own parent",
            ),
        ),
        migrations.AddConstraint(
            model_name="genreedgerule",
            constraint=models.CheckConstraint(
                condition=models.Q(("relation__in", ("classification", "derivation", "influence"))),
                name="genre_edge_rule_relation_valid",
                violation_error_message="Unknown relation",
            ),
        ),
        migrations.AddConstraint(
            model_name="genreedgerule",
            constraint=models.CheckConstraint(
                condition=models.Q(("action__in", ("assert", "prohibit"))),
                name="genre_edge_rule_action_valid",
                violation_error_message="Unknown action",
            ),
        ),
    ]
