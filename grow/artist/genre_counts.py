from uuid import UUID

from django.db.models import Count, Q
from rest_framework.exceptions import NotFound

from grow.model.artist.Artist import Artist
from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.playable import PLAYABLE
from grow.model.song.Song import Song


def artist_genre_counts(artist_id: str) -> list[dict]:
    """
    Sparse per-genre-playlist counts of an artist's canonical songs, each genre folding in its primary descendants'
    (the subtree `library/songs/?genre=` lists). Songs without a genre count toward the Genreless playlist.
    At most 3 queries, whatever the number of songs; the artist is only looked up (404) when it has no songs.
    """
    try:
        artist_uuid = UUID(artist_id)
    except ValueError:
        raise NotFound from None
    own: dict[int | None, list[int]] = {
        row["genre"]: [row["songs"], row["playable"]]
        for row in Song.objects.filter(user__isnull=True, artists=artist_uuid)
        .order_by()
        .values("genre")
        .annotate(songs=Count("pk"), playable=Count("pk", filter=PLAYABLE))
    }
    if not own:
        if not Artist.objects.filter(user__isnull=True, uuid=artist_uuid).exists():
            raise NotFound
        return []

    folded = {genre: counts[:] for genre, counts in own.items()}
    genres = [genre for genre in own if genre is not None]
    for descendant, ascendant in CriteriaLineageRel.objects.filter(
        user__isnull=True, descendant__in=genres
    ).values_list("descendant", "ascendant"):
        for index, count in enumerate(own[descendant]):
            folded.setdefault(ascendant, [0, 0])[index] += count

    wanted = Q(criteria__in=[genre for genre in folded if genre is not None])
    if None in folded:
        wanted |= Q(criteria__isnull=True)
    playlists = GenrePlaylist.objects.filter(wanted, user__isnull=True)
    return [
        {"genre_playlist": uuid, "songs_count": folded[genre][0], "tracks_count": folded[genre][1]}
        for genre, uuid in playlists.values_list("criteria", "uuid")
    ]
