from typing import Any

from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import AppModelViewSet


def _is_inherited(view_cls: type, name: str) -> bool:
    inherited = getattr(AppModelViewSet, name, None)
    return inherited is not None and getattr(view_cls, name, None) is inherited


def _is_unimplemented(view_cls: type, action: str) -> bool:
    if action == "partial_update":
        # The inherited partial_update delegates to update; a view may also implement partial_update alone.
        return _is_inherited(view_cls, "partial_update") and _is_inherited(view_cls, "update")
    return _is_inherited(view_cls, action)


def drop_unimplemented_actions(endpoints: list[tuple[Any, ...]], **kwargs: Any) -> list[tuple[Any, ...]]:
    """
    Removes the operations AppModelViewSet routes but answers with 405 (the kit's ModelViewSet defaults), so the
    schema lists only what a resource implements.
    """
    kept = []
    for endpoint in endpoints:
        _path, _path_regex, method, callback = endpoint
        view_cls = getattr(callback, "cls", None)
        action = getattr(callback, "actions", {}).get(method.lower())
        if view_cls is not None and issubclass(view_cls, AppModelViewSet) and action is not None:
            if _is_unimplemented(view_cls, action):
                continue
        kept.append(endpoint)
    return kept
