from django.core.paginator import Paginator
from django.db.models import F, Subquery
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.query_expressions import InSubquery
from grow.serializer.model.track_playlist_rel.output.in_page import TrackPlaylistRelInPageSerializer


class _MembershipPaginator(Paginator):
    def _get_page(self, object_list, number, paginator):
        # Select the bounded membership page before joining the song/album/genre graphs.
        # Without this LIMIT boundary PostgreSQL can hydrate the entire catalogue first.
        ids = object_list.prefetch_related(None).values("pk")
        page = TrackPlaylistRel.objects.using(object_list.db).filter(InSubquery(F("pk"), Subquery(ids)))
        page = TrackPlaylistRelInPageSerializer.setup_queryset(page).order_by(F("position").asc(nulls_last=True), "pk")
        return super()._get_page(page, number, paginator)


class PlaylistTracksPagination(AppPagination):
    django_paginator_class = _MembershipPaginator
