"""Seeds an empty dev DB with the perf/fixtures Gold snapshot, through the same endpoints and order as the nightly sync."""

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
from perf.gold_graph import (
    SONGS,
    TREES,
    assignments_part,
    build_graph,
    identity_mapping,
    load_songs,
    load_trees,
    read_genres,
    resolve_songs,
    run_body,
    songs_part,
)

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


def _json_headers() -> dict[str, str]:
    return {"Content-Type": "application/json"}


def seed() -> None:
    exported_on = call("GET", "curation/export/")["exported_on"]
    trees = load_trees(exported_on)
    log(f"importing {', '.join(TREES)}")
    task_id = call("POST", "genres/trees/import-runs/", json.dumps({"trees": trees}).encode(), _json_headers())[
        "taskId"
    ]
    # The graph maps onto the imported genres, so wait for the merge.
    while (polled := call("GET", f"genres/trees/import/{task_id}/status/"))["status"] not in ("success", "failure"):
        time.sleep(2)
    if polled["status"] != "success":
        raise SystemExit(f"genre trees import failed: {polled}")
    genres = read_genres(lambda page: call("GET", f"genres/?page={page}&page_size=100"))
    graph = build_graph(trees)
    body = {"graph": graph, "mapping": identity_mapping(graph, genres), "expectedRevision": None}
    call("PUT", "genres/graph/", json.dumps(body).encode(), _json_headers())
    log(f"importing {SONGS}")
    songs = load_songs()
    resolved = resolve_songs(trees, songs)
    runs = "library/songs/songs/import-runs/"
    run_id = call("POST", runs, json.dumps(run_body(call("GET", "genres/graph/"))).encode(), _json_headers())["runId"]
    headers = {"Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"}
    call("PUT", f"{runs}{run_id}/parts/0/", songs_part(songs), headers)
    call("PUT", f"{runs}{run_id}/assignments/parts/0/", assignments_part(resolved), headers)
    call("POST", f"{runs}{run_id}/commit/")
    log("trees and graph imported; songs are merging in the worker")


if __name__ == "__main__":
    if Genre.objects.exists():
        log("DB already has genres, skipping")
    else:
        wait_for_server()
        seed()
