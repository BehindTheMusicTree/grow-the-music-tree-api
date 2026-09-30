from the_music_tree_genre_kit.playlist.Fields import Fields as ModelFields


class Fields:
    CREATED_ON = ModelFields.CREATED_ON
    UPDATED_ON = ModelFields.UPDATED_ON
    UUID = ModelFields.UUID
    NAME = ModelFields.NAME_PUBLIC
    TRACKS_PUBLIC = ModelFields.TRACKS_PUBLIC
    TRACKS_INTERNAL = ModelFields.TRACKS_INTERNAL
    TRACKS_COUNT_INTERNAL = ModelFields.TRACKS_COUNT_INTERNAL
    TRACKS_COUNT_PUBLIC = ModelFields.TRACKS_COUNT_PUBLIC
    TRACKS_COUNT_ANNOTATED = f"{ModelFields.TRACKS_COUNT_INTERNAL}_annotated"
    PLAY_COUNT = ModelFields.PLAY_COUNT
    TYPE_LABEL_PUBLIC = ModelFields.TYPE_LABEL_PUBLIC
    TYPE_LABEL_INTERNAL = ModelFields.TYPE_LABEL_INTERNAL
