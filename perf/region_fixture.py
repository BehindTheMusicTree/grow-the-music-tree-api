import gzip
import hashlib
import json
from pathlib import Path

from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot

FIXTURE = Path(__file__).parent / "fixtures" / "region_map_index.json.gz"
CHECKSUM = "5ee2f9b26dcd1ea79b3d1768ed740a8ba332e41362d4dbab8cdbfec00a8048f2"


def seed_region_snapshot() -> None:
    """Install the pinned read benchmark input, including on a reused pre-region perf database."""
    compressed = FIXTURE.read_bytes()
    body = gzip.decompress(compressed)
    if hashlib.sha256(body).hexdigest() != CHECKSUM:
        raise ValueError("region performance fixture checksum mismatch")
    if len(json.loads(body)["regions"]) != 849:
        raise ValueError("region performance fixture must contain 849 regions")
    snapshot = RegionMapSnapshot.objects.first()
    if snapshot is not None and snapshot.checksum != CHECKSUM:
        raise ValueError("recreate the performance database: region snapshot differs from the pinned fixture")
    RegionMapFile.objects.get_or_create(sha256=CHECKSUM, defaults={"body": compressed, "size": len(compressed)})
    if snapshot is None:
        RegionMapSnapshot.objects.create(checksum=CHECKSUM)
