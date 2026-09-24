from the_music_tree_api_kit.base.BaseModel import BaseModel
from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import AppModelViewSet

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.view.permission.IsAdminOrReadOnly import IsAdminOrReadOnly


class GrowModelViewSet[T: BaseModel](AppModelViewSet[T]):
    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAdminOrReadOnly]
