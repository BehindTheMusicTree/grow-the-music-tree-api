from django.contrib.auth.models import User
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist


def snapshot_kit_seeded_data():
    """
    Captures the exact rows a `TransactionTestCase` flush would otherwise
    permanently destroy, so `restore_kit_seeded_data` can recreate them
    with matching pks right after such a flush.

    `the_music_tree_genre_kit` ships no top-level `models.py`, so Django's test
    serializer (`BaseDatabaseCreation.serialize_db_to_string`, gated on
    `app_config.models_module is not None`) silently skips its tables
    (`CriteriaType`, `Playlist`), even though it DOES capture `auth_user` and
    `grow_criteria_playlist` (an MTI child of `Playlist`, owned by this app).
    Any later `TransactionTestCase` that restores via `serialized_rollback`
    reinserts those rows with their original pks/uuids via `save_base(raw=True)`
    (an UPDATE-or-INSERT, so pre-existing rows are just harmlessly updated), so
    whatever we recreate here must reuse the same pks/uuids or that later
    restore hits a dangling FK on the kit's `Playlist`/`CriteriaType` tables.
    """
    return {
        "users": list(User.objects.values()),
        "criteria_types": list(CriteriaType.objects.values("pk", "label")),
        "criterialess_playlists": list(
            CriteriaPlaylist.objects.filter(criteria=None).values("pk", "uuid", "root_id", "user_id", "type_id")
        ),
    }


def restore_kit_seeded_data(snapshot):
    # bulk_create (not .create()/.save()) deliberately skips post_save signals:
    # create_user_criterialess_playlists would otherwise bootstrap fresh-uuid
    # CriteriaPlaylist rows here, duplicating the ones restored below by pk.
    missing_user_rows = [row for row in snapshot["users"] if not User.objects.filter(pk=row["id"]).exists()]
    User.objects.bulk_create([User(**row) for row in missing_user_rows])

    for row in snapshot["criteria_types"]:
        CriteriaType.objects.get_or_create(pk=row["pk"], defaults={"label": row["label"]})

    for row in snapshot["criterialess_playlists"]:
        if CriteriaPlaylist.objects.filter(pk=row["pk"]).exists():
            continue
        playlist = CriteriaPlaylist(user_id=row["user_id"], type_id=row["type_id"], criteria=None)
        playlist.pk = row["pk"]
        playlist.uuid = row["uuid"]
        playlist.root_id = row["root_id"]
        playlist.save()
