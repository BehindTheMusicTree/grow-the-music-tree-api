from django.db import migrations, models
from django.db.models import F, Func

INDEX = "grow_criteria_folded_name_trgm"


# pg_trgm declares `<%` at the default cost of 1, so on a table this small the planner prefers scanning every row
# (about 35 ms for a multi-word query) over the trigram index (about 1 ms). A realistic cost makes it choose the index.
# The ORM emits `%>`, whose function is the commutator.
OPERATOR_FUNCTIONS = ("public.word_similarity_op(text, text)", "public.word_similarity_commutator_op(text, text)")


def _add_folded_name(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        # No add_field: SQLite would rebuild grow_criteria and drop its genre-tree-version triggers (0039).
        # SQLite cannot add a STORED generated column in place; VIRTUAL is equivalent for the test database.
        schema_editor.execute(
            'ALTER TABLE grow_criteria ADD COLUMN folded_name text GENERATED ALWAYS AS (grow_search_norm("name")) VIRTUAL'
        )
        return
    schema_editor.execute(
        "ALTER TABLE grow_criteria ADD COLUMN IF NOT EXISTS folded_name text "
        'GENERATED ALWAYS AS (grow_search_norm("name")) STORED'
    )
    schema_editor.execute(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON grow_criteria USING gin (folded_name gin_trgm_ops)"
    )
    for function in OPERATOR_FUNCTIONS:
        schema_editor.execute(f"ALTER FUNCTION {function} COST 1000")


def _drop_folded_name(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.execute("ALTER TABLE grow_criteria DROP COLUMN folded_name")
        return
    for function in OPERATOR_FUNCTIONS:
        schema_editor.execute(f"ALTER FUNCTION {function} COST 1")
    schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
    schema_editor.execute("ALTER TABLE grow_criteria DROP COLUMN IF EXISTS folded_name")


class Migration(migrations.Migration):
    # Non-atomic for CONCURRENTLY; idempotent because it can die between the column and the index (see 0075).
    # grow_criteria is small (~6k rows), so the table rewrite is brief.
    atomic = False

    dependencies = [
        ("grow", "0105_alter_curationentry_list_name_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="criteria",
                    name="folded_name",
                    field=models.GeneratedField(
                        db_persist=True,
                        expression=Func(F("_name"), function="grow_search_norm"),
                        output_field=models.TextField(),
                    ),
                ),
            ],
            database_operations=[migrations.RunPython(_add_folded_name, _drop_folded_name)],
        ),
    ]
