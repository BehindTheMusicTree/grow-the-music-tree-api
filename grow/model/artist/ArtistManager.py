import uuid
from typing import TYPE_CHECKING

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db import connection, transaction
from django.db.models import Case, F, IntegerField, TextField, Value, When
from the_music_tree_genre_kit.track_mixin.Fields import Fields as TrackMixinFields
from the_music_tree_genre_kit.track_mixin.TrackMixinWithInternalNameManager import (
    TrackMixinWithInternalNameManager,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from .Artist import Artist

# Below pg_trgm's 0.6 default so a one-letter typo in a long name still matches ("radiohed" -> "Radiohead").
SEARCH_WORD_SIMILARITY_THRESHOLD = 0.4
SEARCH_DUPLICATE_HEADROOM = 4


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

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true), grow_search_norm(%s)",
                [str(SEARCH_WORD_SIMILARITY_THRESHOLD), query],
            )
            folded_query = cursor.fetchone()[1]

            def rank(field: str) -> Case:
                return Case(
                    When(**{field: folded_query}, then=2),
                    When(**{f"{field}__startswith": folded_query}, then=1),
                    default=0,
                )

            by_name = (
                self.filter(folded_name__trigram_word_similar=folded_query)
                .exclude(musicbrainz_artist_id__in=SPECIAL_PURPOSE_ARTIST_MBIDS)
                .values(
                    artist_uuid=F("uuid"),
                    score=TrigramWordSimilarity(folded_query, "folded_name"),
                    rank=rank("folded_name"),
                    matched_alias=Value(None, output_field=TextField()),
                    count=F("recording_count"),
                    is_alias=Value(0, output_field=IntegerField()),
                )
            )
            by_alias = (
                ArtistAlias.objects.filter(folded_name__trigram_word_similar=folded_query)
                .exclude(artist__musicbrainz_artist_id__in=SPECIAL_PURPOSE_ARTIST_MBIDS)
                .values(
                    artist_uuid=F("artist_id"),
                    score=TrigramWordSimilarity(folded_query, "folded_name"),
                    rank=rank("artist__folded_name"),
                    matched_alias=F("name"),
                    count=F("artist__recording_count"),
                    is_alias=Value(1, output_field=IntegerField()),
                )
            )
            # An artist can match by its name and several aliases; sorting best-first (a name wins a tie with an alias)
            # makes its first row the one to keep, and the over-fetch leaves room for the dropped duplicates.
            rows = by_name.union(by_alias, all=True).order_by("-rank", "-score", "-count", "is_alias", "artist_uuid")[
                : limit * SEARCH_DUPLICATE_HEADROOM
            ]
            best: dict[uuid.UUID, str | None] = {}
            for row in rows:
                best.setdefault(row["artist_uuid"], row["matched_alias"])
                if len(best) == limit:
                    break
            artists = self.in_bulk(best)
            result = []
            for artist_uuid, matched_alias in best.items():
                artist = artists[artist_uuid]
                artist.matched_alias = matched_alias
                result.append(artist)
            return result

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
