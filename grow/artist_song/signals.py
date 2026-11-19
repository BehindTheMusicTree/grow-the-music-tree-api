"""ORM writes no manager hook sees: credits changed through the M2M and an album's year edited in place."""

from the_music_tree_genre_kit.track.Track import Track

from grow.model.album.Album import Album
from grow.model.artist_song.ArtistSong import ArtistSong


def on_credits_changed(sender, instance, action, reverse, pk_set, **kwargs) -> None:
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    if not reverse:
        ArtistSong.objects.refresh_songs([instance.pk])
    elif pk_set:  # an artist's side: the songs it was added to or removed from
        ArtistSong.objects.refresh_songs(pk_set)


def on_album_saved(sender, instance, created, **kwargs) -> None:
    if not created:
        ArtistSong.objects.refresh_songs(Track.objects.filter(album_id=instance.pk).values_list("pk", flat=True))


def connect() -> None:
    from django.db.models.signals import m2m_changed, post_save

    m2m_changed.connect(on_credits_changed, sender=Track.artists.through, dispatch_uid="grow_artist_song_credits")
    post_save.connect(on_album_saved, sender=Album, dispatch_uid="grow_artist_song_album_saved")
