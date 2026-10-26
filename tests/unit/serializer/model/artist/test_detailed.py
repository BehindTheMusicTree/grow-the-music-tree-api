from grow.model.artist.Artist import Artist
from grow.serializer.model.artist.detailed import ArtistDetailedSerializer
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_serializes_details_members_groups_links_and_albums(self):
        factory = self.model_fixture_factory
        band = factory.create_artist("Pink Floyd", type=Artist.Type.GROUP, country="GB", begin_year=1965, ended=True)
        waters = factory.create_artist("Roger Waters")
        factory.create_artist_membership(
            band, waters, begin_year=1965, end_year=1985, ended=True, roles=["bass guitar"]
        )
        factory.create_artist_link(band, "official", "https://pinkfloyd.com")
        album = factory.create_album(name="The Wall", year="1979", primary_type="Album", secondary_types=["Live"])
        album.album_artists.set([band])
        factory.create_song(title="Comfortably Numb", genre=factory.create_genre("Rock"), artists=[band])

        def serialize(artist):
            return ArtistDetailedSerializer(
                ArtistDetailedSerializer.setup_queryset(Artist.objects.filter(pk=artist.pk)).get()
            ).data

        data = serialize(band)

        assert (data["type"], data["country"], data["begin_year"], data["end_year"], data["ended"]) == (
            "group",
            "GB",
            1965,
            None,
            True,
        )
        assert data["links"] == [{"kind": "official", "url": "https://pinkfloyd.com"}]
        assert data["members"] == [
            {
                "artist": {"uuid": str(waters.uuid), "name": "Roger Waters", "is_special_purpose": False},
                "begin_year": 1965,
                "end_year": 1985,
                "ended": True,
                "roles": ["bass guitar"],
            }
        ]
        assert data["member_of"] == []
        assert data["albums"] == [
            {
                "uuid": str(album.uuid),
                "name": "The Wall",
                "year": "1979",
                "primary_type": "Album",
                "secondary_types": ["Live"],
            }
        ]
        assert data["tracks_count"] == 1
        assert serialize(waters)["member_of"][0]["artist"]["name"] == "Pink Floyd"
