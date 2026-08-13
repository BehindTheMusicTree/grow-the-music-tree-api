from grow.model.criteria.children.genre.Genre import Genre
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet


class GenreViewSet(CriteriaViewSet):
    def __init__(self, **kwargs):
        super().__init__(model_class=Genre, **kwargs)
