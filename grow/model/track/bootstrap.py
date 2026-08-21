from the_music_tree_genre_kit.track.Track import Track as KitTrack

from .TrackConvenienceMixin import TrackConvenienceMixin


def install_track_convenience_methods() -> None:
    """
    Patches the kit's plain `Track` class with grow's polymorphism conveniences, so
    FK/generic-FK dereferences typed as `settings.TRACK_MODEL` (e.g. `TrackPlaylistRel.track`,
    `Play.content`) can call `resolve_concrete()` without an explicit downcast. `UploadedTrack`/
    `YoutubeTrack` inherit `KitTrack` and therefore pick these up too, making the separate
    `TrackConvenienceMixin` base on those classes redundant, but harmless (same implementation).
    """
    KitTrack.resolve_concrete = TrackConvenienceMixin.resolve_concrete
    KitTrack.__str__ = TrackConvenienceMixin.__str__
    KitTrack.simple_str = TrackConvenienceMixin.simple_str
    KitTrack.playlists_with_positions = TrackConvenienceMixin.playlists_with_positions
