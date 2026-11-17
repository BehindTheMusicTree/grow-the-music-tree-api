"""Bind offline local image IDs to independently installed registry manifests."""

import hashlib
import json
from pathlib import Path

from .manifest import _unique_pairs, exact_keys, matching, positive_integer
from .restore_bundle import schema_bytes

DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
CONFIG_TYPES = {
    DOCKER_MANIFEST: "application/vnd.docker.container.image.v1+json",
    OCI_MANIFEST: "application/vnd.oci.image.config.v1+json",
}
LAYER_TYPES = {
    DOCKER_MANIFEST: {"application/vnd.docker.image.rootfs.diff.tar.gzip"},
    OCI_MANIFEST: {
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.oci.image.layer.v1.tar+gzip",
        "application/vnd.oci.image.layer.v1.tar+zstd",
    },
}


def verify_manifest(path: Path, repository_image: str, local_image: str) -> None:
    """No reserialization: the admitted digest identifies exact registry bytes.

    The operator must separately approve builder/SHA evidence. This proves the
    registry digest/config-ID link, not who built or reviewed the image.
    """
    content = schema_bytes(path)
    if len(content) > 65536:
        raise ValueError("registry manifest exceeds 64 KiB")
    if "sha256:" + hashlib.sha256(content).hexdigest() != repository_image.rsplit("@", 1)[-1]:
        raise ValueError("registry manifest differs from admitted digest")
    value = json.loads(content, object_pairs_hook=_unique_pairs)
    keys = {"schemaVersion", "mediaType", "config", "layers"}
    if isinstance(value, dict) and "annotations" in value:
        keys.add("annotations")
        annotations = value["annotations"]
        if not isinstance(annotations, dict) or any(
            not isinstance(key, str) or not isinstance(item, str) for key, item in annotations.items()
        ):
            raise ValueError("registry annotations must be a string map")
    exact_keys(value, keys)
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 2:
        raise ValueError("registry manifest schemaVersion must be 2")
    media_type = value["mediaType"]
    if not isinstance(media_type, str) or media_type not in CONFIG_TYPES:
        raise ValueError("single-platform Docker or OCI image manifest required; indexes are forbidden")
    config = exact_keys(value["config"], {"mediaType", "digest", "size"})
    if config["mediaType"] != CONFIG_TYPES[media_type] or config["digest"] != local_image:
        raise ValueError("registry config differs from approved local image")
    positive_integer(config["size"], "image config size", 1, 16 * 1024**2)
    if not isinstance(value["layers"], list) or len(value["layers"]) > 256:
        raise ValueError("bounded image layer list required")
    for raw in value["layers"]:
        layer = exact_keys(raw, {"mediaType", "digest", "size"})
        if not isinstance(layer["mediaType"], str) or layer["mediaType"] not in LAYER_TYPES[media_type]:
            raise ValueError("unsupported image layer media type")
        matching(layer["digest"], r"sha256:[0-9a-f]{64}", "image layer digest")
        positive_integer(layer["size"], "image layer size", 1, 1024**4)
