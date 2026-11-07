from dataclasses import asdict
from uuid import UUID

from rest_framework.exceptions import NotFound

from grow.genre_music.artist import artist_catalogue_counts, playlist_counts
from grow.genre_music.catalogue import GenreScopedCounts
from grow.model.artist.Artist import Artist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist


def artist_genre_counts(artist_id: str) -> list[dict]:
    """Return scoped catalogue and actual playlist membership counts for an artist."""
    try:
        artist_uuid = UUID(artist_id)
    except ValueError:
        raise NotFound from None

    rows = list(
        GenrePlaylist.objects.filter(user__isnull=True).values_list(
            "uuid",
            "criteria_id",
            "criteria__tree_name",
            "criteria__parent_id",
            "criteria__additional_primary_parents__pk",
        )
    )
    playlists = {genre: uuid for uuid, genre, _, _, _ in rows}
    trees = {genre: tree for _, genre, tree, _, _ in rows if genre is not None}
    edges = {
        (parent, genre)
        for _, genre, _, direct, extra in rows
        for parent in (direct, extra)
        if genre is not None and parent in trees
    }
    graph = trees, edges
    catalogue = artist_catalogue_counts(artist_uuid, graph)
    if not any(count.genre_and_subgenres_tracks_count["all"] for count in catalogue.values()):
        if not Artist.objects.filter(user__isnull=True, uuid=artist_uuid).exists():
            raise NotFound
        return []
    memberships = playlist_counts(artist_uuid, graph)
    result = []
    for genre, uuid in playlists.items():
        counts = catalogue[genre]
        if not counts.genre_and_subgenres_tracks_count["all"]:
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
