"""Execute admitted images on the Docker daemon of a disposable hosted runner.

The runner is discarded after the job, so there is no private daemon, cgroup
slice or launcher trick: every container is offline, read-only, unprivileged and
labelled with the invocation, and is verified through `docker inspect` before and
after start. Each side is prepared once (restore, owner-run preparation, handoff)
and then PostgreSQL and the API restart on every round.

Approval creation belongs to operators and Grow. This adapter consumes the
manifest and a trusted runtime.json bound to the session identity; it cannot
approve anything itself.
"""

import hashlib
import http.client
import json
import os
import shutil
import stat
import subprocess
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .controller import Endpoint
from .database_handoff import (
    CANDIDATE_HBA,
    HANDOFF_SQL,
    OWNER_HBA,
    OWNER_LOCK_SQL,
    OWNERSHIP_SQL,
    PREPARATION_HBA,
    ROLE_PROOF_SQL,
)
from .manifest import RUNNER_PROFILES, Candidate, HostedSession, exact_keys, matching, positive_integer, trusted_json
from .reflink import clone_directory, require_reflink
from .restore_bundle import restore_approved, schema_bytes
from .scenario_execution import UnixHTTPConnection

ENVIRONMENT = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
DATA = "/var/lib/postgresql/data"
SOCKET = "/run/postgresql"
LABEL = "btmt.grow-perf.invocation"
Docker = Callable[..., str]


def system_docker(*arguments: str, stdin: str | None = None, timeout: int = 30) -> str:
    return subprocess.run(
        ["docker", *arguments],
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
        env=ENVIRONMENT,
    ).stdout.strip()


def process_namespace(pid: int) -> int:
    return Path(f"/proc/{pid}/ns/net").stat().st_ino


@dataclass(frozen=True)
class Image:
    identity: str
    uid: int


