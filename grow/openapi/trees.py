from copy import deepcopy
from typing import Any

from django.conf import settings
from the_music_tree_genre_kit.criteria.children.genre.CriteriaScene import CriteriaScene
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_node import OVERVIEW_TYPES

from grow.openapi.documents import component_ref


def tree_import_components(components: dict[str, Any]) -> dict[str, Any]:
    # The HTTP serializer accepts older and manually assembled trees as well as Gold exports.
    tree = deepcopy(components["GenreTree"])
    tree["required"].remove("curationExportedOn")
    tree["properties"]["tree"].update(items=component_ref("GenreTreeImportNode"), minItems=1)
    tree["properties"]["crossTreeSecondaryParents"]["items"]["properties"]["secondaryParents"] = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "minItems": 1,
    }
    tree["description"] = "Pipeline imports require curationExportedOn."

    node = deepcopy(components["GenreTree_node"])
    node["required"] = ["name"]
    properties = node["properties"]
    properties["name"]["maxLength"] = settings.CRITERIA_NAME_LEN_MAX
    properties["children"].update(type=["array", "null"], items=component_ref("GenreTreeImportNode"))
    properties["id"].update(type=["string", "null"], pattern=r"^(Q\d+|LOCAL:[a-z0-9-]+)$")
    properties["side"] = {"enum": [*CriteriaSide.values, None]}
    properties["scene"] = {"enum": [*CriteriaScene.values, None]}
    properties["overviewType"] = {"enum": [*OVERVIEW_TYPES, None]}
    for key in ("isUnacceptedRoot", "isUmbrella"):
        properties[key] = {"type": "boolean", "default": False}
    for key in ("summary", "description"):
        properties[key] = {"type": ["string", "null"]}
    properties["summarySourceUrl"] = {
        "anyOf": [
            {"type": "null"},
            {"const": ""},
            {"type": "string", "format": "uri", "pattern": "^https?://", "maxLength": 500},
        ]
    }
    for key in ("primaryParents", "secondaryParents"):
        properties[key] = {"type": "array", "items": {"type": "string", "minLength": 1}}
    properties["image"].update(type=["object", "null"], required=["url", "pageUrl", "license"])
    return {"GenreTreeImport": tree, "GenreTreeImportNode": node}
