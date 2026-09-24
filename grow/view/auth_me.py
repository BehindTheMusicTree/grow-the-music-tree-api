from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.view.permission.IsAdminOrReadOnly import AUTHENTICATION_REQUIRED_DETAIL


class AuthMeView(APIView):
    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if request.auth is None:
            raise NotAuthenticated(detail=AUTHENTICATION_REQUIRED_DETAIL)
        return Response({"role": request.auth.role, "email": request.auth.email})
