from django.db import connections
from django.db.models import UUIDField
from django.db.models.expressions import RawSQL

from grow.genre_music.selection import SubgenreScope
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria


def selected_genres_query(genre, tree_name: str, scope: SubgenreScope, *, using: str):
    """An uncorrelated genre-only closure, usable inside a membership-bounded song lookup."""
    if tree_name not in {"canonical", "regional"}:
        raise ValueError("Invalid genre tree")
    if not isinstance(scope, SubgenreScope):
        raise ValueError("Invalid subgenre scope")
    if tree_name == "regional" and scope != SubgenreScope.ALL:
        raise ValueError("Regional genres require the all scope")
    connection = connections[using]
    quote = connection.ops.quote_name
    criteria = quote(Criteria._meta.db_table)
    genres = quote(Genre._meta.db_table)
    additional = quote(Criteria.additional_primary_parents.through._meta.db_table)
    genre_id = Criteria._meta.pk.get_db_prep_value(genre, connection)
    if tree_name == "regional":
        predicate = "TRUE"
    elif scope == SubgenreScope.CANONICAL:
        predicate = "canonical_path"
    elif scope == SubgenreScope.REGIONAL:
        predicate = "tree_name = 'regional' OR id = %s"
    else:
        predicate = "canonical_path OR tree_name = 'regional'"
    params = [genre_id]
    if tree_name == "canonical" and scope == SubgenreScope.REGIONAL:
        params.append(genre_id)
    node_filter = "AND c.tree_name = 'canonical'" if scope == SubgenreScope.CANONICAL else ""
    # UNION terminates even with repeated primary paths; canonical_path preserves whether a
    # canonical descendant was reached without crossing a regional subtree.
    return RawSQL(
        f"""
        WITH RECURSIVE nodes AS MATERIALIZED (
            SELECT c.uuid, c.tree_name, c.parent_id FROM {criteria} c
            JOIN {genres} g ON g.criteria_ptr_id = c.uuid
            WHERE c.user_id IS NULL {node_filter}
        ), edges(parent_id, child_id) AS MATERIALIZED (
            SELECT parent_id, uuid FROM nodes WHERE parent_id IS NOT NULL
            UNION ALL
            SELECT a.to_criteria_id, a.from_criteria_id FROM {additional} a
            JOIN nodes c ON c.uuid = a.from_criteria_id
        ), reachable(id, tree_name, canonical_path) AS (
            SELECT c.uuid, c.tree_name, TRUE FROM nodes c WHERE c.uuid = %s
            UNION
            SELECT c.uuid, c.tree_name, r.canonical_path AND c.tree_name = 'canonical'
            FROM reachable r
            JOIN edges e ON e.parent_id = r.id
            JOIN nodes c ON c.uuid = e.child_id
        )
        SELECT id FROM reachable WHERE {predicate}
        """,
        params,
        output_field=UUIDField(),
    )
