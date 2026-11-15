from uuid import UUID

from rest_framework.exceptions import APIException, ValidationError
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.manifests import require_complete_parts
from grow.genre_graph.service import DATASET_KEY
from grow.model.import_run.ImportRun import ImportRun
from grow.track.bulk_import.assignment_publication import assignment_write_transaction
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging
from grow.track.bulk_import.SongImportStaging import SongImportStaging


class ReviewedImportConflict(APIException):
    status_code = 409
    default_detail = "Reference graph or memberships changed; review and create a new import run"


def require_reviewed_contract(metadata: dict) -> None:
    if not metadata:
        require_legacy_import_contract()
        return
    try:
        with assignment_write_transaction(
            expected_graph=metadata["graph_revision"], expected_membership=metadata["membership_revision"]
        ):
            pass
    except GraphRevisionConflict as error:
        raise ReviewedImportConflict from error
    except GenreGraphDataset.DoesNotExist as error:
        raise ValidationError("Import the reference graph with an explicit identity mapping first") from error
    except GraphValidationError as error:
        raise ValidationError(str(error)) from error


def run_metadata(data, mode: str) -> dict:
    """Semantic transport is opt-in; never infer reviewed revisions from current state."""
    fields = {"graph_revision", "membership_revision", "expected_parts"}
    if not fields.intersection(data):
        return {}
    if not fields.issubset(data):
        raise ValidationError("Semantic imports require graph_revision, membership_revision and expected_parts")
    if mode not in BulkImportRun.Mode.values:
        raise ValidationError("Invalid song import mode")
    try:
        graph, membership = (UUID(str(data[name])) for name in ("graph_revision", "membership_revision"))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValidationError("Reviewed graph and membership revisions must be UUIDs") from error
    parts = data["expected_parts"]
    required = {"songs", "assignments", "deletions"} if mode == BulkImportRun.Mode.DELTA else {"songs", "assignments"}
    if (
        not isinstance(parts, dict)
        or set(parts) != required
        or any(type(count) is not int or count < 0 for count in parts.values())
    ):
        raise ValidationError("expected_parts must declare non-negative integer counts for every import stream")
    if mode == BulkImportRun.Mode.FULL and parts["songs"] == 0:
        raise ValidationError("A full import must declare at least one song part")
    if mode == BulkImportRun.Mode.DELTA and parts["deletions"] not in {0, 1}:
        raise ValidationError("A delta import has at most one deletions part")
    return {"graph_revision": graph, "membership_revision": membership, "expected_parts": parts}


def persisted_metadata(run: BulkImportRun) -> dict:
    """Revalidate stored review metadata at uploads and worker retries, not only at HTTP creation."""
    metadata = {
        field: value
        for field in ("graph_revision", "membership_revision", "expected_parts")
        if (value := getattr(run, field)) is not None
    }
    if metadata and run.kind != ImportRun.Kind.SONGS:
        raise ValidationError("Semantic review metadata is only supported for song imports")
    return run_metadata(metadata, run.mode)


def require_declared_part(run: BulkImportRun, stream: str, part: int) -> None:
    metadata = persisted_metadata(run)
    if metadata and not 0 <= part < metadata["expected_parts"].get(stream, 0):
        raise ValidationError("Part is outside the run's declared import streams")


def require_complete_run(run: BulkImportRun) -> None:
    metadata = persisted_metadata(run)
    if not metadata:
        return
    models = {"songs": SongImportStaging, "assignments": SongAssignmentStaging, "deletions": BulkImportDeletion}
    require_complete_parts(run, {name: (models[name], count) for name, count in metadata["expected_parts"].items()})


def require_legacy_import_contract() -> None:
    if GenreGraphDataset.objects.filter(pk=DATASET_KEY).exists():
        raise ValidationError(
            "Legacy song imports cannot publish into an active reference graph; "
            "semantic assignment imports are required."
        )
