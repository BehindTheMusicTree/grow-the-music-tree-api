from datetime import datetime

from django.contrib.auth.models import User
from django.utils import timezone

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.children.tag.Tag import Tag
from grow.model.criteria.Criteria import Criteria
from grow.model.criteria.Fields import Fields as CriteriaFields


class ModelFixtureFactory:
    default_user: User

    def __init__(self, default_user: User) -> None:
        self.default_user = default_user

    def _create_criteria(self, name: str, model_class: type[Criteria], user: User | None = None, **kwargs) -> Criteria:
        now = timezone.make_aware(datetime.now())
        model_fields = {
            CriteriaFields.CREATED_ON: kwargs.get(CriteriaFields.CREATED_ON, now),
            CriteriaFields.UPDATED_ON: kwargs.get(CriteriaFields.UPDATED_ON, now),
            CriteriaFields.USER: user or self.default_user,
            CriteriaFields.NAME_PUBLIC: name,
            CriteriaFields.PARENT: None,
        }
        model_fields.update(kwargs)
        return model_class.objects.create(**model_fields)

    def create_genre(self, name: str, **kwargs) -> Genre:
        return self._create_criteria(name=name, model_class=Genre, **kwargs)

    def create_tag(self, name: str, **kwargs) -> Tag:
        return self._create_criteria(name=name, model_class=Tag, **kwargs)
