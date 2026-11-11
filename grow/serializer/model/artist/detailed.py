from django.db.models import Prefetch
from rest_framework import serializers
from the_music_tree_api_kit.commons_image.helpers import commons_image_representation
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin

from grow.model.album.Album import Album
from grow.model.album.Fields import Fields as AlbumFields
from grow.model.artist.Artist import Artist
from grow.model.artist_link.ArtistLink import ArtistLink
from grow.model.artist_link.Fields import Fields as LinkFields
from grow.model.artist_membership.ArtistMembership import ArtistMembership
from grow.model.artist_membership.Fields import Fields as MembershipFields
from grow.region_map.drawn_regions import drawn_region_ids
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.artist.simple import playable_tracks_count, tracks_count

from .Fields import Fields

ARTIST = "artist"


class _MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArtistMembership
        fields = [
            ARTIST,
            MembershipFields.BEGIN_YEAR,
            MembershipFields.END_YEAR,
            MembershipFields.ENDED,
            MembershipFields.ROLES,
        ]


class _MemberSerializer(_MembershipSerializer):
    artist = ArtistMinimumSerializer(source=MembershipFields.MEMBER)


class _GroupSerializer(_MembershipSerializer):
    artist = ArtistMinimumSerializer(source=MembershipFields.GROUP)


class _LinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArtistLink
        fields = [LinkFields.KIND, LinkFields.URL]


class _AlbumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Album
        fields = [
            AlbumFields.UUID,
            AlbumFields.NAME_PUBLIC,
            AlbumFields.YEAR,
            AlbumFields.PRIMARY_TYPE,
            AlbumFields.SECONDARY_TYPES,
        ]


class ArtistDetailedSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    links = _LinkSerializer(many=True)
    members = _MemberSerializer(many=True)
    member_of = _GroupSerializer(many=True)
    albums = _AlbumSerializer(many=True)
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_COUNT_ANNOTATED)
    playable_tracks_count = serializers.IntegerField()
    image = serializers.SerializerMethodField()
    origin = serializers.SerializerMethodField()

    def get_image(self, artist: Artist) -> dict | None:
        return commons_image_representation(artist)

    def get_origin(self, artist: Artist) -> dict | None:
        if artist.origin_name is None:
            return None
        region_id = artist.origin_region_id
        return {
            "name": artist.origin_name,
            "kind": artist.origin_kind,
            "source": artist.origin_source,
            "wikidata_id": artist.origin_wikidata_id,
            "longitude": artist.origin_longitude,
            "latitude": artist.origin_latitude,
            # Imported separately from the region map, so only a region the latest index draws resolves on /map.
            "region_id": region_id if region_id is not None and region_id in drawn_region_ids() else None,
        }

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        def ordered(model, *order_by):
            return model._default_manager.order_by(*order_by, "pk")

        return queryset.annotate(
            **{
                Fields.TRACKS_COUNT_ANNOTATED: tracks_count(prefix),
                Fields.PLAYABLE_TRACKS_COUNT: playable_tracks_count(prefix),
            }
        ).prefetch_related(
            Prefetch(f"{prefix}{Fields.LINKS}", ordered(ArtistLink, LinkFields.KIND, LinkFields.URL)),
            Prefetch(
                f"{prefix}{Fields.MEMBERS}",
                ordered(ArtistMembership, MembershipFields.BEGIN_YEAR).select_related(MembershipFields.MEMBER),
            ),
            Prefetch(
                f"{prefix}{Fields.MEMBER_OF}",
                ordered(ArtistMembership, MembershipFields.BEGIN_YEAR).select_related(MembershipFields.GROUP),
            ),
            Prefetch(f"{prefix}{Fields.ALBUMS}", ordered(Album, AlbumFields.YEAR, AlbumFields.NAME_INTERNAL)),
        )

    class Meta:
        model = Artist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.MUSICBRAINZ_ARTIST_ID,
            Fields.TYPE,
            Fields.COUNTRY,
            Fields.BEGIN_YEAR,
            Fields.END_YEAR,
            Fields.ENDED,
            Fields.IMAGE,
            Fields.ORIGIN,
            Fields.LINKS,
            Fields.MEMBERS,
            Fields.MEMBER_OF,
            Fields.ALBUMS,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.PLAYABLE_TRACKS_COUNT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
