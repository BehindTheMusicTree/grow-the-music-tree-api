"""Reject substituted, ambiguous and unsupported offline image provenance."""

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.catalogue.registry_image import CONFIG_TYPES, DOCKER_MANIFEST, OCI_MANIFEST, verify_manifest


class RegistryImageTest(unittest.TestCase):
    def setUp(self):
        self.path = Path("/approved/base.manifest.json")
        self.image = "sha256:" + "a" * 64
        self.value = {
            "schemaVersion": 2,
            "mediaType": DOCKER_MANIFEST,
            "config": {"mediaType": CONFIG_TYPES[DOCKER_MANIFEST], "digest": self.image, "size": 100},
            "layers": [
                {
                    "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    "digest": "sha256:" + "b" * 64,
                    "size": 1000,
                }
            ],
        }

    def verify(self, content, *, digest=None, image=None):
        digest = digest or hashlib.sha256(content).hexdigest()
        with patch("benchmarks.catalogue.registry_image.schema_bytes", return_value=content) as read:
            verify_manifest(self.path, "ghcr.io/behindthemusictree/grow@sha256:" + digest, image or self.image)
        read.assert_called_once_with(self.path)

    def test_exact_docker_and_oci_single_platform_config_bindings(self):
        self.verify(json.dumps(self.value, indent=2).encode())
        self.value["mediaType"] = OCI_MANIFEST
        self.value["config"]["mediaType"] = CONFIG_TYPES[OCI_MANIFEST]
        self.value["layers"][0]["mediaType"] = "application/vnd.oci.image.layer.v1.tar+gzip"
        self.value["annotations"] = {"org.opencontainers.image.title": "fixture"}
        self.verify(json.dumps(self.value).encode())

    def test_exact_bytes_tampering_and_wrong_local_config_are_rejected(self):
        content = json.dumps(self.value).encode()
        with self.assertRaisesRegex(ValueError, "admitted digest"):
            self.verify(content + b"\n", digest=hashlib.sha256(content).hexdigest())
        with self.assertRaisesRegex(ValueError, "approved local image"):
            self.verify(content, image="sha256:" + "c" * 64)

    def test_duplicate_json_keys_at_every_level_are_rejected(self):
        content = json.dumps(self.value).encode()
        for needle, replacement in (
            (b'"schemaVersion": 2', b'"schemaVersion": 1, "schemaVersion": 2'),
            (b'"size": 100}', b'"size": 1, "size": 100}'),
            (b'"size": 1000', b'"size": 1, "size": 1000'),
        ):
            with self.subTest(needle=needle), self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                self.verify(content.replace(needle, replacement))

    def test_malformed_descriptors_and_manifest_types_are_rejected(self):
        for location, key, invalid in (
            ((), "schemaVersion", True),
            ((), "mediaType", "application/vnd.oci.image.index.v1+json"),
            ((), "mediaType", "application/vnd.docker.distribution.manifest.list.v2+json"),
            ((), "mediaType", {}),
            ((), "layers", {}),
            ((), "layers", [{}] * 257),
            ((), "annotations", {"invalid": True}),
            (("config",), "mediaType", "application/octet-stream"),
            (("config",), "digest", "sha256:" + "c" * 64),
            (("config",), "size", True),
            (("config",), "size", 0),
            (("layers", 0), "digest", "invalid"),
            (("layers", 0), "size", -1),
            (("layers", 0), "mediaType", "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip"),
            (("layers", 0), "urls", ["https://example.invalid/layer"]),
        ):
            value = copy.deepcopy(self.value)
            target = value
            for step in location:
                target = target[step]
            target[key] = invalid
            with self.subTest(location=location, key=key, invalid=invalid), self.assertRaises(ValueError):
                self.verify(json.dumps(value).encode())
        for content in (b"[]", b"{", b" " * 65537):
            with self.subTest(content=content[:20]), self.assertRaises(ValueError):
                self.verify(content)

    def test_untrusted_manifest_is_not_parsed(self):
        with (
            patch("benchmarks.catalogue.registry_image.schema_bytes", side_effect=ValueError("private root-owned")),
            self.assertRaisesRegex(ValueError, "private root-owned"),
        ):
            verify_manifest(self.path, "untrusted", self.image)
