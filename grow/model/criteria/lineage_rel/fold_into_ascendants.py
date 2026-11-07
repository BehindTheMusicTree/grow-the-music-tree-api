from collections.abc import Hashable

from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel


def fold_into_ascendants[K: Hashable](own: dict[K | None, list[int]]) -> dict[K | None, list[int]]:
    """
    Adds each genre's count vector to every primary ascendant's. The lineage holds one row per (descendant,
    ascendant) pair, so a genre reaching an ascendant through several parents is counted once. Keys without a
    genre (the Genreless playlist) have no ascendants and stay as they are.
    """
    folded = {key: counts[:] for key, counts in own.items()}
    genres = [key for key in own if key is not None]
    for descendant, ascendant in CriteriaLineageRel.objects.filter(
        user__isnull=True, descendant__in=genres
    ).values_list("descendant", "ascendant"):
        target = folded.setdefault(ascendant, [0] * len(own[descendant]))
        for index, count in enumerate(own[descendant]):
            target[index] += count
    return folded
