from typing import Any
from uuid import UUID

from django.db.models import Model
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
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
from grow.bulk_import.progress import report_step
from grow.genre_graph.bulk_import.GenreGraphImportPayload import GenreGraphImportPayload
from grow.genre_graph.models import GenreGraphAssignmentBackup, GenreGraphImport
from grow.genre_graph.service import GraphPublicationStats, import_reference_graph
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount
from grow.model.playlist.GenreMembershipCount import GenreMembershipCount
from grow.model.song.Song import Song

GRAPH_REVISION_MODELS = (
    Criteria,
    Genre,
    Playlist,
    CriteriaPlaylist,
    CurationSyncState,
    CurationReviewItem,
    GenreTreeVersion,
    GenreGraphImport,
    GenreGraphDataset,
    GenreGraphRevision,
    GenreGraphNode,
    GenreGraphAccess,
)
ASSIGNMENT_MODELS = (
    GenreGraphEvidence,
    GenreGraphAttribution,
    GenreGraphAttributionEvidence,
    GenreGraphAttributionRevision,
    GenreGraphAssignmentState,
)
SONG_PROJECTION_MODELS = (Song, GenreCatalogueCount, GenreMembershipCount, TrackPlaylistRel)


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
    stats = GraphPublicationStats()
    dataset = import_reference_graph(
        payload=body["graph"],
        mapping=body["mapping"],
        expected_revision=UUID(expected) if expected is not None else None,
        curation_exported_on=body["graph"].get("curationExportedOn"),
        retirements=body.get("retirements"),
        publication_stats=stats,
    )
    if str(dataset.revision) != expected:
        models: list[type[Model]] = list(GRAPH_REVISION_MODELS)
        if expected is None:
            models.append(GenreGraphAssignmentBackup)
        if expected is None or body.get("retirements"):
            models.extend(ASSIGNMENT_MODELS)
        if stats.songs_changed:
            models.extend(SONG_PROJECTION_MODELS)
        with report_step("analyze"):
            analyze(models)
    return {"revision": str(dataset.revision), "membership_revision": str(dataset.membership_revision)}
