"""Validate operator-approved benchmark identities without trusting PR inputs."""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = "BehindTheMusicTree/grow-the-music-tree-api"
RUNNER_PROFILES = {"4cpu-16gb": (4, 16), "8cpu-32gb": (8, 32)}


def exact_keys(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or value.keys() != keys:
        raise ValueError(f"expected exactly these keys: {sorted(keys)}")
    return value


def matching(value: object, pattern: str, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(f"invalid {name}")
    return value


def positive_integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def trusted_json(path: Path, *, owner: int = 0, maximum_bytes: int = 65536) -> dict:
    """Reject writable parents, symlinks and oversized manifests before parsing."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("manifest path must be canonical and absolute")
    for parent in (path, *path.parents):
        info = parent.lstat()
        if info.st_uid != owner or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError("manifest and ancestors must be exclusively operator writable")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "r") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size > maximum_bytes
            or info.st_uid != owner
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or info.st_nlink != 1
        ):
            raise ValueError(f"trusted JSON must be a regular file of at most {maximum_bytes} bytes")
        value = json.load(source, object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    return value


@dataclass(frozen=True)
class Candidate:
    sha: str
    image: str

    @classmethod
    def parse(cls, raw: object) -> Candidate:
        value = exact_keys(raw, {"sha", "image"})
        return cls(
            matching(value["sha"], r"[0-9a-f]{40}", "commit SHA"),
            matching(
                value["image"],
                r"ghcr\.io/behindthemusictree/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}",
                "immutable candidate image",
            ),
        )


@dataclass(frozen=True)
class Session:
    repository: str
    pull_request: int
    base: Candidate
    head: Candidate
    backup_sha256: str
    scenario_sha256: str
    rounds: int

    @classmethod
    def parse(cls, raw: object) -> Session:
        if isinstance(raw, dict) and type(raw.get("version")) is int and raw["version"] == 2:
            return HostedSession.parse_hosted(raw)
        value = exact_keys(
            raw, {"version", "repository", "pull_request", "base", "head", "backup_sha256", "scenario_sha256", "rounds"}
        )
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported manifest version")
        if value["repository"] != REPOSITORY:
            raise ValueError("repository is not admitted")
        return Session(
            value["repository"],
            positive_integer(value["pull_request"], "pull request", 1, 2**31 - 1),
            Candidate.parse(value["base"]),
            Candidate.parse(value["head"]),
            matching(value["backup_sha256"], r"[0-9a-f]{64}", "backup digest"),
            matching(value["scenario_sha256"], r"[0-9a-f]{64}", "scenario digest"),
            positive_integer(value["rounds"], "round count", 4, 12),
        )

    @property
    def identity(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()

    def as_dict(self) -> dict:
        return {
            "version": 1,
            "repository": self.repository,
            "pull_request": self.pull_request,
            "base": {"sha": self.base.sha, "image": self.base.image},
            "head": {"sha": self.head.sha, "image": self.head.image},
            "backup_sha256": self.backup_sha256,
            "scenario_sha256": self.scenario_sha256,
            "rounds": self.rounds,
        }

    def schedule(self) -> list[tuple[str, int]]:
        return [
            (side, number)
            for number in range(1, self.rounds + 1)
            for side in (("base", "head") if number % 2 else ("head", "base"))
        ]


@dataclass(frozen=True)
class Preparation:
    version: int
    script_sha256: str
    settings_sha256: str

    @classmethod
    def parse(cls, raw: object) -> Preparation:
        value = exact_keys(raw, {"version", "script_sha256", "settings_sha256"})
        return cls(
            positive_integer(value["version"], "preparation version", 1, 2**31 - 1),
            matching(value["script_sha256"], r"[0-9a-f]{64}", "preparation script digest"),
            matching(value["settings_sha256"], r"[0-9a-f]{64}", "preparation settings digest"),
        )


@dataclass(frozen=True)
class HostedSession(Session):
    """Disposable hosted-runner session; head.sha is the PR merge commit.

    backup_sha256 holds the sanitized catalogue export digest. The deadline is
    an absolute UTC instant after which no measurement may still be accepted.
    """

    policy_sha256: str
    postgres_image: str
    preparation: Preparation
    runner: str
    deadline: str

    @classmethod
    def parse_hosted(cls, raw: object) -> HostedSession:
        value = exact_keys(
            raw,
            {
                "version",
                "repository",
                "pull_request",
                "base",
                "head",
                "catalogue_sha256",
                "scenario_sha256",
                "policy_sha256",
                "postgres_image",
                "preparation",
                "runner",
                "deadline",
                "rounds",
            },
        )
        if value["repository"] != REPOSITORY:
            raise ValueError("repository is not admitted")
        if value["runner"] not in RUNNER_PROFILES:
            raise ValueError("runner profile is not admitted")
        deadline = matching(value["deadline"], r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", "deadline")
        datetime.strptime(deadline, "%Y-%m-%dT%H:%M:%SZ")  # noqa: DTZ007 - format validation only, the value is discarded
        session = cls(
            value["repository"],
            positive_integer(value["pull_request"], "pull request", 1, 2**31 - 1),
            Candidate.parse(value["base"]),
            Candidate.parse(value["head"]),
            matching(value["catalogue_sha256"], r"[0-9a-f]{64}", "catalogue digest"),
            matching(value["scenario_sha256"], r"[0-9a-f]{64}", "scenario digest"),
            positive_integer(value["rounds"], "round count", 4, 12),
            matching(value["policy_sha256"], r"[0-9a-f]{64}", "policy digest"),
            matching(
                value["postgres_image"],
                r"docker\.io/library/postgres@sha256:[0-9a-f]{64}",
                "immutable PostgreSQL image",
            ),
            Preparation.parse(value["preparation"]),
            value["runner"],
            deadline,
        )
        if session.base.sha == session.head.sha:
            raise ValueError("base and merge commits must differ")
        return session

    @property
    def deadline_timestamp(self) -> float:
        return datetime.strptime(self.deadline, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()

    def as_dict(self) -> dict:
        return {
            "version": 2,
            "repository": self.repository,
            "pull_request": self.pull_request,
            "base": {"sha": self.base.sha, "image": self.base.image},
            "head": {"sha": self.head.sha, "image": self.head.image},
            "catalogue_sha256": self.backup_sha256,
            "scenario_sha256": self.scenario_sha256,
            "policy_sha256": self.policy_sha256,
            "postgres_image": self.postgres_image,
            "preparation": {
                "version": self.preparation.version,
                "script_sha256": self.preparation.script_sha256,
                "settings_sha256": self.preparation.settings_sha256,
            },
            "runner": self.runner,
            "deadline": self.deadline,
            "rounds": self.rounds,
        }