class HostedRuntime:
    def __init__(
        self,
        session: HostedSession,
        invocation: str,
        bundle: Path,
        workspace: Path,
        check: Callable[[], None],
        *,
        docker: Docker = system_docker,
        namespace: Callable[[int], int] = process_namespace,
        probe: Callable[[Path], None] = require_reflink,
        clone: Callable[[Path, Path, str], Path] = clone_directory,
    ):
        if not isinstance(session, HostedSession):
            raise ValueError("hosted runtime requires a hosted session")
        self.session, self.bundle, self.workspace, self.check = session, bundle, workspace, check
        self.invocation = matching(invocation, r"[0-9a-f]{32}", "controller invocation")
        self.docker_binary, self.namespace = docker, namespace
        self.probe, self.clone = probe, clone
        for path in (bundle, workspace):
            if any(character in str(path) for character in (",", "\n", "\r")):
                raise ValueError("Docker-safe paths required")
        approval = exact_keys(
            trusted_json(bundle / "runtime.json"),
            {"version", "identity", "postgres_uid", "base_uid", "head_uid", "memory", "cpus", "tasks", "routines"},
        )
        if type(approval["version"]) is not int or approval["version"] != 2 or approval["identity"] != session.identity:
            raise ValueError("runtime approval must bind the exact admitted session")
        cpus, gigabytes = RUNNER_PROFILES[session.runner]
        self.memory = positive_integer(approval["memory"], "container memory", 64 * 1024**2, gigabytes * 1024**3 // 4)
        self.cpus = positive_integer(approval["cpus"], "container CPUs", 1, cpus)
        self.tasks = positive_integer(approval["tasks"], "container tasks", 1, 4096)
        if not isinstance(approval["routines"], list) or len(approval["routines"]) > 256:
            raise ValueError("an explicit bounded routine approval list is required")
        self.routines = {}
        for raw in approval["routines"]:
            routine = exact_keys(raw, {"signature", "sha256"})
            signature = matching(routine["signature"], r"public\.[a-z_][a-z0-9_]*\([a-z_ ,\[\]]*\)", "approved routine")
            if signature in self.routines:
                raise ValueError("duplicate approved routine")
            self.routines[signature] = matching(routine["sha256"], r"[0-9a-f]{64}", "routine definition digest")
        uids = {
            key: positive_integer(approval[key + "_uid"], key + " UID", 1, 65535)
            for key in ("postgres", "base", "head")
        }
        self.artifacts = {}
        for filename, expected in (
            ("prepare.py", session.preparation.script_sha256),
            ("grow_perf_settings.py", session.preparation.settings_sha256),
        ):
            content = schema_bytes(bundle / filename)
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError("preparation artifact differs from the admitted manifest")
            self.artifacts[filename] = content
        self.postgres = self.resolve(session.postgres_image, uids["postgres"], postgres=True)
        self.images = {
            candidate: self.resolve(candidate.image, uids[side])
            for side, candidate in (("base", session.base), ("head", session.head))
        }
        self.sides: dict[Candidate, tuple[Path, Path]] = {}
        self.names: list[str] = []
        self.active = False
        self.cleanup_uncertain = False
        self.host_namespace = namespace(1)

    def docker(self, *arguments: str, timeout: int = 30, stdin: str | None = None) -> str:
        self.check()
        return self.docker_binary(*arguments, stdin=stdin, timeout=timeout)

    def resolve(self, reference: str, uid: int, *, postgres: bool = False) -> Image:
        """Bind a registry digest to a local image ID; containers then run by ID."""
        value = json.loads(self.docker("image", "inspect", reference))
        if not isinstance(value, list) or len(value) != 1:
            raise RuntimeError("image is not present locally")
        details = value[0]
        short = reference.removeprefix("docker.io/library/")
        if not {reference, short, reference.removeprefix("docker.io/")} & set(details.get("RepoDigests") or []):
            raise RuntimeError("local image was not pulled from the admitted digest")
        if set((details.get("Config") or {}).get("Volumes") or {}) - ({DATA} if postgres else set()):
            raise ValueError("image volumes are forbidden")
        return Image(matching(details.get("Id"), r"sha256:[0-9a-f]{64}", "local image ID"), uid)

    def remove(self, name: str) -> None:
        # A create timeout may leave the daemon processing it, so absence is
        # never proof: rm must succeed and the label listing must stay empty.
        self.docker_binary("rm", "--force", "--volumes", name, stdin=None, timeout=30)
        if self.docker_binary("ps", "--all", "--quiet", "--filter", f"name=^/{name}$", stdin=None, timeout=10):
            raise RuntimeError("container cleanup is unconfirmed")

    @contextmanager
    def container(
        self,
        image: Image,
        arguments: list[str],
        mounts: list[str],
        tmpfs: tuple[str, ...] = ("/tmp:rw,nosuid,nodev,noexec,size=32m",),
    ):
        name = "btmt-grow-perf-" + uuid.uuid4().hex
        self.names.append(name)
        try:
            identity = matching(
                self.docker(
                    "create",
                    "--pull=never",
                    "--name",
                    name,
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges:true",
                    "--memory",
                    str(self.memory),
                    "--memory-swap",
                    str(self.memory),
                    "--pids-limit",
                    str(self.tasks),
                    "--cpus",
                    str(self.cpus),
                    "--user",
                    f"{image.uid}:{image.uid}",
                    "--label",
                    f"{LABEL}={self.invocation}",
                    "--no-healthcheck",
                    *[argument for item in tmpfs for argument in ("--tmpfs", item)],
                    *mounts,
                    "--entrypoint",
                    "/usr/bin/env",
                    image.identity,
                    "-i",
                    "PATH=" + ENVIRONMENT["PATH"],
                    *arguments,
                ),
                r"[0-9a-f]{64}",
                "container ID",
            )
            self.verify_created(identity, image, mounts, tmpfs)
            self.docker("start", identity)
            details = self.inspect(identity)
            pid = positive_integer(details["State"]["Pid"], "container PID", 1, 2**31 - 1)
            if details["State"].get("Running") is not True:
                raise RuntimeError("container failed to start from the admitted image")
            if self.namespace(pid) == self.host_namespace:
                raise RuntimeError("container shares the host network namespace")
            yield identity
        finally:
            try:
                self.remove(name)
            except BaseException:
                self.cleanup_uncertain = True
                raise

    def inspect(self, identity: str) -> dict:
        value = json.loads(self.docker("inspect", identity))
        if not isinstance(value, list) or len(value) != 1:
            raise RuntimeError("container inspection failed")
        return value[0]

    def verify_created(self, identity: str, image: Image, mounts: list[str], tmpfs: tuple[str, ...]) -> None:
        details = self.inspect(identity)
        config, host = details.get("Config") or {}, details.get("HostConfig") or {}
        labels = config.get("Labels") or {}
        if (
            details.get("Image") != image.identity
            or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("PidMode") not in ("", None)
            or host.get("IpcMode") in ("host",)
            or host.get("Memory") != self.memory
            or host.get("MemorySwap") != self.memory
            or host.get("PidsLimit") != self.tasks
            or host.get("NanoCpus") != self.cpus * 10**9
            or config.get("User") != f"{image.uid}:{image.uid}"
            or labels.get(LABEL) != self.invocation
            or set(host.get("CapDrop") or []) != {"ALL"}
            or host.get("CapAdd")
            or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
            or set(host.get("Tmpfs") or {}) != {item.split(":", 1)[0] for item in tmpfs}
            or host.get("Binds")
            or host.get("Devices")
        ):
            raise RuntimeError("container isolation differs from the approved configuration")
        expected = {}
        for option, mount in zip(mounts[::2], mounts[1::2], strict=True):
            if option != "--mount":
                raise ValueError("explicit bind mounts required")
            fields = dict(item.split("=", 1) if "=" in item else (item, True) for item in mount.split(","))
            expected[fields["dst"]] = (fields["src"], not fields.get("readonly", False))
        actual = {
            item["Destination"]: (item["Source"], item["RW"])
            for item in details.get("Mounts", [])
            if item["Type"] == "bind"
        }
        if actual != expected or any(item["Type"] not in {"bind", "tmpfs"} for item in details.get("Mounts", [])):
            raise RuntimeError("container mounts differ from the approved configuration")

    def wait(self, identity: str, ready: Callable[[], bool], timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while not ready():
            if self.docker("inspect", "--format={{.State.Running}}", identity) != "true":
                raise RuntimeError("prepared service stopped before readiness")
            if time.monotonic() >= deadline:
                raise RuntimeError("prepared service readiness timed out")
            time.sleep(0.1)

    def finish(self, identity: str, timeout: float) -> int:
        """Poll so the run deadline is checked while a job executes."""
        deadline = time.monotonic() + timeout
        while self.docker("inspect", "--format={{.State.Running}}", identity) == "true":
            self.check()
            if time.monotonic() >= deadline:
                raise RuntimeError("container job timed out")
            time.sleep(0.5)
        return int(self.docker("inspect", "--format={{.State.ExitCode}}", identity))

    def sql(self, identity: str, user: str, database: str, query: str, *, root: bool = False) -> str:
        return self.docker(
            "exec",
            "--interactive",
            *(["--user", "0:0"] if root else []),
            identity,
            "/usr/bin/env",
            "-i",
            "PATH=" + ENVIRONMENT["PATH"],
            "psql",
            "-X",
            "-Atq",
            f"--host={SOCKET}",
            "--port=5432",
            "--username=" + user,
            "--dbname=" + database,
            "--set=ON_ERROR_STOP=1",
            stdin=query,
        )

    def database_ready(self, identity: str, user: str) -> bool:
        try:
            return self.sql(identity, user, "btmt_grow_perf", "SELECT 1") == "1"
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def write_artifact(path: Path, content: bytes) -> None:
        with path.open("xb") as output:
            output.write(content)
        path.chmod(0o444)

    def make_directory(self, parent: Path, name: str, uid: int, mode: int = 0o700) -> Path:
        path = parent / (name + "-" + uuid.uuid4().hex[:8])
        path.mkdir(mode=mode)
        os.chown(path, uid, uid)
        return path

    # ---- one-time per-side preparation -------------------------------------------------

    def restore(self, candidate: Candidate, root: Path) -> Path:
        """Restore as postgres into a fresh data directory, then hand it to the owner role."""
        data = self.make_directory(root, "data", self.postgres.uid)
        archive = self.bundle / "backup.dump"
        script = (
            f"initdb -D {DATA} --auth-local=trust --auth-host=reject -U postgres "
            f"&& exec postgres -D {DATA} -c listen_addresses='' "
            f"-c unix_socket_directories={SOCKET} -c unix_socket_permissions=0777"
        )
        mounts = [
            "--mount",
            f"type=bind,src={data},dst={DATA}",
            "--mount",
            f"type=bind,src={archive},dst=/restore/backup.dump,readonly",
        ]
        tmpfs = (
            f"{SOCKET}:rw,nosuid,nodev,noexec,size=1m,uid={self.postgres.uid},gid={self.postgres.uid},mode=0711",
            "/tmp:rw,nosuid,nodev,noexec,size=16m",
        )
        with self.container(self.postgres, ["/bin/sh", "-ec", script], mounts, tmpfs) as identity:
            transport = _Transport(self, identity)
            self.wait(identity, lambda: self.pg_ready(identity))
            if not 160000 <= int(self.sql(identity, "postgres", "postgres", "SHOW server_version_num")) < 170000:
                raise RuntimeError("admitted image must run PostgreSQL 16")
            self.sql(identity, "postgres", "postgres", "CREATE DATABASE btmt_grow_perf TEMPLATE template0;")
            restore_approved(transport, self.session, self.bundle)
            self.sql(identity, "postgres", "btmt_grow_perf", OWNERSHIP_SQL)
            self.docker("stop", "--time", "60", identity, timeout=90)
            if self.finish(identity, 60) != 0:
                raise RuntimeError("restore database did not shut down cleanly")
        return data

    def pg_ready(self, identity: str) -> bool:
        try:
            return self.sql(identity, "postgres", "postgres", "SELECT 1") == "1"
        except subprocess.CalledProcessError:
            return False

    @contextmanager
    def database(self, data: Path, authentication: str, user: str, *, graceful: bool = False):
        if authentication not in {OWNER_HBA, PREPARATION_HBA, CANDIDATE_HBA}:
            raise ValueError("approved database authentication required")
        directory = self.make_directory(data.parent, "socket", self.postgres.uid, 0o755)
        hba = data.parent / ("hba-" + uuid.uuid4().hex)
        self.write_artifact(hba, authentication.encode())
        mounts = [
            "--mount",
            f"type=bind,src={data},dst={DATA}",
            "--mount",
            f"type=bind,src={directory},dst={SOCKET}",
            "--mount",
            f"type=bind,src={hba},dst=/approved/pg_hba.conf,readonly",
        ]
        arguments = [
            "postgres",
            "-D",
            DATA,
            "-c",
            "listen_addresses=",
            "-c",
            f"unix_socket_directories={SOCKET}",
            "-c",
            "unix_socket_permissions=0777",
            "-c",
            "hba_file=/approved/pg_hba.conf",
        ]
        with self.container(self.postgres, arguments, mounts) as identity:
            self.wait(identity, lambda: self.database_ready(identity, user))
            yield directory, identity
            if graceful:
                # `docker rm --force` kills the server mid-state; a clone needs a checkpointed, pid-free directory.
                self.docker("stop", "--time", "60", identity, timeout=90)
                if self.finish(identity, 60) != 0:
                    raise RuntimeError("prepared database did not shut down cleanly")

    def prepare_application(self, candidate: Candidate, socket: Path, scripts: Path) -> None:
        mounts = [
            "--mount",
            f"type=bind,src={socket},dst={SOCKET}",
            "--mount",
            f"type=bind,src={scripts}/prepare.py,dst=/approved/prepare.py,readonly",
            "--mount",
            f"type=bind,src={scripts}/grow_perf_settings.py,dst=/approved/grow_perf_settings.py,readonly",
        ]
        arguments = [*self.environment("grow_perf_owner"), "python3", "/approved/prepare.py"]
        with self.container(self.images[candidate], arguments, mounts) as identity:
            # A stale projection is rebuilt for hours: only the manifest deadline bounds the job (cause "deadline").
            if self.finish(identity, max(self.session.deadline_timestamp - time.time(), 0)) != 0:
                raise RuntimeError("approved migration/rebuild preparation failed")

    def approve_routines(self, identity: str) -> None:
        for signature, expected in self.routines.items():
            definition = self.sql(
                identity,
                "postgres",
                "btmt_grow_perf",
                "SET search_path=pg_catalog; SELECT pg_get_functiondef('" + signature + "'::regprocedure)",
            )
            if hashlib.sha256(definition.encode()).hexdigest() != expected:
                raise ValueError("routine definition differs from independent approval")
            self.sql(
                identity, "postgres", "btmt_grow_perf", "GRANT EXECUTE ON FUNCTION " + signature + " TO grow_perf_app"
            )

    def prepare_side(self, candidate: Candidate) -> tuple[Path, Path]:
        self.probe(self.workspace)
        root = self.workspace / ("s-" + uuid.uuid4().hex[:8])
        root.mkdir(mode=0o700)
        data = self.restore(candidate, root)
        scripts = root / "approved"
        scripts.mkdir(mode=0o755)
        for filename, content in self.artifacts.items():
            self.write_artifact(scripts / filename, content)
        # Preparation code from the side's own image never sees postgres or the archive.
        with self.database(data, OWNER_HBA, "grow_perf_owner") as (socket, _identity):
            self.prepare_application(candidate, socket, scripts)
        with self.database(data, PREPARATION_HBA, "postgres", graceful=True) as (_socket, identity):
            self.sql(identity, "postgres", "btmt_grow_perf", OWNER_LOCK_SQL)
            self.sql(identity, "postgres", "btmt_grow_perf", HANDOFF_SQL)
            self.approve_routines(identity)
        return data, scripts

    # ---- per-round execution -------------------------------------------------------------

    @contextmanager
    def prepare(self, candidate: Candidate, number: int):
        positive_integer(number, "benchmark round", 1, self.session.rounds)
        if candidate not in self.images or self.active or self.cleanup_uncertain:
            raise ValueError("only one admitted candidate can execute at a time")
        self.active = True
        try:
            if candidate not in self.sides:
                self.sides[candidate] = self.prepare_side(candidate)
            pristine, scripts = self.sides[candidate]
            # Every round runs on its own clone, so earlier rounds' writes and caches never leak into this one.
            data = self.clone(pristine, scripts.parent, "round")
            try:
                # A fresh server parses the restrictive HBA before the API gets its socket.
                with self.database(data, CANDIDATE_HBA, "grow_perf_app") as (socket, identity):
                    self.verify_handoff(identity)
                    yield from self.serve(candidate, socket, scripts)
            finally:
                try:
                    shutil.rmtree(data)
                except OSError:
                    self.cleanup_uncertain = True
                    raise
        finally:
            self.active = False

    def verify_handoff(self, identity: str) -> None:
        if self.sql(identity, "grow_perf_app", "btmt_grow_perf", ROLE_PROOF_SQL) != "t":
            raise RuntimeError("candidate database role has unexpected privileges")
        for user, database in (
            ("postgres", "btmt_grow_perf"),
            ("grow_perf_owner", "btmt_grow_perf"),
            ("grow_perf_app", "postgres"),
        ):
            try:
                self.sql(identity, user, database, "SELECT 1")
            except subprocess.CalledProcessError as error:
                if "pg_hba.conf rejects connection" not in (error.stderr or ""):
                    raise RuntimeError("database rejection did not prove active HBA") from error
            else:
                raise RuntimeError("candidate database accepted a forbidden identity")

    @staticmethod
    def environment(user: str) -> list[str]:
        return [
            "PATH=/home/app/.venv/bin:" + ENVIRONMENT["PATH"],
            "PYTHONPATH=/approved:/home/app",
            "DJANGO_SETTINGS_MODULE=grow_perf_settings",
            f"DATABASE_URL=postgres://{user}@/btmt_grow_perf?host={SOCKET}",
        ]

    def serve(self, candidate: Candidate, database: Path, scripts: Path):
        image = self.images[candidate]
        directory = self.make_directory(scripts.parent, "http", image.uid)
        path = directory / "api.sock"
        if len(str(path).encode()) > 103:
            raise ValueError("workspace path is too long for the HTTP Unix socket")
        mounts = [
            "--mount",
            f"type=bind,src={database},dst={SOCKET},readonly",
            "--mount",
            f"type=bind,src={directory},dst=/http",
            "--mount",
            f"type=bind,src={scripts}/grow_perf_settings.py,dst=/approved/grow_perf_settings.py,readonly",
        ]
        arguments = [
            *self.environment("grow_perf_app"),
            "gunicorn",
            "grow.wsgi:application",
            "--chdir=/home/app",
            "--bind=unix:/http/api.sock",
            "--workers=1",
            "--threads=1",
            "--timeout=120",
            "--access-logfile=/dev/null",
            "--error-logfile=/dev/null",
        ]
        with self.container(image, arguments, mounts) as identity:
            self.wait(identity, lambda: self.http_ready(path))
            yield Endpoint("127.0.0.1", 1, path)

    @staticmethod
    def http_ready(path: Path) -> bool:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISSOCK(info.st_mode):
            raise ValueError("Unix HTTP endpoint must be a socket, without symlinks")
        connection = UnixHTTPConnection(path, 1)
        try:
            connection.request("HEAD", "/", headers={"Host": "grow-perf.invalid"})
            return 200 <= connection.getresponse().status < 500
        except OSError, http.client.HTTPException:
            return False
        finally:
            connection.close()

    def close(self) -> None:
        """Prove no labelled container survives, then drop all prepared data."""
        try:
            for name in self.names:
                self.docker_binary("rm", "--force", "--volumes", name, stdin=None, timeout=30)
        except subprocess.CalledProcessError:
            # rm of an already removed name is expected; the listing below is the proof.
            pass
        remaining = self.docker_binary(
            "ps", "--all", "--quiet", "--filter", f"label={LABEL}={self.invocation}", stdin=None, timeout=10
        )
        if remaining:
            self.cleanup_uncertain = True
            raise RuntimeError("labelled containers survived cleanup")
        shutil.rmtree(self.workspace, ignore_errors=False)


class _Transport:
    """Restore transport: trusted utilities exec'd in the preparation PostgreSQL."""

    def __init__(self, runtime: HostedRuntime, identity: str):
        self.runtime, self.identity = runtime, identity

    def run(self, program: str, arguments: list[str], stdin: str | None = None) -> str:
        if program not in {"psql", "pg_restore", "sha256sum"}:
            raise ValueError("unapproved restore utility")
        endpoint = [] if program == "sha256sum" else [f"--host={SOCKET}", "--port=5432", "--username=postgres"]
        if program == "pg_restore" and "--list" in arguments:
            endpoint = []
        # Root reads the private archive; the server stays an unprivileged UID.
        return self.runtime.docker(
            "exec",
            "--interactive",
            "--user",
            "0:0",
            self.identity,
            "/usr/bin/env",
            "-i",
            "PATH=" + ENVIRONMENT["PATH"],
            program,
            *endpoint,
            *arguments,
            stdin=stdin,
            timeout=6 * 60 * 60,
        )
