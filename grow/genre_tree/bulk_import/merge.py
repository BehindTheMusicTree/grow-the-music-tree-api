from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName
from the_music_tree_genre_kit.playlist.Playlist import Playlist
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.bulk_import.analyze import analyze
from grow.bulk_import.lifecycle import execute_merge
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.genre_tree.bulk_import.GenreTreeImportPayload import GenreTreeImportPayload
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.model.curation.CurationExport import CurationExport
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.import_run.ImportRun import ImportRun
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount

CURATION_EXPORTED_ON = "curation_exported_on"

TREE_IMPORT_RUN_KINDS = {
    CriteriaTreeName.CANONICAL: ImportRun.Kind.CANONICAL_TREE,
    CriteriaTreeName.REGIONAL: ImportRun.Kind.REGIONAL_TREE,
}

# The tables a tree import rewrites. Analyzed in its transaction so the first requests after it (and the songs
# import that follows it nightly) don't plan against the pre-import row counts.
TREE_IMPORT_MODELS = (
    Criteria,
    Genre,
    *(field.remote_field.through for field in Criteria._meta.many_to_many),
    CriteriaLineageRel,
    Playlist,
    CriteriaPlaylist,
    GenreCatalogueCount,
)


def node_count(nodes: list[dict]) -> int:
    return sum(1 + node_count(node.get(Fields.CHILDREN) or []) for node in nodes)


def load_curation_export(value: Any) -> CurationExport:
    """The curation export a tree or graph import was built from, which must be one grow served (and still keeps): a
    replayed older Gold names an older export, so edits made since stay pending."""
    if value is None:
        raise ValidationError({CURATION_EXPORTED_ON: "Required: the curation export this tree was built from"})
    try:
        exported_on = serializers.DateTimeField().run_validation(value)
    except ValidationError as e:
        raise ValidationError({CURATION_EXPORTED_ON: e.detail}) from e
    export = CurationExport.objects.filter(exported_on=exported_on).first()
    if export is None:
        raise ValidationError(
            {CURATION_EXPORTED_ON: "Unknown curation export: never served by grow, or purged after 30 days"}
        )
    return export


def parse_curation_exported_on(value: Any) -> datetime:
    return load_curation_export(value).exported_on


def merge_genre_trees_import_run(
    run_id: int, user_id: int | None, record: bool, attempt_id: int | None = None
) -> dict[str, Any]:
    """
    Imports the run's trees (canonical and regional) in one `import_criteria_trees` call, so a genre that moved
    between them keeps its pk and songs. A pipeline run (`record`) also marks its curation export applied and records
    one `ImportRun` per tree. Everything commits together with the run's receipt, or not at all.
    """
    return execute_merge(run_id, attempt_id, GenreTreeImportPayload, lambda: _merge(run_id, user_id, record))


def _merge(run_id: int, user_id: int | None, record: bool) -> dict[str, Any]:
    lock_catalogue_sources()
    payload = GenreTreeImportPayload.objects.get(run_id=run_id).payload
    trees = payload["trees"]
    user = get_user_model().objects.get(pk=user_id) if user_id is not None else None
    CriteriaPlaylist.objects.ensure_criterialess(user)
    state = CurationSyncState.load()
    if record:
        state.applied_export_on = parse_curation_exported_on(payload.get(CURATION_EXPORTED_ON))
    results = Genre.objects.import_criteria_trees(user, trees)
    Genre.objects.assert_required_roots_present(user)
    analyze(TREE_IMPORT_MODELS)
    if record:
        state.save(update_fields=["applied_export_on"])
        for tree in trees:
            tree_name = tree[Fields.TREE_NAME]
            ImportRun.objects.create(kind=TREE_IMPORT_RUN_KINDS[tree_name], count=node_count(tree[Fields.TREE]))
    return results
