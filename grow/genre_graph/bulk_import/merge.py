from typing import Any
from uuid import UUID

from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.genre_graph.models import (
    GenreGraphAccess,
    GenreGraphAssignmentState,
    GenreGraphAttribution,
    GenreGraphAttributionEvidence,
    GenreGraphAttributionRevision,
    GenreGraphDataset,
    GenreGraphEvidence,
    GenreGraphNode,
    GenreGraphRevision,
)
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.bulk_import.analyze import analyze
from grow.bulk_import.lifecycle import execute_merge
from grow.genre_graph.bulk_import.GenreGraphImportPayload import GenreGraphImportPayload
from grow.genre_graph.models import GenreGraphAssignmentBackup, GenreGraphImport
from grow.genre_graph.service import import_reference_graph
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

# The tables a graph import writes (tracks are only row-locked). Analyzed in its transaction, like the other merges.
GRAPH_IMPORT_MODELS = (
    Criteria,
    Genre,
    Playlist,
    CriteriaPlaylist,
    CurationSyncState,
    GenreTreeVersion,
    GenreGraphImport,
    GenreGraphAssignmentBackup,
    GenreGraphDataset,
    GenreGraphRevision,
    GenreGraphNode,
    GenreGraphEvidence,
    GenreGraphAttribution,
    GenreGraphAttributionEvidence,
    GenreGraphAttributionRevision,
    GenreGraphAssignmentState,
    GenreGraphAccess,
)


def merge_reference_graph_import_run(
    run_id: int, user_id: int | None, record: bool, attempt_id: int | None = None
) -> dict[str, Any]:
    """
    Imports the run's reference graph with `import_reference_graph`, which re-checks the expected revision and every
    binding under its locks: the request-time checks are only a fast failure. Validation errors reach the status
    endpoint as `GraphValidationError: <message>` (a stale revision as `GraphRevisionConflict: ...`).
    """
    return execute_merge(
        run_id,
        attempt_id,
        GenreGraphImportPayload,
        lambda: _merge(run_id),
        public_errors=(GraphValidationError,),
    )


def _merge(run_id: int) -> dict[str, Any]:
    body = GenreGraphImportPayload.objects.get(run_id=run_id).payload
    expected = body["expected_revision"]
    dataset = import_reference_graph(
        payload=body["graph"],
        mapping=body["mapping"],
        expected_revision=UUID(expected) if expected is not None else None,
        curation_exported_on=body["graph"].get("curationExportedOn"),
        retirements=body.get("retirements"),
    )
    analyze(GRAPH_IMPORT_MODELS)
    return {"revision": str(dataset.revision), "membership_revision": str(dataset.membership_revision)}
