from typing import TYPE_CHECKING, TypeVar

from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager

from .Fields import Fields

if TYPE_CHECKING:
    from .UploadedTrackMixin import UploadedTrackMixin

T = TypeVar("T", bound="UploadedTrackMixin")


class UploadedTrackMixinManager(StandardResourceManager[T]):
    def get_default_ordering(self) -> list[str]:
        return [Fields.NAME_PUBLIC]
