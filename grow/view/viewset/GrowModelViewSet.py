from the_music_tree_api_kit.base.BaseModel import BaseModel
from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import AppModelViewSet

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.view.permission.AuthenticatedForWritesReturn401 import AuthenticatedForWritesReturn401
from grow.view.permission.ReadOnlyForPrototypeUser import ReadOnlyForPrototypeUser


class GrowModelViewSet[T: BaseModel](AppModelViewSet[T]):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [AuthenticatedForWritesReturn401, ReadOnlyForPrototypeUser]
