from collections.abc import Iterable

from grow.curation.rows import KEY_SEPARATOR, InvalidRow
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.song.Song import Song

LIST_NAME = "essential_songs"


def _check_required(required_mbids: Iterable[str]) -> None:
    mbids = list(required_mbids)
    found = {
        str(m)
        for m in Song.objects.filter(user=None, musicbrainz_recording_id__in=mbids).values_list(
            "musicbrainz_recording_id", flat=True
        )
    }
    missing = [mbid for mbid in mbids if mbid not in found]
    if missing:
        raise InvalidRow({"musicbrainz_recording_id": f"{missing[0]} is not a song in grow"})


def apply_essential_songs(item_ids: Iterable[str], required_mbids: Iterable[str] = ()) -> None:
    """Sets each canonical genre's ordered essential songs from its `essential_songs` entries, so a curation edit
    shows in the API without waiting for the pipeline. Gold still checks every MBID against the songs export.

    A rule naming a song grow no longer has is skipped, so a genre with stale rules stays editable (the pipeline's
    Gold stage fails on them); only `required_mbids`, the entry being written, must exist.

    Doesn't lock the genre (the tree import never touches essential songs) nor write rules (they are the input)."""
    _check_required(required_mbids)
    for item_id in dict.fromkeys(item_ids):
        genre = Genre.objects.filter(user=None, wikidata_id=item_id).first()
        if genre is None:
            raise InvalidRow({"item_id": f"{item_id} is not a genre in grow"})
        entries = sorted(
            CurationEntry.objects.filter(user=None, list_name=LIST_NAME, key__startswith=f"{item_id}{KEY_SEPARATOR}"),
            key=lambda entry: (int(entry.values["position"]), entry.key),
        )
        mbids = [entry.key.split(KEY_SEPARATOR)[1] for entry in entries]
        songs = {
            str(song.musicbrainz_recording_id): song
            for song in Song.objects.filter(user=None, musicbrainz_recording_id__in=mbids)
        }
        Genre.objects.set_essential_songs(genre, [songs[mbid] for mbid in mbids if mbid in songs])
