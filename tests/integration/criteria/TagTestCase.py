from django.urls import reverse

from grow.model.criteria.children.tag.Tag import Tag
from tests.utils.AppTestCase import AppTestCase


class TagTestCase(AppTestCase):
    model_class = Tag
    list_endpoint = "tag-list"

    def _delete_tag(self, uuid):
        return self.api_client.delete(path=reverse("tag-detail", kwargs={"pk": uuid}))
