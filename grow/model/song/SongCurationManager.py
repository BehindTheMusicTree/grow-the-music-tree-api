import uuid as uuid_lib
from typing import Any

from django.db import transaction
from django.db.models import Count, Q, QuerySet
from rest_framework.exceptions import APIException

from grow.curation.admin_rules import invalid, upsert_admin_rule
from grow.curation.rows import lock_writes
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from grow.model.song.Song import Song
from grow.youtube import YoutubeLookupError, fetch_unplayable_reason

SEARCH_PAGE_SIZE = 50
LINK_SUGGESTIONS_LIMIT = 50


class YoutubeUnavailable(APIException):
    status_code = 502
    default_detail = "The YouTube lookup failed; try again later"
    default_code = "youtube_unavailable"


class SongCurationManager:
    """Admin edits of songs: each writes the curation rule the pipeline reads, applies it to the row and
    marks the song manually edited."""

    @staticmethod
    def _stable_key(song: Song) -> str:
        if song.musicbrainz_recording_id is None:
            raise invalid("songs", f"{song.title} has no MusicBrainz id, so no curation rule can name it")
        return str(song.musicbrainz_recording_id)

    @transaction.atomic
    def assign_genre(self, songs: list[Song], genre: Genre | None, actor: Any) -> list[dict[str, Any]]:
        """Links, moves or (genre None) unlinks songs; returns each one's previous genre uuid for Undo, which
        can't restore a genre without a wikidata id since no curation list names it (`undoable` false)."""
        lock_writes(CurationEntry.objects.all())
        if genre is not None and genre.wikidata_id is None:
            raise invalid("genre", "Only a wikidata-backed genre can be assigned; no curation list names the others")
        if genre is not None and genre.is_umbrella:
            raise invalid("genre", f"{genre.name} is an umbrella genre; assign one of its sub-genres instead")
        keys = [self._stable_key(song) for song in songs]
        previous = []
        for song, key in zip(songs, keys, strict=True):
            old = song.genre
            previous.append(
                {
                    "uuid": song.uuid,
                    "genre": old.uuid if old else None,
                    "undoable": old is None or old.genre.wikidata_id is not None,
                }
            )
            upsert_admin_rule(
                "song_genre",
                {
                    "musicbrainz_recording_id": key,
                    "genre_item_id": genre.wikidata_id if genre else "",
                },
                actor,
            )
            Song.objects.update_instance(song, actor=actor, genre=genre)
        return previous

    @transaction.atomic
    def update_youtube(self, song: Song, fields: dict[str, Any], actor: Any) -> Song:
        """Sets the video and/or its unplayable reason. Without an explicit reason, YouTube decides it."""
        lock_writes(CurationEntry.objects.all())
        key = self._stable_key(song)
        video_id = fields.get("youtube_video_id", song.youtube_video_id)
        reason = fields.get("youtube_unplayable_reason")
        if reason is None and "youtube_unplayable_reason" not in fields and video_id == song.youtube_video_id:
            reason = song.youtube_unplayable_reason
        if (
            reason is None
            and video_id is not None
            and (video_id != song.youtube_video_id or "youtube_unplayable_reason" in fields)
        ):
            try:
                reason = fetch_unplayable_reason(video_id)
            except YoutubeLookupError as e:
                raise YoutubeUnavailable from e
        explicit = fields.get("youtube_unplayable_reason") or ""
        upsert_admin_rule(
            "recording_youtube_video",
            {"musicbrainz_recording_id": key, "youtube_video_id": video_id or "", "unplayable_reason": explicit},
            actor,
        )
        if video_id is None:
            reason = None
        old_video_id = song.youtube_video_id
        if (video_id, reason) == (old_video_id, song.youtube_unplayable_reason):
            updated = song
        else:
            updated = Song.objects.update_instance(
                song,
                actor=actor,
                youtube_video_id=video_id,
                youtube_unplayable_reason=reason,
                youtube_view_count=song.youtube_view_count if video_id == old_video_id else None,
            )
            HistoryEntry.objects.record(
                updated, action=HistoryAction.UPDATED, actor=actor, old_value=old_video_id, new_value=video_id
            )
        updated.is_manually_edited = True
        updated.save(update_fields=["is_manually_edited"])
        return updated

    @staticmethod
    def search(query: str, genreless: bool, cursor: uuid_lib.UUID | None) -> QuerySet[Song]:
        queryset = Song.objects.all()
        if query:
            queryset = queryset.filter(Q(title__icontains=query) | Q(artists___name__icontains=query)).distinct()
        if genreless:
            queryset = queryset.filter(genre__isnull=True)
        if cursor is not None:
            queryset = queryset.filter(uuid__gt=cursor)
        return queryset.order_by("uuid")

    @staticmethod
    def link_suggestions(genre: Genre) -> QuerySet[Song]:
        """Genreless songs by artists who already have songs in the genre's subtree, most shared first."""
        descendants = CriteriaLineageRel.objects.filter(ascendant=genre).values_list("descendant", flat=True)
        artist_ids = list(
            Song.objects.filter(genre__in=[genre, *descendants], artists__isnull=False)
            .values_list("artists", flat=True)
            .distinct()
        )
        return (
            Song.objects.filter(genre__isnull=True, artists__in=artist_ids)
            .annotate(shared_artists=Count("artists", distinct=True))
            .order_by("-shared_artists", "uuid")[:LINK_SUGGESTIONS_LIMIT]
        )
