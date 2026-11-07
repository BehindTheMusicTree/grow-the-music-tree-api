from dataclasses import asdict
from uuid import UUID

from rest_framework.exceptions import NotFound

from grow.genre_music.artist import artist_exact_counts, artist_nonzero_catalogue_counts, playlist_counts
from grow.genre_music.catalogue import GenreScopedCounts
from grow.genre_music.selection import genre_tree_snapshot
from grow.model.artist.Artist import Artist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist


def artist_genre_counts(artist_id: str) -> list[dict]:
    """Return scoped catalogue and actual playlist membership counts for an artist."""
    try:
        artist_uuid = UUID(artist_id)
    except ValueError:
        raise NotFound from None

    snapshot = genre_tree_snapshot()
    exact = artist_exact_counts(artist_uuid)
    if not exact:
        if not Artist.objects.filter(user__isnull=True, uuid=artist_uuid).exists():
            raise NotFound
        return []
    catalogue = artist_nonzero_catalogue_counts(exact, snapshot)
    playlists = {genre: snapshot.playlists.get(genre) for genre in catalogue if genre is not None}
    if exact.get(None):
        playlists[None] = (
            GenrePlaylist.objects.filter(user__isnull=True, criteria__isnull=True)
            .values_list("uuid", flat=True)
            .first()
        )
    memberships = playlist_counts(artist_uuid, (snapshot.tree_names, snapshot.primary_edges))
    result = []
    for genre, uuid in playlists.items():
        counts = catalogue[genre]
        if uuid is None or not counts.genre_and_subgenres_tracks_count["all"]:
            continue
        membership = memberships.get(uuid)
        if membership is None:
            membership = GenreScopedCounts(0, dict.fromkeys(counts.genre_and_subgenres_tracks_count, 0))
        result.append(
            {
                "genre_playlist": uuid,
                "songs_count": counts.default_count,
                "tracks_count": membership.default_count,
                "catalogue": asdict(counts),
                **asdict(membership),
            }
        )
    return result
