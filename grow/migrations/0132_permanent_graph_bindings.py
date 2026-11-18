"""Preserve public genre UUID bindings independently of graph activity."""

from django.db import migrations


def install_guards(apps, schema_editor):
    criteria = apps.get_model("grow", "Criteria")._meta.db_table
    genre = apps.get_model("grow", "Genre")._meta.db_table
    node = apps.get_model("the_music_tree_genre_kit", "GenreGraphNode")._meta.db_table
    valid = f"""((NEW.graph_node_id IS NULL AND NEW.semantic_identity IS NULL) OR
        EXISTS (SELECT 1 FROM {node} n WHERE n.id = NEW.graph_node_id
            AND n.dataset_id = 'grow' AND n.identity = NEW.semantic_identity))"""
    existing_valid = valid.replace("NEW.", "c.")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM {criteria} c WHERE NOT {existing_valid} LIMIT 1")
        if cursor.fetchone():
            raise RuntimeError("Existing graph binding does not match its dataset identity")
    changed = "OLD.graph_node_id IS NOT NULL AND (NEW.graph_node_id IS DISTINCT FROM OLD.graph_node_id OR NEW.semantic_identity IS DISTINCT FROM OLD.semantic_identity OR NEW.uuid IS DISTINCT FROM OLD.uuid)"
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"""CREATE FUNCTION grow_graph_binding_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.graph_node_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Permanent graph binding cannot be deleted' USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF {changed} THEN
                    RAISE EXCEPTION 'Permanent graph binding cannot be changed' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF NOT {valid} THEN
                RAISE EXCEPTION 'Graph binding must match its dataset identity' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        schema_editor.execute(f"""CREATE TRIGGER grow_graph_binding BEFORE INSERT OR UPDATE OR DELETE
            ON {criteria} FOR EACH ROW EXECUTE FUNCTION grow_graph_binding_guard()""")
        schema_editor.execute(f"""CREATE FUNCTION grow_graph_genre_guard() RETURNS trigger AS $$
        BEGIN
            IF (TG_OP = 'DELETE' OR NEW.criteria_ptr_id IS DISTINCT FROM OLD.criteria_ptr_id)
                AND EXISTS (SELECT 1 FROM {criteria} c WHERE c.uuid = OLD.criteria_ptr_id AND c.graph_node_id IS NOT NULL) THEN
                RAISE EXCEPTION 'Permanent graph genre cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        schema_editor.execute(f"""CREATE TRIGGER grow_graph_genre_delete BEFORE DELETE OR UPDATE OF criteria_ptr_id ON {genre}
            FOR EACH ROW EXECUTE FUNCTION grow_graph_genre_guard()""")
    elif schema_editor.connection.vendor == "sqlite":
        for operation in ("INSERT", "UPDATE"):
            schema_editor.execute(f"""CREATE TRIGGER grow_graph_binding_{operation.lower()} BEFORE {operation} ON {criteria}
                WHEN NOT {valid} BEGIN SELECT RAISE(ABORT, 'Graph binding must match its dataset identity'); END""")
        schema_editor.execute(f"""CREATE TRIGGER grow_graph_binding_immutable BEFORE UPDATE ON {criteria}
            WHEN {changed} BEGIN SELECT RAISE(ABORT, 'Permanent graph binding cannot be changed'); END""")
        schema_editor.execute(f"""CREATE TRIGGER grow_graph_binding_delete BEFORE DELETE ON {criteria}
            WHEN OLD.graph_node_id IS NOT NULL BEGIN SELECT RAISE(ABORT, 'Permanent graph binding cannot be deleted'); END""")
        schema_editor.execute(f"""CREATE TRIGGER grow_graph_genre_delete BEFORE DELETE ON {genre}
            WHEN EXISTS (SELECT 1 FROM {criteria} c WHERE c.uuid = OLD.criteria_ptr_id AND c.graph_node_id IS NOT NULL)
            BEGIN SELECT RAISE(ABORT, 'Permanent graph genre cannot be deleted'); END""")
        schema_editor.execute(f"""CREATE TRIGGER grow_graph_genre_update BEFORE UPDATE OF criteria_ptr_id ON {genre}
            WHEN OLD.criteria_ptr_id IS DISTINCT FROM NEW.criteria_ptr_id AND EXISTS
                (SELECT 1 FROM {criteria} c WHERE c.uuid = OLD.criteria_ptr_id AND c.graph_node_id IS NOT NULL)
            BEGIN SELECT RAISE(ABORT, 'Permanent graph genre cannot be changed'); END""")
    else:
        raise RuntimeError("Graph bindings require PostgreSQL or SQLite")


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER grow_graph_binding ON grow_criteria")
        schema_editor.execute("DROP TRIGGER grow_graph_genre_delete ON grow_genre")
        schema_editor.execute("DROP FUNCTION grow_graph_binding_guard()")
        schema_editor.execute("DROP FUNCTION grow_graph_genre_guard()")
    else:
        for name in ("insert", "update", "immutable", "delete"):
            schema_editor.execute(f"DROP TRIGGER grow_graph_binding_{name}")
        schema_editor.execute("DROP TRIGGER grow_graph_genre_delete")
        schema_editor.execute("DROP TRIGGER grow_graph_genre_update")


class Migration(migrations.Migration):
    dependencies = [("grow", "0131_graph_identity_retirement")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
