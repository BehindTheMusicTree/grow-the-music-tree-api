import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory, override_settings
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from grow.track.bulk_import.part_loader import _row
from grow.youtube_regions import (
    attemptable,
    availability,
    normalize_policy,
    policy_from_item,
    viewer_country,
    with_region_status,
)
from tests.utils.AppTestCase import AppTestCase

VECTORS = [
    (None, "FR", "unknown"),
    ({"mode": "unrestricted", "countries": []}, None, "eligible"),
    ({"mode": "allowed", "countries": ["FR"]}, "FR", "eligible"),
    ({"mode": "allowed", "countries": ["FR"]}, "AL", "blocked"),
    ({"mode": "allowed", "countries": ["FR"]}, None, "unknown"),
    ({"mode": "blocked", "countries": ["AL"]}, "AL", "blocked"),
    ({"mode": "blocked", "countries": ["AL"]}, "FR", "eligible"),
    ({"mode": "allowed", "countries": []}, None, "blocked"),
    ({"mode": "blocked", "countries": []}, None, "eligible"),
]


@pytest.mark.parametrize("policy,country,status", VECTORS)
def test_policy_evaluator(policy, country, status):
    song = SimpleNamespace(
        youtube_video_id="77hyIqy4HiQ", youtube_unplayable_reason=None, youtube_region_restriction=policy
    )
    result = availability(song, country)
    assert result == {"status": status, "reason": "region_blocked" if status == "blocked" else None, "country": country}
    song.youtube_unplayable_reason = "private"
    assert availability(song, country)["reason"] == "private"


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"mode": "allowed", "countries": ["fr"]},
        {"mode": "unrestricted", "countries": ["FR"]},
        {"mode": "blocked", "countries": ["XX"]},
    ],
)
def test_invalid_policy(value):
    with pytest.raises(ValueError, match=r"region|country|unrestricted"):
        normalize_policy(value)


def test_metadata_empty_lists_and_normalization():
    assert policy_from_item(None) is None
    assert policy_from_item({"contentDetails": {}}) == {"mode": "unrestricted", "countries": []}
    assert policy_from_item({"contentDetails": {"regionRestriction": {"allowed": []}}}) == {
        "mode": "allowed",
        "countries": [],
    }
    assert normalize_policy({"mode": "allowed", "countries": ["GB", "FR", "FR"]})["countries"] == ["FR", "GB"]


@override_settings(VIEWER_CONTEXT_TOKEN="trusted")
def test_country_requires_authenticated_proxy_context():
    factory = RequestFactory()
    for headers in (
        {},
        {"HTTP_CF_IPCOUNTRY": "FR"},
        {"HTTP_X_VIEWER_COUNTRY": "FR", "HTTP_X_VIEWER_CONTEXT_TOKEN": "forged"},
        {"HTTP_X_VIEWER_COUNTRY": "XX", "HTTP_X_VIEWER_CONTEXT_TOKEN": "trusted"},
    ):
        assert viewer_country(factory.get("/", **headers)) is None
    assert viewer_country(factory.get("/", HTTP_X_VIEWER_COUNTRY="FR", HTTP_X_VIEWER_CONTEXT_TOKEN="trusted")) == "FR"


def test_import_policy_requires_video_and_old_exports_stay_unknown():
    song = {
        "musicbrainz_recording_id": "b1a9c0e9-d987-4042-ae91-78d6a3267d69",
        "title": "Song",
        "artist": "Artist",
        "first_release_year": None,
    }
    assert _row(1, json.dumps(song).encode())[-1] is None
    with pytest.raises(ValidationError):
        _row(1, json.dumps({**song, "youtube_region_restriction": {"mode": "allowed", "countries": []}}).encode())


class TestCountryPredicates(AppTestCase):
    def test_database_predicate_matches_evaluator(self):
        for index, (policy, country, status) in enumerate(VECTORS):
            song = self.model_fixture_factory.create_song(
                genre=None, title=f"Song {index}", youtube_video_id="77hyIqy4HiQ"
            )
            song.youtube_region_restriction = policy
            song.save(update_fields=["youtube_region_restriction"])
            assert with_region_status(type(song).objects.filter(pk=song.pk), country).filter(
                attemptable(country)
            ).exists() == (status != "blocked")


@override_settings(VIEWER_CONTEXT_TOKEN="trusted")
class TestContextResponses(AppTestCase):
    def test_context_is_public_and_private_no_store(self):
        response = self.api_client.get(
            reverse("playback-context"), HTTP_X_VIEWER_CONTEXT_TOKEN="trusted", HTTP_X_VIEWER_COUNTRY="FR"
        )
        assert response.json() == {"country": "FR"}
        assert response["Cache-Control"] == "private, no-store"

    def test_song_detail_exposes_region_without_rewriting_global_reason(self):
        song = self.model_fixture_factory.create_song(genre=None, title="Region", youtube_video_id="77hyIqy4HiQ")
        song.youtube_region_restriction = {"mode": "allowed", "countries": ["FR"]}
        song.save(update_fields=["youtube_region_restriction"])
        response = self.api_client.get(
            reverse("song-detail", kwargs={"pk": song.uuid}),
            HTTP_X_VIEWER_CONTEXT_TOKEN="trusted",
            HTTP_X_VIEWER_COUNTRY="AL",
        )
        assert response["X-Playback-Country"] == "AL"
        assert response.json()["youtubeVideo"]["availability"] == {
            "status": "blocked",
            "reason": "region_blocked",
            "country": "AL",
        }
        song.refresh_from_db()
        assert song.youtube_unplayable_reason is None
