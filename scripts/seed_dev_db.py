"""Seeds an empty dev DB with the perf/fixtures Gold snapshot, through the same endpoints and order as the nightly sync."""

import gzip
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "grow.settings")

import django

django.setup()

from grow.model.criteria.children.genre.Genre import Genre

FIXTURES = ROOT / "perf" / "fixtures"
TREES = ["1_canonical_genre_tree.json.gz", "1_regional_genre_tree.json.gz"]
SONGS = "2_songs.json.gz"
BASE_URL = f"http://127.0.0.1:{os.environ['APP_PORT']}"
API_KEY = os.environ["PIPELINE_API_KEY"]
HEALTH_TIMEOUT_S = 120


def log(message: str) -> None:
    print(f"[seed-dev-db] {message}", flush=True)


def call(method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}/v1/{path}", data=body, method=method, headers={"X-API-Key": API_KEY, **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


def wait_for_server() -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while True:
        try:
            urllib.request.urlopen(f"{BASE_URL}/health/", timeout=5).close()
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
        else:
            return


def seed() -> None:
    exported_on = call("GET", "curation/export/")["exported_on"]
    for fixture in TREES:
        log(f"importing {fixture}")
        with gzip.open(FIXTURES / fixture) as file:
            body = json.dumps({**json.load(file), "curationExportedOn": exported_on}).encode()
        call("POST", "genres/tree/import/", body, {"Content-Type": "application/json"})
    log(f"importing {SONGS}")
    with gzip.open(FIXTURES / SONGS) as file:
        part = gzip.compress(
            "".join(json.dumps({"first_release_year": None, **song}) + "\n" for song in json.load(file)).encode()
        )
    runs = "library/songs/songs/import-runs/"
    run_id = call("POST", runs)["runId"]
    call(
        "PUT",
        f"{runs}{run_id}/parts/0/",
        part,
        {"Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"},
    )
    call("POST", f"{runs}{run_id}/commit/")
    log("trees imported; songs are merging in the worker")


if __name__ == "__main__":
    if Genre.objects.exists():
        log("DB already has genres, skipping")
    else:
        wait_for_server()
        seed()
