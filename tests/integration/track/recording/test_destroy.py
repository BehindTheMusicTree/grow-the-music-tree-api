from django.urls import reverse
from rest_framework import status

from grow.model.recording.Recording import Recording
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_destroy_removes_track(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        recording = self.model_fixture_factory.create_recording(title="Track Title", genre=genre)

        response = self.api_client.delete(path=reverse("recording-detail", kwargs={"pk": recording.uuid}))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Recording.objects.filter(uuid=recording.uuid).exists()
