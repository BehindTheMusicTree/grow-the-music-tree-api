from grow.management.commands.reset_catalogue import (
    CATALOGUE_APPS,
    KEEP_TABLES,
    PARTIAL_TABLES,
    USER_DATA_CHECKS,
    catalogue_tables,
    wiped_tables,
)


def test_kept_and_partial_tables_exist_in_the_registry():
    tables = set(catalogue_tables())
    assert tables >= KEEP_TABLES
    assert tables >= PARTIAL_TABLES
    assert not KEEP_TABLES & PARTIAL_TABLES


def test_every_catalogue_table_is_kept_or_wiped():
    assert sorted(set(wiped_tables()) | KEEP_TABLES) == catalogue_tables()
    assert not set(wiped_tables()) & KEEP_TABLES


def test_partial_tables_are_truncated_then_restored():
    assert set(wiped_tables()) >= PARTIAL_TABLES


def test_wiped_tables_have_no_duplicates_and_skip_other_apps():
    wiped = wiped_tables()
    assert len(wiped) == len(set(wiped))
    assert not [t for t in wiped if t.startswith(("django_", "auth_"))]
    assert CATALOGUE_APPS == ("grow", "the_music_tree_genre_kit")


def test_user_data_checks_target_wiped_tables():
    assert "grow_play" in wiped_tables()
    assert len(USER_DATA_CHECKS) == 7
