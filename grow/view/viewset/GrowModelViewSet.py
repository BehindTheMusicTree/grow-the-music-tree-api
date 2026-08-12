from the_music_tree_api_kit.base.BaseModel import BaseModel
from the_music_tree_api_kit.view.permission.IsAuthenticatedReturn401 import IsAuthenticatedReturn401
from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import AppModelViewSet

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication


class GrowModelViewSet[T: BaseModel](AppModelViewSet[T]):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticatedReturn401]
