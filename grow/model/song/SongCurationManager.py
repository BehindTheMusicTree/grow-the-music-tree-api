from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q, QuerySet
from rest_framework.exceptions import APIException, NotFound
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict

from grow.curation.admin_rules import admin_provenance, invalid, upsert_admin_rule
from grow.curation.rows import InvalidRow, lock_writes
from grow.genre_graph.service import DATASET_KEY
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from grow.model.song.Song import Song
from grow.model.song.SongGenreUndo import SongGenreUndo
from grow.youtube import YoutubeLookupError, fetch_video_metadata

LINK_SUGGESTIONS_LIMIT = 50
SONG_GENRE_LIST = "song_genre"


class YoutubeUnavailable(APIException):
    status_code = 502
    default_detail = "The YouTube lookup failed; try again later"
    default_code = "youtube_unavailable"


class UndoConflict(APIException):
    status_code = 409
    default_detail = "A song changed since this assignment; reload before undoing"
    default_code = "undo_conflict"


class SongCurationManager:
    """Admin edits of songs: each writes the curation rule the pipeline reads, applies it to the row and
    marks the song manually edited."""

    @staticmethod
    def _stable_key(song: Song) -> str:
        if song.musicbrainz_recording_id is None:
            raise invalid("songs", f"{song.title} has no MusicBrainz id, so no curation rule can name it")
        return str(song.musicbrainz_recording_id)

    @transaction.atomic
    def assign_genre(self, songs: list[Song], genre: Genre | None, actor: Any) -> tuple[list[dict[str, Any]], UUID]:
        """Links, moves or (genre None) unlinks songs. Returns each one's previous genre uuid and an undo token whose
        snapshot (previous attributions, assignment revision, curation rule) `undo_assign_genre` restores exactly."""
        lock_catalogue_sources()
        lock_writes(CurationEntry.objects.all())
        if genre is not None and genre.wikidata_id is None:
            raise invalid("genre", "Only a wikidata-backed genre can be assigned; no curation list names the others")
        if genre is not None and genre.is_umbrella:
            raise invalid("genre", f"{genre.name} is an umbrella genre; assign one of its sub-genres instead")
        from grow.genre_graph.service import set_song_genre, song_attribution_state, song_genre

        keys = [self._stable_key(song) for song in songs]
        previous = []
        entries = []
        for song, key in zip(songs, keys, strict=True):
            old = song_genre(song)
            previous.append({"uuid": song.uuid, "genre": old.uuid if old else None})
            before = song_attribution_state(song)
            rule = CurationEntry.objects.filter(user=None, list_name=SONG_GENRE_LIST, key=key).first()
            entry: dict[str, Any] = {
                "song": str(song.uuid),
                "key": key,
                "old_genre": str(old.uuid) if old else None,
                "new_genre": str(genre.uuid) if genre else None,
                "rule": rule.row if rule else None,
                "was_manually_edited": song.is_manually_edited,
            }
            provenance = admin_provenance(actor, "admin")
            upsert_admin_rule(
                SONG_GENRE_LIST,
                {
                    "musicbrainz_recording_id": key,
                    "genre_item_id": genre.wikidata_id if genre else "",
                },
                actor,
                provenance=provenance,
            )
            if set_song_genre(song, genre, provenance=provenance):
                Song.objects.record_semantic_genre_change(song, old_genre=old, actor=actor)
                after = song_attribution_state(song)
                if before is None or after is None:
                    raise RuntimeError("The reference dataset disappeared during an assignment")
                entry["attributions"] = before[0]
                entry["assignment_revision"] = str(after[1])
            else:
                Song.objects.update_instance(song, actor=actor, genre=genre)
            entries.append(entry)
        return previous, SongGenreUndo.objects.create(actor=actor, entries=entries).token

    @transaction.atomic
    def undo_assign_genre(self, token: UUID, actor: Any) -> None:
        """Restores what `assign_genre` overwrote, for the whole batch or not at all: 409 when any song's assignment
        changed since (import, another admin). The token is single-use and only its creator can spend it."""
        lock_catalogue_sources()
        # Documented order: gate, dataset, curation rows, then track rows (a merge holds the dataset before tracks).
        GenreGraphDataset.objects.select_for_update().filter(pk=DATASET_KEY).first()
        lock_writes(CurationEntry.objects.all())
        undo = SongGenreUndo.objects.select_for_update().filter(token=token, actor=actor).first()
        if undo is None:
            raise NotFound("No such undo token")
        from grow.genre_graph.service import restore_song_snapshot, song_attribution_state, song_genre

        for entry in undo.entries:
            song = Song.objects.select_for_update().filter(pk=entry["song"]).first()
            if song is None:
                raise UndoConflict
            current = song_genre(song)
            if "assignment_revision" in entry:
                try:
                    restore_song_snapshot(
                        song, entry["attributions"], expected_assignment_revision=UUID(entry["assignment_revision"])
                    )
                except (GraphRevisionConflict, GraphValidationError, GenreGraphDataset.DoesNotExist) as e:
                    raise UndoConflict from e
                Song.objects.record_semantic_genre_change(song, old_genre=current, actor=actor)
            else:
                current_uuid = str(current.uuid) if current else None
                if song_attribution_state(song) is not None or current_uuid != entry["new_genre"]:
                    raise UndoConflict
                old = Genre.objects.filter(uuid=entry["old_genre"]).first() if entry["old_genre"] else None
                if entry["old_genre"] and old is None:
                    raise UndoConflict
                Song.objects.update_instance(song, actor=actor, genre=old)
            rule = CurationEntry.objects.filter(user=None, list_name=SONG_GENRE_LIST, key=entry["key"]).first()
            if entry["rule"] is not None:
                try:
                    CurationEntry.objects.upsert(SONG_GENRE_LIST, entry["rule"], actor=actor)
                except InvalidRow as e:
                    raise UndoConflict from e
            elif rule is not None:
                CurationEntry.objects.delete_instance(rule, actor=actor)
            Song.objects.filter(pk=song.pk).update(is_manually_edited=entry["was_manually_edited"])
        undo.delete()

    @transaction.atomic
    def update_youtube(self, song: Song, fields: dict[str, Any], actor: Any) -> Song:
        """Sets the video and/or its unplayable reason. Without an explicit reason, YouTube decides it."""
        key = self._stable_key(song)
        video_id = fields.get("youtube_video_id", song.youtube_video_id)
        reason = fields.get("youtube_unplayable_reason")
        if reason is None and "youtube_unplayable_reason" not in fields and video_id == song.youtube_video_id:
            reason = song.youtube_unplayable_reason
        policy = song.youtube_region_restriction if video_id == song.youtube_video_id else None
        if video_id is not None and (video_id != song.youtube_video_id or "youtube_unplayable_reason" in fields):
            try:
                fetched_reason, policy = fetch_video_metadata(video_id)
                if reason is None:
                    reason = fetched_reason
            except YoutubeLookupError as e:
                raise YoutubeUnavailable from e
        # The import's locked-row decision reads is_manually_edited, and an unchanged video skips update_instance's
        # gate. Taken after the YouTube call so the global gate is never held across the network.
        lock_catalogue_sources()
        lock_writes(CurationEntry.objects.all())
        explicit = fields.get("youtube_unplayable_reason") or ""
        upsert_admin_rule(
            "recording_youtube_video",
            {"musicbrainz_recording_id": key, "youtube_video_id": video_id or "", "unplayable_reason": explicit},
            actor,
        )
        if video_id is None:
            reason = None
            policy = None
        old_video_id = song.youtube_video_id
        if (video_id, reason, policy) == (
            old_video_id,
            song.youtube_unplayable_reason,
            song.youtube_region_restriction,
        ):
            updated = song
        else:
            updated = Song.objects.update_instance(
                song,
                actor=actor,
                youtube_video_id=video_id,
                youtube_unplayable_reason=reason,
                youtube_region_restriction=policy,
                youtube_view_count=song.youtube_view_count if video_id == old_video_id else None,
            )
            HistoryEntry.objects.record(
                updated, action=HistoryAction.UPDATED, actor=actor, old_value=old_video_id, new_value=video_id
            )
        updated.is_manually_edited = True
        updated.save(update_fields=["is_manually_edited"])
        return updated

    @staticmethod
    def link_suggestions(genre: Genre) -> QuerySet[Song]:
        """Genreless songs by artists who already have songs in the genre's subtree, most shared first."""
        descendants = CriteriaLineageRel.objects.filter(ascendant=genre).values_list("descendant", flat=True)
        in_subtree = Song.objects.filter(membership_genre__in=[genre, *descendants]).values("pk")
        assigned = Song.objects.filter(membership_genre__isnull=False).values("pk")
        artist_ids = list(
            Song.objects.filter(pk__in=in_subtree, artists__isnull=False).values_list("artists", flat=True).distinct()
        )
        return (
            Song.objects.exclude(pk__in=assigned)
            .filter(artists__in=artist_ids)
            .annotate(shared_artists=Count("artists", distinct=True))
            .order_by("-shared_artists", "uuid")[:LINK_SUGGESTIONS_LIMIT]
        )
