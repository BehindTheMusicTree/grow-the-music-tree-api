import gzip
import json
import logging

from django.core.cache import cache
from redis.exceptions import RedisError

from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot

logger = logging.getLogger(__name__)

DRAWN_TTL_SECONDS = 3600


def drawn_region_ids() -> frozenset[str]:
    """
    The ids of the regions the latest region map index draws; empty without a snapshot. Keyed on the index checksum,
    so a new import is never served a stale set.
    """
    # A merge that commits between the snapshot read and the file read deletes the file just resolved: read again.
    for _ in range(2):
        snapshot = RegionMapSnapshot.objects.first()
        if snapshot is None:
            return frozenset()
        key = f"region-map-drawn:v1:{snapshot.checksum}"
        try:
            ids = cache.get(key)
        except RedisError:
            logger.warning("Region map cache unavailable, reading the index", exc_info=True)
            ids = None
        if ids is not None:
            return ids
        body = RegionMapFile.objects.filter(pk=snapshot.checksum).values_list("body", flat=True).first()
        if body is None:
            continue
        ids = frozenset(
            region["id"] for region in json.loads(gzip.decompress(bytes(body)))["regions"] if "id" in region
        )
        try:
            cache.set(key, ids, DRAWN_TTL_SECONDS)
        except RedisError:
            logger.warning("Region map cache unavailable, drawn regions not cached", exc_info=True)
        return ids
    return frozenset()
