import uuid

import pytest
from django.db import IntegrityError

from grow.model.artist.Artist import Artist
from grow.model.artist_link.ArtistLink import ArtistLink
from grow.model.artist_membership.ArtistMembership import ArtistMembership
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_deleting_artist_cascades_to_memberships_both_ways_and_links(self):
        factory = self.model_fixture_factory
        band, member, other = (factory.create_artist(name) for name in ("Band", "Member", "Other"))
        factory.create_artist_membership(band, member)
        factory.create_artist_membership(member, other)
        factory.create_artist_link(member, "official", "https://member.example")

        member.delete()

        assert not ArtistMembership.objects.exists() and not ArtistLink.objects.exists()

    def test_musicbrainz_artist_id_is_unique_but_optional(self):
        mbid = uuid.uuid4()
        self.model_fixture_factory.create_artist("A", musicbrainz_artist_id=mbid)
        self.model_fixture_factory.create_artist("B")
        self.model_fixture_factory.create_artist("C")

        with pytest.raises(IntegrityError):
            self.model_fixture_factory.create_artist("D", musicbrainz_artist_id=mbid)

    def test_image_requires_url_page_url_and_license_together(self):
        artist = self.model_fixture_factory.create_artist("A")

        with pytest.raises(IntegrityError):
            Artist.objects.filter(pk=artist.pk).update(
                image_url="https://upload.wikimedia.org/a.jpg", image_page_url="https://commons.wikimedia.org/a"
            )
