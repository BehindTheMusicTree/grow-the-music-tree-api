from typing import TYPE_CHECKING, TypeVar

from .Fields import Fields
from .UploadedTrackMixinManager import UploadedTrackMixinManager

if TYPE_CHECKING:
    from .UploadedTrackMixin import UploadedTrackMixin

T = TypeVar("T", bound="UploadedTrackMixin")


class UploadedTrackMixinWithInternalNameManager(UploadedTrackMixinManager[T]):
    def get_default_ordering(self) -> list[str]:
        return [Fields.NAME_INTERNAL]
