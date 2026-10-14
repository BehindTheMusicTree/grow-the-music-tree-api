import uuid

from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from tests.utils.AppTestCase import AppTestCase

VARIOUS_ARTISTS = uuid.UUID("89ad4ac3-39f7-470e-963a-56509c546377")


class TestCase(AppTestCase):
    def test_flags_special_purpose_artists_only(self):
        factory = self.model_fixture_factory
        various = factory.create_artist("Various Artists", musicbrainz_artist_id=VARIOUS_ARTISTS)
        band = factory.create_artist("Pink Floyd", musicbrainz_artist_id=uuid.uuid4())
        legacy = factory.create_artist("No MBID")

        assert [ArtistMinimumSerializer(a).data["is_special_purpose"] for a in (various, band, legacy)] == [
            True,
            False,
            False,
        ]
