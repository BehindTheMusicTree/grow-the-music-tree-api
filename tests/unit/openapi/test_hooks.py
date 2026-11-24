from types import SimpleNamespace

from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import AppModelViewSet

from grow.openapi.hooks import drop_unimplemented_actions


def _endpoint(view_cls: type, method: str, action: str) -> tuple:
    return ("/x/", "^x/$", method, SimpleNamespace(cls=view_cls, actions={method.lower(): action}))


class _PartialOnly(AppModelViewSet):
    def partial_update(self, request, *args, **kwargs):
        raise NotImplementedError


class _UpdateOnly(AppModelViewSet):
    def update(self, request, *args, **kwargs):
        raise NotImplementedError


def _kept(view_cls: type) -> set[str]:
    endpoints = [_endpoint(view_cls, "PUT", "update"), _endpoint(view_cls, "PATCH", "partial_update")]
    return {method for _path, _regex, method, _callback in drop_unimplemented_actions(endpoints)}


def test_inherited_update_and_partial_update_are_dropped():
    assert _kept(AppModelViewSet) == set()


def test_standalone_partial_update_keeps_patch_only():
    assert _kept(_PartialOnly) == {"PATCH"}


def test_overridden_update_keeps_the_delegating_patch():
    assert _kept(_UpdateOnly) == {"PUT", "PATCH"}
