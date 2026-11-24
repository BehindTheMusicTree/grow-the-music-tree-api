from typing import Any
from uuid import uuid4

from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode

from grow.curation.lists import CURATION_LISTS
from grow.curation.rows import InvalidRow
from grow.model.curation.CurationEntry import CurationEntry


def invalid(field_name: str, message: str) -> AppValidationException:
    return AppValidationException(
        field_name=field_name,
        message=message,
        field_validation_error_code=FieldValidationErrorCode.REFERENCE_INVALID,
    )


def admin_provenance(actor: Any, prefix: str) -> dict[str, str]:
    """The `{decisionId, source, rationale}` of an admin decision. The same triplet must be written on the curation
    rule and registered as evidence on the attribution: the genre kit refuses a decision id whose source or
    rationale changes."""
    return {
        "decisionId": f"{prefix}-{uuid4()}",
        "source": "admin curation",
        "rationale": f"grow admin edit by {actor.profile.pseudo}",
    }


def upsert_admin_rule(
    list_name: str, row: dict[str, Any], actor: Any, provenance: dict[str, str] | None = None
) -> None:
    """Writes an admin edit into the curation list the pipeline reads; a row the list rejects is a 400."""
    if provenance is not None:
        row = {
            **row,
            "decision_id": provenance["decisionId"],
            "decision_source": provenance["source"],
            "reason": provenance["rationale"],
        }
    elif CURATION_LISTS[list_name].has_reason:
        row = {**row, "reason": f"grow admin edit by {actor.profile.pseudo}"}
    try:
        CurationEntry.objects.upsert(list_name, row, actor=actor)
    except InvalidRow as e:
        field_name, message = next(iter(e.errors.items()))
        raise invalid(field_name, f"Can't record this edit in {list_name}: {message}") from e
