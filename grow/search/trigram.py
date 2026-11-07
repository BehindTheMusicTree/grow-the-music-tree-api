from django.db.backends.utils import CursorWrapper
from django.db.models import Case, IntegerField, Value, When

# Below pg_trgm's 0.6 default so a one-letter typo in a long name still matches ("radiohed" -> "Radiohead").
SEARCH_WORD_SIMILARITY_THRESHOLD = 0.4


def fold_query(cursor: CursorWrapper, query: str) -> str:
    """Folds `query` like the `folded_name` columns and sets the transaction's trigram threshold. Needs an atomic
    block: the threshold is transaction-local."""
    cursor.execute(
        "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true), grow_search_norm(%s)",
        [str(SEARCH_WORD_SIMILARITY_THRESHOLD), query],
    )
    return cursor.fetchone()[1]


def match_rank(field: str, folded_query: str) -> Case:
    """2 for an exact folded match, 1 for a prefix, 0 for a fuzzy one."""
    return Case(
        When(**{field: folded_query}, then=Value(2)),
        When(**{f"{field}__startswith": folded_query}, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
