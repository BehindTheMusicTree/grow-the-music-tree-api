from typing import Any

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


def upsert_admin_rule(list_name: str, row: dict[str, Any], actor: Any) -> None:
    """Writes an admin edit into the curation list the pipeline reads; a row the list rejects is a 400."""
    if CURATION_LISTS[list_name].has_reason:
        row = {**row, "reason": f"grow admin edit by {actor.profile.pseudo}"}
    try:
        CurationEntry.objects.upsert(list_name, row, actor=actor)
    except InvalidRow as e:
        field_name, message = next(iter(e.errors.items()))
        raise invalid(field_name, f"Can't record this edit in {list_name}: {message}") from e
