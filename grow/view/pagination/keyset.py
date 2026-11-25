from django.db.models import Q, QuerySet

SORT_KEY = "sort_key"


def seek(queryset: QuerySet, key, song_id, *, descending: bool, inclusive: bool, keyed: bool) -> QuerySet:
    """Rows after (or at, if `inclusive`) (`key`, `song_id`) in (SORT_KEY nulls last, pk) order; `keyed=False`: pk only."""
    if not keyed:
        return queryset.filter(**{"pk__gte" if inclusive else "pk__gt": song_id})
    after = "lt" if descending else "gt"
    pk_lookup = f"pk__{after}e" if inclusive else f"pk__{after}"
    null_tail = Q(**{f"{SORT_KEY}__isnull": True})
    if key is None:
        return queryset.filter(null_tail, **{pk_lookup: song_id})
    return queryset.filter(Q(**{f"{SORT_KEY}__{after}": key}) | Q(**{SORT_KEY: key, pk_lookup: song_id}) | null_tail)
