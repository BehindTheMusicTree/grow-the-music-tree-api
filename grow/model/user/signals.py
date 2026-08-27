from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from the_music_tree_genre_kit.criteria.playlist.bootstrap_criterialess_playlists_for_user import (
    bootstrap_criterialess_playlists_for_user,
)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_criterialess_playlists(sender, instance, created, raw, **kwargs):
    # Raw saves (fixture/serialized_rollback loading) don't guarantee CriteriaType rows
    # are loaded yet; bootstrapping is only meaningful for real, ORM-driven user creation.
    if created and not raw:
        from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

        bootstrap_criterialess_playlists_for_user(user=instance, criteria_playlist_model=CriteriaPlaylist)
