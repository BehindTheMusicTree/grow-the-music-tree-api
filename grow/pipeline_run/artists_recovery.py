from collections.abc import Iterable
from typing import Any

from django.db import connection
from django.db.models import Exists, OuterRef, Q, Subquery
from rest_framework.exceptions import APIException

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.model.import_run.ImportRun import ImportRun
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest

State = ImportAttempt.State
Status = PipelineRunRequest.Status
Kind = PipelineRunRequest.Kind
SONGS = ImportRun.Kind.SONGS
ARTISTS = ImportRun.Kind.ARTISTS
ACTIVE = (Status.QUEUED, Status.RUNNING)
MERGING = (State.QUEUED, State.RUNNING, State.COMMITTING, State.CLEANING_UP)


class RecoveryConflict(APIException):
    status_code = 409


def lock_recovery_admission() -> None:
    """Serialize requests and import admission without waiting for a catalogue merge."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(716731928418)")


def _latest_attempts():
    newer = ImportAttempt.objects.filter(run_id=OuterRef("run_id"), attempt__gt=OuterRef("attempt"))
    receipt = ImportReceipt.objects.filter(run_id=OuterRef("run_id"))
    return (
        ImportAttempt.objects.filter(kind__in=(SONGS, ARTISTS), user_id=None)
        .filter(~Exists(newer))
        .annotate(receipt_at=Subquery(receipt.values("applied_at")[:1]))
    )


def recovery_states(sources: Iterable[PipelineRunRequest], *, attest: bool = False) -> dict[int, dict[str, Any]]:
    sources = [source for source in sources if source.kind != Kind.SYNC_ARTISTS and source.status not in ACTIVE]
    if not sources:
        return {}
    ids = [source.pk for source in sources]
    recoveries = list(
        PipelineRunRequest.objects.filter(source_run_id__in=ids).values_list("pk", "source_run_id", "status")
    )
    parents = {pk: source_id for pk, source_id, _ in recoveries}
    finalized = {source_id for _, source_id, status in recoveries if status == Status.SUCCEEDED}
    related_ids = [*ids, *parents]
    attempts = list(
        _latest_attempts()
        .filter(
            Q(pipeline_run_request_id__in=related_ids)
            | Q(state__in=MERGING)
            | Q(data_applied=True)
            | Q(receipt_at__isnull=False)
        )
        .select_related(None)
        .only("run_id", "task_id", "kind", "pipeline_run_request_id", "state", "data_applied", "finished_at")
        .order_by("-run_id")
    )
    staged = {}
    for run_id, request_id in (
        BulkImportRun.objects.filter(kind=ARTISTS, pipeline_run_request_id__in=parents, committed_on=None)
        .order_by("pk")
        .values_list("pk", "pipeline_run_request_id")
    ):
        staged[parents[request_id]] = run_id

    states = {}
    for source in sources:
        songs = next(
            (a for a in attempts if a.kind == SONGS and a.pipeline_run_request_id == source.pk),
            None,
        )
        if songs is None:
            continue
        related = {source.pk, *(pk for pk, parent in parents.items() if parent == source.pk)}
        artists = [a for a in attempts if a.kind == ARTISTS and a.pipeline_run_request_id in related]
        applied = next((a for a in artists if a.data_applied or a.receipt_at is not None), None)
        submitted = next((a for a in artists if a.state in MERGING), None)
        snapshots_finalized = source.pk in finalized or source.status == Status.SUCCEEDED
        songs_applied = songs.receipt_at is not None or (songs.state == State.SUCCEEDED and songs.data_applied)
        attempt = applied or submitted
        reason = None
        if not songs_applied:
            reason = "La fusion des chansons de ce Gold n'est pas confirmée."
        elif snapshots_finalized:
            reason = "Les snapshots de ce Gold sont déjà finalisés."
        elif any(
            a.state in MERGING and a.run_id != songs.run_id and (attempt is None or a.run_id != attempt.run_id)
            for a in attempts
        ):
            reason = "Une autre fusion du catalogue est en cours."
        elif any(
            (a.data_applied or a.receipt_at is not None)
            and (a.kind == SONGS or a.pipeline_run_request_id not in related)
            and a.run_id != songs.run_id
            and (
                a.run_id > songs.run_id
                or (
                    (a.receipt_at or a.finished_at) is not None
                    and (songs.receipt_at or songs.finished_at) is not None
                    and (a.receipt_at or a.finished_at) > (songs.receipt_at or songs.finished_at)
                )
            )
            for a in attempts
        ):
            reason = "Un autre import a modifié le catalogue depuis ce Gold."
        elif not attest and not (source.manifest_sha256 and source.songs_snapshot_sha256):
            reason = "La provenance du Gold doit être attestée."
        elif attempt is not None and not source.artists_snapshot_sha256:
            reason = "L'empreinte du snapshot de l'import artistes est indisponible."
        states[source.pk] = {
            "eligible": reason is None,
            "reason": reason,
            "songs_applied": songs_applied,
            "songs_run_id": songs.run_id,
            "artists_applied": applied is not None,
            "snapshots_finalized": snapshots_finalized,
            "artists_run_id": attempt.run_id if attempt else staged.get(source.pk),
            "artists_task_id": attempt.task_id if attempt else None,
        }
    return states


def require_recovery(source: PipelineRunRequest, *, attest: bool = False, finalize: bool = False) -> dict[str, Any]:
    state = recovery_states([source], attest=attest).get(source.pk)
    if not state or not state["eligible"]:
        raise RecoveryConflict(state["reason"] if state else "Aucune fusion chansons liée à cette demande.")
    if finalize:
        if not state["artists_applied"]:
            raise RecoveryConflict("La fusion des artistes n'est pas confirmée.")
        if _latest_attempts().filter(run_id=state["artists_run_id"], state__in=MERGING).exists():
            raise RecoveryConflict("Le traitement de l'import artistes est toujours en cours.")
    return state


def lock_active_recovery(request: PipelineRunRequest) -> PipelineRunRequest:
    request = PipelineRunRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != Status.RUNNING or request.cancel_requested_on is not None:
        raise RecoveryConflict("La demande de reprise artistes doit être en cours et sans annulation.")
    return request


def guard_catalogue_import(
    kind: str, request: PipelineRunRequest | None, *, mode: str, submitted: bool = False
) -> None:
    """Called under the recovery admission lock, before a run can be staged or committed."""
    if request is not None and request.kind == Kind.SYNC_ARTISTS:
        request = lock_active_recovery(request)
        if kind != ARTISTS or mode != BulkImportRun.Mode.FULL:
            raise RecoveryConflict("La reprise active exige un import artistes complet.")
        state = require_recovery(request.source_run)
        if not request.source_run.artists_snapshot_sha256 or (not submitted and state["artists_task_id"] is not None):
            raise RecoveryConflict("Vérifier le snapshot artistes ou suivre la fusion déjà soumise.")
    elif kind in (SONGS, ARTISTS) and (
        PipelineRunRequest.objects.filter(kind=Kind.SYNC_ARTISTS, status__in=ACTIVE).exists()
        or _latest_attempts()
        .filter(kind=ARTISTS, state__in=MERGING, pipeline_run_request__kind=Kind.SYNC_ARTISTS)
        .exists()
    ):
        raise RecoveryConflict("Une reprise des artistes est en cours.")
