from copy import deepcopy
from typing import Any

from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import AppModelViewSet

from grow.openapi.documents import DOCUMENTS, GROW_DOCUMENTS, adapt_document
from grow.openapi.regions import region_map_import_row, region_map_paths


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


def _add_unique(target: dict, entries: dict) -> None:
    if overlap := target.keys() & entries.keys():
        raise ValueError(f"OpenAPI name collision: {sorted(overlap)}")
    target.update(entries)


def embed_wire_contracts(result: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    # The kit's paginator still produces nullable links in OpenAPI 3.0 form.
    def update_pagination(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("nullable") is True and node.get("type") == "string" and node.get("format") == "uri":
                node.pop("nullable")
                node["type"] = ["string", "null"]
            for value in node.values():
                update_pagination(value)
        elif isinstance(node, list):
            for value in node:
                update_pagination(value)

    update_pagination(result)
    components = result.setdefault("components", {}).setdefault("schemas", {})
    for name, load in DOCUMENTS.items():
        _add_unique(components, adapt_document(name, load()))

    tree = deepcopy(components["GenreTree"])
    tree["required"].remove("curationExportedOn")
    tree["properties"]["tree"]["minItems"] = 1
    tree["description"] = "Pipeline imports require curationExportedOn. It is optional for other callers."
    _add_unique(components, {"GenreTreeImport": tree, "RegionMapImportRow": region_map_import_row(GROW_DOCUMENTS)})
    _add_unique(result["paths"], region_map_paths())
    for path in result["paths"].values():
        for operation in path.values():
            if not isinstance(operation, dict):
                continue
            if operation.pop("x-grow-required-body", False):
                operation["requestBody"]["required"] = True
            if "x-ndjson-item-schema" in operation:
                media = operation["requestBody"]["content"]["application/x-ndjson"]
                _add_unique(media, {"x-ndjson-item-schema": operation.pop("x-ndjson-item-schema")})
    return result
