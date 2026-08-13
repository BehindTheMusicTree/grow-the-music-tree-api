from grow.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import PrivateUniqueResourceFilterSet
from grow.model.play.Play import Play


class PlayFilterSet(PrivateUniqueResourceFilterSet):
    class Meta:
        model = Play
        fields = [*PrivateUniqueResourceFilterSet.get_date_fields()]
