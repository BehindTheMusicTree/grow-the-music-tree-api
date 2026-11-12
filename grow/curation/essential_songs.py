from collections.abc import Iterable

from grow.curation.rows import KEY_SEPARATOR, InvalidRow
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.song.Song import Song

LIST_NAME = "essential_songs"


def apply_essential_songs(item_ids: Iterable[str]) -> None:
    """Sets each canonical genre's ordered essential songs from its `essential_songs` entries, so a curation edit
    shows in the API without waiting for the pipeline. Gold still checks every MBID against the songs export.

    Doesn't lock the genre (the tree import never touches essential songs) nor write rules (they are the input)."""
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
        missing = [mbid for mbid in mbids if mbid not in songs]
        if missing:
            raise InvalidRow({"musicbrainz_recording_id": f"{missing[0]} is not a song in grow"})
        Genre.objects.set_essential_songs(genre, [songs[mbid] for mbid in mbids])
