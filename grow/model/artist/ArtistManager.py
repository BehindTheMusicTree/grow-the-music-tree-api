from typing import TYPE_CHECKING

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db import connection, transaction
from django.db.models import Case, F, Func, OuterRef, Q, Subquery, TextField, Value, When
from django.db.models.fields import FloatField
from django.db.models.functions import Coalesce, Greatest
from the_music_tree_genre_kit.track_mixin.Fields import Fields as TrackMixinFields
from the_music_tree_genre_kit.track_mixin.TrackMixinWithInternalNameManager import (
    TrackMixinWithInternalNameManager,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from .Artist import Artist

# Below pg_trgm's 0.6 default so a one-letter typo in a long name still matches ("radiohed" -> "Radiohead").
SEARCH_WORD_SIMILARITY_THRESHOLD = 0.4


class ArtistManager(TrackMixinWithInternalNameManager["Artist"]):
    model: type[Artist]

    def get_default_ordering(self) -> list[str]:
        return [TrackMixinFields.NAME_INTERNAL]

    def get_artists_list_from_names_after_potential_creation(
        self, user: User, artists_names: list[str] | None
    ) -> list[Artist]:
        return (
            [self.get_or_create(user=user, name=artist_name)[0] for artist_name in artists_names]
            if artists_names and len(artists_names) > 0
            else []
        )

    def search(self, query: str, limit: int) -> list[Artist]:
        from grow.model.artist.Artist import SPECIAL_PURPOSE_ARTIST_MBIDS
        from grow.model.artist_alias.ArtistAlias import ArtistAlias

        def folded(field: str) -> Func:
            return Func(F(field), function="grow_search_norm", output_field=TextField())

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true), grow_search_norm(%s)",
                [str(SEARCH_WORD_SIMILARITY_THRESHOLD), query],
            )
            folded_query = cursor.fetchone()[1]
            alias_hits = ArtistAlias.objects.annotate(norm=folded("name")).filter(
                norm__trigram_word_similar=folded_query
            )
            best_alias = (
                alias_hits.filter(artist=OuterRef("pk"))
                .annotate(score=TrigramWordSimilarity(folded_query, "norm"))
                .order_by("-score")
            )
            return list(
                self.annotate(norm=folded("_name"))
                .filter(Q(norm__trigram_word_similar=folded_query) | Q(pk__in=alias_hits.values("artist_id")))
                .exclude(musicbrainz_artist_id__in=SPECIAL_PURPOSE_ARTIST_MBIDS)
                .annotate(
                    score_by_name=TrigramWordSimilarity(folded_query, "norm"),
                    score_by_alias=Coalesce(
                        Subquery(best_alias.values("score")[:1], output_field=FloatField()), Value(0.0)
                    ),
                    alias_name=Subquery(best_alias.values("name")[:1], output_field=TextField()),
                )
                .annotate(
                    score=Greatest(F("score_by_name"), F("score_by_alias")),
                    rank=Case(
                        When(norm=folded_query, then=2),
                        When(norm__startswith=folded_query, then=1),
                        default=0,
                    ),
                    matched_alias=Case(
                        When(score_by_alias__gt=F("score_by_name"), then=F("alias_name")),
                        default=None,
                        output_field=TextField(),
                    ),
                )
                .order_by("-rank", "-score", "-recording_count", "uuid")[:limit]
            )

    def delete_instance(self, instance: Artist):
        with transaction.atomic():
            self.delete_instance_with_albums_and_tracks(instance)

    def delete_instance_with_albums_and_tracks(self, instance: Artist) -> tuple[int, dict[str, int]]:
        from the_music_tree_genre_kit.track.Track import Track

        from grow.model.album.Album import Album

        # Keep deletion order for rollback tests

        for album in instance.albums.all():
            Album.objects.delete_instance_with_tracks_and_potentially_artists(album)

        for track in instance.tracks.all():
            Track.objects.delete_instance_with_checking_album_and_artists_potential_deletion(track)

        return instance.delete()

    def delete_instance_if_nothing_linked(self, instance: Artist) -> tuple[int, dict[str, int]]:
        if instance.albums.count() == 0:
            if instance.tracks.count() == 0:
                return instance.delete()
        return 0, {}
