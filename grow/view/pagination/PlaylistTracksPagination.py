from django.core.paginator import Paginator
from django.db.models import F, Subquery
from django.utils.functional import cached_property
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.query_expressions import InSubquery
from grow.serializer.model.track_playlist_rel.output.in_page import TrackPlaylistRelInPageSerializer


class _MembershipPaginator(Paginator):
    def __init__(self, *args, known_count=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.known_count = known_count

    @cached_property
    def count(self):
        return super().count if self.known_count is None else self.known_count

    def _get_page(self, object_list, number, paginator):
        # Select the bounded membership page before joining the song/album/genre graphs.
        # Without this LIMIT boundary PostgreSQL can hydrate the entire catalogue first.
        ids = object_list.prefetch_related(None).values("pk")
        page = TrackPlaylistRel.objects.using(object_list.db).filter(InSubquery(F("pk"), Subquery(ids)))
        page = TrackPlaylistRelInPageSerializer.setup_queryset(page).order_by(F("position").asc(nulls_last=True), "pk")
        return super()._get_page(page, number, paginator)


class PlaylistTracksPagination(AppPagination):
    django_paginator_class = _MembershipPaginator

    def paginate_queryset(self, queryset, request, view=None):
        # A view that can total its list from precomputed counts spares the COUNT over every member.
        known_count = view.get_tracks_count() if hasattr(view, "get_tracks_count") else None
        self.django_paginator_class = lambda *args, **kwargs: _MembershipPaginator(
            *args, known_count=known_count, **kwargs
        )
        return super().paginate_queryset(queryset, request, view)
