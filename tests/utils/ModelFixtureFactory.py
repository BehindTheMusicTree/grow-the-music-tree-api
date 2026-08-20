from datetime import datetime

from django.contrib.auth.models import User
from django.utils import timezone

from grow.model.album.Album import Album
from grow.model.artist.Artist import Artist
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.children.tag.Tag import Tag
from grow.model.criteria.Criteria import Criteria
from grow.model.criteria.Fields import Fields as CriteriaFields
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack


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

    def create_artist(self, name: str, user: User | None = None, **kwargs) -> Artist:
        return Artist.objects.create(user=user or self.default_user, name=name, **kwargs)

    def create_album(self, name: str, user: User | None = None, **kwargs) -> Album:
        return Album.objects.create(user=user or self.default_user, name=name, **kwargs)

    def create_youtube_track(self, title: str, genre: Genre, user: User | None = None, **kwargs) -> YoutubeTrack:
        return YoutubeTrack.objects.create(user=user or self.default_user, title=title, genre=genre, **kwargs)
